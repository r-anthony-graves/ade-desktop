"""Piece 7's pure rules: terminal frames, colour codes, what the Problems
list says, and command recall."""

import pytest

from ade_desktop.sections.code.model import (History, diag_note, diag_summary, dirs_first,
                                             listing_note, parse_frame, strip_ansi, tab_title)


# -- frames (the measured /v1/terminal/run shapes) ---------------------------------

def test_frames_are_read_as_ade_os_writes_them():
    assert parse_frame('{"type": "out", "text": "hello"}') == ("out", "hello")
    assert parse_frame('{"type": "exit", "code": 3}') == ("exit", 3)
    assert parse_frame('{"type": "error", "text": "boom"}') == ("error", "boom")


@pytest.mark.parametrize("line", ["not json", "[1, 2]", '{"type": "odd"}', '{"type": "exit"}',
                                  '{"type": "exit", "code": "x"}', '{"type": "out"}'])
def test_anything_else_is_shown_raw_never_dropped(line):
    assert parse_frame(line) == ("raw", line)


def test_a_bool_is_not_an_exit_code():
    assert parse_frame('{"type": "exit", "code": true}')[0] == "raw"


# -- colour codes -------------------------------------------------------------------

def test_colour_and_cursor_codes_are_stripped():
    esc = chr(27)
    assert strip_ansi(esc + "[31mred" + esc + "[0m") == "red"
    assert strip_ansi(esc + "[?25lhidden" + esc + "[2K") == "hidden"
    assert strip_ansi(esc + "]0;title" + chr(7) + "text") == "text"
    assert strip_ansi("plain\r") == "plain"
    assert strip_ansi("a [31m b") == "a [31m b"            # no ESC: not a code


# -- the Problems list ----------------------------------------------------------------

def test_the_summary_counts_what_there_is():
    assert diag_summary({"error": 2, "warning": 1, "info": 0}) == "2 errors, 1 warning"
    assert diag_summary({"error": 1, "warning": 0, "info": 3}) == "1 error, 3 notes"
    assert diag_summary({"error": 0, "warning": 0, "info": 0}) == "No problems"
    assert diag_summary(None) == "No problems"


@pytest.mark.parametrize("result, words", [
    ({"ok": False, "error": {"code": "lsp_no_server",
                             "message": "no language server for '.md' files"}},
     "No checker for .md files"),
    ({"ok": False, "error": {"code": "lsp_no_server",
                             "message": "cannot read C:\\x.py: [Errno 2] No such file"}},
     "cannot read"),
    ({"ok": False, "error": {"code": "lsp_timeout", "message": "no diagnostics in 30s"}},
     "did not answer in time"),
    ({"ok": False, "error": {"code": "lsp_server_down", "message": "died"}}, "not running"),
    ({"error": "ConnectError: refused"}, "Ade OS is not answering"),
    ({"ok": True}, "no answer"),
])
def test_a_refusal_is_said_never_shown_as_an_empty_list(result, words):
    assert words in diag_note(result, "adeos/x.md")


def test_a_real_answer_has_no_note():
    assert diag_note({"ok": True, "data": {"counts": {}, "items": []}}, "a.py") is None


# -- the tree -------------------------------------------------------------------------

def test_folders_come_first_then_names_case_blind():
    entries = [{"name": "b.py", "kind": "file"}, {"name": "Zed", "kind": "dir"},
               {"name": "A.md", "kind": "file"}, {"name": "alpha", "kind": "dir"}]
    assert [e["name"] for e in dirs_first(entries)] == ["alpha", "Zed", "A.md", "b.py"]


def test_a_listing_cut_at_the_server_limit_says_so():
    assert listing_note([{}] * 499) is None
    assert "500" in listing_note([{}] * 500)


def test_a_tab_is_the_file_name_and_a_dot_while_dirty():
    assert tab_title("adeos/api/app.py", False) == "app.py"
    assert tab_title("adeos/api/app.py", True) == "app.py •"


# -- command recall -------------------------------------------------------------------

def test_up_walks_back_and_down_returns_to_the_draft():
    h = History()
    for c in ("git status", "pytest -q", "ls"):
        h.add(c)
    assert h.prev("half-typ") == "ls"
    assert h.prev("ls") == "pytest -q"
    assert h.prev("pytest -q") == "git status"
    assert h.prev("git status") == "git status"          # the oldest stays put
    assert h.next("git status") == "pytest -q"
    assert h.next("pytest -q") == "ls"
    assert h.next("ls") == "half-typ"                     # the draft, as it was
    assert h.next("half-typ") == "half-typ"


def test_down_when_not_walking_leaves_the_line_alone():
    """The review: Down erased a typed line, and after a run it put back
    an old draft."""
    h = History()
    h.add("ls")
    assert h.next("Get-ChildItem -Recurse") == "Get-ChildItem -Recurse"
    h.prev("half")
    h.add("pytest")                                       # ran something else
    assert h.next("typing anew") == "typing anew"


def test_recall_skips_repeats_and_blanks_and_is_capped():
    h = History(limit=3)
    for c in ("a", "a", "  ", "b", "c", "d"):
        h.add(c)
    assert [h.prev(""), h.prev(""), h.prev(""), h.prev("")] == ["d", "c", "b", "b"]


def test_adding_resets_the_walk():
    h = History()
    h.add("one")
    h.add("two")
    h.prev("")
    h.add("three")
    assert h.prev("") == "three"
