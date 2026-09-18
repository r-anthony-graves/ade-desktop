"""The one file editor. It must never save a read that was not the file on
disk, never overwrite a file that changed since it was opened, never drop
unsaved text on a failure -- and CRLF is not a difference."""

import gc
import weakref

import pytest
from PySide6.QtCore import QObject, Signal

from ade_desktop.workspace.editor import CACHED_NOTE, FileEditor
from ade_desktop.workspace.files import FilesClient


class FakeFiles(QObject):
    """Records calls; results are delivered by the test, in order."""
    done = Signal(str, object)

    def __init__(self):
        super().__init__()
        self.calls = []

    def _rid(self, *call):
        self.calls.append(call)
        return f"f{len(self.calls)}"

    def read(self, path): return self._rid("read", path)
    def write(self, path, content): return self._rid("write", path, content)

    def answer(self, result, n=None):
        rid = f"f{n or len(self.calls)}"
        self.done.emit(rid, result)


@pytest.fixture
def ed(qapp):
    files = FakeFiles()
    answers = []
    editor = FileEditor(files, confirm=lambda q: answers.pop(0) if answers else False)
    editor.answers = answers
    return editor, files


def _open(editor, files, text="line one\nline two\n", cached=False):
    editor.open("pm/x/charter.md")
    files.answer({"text": text, "cached": cached})


def test_open_reads_from_disk_and_is_editable(ed):
    editor, files = ed
    _open(editor, files)
    assert files.calls == [("read", "pm/x/charter.md")]
    assert editor.text.toPlainText() == "line one\nline two\n"
    assert not editor.text.isReadOnly() and not editor.is_dirty()
    assert not editor.save_button.isEnabled()


def test_the_index_copy_is_read_only_and_never_saved(ed):
    editor, files = ed
    _open(editor, files, text="fragment", cached=True)
    assert editor.text.isReadOnly() and editor.note.text() == CACHED_NOTE
    editor.text.setPlainText("typed anyway")      # a programmatic edit, even
    editor.save()
    assert [c[0] for c in files.calls] == ["read"]
    assert not editor.save_button.isEnabled()


@pytest.mark.parametrize("status, words", [(404, "no file"), (413, "Too large"),
                                           (415, "Not a text type"), (403, "Outside")])
def test_a_refused_open_is_read_only_with_the_reason(ed, status, words):
    editor, files = ed
    editor.open("x.bin")
    files.answer({"error": {"code": "x", "message": "y"}, "status": status})
    assert editor.text.isReadOnly() and words in editor.note.text()


def test_save_rechecks_the_disk_then_writes(ed):
    editor, files = ed
    _open(editor, files)
    editor.text.setPlainText("line one\nEDITED\n")
    assert editor.is_dirty() and editor.title.text().endswith("•")
    editor.save()
    assert files.calls[-1] == ("read", "pm/x/charter.md")
    files.answer({"text": "line one\r\nline two\r\n", "cached": False})   # CRLF: same file
    assert files.calls[-1] == ("write", "pm/x/charter.md", "line one\nEDITED\n")
    saved = []
    editor.saved.connect(saved.append)
    files.answer({"ok": True, "path": "pm/x/charter.md", "bytes": 16})
    assert saved == ["pm/x/charter.md"] and not editor.is_dirty()


def test_a_file_changed_on_disk_is_not_overwritten(ed):
    editor, files = ed
    _open(editor, files)
    editor.text.setPlainText("mine\n")
    editor.save()
    files.answer({"text": "Ade wrote this meanwhile\n", "cached": False})
    assert [c[0] for c in files.calls] == ["read", "read"]         # no write
    assert "changed on disk" in editor.note.text()
    assert editor.text.toPlainText() == "mine\n" and editor.is_dirty()


def test_a_failed_save_keeps_the_text(ed):
    editor, files = ed
    _open(editor, files)
    editor.text.setPlainText("mine\n")
    editor.save()
    files.answer({"text": "line one\nline two\n", "cached": False})
    files.answer({"error": {"code": "write_failed", "message": "disk full"}, "status": 500})
    assert "Save failed" in editor.note.text() and "disk full" in editor.note.text()
    assert editor.text.toPlainText() == "mine\n" and editor.is_dirty()


def test_unsaved_edits_are_not_dropped_without_asking(ed):
    editor, files = ed
    _open(editor, files)
    editor.text.setPlainText("mine\n")
    editor.answers.append(False)
    assert editor.open("pm/x/other.md") is False
    assert editor.path == "pm/x/charter.md" and editor.text.toPlainText() == "mine\n"
    editor.answers.append(False)
    assert editor.close_file() is False
    editor.answers.append(True)
    assert editor.open("pm/x/other.md") is True and editor.path == "pm/x/other.md"


def test_a_late_answer_for_another_file_is_ignored(ed):
    editor, files = ed
    editor.open("a.md")
    editor.open("b.md")
    files.answer({"text": "A", "cached": False}, n=1)
    assert editor.path == "b.md" and editor.baseline is None
    files.answer({"text": "B", "cached": False}, n=2)
    assert editor.text.toPlainText() == "B"


def test_the_files_client_always_asks_for_disk(qapp):
    urls = []
    client = FilesClient("http://ade", text=lambda url, t: urls.append(url) or {"text": ""})
    client.read("adeos/api/app.py")
    import time
    for _ in range(100):
        if urls:
            break
        time.sleep(0.01)
    assert urls == ["http://ade/v1/file?path=adeos%2Fapi%2Fapp.py&source=disk"]


def test_a_dropped_editor_is_freed_at_once(qapp):
    editor = FileEditor(FakeFiles(), confirm=lambda q: True)
    ref = weakref.ref(editor)
    gc.disable()
    try:
        del editor
        assert ref() is None
    finally:
        gc.enable()


def test_a_write_reply_that_does_not_say_ok_is_not_a_save(ed):
    editor, files = ed
    _open(editor, files)
    editor.text.setPlainText("mine\n")
    editor.save()
    files.answer({"text": "line one\nline two\n", "cached": False})
    files.answer({"detail": "something else answered"})
    assert "Save failed" in editor.note.text() and editor.is_dirty()
