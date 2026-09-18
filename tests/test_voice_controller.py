"""Speech may ASK or STAGE -- never more. Driven against the REAL panel with
a recording client: whatever is said, decide / task / shell / run / upload
are never called, and the Shell tab being open changes nothing."""

import base64
import io
import wave

import pytest

from ade_desktop.conversation.panel import ConversationPanel
from ade_desktop.conversation.threads import ThreadStore
from PySide6.QtCore import QObject, Signal

from ade_desktop.voice.controller import VoiceController


class FakeClient(QObject):
    """test_panel.py's recording client (not importable under
    --import-mode=importlib): every call the panel makes is written down."""
    done = Signal(str, object)
    line = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.calls = []

    def _rid(self, *call):
        self.calls.append(call)
        return f"r{len(self.calls)}"

    def ask(self, q, skills, history): return self._rid("ask", q, list(skills), list(history))
    def chat(self, text): return self._rid("chat", text)
    def task(self, text, t, skills): return self._rid("task", text, t, list(skills))
    def shell(self, cmd): return self._rid("shell", cmd)
    def run(self, cmd): return self._rid("run", cmd)
    def kill(self): return self._rid("kill")
    def health(self): return self._rid("health")
    def skills(self): return self._rid("skills")
    def task_types(self): return self._rid("task_types")
    def decide(self, aid, allow): return self._rid("decide", aid, allow)
    def upload(self, files, overwrite): return self._rid("upload", len(files), overwrite)


class FakeWatcher(QObject):
    appeared = Signal(object)
    vanished = Signal(str)

FORBIDDEN = {"decide", "task", "shell", "run", "upload", "chat", "kill"}


class Harness:
    """The signal slots capture a plain dict, never the Harness (see
    test_orb.Rig: a cycle through Qt objects is freed on a worker)."""

    def __init__(self, tmp_path, listen=None):
        self.client, self.watcher = FakeClient(), FakeWatcher()
        self.panel = ConversationPanel(self.client, self.watcher,
                                       ThreadStore(tmp_path / "threads.json"))
        counts = self.counts = {"opened": 0, "woken": 0}
        self.ctl = VoiceController(self.panel, base="http://ade",
                                   listen=listen or (lambda *a: {"error": "unused"}))
        self.ctl.open_requested.connect(lambda: counts.__setitem__("opened", counts["opened"] + 1))
        self.ctl.wake_heard.connect(lambda: counts.__setitem__("woken", counts["woken"] + 1))

    @property
    def opened(self):
        return self.counts["opened"]

    @property
    def woken(self):
        return self.counts["woken"]

    def verbs(self):
        return [c[0] for c in self.client.calls]

    def notes(self):
        return [m["text"] for m in self.panel.view_messages("chat")
                if m.get("role") == "system"]


@pytest.fixture
def h(qapp, tmp_path):
    return Harness(tmp_path)


def test_not_woken_whisper_is_typed_not_sent(h):
    assert h.ctl.on_text("what time is it", "whisper") == "typed"
    assert h.panel.input.text() == "what time is it"
    assert h.client.calls == [] and h.woken == 0 and h.opened == 0


def test_overheard_dictation_never_touches_a_draft_or_writes_a_note(h):
    h.panel.input.setText("my draft")
    before = len(h.notes())
    assert h.ctl.on_text("so anyway I told him", "whisper") == "ignored"
    assert h.panel.input.text() == "my draft" and len(h.notes()) == before


def test_not_woken_windows_engine_is_ignored(h):
    assert h.ctl.on_text("open the pod bay doors", "windows") == "ignored"
    assert h.panel.input.text() == "" and h.client.calls == []


@pytest.mark.parametrize("said", ["Hey Ade ", "Ade.", "ada", "OK Aday!"])
def test_the_wake_word_alone_opens_on_the_input(h, said):
    assert h.ctl.on_text(said, "whisper") == "opened"
    assert (h.woken, h.opened) == (1, 1) and h.client.calls == []
    assert h.panel.input.text() == ""


def test_the_bare_wake_word_from_the_windows_grammar_is_ignored(h):
    assert h.ctl.on_text("Ade", "windows") == "ignored"
    assert (h.woken, h.opened) == (0, 0)


def test_a_woken_question_is_asked(h):
    assert h.ctl.on_text("Ade, what brain are you on", "whisper") == "asked"
    assert h.client.calls == [("ask", "what brain are you on", [], [])]
    assert h.woken == 1


def test_a_woken_question_is_an_ask_even_with_the_shell_tab_open(h):
    h.panel.set_tab("shell")
    assert h.ctl.on_text("Ade, list the files here", "whisper") == "asked"
    assert h.verbs() == ["ask"]


def test_a_woken_ask_leaves_a_draft_alone(h):
    h.panel.input.setText("half a thought")
    h.ctl.on_text("Ade, what is the weather", "whisper")
    assert h.panel.input.text() == "half a thought"


@pytest.mark.parametrize("line", [
    "!git status", "/test run the suite", "/help", "/skill ade-debugging",
    "/upload", "?what is 2 plus 2", "git push --force", "clear the chat",
    "dir C:\\Users"])
def test_everything_but_a_plain_ask_is_staged(h, line):
    assert h.ctl.on_text(f"Ade, {line}", "whisper") == "staged"
    assert not (set(h.verbs()) & FORBIDDEN)
    assert h.verbs() == []
    assert h.panel.input.text() == line
    assert any(line in n for n in h.notes())


@pytest.mark.parametrize("word", ["yes", "Allow.", "deny it", "approve that", "ok", "go ahead"])
def test_a_spoken_decision_never_reaches_decide(h, word):
    h.watcher.appeared.emit({"id": "ap1", "tool": "run_shell", "args": {}})
    assert h.ctl.on_text(f"Ade, {word}", "whisper") == "staged"
    assert "decide" not in h.verbs() and h.verbs() == []
    assert "click-only" in h.notes()[-1]


def test_a_busy_panel_stages_rather_than_sends(h):
    h.panel.send("first question")
    assert h.ctl.on_text("Ade, second question", "whisper") == "staged"
    assert h.verbs() == ["ask"]
    assert h.panel.input.text() == "second question"


def test_a_staged_line_never_overwrites_a_draft(h):
    h.panel.input.setText("my draft")
    h.ctl.on_text("Ade, !rm -rf build", "whisper")
    assert h.panel.input.text() == "my draft"
    assert "draft in the box was kept" in h.notes()[-1]


def _wav_of(samples_b64):
    with wave.open(io.BytesIO(base64.b64decode(samples_b64))) as w:
        return w.getframerate(), w.getnframes()


def test_an_utterance_is_sent_as_16k_wav_and_the_answer_acted_on(qapp, tmp_path, pump):
    seen = []

    def listen(url, body, timeout):
        seen.append((url, _wav_of(body["audio"])))
        return {"text": "Ade, how are you", "engine": "whisper", "phrases": []}

    h = Harness(tmp_path, listen=listen)
    h.ctl.on_utterance({"samples": [0.1] * 44100, "rate": 44100})
    assert pump(lambda: bool(h.client.calls))
    assert seen == [("http://ade/v1/voice/listen", (16000, 16000))]
    assert h.verbs() == ["ask"]


def test_a_listen_failure_is_noted_once_per_kind(qapp, tmp_path, pump):
    h = Harness(tmp_path, listen=lambda *a: {
        "error": {"code": "voice_unavailable", "message": "no whisper"}, "status": 503})
    for _ in range(3):
        h.ctl.on_utterance({"samples": [0.1] * 1600, "rate": 16000})
        assert pump(lambda: not h.ctl._inflight)
    failures = [n for n in h.notes() if "voice_unavailable" in n]
    assert len(failures) == 1


def test_one_recognition_at_a_time_and_the_newest_waiting_wins(qapp, tmp_path, pump):
    import threading
    gate = threading.Event()
    heard = []

    def listen(url, body, timeout):
        n = _wav_of(body["audio"])[1]
        heard.append(n)
        gate.wait(5)
        return {"text": "", "engine": "whisper"}

    h = Harness(tmp_path, listen=listen)
    h.ctl.on_utterance({"samples": [0.1] * 1600, "rate": 16000})
    h.ctl.on_utterance({"samples": [0.1] * 3200, "rate": 16000})
    h.ctl.on_utterance({"samples": [0.1] * 4800, "rate": 16000})
    gate.set()
    assert pump(lambda: len(heard) == 2 and not h.ctl._inflight)
    assert heard == [1600, 4800]
