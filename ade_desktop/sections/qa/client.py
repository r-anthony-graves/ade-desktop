"""QA's own calls: what the qa primary takes, dispatching one of its task
types, Ade's activity, and the project list (for the header's status)."""

from __future__ import annotations

from ade_desktop.ade_status import ade_base
from ade_desktop.asyncclient import AsyncClient
from ade_desktop.net import get_json, request_json

TOPIC = "qa"               # the web desk's topic for QA dispatch
TASK_TIMEOUT = 1200.0      # the avatar's /v1/tasks budget: turns take minutes


class QaClient(AsyncClient):
    def __init__(self, base=None, *, get=get_json, request=request_json, parent=None) -> None:
        super().__init__(parent)
        self.base = (base or ade_base()).rstrip("/")
        self._get, self._request = get, request

    def _read(self, path, timeout=20.0) -> str:
        get, url = self._get, self.base + path
        return self.call(lambda: get(url, timeout))

    def agents(self) -> str:
        return self._read("/v1/agents")

    def activity(self) -> str:
        return self._read("/v1/activity", 5.0)

    def projects(self) -> str:
        return self._read("/v1/pm/projects")

    def dispatch(self, task_type: str, description: str) -> str:
        request, url = self._request, self.base + "/v1/tasks"
        body = {"task_type": task_type, "description": description, "topic": TOPIC}
        return self.call(lambda: request("POST", url, body, TASK_TIMEOUT))
