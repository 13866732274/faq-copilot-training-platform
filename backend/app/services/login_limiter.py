from __future__ import annotations

import math
import time
from threading import Lock

FAIL_WINDOW_SECONDS = 5 * 60
LOCK_SECONDS = 15 * 60
MAX_FAILS = 5

_state_lock = Lock()
_state: dict[str, dict[str, float | list[float]]] = {}


def _build_key(ip: str, username: str) -> str:
    safe_ip = (ip or "unknown").strip().lower()
    safe_username = (username or "").strip().lower()
    return f"{safe_ip}::{safe_username}"


def _prune_failures(failures: list[float], now_ts: float) -> list[float]:
    return [ts for ts in failures if now_ts - ts <= FAIL_WINDOW_SECONDS]


def check_allowed(ip: str, username: str) -> tuple[bool, int]:
    key = _build_key(ip, username)
    now_ts = time.time()
    with _state_lock:
        entry = _state.get(key)
        if not entry:
            return True, 0
        lock_until = float(entry.get("lock_until", 0) or 0)
        if lock_until > now_ts:
            remain_minutes = max(1, math.ceil((lock_until - now_ts) / 60))
            return False, remain_minutes
        failures = _prune_failures(list(entry.get("failures", [])), now_ts)
        if failures:
            entry["failures"] = failures
        else:
            _state.pop(key, None)
        return True, 0


def mark_failure(ip: str, username: str) -> None:
    key = _build_key(ip, username)
    now_ts = time.time()
    with _state_lock:
        entry = _state.setdefault(key, {"failures": [], "lock_until": 0})
        failures = _prune_failures(list(entry.get("failures", [])), now_ts)
        failures.append(now_ts)
        entry["failures"] = failures
        if len(failures) >= MAX_FAILS:
            entry["lock_until"] = now_ts + LOCK_SECONDS
            entry["failures"] = []


def mark_success(ip: str, username: str) -> None:
    key = _build_key(ip, username)
    with _state_lock:
        _state.pop(key, None)
