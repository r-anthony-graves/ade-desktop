"""The panel's threads on disk: chat, shell, the archive (session memory),
attached skills and the active tab.

The avatar's formats and caps (adeos/avatar/threads-store.js), in a file of
its own: history starts fresh (Ray, 2026-09-18) because the main Ade OS never
took part in the avatar twin's conversation.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

TABS = ("chat", "shell")
MAX_MESSAGES = 4000   # the avatar's safety cap per tab
MAX_ARCHIVE = 20      # newest batches kept
COMPACT_KEEP = 20


class ThreadStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.chat: list[dict] = []
        self.shell: list[dict] = []
        self.archive: list[dict] = []
        self.skills: list[str] = []
        self.tab = "chat"
        self.load_note: str | None = None
        self._load()

    def tab_messages(self, tab: str) -> list[dict]:
        return self.shell if tab == "shell" else self.chat

    def push(self, tab, role, kind, text, meta=None) -> dict:
        now = int(time.time() * 1000)
        msg = {"id": f"{now}-{uuid.uuid4().hex[:6]}", "ts": now, "role": role,
               "kind": kind, "text": "" if text is None else str(text),
               "meta": dict(meta or {})}
        self.tab_messages(tab).append(msg)
        return msg

    def _archive_push(self, tab, messages) -> None:
        self.archive.append({"at": int(time.time() * 1000), "tab": tab,
                             "messages": messages})
        del self.archive[:-MAX_ARCHIVE]

    def clear(self, tab) -> int:
        """Move the tab into the archive. A running turn's working line
        stays: it belongs to a call that has not finished."""
        live = self.tab_messages(tab)
        moved = [m for m in live if m.get("kind") != "working"]
        if not moved:
            return 0
        self._archive_push(tab, moved)
        live[:] = [m for m in live if m.get("kind") == "working"]
        return len(moved)

    def compact(self, tab) -> int | None:
        live = self.tab_messages(tab)
        if len(live) <= COMPACT_KEEP:
            return None
        moved = live[:-COMPACT_KEEP]
        self._archive_push(tab, moved)
        live[:] = live[-COMPACT_KEEP:]
        return len(moved)

    def restore(self) -> tuple[str, int] | None:
        if not self.archive:
            return None
        entry = self.archive.pop()
        tab = entry.get("tab") if entry.get("tab") in TABS else "chat"
        messages = list(entry.get("messages") or [])
        self.tab_messages(tab)[:0] = messages
        return tab, len(messages)

    def _load(self) -> None:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError:
            return
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("not an object")
        except ValueError:
            aside = self.path.with_name(
                self.path.name + ".bad-" + time.strftime("%Y%m%d-%H%M%S"))
            try:
                os.replace(self.path, aside)
                self.load_note = (f"{self.path.name} could not be read; it was "
                                  f"set aside as {aside.name} and the panel "
                                  "started empty.")
            except OSError:
                self.load_note = (f"{self.path.name} could not be read and "
                                  "could not be moved aside.")
            return
        for tab in TABS:
            if isinstance(data.get(tab), list):
                setattr(self, tab, [m for m in data[tab]
                                    if isinstance(m, dict)][-MAX_MESSAGES:])
        if isinstance(data.get("archive"), list):
            self.archive = [a for a in data["archive"]
                            if isinstance(a, dict)][-MAX_ARCHIVE:]
        if isinstance(data.get("skills"), list):
            self.skills = [s for s in data["skills"] if isinstance(s, str)]
        if data.get("tab") in TABS:
            self.tab = data["tab"]

    def save(self) -> None:
        """Atomic: a temp file then os.replace, so an interrupted write never
        leaves a half file. Best effort: a failed save never raises."""
        def keep(msgs):
            return [m for m in msgs if m.get("kind") != "working"][-MAX_MESSAGES:]
        out = {"chat": keep(self.chat), "shell": keep(self.shell),
               "archive": self.archive[-MAX_ARCHIVE:],
               "skills": list(self.skills), "tab": self.tab}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(out, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass
