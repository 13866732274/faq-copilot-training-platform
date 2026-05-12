from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
import uuid

import httpx
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

router = APIRouter()
_ALLOWED_QUALITY_MODES = {"auto", "fast", "balanced", "quality"}
_NONCE_TTL_SEC = 300
_NONCE_CACHE: dict[str, int] = {}
_REQUEST_CACHE: dict[str, tuple[int, dict]] = {}


def _load_secret() -> str:
    return os.getenv("BOT_WEBHOOK_SECRET", "").strip()


def _verify_signature(signature: str, body: bytes, secret: str) -> bool:
    if not signature or not secret:
        return False
    # Accept both `sha256=...` and raw hex digest.
    provided = signature.removeprefix("sha256=").strip().lower()
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest().lower()
    return hmac.compare_digest(provided, expected)


def _std_response(
    *,
    code: int,
    message: str,
    action: str | None = None,
    reply: str | None = None,
    panel_id: int | None = None,
    quality_mode_requested: str | None = None,
    quality_mode_effective: str | None = None,
    quality_route_reason: str | None = None,
    request_id: str | None = None,
    trace_id: str | None = None,
    need_feedback: bool = True,
    human_handoff_reason: str = "",
    status_code: int = 200,
    extra: dict | None = None,
) -> JSONResponse:
    body = {
        "code": code,
        "message": message,
        "action": action,
        "reply": reply or "",
        "panel_id": panel_id,
        "quality_mode_requested": quality_mode_requested,
        "quality_mode_effective": quality_mode_effective,
        "quality_route_reason": quality_route_reason,
        "request_id": request_id,
        "trace_id": trace_id,
        "need_feedback": need_feedback,
        "human_handoff_reason": human_handoff_reason,
    }
    if extra:
        body.update(extra)
    return JSONResponse(status_code=status_code, content=body)


def _cleanup_caches(now_ts: int) -> None:
    expired_nonce = [k for k, t in _NONCE_CACHE.items() if now_ts - t > _NONCE_TTL_SEC]
    for key in expired_nonce:
        _NONCE_CACHE.pop(key, None)
    expired_req = [k for k, (t, _) in _REQUEST_CACHE.items() if now_ts - t > _NONCE_TTL_SEC]
    for key in expired_req:
        _REQUEST_CACHE.pop(key, None)


def _mark_nonce(nonce: str, now_ts: int) -> bool:
    if not nonce:
        return True
    _cleanup_caches(now_ts)
    if nonce in _NONCE_CACHE:
        return False
    _NONCE_CACHE[nonce] = now_ts
    return True


def _sanitize_quality_mode(value: str | None) -> str:
    mode = (value or "auto").strip().lower()
    return mode if mode in _ALLOWED_QUALITY_MODES else "auto"


def _resolve_msg_quality_mode(payload: dict) -> str:
    return _sanitize_quality_mode(str(payload.get("quality_mode") or "auto"))


async def _get_faq_reply(query: str, quality_mode: str = "auto") -> str | None:
    if not query.strip():
        return None

    api_base = os.getenv("FAQ_API_BASE", "http://127.0.0.1:8000/api/v1").rstrip("/")
    user = os.getenv("FAQ_BOT_USERNAME", "wechat_bot")
    pwd = os.getenv("FAQ_BOT_PASSWORD", "")

    if not pwd:
        return None

    async with httpx.AsyncClient(timeout=12.0) as client:
        # 1) login
        login_resp = await client.post(
            f"{api_base}/auth/login",
            json={"username": user, "password": pwd},
        )
        login_resp.raise_for_status()
        token = login_resp.json().get("data", {}).get("access_token")
        if not token:
            return None

        # 2) ask faq copilot
        faq_resp = await client.post(
            f"{api_base}/faq/copilot",
            json={"query": query, "quality_mode": _sanitize_quality_mode(quality_mode)},
            headers={"Authorization": f"Bearer {token}"},
        )
        if faq_resp.status_code != 200:
            return None
        return str(faq_resp.json().get("data", {}).get("recommended_reply") or "").strip() or None


async def _get_faq_panel(
    query: str,
    quality_mode: str = "auto",
    *,
    session_id: str | None = None,
) -> dict | None:
    """Call internal copilot panel API, return panel payload."""
    if not query.strip():
        return None
    api_base = os.getenv("FAQ_API_BASE", "http://127.0.0.1:8000/api/v1").rstrip("/")
    user = os.getenv("FAQ_BOT_USERNAME", "wechat_bot")
    pwd = os.getenv("FAQ_BOT_PASSWORD", "")
    if not pwd:
        return None
    async with httpx.AsyncClient(timeout=15.0) as client:
        login_resp = await client.post(
            f"{api_base}/auth/login",
            json={"username": user, "password": pwd},
        )
        login_resp.raise_for_status()
        token = login_resp.json().get("data", {}).get("access_token")
        if not token:
            return None
        panel_resp = await client.post(
            f"{api_base}/faq/copilot/panel",
            json={
                "query": query,
                "quality_mode": _sanitize_quality_mode(quality_mode),
                "channel": "wechat",
                "conversation_id": session_id,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        if panel_resp.status_code != 200:
            return None
        return panel_resp.json().get("data") or None


async def _submit_faq_feedback(payload: dict) -> dict | None:
    api_base = os.getenv("FAQ_API_BASE", "http://127.0.0.1:8000/api/v1").rstrip("/")
    user = os.getenv("FAQ_BOT_USERNAME", "wechat_bot")
    pwd = os.getenv("FAQ_BOT_PASSWORD", "")
    if not pwd:
        return None
    raw_action = str(payload.get("action") or "").strip().lower()
    user_feedback = str(payload.get("user_feedback") or "").strip().lower()
    mapped_action = raw_action
    if mapped_action not in {"accepted", "edited", "rejected"}:
        if raw_action == "transfer":
            mapped_action = "rejected"
        elif user_feedback in {"up", "like", "accepted"}:
            mapped_action = "accepted"
        elif user_feedback in {"down", "reject", "rejected"}:
            mapped_action = "rejected"
        else:
            mapped_action = "edited"
    body = {
        "panel_id": int(payload.get("panel_id") or 0),
        "action": mapped_action,
        "conversation_id": str(payload.get("conversation_id") or "").strip() or None,
        "channel": str(payload.get("channel") or "").strip() or "wechat",
        "candidate_index": int(payload.get("candidate_index") or 0),
        "final_reply": str(payload.get("final_reply") or "").strip() or None,
        "first_response_ms": int(payload.get("first_response_ms") or 0),
        "session_duration_ms": int(payload.get("session_duration_ms") or 0),
        "message_count": int(payload.get("message_count") or 0),
    }
    if body["panel_id"] <= 0:
        return None
    async with httpx.AsyncClient(timeout=12.0) as client:
        login_resp = await client.post(
            f"{api_base}/auth/login",
            json={"username": user, "password": pwd},
        )
        login_resp.raise_for_status()
        token = login_resp.json().get("data", {}).get("access_token")
        if not token:
            return None
        resp = await client.post(
            f"{api_base}/faq/copilot/feedback",
            json=body,
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code != 200:
            return None
        return resp.json().get("data") or None


@router.post("/wechat-faq")
async def wechat_faq(
    request: Request,
    x_hub_signature_256: str = Header(..., alias="X-Hub-Signature-256"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    x_timestamp: str | None = Header(default=None, alias="X-Timestamp"),
    x_nonce: str | None = Header(default=None, alias="X-Nonce"),
    x_openclaw_version: str | None = Header(default=None, alias="X-OpenClaw-Version"),
    x_client: str | None = Header(default=None, alias="X-Client"),
):
    """
    OpenClaw webhook endpoint (HMAC-SHA256 signed).
    """
    secret = _load_secret()
    if not secret:
        return _std_response(
            code=3002,
            message="service_unavailable",
            action="transfer",
            status_code=503,
        )

    body = await request.body()
    if not _verify_signature(x_hub_signature_256, body, secret):
        return _std_response(code=2002, message="invalid_signature", status_code=401)

    try:
        msg = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return _std_response(code=2001, message="invalid_payload", status_code=400)

    now_ts = int(time.time())
    request_id = str(msg.get("request_id") or x_request_id or uuid.uuid4()).strip()[:128]
    trace_id = str(msg.get("trace_id") or request_id).strip()[:128]
    session_id = str(msg.get("session_id") or f"wechat:{msg.get('sender') or ''}").strip() or None

    ts = int(msg.get("ts") or msg.get("client_ts") or x_timestamp or 0)
    if ts and abs(now_ts - ts) > _NONCE_TTL_SEC:
        return _std_response(
            code=2003,
            message="expired_timestamp",
            request_id=request_id,
            trace_id=trace_id,
            status_code=401,
        )
    nonce = str(msg.get("nonce") or x_nonce or "").strip()
    if nonce and not _mark_nonce(nonce, now_ts):
        return _std_response(
            code=2004,
            message="duplicate_request",
            request_id=request_id,
            trace_id=trace_id,
            status_code=409,
        )

    if bool(msg.get("is_group", False)):
        return _std_response(
            code=1001,
            message="skip_group",
            action="skip",
            request_id=request_id,
            trace_id=trace_id,
            need_feedback=False,
        )

    content = str(msg.get("content") or "").strip()
    requested_quality_mode = _resolve_msg_quality_mode(msg)
    if not content:
        return _std_response(
            code=2001,
            message="invalid_payload",
            action="skip",
            request_id=request_id,
            trace_id=trace_id,
            status_code=400,
        )

    message_id = str(msg.get("message_id") or "").strip()
    sender = str(msg.get("sender") or "").strip()
    dedupe_key = f"{message_id}|{sender}|{ts}" if message_id else ""
    if dedupe_key and dedupe_key in _REQUEST_CACHE:
        _, cached = _REQUEST_CACHE[dedupe_key]
        return _std_response(
            code=0,
            message="ok",
            action=cached.get("action"),
            reply=cached.get("reply"),
            panel_id=cached.get("panel_id"),
            quality_mode_requested=requested_quality_mode,
            quality_mode_effective=cached.get("quality_mode_effective"),
            quality_route_reason=cached.get("quality_route_reason"),
            request_id=request_id,
            trace_id=trace_id,
            extra={"duplicated": True, "candidates": cached.get("candidates", [])},
        )

    panel = await _get_faq_panel(content, quality_mode=requested_quality_mode, session_id=session_id)
    if not panel:
        # Backward-compatible fallback (degraded mode).
        reply = await _get_faq_reply(content, quality_mode=requested_quality_mode)
        if not reply:
            return _std_response(
                code=3001,
                message="faq_backend_error",
                action="transfer",
                quality_mode_requested=requested_quality_mode,
                request_id=request_id,
                trace_id=trace_id,
                status_code=500,
            )
        response_body = {
            "action": "reply",
            "reply": reply,
            "panel_id": None,
            "quality_mode_effective": requested_quality_mode,
            "quality_route_reason": "degraded_fallback",
            "candidates": [],
        }
        if dedupe_key:
            _REQUEST_CACHE[dedupe_key] = (now_ts, response_body)
        return _std_response(
            code=0,
            message="ok",
            action="reply",
            reply=reply,
            quality_mode_requested=requested_quality_mode,
            quality_mode_effective=requested_quality_mode,
            quality_route_reason="degraded_fallback",
            request_id=request_id,
            trace_id=trace_id,
            extra={
                "degraded": True,
                "candidates": [],
                "openclaw_version": x_openclaw_version,
                "client": x_client,
            },
        )
    candidates = panel.get("candidates") or []
    reply = str(candidates[0]).strip() if candidates else None
    if not reply:
        reply = None
    action = "reply" if reply else "transfer"
    code = 0 if reply else 1002
    message = "ok" if reply else "no_confident_answer"
    handoff_reason = "" if reply else "low_confidence"
    response_body = {
        "action": action,
        "reply": reply or "",
        "panel_id": panel.get("panel_id"),
        "quality_mode_effective": panel.get("quality_mode_effective"),
        "quality_route_reason": panel.get("quality_route_reason"),
        "candidates": candidates[:3],
    }
    if dedupe_key:
        _REQUEST_CACHE[dedupe_key] = (now_ts, response_body)
    return _std_response(
        code=code,
        message=message,
        action=action,
        reply=reply,
        panel_id=panel.get("panel_id"),
        quality_mode_requested=requested_quality_mode,
        quality_mode_effective=panel.get("quality_mode_effective"),
        quality_route_reason=panel.get("quality_route_reason"),
        request_id=request_id,
        trace_id=trace_id,
        human_handoff_reason=handoff_reason,
        extra={
            "candidates": candidates[:3],
            "confidence": panel.get("confidence"),
            "latency_ms": panel.get("latency_ms"),
            "openclaw_version": x_openclaw_version,
            "client": x_client,
        },
    )


@router.post("/wechat-faq/feedback")
async def wechat_faq_feedback(
    request: Request,
    x_hub_signature_256: str = Header(..., alias="X-Hub-Signature-256"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    x_timestamp: str | None = Header(default=None, alias="X-Timestamp"),
    x_nonce: str | None = Header(default=None, alias="X-Nonce"),
):
    """Webhook feedback callback to keep same analytics path as console panel."""
    secret = _load_secret()
    if not secret:
        return _std_response(code=3002, message="service_unavailable", status_code=503)
    body = await request.body()
    if not _verify_signature(x_hub_signature_256, body, secret):
        return _std_response(code=2002, message="invalid_signature", status_code=401)
    try:
        msg = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return _std_response(code=2001, message="invalid_payload", status_code=400)
    request_id = str(msg.get("request_id") or x_request_id or uuid.uuid4()).strip()[:128]
    trace_id = str(msg.get("trace_id") or request_id).strip()[:128]
    now_ts = int(time.time())
    ts = int(msg.get("feedback_ts") or msg.get("ts") or x_timestamp or 0)
    if ts and abs(now_ts - ts) > _NONCE_TTL_SEC:
        return _std_response(
            code=2003,
            message="expired_timestamp",
            request_id=request_id,
            trace_id=trace_id,
            status_code=401,
        )
    nonce = str(msg.get("nonce") or x_nonce or "").strip() or secrets.token_hex(8)
    if nonce and not _mark_nonce(f"fb:{nonce}", now_ts):
        return _std_response(
            code=2004,
            message="duplicate_request",
            request_id=request_id,
            trace_id=trace_id,
            status_code=409,
        )
    data = await _submit_faq_feedback(msg)
    if not data:
        return _std_response(
            code=2001,
            message="invalid_payload",
            request_id=request_id,
            trace_id=trace_id,
            status_code=400,
        )
    return _std_response(
        code=0,
        message="ok",
        action=str(msg.get("action") or ""),
        request_id=request_id,
        trace_id=trace_id,
        extra={"data": data},
    )

