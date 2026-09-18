"""Shared test setup. Offscreen Qt, like D:\\tradinglocal's own
tests/command_center/conftest.py.

NO __init__.py in this directory, and --import-mode=importlib in pytest.ini:
importing the trader puts D:\\tradinglocal on sys.path, and that repo owns
the top-level names `agent`, `engine` and `tests`.
"""

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def pump(qapp):
    """Process Qt events until predicate() is true or timeout passes.
    Results from worker threads arrive as queued signals, which only land
    while events are being processed."""

    def _pump(predicate, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            qapp.processEvents()
            if predicate():
                return True
            time.sleep(0.01)
        qapp.processEvents()
        return bool(predicate())

    return _pump


def _is_trader_module(name: str) -> bool:
    return name.split(".")[0] in ("agent", "engine")


@pytest.fixture
def isolated_trader_imports():
    """Each trader test imports from a root of its own choosing. Python
    caches modules by name, so without this a fake `agent` package from one
    test would answer the next test's import of the real one."""
    saved_path = list(sys.path)
    saved = {k: v for k, v in sys.modules.items() if _is_trader_module(k)}
    for key in saved:
        del sys.modules[key]
    yield
    for key in [k for k in sys.modules if _is_trader_module(k)]:
        del sys.modules[key]
    sys.modules.update(saved)
    sys.path[:] = saved_path


@pytest.fixture(autouse=True)
def _deferred_deletes_run_in_their_own_test(request):
    """Run each test's deleteLater()s at ITS teardown. Left queued, they ran
    at the next test that happened to pump events -- the orb's voice tests,
    last in the order -- and a crash in a deletion named the wrong test
    (2026-09-18: a SingleInstance socket deleted twice aborted the suite
    inside test_voice_controller)."""
    yield
    if "qapp" in request.fixturenames:
        from PySide6.QtCore import QCoreApplication, QEvent

        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)



@pytest.fixture(autouse=True)
def _fresh_filling_registry():
    """The "being written" registry is process-wide by design (one answer
    for the app); a test's unfinished flow must not leave marks for the
    next test to trip over."""
    yield
    from ade_desktop.workspace import filling as registry

    registry._FILLING = None
