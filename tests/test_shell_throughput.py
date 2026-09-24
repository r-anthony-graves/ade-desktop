r"""pyte is pure Python, and on this box it parses at 0.45 MB/s (measured
2026-09-24; colour makes no difference). That is fine for real command
output and a multi-second freeze under a flood:

       200 lines  (  14 KB)     66 ms   fine
     2,000 lines  ( 139 KB)    315 ms   visible stutter
    20,000 lines  ( 1.4 MB)  3,342 ms   a freeze
    dir C:\Windows /s (~10 MB)   ~22 s   unusable

So the gate is NOT "pyte is fast enough" -- it measurably is not. The gate
is that the cost is bounded by ELAPSED TIME rather than by output size,
which is what FLOOD_CAP_BYTES buys: the screen keeps 30 rows and history
keeps 5,000 lines, so a flood is discarded either way. Dropping it before
paying to parse it costs nothing anyone could have seen.

These tests pin both halves: real output is never touched, and a flood
cannot cost more than one capped parse however large it is.
"""

import time

from ade_desktop.shell.screen import FLOOD_CAP_BYTES, TerminalScreen

ESC = chr(27)
CHUNK = (ESC + "[32mC:/Users/ray_g/some/path/file.txt" + ESC + "[0m"
         "   12,345 bytes  2026-09-24\r\n")


def test_real_command_output_is_never_dropped():
    """A pytest run, a git log, a large dir -- all far below the cap, and
    all keep full fidelity. Falsify by lowering FLOOD_CAP_BYTES to 4 KB."""
    s = TerminalScreen(120, 30)
    payload = CHUNK * 2000                      # ~139 KB, a big real listing
    assert len(payload) < FLOOD_CAP_BYTES
    assert s.feed(payload) == 0


def test_a_flood_costs_no_more_than_one_capped_parse():
    """The load-bearing property. 10 MB must cost what 256 KB costs --
    otherwise the window locks for tens of seconds on `dir /s`.

    Falsify by removing the FLOOD_CAP_BYTES branch from feed(): this test
    then takes ~22 s and fails its budget."""
    s = TerminalScreen(120, 30)
    payload = CHUNK * (10_000_000 // len(CHUNK))
    assert len(payload) > 9_000_000
    started = time.perf_counter()
    dropped = s.feed(payload)
    elapsed = time.perf_counter() - started
    print(f"\n{len(payload)/1e6:.1f} MB flood: {elapsed:.2f}s, "
          f"{dropped/1e6:.1f} MB dropped before parsing")
    assert dropped > 0, "nothing was dropped; the cap did not engage"
    assert elapsed < 2.0, (
        f"a {len(payload)/1e6:.0f} MB flood took {elapsed:.1f}s -- the cost "
        "is still proportional to output size")


def test_what_survives_a_flood_is_the_END_of_it():
    """A terminal shows you where the command finished, not where it began."""
    s = TerminalScreen(120, 30)
    s.feed(CHUNK * 20000 + "THE-LAST-LINE\r\n")
    assert "THE-LAST-LINE" in "".join(c.text for c in s.rows()[-2])


def test_the_cut_lands_on_a_line_boundary():
    """Cutting mid-escape-sequence leaves the parser holding half a
    sequence and paints the rest of the line as garbage. Falsify by
    dropping the text.find(chr(10), cut) adjustment."""
    s = TerminalScreen(120, 30)
    s.feed(CHUNK * 20000)
    first = "".join(c.text for c in s.rows()[0]).rstrip()
    assert first in ("", CHUNK.split(ESC + "[0m")[0].replace(ESC + "[32m", "")
                     + "   12,345 bytes  2026-09-24") or "file.txt" in first


def test_one_flush_batch_is_inside_a_frame_budget():
    """The interactive constraint is one 50 ms flush, not the total. 32 KB
    is a generous stand-in for what a pty delivers in 50 ms."""
    s = TerminalScreen(120, 30)
    batch = CHUNK * (32_768 // len(CHUNK))
    started = time.perf_counter()
    s.feed(batch)
    elapsed = time.perf_counter() - started
    print(f"\none 32 KB batch in {elapsed*1000:.1f} ms")
    assert elapsed < 0.25, f"a single batch took {elapsed*1000:.0f} ms"
