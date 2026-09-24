"""The frame: a header that always says what Ade OS is doing, a rail that
lists only sections that exist, and a close button that hides rather than
quits -- unless there is no tray to come back from."""

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QLabel

from ade_desktop.app import DesktopWindow
from ade_desktop.geometry import load_state
from ade_desktop.sections import Section


class FakeStatus(QObject):
    health = Signal(dict)
    settings = Signal(dict)

    def __init__(self):
        super().__init__()
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1


def _window(tmp_path, *, tray, sections=None, quits=None):
    calls = {"start": 0, "stop": 0}
    if sections is None:
        sections = [Section(
            "Trader", QLabel("trader"),
            start=lambda: calls.__setitem__("start", calls["start"] + 1),
            stop=lambda: calls.__setitem__("stop", calls["stop"] + 1))]
    quits = quits if quits is not None else []
    status = FakeStatus()
    win = DesktopWindow(sections, status,
                        state_path=tmp_path / "window.json",
                        tray_available=tray,
                        quit_fn=lambda: quits.append(True))
    return win, status, calls, quits


def test_the_rail_lists_exactly_the_registered_sections(qapp, tmp_path):
    win, *_ = _window(tmp_path, tray=False)
    assert win.section_names() == ["Trader"]
    assert win.stack.count() == 1
    assert win.current_section() == "Trader"


def test_the_header_follows_health_and_settings(qapp, tmp_path):
    win, status, *_ = _window(tmp_path, tray=False)
    status.health.emit({"status": "up", "may_execute_tools": True,
                        "subsystems": {}})
    assert (win.ade_pill.label, win.ade_pill.tone) == ("UP", "ok")
    assert "ADE OS" in win.ade_pill.text() and "UP" in win.ade_pill.text()
    status.health.emit({"error": "ConnectError: refused"})
    assert win.ade_pill.label == "DOWN"
    assert "refused" in win.ade_pill.toolTip()
    status.settings.emit({"resolved": {"brain": "own: deepseek-v4-flash-iq1"}})
    assert win.brain_label.text() == "own: deepseek-v4-flash-iq1"


def test_the_log_records_a_transition_once_not_every_poll(
        qapp, tmp_path, caplog):
    import logging

    win, status, *_ = _window(tmp_path, tray=False)
    up = {"status": "up", "may_execute_tools": True, "subsystems": {}}
    with caplog.at_level(logging.INFO, logger="ade_desktop.app"):
        for payload in (up, up, up, {"error": "ConnectError: refused"},
                        {"error": "ConnectError: refused"}):
            status.health.emit(payload)
    lines = [r.getMessage() for r in caplog.records
             if r.name == "ade_desktop.app" and "ade os:" in r.getMessage()]
    assert len(lines) == 2, lines
    assert "-> UP" in lines[0] and "UP -> DOWN" in lines[1]


def test_start_starts_the_status_client_and_every_section(qapp, tmp_path):
    win, status, calls, _ = _window(tmp_path, tray=False)
    win.start()
    assert status.started == 1
    assert calls["start"] == 1


def test_close_with_a_tray_hides_and_does_not_quit(qapp, tmp_path):
    win, _, calls, quits = _window(tmp_path, tray=True)
    win.show()
    event = QCloseEvent()
    win.closeEvent(event)
    assert not event.isAccepted()
    assert not win.isVisible()
    assert quits == []
    assert calls["stop"] == 0
    assert load_state(tmp_path / "window.json")["section"] == "Trader"


def test_close_with_no_tray_quits(qapp, tmp_path):
    win, status, calls, quits = _window(tmp_path, tray=False)
    win.show()
    event = QCloseEvent()
    win.closeEvent(event)
    assert event.isAccepted()
    assert quits == [True]
    assert calls["stop"] == 1
    assert status.stopped == 1


def test_the_tray_quit_action_quits_and_stops_sections(qapp, tmp_path):
    win, status, calls, quits = _window(tmp_path, tray=True)
    actions = {a.text(): a for a in win.tray.contextMenu().actions()}
    assert "Show Ade" in actions and "Quit" in actions
    actions["Quit"].trigger()
    assert quits == [True]
    assert calls["stop"] == 1
    assert status.stopped == 1


def test_a_section_without_stop_does_not_break_quit(qapp, tmp_path):
    sections = [Section("Trader", QLabel("t"), start=None, stop=None)]
    win, _, _, quits = _window(tmp_path, tray=False, sections=sections)
    win.quit_app()
    assert quits == [True]


def test_a_saved_position_on_a_vanished_monitor_is_pulled_back(
        qapp, tmp_path):
    from PySide6.QtGui import QGuiApplication

    (tmp_path / "window.json").write_text(
        '{"x": -30000, "y": -30000, "w": 700, "h": 500, "section": "Trader"}',
        encoding="utf-8")
    win, *_ = _window(tmp_path, tray=False)
    screen = QGuiApplication.primaryScreen().availableGeometry()
    g = win.geometry()
    assert screen.intersects(g)
    assert g.width() == min(700, screen.width())


class _Stoppable:
    def __init__(self, log, name):
        self.log, self.name = log, name

    def start(self):
        self.log.append(f"{self.name}.start")

    def stop(self):
        self.log.append(f"{self.name}.stop")


class FakePanel(QLabel):
    """Stands in for a ChatStack AND for its one session.

    Since 2026-09-24 a page holds a STACK of chats (requirement 7): the
    window calls stack.start() and walks stack.panels, while quit still
    reaches each panel's on_quit/client/watcher. A stack of one is the
    smallest fake that exercises both halves, and it keeps this test's
    assertions about start and quit ORDER meaningful."""

    approval_needed = Signal(str)
    reply_landed = Signal(str)

    def __init__(self, log, name="panel"):
        super().__init__(name)
        self.log, self.name = log, name
        self.client = _Stoppable(log, f"{name}.client")
        self.watcher = _Stoppable(log, f"{name}.watcher")
        self.panels = [self]

    def start(self):
        self.watcher.start()

    def on_quit(self):
        self.log.append(f"{self.name}.on_quit")


def _with_panel(tmp_path, *, tray=True):
    """General's chat, and the Trader section's own (a chat per section)."""
    log = []
    panel = FakePanel(log, "general")
    trader_chat = FakePanel(log, "trader")
    status = FakeStatus()
    win = DesktopWindow([Section("Trader", QLabel("t")), Section("Bare", QLabel("b"))],
                        status, state_path=tmp_path / "window.json",
                        tray_available=tray, quit_fn=lambda: log.append("quit"),
                        panel=panel, side_panels={"Trader": trader_chat})
    win.trader_chat = trader_chat
    return win, panel, log


def test_a_section_s_own_chat_sits_on_the_right_of_a_splitter(qapp, tmp_path):
    win, panel, _ = _with_panel(tmp_path)
    win.show_section("Trader")
    assert win.splitter.widget(win.splitter.count() - 1) is win.side
    assert win.side.currentWidget() is win.trader_chat and not win.side.isHidden()
    assert panel.parent() is win.general_page             # General's never moves
    assert win.panel_open() is True
    assert win.panel_toggle.text() == "Ade ◂"


def test_the_toggle_and_the_shortcut_open_and_close_it(qapp, tmp_path):
    from PySide6.QtCore import Qt

    win, _, _ = _with_panel(tmp_path)
    win.show_section("Trader")
    win.panel_toggle.click()
    assert win.panel_open() is False and win.side.isHidden()
    assert win.panel_toggle.text() == "Ade ▸"
    # The shortcut belongs to THIS window only -- never application-wide,
    # never a global hotkey.
    assert win.panel_shortcut.context() == Qt.ShortcutContext.WindowShortcut
    assert win.panel_shortcut.key().toString() == "Ctrl+Shift+A"
    win.panel_shortcut.activated.emit()
    assert win.panel_open() is True and not win.side.isHidden()


def test_panel_state_round_trips_and_the_width_is_clamped(qapp, tmp_path):
    (tmp_path / "window.json").write_text(
        '{"panel_open": false, "panel_width": 5000}', encoding="utf-8")
    win, _, _ = _with_panel(tmp_path)
    assert win.panel_open() is False
    assert win._panel_width == 900
    win.save_state()
    saved = load_state(tmp_path / "window.json")
    assert saved["panel_open"] is False and saved["panel_width"] == 900


def test_an_approval_shows_the_section_holding_its_card(qapp, tmp_path, monkeypatch):
    win, panel, _ = _with_panel(tmp_path)
    shown = []
    monkeypatch.setattr(win.tray, "showMessage",
                        lambda *a, **k: shown.append(a[:2]))
    win.show_section("Trader")
    win.set_panel_open(False)
    win.show_section("General")
    win.hide()
    win.trader_chat.approval_needed.emit("write_file")    # the Trader chat's turn asked
    assert win.isVisible() and win.current_section() == "Trader"
    assert win.panel_open() and not win.side.isHidden()
    assert shown == [("Ade needs a decision", "write_file")]
    panel.approval_needed.emit("run_shell")                # General's: back to General
    assert win.current_section() == "General" and len(shown) == 1


def test_start_and_quit_include_every_chat(qapp, tmp_path):
    win, _, log = _with_panel(tmp_path)
    win.start()
    assert "general.watcher.start" in log and "trader.watcher.start" in log
    win.quit_app()
    assert log[-7:] == ["general.on_quit", "general.client.stop", "general.watcher.stop",
                        "trader.on_quit", "trader.client.stop", "trader.watcher.stop",
                        "quit"]


def test_show_and_raise_shows_a_hidden_window(qapp, tmp_path):
    win, *_ = _window(tmp_path, tray=True)
    win.hide()
    win.show_and_raise()
    assert win.isVisible()



def test_quit_asks_before_losing_unsaved_work(qapp, tmp_path):
    from PySide6.QtWidgets import QWidget

    class Editing(QWidget):
        def unsaved(self):
            return ["unsaved changes to pm/x/charter.md"]

    asked, quits = [], []
    win = DesktopWindow([Section("PM", Editing())], FakeStatus(),
                        state_path=tmp_path / "window.json", tray_available=False,
                        quit_fn=lambda: quits.append(True),
                        confirm_quit=lambda q: asked.append(q) or False)
    win.quit_app()
    assert quits == [] and "pm/x/charter.md" in asked[0]      # kept open
    win._confirm_quit = lambda q: True
    win.quit_app()
    assert quits == [True]



# -- General (Ray, 2026-09-18: "add a general") -------------------------------------

def test_general_leads_the_rail_and_holds_its_own_chat_full_size(qapp, tmp_path):
    win, panel, _ = _with_panel(tmp_path)
    assert win.section_names()[0] == "General"
    assert win.current_section() == "General"            # the first thing Ray sees
    assert panel.parent() is win.general_page and not panel.isHidden()
    assert win.panel_toggle.isHidden() and win.side.isHidden()


def test_each_section_shows_its_own_chat_and_general_keeps_its(qapp, tmp_path):
    win, panel, _ = _with_panel(tmp_path)
    win.show_section("Trader")
    assert win.side.currentWidget() is win.trader_chat
    assert panel.parent() is win.general_page            # never moved into the side
    win.show_section("Bare")                             # a section with no chat
    assert win.side.isHidden() and win.panel_toggle.isHidden()
    win.show_section("Trader")
    assert not win.side.isHidden() and not win.panel_toggle.isHidden()


def test_leaving_general_keeps_the_side_chat_as_it_was(qapp, tmp_path):
    win, panel, _ = _with_panel(tmp_path)
    win.show_section("Trader")
    win.set_panel_open(False)
    win.show_section("General")
    assert win.side.isHidden()
    win.show_section("Trader")
    assert win.side.isHidden()                           # still closed
    assert win.panel_toggle.text() == "Ade ▸" and not win.panel_toggle.isHidden()


def test_the_side_panel_s_state_is_what_is_saved_from_general(qapp, tmp_path):
    from ade_desktop.geometry import load_state
    win, panel, _ = _with_panel(tmp_path)
    win.show_section("Trader")
    win.set_panel_open(False)
    win.show_section("General")
    win.save_state()
    state = load_state(tmp_path / "window.json")
    assert state["section"] == "General" and state["panel_open"] is False
    win2, panel2, _ = _with_panel(tmp_path)
    assert win2.current_section() == "General" and not panel2.isHidden()
    win2.show_section("Trader")
    assert win2.side.isHidden()                            # the side preference survived


def test_switching_sections_switches_to_that_section_s_chat(qapp, tmp_path):
    log = []
    trader_chat, pm_chat = FakePanel(log, "trader"), FakePanel(log, "pm")
    win = DesktopWindow([Section("Trader", QLabel("t")), Section("PM", QLabel("p"))],
                        FakeStatus(), state_path=tmp_path / "window.json",
                        tray_available=False, quit_fn=lambda: None,
                        panel=FakePanel(log, "general"),
                        side_panels={"Trader": trader_chat, "PM": pm_chat})
    win.show_section("PM")
    assert win.side.currentWidget() is pm_chat
    win.show_section("Trader")
    assert win.side.currentWidget() is trader_chat


def test_a_dropped_window_is_freed_at_once(qapp, tmp_path):
    """The piece-1 lesson, applied to the window that owns everything else.

    Seven panels already carry this guard; the frame holding them did not.
    That matters more than any one panel: DesktopWindow owns the status
    poller, the sections, the tray and the chats, so if IT is cyclic garbage
    the collector tears all of them down at a moment of its choosing -- and
    the poller emits from a worker thread. That is the exact shape that
    crashed the trader's suite 6 of 6 on 2026-09-17, and the shape of the five
    0xc0000005 access violations this app took on 2026-09-21/22.

    `gc.disable()` is what makes it a real test: with the collector running,
    a cyclic window is freed EVENTUALLY and the weakref looks fine.
    """
    import gc
    import weakref

    gc.collect()
    gc.disable()
    try:
        win, status, _, _ = _window(tmp_path, tray=False)
        status.health.emit(
            {"status": "up", "may_execute_tools": True, "blocking_reason": "",
             "subsystems": {}})
        ref = weakref.ref(win)
        del win
        assert ref() is None, "the window survived its last reference"
    finally:
        gc.enable()


def test_general_stacks_chat_over_shell_with_a_usable_shell(qapp, tmp_path):
    """Ray, 2026-09-24: "the powershell does not open just has a tab".

    It HAD opened -- the pty was alive and the prompt was on its screen --
    but the pane was 94 px of a 756 px column and the terminal got 49 px,
    three rows. QSplitter divides by sizeHint on first show and a bare
    QWidget has none; setStretchFactor only shares EXTRA space on a later
    resize. So the shell asks for 80x24 now, and General's first-run split
    is set explicitly rather than left to whichever child asks loudest.

    Falsify by removing the GENERAL_SPLIT branch from _restore_state --
    verified: chat_h > shell_h then fails. Removing TerminalView.sizeHint
    alone does NOT break this any more, because the explicit split now
    decides the first run; that hint is guarded by
    test_shell_view.py::test_the_terminal_asks_for_a_real_size, and it
    still matters for every other container the view is dropped into."""
    from ade_desktop.shell.pane import ShellPane

    log = []
    shell = ShellPane(autostart=False)          # no real pwsh in a unit test
    win = DesktopWindow([Section("Trader", QLabel("t"))], FakeStatus(),
                        state_path=tmp_path / "window.json",
                        tray_available=False, quit_fn=lambda: log.append("quit"),
                        panel=FakePanel(log, "general"), shell=shell)
    win.resize(1200, 800)
    win.show()
    qapp.processEvents()

    chat_h, shell_h = win.general_page.sizes()
    assert shell_h > 0, "the shell pane got no height at all"
    # chat leads, but the shell is a usable terminal, not a sliver
    assert chat_h > shell_h, (chat_h, shell_h)
    assert shell_h > 0.25 * (chat_h + shell_h), (chat_h, shell_h)
    view = shell.current()
    assert view is not None
    assert view.grid()[1] >= 10, f"only {view.grid()[1]} rows: {view.height()}px"
    win.quit_app()
