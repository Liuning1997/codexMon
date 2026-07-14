"""Read-only Codex usage data for the Moon Dashboard.

The dashboard reads local Codex state and the official read-only account
summary endpoint used by Codex Desktop for banked rate-limit resets. It never
writes to Codex's databases and never logs credentials or response payloads.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


USER_HOME = Path(os.environ.get("USERPROFILE", str(Path.home())))
CODEX_HOME = Path(os.environ.get("CODEX_HOME", str(USER_HOME / ".codex")))
CODEX_STATE_DB = Path(
    os.environ.get("CODEX_STATE_DB", str(CODEX_HOME / "state_5.sqlite"))
)
APP_DATA = Path(os.environ.get("APPDATA", str(USER_HOME / "AppData" / "Roaming")))
APP_STATE_DIR = APP_DATA / "CodexMoonDashboard"
SESSION_STATE_PATH = APP_STATE_DIR / "session.json"
MANUAL_RESET_ENDPOINT = os.environ.get(
    "CODEX_MANUAL_RESET_ENDPOINT",
    "https://chatgpt.com/backend-api/wham/rate-limit-reset-credits",
)
MANUAL_RESET_CACHE_TTL = 60.0

_manual_reset_lock = threading.Lock()
_manual_reset_fetching = False
_manual_reset_cache: Dict[str, Any] = {
    "available_count": None,
    "nearest_expiry": None,
    "status": "等待账户摘要同步",
    "updated_at": 0.0,
}


@dataclass(frozen=True)
class ThreadUsage:
    thread_id: str
    created_at_ms: int
    updated_at_ms: int
    tokens_used: int
    model: str
    title: str


def _now_ms() -> int:
    return int(time.time() * 1000)


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write_json(path: Path, value: Dict[str, Any]) -> None:
    APP_STATE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


def read_session_state() -> Dict[str, Any]:
    return _read_json(SESSION_STATE_PATH)


def is_manually_dismissed(lifecycle_id: str) -> bool:
    return read_session_state().get("manual_dismissed_for") == lifecycle_id


def mark_manually_dismissed(lifecycle_id: str) -> None:
    state = read_session_state()
    state["manual_dismissed_for"] = lifecycle_id
    _write_json(SESSION_STATE_PATH, state)


def clear_dismissal() -> None:
    state = read_session_state()
    if state.get("manual_dismissed_for") is not None:
        state["manual_dismissed_for"] = None
        _write_json(SESSION_STATE_PATH, state)


def read_threads() -> List[ThreadUsage]:
    """Read thread totals from Codex's state database without taking a write lock."""

    if not CODEX_STATE_DB.exists():
        return []

    connection: Optional[sqlite3.Connection] = None
    try:
        uri = "file:{}?mode=ro".format(CODEX_STATE_DB.as_posix())
        connection = sqlite3.connect(uri, uri=True, timeout=0.25)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 250")
        rows = connection.execute(
            """
            SELECT id, created_at_ms, updated_at_ms, tokens_used,
                   COALESCE(model, ''), COALESCE(title, '')
            FROM threads
            WHERE COALESCE(tokens_used, 0) >= 0
            """
        ).fetchall()
        result: List[ThreadUsage] = []
        for row in rows:
            result.append(
                ThreadUsage(
                    thread_id=str(row[0]),
                    created_at_ms=int(row[1] or 0),
                    updated_at_ms=int(row[2] or 0),
                    tokens_used=max(0, int(row[3] or 0)),
                    model=str(row[4] or ""),
                    title=str(row[5] or ""),
                )
            )
        return result
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return []
    finally:
        if connection is not None:
            connection.close()


def _session_tokens(
    threads: Iterable[ThreadUsage], lifecycle_id: str, started_at_ms: int
) -> int:
    """Calculate the delta since this Codex process lifecycle began."""

    current = list(threads)
    state = read_session_state()
    if state.get("lifecycle_id") != lifecycle_id:
        baseline: Dict[str, int] = {}
        for thread in current:
            # Existing threads are baselined; threads created after Codex opened
            # count from zero, which makes a newly-created thread immediately useful.
            baseline[thread.thread_id] = (
                thread.tokens_used if thread.created_at_ms < started_at_ms else 0
            )
        state = {
            "lifecycle_id": lifecycle_id,
            "started_at_ms": started_at_ms,
            "baseline": baseline,
            "manual_dismissed_for": None,
        }
        _write_json(SESSION_STATE_PATH, state)
    else:
        baseline = state.get("baseline", {})
        if not isinstance(baseline, dict):
            baseline = {}
        changed = False
        for thread in current:
            if thread.thread_id not in baseline:
                baseline[thread.thread_id] = (
                    thread.tokens_used if thread.created_at_ms < started_at_ms else 0
                )
                changed = True
        if changed:
            state["baseline"] = baseline
            _write_json(SESSION_STATE_PATH, state)

    baseline = state.get("baseline", {})
    if not isinstance(baseline, dict):
        baseline = {}
    total = 0
    for thread in current:
        previous = int(baseline.get(thread.thread_id, 0) or 0)
        total += max(0, thread.tokens_used - previous)
    return total


def _recent_usage(threads: Iterable[ThreadUsage], days: int, now_ms: int) -> int:
    cutoff = now_ms - days * 24 * 60 * 60 * 1000
    return sum(thread.tokens_used for thread in threads if thread.updated_at_ms >= cutoff)


def _daily_usage(threads: Iterable[ThreadUsage], days: int, now_ms: int) -> List[Dict[str, Any]]:
    today = datetime.now().date()
    totals: Dict[str, int] = {}
    cutoff = now_ms - days * 24 * 60 * 60 * 1000
    for thread in threads:
        if thread.updated_at_ms < cutoff:
            continue
        date_value = datetime.fromtimestamp(thread.updated_at_ms / 1000).date()
        key = date_value.isoformat()
        totals[key] = totals.get(key, 0) + thread.tokens_used

    result: List[Dict[str, Any]] = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        key = day.isoformat()
        result.append({"label": day.strftime("%m/%d"), "tokens": totals.get(key, 0)})
    return result


def _read_latest_rate_limit() -> Dict[str, Any]:
    """Read only the tail of the newest rollout file for rate-limit metadata."""

    sessions_dir = CODEX_HOME / "sessions"
    try:
        candidates = list(sessions_dir.rglob("rollout-*.jsonl"))
        if not candidates:
            return {}
        latest = max(candidates, key=lambda path: path.stat().st_mtime_ns)
        with latest.open("rb") as handle:
            handle.seek(max(0, latest.stat().st_size - 256_000))
            text = handle.read().decode("utf-8", errors="ignore")
        latest_rate: Dict[str, Any] = {"rollout_mtime": latest.stat().st_mtime}
        for line in text.splitlines():
            try:
                item = json.loads(line)
            except (ValueError, TypeError):
                continue
            payload = item.get("payload", {})
            if item.get("type") != "event_msg" or payload.get("type") != "token_count":
                continue
            limits = payload.get("rate_limits") or {}
            primary = limits.get("primary") or {}
            if primary:
                latest_rate = {
                    "used_percent": float(primary.get("used_percent", 0) or 0),
                    "window_minutes": int(primary.get("window_minutes", 0) or 0),
                    "resets_at": int(primary.get("resets_at", 0) or 0),
                    "rollout_mtime": latest.stat().st_mtime,
                }
        return latest_rate
    except (OSError, ValueError, TypeError):
        return {}


def _parse_expiry_timestamp(value: Any) -> Optional[float]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        normalized = value.strip().replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def _format_expiry_timestamp(timestamp: Optional[float]) -> str:
    if timestamp is None:
        return "--"
    try:
        return datetime.fromtimestamp(timestamp).strftime("%m/%d %H:%M")
    except (TypeError, ValueError, OverflowError, OSError):
        return "--"


def _read_manual_reset_info() -> Dict[str, Any]:
    """Read the same banked-reset summary used by Codex Desktop."""

    auth = _read_json(CODEX_HOME / "auth.json")
    tokens = auth.get("tokens") if isinstance(auth, dict) else None
    if not isinstance(tokens, dict):
        return {
            "available_count": None,
            "nearest_expiry": None,
            "status": "等待账户摘要同步",
        }

    access_token = tokens.get("access_token")
    account_id = tokens.get("account_id")
    if not isinstance(access_token, str) or not access_token.strip():
        return {
            "available_count": None,
            "nearest_expiry": None,
            "status": "等待账户摘要同步",
        }

    headers = {
        "Accept": "application/json",
        "Authorization": "Bearer " + access_token,
        "Originator": "Codex Desktop",
        "OAI-Language": "zh-CN",
        "User-Agent": "Codex Desktop",
    }
    if isinstance(account_id, str) and account_id.strip():
        headers["ChatGPT-Account-ID"] = account_id

    request = urllib.request.Request(MANUAL_RESET_ENDPOINT, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, ValueError, TypeError):
        return {
            "available_count": None,
            "nearest_expiry": None,
            "status": "账户摘要暂不可用",
        }

    if not isinstance(payload, dict):
        return {
            "available_count": None,
            "nearest_expiry": None,
            "status": "账户摘要暂不可用",
        }

    credits = payload.get("credits")
    available_credits = [
        credit
        for credit in credits
        if isinstance(credit, dict) and credit.get("status") == "available"
    ] if isinstance(credits, list) else []

    available_count = payload.get("available_count")
    if isinstance(available_count, bool):
        available_count = None
    if not isinstance(available_count, int):
        available_count = len(available_credits)

    expiry_timestamps = [
        timestamp
        for timestamp in (_parse_expiry_timestamp(item.get("expires_at")) for item in available_credits)
        if timestamp is not None and timestamp >= time.time()
    ]
    return {
        "available_count": max(0, available_count),
        "nearest_expiry": min(expiry_timestamps) if expiry_timestamps else None,
        "status": "账户摘要已同步",
    }


def _refresh_manual_reset_info() -> None:
    global _manual_reset_fetching
    try:
        result = _read_manual_reset_info()
    except Exception:
        result = {
            "available_count": None,
            "nearest_expiry": None,
            "status": "账户摘要暂不可用",
        }
    with _manual_reset_lock:
        _manual_reset_cache.update(result)
        _manual_reset_cache["updated_at"] = time.time()
        _manual_reset_fetching = False


def _manual_reset_snapshot() -> Dict[str, Any]:
    global _manual_reset_fetching
    now = time.time()
    with _manual_reset_lock:
        snapshot = dict(_manual_reset_cache)
        is_stale = now - float(snapshot.get("updated_at", 0.0) or 0.0) >= MANUAL_RESET_CACHE_TTL
        if is_stale and not _manual_reset_fetching:
            _manual_reset_fetching = True
            threading.Thread(target=_refresh_manual_reset_info, daemon=True).start()
    return snapshot


def _window_label(window_minutes: int) -> str:
    if window_minutes >= 10080:
        return "7 天滚动窗口"
    if window_minutes >= 1440:
        return "近期滚动窗口"
    if window_minutes > 0:
        return "账户滚动窗口"
    return "账户额度窗口"


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def format_tokens(value: int) -> str:
    if value >= 1_000_000_000:
        return "{:.1f}B".format(value / 1_000_000_000)
    if value >= 1_000_000:
        return "{:.1f}M".format(value / 1_000_000)
    if value >= 1_000:
        return "{:.1f}K".format(value / 1_000)
    return "{}".format(value)


def load_dashboard_data(lifecycle_id: str, started_at_ms: int) -> Dict[str, Any]:
    now_ms = _now_ms()
    threads = read_threads()
    recent_7d = _recent_usage(threads, 7, now_ms)
    recent_30d = _recent_usage(threads, 30, now_ms)
    session_tokens = _session_tokens(threads, lifecycle_id, started_at_ms)
    rate = _read_latest_rate_limit()
    rollout_mtime = float(rate.get("rollout_mtime", 0) or 0)
    db_mtime = 0.0
    try:
        db_mtime = CODEX_STATE_DB.stat().st_mtime
    except OSError:
        pass
    last_activity = max(rollout_mtime, db_mtime)
    is_working = last_activity > 0 and (time.time() - last_activity) <= 9.0
    used_percent = rate.get("used_percent")
    if used_percent is None or not math.isfinite(float(used_percent)):
        used_percent = 0.0
        remaining_percent = 100.0
        quota_status = "等待 Codex 额度同步"
    else:
        used_percent = _clamp(float(used_percent), 0.0, 100.0)
        remaining_percent = 100.0 - used_percent
        quota_status = _window_label(int(rate.get("window_minutes", 0) or 0))

    latest_thread = max(threads, key=lambda item: item.updated_at_ms, default=None)
    latest_update = "—"
    if latest_thread and latest_thread.updated_at_ms:
        latest_update = datetime.fromtimestamp(
            latest_thread.updated_at_ms / 1000
        ).strftime("%H:%M:%S")

    # `rate.resets_at` is the rolling quota window, not a banked manual reset.
    # Manual reset credits come from the official account summary below.
    manual_reset = _manual_reset_snapshot()
    manual_reset_count = manual_reset.get("available_count")
    manual_reset_expiry = manual_reset.get("nearest_expiry")
    auto_reset_at = rate.get("resets_at")
    auto_reset_time_label = _format_expiry_timestamp(auto_reset_at if auto_reset_at else None)
    if False:
        reset_time_label = datetime.fromtimestamp(reset_at).strftime("%m/%d %H:%M")
        remaining_seconds = max(0, reset_at - int(time.time()))
        if remaining_seconds >= 24 * 60 * 60:
            reset_eta_label = "约 {} 天".format(max(1, remaining_seconds // (24 * 60 * 60)))
        elif remaining_seconds >= 60 * 60:
            reset_eta_label = "约 {} 小时".format(max(1, remaining_seconds // (60 * 60)))
        else:
            reset_eta_label = "约 {} 分钟".format(max(1, remaining_seconds // 60))

    return {
        "recent_7d": recent_7d,
        "recent_7d_label": format_tokens(recent_7d),
        "recent_30d": recent_30d,
        "recent_30d_label": format_tokens(recent_30d),
        "session_tokens": session_tokens,
        "session_tokens_label": format_tokens(session_tokens),
        "used_percent": used_percent,
        "remaining_percent": remaining_percent,
        "quota_status": quota_status,
        "manual_reset_count": manual_reset_count,
        "manual_reset_count_label": (
            "--" if manual_reset_count is None else str(manual_reset_count)
        ),
        "manual_reset_expiry_label": _format_expiry_timestamp(manual_reset_expiry),
        "auto_reset_time_label": auto_reset_time_label,
        "manual_reset_status": manual_reset.get("status", "等待账户摘要同步"),
        "moon_ratio": _clamp(remaining_percent / 100.0, 0.02, 1.0),
        "is_working": is_working,
        "daily": _daily_usage(threads, 7, now_ms),
        "thread_count": len(threads),
        "latest_update": latest_update,
        "db_path": str(CODEX_STATE_DB),
        "refreshed_at": datetime.now().strftime("%H:%M:%S"),
    }
