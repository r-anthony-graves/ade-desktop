"""Every /v1 call the panel makes, off the UI thread, with results as
queued signals. The network is replaced by fake callables."""

import threading
import time
from pathlib import Path

from ade_desktop.conversation.client import TOPIC, ConversationClient
from ade_desktop.conversation.uploads import UploadFile


class Recorder:
    def __init__(self, reply=None):
        self.calls = []
        self.reply = reply if reply is not None else {"ok": True}

    def post(self, url, body, timeout):
        self.calls.append(("post", url, body, timeout))
        return self.reply

    def get(self, url, timeout):
        self.calls.append(("get", url, timeout))
        return self.reply


def _client(rec, **kw):
    return ConversationClient("http://ade", post=rec.post, get=rec.get, **kw)


def _collect(client):
    done, lines = {}, []
    client.done.connect(lambda rid, res: done.__setitem__(rid, res))
    client.line.connect(lambda rid, text: lines.append((rid, text)))
    return done, lines


def test_ask_task_chat_shell_bodies(qapp, pump):
    rec = Recorder()
    c = _client(rec)
    done, _ = _collect(c)
    ids = [c.ask("q", ["s"], [{"role": "user", "content": "x"}]),
           c.task("fix", "coding", ["s"]), c.chat("hi"), c.shell("dir")]
    assert pump(lambda: all(i in done for i in ids))
    by_url = {call[1]: call for call in rec.calls}
    assert by_url["http://ade/v1/ask"][2] == {
        "question": "q", "skills": ["s"],
        "history": [{"role": "user", "content": "x"}]}
    assert by_url["http://ade/v1/ask"][3] == 2700
    assert by_url["http://ade/v1/tasks"][2] == {
        "description": "fix", "task_type": "coding", "topic": TOPIC,
        "skills": ["s"]}
    assert TOPIC == "u/local/desktop"
    assert by_url["http://ade/v1/tasks"][3] == 1200
    assert by_url["http://ade/v1/chat/completions"][2] == {
        "messages": [{"role": "user", "content": "hi"}], "stream": False}
    assert by_url["http://ade/v1/terminal"][2] == {"cmd": "dir"}
    assert by_url["http://ade/v1/terminal"][3] == 300


def test_decide_is_attributed_to_a_human(qapp, pump):
    rec = Recorder()
    c = _client(rec)
    done, _ = _collect(c)
    rid = c.decide("a1", True)
    assert pump(lambda: rid in done)
    assert rec.calls[0][1] == "http://ade/v1/approvals/a1/decide"
    assert rec.calls[0][2] == {"allow": True,
                               "reason": "allowed from the desktop app",
                               "decided_by": "human"}


def test_run_streams_lines_then_done(qapp, pump):
    seen = {}

    def fake_stream(url, body, on_line, should_stop):
        seen["url"], seen["body"] = url, body
        on_line('{"type":"out","text":"a"}')
        on_line('{"type":"exit","code":0}')
        return {"ok": True}

    c = ConversationClient("http://ade", stream=fake_stream)
    done, lines = _collect(c)
    rid = c.run("git status")
    assert pump(lambda: rid in done)
    assert seen["url"] == "http://ade/v1/terminal/run"
    assert seen["body"] == {"session": "ade-desktop", "cmd": "git status"}
    assert [text for r, text in lines if r == rid] == [
        '{"type":"out","text":"a"}', '{"type":"exit","code":0}']
    assert done[rid] == {"ok": True}


def test_stop_stream_reaches_the_running_stream(qapp, pump):
    started = threading.Event()

    def fake_stream(url, body, on_line, should_stop):
        started.set()
        deadline = time.monotonic() + 5
        while not should_stop() and time.monotonic() < deadline:
            time.sleep(0.01)
        return {"ok": True, "stopped": should_stop()}

    c = ConversationClient("http://ade", stream=fake_stream)
    done, _ = _collect(c)
    rid = c.run("ping -t 1.1.1.1")
    assert started.wait(2)
    c.stop_stream()
    assert pump(lambda: rid in done)
    assert done[rid] == {"ok": True, "stopped": True}


def test_a_raising_fake_becomes_an_error_result(qapp, pump):
    def boom(url, body, timeout):
        raise RuntimeError("nope")

    c = ConversationClient("http://ade", post=boom)
    done, _ = _collect(c)
    rid = c.ask("q", [], [])
    assert pump(lambda: rid in done)
    assert done[rid] == {"error": "RuntimeError: nope"}


def test_upload_reports_sent_and_failed(qapp, pump, tmp_path):
    def fake_upload(url, path, fields, timeout):
        if Path(path).name == "b.txt":
            return {"error": {"code": "exists", "message": "already there"},
                    "status": 409}
        return {"ok": True}

    files = [UploadFile(tmp_path / "a.txt", "a.txt", 10),
             UploadFile(tmp_path / "b.txt", "b.txt", 20)]
    c = ConversationClient("http://ade", upload=fake_upload)
    done, _ = _collect(c)
    rid = c.upload(files, overwrite=False)
    assert pump(lambda: rid in done)
    assert done[rid] == {"sent": 1, "bytes": 10,
                         "failed": [["b.txt", "already there"]]}


def test_stop_returns_quickly_while_a_call_is_in_flight(qapp):
    def slow(url, body, timeout):
        time.sleep(3)
        return {}

    c = ConversationClient("http://ade", post=slow)
    c.ask("q", [], [])
    time.sleep(0.05)
    started = time.monotonic()
    c.stop()
    assert time.monotonic() - started < 2.5


def test_quitting_mid_turn_does_not_keep_the_process_alive(tmp_path):
    """Review finding: stop() returned in 2 s, but Python still waited for
    the executor's worker at exit -- up to 45 min for an ask, forever for a
    silent stream. Measured before the fix: 8.4 s for an 8 s fake call."""
    import subprocess
    import sys
    from pathlib import Path

    code = (
        "import os, time; os.environ['QT_QPA_PLATFORM']='offscreen'\n"
        "from PySide6.QtCore import QCoreApplication\n"
        "app = QCoreApplication([])\n"
        "from ade_desktop.conversation.client import ConversationClient\n"
        "def slow(url, body, timeout):\n"
        "    time.sleep(20)\n"
        "    return {}\n"
        "c = ConversationClient('http://ade', post=slow)\n"
        "c.ask('q', [], [])\n"
        "time.sleep(0.1)\n"
        "c.stop()\n"
    )
    repo = Path(__file__).resolve().parents[1]
    started = time.monotonic()
    proc = subprocess.run([sys.executable, "-c", code], cwd=str(repo),
                          capture_output=True, text=True, timeout=60)
    took = time.monotonic() - started
    assert proc.returncode == 0, proc.stderr
    assert took < 10, f"the process waited {took:.1f}s for an abandoned call"


def test_a_client_dropped_mid_call_is_freed_on_the_main_thread(qapp, pump):
    """No Qt object may be destroyed on a worker thread (the piece-1 lesson).
    A worker that held the client strongly became its last owner."""
    import threading

    release = threading.Event()

    def slow(url, body, timeout):
        release.wait(5)
        return {"ok": True}

    freed_on = []
    c = ConversationClient("http://ade", post=slow)
    c.destroyed.connect(lambda *_: freed_on.append(threading.current_thread().name))
    c.ask("q", [], [])
    time.sleep(0.05)
    del c
    assert freed_on == ["MainThread"]
    release.set()
    pump(lambda: False, timeout=0.3)    # the worker ends quietly, no emit


# -- a chat per section, and Cancel (Ray, 2026-09-18) --------------------------

def test_a_session_client_carries_its_own_topic_and_terminal_session(qapp, pump):
    rec = Recorder()
    seen = []

    def fake_stream(url, body, on_line, should_stop):
        seen.append(body)
        return {"ok": True}

    c = ConversationClient("http://ade", post=rec.post, get=rec.get, stream=fake_stream,
                           topic="u/local/desktop-pm", session="ade-desktop-chat-pm")
    done, _ = _collect(c)
    ids = [c.task("fix", "coding", []), c.run("dir"), c.kill()]
    assert pump(lambda: all(i in done for i in ids))
    by_url = {call[1]: call for call in rec.calls}
    assert by_url["http://ade/v1/tasks"][2]["topic"] == "u/local/desktop-pm"
    assert seen == [{"session": "ade-desktop-chat-pm", "cmd": "dir"}]
    assert by_url["http://ade/v1/terminal/kill"][2] == {"session": "ade-desktop-chat-pm"}


def test_a_turn_id_travels_with_an_ask_and_a_task(qapp, pump):
    rec = Recorder()
    c = _client(rec)
    done, _ = _collect(c)
    ids = [c.ask("q", [], [], turn_id="t-ask"), c.task("fix", "coding", [], turn_id="t-task")]
    assert pump(lambda: all(i in done for i in ids))
    by_url = {call[1]: call for call in rec.calls}
    assert by_url["http://ade/v1/ask"][2]["turn_id"] == "t-ask"
    assert by_url["http://ade/v1/tasks"][2]["turn_id"] == "t-task"


def test_cancel_asks_ade_os_to_stop_that_turn(qapp, pump):
    rec = Recorder()
    c = _client(rec)
    done, _ = _collect(c)
    rid = c.cancel("t-1/../x")
    assert pump(lambda: rid in done)
    assert rec.calls[0][:3] == ("post", "http://ade/v1/tasks/t-1%2F..%2Fx/cancel", {})
