"""The shared off-UI-thread call: results arrive on the UI thread, and the
worker never holds the client -- so dropping the client mid-call frees it
at once, on the UI thread, and the late result goes nowhere."""

import gc
import threading
import weakref

from ade_desktop.asyncclient import AsyncClient


def test_a_result_arrives_on_the_ui_thread(qapp, pump):
    client = AsyncClient()
    got = []
    client.done.connect(lambda rid, r: got.append((rid, r, threading.current_thread())))
    rid = client.call(lambda: {"ok": 1})
    assert pump(lambda: bool(got))
    assert got[0][:2] == (rid, {"ok": 1}) and got[0][2] is threading.main_thread()


def test_a_raise_or_a_non_dict_is_an_error_result(qapp, pump):
    client = AsyncClient()
    got = []
    client.done.connect(lambda rid, r: got.append(r))

    def boom():
        raise RuntimeError("down")

    client.call(boom)
    client.call(lambda: [1, 2])
    assert pump(lambda: len(got) == 2)
    assert {"error": "RuntimeError: down"} in got and {"error": "non-dict reply"} in got


def test_the_worker_never_holds_the_client(qapp, pump):
    gate = threading.Event()
    finished = threading.Event()

    def slow():
        gate.wait(5)
        finished.set()
        return {"late": True}

    client = AsyncClient()
    client.call(slow)
    ref = weakref.ref(client)
    gc.disable()
    try:
        del client
        assert ref() is None             # freed now, here, with the worker still running
    finally:
        gc.enable()
    gate.set()
    assert finished.wait(5)
    pump(lambda: False, timeout=0.2)     # the late result is delivered to nobody


def test_stop_means_no_more_results(qapp, pump):
    client = AsyncClient()
    got = []
    client.done.connect(lambda rid, r: got.append(r))
    gate = threading.Event()
    client.call(lambda: gate.wait(5) and {"late": True})
    client.stop()
    gate.set()
    pump(lambda: False, timeout=0.3)
    assert got == []
    client.call(lambda: {"never": 1})
    pump(lambda: False, timeout=0.2)
    assert got == []


# -- piece 7: streamed lines --------------------------------------------------------

def test_lines_arrive_in_order_on_the_ui_thread_before_done(qapp, pump):
    client = AsyncClient()
    got = []
    client.line.connect(lambda rid, t: got.append(("line", rid, t, threading.current_thread())))
    client.done.connect(lambda rid, r: got.append(("done", rid, r, threading.current_thread())))

    def work(emit):
        for n in range(50):
            emit(f"l{n}")
        return {"ok": True}

    rid = client.call_lines(work)
    assert pump(lambda: any(g[0] == "done" for g in got))
    assert [g[2] for g in got[:-1]] == [f"l{n}" for n in range(50)]
    assert got[-1][:3] == ("done", rid, {"ok": True})
    assert all(g[1] == rid and g[3] is threading.main_thread() for g in got)


def test_a_streaming_worker_never_holds_the_client(qapp, pump):
    gate = threading.Event()
    finished = threading.Event()

    def slow(emit):
        gate.wait(5)
        emit("late line")
        finished.set()
        return {"late": True}

    client = AsyncClient()
    client.call_lines(slow)
    ref = weakref.ref(client)
    gc.disable()
    try:
        del client
        assert ref() is None
    finally:
        gc.enable()
    gate.set()
    assert finished.wait(5)
    pump(lambda: False, timeout=0.2)


def test_stop_means_no_more_lines(qapp, pump):
    client = AsyncClient()
    got = []
    client.line.connect(lambda rid, t: got.append(t))
    gate = threading.Event()

    def work(emit):
        gate.wait(5)
        emit("after stop")
        return {}

    client.call_lines(work)
    client.stop()
    gate.set()
    pump(lambda: False, timeout=0.3)
    assert got == []
