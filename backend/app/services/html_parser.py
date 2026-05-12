from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from bs4 import BeautifulSoup


MessageRole = Literal["patient", "counselor"]
ContentType = Literal["text", "image", "audio", "system"]


@dataclass
class ParsedMessage:
    sequence: int
    role: MessageRole
    content_type: ContentType
    content: str
    sender_name: str
    original_time: str | None


@dataclass
class RoleQualityReport:
    """Import quality report for role identification validation."""

    total_messages: int = 0
    patient_count: int = 0
    counselor_count: int = 0
    text_count: int = 0
    image_count: int = 0
    audio_count: int = 0
    skipped_empty: int = 0
    role_alternation_rate: float = 0.0
    unique_patient_names: list[str] = field(default_factory=list)
    unique_counselor_names: list[str] = field(default_factory=list)
    name_collision: bool = False
    quality_score: float = 0.0
    warnings: list[str] = field(default_factory=list)


@dataclass
class ParsedConversation:
    patient_name: str | None
    counselor_name: str | None
    messages: list[ParsedMessage]
    quality_report: RoleQualityReport | None = None


SYNC_PREFIX_PATTERN = re.compile(r"^\[同步消息\]\s*")
TIME_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})")
IMAGE_MARKERS = ("【图片消息】", "[图片]", "图片消息")
AUDIO_MARKERS = ("【语音消息】", "[语音]", "语音消息")
IMAGE_EXTENSIONS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".heic",
)
AUDIO_EXTENSIONS = (
    ".mp3",
    ".wav",
    ".amr",
    ".aac",
    ".m4a",
    ".ogg",
    ".opus",
)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def _extract_time(text: str) -> str | None:
    matched = TIME_PATTERN.search(text)
    if not matched:
        return None
    time_str = matched.group(1)
    try:
        datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        return time_str
    except ValueError:
        return None


def _extract_sender_name(raw_text: str, role: MessageRole) -> str:
    normalized = _normalize_text(raw_text)
    without_time = _normalize_text(TIME_PATTERN.sub("", normalized))
    if role == "patient":
        # 患者行格式通常是: 昵称 + 时间
        return without_time or "患者"

    # 咨询师格式通常为: 时间 + 机构名--医生名 + 咨询师名（最后一段）
    if " " in without_time:
        tail = without_time.split(" ")[-1].strip()
        if tail:
            return tail
    if without_time:
        return without_time
    return "咨询师"


def _normalize_media_url(value: str | None) -> str:
    if not value:
        return ""
    url = value.strip()
    if not url:
        return ""
    lowered = url.lower()
    if lowered.startswith(("javascript:", "data:text")):
        return ""
    return url


def _is_media_url(url: str, extensions: tuple[str, ...]) -> bool:
    lowered = url.lower()
    if lowered.startswith(("http://", "https://", "/")):
        return True
    return any(ext in lowered for ext in extensions)


def _extract_media_url(msg_div, *, media: Literal["image", "audio"]) -> str:
    if media == "image":
        candidates = []
        for tag in msg_div.find_all("img"):
            candidates.extend(
                [
                    tag.get("src"),
                    tag.get("data-src"),
                    tag.get("data-original"),
                    tag.get("data-url"),
                ]
            )
        for tag in msg_div.find_all("a"):
            candidates.extend([tag.get("href"), tag.get("data-src"), tag.get("data-url")])
        extensions = IMAGE_EXTENSIONS
    else:
        candidates = []
        for tag in msg_div.find_all(["audio", "source"]):
            candidates.extend([tag.get("src"), tag.get("data-src"), tag.get("data-url")])
        for tag in msg_div.find_all("a"):
            candidates.extend([tag.get("href"), tag.get("data-src"), tag.get("data-url")])
        extensions = AUDIO_EXTENSIONS

    for raw in candidates:
        url = _normalize_media_url(raw)
        if url and _is_media_url(url, extensions):
            return url
    return ""


def parse_vel_html(html_content: str) -> ParsedConversation:
    soup = BeautifulSoup(html_content, "html.parser")
    conversations = soup.select("div.conversation")

    messages: list[ParsedMessage] = []
    patient_name: str | None = None
    counselor_name: str | None = None

    for conv in conversations:
        nickname_div = conv.select_one("div.nickname-m")
        msg_div = conv.select_one("div.MsgRigth")
        if not nickname_div or not msg_div:
            continue

        classes = nickname_div.get("class", [])
        role: MessageRole = "counselor" if "text-right" in classes else "patient"
        nickname_text = nickname_div.get_text(" ", strip=True)

        sender_name = _extract_sender_name(nickname_text, role)
        original_time = _extract_time(nickname_text)

        content_type: ContentType = "text"
        raw_text = msg_div.get_text(" ", strip=True)
        content = SYNC_PREFIX_PATTERN.sub("", _normalize_text(raw_text))
        lowered = content.lower()

        image_url = _extract_media_url(msg_div, media="image")
        audio_url = _extract_media_url(msg_div, media="audio")
        has_image_marker = any(marker in content for marker in IMAGE_MARKERS)
        has_audio_marker = any(marker in content for marker in AUDIO_MARKERS)

        if image_url:
            content_type = "image"
            content = image_url
        elif audio_url:
            content_type = "audio"
            content = audio_url
        elif has_image_marker:
            content_type = "image"
            content = "图片消息（未导出原图链接）"
        elif has_audio_marker or "audio" in lowered:
            content_type = "audio"
            content = "语音消息（未导出音频链接）"
        else:
            content = SYNC_PREFIX_PATTERN.sub("", _normalize_text(content))

        messages.append(
            ParsedMessage(
                sequence=len(messages) + 1,
                role=role,
                content_type=content_type,
                content=content,
                sender_name=sender_name,
                original_time=original_time,
            )
        )

        if role == "patient" and not patient_name:
            patient_name = sender_name
        if role == "counselor" and not counselor_name:
            counselor_name = sender_name

    report = _build_quality_report(messages, patient_name, counselor_name)

    return ParsedConversation(
        patient_name=patient_name,
        counselor_name=counselor_name,
        messages=messages,
        quality_report=report,
    )


def parse_vel_html_streaming(html_content: str) -> ParsedConversation:
    """Stream-parse large HTML using lxml for reduced memory usage.

    Falls back to BeautifulSoup parser if lxml cannot handle the format.
    Use for files > 2MB.
    """
    from lxml import etree
    import io

    messages: list[ParsedMessage] = []
    patient_name: str | None = None
    counselor_name: str | None = None

    try:
        parser = etree.HTMLParser(encoding="utf-8")
        tree = etree.parse(io.StringIO(html_content), parser)
        root = tree.getroot()

        for conv in root.iter():
            classes = conv.get("class", "")
            if "conversation" not in classes:
                continue

            nickname_div = None
            msg_div = None
            for child in conv:
                child_classes = child.get("class", "")
                if "nickname-m" in child_classes:
                    nickname_div = child
                elif "MsgRigth" in child_classes:
                    msg_div = child

            if nickname_div is None or msg_div is None:
                continue

            nd_classes = nickname_div.get("class", "")
            role: MessageRole = "counselor" if "text-right" in nd_classes else "patient"
            nickname_text = _normalize_text(
                " ".join(nickname_div.itertext())
            )

            sender_name = _extract_sender_name(nickname_text, role)
            original_time = _extract_time(nickname_text)

            raw_text = _normalize_text(" ".join(msg_div.itertext()))
            content = SYNC_PREFIX_PATTERN.sub("", raw_text)
            lowered = content.lower()

            content_type: ContentType = "text"
            has_image_marker = any(marker in content for marker in IMAGE_MARKERS)
            has_audio_marker = any(marker in content for marker in AUDIO_MARKERS)

            image_url = ""
            for img in msg_div.iter("img"):
                for attr in ("src", "data-src", "data-original", "data-url"):
                    url = _normalize_media_url(img.get(attr))
                    if url and _is_media_url(url, IMAGE_EXTENSIONS):
                        image_url = url
                        break
                if image_url:
                    break

            audio_url = ""
            for tag in msg_div.iter("audio", "source"):
                for attr in ("src", "data-src", "data-url"):
                    url = _normalize_media_url(tag.get(attr))
                    if url and _is_media_url(url, AUDIO_EXTENSIONS):
                        audio_url = url
                        break
                if audio_url:
                    break

            if image_url:
                content_type = "image"
                content = image_url
            elif audio_url:
                content_type = "audio"
                content = audio_url
            elif has_image_marker:
                content_type = "image"
                content = "图片消息（未导出原图链接）"
            elif has_audio_marker or "audio" in lowered:
                content_type = "audio"
                content = "语音消息（未导出音频链接）"

            messages.append(ParsedMessage(
                sequence=len(messages) + 1,
                role=role,
                content_type=content_type,
                content=content,
                sender_name=sender_name,
                original_time=original_time,
            ))

            if role == "patient" and not patient_name:
                patient_name = sender_name
            if role == "counselor" and not counselor_name:
                counselor_name = sender_name

    except Exception:
        return parse_vel_html(html_content)

    if not messages:
        return parse_vel_html(html_content)

    report = _build_quality_report(messages, patient_name, counselor_name)
    return ParsedConversation(
        patient_name=patient_name,
        counselor_name=counselor_name,
        messages=messages,
        quality_report=report,
    )


STREAMING_THRESHOLD_BYTES = 2 * 1024 * 1024


def parse_html_auto(html_content: str) -> ParsedConversation:
    """Auto-select parser: streaming lxml for large files, BeautifulSoup for small."""
    if len(html_content.encode("utf-8", errors="ignore")) > STREAMING_THRESHOLD_BYTES:
        return parse_vel_html_streaming(html_content)
    return parse_vel_html(html_content)


def _build_quality_report(
    messages: list[ParsedMessage],
    patient_name: str | None,
    counselor_name: str | None,
) -> RoleQualityReport:
    """Analyze conversation quality: role distribution, alternation, name collision."""
    report = RoleQualityReport(total_messages=len(messages))

    if not messages:
        report.warnings.append("对话为空，无消息")
        return report

    patient_names: set[str] = set()
    counselor_names: set[str] = set()

    for m in messages:
        if m.role == "patient":
            report.patient_count += 1
            if m.sender_name:
                patient_names.add(m.sender_name)
        else:
            report.counselor_count += 1
            if m.sender_name:
                counselor_names.add(m.sender_name)
        if m.content_type == "text":
            report.text_count += 1
        elif m.content_type == "image":
            report.image_count += 1
        elif m.content_type == "audio":
            report.audio_count += 1

    report.unique_patient_names = sorted(patient_names)
    report.unique_counselor_names = sorted(counselor_names)

    name_overlap = patient_names & counselor_names
    if name_overlap:
        report.name_collision = True
        report.warnings.append(
            f"角色冲突：{', '.join(name_overlap)} 同时被标记为患者和咨询师"
        )

    if len(messages) >= 2:
        alternations = sum(
            1
            for i in range(1, len(messages))
            if messages[i].role != messages[i - 1].role
        )
        report.role_alternation_rate = round(alternations / (len(messages) - 1), 3)

    if report.patient_count == 0:
        report.warnings.append("未识别到任何患者消息，请确认 HTML 结构是否正确")
    if report.counselor_count == 0:
        report.warnings.append("未识别到任何咨询师消息，请确认 HTML 结构是否正确")

    total = report.total_messages
    if total > 0:
        patient_ratio = report.patient_count / total
        counselor_ratio = report.counselor_count / total
        if patient_ratio < 0.1 or patient_ratio > 0.9:
            report.warnings.append(
                f"角色比例异常：患者 {report.patient_count}/{total} "
                f"({patient_ratio:.0%})，咨询师 {report.counselor_count}/{total} "
                f"({counselor_ratio:.0%})"
            )

    score = 1.0
    if report.name_collision:
        score -= 0.3
    if report.patient_count == 0 or report.counselor_count == 0:
        score -= 0.4
    if total > 0 and report.text_count / total < 0.3:
        score -= 0.2
        report.warnings.append("文本消息占比过低，大部分为图片/语音占位")
    if report.role_alternation_rate < 0.15 and total >= 5:
        score -= 0.1
        report.warnings.append("角色交替率过低，可能存在角色识别错误")
    report.quality_score = round(max(0.0, min(1.0, score)), 2)

    return report
