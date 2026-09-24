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

# The Shell tab left on 2026-09-24 (requirement 1). "shell" is no longer a
# tab -- but every existing threads-*.json still HAS one, and save() writes
# a fixed dict, so dropping it from here without the _legacy_shell handling
# below would delete every section's saved shell history on the first save
# after the upgrade. Nothing reads it; nothing loses it either.
TABS = ("chat",)
MAX_MESSAGES = 4000   # the avatar's safety cap per tab
MAX_ARCHIVE = 20      # newest batches kept
COMPACT_KEEP = 20


def live_approval(m) -> bool:
    """A card still waiting for a decision. It NEVER leaves the thread by
    clear, compact or reset: the watcher announces an id once, so an
    archived live card would sit unseen until it timed out -- and a timeout
    denies (review finding, 2026-09-18)."""
    meta = m.get("meta") or {}
    return (m.get("kind") == "approval" and not meta.get("decided")
            and not meta.get("moot"))


def _stays(m) -> bool:
    """Messages clear/compact leave in place: a running turn's working line,
    and a live approval card."""
    return m.get("kind") == "working" or live_approval(m)


def _repair(m) -> dict | None:
    """One loaded message made safe to render: a string id, a dict meta,
    string role/kind/text. A non-dict is dropped."""
    if not isinstance(m, dict):
        return None
    m = dict(m)
    if not isinstance(m.get("id"), str) or not m["id"]:
        m["id"] = f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"
    if not isinstance(m.get("meta"), dict):
        m["meta"] = {}
    for key, default in (("role", "system"), ("kind", "text"), ("text", "")):
        if not isinstance(m.get(key), str):
            m[key] = default if m.get(key) is None else str(m[key])
    return m


class ThreadStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.chat: list[dict] = []
        self.shell: list[dict] = []     # legacy, never written to again
        # Set BEFORE _load(): that method returns early on a missing or
        # unreadable file, and save() reads this on every write. A default
        # assigned only on the happy path is an AttributeError the first
        # time a fresh install saves.
        self._legacy_shell: list = []
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
        """Move the tab into the archive. A running turn's working line and
        every live approval card stay."""
        live = self.tab_messages(tab)
        moved = [m for m in live if not _stays(m)]
        if not moved:
            return 0
        self._archive_push(tab, moved)
        live[:] = [m for m in live if _stays(m)]
        return len(moved)

    def compact(self, tab) -> int | None:
        live = self.tab_messages(tab)
        if len(live) <= COMPACT_KEEP:
            return None
        head, tail = live[:-COMPACT_KEEP], live[-COMPACT_KEEP:]
        moved = [m for m in head if not _stays(m)]
        if not moved:
            return None
        self._archive_push(tab, moved)
        live[:] = [m for m in head if _stays(m)] + tail
        return len(moved)

    def restore(self) -> tuple[str, int] | None:
        """Put the newest archived batch back. Any approval card in it comes
        back as answered-elsewhere, never live: whether it is still pending
        is the watcher's to say."""
        if not self.archive:
            return None
        entry = self.archive.pop()
        tab = entry.get("tab") if entry.get("tab") in TABS else "chat"
        messages = [r for r in (_repair(m) for m in entry.get("messages") or [])
                    if r is not None]
        for m in messages:
            if live_approval(m):
                m["meta"]["moot"] = True
        self.tab_messages(tab)[:0] = messages
        return tab, len(messages)

    def _load(self) -> None:
        try:
            raw = self.path.read_bytes()
        except OSError:
            return        # no file yet: the ordinary first start
        try:
            # Decoding is inside the try: a UTF-16 file raises
            # UnicodeDecodeError, a ValueError, and must be set aside like any
            # other unreadable file -- never stop the app starting (review
            # finding, 2026-09-18).
            data = json.loads(raw.decode("utf-8"))
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
        # Carried forward verbatim, never parsed: see the TABS comment.
        legacy = data.get("shell")
        self._legacy_shell = legacy if isinstance(legacy, list) else []
        for tab in TABS:
            if isinstance(data.get(tab), list):
                repaired = [r for r in (_repair(m) for m in data[tab])
                            if r is not None]
                setattr(self, tab, repaired[-MAX_MESSAGES:])
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
        out = {"chat": keep(self.chat), "shell": self._legacy_shell,
               "archive": self.archive[-MAX_ARCHIVE:],
               "skills": list(self.skills), "tab": self.tab}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(out, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass
