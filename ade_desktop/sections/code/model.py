"""Piece 7's pure rules. No Qt here: what a terminal frame means, what the
Problems list says for an answer, how the tree orders a listing, and the
command line's recall."""

from __future__ import annotations

import json
import os
import re

from ade_desktop.conversation.replies import error_cause

# CSI (colours, cursor moves), OSC (window titles, ended by BEL or ESC \),
# and any other two-character escape. Only ever matched from an ESC.
_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\-_])")

LISTING_LIMIT = 500          # adeos/api/fs.py MAX_ENTRIES


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text or "").rstrip("\r")


def parse_frame(line: str) -> tuple[str, object]:
    """One NDJSON line from /v1/terminal/run: ("out", text), ("exit", code),
    ("error", text) -- or ("raw", line) for anything else, which is shown
    as it came rather than dropped."""
    try:
        frame = json.loads(line)
    except ValueError:
        return ("raw", line)
    if not isinstance(frame, dict):
        return ("raw", line)
    kind = frame.get("type")
    if kind in ("out", "error") and isinstance(frame.get("text"), str):
        return (kind, frame["text"])
    code = frame.get("code")
    if kind == "exit" and isinstance(code, int) and not isinstance(code, bool):
        return ("exit", code)
    return ("raw", line)


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def diag_summary(counts) -> str:
    counts = counts if isinstance(counts, dict) else {}
    parts = [_plural(int(counts.get(key) or 0), one, many)
             for key, one, many in (("error", "error", "errors"),
                                    ("warning", "warning", "warnings"),
                                    ("info", "note", "notes"))
             if counts.get(key)]
    return ", ".join(parts) or "No problems"


def diag_note(result, path: str) -> str | None:
    """What to say instead of a list, or None when the answer IS a list.
    An empty list must only ever mean "the checker found nothing"."""
    if isinstance(result, dict) and result.get("ok") is True and isinstance(
            result.get("data"), dict):
        return None
    if not isinstance(result, dict):
        return "The checker gave no answer."
    err = result.get("error")
    if isinstance(err, str):
        return f"Ade OS is not answering ({err})."
    if not isinstance(err, dict):
        return "The checker gave no answer."
    code, message = err.get("code"), str(err.get("message") or "")
    if code == "lsp_no_server" and message.startswith("no language server for"):
        ext = os.path.splitext(path)[1] or os.path.basename(path)
        return f"No checker for {ext} files."
    if code == "lsp_timeout":
        return "The checker did not answer in time. Refresh to ask again."
    if code == "lsp_server_down":
        return f"The checker is not running: {message}"
    return f"Could not check it: {message or error_cause(result)}"


def dirs_first(entries: list[dict]) -> list[dict]:
    return sorted(entries, key=lambda e: (e.get("kind") != "dir",
                                          str(e.get("name", "")).lower()))


def listing_note(entries: list) -> str | None:
    if len(entries) >= LISTING_LIMIT:
        return (f"Only the first {LISTING_LIMIT} entries are shown "
                "(Ade OS lists no more). The terminal lists the rest.")
    return None


def tab_title(path: str, dirty: bool) -> str:
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    return name + (" •" if dirty else "")


class History:
    """Up/Down recall for the command line. Walking up keeps what was being
    typed; walking back down past the newest returns it."""

    def __init__(self, limit: int = 200) -> None:
        self._items: list[str] = []
        self._limit = limit
        self._at: int | None = None
        self._draft = ""

    def add(self, cmd: str) -> None:
        cmd = cmd.strip()
        if cmd and (not self._items or self._items[-1] != cmd):
            self._items.append(cmd)
            del self._items[:-self._limit]
        self._at = None
        self._draft = ""

    def prev(self, current: str) -> str:
        if not self._items:
            return current
        if self._at is None:
            self._draft = current
            self._at = len(self._items)
        self._at = max(0, self._at - 1)
        return self._items[self._at]

    def next(self, current: str) -> str:
        """Down. Not walking the history, it leaves the line as it is."""
        if self._at is None:
            return current
        self._at += 1
        if self._at >= len(self._items):
            self._at = None
            return self._draft
        return self._items[self._at]
