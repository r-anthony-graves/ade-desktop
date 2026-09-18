"""The PM panel against recording fakes: what it shows is Ade OS's answer,
every write is followed by a re-read, the selection is the app's one
active project, and a dropped panel is freed at once."""

import gc
import weakref

import pytest
from PySide6.QtCore import QObject, Signal

from ade_desktop.sections.pm.panel import PmPanel
from ade_desktop.workspace.active import ActiveProject

PROJECTS = {"projects": [
    {"id": 9, "name": "Fuel Management", "summary": "fuel dashboard", "status": "ongoing"},
    {"id": 10, "name": "test", "summary": "", "status": "complete"},
    {"id": 11, "name": "Old", "summary": "", "status": "archived"}]}
BACKLOG = {"statuses": ["complete", "open"], "backlog": [
    {"id": 1, "title": "Wire the sensor", "detail": "d", "project": "Fuel Management",
     "status": "open", "resolution": ""},
    {"id": 2, "title": "Old thing", "detail": "", "project": "Fuel Management",
     "status": "complete", "resolution": "completed"},
    {"id": 3, "title": "Elsewhere", "detail": "", "project": "test", "status": "open",
     "resolution": ""}]}
RISKS = {"risks": [
    {"id": 5, "title": "Sensor drift", "project": "Fuel Management", "probability": "low",
     "impact": "low", "severity": "low", "response": "", "owner": "", "status": "open"},
    {"id": 6, "title": "Vendor late", "project": "Fuel Management", "probability": "high",
     "impact": "high", "severity": "high", "response": "", "owner": "", "status": "open"}]}
FINDINGS = {"findings": [
    {"domain": "planning", "severity": "check", "what": "empty backlog", "why": "w",
     "evidence": "e", "principle": "value", "subject": ""},
    {"domain": "uncertainty", "severity": "act", "what": "no risks", "why": "w",
     "evidence": "e", "principle": "risk", "subject": ""}],
    "summary": {"findings": 2, "needs_action": 1},
    "coverage": {"covered": ["risk", "scope"], "uncovered": {"cost": "no per-task cost"}}}


class Fake(QObject):
    done = Signal(str, object)

    def __init__(self, prefix):
        super().__init__()
        self.prefix = prefix
        self.calls = []

    def _rid(self, *call):
        self.calls.append(call)
        return f"{self.prefix}{len(self.calls)}"

    def stop(self): pass

    def answer(self, result, verb=None):
        """Answer the latest call (or the latest call with this verb)."""
        idx = max(i for i, c in enumerate(self.calls) if verb is None or c[0] == verb)
        self.done.emit(f"{self.prefix}{idx + 1}", result)


class FakePm(Fake):
    def projects(self): return self._rid("projects")
    def backlog(self): return self._rid("backlog")
    def risks(self): return self._rid("risks")
    def findings(self): return self._rid("findings")
    def set_status(self, pid, status): return self._rid("set_status", pid, status)
    def add_backlog(self, t, d, p): return self._rid("add_backlog", t, d, p)
    def backlog_action(self, i, a): return self._rid("backlog_action", i, a)
    def reopen(self, i): return self._rid("reopen", i)
    def add_risk(self, t, p, pr, im, r): return self._rid("add_risk", t, p, pr, im, r)
    def risk_response(self, i, r): return self._rid("risk_response", i, r)
    def intake(self, n, s): return self._rid("intake", n, s)
    def author(self, *a): return self._rid("author", *a)


class FakeFiles(Fake):
    def list_dir(self, path): return self._rid("list", path)
    def read(self, path): return self._rid("read", path)
    def write(self, path, content): return self._rid("write", path, content)
    def upload(self, path, relpath=""): return self._rid("upload", path)


def verbs(fake):
    return [c[0] for c in fake.calls]


@pytest.fixture
def rig(qapp, tmp_path):
    pm, files = FakePm("pm"), FakeFiles("fs")
    active = ActiveProject(tmp_path / "window.json")
    panel = PmPanel(pm, files, active, ask_text=lambda *a: "mitigate", confirm=lambda q: True)
    panel.refresh()
    pm.answer(PROJECTS, "projects")
    pm.answer(BACKLOG, "backlog")
    pm.answer(RISKS, "risks")
    return panel, pm, files, active


def rail_names(panel):
    return [panel.rail.item(i).text().split("    ")[0] for i in range(panel.rail.count())]


def test_archived_projects_are_hidden_until_asked(rig):
    panel, *_ = rig
    assert rail_names(panel) == ["Fuel Management", "test"]
    panel.show_archived.setChecked(True)
    assert rail_names(panel) == ["Fuel Management", "test", "Old"]


def test_the_first_project_becomes_the_app_s_active_one_and_is_remembered(rig, tmp_path):
    panel, pm, files, active = rig
    assert active.name == "Fuel Management" and panel.title.text() == "Fuel Management"
    assert ActiveProject(tmp_path / "window.json").name == "Fuel Management"
    assert ("list", "pm/fuel-management") in files.calls
    assert ("list", "qa/fuel-management") in files.calls
    assert panel.summary.text() == "fuel dashboard"


def test_picking_a_project_moves_the_active_one(rig):
    panel, pm, files, active = rig
    panel.rail.setCurrentRow(1)
    assert active.name == "test" and panel.title.text() == "test"


def test_a_hidden_active_project_moves_to_what_is_showing(qapp, tmp_path):
    pm, files = FakePm("pm"), FakeFiles("fs")
    active = ActiveProject(tmp_path / "w.json")
    active.set("Old")                                    # archived
    panel = PmPanel(pm, files, active, confirm=lambda q: True)
    panel.refresh()
    pm.answer(PROJECTS, "projects")
    assert active.name == "Fuel Management"


def test_a_status_change_posts_then_rereads(rig):
    panel, pm, *_ = rig
    idx = panel.status_combo.findData("done")
    panel.status_combo.setCurrentIndex(idx)
    panel.status_combo.activated.emit(idx)
    assert pm.calls[-1] == ("set_status", 9, "done")
    pm.answer({"id": 9, "status": "done"})
    assert pm.calls[-1] == ("projects",)


def test_a_failed_status_change_says_so_and_names_the_project(rig):
    panel, pm, *_ = rig
    idx = panel.status_combo.findData("done")
    panel.status_combo.setCurrentIndex(idx)
    panel.status_combo.activated.emit(idx)
    pm.answer({"error": {"code": "bad_status", "message": "nope"}, "status": 400})
    assert panel.status_error.text().startswith("Fuel Management:")
    assert panel.status_combo.currentData() == "ongoing"


def test_the_backlog_is_the_project_s_with_its_actions(rig):
    panel, pm, *_ = rig
    t = panel.backlog_table
    assert [t.item(r, 0).text() for r in range(t.rowCount())] == ["Wire the sensor", "Old thing"]
    t.selectRow(0)
    assert panel.backlog_buttons["promote"].isEnabled()
    assert not panel.backlog_buttons["reopen"].isEnabled()
    panel.backlog_buttons["promote"].click()
    assert pm.calls[-1] == ("backlog_action", 1, "promote")
    pm.answer({"id": 1, "status": "promoted"})
    assert pm.calls[-1] == ("backlog",)
    t.selectRow(1)
    assert panel.backlog_buttons["reopen"].isEnabled()
    panel.backlog_buttons["reopen"].click()
    assert pm.calls[-1] == ("reopen", 2)


def test_adding_a_backlog_item_is_for_the_selected_project(rig):
    panel, pm, *_ = rig
    panel.backlog_title.setText("New work")
    panel.backlog_detail.setText("why")
    panel.backlog_add.click()
    assert pm.calls[-1] == ("add_backlog", "New work", "why", "Fuel Management")
    pm.answer({"error": {"code": "bad", "message": "title too long"}, "status": 400})
    assert "title too long" in panel.backlog_note.text()
    assert panel.backlog_title.text() == "New work"              # kept on failure


def test_risks_sorted_by_severity_add_and_respond(rig):
    panel, pm, *_ = rig
    t = panel.risk_table
    assert [t.item(r, 0).text() for r in range(t.rowCount())] == ["Vendor late", "Sensor drift"]
    panel.risk_title.setText("Budget cut")
    panel.risk_prob.setCurrentText("high")
    panel.risk_add.click()
    assert pm.calls[-1] == ("add_risk", "Budget cut", "Fuel Management", "high", "medium", "")
    t.selectRow(0)
    panel.risk_set_response.click()
    assert pm.calls[-1] == ("risk_response", 6, "mitigate")


def test_health_runs_the_cycle_when_opened_act_first(rig):
    panel, pm, *_ = rig
    assert "findings" not in verbs(pm)
    panel.tabs.setCurrentIndex(3)
    assert verbs(pm).count("findings") == 1
    pm.answer(FINDINGS, "findings")
    t = panel.health_table
    assert [t.item(r, 0).text() for r in range(t.rowCount())] == ["act", "check"]
    assert panel.health_summary.text() == "2 findings, 1 needs action"
    assert "cost — no per-task cost" in panel.coverage.text()


def test_artifacts_listed_from_disk_open_in_the_editor(rig):
    panel, pm, files, _ = rig
    idx = [i for i, c in enumerate(files.calls) if c == ("list", "pm/fuel-management")][-1]
    files.done.emit(f"fs{idx + 1}", {"entries": [
        {"name": "charter.md", "path": "pm/fuel-management/charter.md", "kind": "file"},
        {"name": "sub", "path": "pm/fuel-management/sub", "kind": "dir"}]})
    assert panel.pm_list.count() == 1 and panel.pm_list.item(0).text() == "charter.md"
    panel.pm_list.itemClicked.emit(panel.pm_list.item(0))
    assert files.calls[-1] == ("read", "pm/fuel-management/charter.md")
    assert not panel.editor.isHidden()


def test_an_empty_package_says_so(rig):
    panel, pm, files, _ = rig
    idx = [i for i, c in enumerate(files.calls) if c == ("list", "qa/fuel-management")][-1]
    files.done.emit(f"fs{idx + 1}", {"error": {"code": "not_found", "message": "x"},
                                      "status": 404})
    assert panel.qa_list.item(0).text() == "No QA package yet."


def test_open_qa_desk_asks_the_window(rig):
    panel, *_ = rig
    asked = []
    panel.section_requested.connect(asked.append)
    panel.qa_desk.click()
    assert asked == ["QA"]


def test_a_failed_project_load_says_why(qapp, tmp_path):
    pm, files = FakePm("pm"), FakeFiles("fs")
    panel = PmPanel(pm, files, ActiveProject(), confirm=lambda q: True)
    panel.refresh()
    pm.answer({"error": "ConnectError: refused"}, "projects")
    assert "Could not load projects" in panel.rail_note.text()
    assert "unreachable" in panel.rail_note.text()


def test_a_dropped_panel_is_freed_at_once(qapp, tmp_path):
    pm, files = FakePm("pm"), FakeFiles("fs")
    panel = PmPanel(pm, files, ActiveProject(), confirm=lambda q: True)
    panel.refresh()
    pm.answer(PROJECTS, "projects")
    ref = weakref.ref(panel)
    gc.disable()
    try:
        del panel
        assert ref() is None
    finally:
        gc.enable()
