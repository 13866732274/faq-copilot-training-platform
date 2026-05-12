from pathlib import Path

from app.services.html_parser import parse_vel_html


def main() -> None:
    sample = Path("/www/wwwroot/朱梦宇-未识别的名称-Y.html")
    html = sample.read_text(encoding="utf-8")
    parsed = parse_vel_html(html)
    print("patient_name:", parsed.patient_name)
    print("counselor_name:", parsed.counselor_name)
    print("message_count:", len(parsed.messages))
    for m in parsed.messages[:5]:
        print(
            f"[{m.sequence}] {m.role} {m.sender_name} {m.original_time} -> {m.content_type}: {m.content}"
        )


if __name__ == "__main__":
    main()
