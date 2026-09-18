"""The Path, natively: Today, Read, Diary, Study, Stage and Catalogue over
The Path's JSON face. Everything shown is The Path's answer, as plain text
(nothing here renders HTML or follows a link); every write is followed by
a re-read of the page it changed.

The two verbs that are Ray's -- set the stage, confirm a teaching -- need
the token he pastes into the header box; without it they are not sent at
all, and with a wrong one The Path refuses exactly as its pages do.
No lambda captures the panel.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPlainTextEdit, QPushButton, QSplitter,
                               QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from ade_desktop.conversation.replies import error_cause, failed

STALE_S = 5.0
DOWN_NOTE = ("The Path is not running. Start it yourself with `thepath serve` in "
             "C:\\Users\\ray_g\\the-path — the app never starts it, because it prints "
             "your token.")
NEED_TOKEN = ("{what} is yours: paste the token `thepath serve` printed into the box "
              "above first. It is kept in memory for this session only.")
OK_STYLE = "color:#5fb878;"
ERR_STYLE = "color:#d95757;"
MUTED = "color:#9aa1ab;"


def _ok(result) -> bool:
    return not failed(result)


def _unreachable(result) -> bool:
    """No answer at all -- as opposed to The Path answering with a refusal."""
    return (isinstance(result, dict) and "error" in result and "status" not in result
            and isinstance(result["error"], str))


def _browser() -> QTextBrowser:
    b = QTextBrowser()
    b.setOpenLinks(False)
    b.setOpenExternalLinks(False)
    return b


def _entries_text(entries) -> str:
    lines = []
    for e in entries or []:
        if isinstance(e, dict):
            lines.append(f"— {str(e.get('written_at', ''))[:16].replace('T', ' ')} · "
                         f"{e.get('kind', '')}\n{e.get('body', '')}\n")
    return "\n".join(lines) or "Nothing written yet."


def _pretty(value, depth: int = 0) -> str:
    """Any JSON value as indented plain text -- for the guide and the
    catalogue, whose fields are The Path's to choose."""
    pad = "  " * depth
    if isinstance(value, dict):
        out = []
        for k, v in value.items():
            if isinstance(v, (dict, list)) and v:
                out.append(f"{pad}{k}:\n{_pretty(v, depth + 1)}")
            else:
                out.append(f"{pad}{k}: {'—' if v in (None, '', []) else v}")
        return "\n".join(out)
    if isinstance(value, list):
        return "\n".join(_pretty(v, depth) + ("\n" if isinstance(v, dict) else "")
                         for v in value)
    return f"{pad}{value}"


def today_text(d: dict) -> str:
    parts = [f"Stage: {d.get('stage') or '—'}"]
    cycle = d.get("cycle")
    if cycle:
        parts.append(f"Cycle: day {int(d.get('answered') or 0) + 1} of {d.get('of')} "
                     f"({d.get('answered', 0)} answered)")
    else:
        parts.append("No cycle is open.")
    if d.get("summary"):
        parts.append(f"Today: {d['summary']}")
    src = d.get("source")
    if isinstance(src, dict):
        parts.append("\nSOURCE — " + str(src.get("attribution") or ""))
        parts.append(src.get("passage") or "We name this book, but we do not hold its text.")
        if src.get("passage_2"):
            parts.append(src["passage_2"])
    lesson = d.get("lesson")
    if isinstance(lesson, dict):
        parts.append("\nADE'S READING (an interpretation)\n" + str(lesson.get("text") or ""))
    prompt = d.get("prompt")
    if isinstance(prompt, dict):
        parts.append("\nTODAY'S PROMPT\n" + str(prompt.get("text") or ""))
    elif d.get("offer_open"):
        parts.append("\nA passage is offered above. Put it in your own words to keep it.")
    else:
        parts.append("\nNo prompt yet today.")
    thought = d.get("thought")
    if isinstance(thought, dict):
        parts.append("\nADE'S THOUGHT" + (f" — resting on {d['thought_source']}"
                                          if d.get("thought_source") else "")
                     + "\n" + str(thought.get("text") or ""))
    parts.append("\nRECENT ENTRIES\n" + _entries_text(d.get("entries")))
    return "\n".join(parts)


class PathPanel(QWidget):
    def __init__(self, client, *, clock=time.monotonic, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self._clock = clock
        self._last = -1e9
        self._pending: dict[str, tuple] = {}
        self.today: dict = {}
        self.teachings: list[dict] = []
        self.current_teaching: dict | None = None
        self._build()
        client.done.connect(self._on_done)

    # -- layout -------------------------------------------------------------------

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 8)
        head = QHBoxLayout()
        title = QLabel("The Path")
        title.setStyleSheet("font-size:15px;font-weight:600;")
        self.status = QLabel("")
        self.status.setWordWrap(True)
        head.addWidget(title)
        head.addWidget(self.status, 1)
        self.refresh_button = QPushButton("Refresh")
        head.addWidget(self.refresh_button)
        v.addLayout(head)
        row = QHBoxLayout()
        self.token_box = QLineEdit()
        self.token_box.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_box.setPlaceholderText("Ray's token from `thepath serve` (memory only)")
        self.use_token = QPushButton("Use token")
        self.forget = QPushButton("Forget")
        self.token_state = QLabel("")
        self.token_state.setStyleSheet(MUTED)
        row.addWidget(self.token_box, 1)
        row.addWidget(self.use_token)
        row.addWidget(self.forget)
        row.addWidget(self.token_state)
        v.addLayout(row)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        v.addWidget(self.message)
        self.tabs = QTabWidget()
        v.addWidget(self.tabs, 1)
        self.tabs.addTab(self._build_today(), "Today")
        self.tabs.addTab(self._build_read(), "Read")
        self.tabs.addTab(self._build_diary(), "Diary")
        self.tabs.addTab(self._build_study(), "Study")
        self.tabs.addTab(self._build_stage(), "Stage")
        self.tabs.addTab(self._build_catalogue(), "Catalogue")
        self.refresh_button.clicked.connect(self.refresh)
        self.use_token.clicked.connect(self._on_use_token)
        self.token_box.returnPressed.connect(self._on_use_token)
        self.forget.clicked.connect(self._on_forget)
        self._sync_token()

    def _build_today(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.today_view = _browser()
        v.addWidget(self.today_view, 3)
        row = QHBoxLayout()
        self.offer_button = QPushButton("Offer a passage")
        row.addWidget(self.offer_button)
        row.addStretch(1)
        v.addLayout(row)
        self.prompt_box = QPlainTextEdit()
        self.prompt_box.setPlaceholderText("The offered passage, in your own words — Record keeps it")
        self.prompt_box.setFixedHeight(70)
        self.record_button = QPushButton("Record prompt")
        v.addWidget(self.prompt_box)
        v.addWidget(self.record_button)
        self.entry_box = QPlainTextEdit()
        self.entry_box.setPlaceholderText("Write today's entry — it is immutable once written")
        self.entry_box.setFixedHeight(90)
        self.entry_button = QPushButton("Write")
        v.addWidget(self.entry_box)
        v.addWidget(self.entry_button)
        self.offer_button.clicked.connect(self._on_offer)
        self.record_button.clicked.connect(self._on_record)
        self.entry_button.clicked.connect(self._on_entry)
        return w

    def _build_read(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.read_view = _browser()
        v.addWidget(self.read_view)
        return w

    def _build_diary(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.diary_view = _browser()
        v.addWidget(self.diary_view, 3)
        row = QHBoxLayout()
        self.diary_kind = QComboBox()
        row.addWidget(QLabel("Kind"))
        row.addWidget(self.diary_kind)
        row.addStretch(1)
        v.addLayout(row)
        self.diary_box = QPlainTextEdit()
        self.diary_box.setPlaceholderText("A diary entry answers no prompt — immutable once written")
        self.diary_box.setFixedHeight(90)
        self.diary_button = QPushButton("Write")
        v.addWidget(self.diary_box)
        v.addWidget(self.diary_button)
        self.diary_button.clicked.connect(self._on_diary)
        return w

    def _build_study(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("Teachings"))
        self.teaching_list = QListWidget()
        lv.addWidget(self.teaching_list, 1)
        self.draft_title = QLineEdit()
        self.draft_title.setPlaceholderText("Title")
        self.draft_subject = QLineEdit()
        self.draft_subject.setPlaceholderText("Subject")
        self.draft_button = QPushButton("Draft teaching")
        for x in (self.draft_title, self.draft_subject, self.draft_button):
            lv.addWidget(x)
        split.addWidget(left)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        self.study_view = _browser()
        rv.addWidget(self.study_view, 2)
        self.teaching_view = _browser()
        rv.addWidget(self.teaching_view, 2)
        row = QHBoxLayout()
        self.claim_category = QComboBox()
        self.claim_body = QLineEdit()
        self.claim_body.setPlaceholderText("Claim")
        row.addWidget(self.claim_category)
        row.addWidget(self.claim_body, 1)
        rv.addLayout(row)
        row = QHBoxLayout()
        self.claim_cites = QLineEdit()
        self.claim_cites.setPlaceholderText("cites (citation ids, comma-separated)")
        self.claim_drawn = QLineEdit()
        self.claim_drawn.setPlaceholderText("drawn from (citation ids)")
        self.claim_button = QPushButton("Add claim")
        self.confirm_button = QPushButton("Confirm teaching")
        row.addWidget(self.claim_cites, 1)
        row.addWidget(self.claim_drawn, 1)
        row.addWidget(self.claim_button)
        row.addWidget(self.confirm_button)
        rv.addLayout(row)
        split.addWidget(right)
        split.setSizes([260, 800])
        v.addWidget(split)
        self.teaching_list.currentItemChanged.connect(self._on_teaching_pick)
        self.draft_button.clicked.connect(self._on_draft)
        self.claim_button.clicked.connect(self._on_claim)
        self.confirm_button.clicked.connect(self._on_confirm)
        return w

    def _build_stage(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.stage_label = QLabel("")
        self.stage_label.setStyleSheet("font-size:14px;")
        v.addWidget(self.stage_label)
        row = QHBoxLayout()
        self.stage_combo = QComboBox()
        self.stage_button = QPushButton("Set stage")
        row.addWidget(self.stage_combo)
        row.addWidget(self.stage_button)
        row.addStretch(1)
        v.addLayout(row)
        v.addWidget(QLabel("Advancing the stage is yours alone; it needs your token."))
        v.addStretch(1)
        self.stage_button.clicked.connect(self._on_set_stage)
        return w

    def _build_catalogue(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("Works held for review"))
        self.catalogue_view = _browser()
        v.addWidget(self.catalogue_view)
        return w

    # -- token ------------------------------------------------------------------------

    def _on_use_token(self) -> None:
        self.client.set_token(self.token_box.text())
        self.token_box.clear()                      # not left sitting in a widget
        self._sync_token()

    def _on_forget(self) -> None:
        self.client.forget_token()
        self.token_box.clear()
        self._sync_token()

    def _sync_token(self) -> None:
        held = self.client.has_token()
        self.token_state.setText("token held (this session)" if held else "no token")
        self.forget.setEnabled(held)

    # -- loading -----------------------------------------------------------------------

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._clock() - self._last > STALE_S:
            self.refresh()

    def refresh(self) -> None:
        self._last = self._clock()
        for kind, rid in (("today", self.client.today()), ("read", self.client.read_entries()),
                          ("diary", self.client.diary()), ("study", self.client.study()),
                          ("stage", self.client.stage()), ("catalogue", self.client.catalogue())):
            self._pending[rid] = (kind,)

    def _on_done(self, rid: str, result) -> None:
        job = self._pending.pop(rid, None)
        if job is None:
            return
        if _unreachable(result):
            self._down()
            return
        self.status.setText("The Path is running at " + self.client.base)
        self.status.setStyleSheet(MUTED)
        self.tabs.setEnabled(True)
        getattr(self, f"_got_{job[0]}")(result, *job[1:])

    def _down(self) -> None:
        self.status.setText(DOWN_NOTE)
        self.status.setStyleSheet(ERR_STYLE)
        self.tabs.setEnabled(False)

    def _say(self, result) -> None:
        """An action's answer, in The Path's own words."""
        if _ok(result):
            self.message.setText(str(result.get("message") or ""))
            self.message.setStyleSheet(OK_STYLE if result.get("ok") else ERR_STYLE)
        else:
            err = result.get("error") if isinstance(result, dict) else result
            text = err if isinstance(err, str) and isinstance(result, dict) and \
                result.get("status") else error_cause(result)
            self.message.setText(str(text))
            self.message.setStyleSheet(ERR_STYLE)

    # -- pages ---------------------------------------------------------------------------

    def _got_today(self, result) -> None:
        if not _ok(result):
            self.today_view.setPlainText(f"Could not read Today: {error_cause(result)}")
            return
        self.today = result
        self.today_view.setPlainText(today_text(result))
        has_prompt = isinstance(result.get("prompt"), dict)
        offer_open = bool(result.get("offer_open")) and not has_prompt
        self.offer_button.setEnabled(not has_prompt and not offer_open)
        self.prompt_box.setVisible(offer_open)
        self.record_button.setVisible(offer_open)

    def _got_read(self, result) -> None:
        self.read_view.setPlainText(_entries_text(result.get("entries")) if _ok(result)
                                    else f"Could not read: {error_cause(result)}")

    def _got_diary(self, result) -> None:
        if not _ok(result):
            self.diary_view.setPlainText(f"Could not read the diary: {error_cause(result)}")
            return
        self.diary_view.setPlainText(_entries_text(result.get("entries")))
        keep = self.diary_kind.currentText()
        self.diary_kind.clear()
        for k in result.get("kinds") or []:
            self.diary_kind.addItem(k)
        if keep:
            self.diary_kind.setCurrentText(keep)

    def _got_study(self, result) -> None:
        if not _ok(result):
            self.study_view.setPlainText(f"Could not read Study: {error_cause(result)}")
            return
        self.study_view.setPlainText(_pretty(result.get("guide")) or "No study guide today.")
        self.teachings = [t for t in result.get("teachings") or [] if isinstance(t, dict)]
        keep = (self.current_teaching or {}).get("teaching_id")
        self.teaching_list.blockSignals(True)
        self.teaching_list.clear()
        for t in self.teachings:
            item = QListWidgetItem(f"{t.get('title')} — {t.get('status')}")
            item.setData(Qt.ItemDataRole.UserRole, t.get("teaching_id"))
            self.teaching_list.addItem(item)
            if t.get("teaching_id") == keep:
                self.teaching_list.setCurrentItem(item)
        self.teaching_list.blockSignals(False)
        if keep:
            self._pending[self.client.teaching(keep)] = ("teaching",)

    def _on_teaching_pick(self, current, previous) -> None:
        if current is not None:
            self._pending[self.client.teaching(current.data(Qt.ItemDataRole.UserRole))] = \
                ("teaching",)

    def _got_teaching(self, result) -> None:
        if not _ok(result):
            self.teaching_view.setPlainText(f"Could not open it: {error_cause(result)}")
            return
        t = result.get("teaching") or {}
        self.current_teaching = t
        lines = [f"{t.get('title')} — {t.get('subject')}",
                 f"status: {t.get('status')}  version {t.get('version')}"
                 + (f"  confirmed {t.get('confirmed_at')}" if t.get("confirmed_at") else ""), ""]
        for c in t.get("claims") or []:
            lines.append(f"{c.get('ordinal')}. [{c.get('category')}] {c.get('body')}")
            if c.get("warranted"):
                lines.append("   cites: " + ", ".join(c["warranted"]))
            if c.get("drawn_from"):
                lines.append("   drawn from: " + ", ".join(c["drawn_from"]))
        self.teaching_view.setPlainText("\n".join(lines))
        keep = self.claim_category.currentText()
        self.claim_category.clear()
        for cat in result.get("categories") or []:
            self.claim_category.addItem(cat)
        if keep:
            self.claim_category.setCurrentText(keep)

    def _got_stage(self, result) -> None:
        if not _ok(result):
            self.stage_label.setText(f"Could not read the stage: {error_cause(result)}")
            return
        self.stage_label.setText(f"Current stage: {result.get('stage')}")
        keep = self.stage_combo.currentText()
        self.stage_combo.clear()
        for s in result.get("stages") or []:
            self.stage_combo.addItem(s)
        self.stage_combo.setCurrentText(keep or str(result.get("stage") or ""))

    def _got_catalogue(self, result) -> None:
        self.catalogue_view.setPlainText(
            (_pretty(result.get("held")) or "Nothing is held for review.") if _ok(result)
            else f"Could not read the catalogue: {error_cause(result)}")

    # -- actions ----------------------------------------------------------------------------

    def _act(self, rid: str, *reread: str) -> None:
        self._pending[rid] = ("acted", reread)

    def _got_acted(self, result, reread) -> None:
        self._say(result)
        for kind in reread:
            call = {"today": self.client.today, "read": self.client.read_entries,
                    "diary": self.client.diary, "study": self.client.study,
                    "stage": self.client.stage}[kind]
            self._pending[call()] = (kind,)

    def _on_entry(self) -> None:
        body = self.entry_box.toPlainText()
        if not body.strip():
            return
        self._act(self.client.write_entry(body), "today", "read")
        self.entry_box.clear()

    def _on_diary(self) -> None:
        body = self.diary_box.toPlainText()
        if not body.strip():
            return
        self._act(self.client.write_diary(body, self.diary_kind.currentText()), "diary", "read")
        self.diary_box.clear()

    def _on_offer(self) -> None:
        self._act(self.client.offer(), "today")

    def _on_record(self) -> None:
        src = self.today.get("source") if isinstance(self.today, dict) else None
        text = self.prompt_box.toPlainText()
        if not isinstance(src, dict) or not text.strip():
            return
        self._act(self.client.record_prompt(text, src.get("citation_id") or "",
                                            str(src.get("stage") or ""),
                                            str(src.get("occasion") or "")), "today")
        self.prompt_box.clear()

    def _on_draft(self) -> None:
        title, subject = self.draft_title.text().strip(), self.draft_subject.text().strip()
        if not title:
            return
        self._act(self.client.draft_teaching(title, subject), "study")
        self.draft_title.clear()
        self.draft_subject.clear()

    def _on_claim(self) -> None:
        t = self.current_teaching
        body = self.claim_body.text().strip()
        if not t or not body:
            return

        def ids(box):
            return [x.strip() for x in box.text().split(",") if x.strip()]

        self._act(self.client.add_claim(t["teaching_id"], self.claim_category.currentText(),
                                        body, ids(self.claim_cites), ids(self.claim_drawn)),
                  "study")
        for box in (self.claim_body, self.claim_cites, self.claim_drawn):
            box.clear()

    def _gated(self, what: str) -> bool:
        if self.client.has_token():
            return True
        self.message.setText(NEED_TOKEN.format(what=what))
        self.message.setStyleSheet(ERR_STYLE)
        return False

    def _on_set_stage(self) -> None:
        stage = self.stage_combo.currentText()
        if stage and self._gated("Advancing the stage"):
            self._act(self.client.set_stage(stage), "stage", "today")

    def _on_confirm(self) -> None:
        t = self.current_teaching
        if t and self._gated("Confirming a teaching"):
            self._act(self.client.confirm(t["teaching_id"]), "study")

    def stop_clients(self) -> None:
        self.client.forget_token()
        self.client.stop()
