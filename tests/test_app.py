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


def test_show_and_raise_shows_a_hidden_window(qapp, tmp_path):
    win, *_ = _window(tmp_path, tray=True)
    win.hide()
    win.show_and_raise()
    assert win.isVisible()
