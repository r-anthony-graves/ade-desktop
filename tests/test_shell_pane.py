"""The shell pane. autostart=False everywhere: these tests are about tabs
and lifetimes, and spawning a real pwsh per test would make them slow and
leave orphans behind if one failed. test_shell_pty.py owns the real pty."""

from ade_desktop.shell.pane import ShellPane
from ade_desktop.shell.view import DEFAULT_FONT_PX


def test_it_opens_with_one_session(qapp):
    pane = ShellPane(autostart=False)
    assert pane.session_count() == 1
    assert pane.tabs.count() == 1
    assert pane.current() is pane.views[0]


def test_plus_opens_another_and_each_is_its_own_process(qapp):
    """Requirement 7: one shell running a server, one for git."""
    pane = ShellPane(autostart=False)
    first = pane.views[0]
    second = pane.add_session()
    assert first is not second
    assert first.session is not second.session
    assert first.screen is not second.screen
    assert pane.session_count() == 2
    assert pane.tabs.count() == 2


def test_the_tabs_are_numbered_and_numbers_are_not_reused(qapp):
    """Closing PowerShell 2 and opening another must not give you a second
    PowerShell 2 sitting beside PowerShell 3."""
    pane = ShellPane(autostart=False)
    pane.add_session()
    pane.add_session()
    assert [pane.tabs.tabText(i) for i in range(3)] == [
        "PowerShell 1", "PowerShell 2", "PowerShell 3"]
    pane.close_session(1)
    pane.add_session()
    assert [pane.tabs.tabText(i) for i in range(3)] == [
        "PowerShell 1", "PowerShell 3", "PowerShell 4"]


def test_closing_a_tab_stops_that_pty(qapp):
    """NO TAB, NO SHELL, at the pane level. Falsify by dropping the
    view.stop() call from close_session."""
    pane = ShellPane(autostart=False)
    second = pane.add_session()
    stopped = []
    second.stop = lambda: stopped.append(True)
    pane.close_session(1)
    assert stopped == [True]
    assert pane.session_count() == 1


def test_closing_a_tab_leaves_the_others_running(qapp):
    """The two sets are independent -- closing one shell must not disturb
    another."""
    pane = ShellPane(autostart=False)
    survivor = pane.views[0]
    pane.add_session()
    touched = []
    survivor.stop = lambda: touched.append(True)
    pane.close_session(1)
    assert touched == []


def test_the_last_tab_cannot_be_closed(qapp):
    """A shell pane with no shell is a dead rectangle."""
    pane = ShellPane(autostart=False)
    pane.close_session(0)
    assert pane.session_count() == 1


def test_an_out_of_range_close_is_ignored(qapp):
    pane = ShellPane(autostart=False)
    pane.add_session()
    pane.close_session(99)
    pane.close_session(-1)
    assert pane.session_count() == 2


def test_stop_all_stops_every_session(qapp):
    """Quit must not leave a pwsh behind: the window was the only way to
    notice it."""
    pane = ShellPane(autostart=False)
    pane.add_session()
    pane.add_session()
    stopped = []
    for view in pane.views:
        view.stop = lambda: stopped.append(True)
    pane.stop_all()
    assert len(stopped) == 3


def test_zoom_reaches_every_session(qapp):
    """Including ones not currently on screen -- switching to a background
    tab must not show it at the old size."""
    pane = ShellPane(autostart=False)
    pane.add_session()
    pane.apply_zoom(2.0)
    for view in pane.views:
        assert view.font_px() == round(DEFAULT_FONT_PX * 2.0)


def test_switching_tabs_shows_that_terminal(qapp):
    pane = ShellPane(autostart=False)
    second = pane.add_session()
    pane.tabs.setCurrentIndex(0)
    assert pane.stack.currentWidget() is pane.views[0]
    pane.tabs.setCurrentIndex(1)
    assert pane.stack.currentWidget() is second
