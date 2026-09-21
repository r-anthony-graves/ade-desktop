"""The Path's JSON face (`/api/...` on `thepath serve`, 127.0.0.1:8412),
off the UI thread. The Path is Ray's separate project; this reaches it as
a browser does, over loopback HTTP, and owns none of its rules.

Ray's token -- printed once when HE starts `thepath serve` -- is held here
only after he pastes it: in memory, for this session, never written to
disk, never logged, never sent to Ade OS. It travels in the X-Path-Token
header on exactly the two verbs that are his (setting the stage,
confirming a teaching) and on nothing else. The app never starts the
server: that would print the token into a process the app owns.
"""

from __future__ import annotations

import os
from urllib.parse import quote

from ade_desktop.asyncclient import AsyncClient
from ade_desktop.net import request_json

DEFAULT_URL = "http://127.0.0.1:8412"
TOKEN_HEADER = "X-Path-Token"
GATED = ("set_stage", "confirm", "mark_criteria")


def path_base() -> str:
    """ADE_DESKTOP_PATH_URL, or The Path's own default port."""
    return (os.environ.get("ADE_DESKTOP_PATH_URL") or DEFAULT_URL).rstrip("/")


class PathClient(AsyncClient):
    def __init__(self, base=None, *, request=request_json, parent=None) -> None:
        super().__init__(parent)
        self.base = (base or path_base()).rstrip("/")
        self._request = request
        self._token = ""

    # -- the token: memory only ---------------------------------------------------

    def set_token(self, token: str) -> bool:
        """False (and nothing held) for text that cannot be a token: The
        Path prints hex, and a non-ASCII header cannot even be sent."""
        token = (token or "").strip()
        if not token or not token.isascii() or not token.isprintable():
            return False
        self._token = token
        return True

    def forget_token(self) -> None:
        self._token = ""

    def has_token(self) -> bool:
        return bool(self._token)

    def __repr__(self) -> str:                  # never the token, in any trace
        return f"<PathClient {self.base} token={'held' if self._token else 'none'}>"

    # -- plumbing -------------------------------------------------------------------

    def _read(self, path: str) -> str:
        # request_json, not get_json: a refusal keeps its status, so "The
        # Path answered with an error" is never mistaken for "not running"
        # (review, 2026-09-18).
        request, url = self._request, self.base + path
        return self.call(lambda: request("GET", url, None, 15.0))

    def _post(self, path: str, body: dict, gated: bool = False) -> str:
        request, url = self._request, self.base + path
        headers = {TOKEN_HEADER: self._token} if gated and self._token else None
        return self.call(lambda: request("POST", url, body, 60.0, headers=headers))

    # -- pages ----------------------------------------------------------------------

    def today(self) -> str: return self._read("/api/today")
    def read_entries(self) -> str: return self._read("/api/read")
    def diary(self) -> str: return self._read("/api/diary")
    def stage(self) -> str: return self._read("/api/stage")
    def study(self) -> str: return self._read("/api/study")
    def catalogue(self) -> str: return self._read("/api/catalogue")

    def teaching(self, teaching_id: str) -> str:
        return self._read("/api/teaching/" + quote(teaching_id, safe=""))

    # -- actions (ungated, as in the CLI) -----------------------------------------

    def write_entry(self, body: str, kind: str = "") -> str:
        return self._post("/api/entry", {"body": body, "kind": kind})

    def write_diary(self, body: str, kind: str = "") -> str:
        return self._post("/api/diary", {"body": body, "kind": kind})

    def offer(self) -> str:
        return self._post("/api/offer", {})

    def record_prompt(self, text: str, citation_id: str, stage: str, occasion: str) -> str:
        return self._post("/api/prompt", {"text": text, "citation_id": citation_id,
                                          "stage": stage, "occasion": occasion})

    def draft_teaching(self, title: str, subject: str) -> str:
        return self._post("/api/teaching", {"title": title, "subject": subject})

    def add_claim(self, teaching_id: str, category: str, body: str,
                  cites: list[str], drawn_from: list[str]) -> str:
        return self._post("/api/teaching/%s/claim" % quote(teaching_id, safe=""),
                          {"category": category, "body": body, "cites": list(cites),
                           "drawn_from": list(drawn_from)})

    # -- the two that are Ray's (gated) ------------------------------------------

    def set_stage(self, stage: str) -> str:
        return self._post("/api/stage", {"stage": stage}, gated=True)

    def confirm(self, teaching_id: str) -> str:
        return self._post("/api/teaching/%s/confirm" % quote(teaching_id, safe=""), {},
                          gated=True)

    # -- the day (Read, Refract, Reflect) --------------------------------------------

    def day(self) -> str: return self._read("/api/day")

    def reflect(self, step: int, body: str) -> str:
        """`body` exactly as typed: The Path stores it verbatim."""
        return self._post("/api/day/reflect", {"step": str(step), "body": body})

    def mark_criteria(self, charter_id: str, goal: str, claims: list[str]) -> str:
        return self._post("/api/charter/criteria",
                          {"charter_id": charter_id, "goal": goal,
                           "claims": list(claims)}, gated=True)
