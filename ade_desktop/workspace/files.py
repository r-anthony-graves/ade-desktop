"""The workspace through Ade OS: list a directory, read a file (from DISK),
write one, upload one. Ade OS's safe_path is the containment; this only
asks.

Every read sends source=disk. Without it, an indexed file comes back as the
QVM's RECONSTRUCTION (X-QVM-Cached: true) -- adeos/api/app.py was served as
354 bytes of 197,719 on 2026-09-18 -- and an editor that saved it would
replace the file with the fragment. An Ade OS older than 28a73959 ignores
the parameter; the `cached` flag still says so, and the editor refuses.
"""

from __future__ import annotations

from urllib.parse import urlencode

from ade_desktop.ade_status import ade_base
from ade_desktop.asyncclient import AsyncClient
from ade_desktop.net import get_json, get_text, post_file, request_json

TIMEOUTS = {"list": 20.0, "read": 60.0, "write": 60.0, "upload": 120.0}


def is_missing(result) -> bool:
    """Ade OS said there is nothing at that path. /v1/fs answers through
    get_json, which keeps the envelope but not the status -- measured live
    2026-09-18: {"error": {"code": "not_found", ...}} with no "status" --
    so the code is what says it, not a 404 the fakes had invented."""
    if not isinstance(result, dict) or "error" not in result:
        return False
    err = result["error"]
    return result.get("status") == 404 or (isinstance(err, dict)
                                           and err.get("code") == "not_found")


class FilesClient(AsyncClient):
    def __init__(self, base=None, *, get=get_json, text=get_text, request=request_json,
                 upload=post_file, parent=None) -> None:
        super().__init__(parent)
        self.base = (base or ade_base()).rstrip("/")
        self._get, self._text, self._request, self._upload = get, text, request, upload

    def list_dir(self, path: str) -> str:
        get, url = self._get, self.base + "/v1/fs?" + urlencode({"path": path})
        return self.call(lambda: get(url, TIMEOUTS["list"]))

    def read(self, path: str) -> str:
        text, url = self._text, self.base + "/v1/file?" + urlencode(
            {"path": path, "source": "disk"})
        return self.call(lambda: text(url, TIMEOUTS["read"]))

    def write(self, path: str, content: str) -> str:
        request, url = self._request, self.base + "/v1/file"
        body = {"path": path, "content": content}
        return self.call(lambda: request("PUT", url, body, TIMEOUTS["write"]))

    def upload(self, local_path: str, relpath: str = "") -> str:
        """Into <workspace>/uploads/; the reply's `name` is the
        workspace-relative path intake reads."""
        upload, url = self._upload, self.base + "/v1/upload"
        fields = {"overwrite": "true", "relpath": relpath}
        return self.call(lambda: upload(url, local_path, fields, TIMEOUTS["upload"]))
