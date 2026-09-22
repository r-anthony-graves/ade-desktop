"""Dark, from the trader's own palette, so the whole app reads as one.

When the trader loaded, its OWN DARK_QSS is the base: its screens rely on
object names (tileTitle, tileValue, ...) that only that stylesheet styles,
so a copy here would drift. BASE_QSS is the fallback for when it did not.

The app's text sizes live in ONE place: BASE_FONT_PX and the three
ratios derived from it. Anything that merely wanted the base inherits it
and states nothing. They are declared in DESKTOP_QSS, which is
concatenated AFTER whichever base sheet loaded, so they win over the
trader's own 15px without editing D:/tradinglocal. A Qt stylesheet
font-size also beats a font set with setFont(), so the monospace surfaces
(terminal, editor, shell bubbles) keep the system fixed FAMILY and take
their SIZE from here too -- measured, not assumed.
"""

from __future__ import annotations

BASE_FONT_PX = 18

# The ladder is DERIVED, never retyped: the app title a fifth above the
# base, a quieter label a notch under it, the hint quieter still. Their
# ratios are the ones the app shipped with at 15px, so raising the base
# keeps the hierarchy instead of flattening it.
TITLE_FONT_PX = round(BASE_FONT_PX * 1.2)
SMALL_FONT_PX = round(BASE_FONT_PX * 0.93)
HINT_FONT_PX = round(BASE_FONT_PX * 0.8)

TONES = {"ok": "#3fb68b", "warn": "#d9a441", "bad": "#d95757",
         "off": "#5c626b"}

# No font-size here on purpose: BASE_FONT_PX below is the only one, so the
# two cannot drift apart.
BASE_QSS = """
QMainWindow, QWidget { background: #17191d; color: #d6d9de; }
QPushButton { background: #262b33; border: 1px solid #333a45;
              border-radius: 3px; padding: 6px 14px; }
QMenu { background: #1e2126; border: 1px solid #333a45; }
QMenu::item:selected { background: #2a3442; }
"""

DESKTOP_QSS = f"""QMainWindow, QWidget {{ font-size: {BASE_FONT_PX}px; }}
QLabel#appTitle {{ font-size: {TITLE_FONT_PX}px; font-weight: 800;
                   color: #e8ebef; }}
""" + """
QWidget#header { background: #131417; border-bottom: 1px solid #2a2e35; }
QLabel#brain { color: #9aa1ab; }
QListWidget#rail { background: #131417; border: none;
                   border-right: 1px solid #2a2e35; }
QListWidget#rail::item { padding: 12px 16px; }
QListWidget#rail::item:selected { background: #2a3442; color: #e8ebef;
                                  border-left: 3px solid #4f8cc9; }
QLabel#placeholder { color: #d9a441; padding: 24px; }
QToolButton#micButton { background: #262b33; border: 1px solid #333a45;
                        border-radius: 3px; padding: 4px 14px; color: #d6d9de; }
QToolButton#micButton[muted="true"] { background: #3a1f22; border-color: #d95757;
                                      color: #ff8a8a; font-weight: 700; }
"""


def stylesheet(trader_qss: str | None) -> str:
    return (trader_qss or BASE_QSS) + DESKTOP_QSS
