"""One GET, never an exception. Unreachable is a STATE the UI renders.

Named net.py, not http.py: an `http.py` would shadow the standard library's
`http` package if this directory were ever put on sys.path.
"""

from __future__ import annotations

import httpx


def get_json(url: str, timeout: float = 3.0) -> dict:
    """The JSON object at `url`, whatever the status code -- or
    {"error": "..."}.

    trust_env=False, as in the trader's services.py: a stray HTTP(S)_PROXY
    in the launching shell must never route 127.0.0.1 through a proxy and
    make Ade look down.
    """
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
