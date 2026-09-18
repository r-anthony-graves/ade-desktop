"""PM's rules (each mirrors one home in Ade OS or the web), every route's
method/path/body, and the add-project flow driven step by step."""

import pytest
from PySide6.QtCore import QObject, Signal

from ade_desktop.sections.pm import model
from ade_desktop.sections.pm.add_flow import AddProjectFlow
from ade_desktop.sections.pm.client import PmClient

# ------------------------------------------------------------------ model


@pytest.mark.parametrize("name, slug", [
    ("Fuel Management", "fuel-management"), ("v2.0 rewrite", "v2"),
    ("  !!!  ", "requirements"), ("C:\\docs\\Safety Device.md", "safety-device"),
    ("x" * 60, "x" * 48)])
def test_slug_is_python_slug(name, slug):
    assert model.slug(name) == slug


def test_the_slug_matches_ade_os_itself():
    import importlib.util
    import pathlib
    import sys
    src = pathlib.Path(r"C:\Users\ray_g\ade-ai\adeos\records\pmi.py")
    if not src.exists():
        pytest.skip("Ade OS checkout not here")
    spec = importlib.util.spec_from_file_location("_pmi_probe", src)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_pmi_probe"] = mod
    spec.loader.exec_module(mod)
    for name in ("Fuel Management", "v2.0 rewrite", "  ", "Ünïcode Project", "a/b\\c.d"):
        assert model.slug(name) == mod.python_slug(name), name


def test_project_states_are_the_store_s():
    assert model.PROJECT_STATES == ("active", "complete", "not_started", "ongoing",
                                    "done", "archived")
    assert model.format_status("not_started") == "not started"


PROJECTS = [{"id": 1, "name": "A", "status": "active"},
            {"id": 2, "name": "B", "status": "archived"},
            {"id": 3, "name": "C", "status": "ongoing"}]


def test_archived_are_hidden_and_a_hidden_selection_falls_back():
    shown = model.visible(PROJECTS, False)
    assert [p["name"] for p in shown] == ["A", "C"]
    assert model.pick(shown, "B")["name"] == "A"
    assert model.pick(shown, "C")["name"] == "C"
    assert model.pick(shown, "nope")["name"] == "A"
    assert model.pick([], "A") is None
    assert model.empty_label([PROJECTS[1]], False) == "No visible projects — 1 archived"
    assert model.empty_label([], False) == "No projects."


def test_pm_docs_never_include_the_readme():
    arts = ["pm/x/README.md", "pm/x/charter.md", "pm/x/closure.md"]
    assert model.pm_docs(arts) == ["charter.md", "closure.md"]
    assert model.pm_paths(arts) == ["pm/x/charter.md", "pm/x/closure.md"]
    assert len(model.QA_DOCS) == 13


def test_zero_on_disk_is_stale_never_ok():
    assert model.grade_pm(0, 15)[0] == "stale"
    assert model.grade_pm(15, 15) == ("ok", "15/15 documents authored, 15/15 filled on disk")
    assert model.grade_qa(0, 13, "qa/x")[0] == "stale"
    assert model.is_filled("# T\nFill status: filled\n") and not model.is_filled(
        "Fill status: skeleton")


def test_findings_act_first_and_the_summary():
    rows = [{"severity": "check"}, {"severity": "act"}]
    assert [r["severity"] for r in model.sort_findings(rows)] == ["act", "check"]
    assert model.summarise_findings({"findings": 0}).startswith("Healthy")
    assert model.summarise_findings({"findings": 2, "needs_action": 1}) == \
        "2 findings, 1 needs action"


def test_names_from_a_file_or_a_heading():
    assert model.name_from_file("Safety_Device-Spec.md") == "safety device spec"
    assert model.name_from_paste("intro\n## Fleet Tracker\nbody") == "Fleet Tracker"
    assert model.name_from_paste("no heading") == ""

# ----------------------------------------------------------------- client


def _recording():
    calls = []

    def get(url, timeout):
        calls.append(("GET", url, None))
        return {"ok": True}

    def request(method, url, body, timeout):
        calls.append((method, url, body))
        return {"ok": True}

    return calls, get, request


def test_every_route_is_the_right_method_path_and_body(qapp, pump):
    calls, get, request = _recording()
    c = PmClient("http://ade", get=get, request=request)
    c.projects()
    c.set_status(9, "ongoing")
    c.intake("Fuel", "uploads/f.md")
    c.author("pm", "fuel", "charter.md", "uploads/f.md", "Fuel", "n")
    c.backlog()
    c.add_backlog("t", "d", "Fuel")
    c.backlog_action(4, "promote")
    c.reopen(4)
    c.risks()
    c.add_risk("r", "Fuel", "high", "low", "watch")
    c.risk_response(2, "avoid")
    c.findings()
    assert pump(lambda: len(calls) == 12)
    assert sorted(calls, key=str) == sorted([
        ("GET", "http://ade/v1/pm/projects", None),
        ("POST", "http://ade/v1/pm/projects/9/status", {"status": "ongoing"}),
        ("POST", "http://ade/v1/pm/intake", {"name": "Fuel", "source": "uploads/f.md"}),
        ("POST", "http://ade/v1/pm/author", {"package": "pm", "slug": "fuel",
                                             "doc": "charter.md", "source": "uploads/f.md",
                                             "name": "Fuel", "notes": "n"}),
        ("GET", "http://ade/v1/pm/backlog", None),
        ("POST", "http://ade/v1/pm/backlog", {"title": "t", "detail": "d", "project": "Fuel"}),
        ("POST", "http://ade/v1/pm/backlog/4/promote", None),
        ("POST", "http://ade/v1/pm/backlog/4/reopen", None),
        ("GET", "http://ade/v1/pm/risks", None),
        ("POST", "http://ade/v1/pm/risks", {"title": "r", "project": "Fuel",
                                            "probability": "high", "impact": "low",
                                            "response": "watch"}),
        ("POST", "http://ade/v1/pm/risks/2/response", {"response": "avoid"}),
        ("GET", "http://ade/v1/pm/findings", None)], key=str)

# ------------------------------------------------------------------- flow


class FakePm(QObject):
    done = Signal(str, object)

    def __init__(self):
        super().__init__()
        self.calls = []

    def _rid(self, *call):
        self.calls.append(call)
        return f"pm{len(self.calls)}"

    def intake(self, name, source): return self._rid("intake", name, source)
    def author(self, pkg, slug, doc, source, name, notes):
        return self._rid("author", pkg, doc)


class FakeFiles(QObject):
    done = Signal(str, object)

    def __init__(self):
        super().__init__()
        self.calls = []

    def _rid(self, *call):
        self.calls.append(call)
        return f"fs{len(self.calls)}"

    def upload(self, path, relpath=""): return self._rid("upload", path)
    def read(self, path): return self._rid("read", path)
    def list_dir(self, path): return self._rid("list", path)


ARTS = ["pm/fuel/README.md", "pm/fuel/charter.md", "pm/fuel/risks.md"]
INTAKE = {"project": {"id": 11, "name": "Fuel", "summary": "", "status": "active"},
          "slug": "fuel", "dir": "pm/fuel", "artifacts": ARTS, "qa_dir": "qa/fuel"}


class Driver:
    """Answers each call the flow makes, as Ade OS would."""

    def __init__(self, tmp_path):
        self.pm, self.files = FakePm(), FakeFiles()
        self.flow = AddProjectFlow(self.pm, self.files, tmpdir=str(tmp_path))
        self.events = []
        ev = self.events
        self.flow.package.connect(lambda p, k, n: ev.append(("package", p, k, n)))
        self.flow.failed.connect(lambda m: ev.append(("failed", m)))
        self.flow.created.connect(lambda n: ev.append(("created", n)))
        self.flow.status.connect(lambda s: ev.append(("status", s)))

    def pm_answer(self, result):
        self.pm.done.emit(f"pm{len(self.pm.calls)}", result)

    def fs_answer(self, result, n=None):
        self.files.done.emit(f"fs{n or len(self.files.calls)}", result)

    def through_intake(self):
        assert self.flow.start("Fuel", "C:/x/fuel.md", "", "notes")
        self.fs_answer({"name": "uploads/fuel.md"})
        self.pm_answer(INTAKE)

    def author_all(self, fail=()):
        while self.pm.calls and self.pm.calls[-1][0] == "author":
            call = self.pm.calls[-1]
            before = len(self.pm.calls)
            self.pm_answer({"error": "boom"} if call[2] in fail else {"doc": call[2]})
            if len(self.pm.calls) == before:
                break

    def kinds(self):
        return [e for e in self.events if e[0] == "package" and e[2] != "running"]


def test_the_whole_flow_in_order(qapp, tmp_path):
    d = Driver(tmp_path)
    d.through_intake()
    assert d.pm.calls[0] == ("intake", "Fuel", "uploads/fuel.md")
    assert ("created", "Fuel") in d.events
    d.author_all()
    assert [c[2] for c in d.pm.calls if c[0] == "author"] == ["charter.md", "risks.md"]
    reads = [c for c in d.files.calls if c[0] == "read"]
    assert reads == [("read", "pm/fuel/charter.md"), ("read", "pm/fuel/risks.md")]
    n = len(d.files.calls)
    d.fs_answer({"text": "Fill status: filled", "cached": False}, n=n - 1)
    d.fs_answer({"text": "Fill status: skeleton", "cached": False}, n=n)
    assert d.kinds()[0] == ("package", "pm", "ok", "2/2 documents authored, 1/2 filled on disk")
    d.author_all()
    qa = [c[2] for c in d.pm.calls if c[0] == "author" and c[1] == "qa"]
    assert qa == list(model.QA_DOCS)
    assert d.files.calls[-1] == ("list", "qa/fuel")
    d.fs_answer({"entries": [{"kind": "file"}] * 13})
    assert d.kinds()[1][:3] == ("package", "qa", "ok")
    assert not d.flow.busy


def test_a_failing_document_does_not_stop_the_package(qapp, tmp_path):
    d = Driver(tmp_path)
    d.through_intake()
    d.author_all(fail={"charter.md"})
    assert [c[2] for c in d.pm.calls if c[0] == "author"][:2] == ["charter.md", "risks.md"]
    assert d.kinds()[0] == ("package", "pm", "error", "1/2 authored; failed: charter.md")
    assert [c[1] for c in d.pm.calls if c[0] == "author"][2] == "qa"   # QA still runs


def test_nothing_on_disk_is_stale_even_when_every_call_said_ok(qapp, tmp_path):
    d = Driver(tmp_path)
    d.through_intake()
    d.author_all()
    n = len(d.files.calls)
    d.fs_answer({"text": "Fill status: skeleton", "cached": False}, n=n - 1)
    d.fs_answer({"text": "Fill status: filled", "cached": True}, n=n)   # the index copy
    assert d.kinds()[0][2] == "stale"


def test_stop_ends_after_the_document_in_flight(qapp, tmp_path):
    d = Driver(tmp_path)
    d.through_intake()
    d.flow.stop()
    d.pm_answer({"doc": "charter.md"})
    assert [c[2] for c in d.pm.calls if c[0] == "author"] == ["charter.md"]
    assert d.kinds()[0][:3] == ("package", "pm", "error")
    assert "not authored: risks.md" in d.kinds()[0][3]
    assert not d.flow.busy


def test_rerun_repeats_one_package(qapp, tmp_path):
    d = Driver(tmp_path)
    d.through_intake()
    d.flow.stop()
    d.pm_answer({"doc": "charter.md"})
    assert d.flow.rerun("pm")
    d.author_all()
    n = len(d.files.calls)
    d.fs_answer({"text": "Fill status: filled"}, n=n - 1)
    d.fs_answer({"text": "Fill status: filled"}, n=n)
    assert d.kinds()[-1] == ("package", "pm", "ok", "2/2 documents authored, 2/2 filled on disk")
    assert not any(c[1] == "qa" for c in d.pm.calls if c[0] == "author")
    assert not d.flow.busy


def test_intake_refused_stops_with_the_server_s_words(qapp, tmp_path):
    d = Driver(tmp_path)
    d.flow.start("Fuel", "C:/x/fuel.md", "", "")
    d.fs_answer({"name": "uploads/fuel.md"})
    d.pm_answer({"error": {"code": "exists", "message": "pm/fuel/ already exists"},
                 "status": 409})
    assert d.events[-1][0] == "failed" and "already exists" in d.events[-1][1]
    assert not d.flow.busy and not any(c[0] == "author" for c in d.pm.calls)


def test_pasted_text_is_uploaded_from_a_temp_file_then_removed(qapp, tmp_path):
    d = Driver(tmp_path)
    assert d.flow.start("Fleet Tracker", None, "# Fleet Tracker\nreqs", "")
    path = d.files.calls[0][1]
    assert path.endswith("fleet-tracker-requirements.md")
    assert open(path, encoding="utf-8").read() == "# Fleet Tracker\nreqs"
    d.fs_answer({"error": "ConnectError: refused"})
    import os
    assert not os.path.exists(path) and d.events[-1][0] == "failed"


def test_it_refuses_without_a_name_or_a_source(qapp, tmp_path):
    d = Driver(tmp_path)
    assert d.flow.start("", "C:/x.md", "", "") is False
    assert d.flow.start("X", None, "   ", "") is False
    assert [e[1] for e in d.events if e[0] == "failed"] == [
        "Project name is required.", "Choose a file or paste requirements text."]
