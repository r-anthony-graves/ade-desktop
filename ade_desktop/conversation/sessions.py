"""A chat per section (Ray, 2026-09-18: "create chat sessions for each so
chats dont overlap").

Each section's chat has its own thread file, Ade OS topic and terminal
session, and its own busy state, so a question in PM never lands in QA and
one long ask never blocks another section. General keeps what it had --
threads.json, topic u/local/desktop, terminal session ade-desktop -- so
today's history is still there.

Approvals come from ONE watcher (they are Ade OS-wide) and go to the chat
whose turn raised them: Ade OS tags each record with its turn_id, and each
chat knows its running turn. Anything no chat owns -- a workflow, the web,
the CLI, an older Ade OS -- goes to General, once. A card's vanish follows
it to wherever it went, even after its turn has ended.
"""

from __future__ import annotations

import re
import weakref
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from ade_desktop.conversation.client import SESSION, TOPIC

GENERAL = "General"


@dataclass(frozen=True)
class SessionSpec:
    name: str
    slug: str
    threads_file: str       # beside window.json
    topic: str              # the Ade OS conversation topic
    terminal: str           # the Ade OS terminal session (! and bare commands)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "section"


def session_for(name: str) -> SessionSpec:
    if name == GENERAL:
        return SessionSpec(name, "general", "threads.json", TOPIC, SESSION)
    slug = _slug(name)
    # "chat" in the terminal name: the Code section's own terminal pane is
    # ade-desktop-code, and a chat must never share (and 409) it.
    return SessionSpec(name, slug, f"threads-{slug}.json", f"{TOPIC}-{slug}",
                       f"ade-desktop-chat-{slug}")


class SessionWatcher(QObject):
    """What one chat sees of the approvals. Same shape as ApprovalWatcher,
    so a panel cannot tell the difference. Holds its router weakly: the
    router owns it (as its Qt parent), never the other way round."""

    appeared = Signal(object)
    vanished = Signal(str)

    def __init__(self, router) -> None:
        super().__init__(router)
        self._router = weakref.ref(router)

    def start(self) -> None:
        router = self._router()
        if router is not None:
            router.start()

    def stop(self) -> None:
        router = self._router()
        if router is not None:
            router.stop()

    def pending_count(self) -> int:
        router = self._router()
        return router.pending_count() if router is not None else 0


class ApprovalRouter(QObject):
    def __init__(self, source, parent=None) -> None:
        super().__init__(parent)
        self.source = source
        self._watchers: dict[str, SessionWatcher] = {}
        self._chats: dict[str, weakref.ref] = {}
        self._where: dict[str, str] = {}           # approval id -> chat name
        self._running = False
        source.appeared.connect(self._on_appeared)
        source.vanished.connect(self._on_vanished)

    def watcher_for(self, name: str) -> SessionWatcher:
        if name not in self._watchers:
            self._watchers[name] = SessionWatcher(self)
        return self._watchers[name]

    def bind(self, name: str, chat) -> None:
        """`chat` answers owns_turn(turn_id). Held weakly."""
        self.watcher_for(name)
        self._chats[name] = weakref.ref(chat)

    def start(self) -> None:
        if not self._running:
            self._running = True
            self.source.start()

    def stop(self) -> None:
        if self._running:
            self._running = False
            self.source.stop()

    def pending_count(self) -> int:
        return int(self.source.pending_count())

    def _owner(self, turn_id) -> str:
        if turn_id:
            for name, ref in self._chats.items():
                chat = ref()
                if chat is not None and chat.owns_turn(turn_id):
                    return name
        return GENERAL if GENERAL in self._watchers else next(iter(self._watchers), GENERAL)

    def _on_appeared(self, approval) -> None:
        if not isinstance(approval, dict) or not self._watchers:
            return
        name = self._owner(approval.get("turn_id"))
        self._where[str(approval.get("id"))] = name
        self._watchers[name].appeared.emit(approval)

    def _on_vanished(self, approval_id: str) -> None:
        name = self._where.pop(approval_id, None)
        watcher = self._watchers.get(name) if name is not None else None
        if watcher is not None:
            watcher.vanished.emit(approval_id)
        else:
            for w in self._watchers.values():   # never announced here: tell everyone
                w.vanished.emit(approval_id)
