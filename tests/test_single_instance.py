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
