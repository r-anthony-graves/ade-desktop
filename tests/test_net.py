"""The one door to Ade OS. get_json / post_json / post_file / stream_lines
never raise, and read a body whatever the status code: /v1/health answers
503 WITH a full body when tools are blocked, and a 409 on decide carries
the envelope the panel shows."""

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from ade_desktop.net import (get_json, get_text, post_bytes, post_file, post_json,
                             request_json, stream_lines)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 -- http.server's name
        if self.path == "/ok":
            self._send(200, "application/json", json.dumps({"status": "up"}))
        elif self.path == "/blocked":
            self._send(503, "application/json", json.dumps(
                {"status": "up", "may_execute_tools": False,
                 "blocking_reason": "memory down"}))
        elif self.path == "/html":
            self._send(200, "text/html", "<html>nope</html>")
        elif self.path == "/text":
            self._send(200, "text/plain; charset=utf-8", "plain text")
        elif self.path == "/cached":
            data = "fragment".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("X-QVM-Cached", "true")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif self.path == "/list":
            self._send(200, "application/json", "[1, 2]")
        else:
            self._send(404, "application/json",
                       json.dumps({"error": {"code": "not_found"}}))

    def do_PATCH(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        self._send(200, "application/json", json.dumps({"method": "PATCH", "body": body}))

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        if self.path == "/echo":
            self._send(200, "application/json", raw.decode())
        elif self.path == "/conflict":
            self._send(409, "application/json", json.dumps(
                {"error": {"code": "already_decided", "message": "x"}}))
        elif self.path == "/wav":
            self._send(200, "audio/wav", "RIFFxxxxWAVE")
        elif self.path == "/voice-down":
            self._send(503, "application/json", json.dumps(
                {"error": {"code": "voice_unavailable", "message": "no tts"}}))
        elif self.path == "/teapot":
            self._send(500, "text/plain", "boom")
        elif self.path == "/upload":
            self._send(200, "application/json", json.dumps({
                "has_bytes": b"HELLO-FILE" in raw,
                "has_relpath": b'name="relpath"' in raw and b"docs/a.txt" in raw,
                "filename": b'filename="a.txt"' in raw}))
        elif self.path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            self.wfile.write(b'{"type":"out","text":"a"}\n{"type":"out","te')
            self.wfile.flush()
            time.sleep(0.05)
            self.wfile.write(b'xt":"b"}\n{"type":"exit","code":0}\n')
            self.wfile.flush()
        else:
            self._send(404, "application/json", "{}")

    def _send(self, code, ctype, body):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def server():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _closed_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_a_200_json_body_is_returned(server):
    assert get_json(server + "/ok") == {"status": "up"}


def test_a_503_with_a_body_is_the_body_not_an_error(server):
    body = get_json(server + "/blocked")
    assert "error" not in body
    assert body["may_execute_tools"] is False
    assert body["blocking_reason"] == "memory down"


def test_a_non_json_body_is_an_error(server):
    assert get_json(server + "/html") == {"error": "HTTP 200: not JSON"}


def test_a_json_list_is_an_error(server):
    assert get_json(server + "/list") == {
        "error": "HTTP 200: not a JSON object"}


def test_a_refused_port_is_an_error_not_an_exception():
    body = get_json(f"http://127.0.0.1:{_closed_port()}/v1/health",
                    timeout=1.0)
    assert set(body) == {"error"}
    assert body["error"]


def test_post_json_round_trips(server):
    assert post_json(server + "/echo", {"a": [1, "b"]}, 5.0) == {"a": [1, "b"]}


def test_a_409_keeps_the_envelope_and_the_status(server):
    body = post_json(server + "/conflict", {}, 5.0)
    assert body == {"error": {"code": "already_decided", "message": "x"},
                    "status": 409}


def test_an_http_error_without_json_says_so(server):
    assert post_json(server + "/teapot", {}, 5.0) == {
        "error": "HTTP 500: not JSON", "status": 500}


def test_post_file_sends_the_bytes_and_the_fields(server, tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"HELLO-FILE")
    body = post_file(server + "/upload", f,
                     {"relpath": "docs/a.txt", "overwrite": "false"}, 5.0)
    assert body == {"has_bytes": True, "has_relpath": True, "filename": True}


def test_stream_lines_delivers_whole_lines_across_chunks(server):
    got = []
    result = stream_lines(server + "/stream", {"cmd": "x"}, got.append,
                          lambda: False)
    assert result == {"ok": True}
    assert [json.loads(line) for line in got] == [
        {"type": "out", "text": "a"}, {"type": "out", "text": "b"},
        {"type": "exit", "code": 0}]


def test_stream_lines_stops_when_asked(server):
    got = []
    result = stream_lines(server + "/stream", {}, got.append,
                          lambda: len(got) >= 1)
    assert result == {"ok": True, "stopped": True}
    assert len(got) == 1


def test_nothing_raises_on_a_refused_port(tmp_path):
    url = f"http://127.0.0.1:{_closed_port()}"
    f = tmp_path / "x"
    f.write_text("x")
    assert "error" in post_json(url + "/a", {}, 1.0)
    assert "error" in post_file(url + "/a", f, {}, 1.0)
    assert "error" in stream_lines(url + "/a", {}, lambda s: None, lambda: False)


def test_post_bytes_returns_the_raw_audio(server):
    assert post_bytes(server + "/wav", {"text": "hi"}, 5.0) == {"wav": b"RIFFxxxxWAVE"}


def test_post_bytes_keeps_an_error_envelope(server):
    assert post_bytes(server + "/voice-down", {}, 5.0) == {
        "error": {"code": "voice_unavailable", "message": "no tts"}, "status": 503}


def test_post_bytes_refuses_json_as_audio(server):
    body = post_bytes(server + "/echo", {"a": 1}, 5.0)
    assert body["error"] == "HTTP 200: JSON, not audio" and "wav" not in body


def test_post_bytes_unreachable_is_an_error():
    body = post_bytes(f"http://127.0.0.1:{_closed_port()}/v1/voice/speak", {}, 1.0)
    assert set(body) == {"error"}


def test_request_json_sends_any_method_with_a_body(server):
    assert request_json("PATCH", server + "/x", {"summary": None}, 5.0) == {
        "method": "PATCH", "body": {"summary": None}}


def test_get_text_says_when_the_text_is_the_index_copy(server):
    assert get_text(server + "/text") == {"text": "plain text", "cached": False}
    assert get_text(server + "/cached") == {"text": "fragment", "cached": True}


def test_get_text_keeps_the_error_envelope(server):
    assert get_text(server + "/nope")["status"] == 404
