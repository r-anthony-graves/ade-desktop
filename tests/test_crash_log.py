"""A native crash must leave a Python traceback behind.

Measured 2026-09-22/23: the app died five times in two days with
`0xc0000005` (access violation) inside `python314.dll`, and left **nothing** a
person could act on. Windows recorded a fault offset; the app's own
`desktop.log` recorded the last ordinary INFO line and then stopped mid-air.

There is no console to print to -- `run-desktop.ps1` launches `pythonw.exe`
deliberately, so the app has no stderr anywhere a human will ever read it --
and `faulthandler` is off by default. So the one artefact that names the
faulting Python line did not exist.

The suite does not reproduce the crash (600 tests pass), so there is nothing
to bisect. Until a crash names its line, any "fix" is a guess. This is the
thing that makes the next one diagnosable.

`faulthandler.enable(file=...)` keeps the fd open for the process's life and
writes the traceback of every thread from the signal handler itself, so it
survives the kind of death that leaves no other trace.
"""

from __future__ import annotations

import faulthandler

from ade_desktop.__main__ import crash_log_path, setup_crash_log


def test_a_crash_log_is_opened_next_to_the_desktop_log(tmp_path):
    handle = setup_crash_log(tmp_path)
    try:
        assert crash_log_path(tmp_path).exists()
        assert crash_log_path(tmp_path).parent == tmp_path
    finally:
        if handle is not None:
            faulthandler.disable()
            handle.close()


def test_faulthandler_is_actually_enabled(tmp_path):
    """The point is not that a file exists. `faulthandler.is_enabled()` is
    what decides whether an access violation writes a traceback or vanishes.

    It must be DISABLED first, and that is the whole test. pytest enables
    faulthandler itself through its own plugin, so the obvious version of this
    -- call setup, assert is_enabled -- passes with `faulthandler.enable()`
    deleted from the app entirely. Verified: it did.
    """
    faulthandler.disable()
    assert not faulthandler.is_enabled(), "precondition: nothing else enabled it"

    handle = setup_crash_log(tmp_path)
    try:
        assert faulthandler.is_enabled(), \
            "setup_crash_log did not enable faulthandler"
    finally:
        if handle is not None:
            faulthandler.disable()
            handle.close()
        # Give pytest's own crash handling back, or every later test in this
        # session runs without it.
        faulthandler.enable()


def test_the_crash_log_records_a_traceback(tmp_path):
    """End to end, through the real faulthandler rather than a mock: dump a
    traceback and read it back off disk. A test that only checked the flag
    would pass with the file opened in a mode that never persists anything."""
    handle = setup_crash_log(tmp_path)
    try:
        faulthandler.dump_traceback(file=handle)
        handle.flush()
        text = crash_log_path(tmp_path).read_text(encoding="utf-8",
                                                  errors="replace")
    finally:
        if handle is not None:
            faulthandler.disable()
            handle.close()

    assert "Current thread" in text or "Thread" in text
    assert "test_the_crash_log_records_a_traceback" in text, \
        "the dump did not reach the file the app would be read from"


def test_a_session_header_says_which_run_crashed(tmp_path):
    """The log is APPENDED across runs -- a crash log truncated at startup
    loses the crash you are investigating the moment you relaunch to look at
    it. So each run marks itself, or the tracebacks cannot be told apart."""
    first = setup_crash_log(tmp_path)
    if first is not None:
        faulthandler.disable()
        first.close()
    second = setup_crash_log(tmp_path)
    try:
        text = crash_log_path(tmp_path).read_text(encoding="utf-8",
                                                  errors="replace")
    finally:
        if second is not None:
            faulthandler.disable()
            second.close()

    assert text.count("=== ade_desktop ") >= 2, \
        "a second run overwrote or failed to mark the log"


def test_an_unwritable_directory_does_not_stop_the_app(tmp_path):
    """Same rule as setup_logging above it: a box where the state directory
    cannot be written must still get an app. Diagnostics are an improvement,
    and an app that refuses to start because it could not open its crash log
    is worse than one that starts without it."""
    blocker = tmp_path / "state"
    blocker.write_text("not a directory", encoding="utf-8")

    handle = setup_crash_log(blocker)

    assert handle is None


def test_main_actually_sets_the_crash_log_up():
    """Every test above passes with nothing calling setup_crash_log.

    That is not hypothetical: `index_code` in the sibling repo shipped with 22
    tests, a careful docstring and no production caller, and went seven weeks
    describing a tree that no longer existed. A diagnostic nobody wires in is
    worse than none, because it reads as covered.
    """
    import inspect

    from ade_desktop import __main__ as entry

    source = inspect.getsource(entry.main)
    assert "setup_crash_log(" in source, "main() never CALLS setup_crash_log"
    assert "_CRASH_LOG" in source, \
        "the handle must outlive main()'s frame or the next crash is silent"


def test_the_handle_is_held_at_module_scope():
    """A local would be collected when main()'s frame went away, closing the
    fd faulthandler writes through."""
    from ade_desktop import __main__ as entry

    assert hasattr(entry, "_CRASH_LOG")
