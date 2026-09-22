"""The Path, natively: Day, Today, Read, Diary, Study, Stage and Catalogue
over The Path's JSON face. Everything shown is The Path's answer, as plain
text (nothing here renders HTML or follows a link); every write is followed
by a re-read of the page it changed.

The three verbs that are Ray's -- set the stage, confirm a teaching, mark a
charter's criteria -- need the token he pastes into the header box; without
it they are not sent at all, and with a wrong one The Path refuses exactly
as its pages do. The day's mirror is asked of Ade OS (a `mirror` job), not
of The Path, so its failure never marks The Path down.
No lambda captures the panel.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
                               QSplitter, QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from ade_desktop.conversation.replies import error_cause, failed, task_report
from ade_desktop.theme import SMALL_FONT_PX

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


_TRANSPORT = ("ConnectError", "ConnectTimeout", "ReadTimeout", "WriteTimeout",
              "PoolTimeout", "RemoteProtocolError", "LocalProtocolError", "NetworkError",
              "ReadError", "WriteError", "TimeoutException")


def _unreachable(result) -> bool:
    """No answer at all -- a transport failure -- as opposed to The Path
    answering with an error (which carries a status). A database outage
    behind a running server is a 503 from The Path, not "not running"."""
    if not isinstance(result, dict) or "status" in result:
        return False
    err = result.get("error")
    return isinstance(err, str) and err.split(":", 1)[0].strip() in _TRANSPORT


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
    has_source = isinstance(d.get("source"), dict)
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
        # The page's own reading of the attribution (cite.plainly, via
        # source_plain): who, what and where -- not the machine addresses.
        parts.append("\nSOURCE — " + str(d.get("source_plain") or src.get("attribution") or ""))
        parts.append(src.get("passage") or "We name this book, but we do not hold its text.")
        if src.get("passage_2"):
            parts.append(src["passage_2"])
    lesson = d.get("lesson")
    if isinstance(lesson, dict):
        parts.append("\nADE'S READING (an interpretation)\n" + str(lesson.get("text") or ""))
    prompt = d.get("prompt")
    if isinstance(prompt, dict):
        parts.append("\nTODAY'S PROMPT\n" + str(prompt.get("text") or ""))
    elif has_source:
        parts.append("\nPut the passage above in your own words to keep it as today's prompt.")
    else:
        parts.append("\nNothing offered yet today.")
    thought = d.get("thought")
    if isinstance(thought, dict):
        parts.append("\nADE'S THOUGHT" + (f" — resting on {d['thought_source']}"
                                          if d.get("thought_source") else "")
                     + "\n" + str(thought.get("text") or ""))
    parts.append("\nRECENT ENTRIES\n" + _entries_text(d.get("entries")))
    return "\n".join(parts)


def ask_ray(parent, title: str, text: str) -> bool:
    """The default confirmation: a plain Yes/No box, No unless he says Yes."""
    answer = QMessageBox.question(parent, title, text,
                                  QMessageBox.StandardButton.Yes
                                  | QMessageBox.StandardButton.No,
                                  QMessageBox.StandardButton.No)
    return answer == QMessageBox.StandardButton.Yes


def mark_question(goal: str, criteria: list[str]) -> str:
    """What Ray is asked before criteria are marked: marking is FINAL and
    append-only in The Path, so he sees exactly what will be sent."""
    ticked = "\n".join(f"  - {c}" for c in criteria) or "  (none ticked)"
    return ("Marking the criteria is final: The Path keeps them for the whole "
            "cycle and they cannot be changed afterwards.\n\n"
            f"Cycle goal:\n  {goal}\n\nCriteria:\n{ticked}\n\nMark these?")


class PathPanel(QWidget):
    def __init__(self, client, *, mirror_client=None, clock=time.monotonic,
                 confirm=ask_ray, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.mirror_client = mirror_client
        self._confirm = confirm
        self._clock = clock
        self._last = -1e9
        self._pending: dict[str, tuple] = {}
        self.today: dict = {}
        self.teachings: list[dict] = []
        self.current_teaching: dict | None = None
        self._build()
        client.done.connect(self._on_done)
        if mirror_client is not None:
            mirror_client.done.connect(self._on_done)

    # -- layout -------------------------------------------------------------------

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 8)
        head = QHBoxLayout()
        title = QLabel("The Path")
        title.setStyleSheet("font-weight:600;")
        self.status = QLabel("")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
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
        self.token_state.setTextFormat(Qt.TextFormat.PlainText)
        self.token_state.setStyleSheet(MUTED)
        row.addWidget(self.token_box, 1)
        row.addWidget(self.use_token)
        row.addWidget(self.forget)
        row.addWidget(self.token_state)
        v.addLayout(row)
        self.message = QLabel("")
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        v.addWidget(self.message)
        self.tabs = QTabWidget()
        v.addWidget(self.tabs, 1)
        self.tabs.addTab(self._build_day(), "Day")
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

    def _build_day(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.day_view = _browser()
        v.addWidget(self.day_view, 4)
        self.day_box = QPlainTextEdit()
        self.day_box.setPlaceholderText("Your answer to the next step — immutable once saved")
        self.day_box.setFixedHeight(90)
        row = QHBoxLayout()
        self.day_step_button = QPushButton("Save step")
        self.mirror_button = QPushButton("Ask Ade for the mirror")
        row.addWidget(self.day_step_button)
        row.addStretch(1)
        row.addWidget(self.mirror_button)
        v.addWidget(self.day_box)
        v.addLayout(row)
        self.criteria_box = QWidget()
        cv = QVBoxLayout(self.criteria_box)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.addWidget(QLabel("Cycle goal (one claim):"))
        self.goal_combo = QComboBox()
        cv.addWidget(self.goal_combo)
        cv.addWidget(QLabel("Criteria (tick the claims the cycle is graded on):"))
        self.criteria_list = QListWidget()
        cv.addWidget(self.criteria_list, 1)
        self.mark_button = QPushButton("Mark criteria (final, needs your token)")
        cv.addWidget(self.mark_button)
        v.addWidget(self.criteria_box, 2)
        self.criteria_box.setVisible(False)
        self._charter_id = ""
        self.day_status: dict = {}
        self.day_step_button.clicked.connect(self._on_day_step)
        self.mirror_button.clicked.connect(self._on_mirror)
        self.mark_button.clicked.connect(self._on_mark)
        return w

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
        self.stage_label.setTextFormat(Qt.TextFormat.PlainText)
        self.stage_label.setStyleSheet(f"font-size:{SMALL_FONT_PX}px;")
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
        ok = self.client.set_token(self.token_box.text())
        self.token_box.clear()                      # not left sitting in a widget
        if not ok:
            self.message.setText("That is not a token: The Path prints one as plain "
                                 "letters and digits when `thepath serve` starts.")
            self.message.setStyleSheet(ERR_STYLE)
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
        for kind, rid in (("day", self.client.day()), ("today", self.client.today()), ("read", self.client.read_entries()),
                          ("diary", self.client.diary()), ("study", self.client.study()),
                          ("stage", self.client.stage()), ("catalogue", self.client.catalogue())):
            self._pending[rid] = (kind,)

    def _on_done(self, rid: str, result) -> None:
        job = self._pending.pop(rid, None)
        if job is None:
            return
        if job[0] == "mirror":                   # Ade OS answered, not The Path
            return self._got_mirror(result)
        if _unreachable(result):
            self._down()
            if job[0] in ("acted", "acted_day"):
                self.message.setText("Not sent: The Path is not answering. What you "
                                     "typed is still in its box.")
                self.message.setStyleSheet(ERR_STYLE)
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

    def _got_day(self, result) -> None:
        from ade_desktop.sections.path.day import can_ask_mirror, day_text, next_step
        if not _ok(result):
            self.day_view.setPlainText(f"Could not read the day: {error_cause(result)}")
            return
        self.day_status = result
        self.day_view.setPlainText(day_text(result))
        step = next_step(result)
        self.day_box.setEnabled(step is not None)
        self.day_step_button.setEnabled(step is not None)
        self.day_step_button.setText(f"Save step {step}" if step else "Save step")
        asking = any(job[0] == "mirror" for job in self._pending.values())
        self.mirror_button.setEnabled(can_ask_mirror(result) and not asking and
                                      self.mirror_client is not None)
        charter = result.get("charter") if result.get("state") == "criteria_unmarked" \
            else None
        self.criteria_box.setVisible(bool(charter))
        if charter:
            self._charter_id = charter["charter_id"]
            self.goal_combo.clear()
            self.criteria_list.clear()
            for c in charter["claims"]:
                label = f"#{c['ordinal']} {c['body']}"
                self.goal_combo.addItem(label, c["claim_id"])
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, c["claim_id"])
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                self.criteria_list.addItem(item)

    def _got_today(self, result) -> None:
        if not _ok(result):
            self.today_view.setPlainText(f"Could not read Today: {error_cause(result)}")
            return
        self.today = result
        self.today_view.setPlainText(today_text(result))
        # The page's rule (views.today): a source and no prompt -> record it
        # in your own words; no source -> Offer. The source may be the
        # LESSON's citation, so "offer_open" alone was the wrong test.
        has_prompt = isinstance(result.get("prompt"), dict)
        has_source = isinstance(result.get("source"), dict)
        self.offer_button.setEnabled(not has_prompt and not has_source)
        self.prompt_box.setVisible(has_source and not has_prompt)
        self.record_button.setVisible(has_source and not has_prompt)

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

    def _act(self, rid: str, *reread: str, clear=()) -> None:
        self._pending[rid] = ("acted", reread, tuple(clear))

    def _got_acted(self, result, reread, clear=()) -> None:
        """Typed text is cleared only once The Path has kept it: a refused
        or failed write leaves it where it was (review: it was cleared on
        send, and a failed write lost it)."""
        self._say(result)
        if _ok(result) and result.get("ok"):
            for box in clear:
                box.clear()
        for kind in reread:
            call = {"today": self.client.today, "read": self.client.read_entries,
                    "diary": self.client.diary, "study": self.client.study,
                    "stage": self.client.stage}[kind]
            self._pending[call()] = (kind,)

    def _on_entry(self) -> None:
        body = self.entry_box.toPlainText()
        if not body.strip():
            return
        self._act(self.client.write_entry(body), "today", "read", clear=(self.entry_box,))

    def _on_diary(self) -> None:
        body = self.diary_box.toPlainText()
        if not body.strip():
            return
        self._act(self.client.write_diary(body, self.diary_kind.currentText()), "diary", "read",
                  clear=(self.diary_box,))

    def _on_offer(self) -> None:
        self._act(self.client.offer(), "today")

    def _on_record(self) -> None:
        src = self.today.get("source") if isinstance(self.today, dict) else None
        text = self.prompt_box.toPlainText()
        if not isinstance(src, dict) or not text.strip():
            return
        self._act(self.client.record_prompt(text, src.get("citation_id") or "",
                                            str(src.get("stage") or ""),
                                            str(src.get("occasion") or "")), "today",
                  clear=(self.prompt_box,))

    def _on_draft(self) -> None:
        title, subject = self.draft_title.text().strip(), self.draft_subject.text().strip()
        if not title:
            return
        self._act(self.client.draft_teaching(title, subject), "study",
                  clear=(self.draft_title, self.draft_subject))

    def _on_claim(self) -> None:
        t = self.current_teaching
        body = self.claim_body.text().strip()
        if not t or not body:
            return

        def ids(box):
            return [x.strip() for x in box.text().split(",") if x.strip()]

        self._act(self.client.add_claim(t["teaching_id"], self.claim_category.currentText(),
                                        body, ids(self.claim_cites), ids(self.claim_drawn)),
                  "study", clear=(self.claim_body, self.claim_cites, self.claim_drawn))

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

    def _on_day_step(self) -> None:
        from ade_desktop.sections.path.day import next_step
        step, body = next_step(self.day_status), self.day_box.toPlainText()
        if step is None or not body.strip():
            return
        self._pending[self.client.reflect(step, body)] = ("acted_day",)

    def _got_acted_day(self, result) -> None:
        self._say(result)
        if _ok(result) and result.get("ok"):
            self.day_box.clear()                 # only once The Path kept it
        self._pending[self.client.day()] = ("day",)

    def _on_mirror(self) -> None:
        day = (self.day_status.get("day") or {}).get("day_id")
        if not day or self.mirror_client is None:
            return
        self.mirror_button.setEnabled(False)
        self.message.setText("Asked Ade for the mirror — a turn takes minutes.")
        self.message.setStyleSheet(MUTED)
        self._pending[self.mirror_client.ask(day)] = ("mirror",)

    def _got_mirror(self, result) -> None:
        """Every reply replaces the "Asked Ade…" line, in Ade's own words
        (task_report: ok:false, summary, degraded, low confidence). Whether
        a mirror was written is The Path's to say -- the day is re-read."""
        if not _ok(result):
            self.message.setText("Ade did not finish the mirror: "
                                 f"{error_cause(result)}. The day stays open; ask again.")
            self.message.setStyleSheet(ERR_STYLE)
        else:
            text, needs_a_look = task_report(result)
            if result.get("ok") is False:
                text += "\nThe day stays open; ask again."
            self.message.setText("Ade on the mirror: " + text)
            self.message.setStyleSheet(ERR_STYLE if needs_a_look else MUTED)
        self._pending[self.client.day()] = ("day",)

    def _on_mark(self) -> None:
        if not self.client.has_token():
            self.message.setText(NEED_TOKEN.format(what="Marking the criteria"))
            self.message.setStyleSheet(ERR_STYLE)
            return
        goal = self.goal_combo.currentData()
        items = [self.criteria_list.item(i) for i in range(self.criteria_list.count())
                 if self.criteria_list.item(i).checkState() == Qt.CheckState.Checked]
        ticked = [it.data(Qt.ItemDataRole.UserRole) for it in items]
        # FINAL AND APPEND-ONLY: nothing is sent until Ray has seen the goal
        # and every ticked criterion and said yes.
        if not self._confirm(self, "Mark the criteria?",
                             mark_question(self.goal_combo.currentText(),
                                           [it.text() for it in items])):
            self.message.setText("Not marked: nothing was sent.")
            self.message.setStyleSheet(MUTED)
            return
        self._pending[self.client.mark_criteria(self._charter_id, goal, ticked)] = \
            ("acted_day",)

    def stop_clients(self) -> None:
        self.client.forget_token()
        self.client.stop()
        if self.mirror_client is not None:
            self.mirror_client.stop()
