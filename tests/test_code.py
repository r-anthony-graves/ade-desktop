"""Piece 7: the Code section -- tree, tabs, Problems, terminal.

Fakes answer in the shapes Ade OS was measured answering on 2026-09-18:
/v1/fs {root, path, entries:[{name, path, kind}]} and its status-less
not_found; /v1/lsp/diagnostics {ok, data:{counts, items}} and its
lsp_no_server envelope; /v1/terminal/run's NDJSON frames.
"""

import gc
import json
import sys
import threading
import time
import weakref

import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtTest import QTest

from ade_desktop.sections.code import client as client_mod
from ade_desktop.sections.code.client import SESSION, CodeClient
from ade_desktop.sections.code.panel import EMPTY_NOTE, CodePanel
from ade_desktop.sections.code.terminal import (BUSY_NOTE, MAX_LINES, STOPPED_NOTE,
                                                TerminalPane)
from ade_desktop.sections.code.tree import KIND, LOADING, PATH, FileTree


class _Fake(QObject):
    done = Signal(str, object)
    line = Signal(str, str)

    def __init__(self, prefix):
        super().__init__()
        self.calls = []
        self._prefix = prefix

    def _rid(self, *call):
        self.calls.append(call)
        return f"{self._prefix}{len(self.calls)}"

    def rid(self, kind, nth=-1):
        found = [i for i, c in enumerate(self.calls) if c[0] == kind]
        return f"{self._prefix}{found[nth] + 1}"

    def count(self, kind):
        return sum(1 for c in self.calls if c[0] == kind)

    def answer(self, kind, result, nth=-1):
        self.done.emit(self.rid(kind, nth), result)

    def stop(self):
        self.calls.append(("stop",))


class FakeFiles(_Fake):
    def __init__(self):
        super().__init__("f")

    def list_dir(self, path): return self._rid("list", path)
    def read(self, path): return self._rid("read", path)
    def write(self, path, content): return self._rid("write", path, content)


class FakeCode(_Fake):
    def __init__(self):
        super().__init__("c")
        self.killed_now = 0

    def diagnostics(self, path): return self._rid("diagnostics", path)
    def run(self, cmd): return self._rid("run", cmd)
    def kill(self): return self._rid("kill")

    def kill_now(self, timeout=2.0):
        self.killed_now += 1
        return {"ok": True}

    def frame(self, **frame):
        self.line.emit(self.rid("run"), json.dumps(frame))


def _entries(*names):
    return {"root": "C:\\Users\\ray_g\\ade-ai", "path": "",
            "entries": [{"name": n.rstrip("/"), "path": n.rstrip("/"),
                         "kind": "dir" if n.endswith("/") else "file"} for n in names]}


def _children(item):
    return [(item.child(i).text(0), item.child(i).data(0, KIND))
            for i in range(item.childCount())]


def _find(tree, path):
    return tree._item_for(path) if path else None


# -- the tree ---------------------------------------------------------------------

@pytest.fixture
def tree(qapp):
    files = FakeFiles()
    t = FileTree(files)
    named = []
    t.root_named.connect(named.append)
    return t, files, named


def test_the_root_is_listed_folders_first_each_with_an_arrow(tree):
    t, files, named = tree
    t.refresh()
    assert files.calls == [("list", "")]
    files.answer("list", _entries("z.py", "adeos/", "README.md", "Docs/"))
    root = t.invisibleRootItem()
    assert _children(root) == [("adeos", "dir"), ("Docs", "dir"), ("README.md", "file"),
                               ("z.py", "file")]
    assert _children(root.child(0)) == [(LOADING, "note")]
    assert named == ["C:\\Users\\ray_g\\ade-ai"]


def test_a_folder_is_listed_once_when_opened(tree):
    t, files, _ = tree
    t.refresh()
    files.answer("list", _entries("adeos/"))
    folder = t.invisibleRootItem().child(0)
    folder.setExpanded(True)
    assert files.calls[-1] == ("list", "adeos")
    files.done.emit(files.rid("list"), {"root": "r", "path": "adeos", "entries": [
        {"name": "main.py", "path": "adeos/main.py", "kind": "file"}]})
    assert _children(folder) == [("main.py", "file")]
    folder.setExpanded(False)
    folder.setExpanded(True)
    assert files.count("list") == 2


def test_only_a_file_asks_to_be_opened(tree):
    t, files, _ = tree
    got = []
    t.open_requested.connect(got.append)
    t.refresh()
    files.answer("list", _entries("adeos/", "README.md"))
    root = t.invisibleRootItem()
    t.itemActivated.emit(root.child(0), 0)
    t.itemActivated.emit(root.child(1), 0)
    assert got == ["README.md"]


def test_a_failed_listing_says_why_and_opening_again_asks_again(tree):
    t, files, _ = tree
    t.refresh()
    files.answer("list", _entries("adeos/"))
    folder = t.invisibleRootItem().child(0)
    folder.setExpanded(True)
    files.answer("list", {"error": "ReadTimeout: timed out"})
    assert "Could not list it" in folder.child(0).text(0)
    assert "no answer in time" in folder.child(0).text(0)
    folder.setExpanded(False)
    folder.setExpanded(True)
    assert files.count("list") == 3


def test_a_folder_that_is_gone_says_so(tree):
    t, files, _ = tree
    t.refresh()
    files.answer("list", _entries("gone/"))
    folder = t.invisibleRootItem().child(0)
    folder.setExpanded(True)
    files.answer("list", {"error": {"code": "not_found", "message": "no directory"}})
    assert "gone" in folder.child(0).text(0) and "Refresh" in folder.child(0).text(0)


def test_a_listing_at_the_server_limit_says_it_was_cut(tree):
    t, files, _ = tree
    t.refresh()
    files.answer("list", _entries(*[f"f{n}.py" for n in range(500)]))
    root = t.invisibleRootItem()
    assert root.childCount() == 501 and "500" in root.child(500).text(0)


def test_refresh_reopens_what_was_open(tree):
    t, files, _ = tree
    t.refresh()
    files.answer("list", _entries("adeos/", "docs/"))
    t.invisibleRootItem().child(0).setExpanded(True)
    files.done.emit(files.rid("list"), {"root": "r", "path": "adeos", "entries": [
        {"name": "api", "path": "adeos/api", "kind": "dir"}]})
    t.invisibleRootItem().child(0).child(0).setExpanded(True)
    files.done.emit(files.rid("list"), {"root": "r", "path": "adeos/api", "entries": []})
    assert t.expanded_paths() == {"adeos", "adeos/api"}
    t.refresh()
    files.answer("list", _entries("adeos/", "docs/"))
    assert files.calls[-1] == ("list", "adeos")
    files.done.emit(files.rid("list"), {"root": "r", "path": "adeos", "entries": [
        {"name": "api", "path": "adeos/api", "kind": "dir"}]})
    assert files.calls[-1] == ("list", "adeos/api")
    assert t.expanded_paths() == {"adeos", "adeos/api"}


def test_a_listing_from_before_a_refresh_is_dropped(tree):
    t, files, _ = tree
    t.refresh()
    old = files.rid("list")
    t.refresh()
    files.done.emit(old, _entries("stale.py"))
    assert t.invisibleRootItem().childCount() == 0
    files.answer("list", _entries("fresh.py"))
    assert _children(t.invisibleRootItem()) == [("fresh.py", "file")]


# -- the panel --------------------------------------------------------------------

@pytest.fixture
def rig(qapp):
    code, files, answers = FakeCode(), FakeFiles(), []
    panel = CodePanel(code, files, confirm=lambda q: answers.pop(0) if answers else False)
    return panel, code, files, answers


def _open(panel, files, path="adeos/x.py", text="import os\nx = 1\n"):
    editor = panel.open_file(path)
    files.answer("read", {"text": text, "cached": False})
    return editor


DIAGS = {"ok": True, "data": {"counts": {"error": 2, "warning": 1, "info": 0}, "items": [
    {"severity": "error", "line": 2, "col": 5, "message": "bad\nmore detail",
     "code": "reportX"},
    {"severity": "error", "line": 1, "col": 1, "message": "worse", "code": ""},
    {"severity": "warning", "line": 2, "col": 1, "message": "meh", "code": "w"}]}}


def test_no_file_open_says_how_to_open_one(rig):
    panel, *_ = rig
    assert panel.stack.currentWidget() is panel.empty and panel.empty.text() == EMPTY_NOTE


def test_opening_an_open_file_focuses_its_tab_and_reads_nothing(rig):
    panel, code, files, _ = rig
    first = _open(panel, files, "a.py")
    _open(panel, files, "b.py")
    assert panel.tabs.count() == 2 and panel.current_editor().path == "b.py"
    assert panel.open_file("a.py") is first
    assert panel.tabs.count() == 2 and panel.current_editor() is first
    assert files.count("read") == 2


def test_a_tab_carries_a_dot_while_dirty(rig):
    panel, code, files, _ = rig
    editor = _open(panel, files, "adeos/x.py")
    assert panel.tabs.tabText(0) == "x.py" and panel.tabs.tabToolTip(0) == "adeos/x.py"
    editor.text.insertPlainText("# more\n")
    assert panel.tabs.tabText(0) == "x.py •"
    editor.save()
    files.answer("read", {"text": "import os\nx = 1\n", "cached": False})
    files.answer("write", {"ok": True, "path": "adeos/x.py", "bytes": 1})
    assert panel.tabs.tabText(0) == "x.py"


def test_closing_a_dirty_tab_asks_and_no_keeps_it(rig):
    panel, code, files, answers = rig
    editor = _open(panel, files)
    editor.text.insertPlainText("typed")
    answers.append(False)
    panel.tabs.tabCloseRequested.emit(0)
    assert panel.tabs.count() == 1 and "typed" in editor.current_text()
    answers.append(True)
    panel.tabs.tabCloseRequested.emit(0)
    assert panel.tabs.count() == 0 and panel.stack.currentWidget() is panel.empty


def test_the_editor_s_own_close_button_closes_its_tab(rig):
    panel, code, files, _ = rig
    editor = _open(panel, files)
    editor.close_button.click()
    assert panel.tabs.count() == 0


def test_a_loaded_file_is_checked_and_its_problems_listed(rig):
    panel, code, files, _ = rig
    _open(panel, files, "adeos/x.py")
    assert code.calls[-1] == ("diagnostics", "adeos/x.py")
    assert "Checking x.py" in panel.problems_label.text()
    code.answer("diagnostics", DIAGS)
    label = panel.problems_label.text()
    assert "as saved on disk" in label and "2 errors, 1 warning" in label
    assert panel.problems.topLevelItemCount() == 3
    first = panel.problems.topLevelItem(0)
    assert first.text(0) == "error" and first.text(1) == "2:5"
    assert first.text(2) == "bad  [reportX]" and first.toolTip(2) == "bad\nmore detail"
    assert panel.bottom.tabText(0) == "Problems (3)"


def test_a_file_with_no_checker_says_so_rather_than_no_problems(rig):
    panel, code, files, _ = rig
    _open(panel, files, "docs/notes.md")
    code.answer("diagnostics", {"ok": False, "error": {
        "code": "lsp_no_server", "message": "no language server for '.md' files"}})
    assert panel.problems_label.text() == "No checker for .md files."
    assert panel.problems.topLevelItemCount() == 0


def test_a_file_that_did_not_open_is_not_checked(rig):
    panel, code, files, _ = rig
    panel.open_file("gone.py")
    files.answer("read", {"error": {"code": "not_found", "message": "x"}, "status": 404})
    assert code.count("diagnostics") == 0
    assert "did not open" in panel.problems_label.text()


def test_an_answer_for_another_tab_is_dropped(rig):
    panel, code, files, _ = rig
    _open(panel, files, "a.py")
    first = code.rid("diagnostics")
    _open(panel, files, "b.py")
    code.done.emit(first, DIAGS)
    assert panel.problems.topLevelItemCount() == 0
    assert "Checking b.py" in panel.problems_label.text()


def test_switching_tabs_checks_the_one_now_shown(rig):
    panel, code, files, _ = rig
    _open(panel, files, "a.py")
    _open(panel, files, "b.py")
    panel.tabs.setCurrentIndex(0)
    assert code.calls[-1] == ("diagnostics", "a.py")


def test_saving_checks_again(rig):
    panel, code, files, _ = rig
    editor = _open(panel, files)
    before = code.count("diagnostics")
    editor.text.insertPlainText("y = 2\n")
    editor.save()
    files.answer("read", {"text": "import os\nx = 1\n", "cached": False})
    files.answer("write", {"ok": True, "path": "adeos/x.py", "bytes": 1})
    assert code.count("diagnostics") == before + 1


def test_a_problem_jumps_to_its_line_and_column(rig):
    panel, code, files, _ = rig
    editor = _open(panel, files, text="import os\nabcdefgh = 1\n")
    code.answer("diagnostics", DIAGS)
    panel.problems.itemActivated.emit(panel.problems.topLevelItem(0), 0)
    cursor = editor.text.textCursor()
    assert (cursor.blockNumber(), cursor.positionInBlock()) == (1, 4)
    assert panel.position.text() == "Ln 2, Col 5"


def test_find_goes_forward_back_and_wraps(rig):
    panel, code, files, _ = rig
    editor = _open(panel, files, text="alpha\nbeta alpha\ngamma\n")
    panel.show_find()
    assert panel.find_bar.isVisibleTo(panel)
    panel.find_bar.box.setText("alpha")
    panel.find_bar.next_button.click()
    assert editor.text.textCursor().selectionStart() == 0
    panel.find_bar.next_button.click()
    assert editor.text.textCursor().selectionStart() == 11
    panel.find_bar.next_button.click()                   # wraps to the top
    assert editor.text.textCursor().selectionStart() == 0
    panel.find_bar.prev_button.click()                   # wraps to the bottom
    assert editor.text.textCursor().selectionStart() == 11
    panel.find_bar.box.setText("zeta")
    panel.find_bar.next_button.click()
    assert panel.find_bar.note.text() == "No match"


def test_shift_enter_finds_backwards_and_escape_closes(rig):
    panel, code, files, _ = rig
    editor = _open(panel, files, text="one two one two\n")
    panel.show_find()
    panel.find_bar.box.setText("two")
    QTest.keyClick(panel.find_bar.box, Qt.Key.Key_Return)
    QTest.keyClick(panel.find_bar.box, Qt.Key.Key_Return)
    assert editor.text.textCursor().selectionStart() == 12
    QTest.keyClick(panel.find_bar.box, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert editor.text.textCursor().selectionStart() == 4
    QTest.keyClick(panel.find_bar.box, Qt.Key.Key_Escape)
    assert not panel.find_bar.isVisibleTo(panel)


def test_quitting_names_what_would_be_lost(rig):
    panel, code, files, _ = rig
    editor = _open(panel, files)
    assert panel.unsaved() == []
    editor.text.insertPlainText("typed")
    panel.terminal.command.setText("pytest")
    panel.terminal.run()
    lost = panel.unsaved()
    assert "unsaved changes to adeos/x.py" in lost
    assert any("may still be running" in item for item in lost)


def test_a_confirmed_quit_kills_the_running_command(rig):
    panel, code, files, _ = rig
    panel.terminal.command.setText("long-build")
    panel.terminal.run()
    panel.stop_clients()
    assert code.killed_now == 1
    assert ("stop",) in code.calls and ("stop",) in files.calls


def test_quitting_idle_kills_nothing(rig):
    panel, code, files, _ = rig
    panel.stop_clients()
    assert code.killed_now == 0


def test_the_tree_is_listed_the_first_time_the_section_shows(rig):
    panel, code, files, _ = rig
    assert files.count("list") == 0
    panel.show()
    panel.hide()
    panel.show()
    assert files.count("list") == 1
    panel.hide()


# -- the terminal -----------------------------------------------------------------

@pytest.fixture
def term(qapp):
    code = FakeCode()
    return TerminalPane(code), code


def _run(pane, cmd="git status"):
    pane.command.setText(cmd)
    pane.run()


def test_a_command_echoes_streams_and_ends_with_its_code(term, pump):
    pane, code = term
    _run(pane)
    assert code.calls == [("run", "git status")] and pane.command.text() == ""
    assert pane.output.toPlainText() == "PS> git status"
    assert not pane.run_button.isEnabled() and pane.stop_button.isEnabled()
    code.frame(type="out", text="On branch mind-evolve")
    code.frame(type="exit", code=0)
    code.answer("run", {"ok": True})
    assert pane.output.toPlainText().splitlines() == [
        "PS> git status", "On branch mind-evolve", "[exit 0]"]
    assert pane.run_button.isEnabled() and not pane.stop_button.isEnabled()
    assert not pane.is_running()


def test_lines_are_put_on_screen_in_batches(term, pump):
    pane, code = term
    _run(pane)
    for n in range(300):
        code.frame(type="out", text=f"line {n}")
    assert "line 0" not in pane.output.toPlainText()       # not one paint per line
    assert pump(lambda: "line 299" in pane.output.toPlainText(), timeout=2)


def test_the_screen_keeps_only_the_newest_lines(term):
    pane, code = term
    _run(pane)
    for n in range(MAX_LINES + 2000):
        code.frame(type="out", text=f"line {n}")
    pane.flush()
    assert pane.output.blockCount() <= MAX_LINES
    assert pane.output.toPlainText().endswith(f"line {MAX_LINES + 1999}")


def test_one_command_at_a_time(term):
    pane, code = term
    _run(pane, "first")
    _run(pane, "second")
    assert code.count("run") == 1 and "One command at a time" in pane.note.text()


def test_stop_kills_the_session_and_drops_what_comes_after(term):
    pane, code = term
    _run(pane)
    code.frame(type="out", text="before")
    pane.stop_button.click()
    assert code.calls[-1] == ("kill",)
    assert not pane.is_running() and not pane.run_button.isEnabled()   # until the kill lands
    code.line.emit(code.rid("run"), json.dumps({"type": "out", "text": "after"}))
    code.answer("run", {"ok": True, "stopped": True})
    code.answer("kill", {"ok": True})
    pane.flush()                                   # anything buffered is on screen now
    text = pane.output.toPlainText()
    assert "before" in text and "[stopped]" in text and "after" not in text
    assert "without an exit code" not in text
    assert pane.note.text() == STOPPED_NOTE and pane.run_button.isEnabled()


def test_a_failed_kill_leaves_stop_usable(term):
    pane, code = term
    _run(pane)
    pane.stop()
    code.answer("kill", {"error": "ConnectError: refused"})
    assert "Could not stop it" in pane.note.text() and pane.stop_button.isEnabled()
    pane.stop()
    assert code.count("kill") == 2


def test_a_busy_session_says_so_and_offers_stop(term):
    pane, code = term
    _run(pane)
    code.answer("run", {"error": "session busy: one command at a time", "status": 409})
    assert "[not run: the session is busy]" in pane.output.toPlainText()
    assert pane.note.text() == BUSY_NOTE and pane.stop_button.isEnabled()
    pane.stop()
    assert code.calls[-1] == ("kill",)


def test_no_answer_is_not_run_but_a_lost_stream_may_still_be_running(term):
    pane, code = term
    _run(pane)
    code.answer("run", {"error": "ConnectError: [WinError 10061] refused"})
    assert "[not run: Ade OS unreachable" in pane.output.toPlainText()
    _run(pane)
    code.frame(type="out", text="building")
    code.answer("run", {"error": "RemoteProtocolError: peer closed"})
    assert "[connection lost:" in pane.output.toPlainText()
    assert "may still be running" in pane.output.toPlainText()


def test_a_stream_with_no_exit_frame_says_so(term):
    pane, code = term
    _run(pane)
    code.frame(type="out", text="x")
    code.answer("run", {"ok": True})
    assert "[the stream ended without an exit code]" in pane.output.toPlainText()


def test_error_frames_and_colour_codes(term):
    pane, code = term
    _run(pane)
    esc = chr(27)
    code.frame(type="out", text=esc + "[32mPASSED" + esc + "[0m")
    code.frame(type="error", text="boom")
    code.line.emit(code.rid("run"), "not json at all")
    pane.flush()
    assert pane.output.toPlainText().splitlines()[1:] == ["PASSED", "[error] boom",
                                                          "not json at all"]


def test_up_and_down_recall_commands(term):
    pane, code = term
    _run(pane, "git status")
    code.answer("run", {"ok": True})
    _run(pane, "pytest -q")
    code.answer("run", {"ok": True})
    pane.command.setText("draft")
    QTest.keyClick(pane.command, Qt.Key.Key_Up)
    assert pane.command.text() == "pytest -q"
    QTest.keyClick(pane.command, Qt.Key.Key_Up)
    assert pane.command.text() == "git status"
    QTest.keyClick(pane.command, Qt.Key.Key_Down)
    QTest.keyClick(pane.command, Qt.Key.Key_Down)
    assert pane.command.text() == "draft"


def test_enter_runs(term):
    pane, code = term
    pane.command.setText("ls")
    QTest.keyClick(pane.command, Qt.Key.Key_Return)
    assert code.calls == [("run", "ls")]


# -- the client -------------------------------------------------------------------

def test_the_client_uses_its_own_session_and_stop_reaches_the_stream(qapp, pump):
    seen, gate = [], threading.Event()

    def stream(url, body, on_line, should_stop):
        seen.append((url, body))
        on_line('{"type": "out", "text": "one"}')
        gate.wait(5)
        return {"ok": True, "stopped": should_stop()}

    posted = []

    def request(method, url, body, timeout, headers=None):
        posted.append((method, url, body))
        return {"ok": True}

    c = CodeClient("http://ade", stream=stream, request=request)
    lines, done = [], []
    c.line.connect(lambda rid, t: lines.append(t))
    c.done.connect(lambda rid, r: done.append(r))
    c.run("pytest")
    assert pump(lambda: lines == ['{"type": "out", "text": "one"}'])
    c.kill()
    gate.set()
    assert pump(lambda: len(done) == 2)
    assert seen == [("http://ade/v1/terminal/run", {"session": SESSION, "cmd": "pytest"})]
    assert SESSION == "ade-desktop-code"
    assert posted == [("POST", "http://ade/v1/terminal/kill", {"session": SESSION})]
    assert {"ok": True, "stopped": True} in done


def test_a_run_after_a_stop_is_not_born_stopped(qapp, pump):
    """Each run has its own stop flag: the kill of the last one must not
    end the next one before its first line."""
    stops = []

    def stream(url, body, on_line, should_stop):
        stops.append(should_stop())
        return {"ok": True}

    c = CodeClient("http://ade", stream=stream,
                   request=lambda method, url, body, timeout, headers=None: {"ok": True})
    c.run("one")
    assert pump(lambda: len(stops) == 1)
    c.kill()
    c.run("two")
    assert pump(lambda: len(stops) == 2)
    assert stops == [False, False]


def test_the_checker_is_asked_by_file(qapp, pump):
    urls = []
    c = CodeClient("http://ade", get=lambda url, timeout: urls.append(url) or {"ok": True})
    c.diagnostics("adeos/api/app.py")
    assert pump(lambda: bool(urls))
    assert urls == ["http://ade/v1/lsp/diagnostics?file=adeos%2Fapi%2Fapp.py"]


# -- lifetime ---------------------------------------------------------------------

def test_a_dropped_code_panel_is_freed_at_once(qapp, monkeypatch):
    raised = []
    monkeypatch.setattr(sys, "excepthook", lambda *exc: raised.append(exc[1]))
    code, files = FakeCode(), FakeFiles()
    panel = CodePanel(code, files, confirm=lambda q: False)
    panel.open_file("a.py")
    files.answer("read", {"text": "x\n", "cached": False})
    panel.terminal.command.setText("ls")
    panel.terminal.run()
    panel.show_find()
    ref = weakref.ref(panel)
    gc.disable()
    try:
        del panel
        assert ref() is None
    finally:
        gc.enable()
    code.frame(type="out", text="late")              # delivered to nobody
    code.answer("diagnostics", DIAGS)
    files.answer("read", {"text": "late", "cached": False})
    assert raised == [], raised                       # ...and nothing raised on the way


# -- live, against the running Ade OS ------------------------------------------------

def _ade_up():
    from ade_desktop.ade_status import ade_base
    from ade_desktop.net import get_json
    return "status" in get_json(ade_base() + "/v1/health", 3.0)


@pytest.mark.skipif(not _ade_up(), reason="Ade OS is not answering on :8300")
def test_live_a_command_streams_and_ends(qapp, pump, monkeypatch):
    monkeypatch.setattr(client_mod, "SESSION", "ade-desktop-test")
    c = CodeClient()
    lines, done = [], []
    c.line.connect(lambda rid, t: lines.append(t))
    c.done.connect(lambda rid, r: done.append(r))
    try:
        c.run("Write-Output ade-live-check")
        assert pump(lambda: bool(done), timeout=60)
        frames = [json.loads(line) for batch in lines for line in batch.split("\n")]
        assert {"type": "out", "text": "ade-live-check"} in frames
        assert frames[-1] == {"type": "exit", "code": 0}
    finally:
        c.kill_now(timeout=10.0)


@pytest.mark.skipif(not _ade_up(), reason="Ade OS is not answering on :8300")
def test_live_the_checker_answers_in_the_measured_shape(qapp, pump):
    c = CodeClient()
    done = []
    c.done.connect(lambda rid, r: done.append(r))
    c.diagnostics("adeos/desktop/ade_desktop/net.py")
    assert pump(lambda: bool(done), timeout=90)
    assert done[0]["ok"] is True and set(done[0]["data"]) == {"counts", "items"}


# -- the piece-7 review (2026-09-18) --------------------------------------------------

def test_the_client_hands_lines_on_in_batches_in_order(qapp, pump):
    """One signal per line froze the window at ~23k lines/s: lines travel
    in batches, in order, all before the result."""
    n = 2500

    def stream(url, body, on_line, should_stop):
        for i in range(n):
            on_line(json.dumps({"type": "out", "text": f"l{i}"}))
        return {"ok": True}

    c = CodeClient("http://ade", stream=stream)
    batches, done = [], []
    c.line.connect(lambda rid, t: batches.append(t))
    c.done.connect(lambda rid, r: done.append(len(batches)))
    c.run("flood")
    assert pump(lambda: bool(done), timeout=10)
    lines = [json.loads(x)["text"] for b in batches for x in b.split("\n")]
    assert lines == [f"l{i}" for i in range(n)]
    assert len(batches) <= 10 and done == [len(batches)]


def test_a_quiet_line_is_not_held_until_the_next(qapp, pump):
    """A line followed by silence goes out on the timer, not when more
    output (or the end) happens to come."""
    gate = threading.Event()

    def stream(url, body, on_line, should_stop):
        on_line('{"type": "out", "text": "first"}')
        gate.wait(5)
        return {"ok": True}

    c = CodeClient("http://ade", stream=stream)
    got = []
    c.line.connect(lambda rid, t: got.append(t))
    c.run("slow")
    try:
        assert pump(lambda: bool(got), timeout=2)
    finally:
        gate.set()


def test_a_batch_of_frames_is_read_frame_by_frame(term):
    pane, code = term
    _run(pane)
    code.line.emit(code.rid("run"), "\n".join(json.dumps(f) for f in (
        {"type": "out", "text": "a"}, {"type": "out", "text": "b"},
        {"type": "exit", "code": 2})))
    code.answer("run", {"ok": True})
    assert pane.output.toPlainText().splitlines()[1:] == ["a", "b", "[exit 2]"]


def test_the_waiting_buffer_keeps_only_what_the_screen_would(term):
    pane, code = term
    _run(pane)
    for n in range(MAX_LINES + 500):
        pane._put(f"x{n}")
    assert len(pane._buffer) == MAX_LINES and pane._buffer[-1] == f"x{MAX_LINES + 499}"


def test_a_lost_stream_can_still_be_stopped_and_quitting_kills_it(term):
    pane, code = term
    _run(pane)
    code.frame(type="out", text="building")
    code.answer("run", {"error": "RemoteProtocolError: peer closed"})
    assert not pane.is_running() and pane.may_be_running()
    assert pane.stop_button.isEnabled() and pane.run_button.isEnabled()
    pane.stop_now()
    assert code.killed_now == 1 and not pane.may_be_running()


def test_quitting_mid_kill_kills_again(term):
    pane, code = term
    _run(pane)
    pane.stop()                            # the kill is still in flight
    assert pane.may_be_running()
    pane.stop_now()
    assert code.killed_now == 1


def test_quit_names_a_lost_command(rig):
    panel, code, files, _ = rig
    panel.terminal.command.setText("build")
    panel.terminal.run()
    code.frame(type="out", text="x")
    code.answer("run", {"error": "ReadError: reset"})
    assert any("may still be running" in item for item in panel.unsaved())


def test_down_in_the_command_line_keeps_what_was_typed(term):
    pane, code = term
    _run(pane, "ls")
    code.answer("run", {"ok": True})
    pane.command.setText("Get-ChildItem -Recurse")
    QTest.keyClick(pane.command, Qt.Key.Key_Down)
    assert pane.command.text() == "Get-ChildItem -Recurse"


def test_a_tab_still_opening_does_not_show_the_last_tab_s_problems(rig):
    panel, code, files, _ = rig
    _open(panel, files, "a.py")
    code.answer("diagnostics", DIAGS)
    assert panel.problems.topLevelItemCount() == 3
    panel.open_file("b.py")                  # not answered yet
    assert panel.problems.topLevelItemCount() == 0
    assert "Waiting for b.py" in panel.problems_label.text()
    panel.tabs.setCurrentIndex(0)
    panel.tabs.setCurrentIndex(1)
    assert "Waiting for b.py" in panel.problems_label.text()


def test_a_tab_that_did_not_open_does_not_show_the_last_tab_s_problems(rig):
    panel, code, files, _ = rig
    panel.open_file("gone.py")
    files.answer("read", {"error": {"code": "not_found", "message": "x"}, "status": 404})
    _open(panel, files, "a.py")
    code.answer("diagnostics", DIAGS)
    panel.tabs.setCurrentIndex(0)
    assert panel.problems.topLevelItemCount() == 0
    assert "did not open" in panel.problems_label.text()


def test_an_older_check_of_the_same_file_is_dropped(rig):
    panel, code, files, _ = rig
    _open(panel, files, "a.py")
    first = code.rid("diagnostics")
    panel.check_button.click()
    code.done.emit(first, DIAGS)
    assert panel.problems.topLevelItemCount() == 0 and "Checking" in panel.problems_label.text()
    code.answer("diagnostics", {"ok": True, "data": {"counts": {}, "items": []}})
    assert "No problems" in panel.problems_label.text()


def test_a_jump_with_unsaved_edits_says_the_lines_may_have_moved(rig):
    panel, code, files, _ = rig
    editor = _open(panel, files, text="import os\nabcdefgh = 1\n")
    code.answer("diagnostics", DIAGS)
    panel.problems.itemActivated.emit(panel.problems.topLevelItem(0), 0)
    assert "may have moved" not in panel.problems_label.text()
    editor.text.moveCursor(editor.text.textCursor().MoveOperation.Start)
    editor.text.insertPlainText("# new\n")
    panel.problems.itemActivated.emit(panel.problems.topLevelItem(0), 0)
    label = panel.problems_label.text()
    assert "may have moved" in label and "2 errors, 1 warning" in label


def test_a_search_with_no_match_leaves_the_cursor_where_it_was(rig):
    panel, code, files, _ = rig
    editor = _open(panel, files, text="".join(f"line {n}\n" for n in range(50)))
    cursor = editor.text.textCursor()
    cursor.setPosition(editor.text.document().findBlockByNumber(30).position() + 2)
    editor.text.setTextCursor(cursor)
    panel.show_find()
    for backward in (False, True):
        panel.find_bar.box.setText("zeta")
        panel.find_bar.find.emit("zeta", backward)
        c = editor.text.textCursor()
        assert (c.blockNumber(), c.positionInBlock()) == (30, 2)
