"""Approvals are polled independently of the busy gate. A new id appears
once; an id that leaves the pending list vanishes once; a poll that fails
changes NOTHING -- an unreachable Ade OS must not make every card read
'answered elsewhere'."""

from ade_desktop.conversation.approvals import ApprovalWatcher


def test_appeared_and_vanished_semantics(qapp, pump):
    a = {"id": "a", "tool": "write_file", "args": {}, "decided": False}
    b = {"id": "b", "tool": "run_shell", "args": {}, "decided": False}
    script = [{"approvals": [a]}, {"approvals": [a, b]}, {"approvals": [b]},
              {"error": "ConnectError: refused"}, {"approvals": []}]
    polls = []

    def fake_get(url, timeout):
        polls.append(url)
        return script[min(len(polls) - 1, len(script) - 1)]

    w = ApprovalWatcher("http://ade", get=fake_get, interval_ms=60_000)
    appeared, vanished = [], []
    w.appeared.connect(lambda x: appeared.append(x["id"]))
    w.vanished.connect(vanished.append)
    # After EACH poll, what has appeared / vanished so far. The error poll
    # (step 4) must change nothing: checking only the final lists passed
    # even when an error made b vanish early (falsified 2026-09-18).
    expected = [(["a"], []), (["a", "b"], []), (["a", "b"], ["a"]),
                (["a", "b"], ["a"]), (["a", "b"], ["a", "b"])]
    for step, want in enumerate(expected, 1):
        before = len(polls)
        w.poll_now()
        assert pump(lambda: len(polls) > before and w._inflight is None)
        pump(lambda: False, timeout=0.05)   # let the queued result land
        assert (appeared, vanished) == want, f"after poll {step}"
    w.stop()
    assert polls[0] == "http://ade/v1/approvals"


def test_stop_is_bounded_while_a_poll_hangs(qapp):
    """Review finding: stop() waited for the whole request timeout on a hung
    Ade OS; the spec says at most 2 s."""
    import time

    def hung(url, timeout):
        time.sleep(10)
        return {"approvals": []}

    w = ApprovalWatcher("http://ade", get=hung, interval_ms=60_000)
    w.poll_now()
    time.sleep(0.05)
    started = time.monotonic()
    w.stop()
    assert time.monotonic() - started < 2.5


def test_a_decided_row_is_not_pending(qapp, pump):
    def fake_get(url, timeout):
        return {"approvals": [{"id": "x", "decided": True}]}

    w = ApprovalWatcher("http://ade", get=fake_get, interval_ms=60_000)
    appeared = []
    w.appeared.connect(lambda x: appeared.append(x["id"]))
    w.poll_now()
    pump(lambda: False, timeout=0.3)
    w.stop()
    assert appeared == []
