"""The whole shell, end to end: a real ShellPane, a real ConPTY, a real
pwsh, and the text read back off the rendered screen.

The unit tests each prove one seam. This proves they are connected -- which
is the failure mode that survives a green unit suite, and the one Ray would
otherwise have to find by launching the app.

Slow (seconds) and Windows-only, like test_shell_pty.py.
"""

import sys
import time

import pytest
from PySide6.QtWidgets import QApplication

from ade_desktop.shell.pane import ShellPane

pytestmark = pytest.mark.skipif(sys.platform != "win32",
                                reason="ConPTY is Windows-only")


def _screen_text(view) -> str:
    return "\n".join("".join(c.text for c in row) for row in view.screen.rows())


def _await(view, needle: str, seconds: float = 30.0) -> str:
    """Drive the real event loop until `needle` is painted. Output crosses
    from the reader thread as a queued signal and is flushed on a 50 ms
    timer, so BOTH have to be pumped -- a plain sleep sees nothing.

    CAUTION, and this cost a debugging session: THE SHELL ECHOES WHAT YOU
    TYPE. A needle that appears in the command itself matches the echo
    immediately, so the wait returns before the command has run and the
    assertion reads an empty screen. Every needle below is ASSEMBLED by
    the shell -- `$(6*7)` becomes 42, `$PWD.Path` becomes a path -- so the
    literal cannot exist until the command has actually executed."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QApplication.processEvents()
        view.flush()
        if needle in _screen_text(view):
            break
        time.sleep(0.02)
    return _screen_text(view)


def test_a_command_typed_into_the_pane_shows_its_output(qapp):
    """The full path: keystrokes -> pty -> reader thread -> queued signal
    -> 50 ms flush -> pyte -> the rendered screen."""
    pane = ShellPane()
    try:
        pane.resize(900, 420)
        pane.show()
        qapp.processEvents()
        view = pane.current()
        assert view is not None
        _await(view, "PS ", seconds=30)         # the prompt arrived at all
        view.session.write("echo ADE_E2E_$(6*7)\r\n")
        text = _await(view, "ADE_E2E_42")
        assert "ADE_E2E_42" in text, text[-600:]
    finally:
        pane.stop_all()


def test_the_shell_opens_at_home_and_can_leave_it(qapp):
    """Requirement 2: a command line window that navigates the full
    computer. It starts at home and `cd C:\\` works from there."""
    pane = ShellPane()
    try:
        pane.resize(900, 420)
        pane.show()
        qapp.processEvents()
        view = pane.current()
        _await(view, "PS ", seconds=30)
        # The marker is ASSEMBLED by the shell, so the literal "HERE=" does
        # not exist in the echoed command line and the wait cannot end early.
        view.session.write("cd C:\\ ; echo ('HER' + 'E=' + $PWD.Path)\r\n")
        text = _await(view, "HERE=")
        assert "HERE=C:\\" in text, text[-600:]
    finally:
        pane.stop_all()


def test_two_sessions_have_separate_working_directories(qapp):
    """Requirement 7: the shells are independent, not two views of one."""
    pane = ShellPane()
    try:
        pane.resize(900, 420)
        pane.show()
        qapp.processEvents()
        first = pane.views[0]
        _await(first, "PS ", seconds=30)
        first.session.write("cd C:\\Windows ; echo ('ON' + 'E=' + $PWD.Path)\r\n")
        assert "ONE=C:\\Windows" in _await(first, "ONE=")

        second = pane.add_session()
        _await(second, "PS ", seconds=30)
        second.session.write("echo ('TW' + 'O=' + $PWD.Path)\r\n")
        text = _await(second, "TWO=")
        assert "TWO=" in text
        assert "TWO=C:\\Windows" not in text, "the second shell inherited the first's cwd"
    finally:
        pane.stop_all()
