"""
OpenClaw/WeChat watchdog (Windows).

Run every 60 seconds via Task Scheduler.
Checks:
  - WeChat.exe process
  - OpenClaw process
  - backend health endpoint
On failure: prints logs and optionally sends Feishu webhook alert.
"""

from __future__ import annotations

import subprocess
from datetime import datetime

import requests

BACKEND_HEALTH = "http://192.168.9.139/api/v1/health"
FEISHU_WEBHOOK = ""  # Fill your webhook URL
LOG_FILE = "watchdog_openclaw.log"


def _log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _check_process(name: str) -> bool:
    try:
        out = subprocess.run(["tasklist"], capture_output=True, text=True, timeout=10)
        return name.lower() in out.stdout.lower()
    except Exception:
        return False


def _check_backend() -> bool:
    try:
        r = requests.get(BACKEND_HEALTH, timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def _notify(msg: str) -> None:
    _log(f"ALERT: {msg}")
    if not FEISHU_WEBHOOK:
        return
    try:
        requests.post(
            FEISHU_WEBHOOK,
            json={"msg_type": "text", "content": {"text": f"[OpenClaw Watchdog] {msg}"}},
            timeout=5,
        )
    except Exception:
        pass


def main() -> None:
    issues: list[str] = []
    if not _check_process("WeChat.exe"):
        issues.append("WeChat.exe not running")
    # Process name may vary by installation; keep both checks.
    if not (_check_process("openclaw") or _check_process("OpenClaw")):
        issues.append("OpenClaw process not found")
    if not _check_backend():
        issues.append("Backend health check failed")

    if issues:
        _notify(" | ".join(issues))
    else:
        _log("OK")


if __name__ == "__main__":
    main()
