"""Asking Ade for the day's mirror: one /v1/tasks turn to the companion, the
way QA dispatches to qa. The app executes nothing itself; Ade writes the
mirror through The Path's CLI under the-path-mirror skill."""

from __future__ import annotations

from ade_desktop.ade_status import ade_base
from ade_desktop.asyncclient import AsyncClient
from ade_desktop.net import request_json

TASK_TIMEOUT = 1200.0      # a deep-brain turn takes minutes


def mirror_body(day_id: str) -> dict:
    return {"task_type": "oracle", "agent": "companion", "topic": "u/local/thepath",
            "description": (f"Write the mirror for The Path's day {day_id}. Follow "
                            "the the-path-mirror skill exactly. If the packet is "
                            "refused, say so and write nothing.")}


class MirrorClient(AsyncClient):
    def __init__(self, base=None, *, request=request_json, parent=None) -> None:
        super().__init__(parent)
        self.base = (base or ade_base()).rstrip("/")
        self._request = request

    def ask(self, day_id: str) -> str:
        request, url, body = self._request, self.base + "/v1/tasks", mirror_body(day_id)
        return self.call(lambda: request("POST", url, body, TASK_TIMEOUT))
