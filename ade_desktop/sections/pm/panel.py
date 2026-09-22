"""The PM section: projects on the left; on the right the selected project
in four tabs -- Overview (status, summary, its PMI and QA artifacts, the
editor), Backlog, Risks, Health -- and the add-project panel.

Every number and state on screen is Ade OS's answer; a write is followed
by a re-read, never an optimistic local copy (the web's rule: a second
copy of what the next read fetches is how a screen starts lying).
No lambda captures the panel: every connection is to a method.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog,
                               QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton,
                               QSplitter, QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from ade_desktop.conversation.replies import error_cause, failed
from ade_desktop.sections.pm import model
from ade_desktop.sections.pm.add_flow import AddProjectFlow
from ade_desktop.workspace.editor import FileEditor
from ade_desktop.workspace.files import is_missing
from ade_desktop.workspace.filling import WRITING_NOTE, filling

ERROR_STYLE = "color:#d95757;"
MUTED_STYLE = "color:#9aa1ab;"
TEXT_FILTER = ("Text documents (*.md *.txt *.rst *.markdown *.csv *.tsv *.json *.yaml "
               "*.yml *.feature *.xml *.html);;All files (*)")
STALE_S = 5.0


def _ok(result) -> bool:
    return not failed(result)


def _table(headers) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    t.horizontalHeader().setStretchLastSection(True)
    t.setWordWrap(True)
    return t


def _fill(table: QTableWidget, rows: list[list[str]], ids: list | None = None) -> None:
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            item = QTableWidgetItem(str(value if value is not None else ""))
            if ids is not None and c == 0:
                item.setData(Qt.ItemDataRole.UserRole, ids[r])
            table.setItem(r, c, item)
    table.resizeRowsToContents()


class AddProjectPanel(QWidget):
    """The web's panel, natively. The flow does the work; this only shows
    it and hands it the fields."""

    def __init__(self, flow: AddProjectFlow, *, pick_file=None, parent=None) -> None:
        super().__init__(parent)
        self.flow = flow
        self._pick = pick_file
        self.file_path: str | None = None
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 8)
        head = QLabel("Add project from requirements")
        head.setStyleSheet("font-weight:600;")
        box.addWidget(head)
        blurb = QLabel("Upload or paste a requirements document. The project and all PMI "
                       "Solo Software artifacts are created at once under pm/<slug>/, "
                       "then Ade fills them and writes the QA package under qa/<slug>/.")
        blurb.setWordWrap(True)
        blurb.setStyleSheet(MUTED_STYLE)
        box.addWidget(blurb)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Project name")
        box.addWidget(self.name)
        row = QHBoxLayout()
        self.file_label = QLabel("No file chosen")
        self.choose = QPushButton("Choose file…")
        self.clear_file = QPushButton("Clear")
        row.addWidget(self.file_label, 1)
        row.addWidget(self.choose)
        row.addWidget(self.clear_file)
        box.addLayout(row)
        self.paste = QPlainTextEdit()
        self.paste.setPlaceholderText("Or paste requirements… (# Heading becomes the name)")
        self.paste.setFixedHeight(110)
        box.addWidget(self.paste)
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Notes for Ade (optional)")
        self.notes.setFixedHeight(48)
        box.addWidget(self.notes)
        row = QHBoxLayout()
        self.run = QPushButton("Add project && generate artifacts")
        self.stop = QPushButton("Stop")
        self.stop.hide()
        row.addWidget(self.run)
        row.addWidget(self.stop)
        row.addStretch(1)
        box.addLayout(row)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(MUTED_STYLE)
        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setStyleSheet(ERROR_STYLE)
        box.addWidget(self.status)
        box.addWidget(self.error)
        self.lines = {}
        self.reruns = {}
        for pkg, label in (("pm", "PM fill"), ("qa", "QA package")):
            r = QHBoxLayout()
            line = QLabel(f"{label}: —")
            line.setStyleSheet("font-family: monospace;")
            rerun = QPushButton("Re-run")
            rerun.setProperty("pkg", pkg)
            rerun.hide()
            rerun.clicked.connect(self._on_rerun)
            r.addWidget(line, 1)
            r.addWidget(rerun)
            box.addLayout(r)
            self.lines[pkg], self.reruns[pkg] = line, rerun
        self._labels = {"pm": "PM fill", "qa": "QA package"}

        self.choose.clicked.connect(self._on_choose)
        self.clear_file.clicked.connect(self._on_clear_file)
        self.paste.textChanged.connect(self._on_paste)
        self.run.clicked.connect(self._on_run)
        self.stop.clicked.connect(self.flow.stop)
        flow.status.connect(self.status.setText)
        flow.failed.connect(self.error.setText)
        flow.package.connect(self._on_package)
        flow.progress.connect(self._on_progress)
        flow.busy_changed.connect(self._on_busy)

    def _on_choose(self) -> None:
        if self._pick is not None:
            path = self._pick()
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Requirements document", "", TEXT_FILTER)
        if path:
            self.file_path = path
            self.file_label.setText(path)
            self.paste.setEnabled(False)
            if not self.name.text().strip():
                self.name.setText(model.name_from_file(path))

    def _on_clear_file(self) -> None:
        self.file_path = None
        self.file_label.setText("No file chosen")
        self.paste.setEnabled(True)

    def _on_paste(self) -> None:
        if not self.name.text().strip():
            heading = model.name_from_paste(self.paste.toPlainText())
            if heading:
                self.name.setText(heading)

    def _on_run(self) -> None:
        self.error.setText("")
        for pkg in ("pm", "qa"):
            self.lines[pkg].setText(f"{self._labels[pkg]}: —")
            self.reruns[pkg].hide()
        self.flow.start(self.name.text(), self.file_path, self.paste.toPlainText(),
                        self.notes.toPlainText())

    def _on_rerun(self) -> None:
        pkg = self.sender().property("pkg")
        self.reruns[pkg].hide()
        self.flow.rerun(pkg)

    def _on_package(self, pkg: str, kind: str, note: str) -> None:
        if kind == "running":
            self.lines[pkg].setText(f"{self._labels[pkg]}: running…")
            return
        self.lines[pkg].setText(f"{self._labels[pkg]}: {note}")
        self.reruns[pkg].setVisible(kind in ("error", "stale"))

    def _on_progress(self, pkg: str, done: int, total: int, current: str) -> None:
        self.lines[pkg].setText(f"{self._labels[pkg]}: authoring {current}… ({done}/{total})")

    def _on_busy(self, busy: bool) -> None:
        for w in (self.name, self.choose, self.clear_file, self.notes, self.run):
            w.setEnabled(not busy)
        self.paste.setEnabled(not busy and self.file_path is None)
        self.stop.setVisible(busy)
        for b in self.reruns.values():
            b.setEnabled(not busy)


class PmPanel(QWidget):
    section_requested = Signal(str)     # "QA": the window switches its rail

    def __init__(self, pm, files, active, *, ask_text=None, pick_file=None,
                 confirm=None, clock=time.monotonic, parent=None) -> None:
        super().__init__(parent)
        self.pm, self.files, self.active = pm, files, active
        self._ask_text = ask_text
        self._confirm = confirm
        self._clock = clock
        self._last_refresh = -1e9
        self._pending: dict[str, tuple] = {}
        self._latest: dict[str, str] = {}     # kind -> the newest read's request id
        self.projects: list[dict] = []
        self.backlog_rows: list[dict] = []
        self.backlog_statuses: list[str] = []
        self.risk_rows: list[dict] = []
        self.selected: dict | None = None
        self._build(pick_file)
        pm.done.connect(self._on_done)
        files.done.connect(self._on_done)
        active.changed.connect(self._on_active_changed)

    # -- layout -----------------------------------------------------------------

    def _build(self, pick_file) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        split = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(split)

        rail = QWidget()
        rv = QVBoxLayout(rail)
        rv.setContentsMargins(0, 0, 6, 0)
        row = QHBoxLayout()
        title = QLabel("Projects")
        title.setStyleSheet("font-weight:600;")
        self.add_toggle = QPushButton("+ Add")
        self.add_toggle.setCheckable(True)
        self.refresh_button = QPushButton("Refresh")
        row.addWidget(title, 1)
        row.addWidget(self.add_toggle)
        row.addWidget(self.refresh_button)
        rv.addLayout(row)
        self.show_archived = QCheckBox("Show archived")
        rv.addWidget(self.show_archived)
        self.rail = QListWidget()
        rv.addWidget(self.rail, 1)
        self.rail_note = QLabel("Loading projects…")
        self.rail_note.setWordWrap(True)
        self.rail_note.setStyleSheet(MUTED_STYLE)
        rv.addWidget(self.rail_note)
        split.addWidget(rail)

        right = QWidget()
        box = QVBoxLayout(right)
        box.setContentsMargins(6, 0, 0, 0)
        self.flow = AddProjectFlow(self.pm, self.files, parent=self)
        self.add_panel = AddProjectPanel(self.flow, pick_file=pick_file)
        self.add_panel.hide()
        box.addWidget(self.add_panel)
        head = QHBoxLayout()
        self.title = QLabel("")
        self.title.setStyleSheet("font-weight:600;")
        self.status_combo = QComboBox()
        for s in model.PROJECT_STATES:
            self.status_combo.addItem(model.format_status(s), s)
        head.addWidget(self.title, 1)
        head.addWidget(self.status_combo)
        box.addLayout(head)
        self.status_error = QLabel("")
        self.status_error.setStyleSheet(ERROR_STYLE)
        self.status_error.setWordWrap(True)
        box.addWidget(self.status_error)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet(MUTED_STYLE)
        box.addWidget(self.summary)
        self.tabs = QTabWidget()
        box.addWidget(self.tabs, 1)
        self.tabs.addTab(self._build_overview(), "Overview")
        self.tabs.addTab(self._build_backlog(), "Backlog")
        self.tabs.addTab(self._build_risks(), "Risks")
        self.tabs.addTab(self._build_health(), "Health")
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([240, 900])

        self.add_toggle.toggled.connect(self.add_panel.setVisible)
        self.refresh_button.clicked.connect(self.refresh)
        self.show_archived.toggled.connect(self._render_rail)
        self.rail.currentItemChanged.connect(self._on_rail_pick)
        self.status_combo.activated.connect(self._on_status_picked)
        self.tabs.currentChanged.connect(self._on_tab)
        self.flow.created.connect(self._on_created)
        self.flow.busy_changed.connect(self._on_flow_busy)
        self.flow.package.connect(self._on_flow_package)
        filling().changed.connect(self._label_groups)

    def _build_overview(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        lists = QHBoxLayout()
        self.pm_label, self.pm_list, pm_box = self._artifact_group("PM artifacts")
        self.qa_label, self.qa_list, qa_box = self._artifact_group("QA package")
        self.qa_desk = QPushButton("Open QA desk →")
        self.qa_desk.clicked.connect(self._on_open_qa)
        qa_box.addWidget(self.qa_desk)
        lists.addLayout(pm_box, 1)
        lists.addLayout(qa_box, 1)
        v.addLayout(lists, 1)
        self.editor = FileEditor(self.files, confirm=self._confirm)
        self.editor.hide()
        self.editor.closed.connect(self.editor.hide)
        v.addWidget(self.editor, 3)
        self.pm_list.itemClicked.connect(self._on_open_artifact)
        self.qa_list.itemClicked.connect(self._on_open_artifact)
        return w

    def _artifact_group(self, title: str):
        box = QVBoxLayout()
        label = QLabel(title)
        label.setStyleSheet("font-weight:600;")
        box.addWidget(label)
        lst = QListWidget()
        lst.setStyleSheet("font-family: monospace;")
        box.addWidget(lst, 1)
        return label, lst, box

    def _build_backlog(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        self.backlog_filter = QComboBox()
        self.backlog_filter.addItem("All", "")
        row.addWidget(QLabel("Status:"))
        row.addWidget(self.backlog_filter)
        row.addStretch(1)
        self.backlog_buttons = {}
        for action, label in (("complete", "Complete"), ("promote", "Promote"),
                              ("drop", "Drop"), ("reopen", "Reopen")):
            b = QPushButton(label)
            b.setProperty("action", action)
            b.clicked.connect(self._on_backlog_action)
            b.setEnabled(False)
            row.addWidget(b)
            self.backlog_buttons[action] = b
        v.addLayout(row)
        self.backlog_table = _table(["Title", "Detail", "Status", "Resolution"])
        v.addWidget(self.backlog_table, 1)
        row = QHBoxLayout()
        self.backlog_title = QLineEdit()
        self.backlog_title.setPlaceholderText("New item")
        self.backlog_detail = QLineEdit()
        self.backlog_detail.setPlaceholderText("Detail (optional)")
        self.backlog_add = QPushButton("Add")
        row.addWidget(self.backlog_title, 2)
        row.addWidget(self.backlog_detail, 3)
        row.addWidget(self.backlog_add)
        v.addLayout(row)
        self.backlog_note = QLabel("")
        self.backlog_note.setWordWrap(True)
        v.addWidget(self.backlog_note)
        self.backlog_filter.activated.connect(self._render_backlog)
        self.backlog_table.itemSelectionChanged.connect(self._sync_backlog_buttons)
        self.backlog_add.clicked.connect(self._on_backlog_add)
        self.backlog_title.returnPressed.connect(self._on_backlog_add)
        return w

    def _build_risks(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.risk_table = _table(["Title", "Probability", "Impact", "Severity",
                                  "Response", "Owner", "Status"])
        v.addWidget(self.risk_table, 1)
        row = QHBoxLayout()
        self.risk_title = QLineEdit()
        self.risk_title.setPlaceholderText("New risk")
        self.risk_prob = QComboBox()
        self.risk_impact = QComboBox()
        for c in (self.risk_prob, self.risk_impact):
            for level in model.RISK_LEVELS:
                c.addItem(level)
            c.setCurrentText("medium")
        self.risk_response_edit = QLineEdit()
        self.risk_response_edit.setPlaceholderText("Response (optional)")
        self.risk_add = QPushButton("Add")
        row.addWidget(self.risk_title, 2)
        row.addWidget(QLabel("P"))
        row.addWidget(self.risk_prob)
        row.addWidget(QLabel("I"))
        row.addWidget(self.risk_impact)
        row.addWidget(self.risk_response_edit, 2)
        row.addWidget(self.risk_add)
        v.addLayout(row)
        row = QHBoxLayout()
        self.risk_set_response = QPushButton("Set response…")
        self.risk_set_response.setEnabled(False)
        row.addStretch(1)
        row.addWidget(self.risk_set_response)
        v.addLayout(row)
        self.risk_note = QLabel("")
        self.risk_note.setWordWrap(True)
        v.addWidget(self.risk_note)
        self.risk_add.clicked.connect(self._on_risk_add)
        self.risk_title.returnPressed.connect(self._on_risk_add)
        self.risk_table.itemSelectionChanged.connect(self._sync_risk_buttons)
        self.risk_set_response.clicked.connect(self._on_risk_response)
        return w

    def _build_health(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        self.health_summary = QLabel("Open this tab to run a monitoring cycle.")
        self.health_summary.setWordWrap(True)
        self.health_refresh = QPushButton("Run again")
        row.addWidget(self.health_summary, 1)
        row.addWidget(self.health_refresh)
        v.addLayout(row)
        self.health_table = _table(["Severity", "Domain", "Subject", "What", "Why",
                                    "Evidence"])
        v.addWidget(self.health_table, 1)
        self.coverage = QLabel("")
        self.coverage.setWordWrap(True)
        self.coverage.setStyleSheet(MUTED_STYLE)
        v.addWidget(self.coverage)
        self.health_refresh.clicked.connect(self.run_findings)
        return w

    def stop_clients(self) -> None:
        self.flow.close()
        self.pm.stop()
        self.files.stop()

    # -- loading ----------------------------------------------------------------

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._clock() - self._last_refresh > STALE_S:
            self.refresh()

    def _read(self, kind: str, rid: str) -> None:
        """Answers can arrive out of order; only the newest read of a kind
        is shown (review: a refresh landing after a write's re-read showed
        the state from before the write)."""
        self._latest[kind] = rid
        self._pending[rid] = (kind,)

    def refresh(self) -> None:
        self._last_refresh = self._clock()
        self._read("projects", self.pm.projects())
        self._read("backlog", self.pm.backlog())
        self._read("risks", self.pm.risks())
        if self.tabs.currentIndex() == 3:
            self.run_findings()

    def run_findings(self) -> None:
        self.health_summary.setText("Running a monitoring cycle…")
        self._read("findings", self.pm.findings())

    def _on_tab(self, index: int) -> None:
        if index == 3:
            self.run_findings()

    def _on_done(self, rid: str, result) -> None:
        job = self._pending.pop(rid, None)
        if job is None:
            return
        if job[0] in self._latest and self._latest[job[0]] != rid:
            return                                  # an older read of the same thing
        getattr(self, f"_got_{job[0]}")(result, *job[1:])

    def _got_projects(self, result) -> None:
        if not _ok(result):
            self.rail_note.setText(f"Could not load projects: {error_cause(result)}")
            self.rail_note.setStyleSheet(ERROR_STYLE)
            return
        self.rail_note.setStyleSheet(MUTED_STYLE)
        self.projects = [p for p in result.get("projects") or [] if isinstance(p, dict)]
        self._render_rail()

    def _got_backlog(self, result) -> None:
        if not _ok(result):
            self.backlog_note.setText(f"Could not load the backlog: {error_cause(result)}")
            self.backlog_note.setStyleSheet(ERROR_STYLE)
            return
        self.backlog_note.setStyleSheet("")
        self.backlog_note.setText("")
        self.backlog_rows = [b for b in result.get("backlog") or [] if isinstance(b, dict)]
        self.backlog_statuses = [s for s in result.get("statuses") or [] if isinstance(s, str)]
        self._render_backlog()

    def _got_risks(self, result) -> None:
        if not _ok(result):
            self.risk_note.setText(f"Could not load the risks: {error_cause(result)}")
            self.risk_note.setStyleSheet(ERROR_STYLE)
            return
        self.risk_note.setStyleSheet("")
        self.risk_note.setText("")
        self.risk_rows = [r for r in result.get("risks") or [] if isinstance(r, dict)]
        self._render_risks()

    def _got_findings(self, result) -> None:
        if not _ok(result):
            self.health_summary.setText(f"The monitoring cycle failed: {error_cause(result)}")
            return
        found = model.sort_findings([f for f in result.get("findings") or []
                                     if isinstance(f, dict)])
        if result.get("detail") and not found:
            # "no records store configured": nothing was measured, which
            # is not the same as healthy (the daemon's own rule).
            self.health_summary.setText(f"Not measured: {result['detail']}.")
        else:
            self.health_summary.setText(
                model.summarise_findings(result.get("summary") or {})
                + " — across every live project, not only this one.")
        _fill(self.health_table, [[f.get("severity"), f.get("domain"), f.get("subject") or "—",
                                   f.get("what"), f.get("why"), f.get("evidence")]
                                  for f in found])
        cov = result.get("coverage") or {}
        covered = ", ".join(cov.get("covered") or [])
        uncovered = cov.get("uncovered") or {}
        text = f"PMBOK areas covered: {covered or 'none'}."
        if isinstance(uncovered, dict) and uncovered:
            text += "  Not covered: " + "; ".join(f"{k} — {v}" for k, v in uncovered.items())
        self.coverage.setText(text)

    # -- the rail and the selection --------------------------------------------------

    def _render_rail(self) -> None:
        shown = model.visible(self.projects, self.show_archived.isChecked())
        self.rail.blockSignals(True)
        self.rail.clear()
        for p in shown:
            item = QListWidgetItem(f"{p.get('name')}    {model.format_status(p.get('status'))}")
            item.setData(Qt.ItemDataRole.UserRole, p.get("name"))
            self.rail.addItem(item)
        self.rail.blockSignals(False)
        self.rail_note.setText("" if shown else model.empty_label(
            self.projects, self.show_archived.isChecked()))
        self._select(model.pick(shown, self.active.name), shown)

    def _select(self, project: dict | None, shown: list[dict]) -> None:
        # The web's sync rule: an active name hidden by the archive filter
        # moves to what is showing, so QA never keeps pointing at a hidden
        # project; an empty name adopts the first, so QA has one at all.
        hidden = (self.active.name and project is not None
                  and self.active.name != project.get("name")
                  and any(p.get("name") == self.active.name for p in self.projects))
        if project is not None and (not self.active.name or hidden):
            self.active.set(project["name"])      # re-enters via _on_active_changed
            return
        changed = (self.selected or {}).get("name") != (project or {}).get("name")
        self.selected = project
        for i in range(self.rail.count()):
            if project and self.rail.item(i).data(Qt.ItemDataRole.UserRole) == project["name"]:
                self.rail.blockSignals(True)
                self.rail.setCurrentRow(i)
                self.rail.blockSignals(False)
        self._render_selected(changed)

    def _on_rail_pick(self, current, previous) -> None:
        if current is not None:
            self.active.set(current.data(Qt.ItemDataRole.UserRole))

    def _on_active_changed(self, name: str) -> None:
        self._render_rail()

    def _render_selected(self, changed: bool) -> None:
        p = self.selected
        has = p is not None
        self.title.setText(p["name"] if has else "No project selected")
        self.status_combo.setEnabled(has)
        self.summary.setText((p or {}).get("summary") or "")
        if has:
            idx = self.status_combo.findData(p.get("status") or "active")
            self.status_combo.setCurrentIndex(max(0, idx))
        if changed:
            self.status_error.setText("")
            if self.editor.path and not self.editor.close_file():
                pass                                # kept: the user chose to
            self._list_artifacts()
        self._render_backlog()
        self._render_risks()

    def _list_artifacts(self) -> None:
        self.pm_list.clear()
        self.qa_list.clear()
        if self.selected is None:
            return
        s = model.slug(self.selected["name"])
        self._label_groups()
        self._pending[self.files.list_dir(f"pm/{s}")] = ("listing", "pm", s)
        self._pending[self.files.list_dir(f"qa/{s}")] = ("listing", "qa", s)

    def _label_groups(self) -> None:
        if self.selected is None:
            self.editor.block_reason = WRITING_NOTE if filling().folder_of(self.editor.path) else ""
            return
        s = model.slug(self.selected["name"])
        for label, title, d in ((self.pm_label, "PM artifacts", f"pm/{s}"),
                                (self.qa_label, "QA package", f"qa/{s}")):
            label.setText(f"{title}   {d}/" + ("   filling…" if filling().is_filling(d) else ""))
        # A document Ade is about to rewrite must not be saved over meanwhile
        # -- whichever panel's run is writing it.
        self.editor.block_reason = WRITING_NOTE if filling().folder_of(self.editor.path) else ""

    def _got_listing(self, result, which: str, slug: str) -> None:
        if self.selected is None or model.slug(self.selected["name"]) != slug:
            return                              # a listing for the project before
        lst = self.pm_list if which == "pm" else self.qa_list
        lst.clear()
        missing = is_missing(result)
        entries = [e for e in (result.get("entries") or []) if e.get("kind") == "file"] \
            if _ok(result) else []
        for e in entries:
            item = QListWidgetItem(e.get("name"))
            item.setData(Qt.ItemDataRole.UserRole, e.get("path"))
            lst.addItem(item)
        if not entries:
            if _ok(result) or missing:
                text = ("No PMI artifacts yet — use + Add." if which == "pm"
                        else "No QA package yet.")
            else:
                text = f"Could not list it: {error_cause(result)}"
            empty = QListWidgetItem(text)
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            lst.addItem(empty)

    def _on_open_artifact(self, item) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and self.editor.open(path):
            self.editor.show()
            self._label_groups()

    def _on_open_qa(self) -> None:
        self.section_requested.emit("QA")

    # -- status -------------------------------------------------------------------

    def _on_status_picked(self, index: int) -> None:
        p = self.selected
        status = self.status_combo.itemData(index)
        if p is None or status == p.get("status"):
            return
        self.status_error.setText("")
        # Not an optimistic copy: the combo goes back to what Ade OS last
        # said and waits, disabled, for the re-read to show the change.
        self.status_combo.setCurrentIndex(max(0, self.status_combo.findData(p.get("status"))))
        self.status_combo.setEnabled(False)
        self._pending[self.pm.set_status(p["id"], status)] = ("status", p["name"], p.get("status"))

    def _got_status(self, result, name: str, before: str) -> None:
        self.status_combo.setEnabled(self.selected is not None)
        if not _ok(result):
            self.status_error.setText(f"{name}: {error_cause(result)}")
            if self.selected and self.selected.get("name") == name:
                self.status_combo.setCurrentIndex(max(0, self.status_combo.findData(before)))
            return
        self._read("projects", self.pm.projects())

    # -- backlog ------------------------------------------------------------------

    def _render_backlog(self, *_) -> None:
        name = (self.selected or {}).get("name")
        rows = model.for_project(self.backlog_rows, name) if name else []
        present = sorted({r.get("status") for r in rows if r.get("status")})
        want = self.backlog_filter.currentData() or ""
        self.backlog_filter.blockSignals(True)
        self.backlog_filter.clear()
        self.backlog_filter.addItem("All", "")
        for s in present:
            self.backlog_filter.addItem(s, s)
        self.backlog_filter.setCurrentIndex(max(0, self.backlog_filter.findData(want)))
        self.backlog_filter.blockSignals(False)
        want = self.backlog_filter.currentData() or ""
        shown = [r for r in rows if not want or r.get("status") == want]
        _fill(self.backlog_table, [[r.get("title"), r.get("detail"), r.get("status"),
                                    r.get("resolution")] for r in shown],
              [r.get("id") for r in shown])
        if self.backlog_note.styleSheet() != ERROR_STYLE:
            self.backlog_note.setText("" if shown or not name
                                      else "No backlog items for this project.")
        self.backlog_add.setEnabled(bool(name))
        self._sync_backlog_buttons()

    def _selected_id(self, table: QTableWidget):
        items = table.selectedItems()
        if not items:
            return None
        return table.item(items[0].row(), 0).data(Qt.ItemDataRole.UserRole)

    def _row(self, rows, rid):
        return next((r for r in rows if r.get("id") == rid), None)

    def _sync_backlog_buttons(self) -> None:
        row = self._row(self.backlog_rows, self._selected_id(self.backlog_table))
        is_open = bool(row) and row.get("status") == "open"
        for action in model.BACKLOG_ACTIONS:
            self.backlog_buttons[action].setEnabled(is_open)
        self.backlog_buttons["reopen"].setEnabled(bool(row) and not is_open)

    def _on_backlog_action(self) -> None:
        action = self.sender().property("action")
        rid = self._selected_id(self.backlog_table)
        if rid is None:
            return
        call = self.pm.reopen(rid) if action == "reopen" else self.pm.backlog_action(rid, action)
        self._pending[call] = ("backlog_write", action)

    def _on_backlog_add(self) -> None:
        title = self.backlog_title.text().strip()
        if not title or self.selected is None:
            return
        self._pending[self.pm.add_backlog(title, self.backlog_detail.text().strip(),
                                          self.selected["name"])] = ("backlog_write", "add")

    def _got_backlog_write(self, result, what: str) -> None:
        if not _ok(result):
            self.backlog_note.setStyleSheet(ERROR_STYLE)
            self.backlog_note.setText(f"Could not {what}: {error_cause(result)}")
            return
        self.backlog_note.setStyleSheet("")
        self.backlog_note.setText("")
        if what == "add":
            self.backlog_title.clear()
            self.backlog_detail.clear()
        self._read("backlog", self.pm.backlog())

    # -- risks --------------------------------------------------------------------

    def _render_risks(self) -> None:
        name = (self.selected or {}).get("name")
        # Ade OS's order: highest severity (probability x impact) first.
        rows = model.for_project(self.risk_rows, name) if name else []
        _fill(self.risk_table, [[r.get("title"), r.get("probability"), r.get("impact"),
                                 r.get("severity"), r.get("response"), r.get("owner"),
                                 r.get("status")] for r in rows],
              [r.get("id") for r in rows])
        if self.risk_note.styleSheet() != ERROR_STYLE:
            self.risk_note.setText("" if rows or not name else
                                   "No risks recorded. A live project with none has "
                                   "unexamined ones, not none.")
        self.risk_add.setEnabled(bool(name))
        self._sync_risk_buttons()

    def _sync_risk_buttons(self) -> None:
        self.risk_set_response.setEnabled(self._selected_id(self.risk_table) is not None)

    def _on_risk_add(self) -> None:
        title = self.risk_title.text().strip()
        if not title or self.selected is None:
            return
        self._pending[self.pm.add_risk(title, self.selected["name"],
                                       self.risk_prob.currentText(),
                                       self.risk_impact.currentText(),
                                       self.risk_response_edit.text().strip())] = ("risk_write", "add")

    def _on_risk_response(self) -> None:
        rid = self._selected_id(self.risk_table)
        row = self._row(self.risk_rows, rid)
        if row is None:
            return
        if self._ask_text is not None:
            text = self._ask_text("Risk response", row.get("title") or "", row.get("response") or "")
        else:
            text, ok = QInputDialog.getText(self, "Risk response", row.get("title") or "",
                                            text=row.get("response") or "")
            text = text if ok else None
        if text is None:
            return
        self._pending[self.pm.risk_response(rid, text)] = ("risk_write", "set the response")

    def _got_risk_write(self, result, what: str) -> None:
        if not _ok(result):
            self.risk_note.setStyleSheet(ERROR_STYLE)
            self.risk_note.setText(f"Could not {what}: {error_cause(result)}")
            return
        self.risk_note.setStyleSheet("")
        self.risk_note.setText("")
        if what == "add":
            self.risk_title.clear()
            self.risk_response_edit.clear()
        self._read("risks", self.pm.risks())

    # -- add project ----------------------------------------------------------------

    def _on_created(self, name: str) -> None:
        self.active.set(name)
        self._read("projects", self.pm.projects())

    def _on_flow_busy(self, busy: bool) -> None:
        self._label_groups()
        if not busy:
            self._list_artifacts()      # the disk, not the flow's summary

    def _on_flow_package(self, pkg: str, kind: str, note: str) -> None:
        self._label_groups()            # "filling…" follows the package being written

    # -- quitting -----------------------------------------------------------------

    def unsaved(self) -> list[str]:
        """What quitting would lose: an edited file, a save in flight, an
        authoring run in progress."""
        lost = []
        if self.editor.is_dirty():
            lost.append(f"unsaved changes to {self.editor.path}")
        if self.editor.is_busy():
            lost.append(f"a save of {self.editor.path} still in flight")
        if self.flow.busy:
            lost.append("an add-project run still authoring documents")
        return lost
