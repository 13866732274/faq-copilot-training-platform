"""
Bot Webhook API — OpenClaw 消息网关回调端点。

OpenClaw 收到微信消息后 POST 到此端点，服务器完成：
  合规拦截 → FAQ 检索 → LLM 推荐回复 → 返回给 OpenClaw 发送。

认证方式：X-Bot-Secret 共享密钥（不走 JWT），在系统设置中配置。
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.faq_copilot_log import FaqCopilotLog
from app.services.faq_llm import copilot_answer, get_single_embedding
from app.services.faq_pipeline import semantic_search

router = APIRouter()
logger = logging.getLogger("chattrainer.bot_webhook")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  默认配置（可通过系统设置覆盖）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CONF_AUTO_THRESHOLD = 0.65
CONF_HUMAN_THRESHOLD = 0.35

SENSITIVE_KEYWORDS: list[str] = [
    "吃什么药", "吃啥药", "怎么用药", "开药", "处方", "药物",
    "要不要手术", "手术风险", "能治好吗", "严重吗", "会死吗",
    "诊断", "确诊", "病因", "化验单", "报告单",
]

SKIP_WORDS: set[str] = {
    "嗯", "哦", "好", "好的", "ok", "OK", "谢谢", "感谢",
    "拜拜", "再见", "👍", "嗯嗯", "收到",
}

BLOCK_WORDS: list[str] = ["转账", "付款", "红包", "借钱"]

DISCLAIMER = (
    "您好，我是智能助手，以下回复仅供参考，不构成医疗诊断。"
    "具体情况请到院面诊，由专业医生为您详细评估。\n\n"
)

OFF_HOURS_REPLY = "您好，您的消息已收到。目前为非工作时间，工作人员将在明天上班后第一时间回复您，感谢您的耐心等待。"

TRANSFER_REPLY = "您的问题我已记录，稍后会有专业工作人员为您详细解答，请稍等。"
LOW_CONF_REPLY = "您的问题我已记录，稍后工作人员会为您回复，请稍等。"

_HUMANIZE_SUFFIXES = ["", "", "", "~", "，有其他问题随时问我", "，希望能帮到您"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Pydantic 模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class BotMessage(BaseModel):
    sender: str = Field(..., description="发送者 wxid")
    content: str = Field("", description="消息文本")
    is_group: bool = Field(False, description="是否群消息")
    room_id: str = Field("", description="群 ID")
    msg_type: str = Field("text", description="消息类型")
    timestamp: str = Field("", description="消息时间戳")


class BotReply(BaseModel):
    action: str = Field(..., description="skip / reply / transfer")
    reply: str = Field("", description="回复文本（action=reply 时有值）")
    confidence: float = Field(0.0, description="FAQ 匹配置信度")
    transfer_reason: str = Field("", description="转人工原因（action=transfer 时有值）")
    delay_sec: float = Field(0.0, description="建议延迟秒数（模拟真人打字）")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  认证：X-Bot-Secret
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _get_bot_secret() -> str:
    """从环境变量/config 读取 bot_webhook_secret。"""
    return (settings.bot_webhook_secret or "").strip()


async def verify_bot_secret(
    x_bot_secret: str = Header("", alias="X-Bot-Secret"),
):
    secret = _get_bot_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="Bot Webhook 未配置密钥，请在 .env 中设置 BOT_WEBHOOK_SECRET")
    if x_bot_secret != secret:
        raise HTTPException(status_code=401, detail="Bot 密钥无效")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  动态配置加载
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _load_bot_config(db: AsyncSession) -> dict:  # noqa: ARG001
    """Bot 行为配置（当前使用内置默认值，后续可扩展为 SystemSetting 字段）。"""
    return {}


def _get_sensitive_keywords(cfg: dict) -> list[str]:
    return cfg.get("sensitive_keywords", SENSITIVE_KEYWORDS)


def _get_conf_thresholds(cfg: dict) -> tuple[float, float]:
    auto = float(cfg.get("confidence_auto", CONF_AUTO_THRESHOLD))
    human = float(cfg.get("confidence_human", CONF_HUMAN_THRESHOLD))
    return auto, human


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  合规拦截
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _is_sensitive(text: str, keywords: list[str]) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)


def _is_skip(text: str) -> bool:
    return text.strip() in SKIP_WORDS or len(text.strip()) <= 1


def _is_blocked(text: str) -> bool:
    return any(w in text for w in BLOCK_WORDS)


def _is_working_hours(cfg: dict) -> bool:
    hour = datetime.now().hour
    start = int(cfg.get("working_hours_start", 8))
    end = int(cfg.get("working_hours_end", 22))
    return start <= hour < end


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  模拟真人
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _calc_delay(text: str, cfg: dict) -> float:
    delay_min = float(cfg.get("delay_min_sec", 1.5))
    delay_max = float(cfg.get("delay_max_sec", 4.0))
    base = random.uniform(delay_min, delay_max)
    typing = len(text) * 0.04
    return round(min(base + typing, 8.0), 2)


def _humanize(text: str) -> str:
    suffix = random.choice(_HUMANIZE_SUFFIXES)
    return text.rstrip("。，！!.") + suffix


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  会话免责前缀追踪（内存，重启后重置）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_disclaimer_sent: set[str] = set()


def _maybe_prepend_disclaimer(sender: str, text: str, cfg: dict) -> str:
    if sender in _disclaimer_sent:
        return text
    disclaimer = cfg.get("disclaimer", DISCLAIMER)
    _disclaimer_sent.add(sender)
    return disclaimer + text


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  核心 Webhook 端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/webhook", response_model=BotReply)
async def handle_bot_webhook(
    msg: BotMessage,
    db: AsyncSession = Depends(get_db),
    _auth: None = Depends(verify_bot_secret),
):
    """
    OpenClaw Webhook 回调。

    OpenClaw 收到微信消息后 POST 到此端点。
    服务器完成合规拦截、FAQ 检索、LLM 回复，返回结构化结果给 OpenClaw。
    OpenClaw 根据 action 决定发送回复或跳过。
    """
    text = (msg.content or "").strip()
    t0 = time.monotonic()
    cfg = await _load_bot_config(db)

    # ── 基本过滤 ──
    if not text or msg.msg_type != "text":
        return BotReply(action="skip")
    if msg.is_group:
        return BotReply(action="skip")
    if _is_skip(text):
        return BotReply(action="skip")
    if _is_blocked(text):
        return BotReply(action="skip")

    logger.info("Bot ← [%s] %s", msg.sender, text[:100])

    # ── 合规拦截：敏感词 → 转人工 ──
    keywords = _get_sensitive_keywords(cfg)
    if _is_sensitive(text, keywords):
        logger.info("Bot →✋ [%s] 敏感词命中，转人工", msg.sender)
        _log_bot_action(db, msg, "transfer", TRANSFER_REPLY, 0.0, "sensitive_keyword")
        return BotReply(
            action="transfer",
            reply=TRANSFER_REPLY,
            transfer_reason="sensitive_keyword",
            delay_sec=_calc_delay(TRANSFER_REPLY, cfg),
        )

    # ── 非工作时间 ──
    if not _is_working_hours(cfg):
        off_reply = cfg.get("off_hours_reply", OFF_HOURS_REPLY)
        logger.info("Bot →🌙 [%s] 非工作时间", msg.sender)
        _log_bot_action(db, msg, "reply", off_reply, 0.0, "off_hours")
        return BotReply(
            action="reply",
            reply=off_reply,
            delay_sec=_calc_delay(off_reply, cfg),
        )

    # ── 调用 FAQ AI 问答助手 ──
    try:
        tenant_id = int(cfg.get("tenant_id", 1))
        query_embedding = await get_single_embedding(text)
        search_results = await semantic_search(db, query_embedding, tenant_id, top_k=6)
        result = await copilot_answer(text, search_results, quality_mode="auto")
    except Exception as e:
        logger.exception("Bot FAQ API error for [%s]: %s", msg.sender, e)
        _log_bot_action(db, msg, "transfer", "", 0.0, f"api_error:{e}")
        return BotReply(
            action="transfer",
            reply=TRANSFER_REPLY,
            transfer_reason=f"api_error",
            delay_sec=_calc_delay(TRANSFER_REPLY, cfg),
        )

    conf = result.confidence or 0.0
    reply_text = result.recommended_reply or ""
    latency_ms = int((time.monotonic() - t0) * 1000)
    conf_auto, conf_human = _get_conf_thresholds(cfg)

    # ── 按置信度决策 ──
    if conf >= conf_auto and reply_text:
        final = _humanize(reply_text)
        final = _maybe_prepend_disclaimer(msg.sender, final, cfg)
        delay = _calc_delay(final, cfg)
        logger.info("Bot → [%s] conf=%.2f latency=%dms | %s...", msg.sender, conf, latency_ms, final[:80])
        _log_bot_action(db, msg, "reply", final, conf, "auto")
        return BotReply(action="reply", reply=final, confidence=conf, delay_sec=delay)

    elif conf >= conf_human and reply_text:
        final = _humanize(reply_text)
        final = _maybe_prepend_disclaimer(msg.sender, final, cfg)
        delay = _calc_delay(final, cfg)
        logger.info("Bot →⚠ [%s] conf=%.2f 中置信回复+通知人工", msg.sender, conf)
        _log_bot_action(db, msg, "reply", final, conf, "medium_confidence")
        return BotReply(
            action="reply",
            reply=final,
            confidence=conf,
            transfer_reason="medium_confidence",
            delay_sec=delay,
        )

    else:
        logger.info("Bot →✋ [%s] conf=%.2f 低置信，转人工", msg.sender, conf)
        _log_bot_action(db, msg, "transfer", LOW_CONF_REPLY, conf, "low_confidence")
        return BotReply(
            action="transfer",
            reply=LOW_CONF_REPLY,
            confidence=conf,
            transfer_reason="low_confidence",
            delay_sec=_calc_delay(LOW_CONF_REPLY, cfg),
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  健康检查（Watchdog 用）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/health")
async def bot_health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  日志记录
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _log_bot_action(
    db: AsyncSession,
    msg: BotMessage,
    action: str,
    reply: str,
    confidence: float,
    reason: str,
):
    """异步写入 Copilot 日志表（复用 FaqCopilotLog）。"""
    try:
        log = FaqCopilotLog(
            tenant_id=1,
            user_id=None,
            mode=f"bot:{action}:{reason}",
            query=msg.content[:500],
            reply=reply[:2000] if reply else "",
            confidence=confidence,
            sources_json=json.dumps({"sender": msg.sender, "is_group": msg.is_group}),
            matched_count=0,
            latency_ms=0,
        )
        db.add(log)
    except Exception:
        logger.exception("Failed to log bot action")
