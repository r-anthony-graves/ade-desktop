"""A second launch hands "show" to the running app and exits. The client
side runs in a SEPARATE process, as it does for real: a blocking connect in
the same thread as the server proves nothing about two processes."""

import subprocess
import sys
import time
import uuid
from pathlib import Path

from ade_desktop.single_instance import SingleInstance, instance_name

REPO = Path(__file__).resolve().parents[1]


def _unique() -> str:
    return f"ade-desktop-test-{uuid.uuid4().hex[:8]}"


def test_instance_name_is_per_user(monkeypatch):
    monkeypatch.setenv("USERNAME", "ray_g")
    assert instance_name() == "ade-desktop-ray_g"


def test_listen_alone_is_not_a_guard_on_windows(qapp):
    """Why the lock exists: measured in review on 2026-09-17, a second
    QLocalServer.listen() on a name already held returns True on Windows.
    Two launches that both miss notify_running() would both run."""
    name = _unique()
    first, second = SingleInstance(name), SingleInstance(name)
    try:
        assert first.listen()
        assert second.listen()  # if this ever fails, the lock is redundant
    finally:
        first.close()
        second.close()


def test_only_one_instance_holds_the_lock(qapp, tmp_path):
    name = _unique()
    first, second = SingleInstance(name), SingleInstance(name)
    assert first.acquire(tmp_path) is True
    assert second.acquire(tmp_path) is False
    first.release()
    assert second.acquire(tmp_path) is True
    second.release()


def test_nothing_listening_means_not_running(qapp):
    started = time.monotonic()
    assert SingleInstance(_unique()).notify_running(timeout_ms=500) is False
    assert time.monotonic() - started < 5


def test_a_second_process_hands_show_to_the_first(qapp, pump):
    name = _unique()
    first = SingleInstance(name)
    assert first.listen()
    shown = []
    first.show_requested.connect(lambda: shown.append(True))
    code = (
        "import os, sys; os.environ['QT_QPA_PLATFORM']='offscreen';"
        "from PySide6.QtCore import QCoreApplication;"
        "app = QCoreApplication([]);"
        "from ade_desktop.single_instance import SingleInstance;"
        f"sys.exit(0 if SingleInstance({name!r}).notify_running() else 3)"
    )
    proc = subprocess.Popen([sys.executable, "-c", code], cwd=str(REPO))
    try:
        assert pump(lambda: bool(shown) and proc.poll() is not None,
                    timeout=20)
    finally:
        if proc.poll() is None:
            proc.kill()
        first.close()
    assert proc.returncode == 0
    assert shown == [True]


def test_a_served_connection_does_not_keep_the_instance_alive(qapp, pump):
    """The socket's readyRead once held a lambda capturing the socket AND
    this object, so its deleteLater dropped the last reference mid-teardown
    and the server deleted the socket twice: a full-suite abort
    (2026-09-18). Served, closed and dropped, it must be freed at once."""
    import gc
    import weakref

    name = _unique()
    first = SingleInstance(name)
    assert first.listen()
    shown = []
    first.show_requested.connect(lambda: shown.append(True))
    code = (
        "import os, sys; os.environ['QT_QPA_PLATFORM']='offscreen';"
        "from PySide6.QtCore import QCoreApplication;"
        "app = QCoreApplication([]);"
        "from ade_desktop.single_instance import SingleInstance;"
        f"sys.exit(0 if SingleInstance({name!r}).notify_running() else 3)"
    )
    proc = subprocess.Popen([sys.executable, "-c", code], cwd=str(REPO))
    try:
        assert pump(lambda: bool(shown) and proc.poll() is not None, timeout=20)
    finally:
        if proc.poll() is None:
            proc.kill()
    first.close()
    ref = weakref.ref(first)
    gc.disable()
    try:
        del first
        assert ref() is None
    finally:
        gc.enable()
