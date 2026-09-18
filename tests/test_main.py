"""main()'s wiring, which the rest of the suite never reached (found in
review, 2026-09-17): deleting the show hand-over or quit-on-last-window
left every other test green."""

import time
import uuid

from ade_desktop.__main__ import claim_instance, configure_app, connect_instance
from ade_desktop.single_instance import SingleInstance


def _unique() -> str:
    return f"ade-desktop-test-{uuid.uuid4().hex[:8]}"


def test_closing_the_last_window_does_not_quit_the_app(qapp):
    """Close hides to the tray. If the last hidden window quit the app, the
    tray icon would vanish with it."""
    was = qapp.quitOnLastWindowClosed()
    try:
        qapp.setQuitOnLastWindowClosed(True)
        configure_app(qapp)
        assert qapp.quitOnLastWindowClosed() is False
        assert qapp.applicationName() == "Ade"
    finally:
        qapp.setQuitOnLastWindowClosed(was)


def test_a_show_request_reaches_the_window(qapp):
    class Window:
        shown = 0

        def show_and_raise(self):
            Window.shown += 1

    guard = SingleInstance(_unique())
    win = Window()
    connect_instance(guard, win)
    guard.show_requested.emit()
    assert Window.shown == 1


def test_the_first_launch_claims_the_instance(qapp, tmp_path):
    guard = SingleInstance(_unique())
    try:
        assert claim_instance(guard, tmp_path) is True
    finally:
        guard.close()
        guard.release()


def test_a_launch_that_loses_the_lock_does_not_start_a_second_app(
        qapp, tmp_path):
    """The first launch holds the lock but is not listening yet -- the
    moment the review found two launches could both run."""
    name = _unique()
    first = SingleInstance(name)
    assert first.acquire(tmp_path)
    try:
        second = SingleInstance(name)
        started = time.monotonic()
        assert claim_instance(second, tmp_path, wait_s=0.3) is False
        assert time.monotonic() - started < 5
    finally:
        first.release()
