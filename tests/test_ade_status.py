"""The header's words for Ade OS. Unreachable, blocked and degraded are three
different states and must never render as one another -- and a payload that
cannot say whether tools may run must not be read as "yes" or "no"."""

import threading

from ade_desktop.ade_status import (
    AdeStatusClient, ade_base, brain_name, health_pill, is_active, is_online,
)

UP = {"status": "up", "may_execute_tools": True, "blocking_reason": "",
      "subsystems": {
          "memory": {"up": True, "detail": "durable memory (PgVectorStore)"},
          "inference": {"up": True, "detail": "own brain reachable"}}}


def test_up():
    label, tone, tip = health_pill(UP)
    assert (label, tone) == ("UP", "ok")
    assert "durable memory" in tip and "own brain reachable" in tip


def test_unreachable_is_down():
    label, tone, tip = health_pill({"error": "ConnectError: refused"})
    assert (label, tone) == ("DOWN", "bad")
    assert tip == "unreachable: ConnectError: refused"


def test_an_answer_that_is_not_health_is_not_called_unreachable():
    label, _, tip = health_pill({"error": "HTTP 502: not JSON"})
    assert label == "DOWN"
    assert tip == "answered, but not with health: HTTP 502: not JSON"


def test_a_timeout_is_not_called_unreachable():
    label, _, tip = health_pill({"error": "ReadTimeout: timed out"})
    assert label == "DOWN"
    assert tip == "no answer in time: ReadTimeout: timed out"


def test_an_ade_error_envelope_is_down_and_says_so():
    label, tone, tip = health_pill({"error": {
        "code": "unavailable", "message": "no health probes registered"}})
    assert (label, tone) == ("DOWN", "bad")
    assert tip == "Ade OS error: unavailable - no health probes registered"


def test_the_503_blocked_body_is_blocked_not_down():
    label, tone, tip = health_pill({
        "status": "down", "may_execute_tools": False,
        "blocking_reason": "memory store unreachable", "subsystems": {}})
    assert (label, tone, tip) == ("BLOCKED", "bad", "memory store unreachable")


def test_blocked_without_a_reason_still_says_blocked():
    label, _, tip = health_pill({"status": "up", "may_execute_tools": False,
                                 "blocking_reason": ""})
    assert (label, tip) == ("BLOCKED", "tools blocked")


def test_down_but_tools_allowed_is_degraded():
    payload = {"status": "down", "may_execute_tools": True, "subsystems": {
        "memory": {"up": True, "detail": "ok"},
        "voice": {"up": False, "detail": "sidecar down"}}}
    assert health_pill(payload) == ("DEGRADED", "warn", "down: voice")


def test_a_missing_may_execute_tools_is_unknown_not_an_answer():
    label, tone, _ = health_pill({"status": "up"})
    assert (label, tone) == ("UNKNOWN", "off")


def test_garbage_is_unknown():
    assert health_pill(None)[0] == "UNKNOWN"
    assert health_pill({"status": "sideways", "may_execute_tools": True})[0] \
        == "UNKNOWN"


def test_brain_name_reads_resolved_brain():
    payload = {"resolved": {"brain": "own: deepseek-v4-flash-iq1",
                            "mode": "cloud"}}
    assert brain_name(payload) == "own: deepseek-v4-flash-iq1"


def test_brain_name_is_a_dash_when_it_cannot_tell():
    assert brain_name({"error": "refused"}) == "—"
    assert brain_name({"resolved": {"mode": "cloud"}}) == "—"
    assert brain_name(None) == "—"


def test_ade_base_default_and_override(monkeypatch):
    monkeypatch.delenv("ADE_DESKTOP_ADE_URL", raising=False)
    assert ade_base() == "http://127.0.0.1:8300"
    monkeypatch.setenv("ADE_DESKTOP_ADE_URL", "http://127.0.0.1:8301/")
    assert ade_base() == "http://127.0.0.1:8301"


def test_the_client_polls_both_endpoints_and_emits(qapp, pump):
    seen = {}

    def fetch(url):
        return {"url": url}

    client = AdeStatusClient("http://ade", fetch=fetch)
    client.health.connect(lambda p: seen.__setitem__("health", p))
    client.settings.connect(lambda p: seen.__setitem__("settings", p))
    client.start()
    try:
        assert pump(lambda: len(seen) == 2)
    finally:
        client.stop()
    assert seen["health"] == {"url": "http://ade/v1/health"}
    assert seen["settings"] == {"url": "http://ade/v1/settings"}


def test_a_fetch_that_raises_becomes_an_error_payload(qapp, pump):
    got = []

    def fetch(url):
        raise RuntimeError("boom")

    client = AdeStatusClient("http://ade", fetch=fetch)
    client.health.connect(got.append)
    client.poll_health()
    assert pump(lambda: bool(got))
    assert got[0] == {"error": "RuntimeError: boom"}


def test_stop_waits_for_a_poll_in_flight_and_polls_no_more(qapp):
    """At quit a worker still running would emit on an object the main
    thread is tearing down. stop() returns only once it has finished."""
    import time

    finished = []
    calls = []

    def fetch(url):
        calls.append(url)
        time.sleep(0.3)
        finished.append(True)
        return {"ok": True}

    client = AdeStatusClient("http://ade", fetch=fetch)
    client.poll_health()
    time.sleep(0.05)  # the worker is inside fetch now
    client.stop()
    assert finished == [True]
    client.poll_health()
    client.poll_settings()
    time.sleep(0.1)
    assert calls == ["http://ade/v1/health"]


def test_a_slow_poll_is_not_stacked(qapp, pump):
    release = threading.Event()
    calls = []
    got = []

    def fetch(url):
        calls.append(url)
        release.wait(5)
        return {"ok": True}

    client = AdeStatusClient("http://ade", fetch=fetch)
    client.health.connect(got.append)
    client.poll_health()
    client.poll_health()
    client.poll_health()
    release.set()
    assert pump(lambda: bool(got))
    assert calls == ["http://ade/v1/health"]


def test_the_client_also_polls_activity(qapp, pump):
    got = []
    client = AdeStatusClient("http://ade", fetch=lambda url: {"url": url})
    client.activity.connect(got.append)
    client.start()
    try:
        assert pump(lambda: bool(got))
    finally:
        client.stop()
    assert got[0] == {"url": "http://ade/v1/activity"}


def test_activity_reads_active_or_a_count_and_an_error_is_not_idle():
    assert is_active({"active": False, "count": 0, "topics": []}) is False
    assert is_active({"active": True, "count": 0}) is True
    assert is_active({"active": False, "count": 2}) is True
    assert is_active({"error": "ConnectError"}) is None
    assert is_active({}) is None
    assert is_active("nope") is None


def test_online_is_reachable_not_healthy():
    assert is_online(UP) is True
    assert is_online({"status": "down", "may_execute_tools": False,
                      "blocking_reason": "x"}) is True
    assert is_online({"error": "ConnectError: refused"}) is False
    assert is_online("garbage") is False


def test_a_dropped_status_client_is_freed_at_once(qapp):
    """The poller is the app's only cross-thread emitter: three QTimers on the
    GUI thread, a ThreadPoolExecutor, and `signal.emit(...)` called from a
    worker. If a dropped one is cyclic garbage, the collector frees it -- and
    its pool, and its timers -- at a moment of its choosing, possibly while a
    worker is mid-emit. That is the shape that crashed the trader's suite 6 of
    6 on 2026-09-17.

    `gc.disable()` is the test: with the collector running a cycle is freed
    eventually and the weakref looks fine.
    """
    import gc
    import weakref

    from ade_desktop.ade_status import AdeStatusClient

    gc.collect()
    gc.disable()
    try:
        client = AdeStatusClient(base="http://127.0.0.1:1",
                                 fetch=lambda url: {"status": "up"})
        client.poll_health()
        client.stop()
        ref = weakref.ref(client)
        del client
        assert ref() is None, "the status client survived its last reference"
    finally:
        gc.enable()
