"""Dropped or picked files for /v1/upload, within the avatar's limits,
trimmed BEFORE anything is sent."""

from ade_desktop.conversation import uploads
from ade_desktop.conversation.uploads import report, walk


def test_walk_keeps_paths_relative_to_the_parent_and_skips_dirs(tmp_path):
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("a")
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("x")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "m.js").write_text("x")
    plan = walk([str(root)])
    assert [f.rel for f in plan.send] == ["proj/src/a.py"]
    assert ("proj/.git", "skipped by name") in plan.skipped
    assert ("proj/node_modules", "skipped by name") in plan.skipped
    assert plan.found == 1


def test_file_cap_is_applied_before_sending(tmp_path, monkeypatch):
    monkeypatch.setattr(uploads, "MAX_FILES", 2)
    for i in range(3):
        (tmp_path / f"f{i}.txt").write_text("x")
    plan = walk([str(tmp_path / f"f{i}.txt") for i in range(3)])
    assert [f.rel for f in plan.send] == ["f0.txt", "f1.txt"]
    assert plan.skipped == [("f2.txt", "over 2 files")]


def test_byte_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(uploads, "MAX_TOTAL", 5)
    (tmp_path / "a.txt").write_text("1234")
    (tmp_path / "b.txt").write_text("1234")
    plan = walk([str(tmp_path / "a.txt"), str(tmp_path / "b.txt")])
    assert [f.rel for f in plan.send] == ["a.txt"]
    assert plan.skipped == [("b.txt", "over the 50 MB drop limit")]


def test_depth_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(uploads, "MAX_DEPTH", 1)
    deep = tmp_path / "d" / "e"
    deep.mkdir(parents=True)
    (deep / "x.txt").write_text("x")
    (tmp_path / "d" / "top.txt").write_text("t")
    plan = walk([str(tmp_path / "d")])
    assert [f.rel for f in plan.send] == ["d/top.txt"]
    assert ("d/e", "deeper than 1") in plan.skipped


def test_report():
    assert report(2, 2048, 3, [("c", "why")], [("d", "HTTP 409")]) == (
        "Sent 2 of 3 files (2.0 KB).\nSkipped: c (why)\nFailed: d (HTTP 409)")
    assert report(0, 0, 0, [], []) == "Sent 0 of 0 files (0.0 KB)."
