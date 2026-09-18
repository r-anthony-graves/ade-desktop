"""The panel's threads on disk. The avatar's formats and caps, in a file of
its own; atomic; a corrupt file is set aside, never lost."""

import json

from ade_desktop.conversation.threads import COMPACT_KEEP, MAX_ARCHIVE, ThreadStore


def test_round_trip_and_working_is_never_saved(tmp_path):
    s = ThreadStore(tmp_path / "threads.json")
    s.push("chat", "user", "ask", "hi")
    s.push("chat", "system", "working", "Working…")
    s.skills = ["ade-brainstorming"]
    s.tab = "shell"
    s.save()
    t = ThreadStore(tmp_path / "threads.json")
    assert [m["text"] for m in t.chat] == ["hi"]
    assert t.skills == ["ade-brainstorming"] and t.tab == "shell"
    assert t.load_note is None


def test_clear_compact_restore(tmp_path):
    s = ThreadStore(tmp_path / "t.json")
    for i in range(25):
        s.push("chat", "user", "ask", f"q{i}")
    assert s.compact("chat") == 5 and len(s.chat) == COMPACT_KEEP
    assert s.compact("chat") is None
    assert s.clear("chat") == 20 and s.chat == []
    assert s.clear("chat") == 0
    assert s.restore() == ("chat", 20)
    assert s.restore() == ("chat", 5)
    assert s.chat[0]["text"] == "q0" and len(s.chat) == 25
    assert s.restore() is None


def test_archive_keeps_the_newest_20(tmp_path):
    s = ThreadStore(tmp_path / "t.json")
    for i in range(25):
        s.push("shell", "user", "shell", f"c{i}")
        s.clear("shell")
    assert len(s.archive) == MAX_ARCHIVE
    assert s.archive[-1]["messages"][0]["text"] == "c24"
    assert s.archive[0]["messages"][0]["text"] == "c5"


def test_a_corrupt_file_is_set_aside_not_lost(tmp_path):
    p = tmp_path / "threads.json"
    p.write_text("{not json", encoding="utf-8")
    s = ThreadStore(p)
    assert s.chat == [] and s.load_note and "set aside" in s.load_note
    aside = list(tmp_path.glob("threads.json.bad-*"))
    assert len(aside) == 1
    assert aside[0].read_text(encoding="utf-8") == "{not json"


def test_save_is_atomic(tmp_path, monkeypatch):
    import os

    p = tmp_path / "t.json"
    s = ThreadStore(p)
    s.push("chat", "user", "ask", "kept")
    s.save()
    s.push("chat", "user", "ask", "lost")

    def boom(*a, **k):
        raise OSError("disk gone")

    monkeypatch.setattr(os, "replace", boom)
    s.save()   # must not raise, must not truncate
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert [m["text"] for m in saved["chat"]] == ["kept"]
