"""Dashscope LLM & Embedding helpers for FAQ pipeline."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

import httpx

from app.config import settings

logger = logging.getLogger("chattrainer.faq_llm")

EMBEDDING_MODEL = "text-embedding-v3"
EMBEDDING_DIMENSION = 1024
EMBEDDING_BATCH_SIZE = 10

_http_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """Reuse a global httpx client for connection pooling."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=60.0,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _http_client


def _api_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.dashscope_api_key}",
        "Content-Type": "application/json",
    }


async def get_embeddings(texts: list[str]) -> list[list[float]]:
    """Get text embeddings from Dashscope in batches."""
    if not settings.dashscope_api_key:
        raise RuntimeError("Dashscope API Key 未配置，无法获取文本向量")

    url = f"{settings.dashscope_base_url}/embeddings"
    if not texts:
        return []

    client = _get_client()

    async def _embed_batch(batch: list[str]) -> list[list[float]]:
        body = {
            "model": EMBEDDING_MODEL,
            "input": batch,
            "dimensions": EMBEDDING_DIMENSION,
        }
        resp = await client.post(url, json=body, headers=_api_headers())
        if resp.status_code != 200:
            detail = resp.text[:500]
            logger.error("Embedding API error %d: %s", resp.status_code, detail)
            if resp.status_code == 400 and len(batch) > 1:
                mid = max(1, len(batch) // 2)
                left = await _embed_batch(batch[:mid])
                right = await _embed_batch(batch[mid:])
                return [*left, *right]
            raise RuntimeError(f"Embedding API 返回 {resp.status_code}: {detail}")
        data = resp.json()
        embeddings = data.get("data", [])
        embeddings.sort(key=lambda x: x.get("index", 0))
        return [item["embedding"] for item in embeddings]

    import asyncio

    CONCURRENT_BATCHES = 3
    batches = [
        texts[i : i + EMBEDDING_BATCH_SIZE]
        for i in range(0, len(texts), EMBEDDING_BATCH_SIZE)
    ]

    all_embeddings: list[list[float]] = []
    for chunk_start in range(0, len(batches), CONCURRENT_BATCHES):
        chunk = batches[chunk_start : chunk_start + CONCURRENT_BATCHES]
        results = await asyncio.gather(*[_embed_batch(b) for b in chunk])
        for r in results:
            all_embeddings.extend(r)

    return all_embeddings


async def get_single_embedding(text: str) -> list[float]:
    """Get embedding for a single text."""
    result = await get_embeddings([text])
    return result[0]


def _parse_llm_json(text: str) -> dict | None:
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


EXTRACT_QA_SYSTEM_PROMPT = """\
你是一位医疗咨询数据清洗专家。给你一段患者和咨询师的对话记录，请提取出有意义的"问答对"。

关键角色识别规则（务必严格遵守）：
- [patient] 标签的消息来自患者/访客/家属，是提问方
- [counselor] 标签的消息来自咨询师/客服/医生，是回答方
- 绝不能把 counselor 的消息当作问题，也不能把 patient 的消息当作专业回答
- 如果 counselor 主动提问（如"您几点方便"），这不是患者问题，不要提取

提取规则：
1. 只提取患者提出的实质性问题（咨询地址、价格、时间、治疗方案、预约流程、医院资质等）
2. 过滤掉：寒暄（你好、谢谢、再见）、单字回复（嗯、好）、图片/语音占位消息、无意义的闲聊
3. 如果患者连续多条消息在问同一个问题，合并成一条清晰的问题
4. 每个问题配上咨询师的完整回答（可能是连续多条消息合并为一段完整回复）
5. 如果一段对话没有任何有价值的问答，返回空数组
6. answer 字段中仅包含咨询师的回复内容，不要混入患者的话

输出格式（严格 JSON）：
```json
{
  "pairs": [
    {
      "question": "患者的问题（清洗整理后的规范表述）",
      "raw_question": "患者原始提问文本",
      "answer": "咨询师的完整回答（多条合并后）",
      "question_msg_ids": [消息序号列表],
      "answer_msg_ids": [消息序号列表]
    }
  ]
}
```"""


@dataclass
class QAPair:
    question: str
    raw_question: str
    answer: str
    question_msg_ids: list[int] = field(default_factory=list)
    answer_msg_ids: list[int] = field(default_factory=list)


async def extract_qa_pairs(messages: list[dict]) -> list[QAPair]:
    """Use LLM to extract clean Q&A pairs from a conversation."""
    if not settings.dashscope_api_key:
        return []

    conversation_text = "\n".join(
        f"[{m['sequence']}][{m['role']}] {m['content']}"
        for m in messages
        if m.get("content_type") == "text" and m.get("content", "").strip()
    )

    if len(conversation_text) < 20:
        return []

    url = f"{settings.dashscope_base_url}/chat/completions"
    body = {
        "model": settings.dashscope_model,
        "messages": [
            {"role": "system", "content": EXTRACT_QA_SYSTEM_PROMPT},
            {"role": "user", "content": f"以下是对话记录：\n\n{conversation_text}"},
        ],
        "temperature": 0.2,
        "max_tokens": 4096,
        "response_format": {"type": "json_object"},
        "enable_thinking": False,  # 关闭 qwen3 系列思考模式，避免高延迟与 token 浪费
    }

    t0 = time.monotonic()
    try:
        client = _get_client()
        resp = await client.post(url, json=body, headers=_api_headers(), timeout=60.0)
        latency = int((time.monotonic() - t0) * 1000)
        logger.info("extract_qa_pairs latency=%dms status=%d", latency, resp.status_code)

        if resp.status_code != 200:
            logger.error("LLM API error: %s", resp.text[:300])
            return []

        content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        parsed = _parse_llm_json(content)
        if not parsed:
            logger.warning("Failed to parse LLM output: %s", content[:300])
            return []

        pairs = []
        for item in parsed.get("pairs", []):
            q = str(item.get("question", "")).strip()
            a = str(item.get("answer", "")).strip()
            if not q or not a:
                continue
            pairs.append(QAPair(
                question=q,
                raw_question=str(item.get("raw_question", q)).strip(),
                answer=a,
                question_msg_ids=[int(x) for x in item.get("question_msg_ids", [])],
                answer_msg_ids=[int(x) for x in item.get("answer_msg_ids", [])],
            ))
        return pairs
    except Exception:
        logger.exception("extract_qa_pairs failed")
        return []


REFINE_CLUSTER_SYSTEM_PROMPT = """\
你是一位医疗咨询知识库运营专家。给你一组语义相似的患者问题和对应的咨询师回答。

请完成：
1. 为这组问题起一个简洁精准的标题（如"医院地址"、"挂号流程"、"治疗费用"、"医院资质"等）
2. 写一句总结描述，概述患者关心什么
3. 选出一个最具代表性的患者问题（最能代表这类问题的核心意图）
4. 从所有咨询师回答中总结/提取最佳回答，要求：
   - 信息完整、专业准确
   - 只包含咨询师的回复，不要混入患者的话
   - 如果多个回答互补，合并取精华
   - 包含关键细节（如具体地址、电话、时间、价格区间）
5. 给出一个分类标签：基础信息、就诊流程、费用咨询、治疗方案、预约相关、医院资质、医保政策、术后护理、其他
6. 对每个回答给出质量评分（0.0-1.0），依据信息完整度、专业性、实用性

输出格式（严格 JSON）：
```json
{
  "title": "问题标题",
  "summary": "这组问题主要是关于...",
  "category": "分类",
  "representative_question": "最具代表性的问题原文",
  "best_answer": "综合最佳回答",
  "answer_quality_scores": [0.0-1.0 的评分，按输入的回答顺序]
}
```"""


@dataclass
class ClusterRefinement:
    title: str = ""
    summary: str = ""
    category: str = ""
    representative_question: str = ""
    best_answer: str = ""
    answer_quality_scores: list[float] = field(default_factory=list)


async def refine_cluster(
    questions: list[str],
    answers: list[str],
) -> ClusterRefinement:
    """Use LLM to generate cluster title, best answer, and quality scores."""
    if not settings.dashscope_api_key:
        return ClusterRefinement(title=questions[0][:50] if questions else "未命名")

    user_text = "## 患者问题（同一类）\n"
    for i, q in enumerate(questions[:20], 1):
        user_text += f"{i}. {q}\n"
    user_text += "\n## 对应咨询师回答\n"
    for i, a in enumerate(answers[:20], 1):
        user_text += f"{i}. {a}\n"

    url = f"{settings.dashscope_base_url}/chat/completions"
    body = {
        "model": settings.dashscope_model,
        "messages": [
            {"role": "system", "content": REFINE_CLUSTER_SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0.3,
        "max_tokens": 2048,
        "response_format": {"type": "json_object"},
        "enable_thinking": False,  # 关闭思考模式
    }

    try:
        client = _get_client()
        resp = await client.post(url, json=body, headers=_api_headers(), timeout=60.0)

        if resp.status_code != 200:
            logger.error("Refine API error: %s", resp.text[:300])
            return ClusterRefinement(title=questions[0][:50] if questions else "未命名")

        content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        parsed = _parse_llm_json(content)
        if not parsed:
            return ClusterRefinement(title=questions[0][:50] if questions else "未命名")

        scores_raw = parsed.get("answer_quality_scores", [])
        scores = []
        for s in scores_raw:
            try:
                scores.append(max(0.0, min(1.0, float(s))))
            except (TypeError, ValueError):
                scores.append(0.5)

        return ClusterRefinement(
            title=str(parsed.get("title", ""))[:500],
            summary=str(parsed.get("summary", ""))[:1000],
            category=str(parsed.get("category", ""))[:200],
            representative_question=str(parsed.get("representative_question", ""))[:2000],
            best_answer=str(parsed.get("best_answer", ""))[:5000],
            answer_quality_scores=scores,
        )
    except Exception:
        logger.exception("refine_cluster failed")
        return ClusterRefinement(title=questions[0][:50] if questions else "未命名")


COPILOT_SYSTEM_PROMPT = """\
你是医疗咨询机构的智能助手。用户输入患者的问题，请根据提供的知识库FAQ条目给出最佳回复建议。

规则：
1. 优先使用知识库中已有的最佳回答
2. 可以适当整合多条相关回答
3. 回复要专业、亲切、有温度
4. 不得编造未在知识库出现的关键信息（如地址、价格、医保政策）
5. 如果知识库没有直接相关内容，只能基于已有信息谨慎回答并标注"仅供参考"
6. 回答中尽量覆盖用户问题中的关键点（如费用、医保、地址、时间）

直接回复推荐内容即可，不需要JSON格式。简洁专业，控制在 260 字以内。"""


COPILOT_SYSTEM_PROMPT_JSON = """\
你是医疗咨询机构的智能助手。用户输入患者的问题，请根据提供的知识库FAQ条目给出最佳回复建议。

规则同上。输出严格 JSON：
{"recommended_reply": "推荐回复", "confidence": 0.0-1.0, "sources": ["FAQ标题"], "note": ""}"""


@dataclass
class CopilotResult:
    recommended_reply: str = ""
    confidence: float = 0.0
    sources: list[str] = field(default_factory=list)
    note: str = ""


# 高置信直接返回阈值：超过此值直接用 best_answer，跳过 LLM（除非 quality 模式）
HIGH_CONF_DIRECT_THRESHOLD = 0.82


def _try_direct_faq_answer(
    faq_context: list[dict],
    quality_mode: str | None = None,
) -> CopilotResult | None:
    """若顶部 FAQ 匹配度超过高置信阈值，直接返回 best_answer，跳过 LLM 调用。

    quality 模式强制走 LLM 润色，不触发直通逻辑。
    """
    if _resolve_quality_mode(quality_mode) == "quality":
        return None
    if not faq_context:
        return None
    top = faq_context[0]
    sim = float(top.get("similarity") or 0.0)
    if sim < HIGH_CONF_DIRECT_THRESHOLD:
        return None
    best = str(top.get("best_answer") or "").strip()
    if not best:
        return None
    return CopilotResult(
        recommended_reply=best,
        confidence=round(sim, 4),
        sources=[str(top.get("title") or "")],
        note="high_conf_direct",
    )


def _resolve_quality_mode(mode: str | None) -> str:
    v = (mode or "").strip().lower()
    if v in {"fast", "balanced", "quality"}:
        return v
    return "balanced"


def _resolve_copilot_model(mode: str | None) -> str:
    m = _resolve_quality_mode(mode)
    if m == "fast":
        return settings.dashscope_copilot_model or "qwen-turbo"
    if m == "quality":
        return settings.dashscope_model or "qwen3-max"
    return settings.dashscope_copilot_balanced_model or "qwen-plus"


def _resolve_copilot_tokens(mode: str | None) -> int:
    m = _resolve_quality_mode(mode)
    if m == "fast":
        return 384
    if m == "quality":
        return 768
    return 512


def _build_copilot_context(faq_context: list[dict]) -> str:
    context_text = ""
    for i, faq in enumerate(faq_context[:5], 1):
        context_text += f"### FAQ {i}: {faq.get('title', '')}\n"
        context_text += f"代表性问题：{faq.get('representative_question', '')}\n"
        context_text += f"最佳回答：{faq.get('best_answer', '')}\n\n"
    return context_text


async def copilot_answer_stream(
    user_question: str,
    faq_context: list[dict],
    quality_mode: str | None = None,
) -> AsyncGenerator[str, None]:
    """Stream copilot answer token by token via SSE-compatible generator.

    高置信直通：相似度 >= HIGH_CONF_DIRECT_THRESHOLD 时一次性返回 best_answer，
    无需流式，前端仍按 SSE 协议接收到完整内容。
    """
    direct = _try_direct_faq_answer(faq_context, quality_mode)
    if direct is not None:
        yield direct.recommended_reply
        return

    if not settings.dashscope_api_key:
        yield "AI 未配置"
        return

    context_text = _build_copilot_context(faq_context)
    model = _resolve_copilot_model(quality_mode)
    max_tokens = _resolve_copilot_tokens(quality_mode)
    url = f"{settings.dashscope_base_url}/chat/completions"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": COPILOT_SYSTEM_PROMPT},
            {"role": "user", "content": f"知识库：\n{context_text}\n\n患者问题：{user_question}"},
        ],
        "temperature": 0.3,
        "max_tokens": max_tokens,
        "stream": True,
        "enable_thinking": False,  # 流式场景下思考 token 在 reasoning_content 里，对首字延迟影响最大
    }

    client = _get_client()
    try:
        async with client.stream("POST", url, json=body, headers=_api_headers(), timeout=30.0) as resp:
            if resp.status_code != 200:
                yield "AI 服务暂时不可用"
                return
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                    delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    if delta:
                        yield delta
                except (json.JSONDecodeError, IndexError, KeyError):
                    continue
    except Exception:
        logger.exception("copilot_answer_stream failed")
        yield "AI 服务异常"


async def copilot_answer(
    user_question: str,
    faq_context: list[dict],
    quality_mode: str | None = None,
) -> CopilotResult:
    """Non-streaming copilot answer (fallback / for logging).

    高置信直通：顶部 FAQ 相似度 >= HIGH_CONF_DIRECT_THRESHOLD 时直接返回 best_answer，
    响应时间从 1-3s 降至 <50ms（仅耗 Embedding 时间）。quality 模式不触发直通。
    """
    direct = _try_direct_faq_answer(faq_context, quality_mode)
    if direct is not None:
        return direct

    if not settings.dashscope_api_key:
        return CopilotResult(recommended_reply="AI 未配置", confidence=0.0)

    context_text = _build_copilot_context(faq_context)
    model = _resolve_copilot_model(quality_mode)
    max_tokens = _resolve_copilot_tokens(quality_mode)
    url = f"{settings.dashscope_base_url}/chat/completions"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": COPILOT_SYSTEM_PROMPT_JSON},
            {"role": "user", "content": f"知识库：\n{context_text}\n\n患者问题：{user_question}"},
        ],
        "temperature": 0.3,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "enable_thinking": False,
    }

    try:
        client = _get_client()
        resp = await client.post(url, json=body, headers=_api_headers(), timeout=30.0)

        if resp.status_code != 200:
            return CopilotResult(recommended_reply="AI 服务暂时不可用", confidence=0.0)

        content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        parsed = _parse_llm_json(content)
        if not parsed:
            return CopilotResult(recommended_reply="AI 回复解析失败", confidence=0.0)

        return CopilotResult(
            recommended_reply=str(parsed.get("recommended_reply", "")),
            confidence=max(0.0, min(1.0, float(parsed.get("confidence", 0.0)))),
            sources=[str(s) for s in parsed.get("sources", [])[:5]],
            note=str(parsed.get("note", "")),
        )
    except Exception:
        logger.exception("copilot_answer failed")
        return CopilotResult(recommended_reply="AI 服务异常", confidence=0.0)
