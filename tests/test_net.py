"""get_json never raises, and reads a body whatever the status code:
/v1/health answers 503 WITH a full body when tools are blocked, and
treating that as unreachable would turn BLOCKED into DOWN."""

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from ade_desktop.net import get_json


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
        elif self.path == "/list":
            self._send(200, "application/json", "[1, 2]")
        else:
            self._send(404, "application/json",
                       json.dumps({"error": {"code": "not_found"}}))

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
