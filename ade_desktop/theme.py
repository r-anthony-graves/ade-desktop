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
ZOOM_MIN, ZOOM_MAX = 0.6, 2.5        # 11px .. 45px off the 18px base

# The ladder is DERIVED, never retyped: the app title a fifth above the
# base, a quieter label a notch under it, the hint quieter still. Their
# ratios are the ones the app shipped with at 15px, so raising the base
# keeps the hierarchy instead of flattening it.
#
# They are derived INSIDE stylesheet() rather than exported as module
# constants, and that is the whole point of this shape: TITLE/SMALL/HINT
# used to be importable, and two files imported them and baked the numbers
# into inline stylesheets -- which no rescale could ever reach. A constant
# that can be imported is a constant that can be inlined again, so the
# rule above is now enforced by there being nothing to import.
_RATIOS = {"title": 1.2, "small": 0.93, "hint": 0.8}


def clamp_zoom(value) -> float:
    """Anything unusable reads as 1.0. A zoom that refuses is a zoom that
    leaves the app at whatever a bad saved state contained."""
    try:
        scale = float(value)
    except (TypeError, ValueError):
        return 1.0
    return max(ZOOM_MIN, min(ZOOM_MAX, scale))

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

DESKTOP_QSS = """
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

/* Every boundary in the app is draggable; this is what makes it LOOK it.
   There was no QSplitter rule here at all, so a 4 px handle was drawn in
   the default grey on a #17191d background and read as a gap rather than
   a grip -- Ray, 2026-09-24, reported the areas as not resizable when two
   of the three already were. 6 px is a real hit target; the hover colour
   is what says "drag me" BEFORE you try. */
QSplitter::handle { background: #2a2e35; }
QSplitter::handle:horizontal { width: 6px; }
QSplitter::handle:vertical { height: 6px; }
QSplitter::handle:hover { background: #4f8cc9; }
QSplitter::handle:pressed { background: #4f8cc9; }
"""


def sizes_qss(scale: float = 1.0) -> str:
    """Every font-size in the app, from one number.

    A Qt stylesheet font-size also beats a font set with setFont(), so the
    monospace surfaces (the editor, the shell bubbles) take their SIZE from
    here too while keeping the system fixed FAMILY -- measured, not assumed.
    The terminal is the one exception: it paints itself, so it cannot be
    styled at all and takes the scale by signal instead.
    """
    scale = clamp_zoom(scale)
    base = round(BASE_FONT_PX * scale)
    title = round(BASE_FONT_PX * _RATIOS["title"] * scale)
    small = round(BASE_FONT_PX * _RATIOS["small"] * scale)
    hint = round(BASE_FONT_PX * _RATIOS["hint"] * scale)
    return (f"QMainWindow, QWidget {{ font-size: {base}px; }}\n"
            f"QLabel#appTitle {{ font-size: {title}px; font-weight: 800;\n"
            f"                   color: #e8ebef; }}\n"
            f"QLabel#chatHint {{ font-size: {hint}px; color: #6f7682; }}\n"
            f"QLabel#pathStage {{ font-size: {small}px; }}\n")


def stylesheet(trader_qss: str | None, scale: float = 1.0) -> str:
    return (trader_qss or BASE_QSS) + sizes_qss(scale) + DESKTOP_QSS
