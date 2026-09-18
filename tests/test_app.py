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
    approval_needed = Signal(str)

    def __init__(self, log):
        super().__init__("panel")
        self.log = log
        self.client = _Stoppable(log, "client")
        self.watcher = _Stoppable(log, "watcher")

    def on_quit(self):
        self.log.append("panel.on_quit")


def _with_panel(tmp_path, *, tray=True):
    log = []
    panel = FakePanel(log)
    status = FakeStatus()
    win = DesktopWindow([Section("Trader", QLabel("t"))], status,
                        state_path=tmp_path / "window.json",
                        tray_available=tray, quit_fn=lambda: log.append("quit"),
                        panel=panel)
    return win, panel, log


def test_the_panel_sits_on_the_right_of_a_splitter(qapp, tmp_path):
    win, panel, _ = _with_panel(tmp_path)
    win.show_section("Trader")                   # General holds it full size
    assert win.splitter.widget(win.splitter.count() - 1) is panel
    assert win.panel_open() is True
    assert win.panel_toggle.text() == "Ade ◂"


def test_the_toggle_and_the_shortcut_open_and_close_it(qapp, tmp_path):
    from PySide6.QtCore import Qt

    win, _, _ = _with_panel(tmp_path)
    win.show_section("Trader")
    win.panel_toggle.click()
    assert win.panel_open() is False and win.panel_toggle.text() == "Ade ▸"
    # The shortcut belongs to THIS window only -- never application-wide,
    # never a global hotkey.
    assert win.panel_shortcut.context() == Qt.ShortcutContext.WindowShortcut
    assert win.panel_shortcut.key().toString() == "Ctrl+Shift+A"
    win.panel_shortcut.activated.emit()
    assert win.panel_open() is True


def test_panel_state_round_trips_and_the_width_is_clamped(qapp, tmp_path):
    (tmp_path / "window.json").write_text(
        '{"panel_open": false, "panel_width": 5000}', encoding="utf-8")
    win, _, _ = _with_panel(tmp_path)
    assert win.panel_open() is False
    assert win._panel_width == 900
    win.save_state()
    saved = load_state(tmp_path / "window.json")
    assert saved["panel_open"] is False and saved["panel_width"] == 900


def test_an_approval_raises_the_window_and_opens_the_panel(qapp, tmp_path, monkeypatch):
    win, panel, _ = _with_panel(tmp_path)
    shown = []
    monkeypatch.setattr(win.tray, "showMessage",
                        lambda *a, **k: shown.append(a[:2]))
    win.set_panel_open(False)
    win.hide()
    panel.approval_needed.emit("write_file")
    assert win.isVisible() and win.panel_open()
    assert shown == [("Ade needs a decision", "write_file")]
    panel.approval_needed.emit("run_shell")     # already visible: no notice
    assert len(shown) == 1


def test_start_and_quit_include_the_panel(qapp, tmp_path):
    win, _, log = _with_panel(tmp_path)
    win.start()
    assert "watcher.start" in log
    win.quit_app()
    assert log[-4:] == ["panel.on_quit", "client.stop", "watcher.stop", "quit"]


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

def test_general_leads_the_rail_and_holds_the_conversation_full_size(qapp, tmp_path):
    win, panel, _ = _with_panel(tmp_path)
    assert win.section_names()[0] == "General"
    assert win.current_section() == "General"            # the first thing Ray sees
    assert panel.parent() is win.general_page and not panel.isHidden()
    assert win.panel_toggle.isHidden()


def test_leaving_general_puts_the_panel_back_as_it_was(qapp, tmp_path):
    win, panel, _ = _with_panel(tmp_path)
    win.show_section("Trader")
    assert win.splitter.indexOf(panel) >= 0 and not panel.isHidden()
    win.set_panel_open(False)
    win.show_section("General")
    assert panel.parent() is win.general_page and not panel.isHidden()
    win.show_section("Trader")
    assert win.splitter.indexOf(panel) >= 0 and panel.isHidden()   # still closed
    assert win.panel_toggle.text() == "Ade ▸" and not win.panel_toggle.isHidden()


def test_an_approval_in_general_needs_nothing_moved(qapp, tmp_path):
    win, panel, _ = _with_panel(tmp_path)
    win.raise_for_approval("run_shell")
    assert panel.parent() is win.general_page and not panel.isHidden()


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
    assert panel2.isHidden()                               # the side preference survived
