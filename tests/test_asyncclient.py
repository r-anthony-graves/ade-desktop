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
