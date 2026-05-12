"""CSV/Excel conversation parser.

Supports importing conversations from structured CSV/Excel files.

Expected CSV columns:
  role        - "patient" or "counselor"
  content     - message text
  sender_name - (optional) display name
  timestamp   - (optional) YYYY-MM-DD HH:MM:SS
  content_type - (optional) text/image/audio, defaults to "text"

Multiple conversations can be separated by a "---" row or a "conversation_id" column.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime
from typing import Literal

from app.services.html_parser import (
    ContentType,
    MessageRole,
    ParsedConversation,
    ParsedMessage,
    RoleQualityReport,
    _build_quality_report,
)

logger = logging.getLogger("chattrainer.csv_parser")

_ROLE_MAP: dict[str, MessageRole] = {
    "patient": "patient",
    "患者": "patient",
    "访客": "patient",
    "用户": "patient",
    "counselor": "counselor",
    "咨询师": "counselor",
    "客服": "counselor",
    "医生": "counselor",
}

_CONTENT_TYPE_MAP: dict[str, ContentType] = {
    "text": "text",
    "文本": "text",
    "image": "image",
    "图片": "image",
    "audio": "audio",
    "语音": "audio",
    "system": "system",
    "系统": "system",
}


def _normalize_role(raw: str) -> MessageRole | None:
    return _ROLE_MAP.get(raw.strip().lower())


def _normalize_content_type(raw: str) -> ContentType:
    return _CONTENT_TYPE_MAP.get(raw.strip().lower(), "text")


def _detect_delimiter(sample: str) -> str:
    """Auto-detect CSV delimiter (comma, tab, or semicolon)."""
    for d in ["\t", ",", ";"]:
        if d in sample:
            try:
                reader = csv.reader(io.StringIO(sample), delimiter=d)
                row = next(reader)
                if len(row) >= 2:
                    return d
            except Exception:
                continue
    return ","


def _find_column(headers: list[str], candidates: list[str]) -> int | None:
    """Find column index by trying multiple header name variants."""
    for i, h in enumerate(headers):
        h_lower = h.strip().lower()
        if h_lower in candidates:
            return i
    return None


def parse_csv_text(text: str) -> list[ParsedConversation]:
    """Parse CSV text into one or more ParsedConversation objects.

    If a 'conversation_id' column exists, rows are grouped by it.
    Otherwise, '---' separator rows or a single conversation is assumed.
    """
    text = text.strip()
    if not text:
        return []

    first_line = text.split("\n")[0]
    delimiter = _detect_delimiter(first_line)

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)
    if len(rows) < 2:
        return []

    headers = [h.strip() for h in rows[0]]
    headers_lower = [h.lower() for h in headers]

    role_col = _find_column(headers, ["role", "角色", "发送方"])
    content_col = _find_column(headers, ["content", "内容", "消息", "message"])
    name_col = _find_column(headers, ["sender_name", "sender", "昵称", "姓名", "name"])
    time_col = _find_column(headers, ["timestamp", "time", "时间", "发送时间"])
    type_col = _find_column(headers, ["content_type", "type", "消息类型", "类型"])
    conv_col = _find_column(headers, ["conversation_id", "conv_id", "对话id", "会话id"])

    if role_col is None or content_col is None:
        logger.warning("CSV missing required columns: role=%s, content=%s", role_col, content_col)
        return []

    grouped: dict[str, list[dict]] = {}
    current_conv = "default"

    for row_idx, row in enumerate(rows[1:], start=2):
        if len(row) <= max(role_col, content_col):
            continue

        if conv_col is not None and conv_col < len(row):
            cid = row[conv_col].strip()
            if cid:
                current_conv = cid

        role_raw = row[role_col].strip()
        if role_raw == "---":
            current_conv = f"sep_{row_idx}"
            continue

        role = _normalize_role(role_raw)
        if role is None:
            continue

        content = row[content_col].strip()
        if not content:
            continue

        sender_name = row[name_col].strip() if name_col is not None and name_col < len(row) else None
        timestamp = row[time_col].strip() if time_col is not None and time_col < len(row) else None
        content_type = _normalize_content_type(
            row[type_col].strip() if type_col is not None and type_col < len(row) else "text"
        )

        original_time: str | None = None
        if timestamp:
            try:
                datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
                original_time = timestamp
            except ValueError:
                pass

        grouped.setdefault(current_conv, []).append({
            "role": role,
            "content": content,
            "content_type": content_type,
            "sender_name": sender_name or ("患者" if role == "patient" else "咨询师"),
            "original_time": original_time,
        })

    results: list[ParsedConversation] = []
    for conv_id, msg_list in grouped.items():
        if not msg_list:
            continue

        messages: list[ParsedMessage] = []
        patient_name: str | None = None
        counselor_name: str | None = None

        for i, m in enumerate(msg_list):
            pm = ParsedMessage(
                sequence=i + 1,
                role=m["role"],
                content_type=m["content_type"],
                content=m["content"],
                sender_name=m["sender_name"],
                original_time=m["original_time"],
            )
            messages.append(pm)
            if m["role"] == "patient" and not patient_name:
                patient_name = m["sender_name"]
            if m["role"] == "counselor" and not counselor_name:
                counselor_name = m["sender_name"]

        report = _build_quality_report(messages, patient_name, counselor_name)
        results.append(ParsedConversation(
            patient_name=patient_name,
            counselor_name=counselor_name,
            messages=messages,
            quality_report=report,
        ))

    return results


def parse_excel_bytes(content: bytes) -> list[ParsedConversation]:
    """Parse Excel (.xlsx) file bytes into conversations.

    Converts to CSV internally and delegates to parse_csv_text.
    """
    try:
        import openpyxl
    except ImportError:
        logger.error("openpyxl not installed — cannot parse Excel files")
        raise RuntimeError("服务端缺少 openpyxl 库，无法解析 Excel 文件")

    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    if ws is None:
        return []

    buf = io.StringIO()
    writer = csv.writer(buf)
    for row in ws.iter_rows(values_only=True):
        writer.writerow([str(c) if c is not None else "" for c in row])

    return parse_csv_text(buf.getvalue())
