"""The QA desk: the web's catalogue, the ACTIVE project's package (read
there, generated there -- never at the uploaded file's slug), dispatch of
the qa primary's live task types, and only measured numbers."""

import gc
import json
import pathlib
import weakref

import pytest
from PySide6.QtCore import QObject, Signal

from ade_desktop.sections.pm import model as pm_model
from ade_desktop.sections.qa import model
from ade_desktop.sections.qa.client import QaClient
from ade_desktop.sections.qa.panel import NO_PROJECT, QaPanel
from ade_desktop.workspace.active import ActiveProject

WEB = pathlib.Path(r"C:\Users\ray_g\ade-ai\adeos\web\src\pages\QA\qaNav.ts")

# ------------------------------------------------------------------ model


def test_the_catalogue_is_the_web_s_sixteen_in_order():
    assert [s["id"] for s in model.SECTIONS] == [
        "dashboard", "requirements", "test-plans", "test-suites", "test-cases",
        "test-execution", "defects", "traceability", "reports", "test-data", "automation",
        "api-testing", "performance", "security", "analytics", "settings"]
    if WEB.exists():
        text = WEB.read_text(encoding="utf-8")
        for sec in model.SECTIONS:                  # every label and purpose, verbatim
            assert f"label: '{sec['label']}'" in text, sec["id"]
            first = sec["purpose"].split("'")[0][:40]
            assert first in text, sec["id"]


def test_the_thirteen_files_are_the_qa_package():
    assert len(model.SECTION_FILE) == 13
    assert set(model.SECTION_FILE.values()) == set(pm_model.QA_DOCS)
    assert model.artifact_path("fuel", "test-plans") == "qa/fuel/test_plan.md"
    assert model.artifact_path("", "test-plans") is None
    assert model.artifact_path("fuel", "dashboard") is None


def test_qa_task_types_come_from_the_qa_agent_or_fall_back():
    agents = {"agents": [{"name": "coding", "task_types": ["coding"]},
                         {"name": "qa", "task_types": ["test", "verify", "new_type"]}]}
    assert model.qa_types(agents) == ["test", "verify", "new_type"]
    assert model.qa_types({"error": "down"}) == list(model.FALLBACK_TYPES)
    assert model.qa_types({"agents": []}) == list(model.FALLBACK_TYPES)


def test_dispatch_is_topic_qa(qapp, pump):
    calls = []
    c = QaClient("http://ade", request=lambda m, u, b, t: calls.append((m, u, b, t)) or {})
    c.dispatch("verify", "report only")
    assert pump(lambda: bool(calls))
    assert calls == [("POST", "http://ade/v1/tasks",
                      {"task_type": "verify", "description": "report only", "topic": "qa"},
                      1200.0)]

# ------------------------------------------------------------------ panel


class Fake(QObject):
    done = Signal(str, object)

    def __init__(self, prefix):
        super().__init__()
        self.prefix, self.calls = prefix, []

    def _rid(self, *call):
        self.calls.append(call)
        return f"{self.prefix}{len(self.calls)}"

    def stop(self): pass

    def answer_last(self, verb, result):
        idx = max(i for i, c in enumerate(self.calls) if c[0] == verb)
        self.done.emit(f"{self.prefix}{idx + 1}", result)


class FakeQa(Fake):
    def projects(self): return self._rid("projects")
    def agents(self): return self._rid("agents")
    def activity(self): return self._rid("activity")
    def dispatch(self, t, d): return self._rid("dispatch", t, d)


class FakePm(Fake):
    def author(self, pkg, slug, doc, source, name, notes):
        return self._rid("author", pkg, slug, doc, name)
    def intake(self, n, s): return self._rid("intake", n, s)


class FakeFiles(Fake):
    def list_dir(self, path): return self._rid("list", path)
    def read(self, path): return self._rid("read", path)
    def write(self, path, content): return self._rid("write", path, content)
    def upload(self, path, relpath=""): return self._rid("upload", path)


@pytest.fixture
def rig(qapp, tmp_path):
    qa, pm, files = FakeQa("qa"), FakePm("pm"), FakeFiles("fs")
    active = ActiveProject(tmp_path / "w.json")
    active.set("Fuel Management")
    panel = QaPanel(qa, pm, files, active, confirm=lambda q: True,
                    pick_file=lambda: "C:/docs/requirements-paste.md")
    panel.refresh()
    qa.answer_last("projects", {"projects": [{"id": 9, "name": "Fuel Management",
                                              "status": "ongoing"}]})
    return panel, qa, pm, files, active


def go(panel, section_id):
    ids = [s["id"] for s in model.SECTIONS]
    panel.rail.setCurrentRow(ids.index(section_id))


def test_the_header_names_the_active_project_and_its_status(rig):
    panel, *_ = rig
    assert panel.project_label.text() == "Fuel Management — ongoing"


def test_an_artifact_section_reads_the_active_project_s_file(rig):
    panel, qa, pm, files, _ = rig
    go(panel, "test-plans")
    assert files.calls[-1] == ("read", "qa/fuel-management/test_plan.md")
    files.answer_last("read", {"text": "# Test plan\n", "cached": False})
    assert not panel.artifact.editor.isHidden() and panel.artifact.board.isHidden()
    assert panel.artifact.editor.text.toPlainText() == "# Test plan\n"


def test_a_missing_file_shows_the_board_and_says_so(rig):
    panel, qa, pm, files, _ = rig
    go(panel, "security")
    files.answer_last("read", {"error": {"code": "not_found", "message": "x"}, "status": 404})
    assert panel.artifact.editor.isHidden() and not panel.artifact.board.isHidden()
    assert "No security.md for “Fuel Management” yet" in panel.artifact.missing.text()
    assert "OWASP" in panel.artifact.board.text() or "Vulnerab" in panel.artifact.board.text()


def test_no_active_project_reads_nothing_and_says_where_to_pick_one(qapp, tmp_path):
    qa, pm, files = FakeQa("qa"), FakePm("pm"), FakeFiles("fs")
    panel = QaPanel(qa, pm, files, ActiveProject(), confirm=lambda q: True)
    go(panel, "test-cases")
    assert not any(c[0] == "read" for c in files.calls)
    assert panel.artifact.missing.text() == NO_PROJECT
    go(panel, "dashboard")
    assert panel.package_note.text() == NO_PROJECT


def test_changing_project_rereads_the_section(rig):
    panel, qa, pm, files, active = rig
    go(panel, "reports")
    files.answer_last("read", {"text": "fuel", "cached": False})
    active.set("test")
    assert files.calls[-1] == ("read", "qa/test/reports.md")


def test_the_dashboard_counts_the_package_on_disk(rig):
    panel, qa, pm, files, _ = rig
    go(panel, "dashboard")
    assert files.calls[-1] == ("list", "qa/fuel-management")
    files.answer_last("list", {"entries": [
        {"name": "test_plan.md", "kind": "file"}, {"name": "README.md", "kind": "file"},
        {"name": "security.md", "kind": "file"}, {"name": "x", "kind": "dir"}]})
    assert panel.package_note.text().startswith("qa/fuel-management/: 2 of 13 documents on disk")
    states = {panel.package_table.item(r, 1).text(): panel.package_table.item(r, 2).text()
              for r in range(panel.package_table.rowCount())}
    assert states["test_plan.md"] == "present" and states["automation.md"] == "missing"


def test_a_package_folder_that_does_not_exist_is_zero_not_an_error(rig):
    panel, qa, pm, files, _ = rig
    go(panel, "dashboard")
    files.answer_last("list", {"error": {"code": "not_found", "message": "x"}, "status": 404})
    assert "0 of 13" in panel.package_note.text()


def test_generation_writes_into_the_active_project_never_the_file_s_slug(rig):
    panel, qa, pm, files, _ = rig
    go(panel, "requirements")
    panel.gen_choose.click()                        # "C:/docs/requirements-paste.md"
    panel.gen_run.click()
    assert files.calls[-1] == ("upload", "C:/docs/requirements-paste.md")
    files.answer_last("upload", {"name": "uploads/requirements-paste.md"})
    first = pm.calls[-1]
    assert first == ("author", "qa", "fuel-management", "requirements.md", "Fuel Management")
    for _ in range(12):
        pm.answer_last("author", {"ok": True})
    pm.answer_last("author", {"ok": True})
    authored = [c for c in pm.calls if c[0] == "author"]
    assert len(authored) == 13 and {c[2] for c in authored} == {"fuel-management"}
    assert not any(c[0] == "intake" for c in pm.calls)      # no new project
    assert files.calls[-1] == ("list", "qa/fuel-management")
    files.answer_last("list", {"entries": [{"name": f, "kind": "file"}
                                           for f in pm_model.QA_DOCS]})
    assert panel.gen_line.text().startswith("QA package: 13/13 documents authored")


def test_execution_dispatches_the_chosen_type_and_shows_the_reply(rig):
    panel, qa, pm, files, _ = rig
    qa.answer_last("agents", {"agents": [{"name": "qa", "task_types": ["verify", "test"]}]})
    assert [panel.exec_type.itemText(i) for i in range(panel.exec_type.count())] == \
        ["verify", "test"]
    assert panel.exec_type.currentText() == "test"          # the choice survives a reload
    go(panel, "test-execution")
    panel.exec_type.setCurrentText("verify")
    panel.exec_text.setPlainText("Report the failing web tests; change nothing.")
    panel.exec_run.click()
    assert qa.calls[-1] == ("dispatch", "verify", "Report the failing web tests; change nothing.")
    assert not panel.exec_run.isEnabled()
    qa.answer_last("dispatch", {"result": "2 failing: a, b"})
    assert panel.exec_result.toPlainText() == "2 failing: a, b" and panel.exec_run.isEnabled()


def test_a_failed_dispatch_says_why(rig):
    panel, qa, *_ = rig
    go(panel, "test-execution")
    panel.exec_text.setPlainText("x")
    panel.exec_run.click()
    qa.answer_last("dispatch", {"error": {"code": "unknown_task_type", "message": "no"},
                                "status": 400})
    assert "failed" in panel.exec_result.toPlainText()
    assert "unknown_task_type" in panel.exec_result.toPlainText()


def test_settings_is_the_board(rig):
    panel, qa, pm, files, _ = rig
    before = len(files.calls)
    go(panel, "settings")
    assert panel.stack.currentWidget() is panel.board_only and len(files.calls) == before


def test_a_dropped_panel_is_freed_at_once(qapp):
    qa, pm, files = FakeQa("qa"), FakePm("pm"), FakeFiles("fs")
    panel = QaPanel(qa, pm, files, ActiveProject(), confirm=lambda q: True)
    ref = weakref.ref(panel)
    gc.disable()
    try:
        del panel
        assert ref() is None
    finally:
        gc.enable()


def test_no_active_project_generates_nothing(qapp):
    qa, pm, files = FakeQa("qa"), FakePm("pm"), FakeFiles("fs")
    panel = QaPanel(qa, pm, files, ActiveProject(), confirm=lambda q: True,
                    pick_file=lambda: "C:/docs/r.md")
    go(panel, "requirements")
    assert not panel.gen_run.isEnabled()
    panel.gen_choose.click()
    panel._on_generate()                      # even if something calls it anyway
    assert panel.gen_error.text() == NO_PROJECT
    assert not any(c[0] == "upload" for c in files.calls)


def test_a_document_closed_in_the_editor_opens_again_when_its_section_is_shown(rig):
    panel, qa, pm, files, _ = rig
    go(panel, "test-cases")
    files.answer_last("read", {"text": "cases", "cached": False})
    panel.artifact.editor.close_button.click()
    reads = sum(1 for c in files.calls if c[0] == "read")
    panel.refresh()                           # re-renders the SAME section
    assert sum(1 for c in files.calls if c[0] == "read") == reads + 1
    assert files.calls[-1] == ("read", "qa/fuel-management/test_cases.md")
