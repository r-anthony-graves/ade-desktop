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
        time.sleep(10)
        return {}

    c = ConversationClient("http://ade", post=slow)
    c.ask("q", [], [])
    time.sleep(0.05)
    started = time.monotonic()
    c.stop()
    assert time.monotonic() - started < 2.5
