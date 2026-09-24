"""The VT screen. Pure: no Qt, no process, no I/O.

Keeping it pure is not tidiness -- it is what lets the escape-sequence
behaviour be tested headless, so a parser bug and a painting bug can never
be mistaken for one another.

**pyte's two argument orders are reversed with respect to each other:**
`HistoryScreen(columns, lines)` but `Screen.resize(lines, columns)`. This
wrapper takes `(cols, rows)` at every door and does the swap in exactly ONE
place, because doing it at each call site is how a transposed terminal
ships. A test pins the direction.
"""

from __future__ import annotations

from typing import NamedTuple

import pyte

DEFAULT_HISTORY = 5000

# Flood control. MEASURED on this box 2026-09-24: pyte parses at 0.45 MB/s
# (colour makes no difference), so 20,000 lines cost 3.3 s and a
# `dir C:\Windows /s` would lock the window for roughly 22 seconds.
#
# The waste is specific and fixable: the screen shows ~30 rows and history
# keeps DEFAULT_HISTORY lines, so under a flood pyte parses megabytes at
# full price and then discards nearly all of it. Dropping it BEFORE paying
# to parse it costs nothing that scrollback would have kept.
#
# 256 KB is chosen so that real command output is never touched -- `git
# log`, a pytest run and a large `dir` are all far below it, and those keep
# full fidelity. Only a genuine flood is cut, and then the view says so
# rather than silently losing the middle of a file.
#
# This converts an UNBOUNDED freeze (proportional to output size) into a
# bounded one (proportional to elapsed time). It does not make pyte fast:
# under a sustained flood the window is still choppy, ~0.5 s per flush.
# If that is not good enough, the next steps are parsing on a worker
# thread or replacing the parser -- see the spec's rejected alternatives.
FLOOD_CAP_BYTES = 256 * 1024

# The alternate screen. pyte implements NO buffer switching -- pyte.modes
# knows only LNM, IRM, DECTCEM, DECSCNM, DECOM, DECAWM and DECCOLM -- so
# without this, quitting vim or btop leaves that program's last frame on
# screen instead of the prompt history it covered. 1049 is what modern
# programs send; 47 and 1047 are the older spellings, kept because `less`
# and older builds still emit them.
_ALT_MODES = frozenset({47, 1047, 1049})


class _Screen(pyte.HistoryScreen):
    """HistoryScreen plus the alternate screen buffer.

    Private modes reach set_mode/reset_mode as RAW ints with private=True
    (pyte shifts them by 5 only afterwards, for its own mode set), so they
    can be intercepted here before pyte ever sees them.
    """

    def __init__(self, *args, **kwargs) -> None:
        self._saved: tuple | None = None
        super().__init__(*args, **kwargs)

    def _snapshot(self) -> tuple:
        return ({y: dict(row) for y, row in self.buffer.items()},
                self.cursor.x, self.cursor.y)

    def set_mode(self, *modes: int, **kwargs) -> None:
        if kwargs.get("private") and _ALT_MODES.intersection(modes):
            if self._saved is None:          # entering twice must not nest
                self._saved = self._snapshot()
            self.reset()
        super().set_mode(*modes, **kwargs)

    def reset_mode(self, *modes: int, **kwargs) -> None:
        if kwargs.get("private") and _ALT_MODES.intersection(modes):
            saved, self._saved = self._saved, None
            if saved is not None:
                buffer, x, y = saved
                self.reset()
                for line, row in buffer.items():
                    for column, char in row.items():
                        self.buffer[line][column] = char
                self.cursor.x, self.cursor.y = x, y
                self.dirty.update(range(self.lines))
        super().reset_mode(*modes, **kwargs)


class Cell(NamedTuple):
    """One rendered character. `fg`/`bg` are pyte's own colour values: a
    NAME ('default', 'red', 'brown', 'brightblue') or a 6-digit hex string
    ('ff8000') for 256-colour and truecolor. Never None -- the renderer
    should never have to guess."""

    text: str
    fg: str
    bg: str
    bold: bool
    underline: bool
    reverse: bool


class TerminalScreen:
    def __init__(self, cols: int, rows: int,
                 history: int = DEFAULT_HISTORY) -> None:
        self._cols, self._rows = self._clamp(cols, rows)
        self._screen = _Screen(self._cols, self._rows, history=history)
        self._stream = pyte.Stream(self._screen)

    @staticmethod
    def _clamp(cols, rows) -> tuple[int, int]:
        """A widget is 0 px wide for at least one layout pass, and pyte
        divides by the column count -- a zero would raise mid-paint."""
        try:
            cols, rows = int(cols), int(rows)
        except (TypeError, ValueError):
            return 1, 1
        return max(1, cols), max(1, rows)

    @property
    def size(self) -> tuple[int, int]:
        return self._cols, self._rows

    def feed(self, text: str) -> int:
        """Feed output. Returns the number of characters DROPPED, so the
        caller can say so on screen -- a silent gap is a lie about what ran.

        Incremental: pyte's Stream carries its state between calls, so a pty
        read that ends mid-escape-sequence is reassembled rather than lost.
        A test pins that.

        The cut is made at a LINE boundary past the drop point, never at an
        arbitrary offset: cutting mid-escape-sequence would leave the parser
        holding half a sequence and paint the rest of the line as garbage.
        """
        if not text:
            return 0
        dropped = 0
        if len(text) > FLOOD_CAP_BYTES:
            cut = len(text) - FLOOD_CAP_BYTES
            newline = text.find("\n", cut)
            cut = newline + 1 if newline != -1 else cut
            dropped, text = cut, text[cut:]
        if text:
            self._stream.feed(text)
        return dropped

    def resize(self, cols: int, rows: int) -> None:
        cols, rows = self._clamp(cols, rows)
        if (cols, rows) == (self._cols, self._rows):
            return
        self._cols, self._rows = cols, rows
        self._screen.resize(rows, cols)          # pyte: (lines, columns)
        self._screen.dirty.update(range(rows))

    def cursor(self) -> tuple[int, int, bool]:
        """(x, y, hidden)."""
        c = self._screen.cursor
        return c.x, c.y, bool(c.hidden)

    def rows(self) -> list[list[Cell]]:
        buffer = self._screen.buffer
        out: list[list[Cell]] = []
        for y in range(self._rows):
            line = buffer[y]
            out.append([Cell(ch.data or " ", ch.fg, ch.bg, bool(ch.bold),
                             bool(ch.underscore), bool(ch.reverse))
                        for ch in (line[x] for x in range(self._cols))])
        return out

    def scroll(self, pages: int) -> None:
        """Wheel scrollback. Negative goes back into history."""
        step = self._screen.prev_page if pages < 0 else self._screen.next_page
        for _ in range(abs(int(pages))):
            step()
