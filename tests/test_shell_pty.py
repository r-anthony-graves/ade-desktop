"""The pty, against a REAL pwsh.

These are slow (seconds) and Windows-only on purpose: a mocked pty proves
nothing about ConPTY, and ConPTY is the entire point of requirements 2, 4
and 5.
"""

import os
import subprocess
import sys
import time

import pytest
from PySide6.QtWidgets import QApplication

from ade_desktop.shell.pty import PtySession, default_cwd, shell_command

pytestmark = pytest.mark.skipif(sys.platform != "win32",
                                reason="ConPTY is Windows-only")


def _pump(session, needle, seconds=25):
    """Drain the pty until `needle` shows up. Output crosses from the reader
    thread as a queued signal, so it only lands while events are processed."""
    seen = []
    session.output.connect(seen.append)
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if needle in "".join(seen):
            break
        time.sleep(0.02)
    QApplication.processEvents()
    return "".join(seen)


def test_the_spawn_contract_drops_every_flag_that_cost_a_requirement():
    """Ade OS's shell runs with -NoProfile -NonInteractive -NoLogo
    -ExecutionPolicy Bypass -Command -, and each of those removes something
    Ray asked for: -NoProfile costs the modules (req 9), -NonInteractive
    costs prompts and PSReadLine (req 2), and Bypass is WIDER than this
    machine's real policy (req 5).

    Falsify by re-adding any one of them."""
    cmd = shell_command()
    assert "-NoProfile" not in cmd
    assert "-NonInteractive" not in cmd
    assert "-ExecutionPolicy" not in cmd
    assert "-Command" not in cmd
    assert cmd.split()[0] in ("pwsh.exe", "powershell.exe")


def test_it_opens_at_home_not_in_the_repo():
    """Requirement 2: navigate the full computer. A shell that opens in the
    checkout is a project tool, not a terminal."""
    assert default_cwd() == (os.environ.get("USERPROFILE")
                             or os.path.expanduser("~"))


def test_a_command_round_trips(qapp):
    session = PtySession()
    session.start(cols=100, rows=24)
    try:
        session.write("echo ADE_MARKER_$(2+2)\r\n")
        assert "ADE_MARKER_4" in _pump(session, "ADE_MARKER_4")
    finally:
        session.stop()


def test_the_environment_is_inherited(qapp):
    """Requirement 4, and the whole reason this is local rather than an Ade
    OS call: Ade OS is started through WMI Win32_Process.Create, through
    which environment does not propagate. Set a variable in THIS process and
    read it back inside the shell.

    Falsify by passing env={} to spawn()."""
    os.environ["ADE_ENV_PROBE"] = "propagated"
    session = PtySession()
    session.start()
    try:
        session.write("echo PROBE=$env:ADE_ENV_PROBE\r\n")
        assert "PROBE=propagated" in _pump(session, "PROBE=propagated")
    finally:
        session.stop()
        os.environ.pop("ADE_ENV_PROBE", None)


def test_no_tab_no_shell(qapp):
    """THE INVARIANT THAT MUST NEVER REGRESS. An orphaned pwsh holding a
    directory open, with nothing on screen to notice it by, is exactly the
    failure adeos/api/term.py names.

    Falsify by deleting stop()'s terminate() call."""
    session = PtySession()
    session.start()
    pid = session.pid
    assert pid and session.is_alive()
    session.stop()
    time.sleep(1.5)
    assert not session.is_alive()
    listed = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                            capture_output=True, text=True).stdout
    assert str(pid) not in listed, f"pid {pid} survived stop()"


def test_stop_is_idempotent(qapp):
    """Quit calls stop() after a tab close already did."""
    session = PtySession()
    session.start()
    session.stop()
    session.stop()
    assert not session.is_alive()


def test_stop_before_start_does_not_raise(qapp):
    PtySession().stop()


def test_writing_to_a_dead_pty_is_survivable(qapp):
    """The shell can exit on its own (`exit`), and a keystroke arriving
    after that must not take the window down with it."""
    session = PtySession()
    session.start()
    session.stop()
    session.write("echo still here\r\n")        # must not raise
