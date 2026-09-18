"""The Trader section is the REAL command center, minus its Chat dock --
and when it cannot be loaded, a readable placeholder, never a crash."""

from pathlib import Path

from ade_desktop.sections import Section, build_sections
from ade_desktop.sections.trader import build_trader_section, trader_root
from ade_desktop.theme import BASE_QSS, DESKTOP_QSS, stylesheet

REAL_ROOT = Path(r"D:\tradinglocal")


def test_the_real_trader_is_the_panel_with_four_tabs_and_no_dock(
        qapp, isolated_trader_imports, monkeypatch):
    from PySide6.QtWidgets import QDockWidget

    monkeypatch.setenv("COMMAND_CENTER_DESK", "http://127.0.0.1:9")
    section = build_trader_section(REAL_ROOT)
    assert section.placeholder_reason is None, section.placeholder_reason
    panel = section.widget
    assert type(panel).__name__ == "TraderPanel"
    names = [panel.tabs.tabText(i) for i in range(panel.tabs.count())]
    assert names == ["Desk", "Decisions", "Committee", "Record"]
    assert not panel.findChildren(QDockWidget)
    assert callable(section.start)
    assert section.stop is None
    assert "QMainWindow, QWidget" in section.qss  # the trader's DARK_QSS


def test_the_trader_root_goes_on_the_end_of_sys_path(
        qapp, isolated_trader_imports, monkeypatch):
    """tradinglocal has its own `adeos` package; at the FRONT of sys.path it
    would answer every later `import adeos` in this process."""
    import sys

    monkeypatch.setenv("COMMAND_CENTER_DESK", "http://127.0.0.1:9")
    assert str(REAL_ROOT) not in sys.path
    build_trader_section(REAL_ROOT)
    assert sys.path[-1] == str(REAL_ROOT)
    assert sys.path[0] != str(REAL_ROOT)


def test_a_missing_root_is_a_placeholder_naming_it(
        qapp, isolated_trader_imports, tmp_path):
    section = build_trader_section(tmp_path / "nowhere")
    assert section.name == "Trader"
    assert section.placeholder_reason
    assert str(tmp_path / "nowhere") in section.placeholder_reason
    assert "ADE_DESKTOP_TRADER_ROOT" in section.placeholder_reason
    assert section.start is None


def test_a_root_that_fails_to_import_is_a_placeholder_naming_the_error(
        qapp, isolated_trader_imports, tmp_path):
    cc = tmp_path / "agent" / "command_center"
    cc.mkdir(parents=True)
    (tmp_path / "agent" / "__init__.py").write_text("", encoding="utf-8")
    (cc / "__init__.py").write_text("", encoding="utf-8")
    (cc / "__main__.py").write_text(
        "raise RuntimeError('the trader is broken today')\n", encoding="utf-8")
    section = build_trader_section(tmp_path)
    assert section.placeholder_reason
    assert "the trader is broken today" in section.placeholder_reason
    assert str(tmp_path) in section.placeholder_reason


def test_a_root_without_build_panel_is_a_placeholder(
        qapp, isolated_trader_imports, tmp_path):
    cc = tmp_path / "agent" / "command_center"
    cc.mkdir(parents=True)
    for p in (tmp_path / "agent" / "__init__.py", cc / "__init__.py",
              cc / "__main__.py", cc / "app.py"):
        p.write_text("", encoding="utf-8")
    (cc / "services.py").write_text(
        "class DeskClient:\n    def start(self):\n        pass\n",
        encoding="utf-8")
    section = build_trader_section(tmp_path)
    assert section.placeholder_reason
    assert "build_panel" in section.placeholder_reason


def test_trader_root_default_and_override(monkeypatch, tmp_path):
    monkeypatch.delenv("ADE_DESKTOP_TRADER_ROOT", raising=False)
    assert trader_root() == REAL_ROOT
    monkeypatch.setenv("ADE_DESKTOP_TRADER_ROOT", str(tmp_path))
    assert trader_root() == tmp_path


def test_build_sections_is_trader_pm_qa(
        qapp, isolated_trader_imports, monkeypatch):
    monkeypatch.setenv("COMMAND_CENTER_DESK", "http://127.0.0.1:9")
    sections = build_sections()
    assert [s.name for s in sections] == ["Trader", "PM", "QA"]
    assert all(isinstance(s, Section) for s in sections)


def test_stylesheet_uses_the_traders_own_qss_when_it_loaded():
    assert stylesheet("TRADER {}") == "TRADER {}" + DESKTOP_QSS
    assert stylesheet(None) == BASE_QSS + DESKTOP_QSS
