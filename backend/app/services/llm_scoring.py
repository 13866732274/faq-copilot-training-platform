"""LLM Rubric Audit for AI Scoring (V2).

Uses Alibaba Dashscope (Qwen) via OpenAI-compatible API.
Rule-based scores (V1) and LLM scores are fused with configurable weights.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

RUBRIC_SYSTEM_PROMPT = """\
你是一位专业的医疗咨询培训评审专家。你的任务是根据"患者-咨询师"对话记录，对咨询员的回复进行五维度打分。

## 评分维度（每维0-100分）
1. **task_completion** 任务完成度：咨询员是否对每一轮标准回复做出了完整回应。未回复的轮次应扣分。
2. **semantic_alignment** 语义贴合度：咨询员回复与标准答案在语义、要点、意图上的匹配程度。
3. **keypoint_coverage** 关键点命中：咨询员回复是否覆盖了标准答案中的核心关键词和要点。
4. **communication_quality** 沟通质量：是否体现共情表达（如"理解"、"辛苦"）、结构化建议、行动方案和礼貌用语。
5. **risk_control** 风险控制：是否存在绝对化承诺（"保证"、"一定会"）、忽视风险（"不用管"、"没事"）或过短无效回复。

## 输出格式
请严格以JSON格式输出，不要输出任何额外文字：
```json
{
  "scores": {
    "task_completion": <int 0-100>,
    "semantic_alignment": <int 0-100>,
    "keypoint_coverage": <int 0-100>,
    "communication_quality": <int 0-100>,
    "risk_control": <int 0-100>
  },
  "overall": <int 0-100>,
  "deduction_reasons": ["<扣分原因1>", "<扣分原因2>"],
  "highlights": ["<亮点1>"],
  "summary": "<50字以内总评>"
}
```"""


def _build_conversation_text(rounds: list[dict], reply_map: dict[int, str]) -> str:
    """Build a readable conversation transcript for LLM evaluation."""
    parts: list[str] = []
    for i, r in enumerate(rounds, 1):
        msg_id = int(r["first_message_id"])
        standards = r.get("standards", [])
        student_reply = reply_map.get(msg_id, "")
        parts.append(f"=== 第{i}轮 ===")
        for j, std in enumerate(standards, 1):
            parts.append(f"【标准答案{j}】{std}")
        if student_reply:
            parts.append(f"【咨询员回复】{student_reply}")
        else:
            parts.append("【咨询员回复】（未回复）")
        parts.append("")
    return "\n".join(parts)


@dataclass
class LlmAuditResult:
    enabled: bool = True
    provider: str = "dashscope"
    model: str = ""
    status: str = "success"
    scores: dict[str, float] = field(default_factory=dict)
    overall: float = 0.0
    deduction_reasons: list[str] = field(default_factory=list)
    highlights: list[str] = field(default_factory=list)
    summary: str = ""
    latency_ms: int = 0
    error: str | None = None


def _not_configured_result() -> LlmAuditResult:
    return LlmAuditResult(
        enabled=False,
        status="not_configured",
        error="百炼 API Key 未配置",
    )


def _error_result(error: str, latency_ms: int = 0) -> LlmAuditResult:
    return LlmAuditResult(
        enabled=True,
        provider="dashscope",
        model=settings.dashscope_model,
        status="error",
        latency_ms=latency_ms,
        error=error,
    )


def _parse_llm_json(text: str) -> dict | None:
    """Extract JSON from LLM response, handling markdown code fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        start = 1
        end = len(lines)
        for i, line in enumerate(lines[1:], 1):
            if line.strip().startswith("```"):
                end = i
                break
        text = "\n".join(lines[start:end]).strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


async def run_llm_audit(
    rounds: list[dict],
    reply_map: dict[int, str],
) -> LlmAuditResult:
    """Call Dashscope LLM to evaluate the practice conversation."""

    api_key = settings.dashscope_api_key
    if not api_key:
        return _not_configured_result()

    conversation_text = _build_conversation_text(rounds, reply_map)
    total_rounds = len(rounds)
    answered = sum(1 for r in rounds if int(r["first_message_id"]) in reply_map)

    user_prompt = (
        f"以下是一次咨询话术模拟练习的对话记录，共 {total_rounds} 个回合，"
        f"咨询员回复了 {answered} 个回合。\n\n"
        f"{conversation_text}\n"
        f"请按评分标准对咨询员的回复进行五维度打分。"
    )

    url = f"{settings.dashscope_base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": settings.dashscope_model,
        "messages": [
            {"role": "system", "content": RUBRIC_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 1024,
        "response_format": {"type": "json_object"},
    }

    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=body, headers=headers)
        latency_ms = int((time.monotonic() - t0) * 1000)

        if resp.status_code != 200:
            err_msg = f"API 返回 {resp.status_code}: {resp.text[:200]}"
            logger.warning("[LLM-Audit] %s", err_msg)
            return _error_result(err_msg, latency_ms)

        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        parsed = _parse_llm_json(content)
        if not parsed:
            logger.warning("[LLM-Audit] Failed to parse LLM JSON: %s", content[:300])
            return _error_result("LLM 输出格式解析失败", latency_ms)

        scores_raw = parsed.get("scores", {})
        dim_keys = [
            "task_completion",
            "semantic_alignment",
            "keypoint_coverage",
            "communication_quality",
            "risk_control",
        ]
        scores = {}
        for k in dim_keys:
            val = scores_raw.get(k)
            scores[k] = max(0.0, min(100.0, float(val))) if val is not None else 0.0

        overall_raw = parsed.get("overall")
        overall = max(0.0, min(100.0, float(overall_raw))) if overall_raw is not None else 0.0

        return LlmAuditResult(
            enabled=True,
            provider="dashscope",
            model=settings.dashscope_model,
            status="success",
            scores=scores,
            overall=overall,
            deduction_reasons=[str(r) for r in parsed.get("deduction_reasons", [])[:5]],
            highlights=[str(h) for h in parsed.get("highlights", [])[:3]],
            summary=str(parsed.get("summary", ""))[:200],
            latency_ms=latency_ms,
        )

    except httpx.TimeoutException:
        latency_ms = int((time.monotonic() - t0) * 1000)
        logger.warning("[LLM-Audit] Timeout after %dms", latency_ms)
        return _error_result("LLM 请求超时（30s），请稍后重试", latency_ms)
    except Exception as e:
        latency_ms = int((time.monotonic() - t0) * 1000)
        logger.exception("[LLM-Audit] Unexpected error")
        return _error_result(f"LLM 请求异常: {type(e).__name__}", latency_ms)


def fuse_scores(
    rule_scores: dict[str, float],
    llm_scores: dict[str, float],
    rule_weight: float | None = None,
    llm_weight: float | None = None,
) -> dict[str, float]:
    """Fuse rule-based and LLM dimension scores with configurable weights."""
    rw = rule_weight if rule_weight is not None else settings.ai_scoring_rule_weight
    lw = llm_weight if llm_weight is not None else settings.ai_scoring_llm_weight

    if not llm_scores:
        return dict(rule_scores)

    fused: dict[str, float] = {}
    for key in rule_scores:
        r_val = rule_scores.get(key, 0.0)
        l_val = llm_scores.get(key, r_val)
        fused[key] = round(r_val * rw + l_val * lw, 2)
    return fused
