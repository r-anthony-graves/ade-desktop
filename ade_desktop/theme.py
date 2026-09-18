"""Dark, from the trader's own palette, so the whole app reads as one.

When the trader loaded, its OWN DARK_QSS is the base: its screens rely on
object names (tileTitle, tileValue, ...) that only that stylesheet styles,
so a copy here would drift. BASE_QSS is the fallback for when it did not.
"""

from __future__ import annotations

TONES = {"ok": "#3fb68b", "warn": "#d9a441", "bad": "#d95757",
         "off": "#5c626b"}

BASE_QSS = """
QMainWindow, QWidget { background: #17191d; color: #d6d9de;
                       font-size: 15px; }
QPushButton { background: #262b33; border: 1px solid #333a45;
              border-radius: 3px; padding: 6px 14px; }
QMenu { background: #1e2126; border: 1px solid #333a45; }
QMenu::item:selected { background: #2a3442; }
"""

DESKTOP_QSS = """
QWidget#header { background: #131417; border-bottom: 1px solid #2a2e35; }
QLabel#appTitle { font-size: 18px; font-weight: 800; color: #e8ebef; }
QLabel#brain { color: #9aa1ab; }
QListWidget#rail { background: #131417; border: none;
                   border-right: 1px solid #2a2e35; font-size: 15px; }
QListWidget#rail::item { padding: 12px 16px; }
QListWidget#rail::item:selected { background: #2a3442; color: #e8ebef;
                                  border-left: 3px solid #4f8cc9; }
QLabel#placeholder { color: #d9a441; padding: 24px; font-size: 15px; }
QToolButton#micButton { background: #262b33; border: 1px solid #333a45;
                        border-radius: 3px; padding: 4px 14px; color: #d6d9de; }
QToolButton#micButton[muted="true"] { background: #3a1f22; border-color: #d95757;
                                      color: #ff8a8a; font-weight: 700; }
"""


def stylesheet(trader_qss: str | None) -> str:
    return (trader_qss or BASE_QSS) + DESKTOP_QSS
