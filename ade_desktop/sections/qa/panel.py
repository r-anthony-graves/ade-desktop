"""The QA desk: the web's 16-section rail over the ACTIVE project's QA
package (qa/<slug>/), natively.

    Dashboard        the package's 13 documents present or missing (one
                     /v1/fs listing), Ade's activity, quick links -- only
                     measured things; the web's six "—" tiles are not ported
    Requirements     generate the package into THIS project's qa/<slug>/
                     (one /v1/pm/author per document), then its requirements.md
    13 artifacts     qa/<slug>/<file> in the shared editor; missing -> the
                     catalogue board and a note
    Test Execution   dispatch one of the qa primary's task types (/v1/tasks)
    Settings         the catalogue board

No lambda captures the panel: every connection is to a method.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPlainTextEdit, QPushButton, QStackedWidget,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ade_desktop.conversation.replies import error_cause, failed, task_report, task_types_from
from ade_desktop.sections.pm import model as pm_model
from ade_desktop.sections.pm.add_flow import AddProjectFlow
from ade_desktop.sections.pm.panel import ERROR_STYLE, MUTED_STYLE, TEXT_FILTER
from ade_desktop.sections.qa import model
from ade_desktop.workspace.editor import FileEditor
from ade_desktop.workspace.files import is_missing
from ade_desktop.workspace.filling import WRITING_NOTE, filling

STALE_S = 5.0
NO_PROJECT = "No project is selected. Pick one in PM — the QA desk follows it."


def _ok(result) -> bool:
    return not failed(result)


def _muted(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(MUTED_STYLE)
    return label


class ArtifactView(QWidget):
    """One section's document: the editor when the file exists, else the
    catalogue board and what is missing."""

    def __init__(self, files, *, confirm=None, parent=None) -> None:
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        self.board = _muted()
        box.addWidget(self.board)
        row = QHBoxLayout()
        self.missing = QLabel("")
        self.missing.setWordWrap(True)
        self.again = QPushButton("Check again")
        self.again.hide()
        row.addWidget(self.missing, 1)
        row.addWidget(self.again)
        box.addLayout(row)
        self.editor = FileEditor(files, confirm=confirm)
        self.editor.hide()
        box.addWidget(self.editor, 1)
        self.path: str | None = None
        self._label = ""
        self._loaded_ok: bool | None = None     # for self.path, once it answered
        self.editor.loaded.connect(self._on_loaded)
        self.again.clicked.connect(self.reload)

    def show_section(self, sec: dict, path: str | None, project: str) -> None:
        self.board.setText(model.board_text(sec))
        self._label = project
        self.missing.setText("")
        self.again.hide()
        if path is None:
            self.path, self._loaded_ok = None, None
            self.editor.hide()
            self.board.show()
            if not project:
                self.missing.setText(NO_PROJECT)
            return
        if path == self.path and self.editor.path == path and self._loaded_ok is not None:
            self._apply(self._loaded_ok)
            return
        if self.editor.path != path and not self.editor.open(path):
            # The user kept unsaved edits elsewhere: say so, and keep that
            # file in view rather than a board for a section it is not.
            self.board.hide()
            self.editor.show()
            self.missing.setText(f"Still editing {self.editor.path}: save or revert it "
                                 f"to open {path}.")
            return
        if self.editor.path == path and self.path != path:
            self.editor.revert()                    # the same file, asked for anew
        self.path, self._loaded_ok = path, None

    def reload(self) -> None:
        if self.path:
            self._loaded_ok = None
            self.editor.revert()

    def _on_loaded(self, path: str, ok: bool) -> None:
        if path != self.path:
            return
        self._loaded_ok = ok
        self._apply(ok)

    def _apply(self, ok: bool) -> None:
        # Only a document that is not THERE shows the board. A timeout, a
        # refusal or an unreachable Ade OS shows the editor with its reason:
        # "missing" there would invite regenerating over a file that exists.
        absent = not ok and self.editor.missing
        self.editor.setVisible(not absent)
        self.board.setVisible(absent)
        if absent:
            file = (self.path or "").rsplit("/", 1)[-1]
            self.missing.setText(f"No {file} for “{self._label}” yet ({self.path}).")
        self.again.setVisible(not ok)

    def reread(self) -> None:
        """After Ade wrote the package: read the document again, unless the
        user has edits in it (those are never replaced silently)."""
        if not self.path or self.editor.path != self.path:
            return
        if self.editor.is_dirty():
            self.missing.setText(f"Ade rewrote this package; {self.path} has your unsaved "
                                 "edits, so it was not reloaded. Revert to see Ade's version.")
            return
        self._loaded_ok = None
        self.editor.revert()

    def sync_block(self) -> None:
        folder = filling().folder_of(self.editor.path)
        self.editor.block_reason = WRITING_NOTE if folder else ""


class QaPanel(QWidget):
    section_requested = Signal(str)       # "PM"

    def __init__(self, qa, pm, files, active, *, pick_file=None, confirm=None,
                 clock=time.monotonic, parent=None) -> None:
        super().__init__(parent)
        self.qa, self.pm, self.files, self.active = qa, pm, files, active
        self._pick = pick_file
        self._clock = clock
        self._last_refresh = -1e9
        self._pending: dict[str, tuple] = {}
        self.projects: list[dict] = []
        self.types: list[str] = list(model.FALLBACK_TYPES)
        self.flow = AddProjectFlow(pm, files, parent=self)
        self._stale = False
        self._dispatching = False
        self._build(confirm)
        qa.done.connect(self._on_done)
        files.done.connect(self._on_done)
        active.changed.connect(self._on_active_changed)
        self.flow.package.connect(self._on_package)
        self.flow.progress.connect(self._on_progress)
        self.flow.status.connect(self.gen_status.setText)
        self.flow.failed.connect(self.gen_error.setText)
        self.flow.busy_changed.connect(self._on_gen_busy)
        filling().changed.connect(self._on_filling)

    # -- layout -----------------------------------------------------------------

    def _build(self, confirm) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        head = QHBoxLayout()
        title = QLabel("QA")
        title.setStyleSheet("font-weight:600;")
        self.project_label = _muted()
        head.addWidget(title)
        head.addWidget(self.project_label, 1)
        outer.addLayout(head)
        body = QHBoxLayout()
        outer.addLayout(body, 1)
        self.rail = QListWidget()
        self.rail.setFixedWidth(190)
        for sec in model.SECTIONS:
            item = QListWidgetItem(sec["label"])
            item.setData(Qt.ItemDataRole.UserRole, sec["id"])
            self.rail.addItem(item)
        body.addWidget(self.rail)
        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)

        self.dashboard = self._build_dashboard()
        self.requirements = self._build_requirements(confirm)
        self.artifact = ArtifactView(self.files, confirm=confirm)
        self.execution = self._build_execution()
        self.board_only = QWidget()
        bl = QVBoxLayout(self.board_only)
        self.board_label = _muted()
        bl.addWidget(self.board_label)
        bl.addStretch(1)
        for page in (self.dashboard, self.requirements, self.artifact, self.execution,
                     self.board_only):
            self.stack.addWidget(page)
        self.rail.currentRowChanged.connect(self._on_section)
        self.rail.setCurrentRow(0)

    def _build_dashboard(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_muted(model.section("dashboard")["purpose"]))
        self.package_note = QLabel("")
        self.package_note.setWordWrap(True)
        v.addWidget(self.package_note)
        self.package_table = QTableWidget(0, 3)
        self.package_table.setHorizontalHeaderLabels(["Section", "Document", "On disk"])
        self.package_table.verticalHeader().setVisible(False)
        self.package_table.horizontalHeader().setStretchLastSection(True)
        self.package_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        v.addWidget(self.package_table, 1)
        self.activity_label = QLabel("")
        v.addWidget(self.activity_label)
        row = QHBoxLayout()
        self.go_generate = QPushButton("Generate the package…")
        self.go_pm = QPushButton("Projects (PM) →")
        self.dash_refresh = QPushButton("Refresh")
        row.addWidget(self.go_generate)
        row.addWidget(self.go_pm)
        row.addStretch(1)
        row.addWidget(self.dash_refresh)
        v.addLayout(row)
        self.go_generate.clicked.connect(self._on_go_generate)
        self.go_pm.clicked.connect(self._on_go_pm)
        self.dash_refresh.clicked.connect(self.refresh)
        return w

    def _build_requirements(self, confirm) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        head = QLabel("Generate the QA package from requirements")
        head.setStyleSheet("font-weight:600;")
        v.addWidget(head)
        self.gen_target = _muted()
        v.addWidget(self.gen_target)
        row = QHBoxLayout()
        self.gen_file_label = QLabel("No file chosen")
        self.gen_choose = QPushButton("Choose file…")
        self.gen_clear = QPushButton("Clear")
        row.addWidget(self.gen_file_label, 1)
        row.addWidget(self.gen_choose)
        row.addWidget(self.gen_clear)
        v.addLayout(row)
        self.gen_paste = QPlainTextEdit()
        self.gen_paste.setPlaceholderText("Or paste requirements…")
        self.gen_paste.setFixedHeight(90)
        v.addWidget(self.gen_paste)
        self.gen_notes = QPlainTextEdit()
        self.gen_notes.setPlaceholderText("Notes for Ade (optional)")
        self.gen_notes.setFixedHeight(44)
        v.addWidget(self.gen_notes)
        row = QHBoxLayout()
        self.gen_run = QPushButton("Generate QA package")
        self.gen_stop = QPushButton("Stop")
        self.gen_stop.hide()
        self.gen_rerun = QPushButton("Re-run")
        self.gen_rerun.hide()
        row.addWidget(self.gen_run)
        row.addWidget(self.gen_stop)
        row.addWidget(self.gen_rerun)
        row.addStretch(1)
        v.addLayout(row)
        self.gen_status = _muted()
        self.gen_error = QLabel("")
        self.gen_error.setWordWrap(True)
        self.gen_error.setStyleSheet(ERROR_STYLE)
        self.gen_line = QLabel("QA package: —")
        self.gen_line.setStyleSheet("font-family: monospace;")
        for x in (self.gen_status, self.gen_error, self.gen_line):
            v.addWidget(x)
        self.req_artifact = ArtifactView(self.files, confirm=confirm)
        v.addWidget(self.req_artifact, 1)
        self.gen_file: str | None = None
        self.gen_choose.clicked.connect(self._on_gen_choose)
        self.gen_clear.clicked.connect(self._on_gen_clear)
        self.gen_run.clicked.connect(self._on_generate)
        self.gen_stop.clicked.connect(self.flow.stop)
        self.gen_rerun.clicked.connect(self._on_gen_rerun)
        return w

    def _build_execution(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.exec_board = _muted(model.board_text(model.section("test-execution")))
        v.addWidget(self.exec_board)
        head = QLabel("Ade QA agents")
        head.setStyleSheet("font-weight:600;")
        v.addWidget(head)
        self.exec_activity = _muted()
        v.addWidget(self.exec_activity)
        row = QHBoxLayout()
        row.addWidget(QLabel("Task type"))
        self.exec_type = QComboBox()
        for t in self.types:
            self.exec_type.addItem(t)
        row.addWidget(self.exec_type)
        row.addStretch(1)
        v.addLayout(row)
        self.exec_text = QPlainTextEdit()
        self.exec_text.setPlaceholderText("What should QA do? e.g. Run the web unit tests and "
                                          "report failures…")
        self.exec_text.setFixedHeight(90)
        v.addWidget(self.exec_text)
        row = QHBoxLayout()
        self.exec_run = QPushButton("Run QA task")
        row.addWidget(self.exec_run)
        row.addStretch(1)
        v.addLayout(row)
        self.exec_result = QPlainTextEdit()
        self.exec_result.setReadOnly(True)
        v.addWidget(self.exec_result, 1)
        self.exec_run.clicked.connect(self._on_dispatch)
        return w

    # -- loading ----------------------------------------------------------------

    def stop_clients(self) -> None:
        self.flow.close()
        for c in (self.qa, self.pm, self.files):
            c.stop()

    def unsaved(self) -> list[str]:
        lost = []
        if self._dispatching:
            lost.append("a QA task still running (it keeps running in Ade OS)")
        for view in (self.artifact, self.req_artifact):
            if view.editor.is_dirty():
                lost.append(f"unsaved changes to {view.editor.path}")
            if view.editor.is_busy():
                lost.append(f"a save of {view.editor.path} still in flight")
        if self.flow.busy:
            lost.append("a QA package still being generated")
        return lost

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._clock() - self._last_refresh > STALE_S:
            self.refresh()
        elif self._stale:
            self._stale = False
            self._render_section()

    def _on_filling(self) -> None:
        for view in (self.artifact, self.req_artifact):
            view.sync_block()

    def refresh(self) -> None:
        self._last_refresh = self._clock()
        self._pending[self.qa.projects()] = ("projects",)
        self._pending[self.qa.agents()] = ("agents",)
        self._pending[self.qa.activity()] = ("activity",)
        self._render_section()

    def _on_done(self, rid: str, result) -> None:
        job = self._pending.pop(rid, None)
        if job is not None:
            getattr(self, f"_got_{job[0]}")(result, *job[1:])

    def _got_projects(self, result) -> None:
        if _ok(result):
            self.projects = [p for p in result.get("projects") or [] if isinstance(p, dict)]
        self._render_header()

    def _got_agents(self, result) -> None:
        types = model.qa_types(result)
        if types != self.types:
            self.types = types
            keep = self.exec_type.currentText()
            self.exec_type.clear()
            for t in types:
                self.exec_type.addItem(t)
            if keep in types:
                self.exec_type.setCurrentText(keep)

    def _got_activity(self, result) -> None:
        if not _ok(result):
            text = f"Activity unavailable: {error_cause(result)}"
        elif result.get("active") or int(result.get("count") or 0) > 0:
            topics = ", ".join(result.get("topics") or []) or "—"
            text = f"Ade is working: {result.get('count', 0)} active · topics: {topics}"
        else:
            text = "Ade is idle."
        self.activity_label.setText(text)
        self.exec_activity.setText(text)

    # -- header and sections ----------------------------------------------------------

    def _slug(self) -> str:
        return pm_model.slug(self.active.name) if self.active.name else ""

    def _render_header(self) -> None:
        name = self.active.name
        match = next((p for p in self.projects if p.get("name") == name), None)
        if not name:
            self.project_label.setText("— no project selected (pick one in PM)")
        elif match:
            self.project_label.setText(f"{name} — {pm_model.format_status(match.get('status'))}")
        else:
            self.project_label.setText(name)
        running = self.flow.intake if self.flow.busy else None
        if running and running.get("slug") != self._slug():
            self.gen_target.setText(
                f"Still writing into {running['qa_dir']}/ for “{running['project']['name']}”"
                " — the run started before you switched projects.")
        else:
            self.gen_target.setText(
                f"Writes the 13 QA documents into qa/{self._slug()}/ for “{name}”, one at a "
                "time, then checks them on disk." if name else NO_PROJECT)
        self.gen_run.setEnabled(bool(name) and not self.flow.busy)

    def _current_id(self) -> str:
        item = self.rail.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else "dashboard"

    def _on_section(self, row: int) -> None:
        self._render_section()

    def _on_active_changed(self, name: str) -> None:
        # A run for the previous project keeps writing where it started;
        # its Re-run belongs to that project, not this one (review).
        if not self.flow.busy:
            self.gen_rerun.hide()
            self.gen_line.setText("QA package: —")
            self.gen_status.setText("")
        self._render_header()
        if not self.isVisible():
            # Re-rendered when shown: a hidden panel must not raise a
            # discard dialog because PM picked another project.
            self._stale = True
            return
        self._render_section()

    def _render_section(self) -> None:
        sid = self._current_id()
        sec = model.section(sid)
        name, slug = self.active.name, self._slug()
        if sid == "dashboard":
            self.stack.setCurrentWidget(self.dashboard)
            self._list_package()
        elif sid == "requirements":
            self.stack.setCurrentWidget(self.requirements)
            self.req_artifact.show_section(sec, model.artifact_path(slug, sid), name)
        elif sid == "test-execution":
            self.stack.setCurrentWidget(self.execution)
        elif sid in model.SECTION_FILE:
            self.stack.setCurrentWidget(self.artifact)
            self.artifact.show_section(sec, model.artifact_path(slug, sid), name)
        else:
            self.board_label.setText(model.board_text(sec))
            self.stack.setCurrentWidget(self.board_only)
        self._render_header()

    # -- dashboard ----------------------------------------------------------------------

    def _list_package(self) -> None:
        slug = self._slug()
        if not slug:
            self.package_note.setText(NO_PROJECT)
            self.package_table.setRowCount(0)
            return
        self.package_note.setText(f"Checking qa/{slug}/ on disk…")
        self._pending[self.files.list_dir(f"qa/{slug}")] = ("package", slug)

    def _got_package(self, result, slug: str) -> None:
        if slug != self._slug():
            return
        missing_dir = is_missing(result)
        if not _ok(result) and not missing_dir:
            self.package_note.setText(f"Could not read qa/{slug}/: {error_cause(result)}")
            self.package_table.setRowCount(0)      # not the last project's rows
            return
        names = {e.get("name") for e in (result.get("entries") or []) if e.get("kind") == "file"} \
            if _ok(result) else set()
        rows = model.package_rows(names)
        present = sum(1 for r in rows if r[2])
        self.package_note.setText(
            f"qa/{slug}/: {present} of {len(rows)} documents on disk."
            + ("" if present else " Generate the package from Requirements."))
        self.package_table.setRowCount(len(rows))
        for i, (label, file, ok) in enumerate(rows):
            for c, value in enumerate((label, file, "present" if ok else "missing")):
                self.package_table.setItem(i, c, QTableWidgetItem(value))

    def _on_go_generate(self) -> None:
        self.rail.setCurrentRow(1)

    def _on_go_pm(self) -> None:
        self.section_requested.emit("PM")

    # -- requirements / generation -------------------------------------------------------

    def _on_gen_choose(self) -> None:
        if self._pick is not None:
            path = self._pick()
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Requirements document", "", TEXT_FILTER)
        if path:
            self.gen_file = path
            self.gen_file_label.setText(path)
            self.gen_paste.setEnabled(False)

    def _on_gen_clear(self) -> None:
        self.gen_file = None
        self.gen_file_label.setText("No file chosen")
        self.gen_paste.setEnabled(True)

    def _on_generate(self) -> None:
        self.gen_error.setText("")
        self.gen_rerun.hide()
        if not self.active.name:
            self.gen_error.setText(NO_PROJECT)
            return
        self.flow.start_qa(self.active.name, self.gen_file, self.gen_paste.toPlainText(),
                           self.gen_notes.toPlainText())

    def _on_gen_rerun(self) -> None:
        intake = self.flow.intake or {}
        if intake.get("slug") != self._slug():
            self.gen_rerun.hide()
            self.gen_error.setText("That run was for another project; Generate writes this one's.")
            return
        self.gen_rerun.hide()
        self.flow.rerun("qa")

    def _on_package(self, pkg: str, kind: str, note: str) -> None:
        if pkg != "qa":
            return
        self.gen_line.setText("QA package: running…" if kind == "running" else f"QA package: {note}")
        self.gen_rerun.setVisible(kind in ("error", "stale"))

    def _on_progress(self, pkg: str, done: int, total: int, current: str) -> None:
        if pkg == "qa":
            self.gen_line.setText(f"QA package: authoring {current}… ({done}/{total})")

    def _on_gen_busy(self, busy: bool) -> None:
        self.gen_stop.setVisible(busy)
        for w in (self.gen_choose, self.gen_clear, self.gen_notes):
            w.setEnabled(not busy)
        self.gen_paste.setEnabled(not busy and self.gen_file is None)
        self.gen_run.setEnabled(not busy and bool(self.active.name))
        if not busy:
            # The disk, not the flow's summary: whatever is open is read again.
            for view in (self.artifact, self.req_artifact):
                view.reread()
            self._render_section()

    # -- execution ----------------------------------------------------------------------

    def _on_dispatch(self) -> None:
        text = self.exec_text.toPlainText().strip()
        if not text:
            return
        task_type = self.exec_type.currentText()
        self.exec_run.setEnabled(False)
        self.exec_run.setText("Running…")
        self._dispatching = True
        self.exec_result.setPlainText(f"Dispatched {task_type} to Ade's QA agents — a task "
                                      "takes minutes; an approval it needs appears in the "
                                      "Ade panel.")
        self._pending[self.qa.dispatch(task_type, text, self.active.name)] = \
            ("dispatch", task_type)

    def _got_dispatch(self, result, task_type: str) -> None:
        self._dispatching = False
        self.exec_run.setEnabled(True)
        self.exec_run.setText("Run QA task")
        if isinstance(result, dict) and "task_id" in result and "status" not in result:
            text, _ = task_report(result)               # the task RAN, well or not
            self.exec_result.setPlainText(text or "(no output)")
        elif isinstance(result, dict) and "Timeout" in str(result.get("error", "")):
            self.exec_result.setPlainText(
                f"No answer in 20 minutes. The {task_type} task may still be running in "
                "Ade OS — check Ade's activity before sending it again.")
        else:
            cause = error_cause(result)
            types = task_types_from(result)
            self.exec_result.setPlainText(f"{task_type} failed: {cause}"
                                          + ("\n\nTypes: " + ", ".join(types) if types else ""))
        self._pending[self.qa.activity()] = ("activity",)
