"""The one door to Ade OS. Nothing here ever raises: unreachable is a STATE
the UI renders.

Named net.py, not http.py: an `http.py` would shadow the standard library's
`http` package if this directory were ever put on sys.path.

trust_env=False everywhere, as in the trader's services.py: a stray
HTTP(S)_PROXY in the launching shell must never route 127.0.0.1 through a
proxy and make Ade look down.
"""

from __future__ import annotations

import os

import httpx


def get_json(url: str, timeout: float = 3.0) -> dict:
    """The JSON object at `url`, whatever the status code -- or
    {"error": "..."}. /v1/health's 503 carries BLOCKED in its body."""
    try:
        with httpx.Client(trust_env=False, timeout=timeout) as client:
            response = client.get(url)
    except Exception as exc:  # noqa: BLE001 -- unreachable is a state
        return {"error": f"{type(exc).__name__}: {exc}"}
    try:
        body = response.json()
    except ValueError:
        return {"error": f"HTTP {response.status_code}: not JSON"}
    if not isinstance(body, dict):
        return {"error": f"HTTP {response.status_code}: not a JSON object"}
    return body


def _result(response) -> dict:
    """A POST's result. Below 400 the body is the result. From 400 up the
    status travels with it -- and an Ade error envelope ({"error": {code,
    message}}) is kept whole, because a 409 already_decided means something
    different from a 500."""
    try:
        body = response.json()
    except ValueError:
        body = None
    code = response.status_code
    if code >= 400:
        if isinstance(body, dict) and "error" in body:
            return {**body, "status": code}
        if isinstance(body, dict):
            return {"error": f"HTTP {code}", "detail": body, "status": code}
        return {"error": f"HTTP {code}: not JSON", "status": code}
    if body is None:
        return {"error": f"HTTP {code}: not JSON"}
    if not isinstance(body, dict):
        return {"error": f"HTTP {code}: not a JSON object"}
    return body


def post_json(url: str, body: dict, timeout: float) -> dict:
    try:
        with httpx.Client(trust_env=False, timeout=timeout) as client:
            return _result(client.post(url, json=body))
    except Exception as exc:  # noqa: BLE001 -- unreachable is a state
        return {"error": f"{type(exc).__name__}: {exc}"}


def request_json(method: str, url: str, body: dict | None = None,
                 timeout: float = 30.0) -> dict:
    """Any method with an optional JSON body; the result read as post_json
    reads it (from 400 up, the status travels with the error)."""
    try:
        with httpx.Client(trust_env=False, timeout=timeout) as client:
            if body is None:
                response = client.request(method, url)
            else:
                response = client.request(method, url, json=body)
            return _result(response)
    except Exception as exc:  # noqa: BLE001 -- unreachable is a state
        return {"error": f"{type(exc).__name__}: {exc}"}


def get_text(url: str, timeout: float = 30.0) -> dict:
    """A text body: {"text", "cached"} -- `cached` is True when Ade OS says
    the text is its QVM index copy (X-QVM-Cached), which is NOT the file and
    must never be saved back. From 400 up, the error envelope and status."""
    try:
        with httpx.Client(trust_env=False, timeout=timeout) as client:
            response = client.get(url)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}
    if response.status_code >= 400:
        return _result(response)
    cached = response.headers.get("x-qvm-cached", "").lower() == "true"
    return {"text": response.content.decode("utf-8", errors="replace"),
            "cached": cached}


def post_bytes(url: str, body: dict, timeout: float) -> dict:
    """POST JSON, expecting raw bytes back (/v1/voice/speak answers
    audio/wav, not base64): {"wav": bytes} -- or the usual error dict, the
    envelope kept whole, when the answer is an error or is JSON."""
    try:
        with httpx.Client(trust_env=False, timeout=timeout) as client:
            response = client.post(url, json=body)
    except Exception as exc:  # noqa: BLE001 -- unreachable is a state
        return {"error": f"{type(exc).__name__}: {exc}"}
    ctype = response.headers.get("content-type", "")
    if response.status_code < 400 and not ctype.startswith("application/json"):
        if not response.content:
            return {"error": f"HTTP {response.status_code}: empty body"}
        return {"wav": response.content}
    result = _result(response)
    if "error" not in result:
        return {"error": f"HTTP {response.status_code}: JSON, not audio",
                "detail": result}
    return result


def post_file(url: str, path, fields: dict, timeout: float) -> dict:
    """One file as multipart `file`, plus form `fields` (for /v1/upload:
    relpath and overwrite)."""
    try:
        with open(path, "rb") as handle, \
                httpx.Client(trust_env=False, timeout=timeout) as client:
            files = {"file": (os.path.basename(str(path)), handle)}
            return _result(client.post(url, files=files, data=dict(fields)))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def stream_lines(url: str, body: dict, on_line, should_stop) -> dict:
    """POST, then hand each response line to on_line(). NO read timeout: a
    long command must never die silently (the avatar pins the same for its
    terminal stream). should_stop() is checked between lines -- Stop in the
    panel sets it and also kills the session server-side."""
    timeout = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)
    try:
        with httpx.Client(trust_env=False, timeout=timeout) as client:
            with client.stream("POST", url, json=body) as response:
                if response.status_code >= 400:
                    response.read()
                    return _result(response)
                for line in response.iter_lines():
                    if should_stop():
                        return {"ok": True, "stopped": True}
                    if line.strip():
                        on_line(line)
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}
