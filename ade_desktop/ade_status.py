"""What the header says about Ade OS.

Pure functions decide the words; the client only fetches. Unreachable,
blocked and degraded are three different states and must never render as
one another.
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from ade_desktop.net import get_json

DEFAULT_ADE_URL = "http://127.0.0.1:8300"

# A sentinel, never a default of True/False: a payload that does not say
# whether tools may run must not be read as an answer either way.
_MISSING = object()


def ade_base() -> str:
    """ADE_DESKTOP_ADE_URL, or the main Ade OS on :8300. Prefixed on
    purpose: LLM_* names are set user-wide on this machine and point at a
    dead port."""
    return (os.environ.get("ADE_DESKTOP_ADE_URL") or DEFAULT_ADE_URL).rstrip("/")


def _trim(value, limit: int = 300) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _error_text(error) -> str:
    """Three different failures, worded apart: an error envelope from Ade
    OS, an answer that was not health at all (a proxy's 502 page), and no
    answer. A slow Ade OS is not the same as a stopped one."""
    if isinstance(error, dict):
        code = error.get("code") or "error"
        message = error.get("message") or ""
        return f"Ade OS error: {code} - {message}".rstrip(" -")
    text = str(error)
    if text.startswith("HTTP "):
        return f"answered, but not with health: {text}"
    if "Timeout" in text.split(":", 1)[0]:
        return f"no answer in time: {text}"
    return f"unreachable: {text}"


def health_pill(payload) -> tuple[str, str, str]:
    """(label, tone, tooltip) for a /v1/health payload.

    /v1/health answers 503 WITH this body when may_execute_tools is false,
    so BLOCKED arrives as a body, not as a transport error."""
    if not isinstance(payload, dict):
        return ("UNKNOWN", "off", _trim(payload))
    if "error" in payload:
        return ("DOWN", "bad", _error_text(payload["error"]))
    may = payload.get("may_execute_tools", _MISSING)
    if may is False:
        return ("BLOCKED", "bad",
                str(payload.get("blocking_reason") or "tools blocked"))
    subsystems = payload.get("subsystems")
    if not isinstance(subsystems, dict):
        subsystems = {}
    status = payload.get("status", _MISSING)
    if may is True and status == "up":
        lines = [f"{name}: {info.get('detail', '')}"
                 for name, info in subsystems.items() if isinstance(info, dict)]
        return ("UP", "ok", "\n".join(lines))
    if may is True and status == "down":
        down = [name for name, info in subsystems.items()
                if isinstance(info, dict) and info.get("up") is False]
        return ("DEGRADED", "warn", "down: " + (", ".join(down) or "unspecified"))
    return ("UNKNOWN", "off", _trim(payload))


def is_active(payload) -> bool | None:
    """/v1/activity's answer: True if Ade has work in flight, False if it
    says it has none, None if it could not say (an error is not "idle")."""
    if not isinstance(payload, dict) or "error" in payload:
        return None
    active, count = payload.get("active"), payload.get("count")
    if active is None and count is None:
        return None
    try:
        return bool(active) or int(count or 0) > 0
    except (TypeError, ValueError):
        return bool(active)


def is_online(payload) -> bool:
    """The orb's online: Ade OS answered /v1/health at all. BLOCKED and
    DEGRADED are reachable; DOWN and UNKNOWN are not."""
    return health_pill(payload)[0] in ("UP", "DEGRADED", "BLOCKED")


def brain_name(payload) -> str:
    """resolved.brain from /v1/settings -- the one field that NAMES the
    brain. Never derived from `mode`: LM Studio and DeepSeek share
    mode == cloud, and a loopback server once announced that its prompts
    were leaving the machine."""
    if not isinstance(payload, dict) or "error" in payload:
        return "—"
    resolved = payload.get("resolved")
    if isinstance(resolved, dict):
        brain = resolved.get("brain")
        if isinstance(brain, str) and brain.strip():
            return brain.strip()
    return "—"


class AdeStatusClient(QObject):
    """Polls /v1/health (5 s), /v1/settings (30 s) and /v1/activity (2 s,
    the orb's "is Ade working" -- a cheap GET) off the UI thread.

    A signal emitted from a worker thread to an object on the GUI thread is
    queued by Qt -- the trader's JsonPoller uses the same model. A poll still
    in flight when its timer fires is skipped, never stacked behind a slow
    Ade OS."""

    health = Signal(dict)
    settings = Signal(dict)
    activity = Signal(dict)

    def __init__(self, base: str | None = None, *, health_ms: int = 5000,
                 settings_ms: int = 30000, activity_ms: int = 2000,
                 fetch: Callable[[str], dict] = get_json,
                 parent=None) -> None:
        super().__init__(parent)
        self.base = (base or ade_base()).rstrip("/")
        self._fetch = fetch
        self._pool = ThreadPoolExecutor(max_workers=3,
                                        thread_name_prefix="ade-status")
        self._inflight: set[str] = set()
        self._lock = threading.Lock()
        self._stopped = False
        self._health_timer = QTimer(self)
        self._health_timer.setInterval(health_ms)
        self._health_timer.timeout.connect(self.poll_health)
        self._settings_timer = QTimer(self)
        self._settings_timer.setInterval(settings_ms)
        self._settings_timer.timeout.connect(self.poll_settings)
        self._activity_timer = QTimer(self)
        self._activity_timer.setInterval(activity_ms)
        self._activity_timer.timeout.connect(self.poll_activity)

    def start(self) -> None:
        self._health_timer.start()
        self._settings_timer.start()
        self._activity_timer.start()
        self.poll_health()
        self.poll_settings()
        self.poll_activity()

    def stop(self) -> None:
        """Stop polling for good, and wait for a poll in flight -- at most
        one fetch timeout. Called at quit: a worker still running would
        emit on, or drop the last reference to, an object the main thread
        is tearing down (found in review, 2026-09-17)."""
        self._stopped = True
        self._health_timer.stop()
        self._settings_timer.stop()
        self._activity_timer.stop()
        self._pool.shutdown(wait=True, cancel_futures=True)

    def poll_health(self) -> None:
        self._poll("health", "/v1/health", self.health)

    def poll_settings(self) -> None:
        self._poll("settings", "/v1/settings", self.settings)

    def poll_activity(self) -> None:
        self._poll("activity", "/v1/activity", self.activity)

    def _poll(self, key: str, path: str, signal) -> None:
        with self._lock:
            if self._stopped or key in self._inflight:
                return
            self._inflight.add(key)

        def work() -> None:
            try:
                body = self._fetch(self.base + path)
            except Exception as exc:  # noqa: BLE001 -- unreachable is a state
                body = {"error": f"{type(exc).__name__}: {exc}"}
            finally:
                with self._lock:
                    self._inflight.discard(key)
            signal.emit(body if isinstance(body, dict)
                        else {"error": "non-dict reply"})

        self._pool.submit(work)
