"""Every /v1/pm/* route, off the UI thread (AsyncClient). Nothing here
decides anything: Ade OS validates the states, the actions and the paths,
and its answer -- the record as it now stands, or the error -- is what the
panel shows."""

from __future__ import annotations

from urllib.parse import quote

from ade_desktop.ade_status import ade_base
from ade_desktop.asyncclient import AsyncClient
from ade_desktop.net import get_json, request_json

# Intake writes 16 files; authoring is one brain call on the local deep
# tier -- minutes each, 15 as the budget before it is called failed.
TIMEOUTS = {"read": 30.0, "write": 30.0, "findings": 60.0, "intake": 120.0,
            "author": 900.0}


class PmClient(AsyncClient):
    def __init__(self, base=None, *, get=get_json, request=request_json,
                 parent=None) -> None:
        super().__init__(parent)
        self.base = (base or ade_base()).rstrip("/")
        self._get, self._request = get, request

    def _read(self, path, timeout=TIMEOUTS["read"]) -> str:
        get, url = self._get, self.base + path
        return self.call(lambda: get(url, timeout))

    def _send(self, method, path, body=None, timeout=TIMEOUTS["write"]) -> str:
        request, url = self._request, self.base + path
        return self.call(lambda: request(method, url, body, timeout))

    # -- projects ------------------------------------------------------------
    def projects(self) -> str:
        return self._read("/v1/pm/projects")

    def set_status(self, project_id: int, status: str) -> str:
        return self._send("POST", f"/v1/pm/projects/{int(project_id)}/status",
                          {"status": status})

    def intake(self, name: str, source: str) -> str:
        return self._send("POST", "/v1/pm/intake", {"name": name, "source": source},
                          TIMEOUTS["intake"])

    def author(self, package: str, slug: str, doc: str, source: str, name: str,
               notes: str = "") -> str:
        return self._send("POST", "/v1/pm/author", {
            "package": package, "slug": slug, "doc": doc, "source": source,
            "name": name, "notes": notes}, TIMEOUTS["author"])

    # -- backlog -------------------------------------------------------------
    def backlog(self) -> str:
        return self._read("/v1/pm/backlog")

    def add_backlog(self, title: str, detail: str, project: str) -> str:
        return self._send("POST", "/v1/pm/backlog",
                          {"title": title, "detail": detail, "project": project})

    def backlog_action(self, item_id: int, action: str) -> str:
        return self._send("POST", f"/v1/pm/backlog/{int(item_id)}/{quote(action)}")

    def reopen(self, item_id: int) -> str:
        return self._send("POST", f"/v1/pm/backlog/{int(item_id)}/reopen")

    # -- risks ---------------------------------------------------------------
    def risks(self) -> str:
        return self._read("/v1/pm/risks")

    def add_risk(self, title: str, project: str, probability: str, impact: str,
                 response: str = "") -> str:
        return self._send("POST", "/v1/pm/risks", {
            "title": title, "project": project, "probability": probability,
            "impact": impact, "response": response})

    def risk_response(self, risk_id: int, response: str) -> str:
        return self._send("POST", f"/v1/pm/risks/{int(risk_id)}/response",
                          {"response": response})

    # -- monitoring ----------------------------------------------------------
    def findings(self) -> str:
        return self._read("/v1/pm/findings", TIMEOUTS["findings"])
