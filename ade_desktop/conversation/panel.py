"""The Ade conversation panel: Chat and Shell, one turn at a time,
click-only approvals, persisted threads. The piece-2 spec is the contract.

Rules this file keeps:
- Nothing runs here: every action is a ConversationClient call to Ade OS.
- One turn at a time. While one runs, Enter dispatches NOTHING: the line is
  put back in the input with a note (only /help and /health run).
- A failed turn puts the EXACT line back in the input -- Enter retries.
- Approvals arrive independently of the busy gate and are answered only by
  a click on the card.
- No lambda captures the panel (a plain callable is held strongly by PySide;
  a connection to one of the panel's own methods is not -- measured
  2026-09-18). A test pins that a dropped panel is freed at once.
"""

from __future__ import annotations

import json
import time

import random
import uuid

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from ade_desktop.conversation.commands import BY_NAME, COMMAND_NAMES, help_text, run_local
from ade_desktop.conversation.history import thread_history
from ade_desktop.conversation.replies import (
    ask_reply, error_cause, failed, health_text, read_reply, task_report, task_types_from,
)
from ade_desktop.conversation.router import route
from ade_desktop.conversation.spin import ROTATE_S, WORDS as SPIN_WORDS
from ade_desktop.conversation.skills import (
    attach, detach, resolve_superpowers, skill_list_text,
)
from ade_desktop.conversation.uploads import report, walk
from ade_desktop.conversation.widgets import (
    SENDING, ApprovalCard, SkillChips, message_widget,
)

RENDER_WINDOW = 300
# Ray, 2026-09-24, requirement 1: "the shell only is needed in the general
# chat tab, remove it from the others". The Shell TAB is gone from every
# chat panel; the shell is now a real terminal of its own on the General
# page (ade_desktop/shell/). current_tab() and set_tab() survive as the one
# word "chat" rather than being deleted from twenty call sites -- the panel
# is single-tab now, and saying so once is smaller than saying it everywhere.
TABS = ("chat",)
BUSY_NOTE = ("Ade is still working on the previous turn - press Enter again "
             "once it settles.")
RETRY = "\n\nThe message is staged in the input - press Enter to retry."
QUIT_NOTE = ("This turn was still running when the app quit. Ade OS may have "
             "finished it.")
QUEUE_LIMIT = 3         # spoken questions waiting for a busy chat; the newest are kept
CANCELLED_NOTE = ("Cancelled. Ade stops at its next step (a round already under way "
                  "finishes first); its reply will not be shown here.")
CANCELLED_WAIT_NOTE = ("Cancelled: stopped waiting. Ade OS cannot interrupt this kind of "
                       "request, so it may still finish in the background.")
# Kinds Cancel ends. "inline" keeps its Stop (it kills the shell session);
# an upload has no Cancel -- its files go one after another, locally, fast.
CANCELLABLE = ("ask", "task", "chat", "shell")
ASK_LABEL = "Ask"


def _turn_id() -> str:
    """A client turn id: Ade OS registers it, so the turn can be cancelled
    and its approvals are known to be this chat's."""
    return "desk-" + uuid.uuid4().hex


class HistoryLineEdit(QLineEdit):
    """Up / Down recall the last 50 lines sent from this tab (not saved)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.history: list[str] = []
        self._pos = 0

    def remember(self, line: str) -> None:
        if line and (not self.history or self.history[-1] != line):
            self.history.append(line)
            del self.history[:-50]
        self._pos = len(self.history)

    def set_history(self, lines) -> None:
        self.history = list(lines)[-50:]
        self._pos = len(self.history)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Up and self.history:
            self._pos = max(0, self._pos - 1)
            self.setText(self.history[self._pos])
            return
        if event.key() == Qt.Key.Key_Down and self.history:
            self._pos = min(len(self.history), self._pos + 1)
            self.setText(self.history[self._pos] if self._pos < len(self.history) else "")
            return
        super().keyPressEvent(event)


class ConversationPanel(QWidget):
    approval_needed = Signal(str)   # the tool: the window raises itself
    # For the orb (piece 3): what Ade is doing, as the panel sees it.
    busy_changed = Signal(bool)      # a turn started / ended
    reply_landed = Signal(str)       # an ask / chat / task answer shown in Chat
    turn_failed = Signal()           # a turn ended in "Call failed"
    approval_decided = Signal(bool)  # Ade OS accepted Allow (True) / Deny

    def __init__(self, client, watcher, store, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("conversationPanel")
        self.client, self.watcher, self.store = client, watcher, store
        self.busy = False
        self._turn: dict | None = None
        self._voice_queue: list[str] = []   # spoken questions waiting for this turn to end
        self._pending: dict[str, tuple] = {}
        self._window = {tab: RENDER_WINDOW for tab in TABS}
        self._widgets: dict[str, QWidget] = {}
        self._seen_approvals: set[str] = set()
        self._histories = {tab: [] for tab in TABS}
        self.setAcceptDrops(True)
        self._build()

        client.done.connect(self._on_done)
        client.line.connect(self._on_line)
        watcher.appeared.connect(self._on_appeared)
        watcher.vanished.connect(self._on_vanished)

        # Restored approval cards are never live: whether they are still
        # pending is the NEXT poll's to say, as a fresh card.
        for m in self.store.chat:
            meta = m.get("meta") or {}
            if m.get("kind") == "approval" and not meta.get("decided"):
                meta["moot"] = True
                m["meta"] = meta
        if self.store.load_note:
            self.store.push("chat", "system", "text", self.store.load_note)
        self.chips.set_skills(self.store.skills)
        self.store.tab = "chat"
        self.input.set_history(self._histories["chat"])
        self._render()                # the one full render at start

    # -- layout -------------------------------------------------------------

    def _build(self) -> None:
        box = QVBoxLayout(self)
        box.setContentsMargins(8, 6, 8, 8)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.content = QWidget()
        self.list = QVBoxLayout(self.content)
        self.list.setContentsMargins(2, 2, 2, 2)
        self.list.setSpacing(6)
        self.earlier = QPushButton("")
        self.earlier.clicked.connect(self._on_earlier)
        self.list.addWidget(self.earlier)
        self.list.addStretch(1)
        self.scroll.setWidget(self.content)
        box.addWidget(self.scroll, 1)

        # The spinner lives IN the thread (a "working" message: never saved,
        # never history, kept by clear -- threads.py); below it, only the
        # turn's Cancel / Stop.
        working = QHBoxLayout()
        working.addStretch(1)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setAutoDefault(False)
        self.stop_button.clicked.connect(self._on_stop)
        working.addWidget(self.stop_button)
        box.addLayout(working)
        self.stop_button.hide()

        self.chips = SkillChips()
        self.chips.removed.connect(self._on_chip_removed)
        box.addWidget(self.chips)

        row = QHBoxLayout()
        self.route_label = QLabel(ASK_LABEL)
        self.input = HistoryLineEdit()
        self.input.setPlaceholderText("Tell Ade what to do…")
        self.input.returnPressed.connect(self._on_return)
        row.addWidget(self.route_label)
        row.addWidget(self.input, 1)
        box.addLayout(row)
        self.hint = QLabel("/help · ! shell · ? chat · /type a task · /skill")
        self.hint.setObjectName("chatHint")
        box.addWidget(self.hint)

        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._on_tick)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(300)
        self._save_timer.timeout.connect(self.store.save)
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(0)
        self._scroll_timer.timeout.connect(self._to_bottom)

    # -- rendering ----------------------------------------------------------

    def current_tab(self) -> str:
        """There is one. Kept as a method so the twenty call sites that ask
        do not each have to be edited to say the same word."""
        return "chat"

    def set_tab(self, tab: str) -> None:
        """A no-op since the Shell tab left (2026-09-24). Kept so the code
        that used to switch back to Chat after routing still reads as
        intent rather than as a deletion."""

    def view_messages(self, tab: str) -> list[dict]:
        return list(self.store.tab_messages(tab))

    def rendered_count(self) -> int:
        return len(self._widgets)

    def _render(self) -> None:
        for widget in self._widgets.values():
            self.list.removeWidget(widget)
            widget.deleteLater()
        self._widgets = {}
        tab = self.current_tab()
        messages = self.store.tab_messages(tab)
        shown = messages[-self._window[tab]:]
        hidden = len(messages) - len(shown)
        self.earlier.setText(f"Show earlier ({hidden})")
        self.earlier.setVisible(hidden > 0)
        for msg in shown:
            self._add_widget(msg)
        self._scroll_to_end()

    def _add_widget(self, msg: dict) -> None:
        widget = message_widget(msg)
        if isinstance(widget, ApprovalCard):
            widget.decided.connect(self._on_card_decided)
        self._widgets[msg["id"]] = widget
        self.list.insertWidget(self.list.count() - 1, widget)

    def _on_earlier(self) -> None:
        self._window[self.current_tab()] += RENDER_WINDOW
        self._render()

    def _scroll_to_end(self) -> None:
        # A member timer, NOT QTimer.singleShot(0, self._to_bottom): a pending
        # single-shot holds its bound method -- and so the panel -- strongly
        # until it fires (measured 2026-09-18; the dropped-panel test caught
        # it). A child timer's connection to the panel's own method does not.
        bar = self.scroll.verticalScrollBar()
        if bar.maximum() - bar.value() <= 40:
            self._scroll_timer.start()

    def _to_bottom(self) -> None:
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _push(self, tab, role, kind, text, meta=None) -> dict:
        msg = self.store.push(tab, role, kind, text, meta)
        if tab == self.current_tab():
            self._add_widget(msg)
            self._scroll_to_end()
        self._save_soon()
        return msg

    def _refresh(self, msg: dict) -> None:
        widget = self._widgets.get(msg["id"])
        if widget is None:
            return
        if isinstance(widget, ApprovalCard):
            meta = msg.get("meta") or {}
            if meta.get("decided"):
                widget.set_outcome(str(meta["decided"]), live=False)
            elif meta.get("moot"):
                widget.set_outcome("Answered elsewhere", live=False)
            elif meta.get("deciding") is not None:
                widget.set_outcome(SENDING, live=False)
            return
        if hasattr(widget, "setText"):
            widget.setText(msg.get("text") or "")

    def _save_soon(self) -> None:
        self._save_timer.start()

    # -- sending ------------------------------------------------------------

    def _on_return(self) -> None:
        self.send()

    def send(self, raw: str | None = None) -> None:
        raw = self.input.text() if raw is None else raw
        tab = self.current_tab()
        r = route(raw, tab, COMMAND_NAMES)
        if r.kind == "empty":
            return
        while_busy = r.kind == "command" and BY_NAME[r.verb].while_busy
        if self.busy and not while_busy:
            self._push(tab, "system", "text", BUSY_NOTE)
            self.input.setText(raw)
            return
        self._histories[tab].append(raw)
        del self._histories[tab][:-50]
        self.input.remember(raw)
        self.input.clear()
        handler = getattr(self, f"_route_{r.kind}")
        handler(r, raw, tab)

    def _route_clear(self, r, raw, tab) -> None:
        self.set_tab("chat")
        note = run_local("clear", self.store, "chat")
        self._render()
        self._push("chat", "system", "text", note)

    def _route_ask(self, r, raw, tab) -> None:
        self.set_tab("chat")
        self._push("chat", "user", "ask", raw)
        # AFTER the push, as the avatar does: thread_history drops the
        # trailing user line, which must be THIS question -- built first, it
        # dropped an earlier unanswered question instead (review finding).
        history = thread_history(self.store.chat)
        tid = _turn_id()
        rid = self.client.ask(r.text, self.store.skills, history, turn_id=tid)
        self._start_turn(rid, "ask", "chat", raw, turn_id=tid)

    def _route_chat(self, r, raw, tab) -> None:
        if not r.text:
            self._push(tab, "system", "staged",
                       "Type a question after ? — e.g. ?what brain are you on")
            return
        self.set_tab("chat")
        self._push("chat", "user", "chat", raw)
        self._start_turn(self.client.chat(r.text), "chat", "chat", raw)

    def _route_task(self, r, raw, tab) -> None:
        if not r.text:
            rid = self.client.task_types()
            self._pending[rid] = ("types_help", tab, r.type)
            return
        self.set_tab("chat")
        self._push("chat", "user", "task", f"/{r.type} {r.text}")
        tid = _turn_id()
        rid = self.client.task(r.text, r.type, self.store.skills, turn_id=tid)
        self._start_turn(rid, "task", "chat", raw, turn_id=tid)

    def _route_shell(self, r, raw, tab) -> None:
        if not r.text:
            self._push(tab, "system", "staged",
                       "Type a command after ! — e.g. !git status")
            return
        # Answered on the tab it was typed on. Switching to Shell (the
        # avatar's behaviour) left the next PROSE line running as PowerShell,
        # ungated -- found live 2026-09-18. The Shell tab is reached only by
        # choosing it.
        self._push(tab, "user", "shell", f"! {r.text}")
        self._start_turn(self.client.shell(r.text), "shell", tab, raw)

    def _route_inline_shell(self, r, raw, tab) -> None:
        self.set_tab("chat")
        self._push("chat", "user", "shell", f"$ {r.text}")
        rid = self.client.run(r.text)
        self._start_turn(rid, "inline", "chat", raw)
        self._turn["out"] = self._push("chat", "ade", "inline", "")
        self.stop_button.show()

    def _route_command(self, r, raw, tab) -> None:
        verb = r.verb
        if verb == "help":
            self._push(tab, "system", "text", help_text())
        elif verb == "health":
            self._pending[self.client.health()] = ("health", tab)
        elif verb in ("search", "research"):
            if not r.text:
                self._push(tab, "system", "staged", f"Usage: /{verb} <question>")
                return
            self.set_tab("chat")
            self._push("chat", "user", "ask", raw)
            # A fresh question: no thread history travels with it.
            tid = _turn_id()
            rid = self.client.ask(r.text, self.store.skills, [], turn_id=tid)
            self._start_turn(rid, "ask", "chat", raw, turn_id=tid)
        else:
            note = run_local(verb, self.store, tab)
            if verb in ("reset", "restore", "clear", "compact"):
                self.chips.set_skills(self.store.skills)
                self._render()
            self._push(tab, "system", "text", note)

    def _route_skill(self, r, raw, tab) -> None:
        self._pending[self.client.skills()] = ("skills", tab, r.verb, r.text)

    def _route_upload(self, r, raw, tab) -> None:
        text = r.text or ""
        overwrite = "overwrite" in text.lower()
        if text.lower().startswith(("folder", "dir")):
            folder = QFileDialog.getExistingDirectory(self, "Upload a folder to Ade")
            paths = [folder] if folder else []
        else:
            paths, _ = QFileDialog.getOpenFileNames(self, "Upload files to Ade")
        self.upload_paths(paths, overwrite)

    def upload_paths(self, paths, overwrite: bool = False) -> None:
        tab = self.current_tab()
        if not paths:
            self._push(tab, "ade", "error", "Nothing selected.")
            return
        if self.busy:
            self._push(tab, "system", "text", BUSY_NOTE)
            return
        plan = walk(paths)
        rid = self.client.upload(plan.send, overwrite)
        self._start_turn(rid, "upload", tab, "")
        self._turn["plan"] = plan

    # -- turns --------------------------------------------------------------

    def _start_turn(self, rid, kind, tab, raw, turn_id=None) -> None:
        self.busy = True
        self.busy_changed.emit(True)
        self._turn = {"rid": rid, "kind": kind, "tab": tab, "raw": raw,
                      "t0": time.monotonic(), "stopped": False, "turn_id": turn_id}
        # The avatar's spinner: a word from its list, a new one every 90 s.
        self._spin_index = random.randrange(len(SPIN_WORDS))
        self._turn["spin"] = self._push(tab, "system", "working",
                                        SPIN_WORDS[self._spin_index] + "…")
        self._tick.start()
        if kind in CANCELLABLE:
            self.stop_button.setText("Cancel")
            self.stop_button.show()
        elif kind == "inline":
            self.stop_button.setText("Stop")

    def owns_turn(self, turn_id) -> bool:
        """Is `turn_id` the turn this chat is running? (Approvals raised by
        it are shown here, not in another section's chat.)"""
        return bool(turn_id) and self._turn is not None and self._turn.get("turn_id") == turn_id

    def _on_tick(self) -> None:
        turn = self._turn
        if turn is None or turn.get("spin") is None:
            return
        seconds = int(time.monotonic() - turn["t0"])
        index = (self._spin_index + seconds // ROTATE_S) % len(SPIN_WORDS)
        turn["spin"]["text"] = f"{SPIN_WORDS[index]}… {seconds} s"
        self._refresh(turn["spin"])

    def _end_turn(self) -> dict:
        turn, self._turn = self._turn, None
        self.busy = False
        self.busy_changed.emit(False)
        self._tick.stop()
        self._drop(turn.get("spin"), turn["tab"])
        self.stop_button.hide()
        return turn

    def _drop(self, msg, tab) -> None:
        """Take a message out of its thread and off the screen (the
        spinner, when its turn ends)."""
        if msg is None:
            return
        messages = self.store.tab_messages(tab)
        if msg in messages:
            messages.remove(msg)
        widget = self._widgets.pop(msg["id"], None)
        if widget is not None:
            self.list.removeWidget(widget)
            widget.deleteLater()

    def _fail(self, turn, cause: str) -> None:
        self.turn_failed.emit()
        raw = turn.get("raw") or ""
        draft = self.input.text().strip()
        if draft and draft != raw.strip():
            # Something was typed while the turn ran: never overwrite it.
            self._push(turn["tab"], "ade", "error",
                       f"Call failed: {cause}.\n\nThe failed line was: {raw}\n"
                       "Your draft in the box was kept.")
            return
        self._push(turn["tab"], "ade", "error", f"Call failed: {cause}.{RETRY}")
        if raw:
            self.input.setText(raw)
            self.input.setFocus()

    def _on_stop(self) -> None:
        if self._turn is None:
            return
        if self._turn["kind"] == "inline":
            self._turn["stopped"] = True
            self._pending[self.client.kill()] = ("kill",)
        elif self._turn["kind"] in CANCELLABLE:
            self.cancel_turn()

    def cancel_turn(self) -> None:
        """Stop waiting now, and ask Ade OS to stop the turn when it can:
        an ask or a task carries a turn_id Ade OS registered; a plain chat
        or a one-shot shell has nothing Ade OS can interrupt. Either way the
        chat is free at once and the late reply is dropped (its rid is no
        longer the turn's)."""
        turn = self._end_turn()
        if turn.get("turn_id"):
            self._pending[self.client.cancel(turn["turn_id"])] = ("cancel", turn["tab"])
            self._push(turn["tab"], "system", "text", CANCELLED_NOTE)
        else:
            self._push(turn["tab"], "system", "text", CANCELLED_WAIT_NOTE)
        self._save_soon()
        self._drain_voice_queue()

    def _on_line(self, rid: str, text: str) -> None:
        turn = self._turn
        if turn is None or turn["rid"] != rid or turn["kind"] != "inline":
            return
        out = turn["out"]
        try:
            frame = json.loads(text)
        except ValueError:
            return
        kind = frame.get("type")
        if kind == "out":
            piece = str(frame.get("text") or "")
            out["text"] = (out["text"] + "\n" + piece) if out["text"] else piece
        elif kind == "exit":
            turn["ended"] = True
            if frame.get("code") not in (0, None):
                out["text"] += ("\n" if out["text"] else "") + f"[exit {frame.get('code')}]"
        elif kind == "error":
            turn["ended"] = True
            out["text"] += ("\n" if out["text"] else "") + str(frame.get("text") or "")
        self._refresh(out)

    def _on_done(self, rid: str, result) -> None:
        result = result if isinstance(result, dict) else {"error": "non-dict reply"}
        if self._turn is not None and rid == self._turn["rid"]:
            self._finish_turn(self._end_turn(), result)
            self._save_soon()
            self._drain_voice_queue()       # after the answer, so the thread reads in order
            return
        pending = self._pending.pop(rid, None)
        if pending is None:
            return
        getattr(self, f"_done_{pending[0]}")(pending, result)
        self._save_soon()

    def _finish_turn(self, turn, result) -> None:
        kind, tab = turn["kind"], turn["tab"]
        if kind == "inline":
            out = turn["out"]
            if turn["stopped"]:
                out["text"] += ("\n" if out["text"] else "") + "[stopped]"
            elif failed(result):
                if not out["text"]:
                    self.store.tab_messages("chat").remove(out)
                    self._render()
                    self._fail(turn, error_cause(result))
                    return
                out["text"] += f"\n[stream ended: {error_cause(result)}]"
            elif not turn.get("ended"):
                # Closed without an exit or error frame: not a success we can
                # vouch for (review finding).
                out["text"] += (("\n" if out["text"] else "")
                                + "[stream ended without an exit code]")
            if not out["text"]:
                out["text"] = "(no output)"
            self._refresh(out)
            return
        if kind == "upload":
            plan = turn["plan"]
            if failed(result):
                self._push(tab, "ade", "error", f"Upload failed: {error_cause(result)}")
                return
            text = report(result.get("sent", 0), result.get("bytes", 0), plan.found,
                          plan.skipped, [tuple(f) for f in result.get("failed", [])])
            failed_all = result.get("failed") and not result.get("sent")
            self._push(tab, "ade", "error" if failed_all else "text", text)
            return
        if kind == "shell" and "ok" in result and "status" not in result:
            # /v1/terminal answered: {ok, exit_code, output, error}. A failed
            # command is the command's answer, not a failed call.
            text = str(result.get("output") or "") or str(result.get("error") or "")
            self._push(tab, "ade", "shell", text or "(no output)")
            return
        if kind == "task" and isinstance(result, dict) and "task_id" in result \
                and "status" not in result:
            # The task RAN: its reply is Ade's account of it, success or not.
            text, _ = task_report(result)
            bad = bool(result.get("error")) or result.get("ok") is False
            self._push(tab, "ade", "error" if bad else "task", text)
            if not bad:
                self.reply_landed.emit(text)
            return
        if failed(result):
            types = task_types_from(result) if kind == "task" else []
            cause = error_cause(result)
            if types:
                cause += "\n\nTypes: " + ", ".join(types)
            self._fail(turn, cause)
            return
        if kind == "ask":
            reply = ask_reply(result)
            if reply.cleared:
                note = run_local("clear", self.store, "chat")
                self._render()
                self._push("chat", "system", "text", note)
                return
            self._push("chat", "ade", "ask", reply.text)
            self.reply_landed.emit(reply.text)
            return
        text = read_reply(result) or "(no output)"
        self._push(tab, "ade", kind, text)
        if kind in ("chat", "task") and tab == "chat":
            self.reply_landed.emit(text)

    # -- pending, non-turn calls --------------------------------------------

    def _done_health(self, pending, result) -> None:
        self._push(pending[1], "system", "text", health_text(result))

    def _done_types_help(self, pending, result) -> None:
        tab, typed = pending[1], pending[2]
        rows = result.get("types") if isinstance(result, dict) else None
        names = [str(t.get("type")) for t in rows or [] if isinstance(t, dict)]
        head = (f"/{typed} needs something to do — e.g. /{typed} run the tests."
                if typed in names else f'"{typed}" is not a task type.')
        tail = ("\n\nTypes: " + ", ".join(names)) if names else ""
        self._push(tab, "system", "staged",
                   head + tail + "\n\nOr /skill <name> to attach a procedure, "
                   "/superpowers for the process set.")

    def _done_cancel(self, pending, result) -> None:
        if failed(result):
            self._push(pending[1], "system", "text",
                       f"Could not reach Ade OS to stop it ({error_cause(result)}), so it "
                       "may still be running; its reply will not be shown here.")

    def _done_kill(self, pending, result) -> None:
        if failed(result):
            self._push("chat", "system", "text",
                       f"Stop failed: {error_cause(result)}. The command may "
                       "still be running in the shell session.")

    def _done_skills(self, pending, result) -> None:
        tab, verb, text = pending[1], pending[2], pending[3]
        rows = result.get("skills") if isinstance(result, dict) else None
        if not isinstance(rows, list):
            self._push(tab, "ade", "error",
                       f"Could not read the skills index from Ade OS: "
                       f"{error_cause(result)}")
            return
        if verb == "superpowers" and not text:
            added = [n for n in resolve_superpowers(rows) if n not in self.store.skills]
            self.store.skills = self.store.skills + added
            note = ("Attached the Superpowers process: " + ", ".join(added)
                    + ". Asks and /type tasks will follow them. /unskill <name> "
                    "removes one." if added else
                    "The Superpowers process skills are already attached.")
        elif not text.lstrip("-").strip():
            note = skill_list_text(rows, self.store.skills)
        elif verb == "unskill" or text.startswith("-"):
            self.store.skills, note = detach(self.store.skills, text)
        else:
            self.store.skills, note = attach(rows, self.store.skills, text)
        self.chips.set_skills(self.store.skills)
        self._push(tab, "system", "text", note)

    def _on_chip_removed(self, name: str) -> None:
        self.store.skills, note = detach(self.store.skills, name)
        self.chips.set_skills(self.store.skills)
        self._push(self.current_tab(), "system", "text", note)

    # -- approvals ----------------------------------------------------------

    def _on_appeared(self, approval) -> None:
        aid = str((approval or {}).get("id") or "")
        if not aid or aid in self._seen_approvals:
            return
        self._seen_approvals.add(aid)
        tool = str(approval.get("tool") or "?")
        self.set_tab("chat")
        self._push("chat", "ade", "approval", "", {"approval": {
            "id": aid, "tool": tool, "args": approval.get("args") or {}}})
        self.approval_needed.emit(tool)

    def _card_message(self, approval_id: str) -> dict | None:
        for m in reversed(self.store.chat):
            meta = m.get("meta") or {}
            if m.get("kind") == "approval" and \
                    str((meta.get("approval") or {}).get("id")) == approval_id:
                return m
        return None

    def _on_card_decided(self, approval_id: str, allow: bool) -> None:
        msg = self._card_message(approval_id)
        if msg is None:
            return
        meta = msg.setdefault("meta", {})
        if meta.get("decided") or meta.get("moot") or meta.get("deciding") is not None:
            return    # one decision per approval, however often it is drawn
        meta["deciding"] = bool(allow)
        self._refresh(msg)
        rid = self.client.decide(approval_id, allow)
        self._pending[rid] = ("decide", approval_id, allow)

    def _done_decide(self, pending, result) -> None:
        approval_id, allow = pending[1], pending[2]
        msg = self._card_message(approval_id)
        if msg is None:
            return
        meta = msg.setdefault("meta", {})
        meta.pop("deciding", None)
        err = result.get("error") if isinstance(result, dict) else "no reply"
        if err is None:
            meta["decided"] = f"{'Allowed' if allow else 'Denied'} {approval_id}"
            self.approval_decided.emit(bool(allow))
        elif isinstance(err, dict) and err.get("code") == "already_decided":
            meta["decided"] = "Already decided elsewhere"
        else:
            # The buttons come back: an approval nobody can answer times out
            # as a denial.
            widget = self._widgets.get(msg["id"])
            if isinstance(widget, ApprovalCard):
                widget.set_outcome(
                    f"Could not decide {approval_id}: {error_cause(result)}", live=True)
            return
        self._refresh(msg)

    def _on_vanished(self, approval_id: str) -> None:
        msg = self._card_message(approval_id)
        if msg is None:
            return
        meta = msg.setdefault("meta", {})
        if not meta.get("decided"):
            meta["moot"] = True
            self._refresh(msg)
            self._save_soon()

    # -- speech (piece 3) -----------------------------------------------------

    def note(self, text: str) -> None:
        """A system line in Chat."""
        self._push("chat", "system", "text", text)

    def focus_input(self) -> None:
        self.input.setFocus()

    def stage(self, text: str, note: str | None = None) -> bool:
        """Put `text` in the input for Enter, unsent. A draft already in the
        box is never overwritten: the note says what was heard instead.
        (Overheard dictation no longer comes here at all: only a woken line
        is ever staged -- Ray, 2026-09-18.)"""
        draft = self.input.text().strip()
        if draft and draft != text.strip():
            self.set_tab("chat")
            self._push("chat", "system", "staged",
                       f"Heard: {text} (not placed: your draft in the box was kept).")
            return False
        self.set_tab("chat")
        if note:
            self._push("chat", "system", "staged", note)
        self.input.setText(text)
        self.input.setFocus()
        return True

    def queue_voice_ask(self, text: str) -> bool:
        """A spoken question that arrived while this chat was busy: it is
        asked the moment the turn ends (answered or cancelled). Only a
        plain ask queues; False for anything else, which the caller boxes."""
        if route(text, "chat", COMMAND_NAMES).kind != "ask":
            return False
        self._voice_queue.append(text)
        del self._voice_queue[:-QUEUE_LIMIT]
        self._push("chat", "system", "staged",
                   f"Queued: {text} — asked as soon as Ade finishes.")
        return True

    def _drain_voice_queue(self) -> None:
        if not self.busy and self._voice_queue:
            self.voice_ask(self._voice_queue.pop(0))

    def voice_ask(self, text: str) -> bool:
        """Speech's ONLY way to send anything: a read-only ask, on Chat,
        routed as Chat routes it -- never on Shell, whatever tab is open.
        Anything that routes elsewhere, or a busy panel, is refused here and
        the caller stages it. The input box is not touched."""
        r = route(text, "chat", COMMAND_NAMES)
        if r.kind != "ask" or self.busy:
            return False
        self._route_ask(r, text, "chat")
        return True

    # -- drag and drop, quit ------------------------------------------------

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        self.upload_paths(paths, False)

    def on_quit(self) -> None:
        if self._turn is not None:
            self.store.push(self._turn["tab"], "system", "text", QUIT_NOTE)
        self.store.save()
