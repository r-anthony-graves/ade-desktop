# Ade Desktop

One native desktop app for all of Ade: PySide6, **no browser engine** (Ray,
2026-09-17). It's being built in seven pieces. Each section appears in the
rail only once it exists.

| Piece | Section | State |
|---|---|---|
| 1 | Frame + **Trader** | built, and this README describes it |
| 2 | Ade conversation | next |
| 3 | Orb + voice (after this, the Electron avatar retires) | |
| 4 | PM | |
| 5 | QA | |
| 6 | Path | needs a data source first: The Path serves HTML only |
| 7 | Code | |

Design: `docs/superpowers/specs/2026-09-17-ade-desktop-piece-1-design.md` in
ade-ai. Plan: `docs/superpowers/plans/2026-09-17-ade-desktop-piece-1.md`.

## Set up once

    py -V:Astral/CPython3.14.0 -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt

`requirements.txt` pins **PySide6-Essentials 6.11.1**, the same Qt
`D:\tradinglocal\.venv` runs, because the trader's widgets are imported into
this process. If tradinglocal upgrades PySide6, move this pin with it.
Essentials leaves out PySide6-Addons, which is where QtWebEngine lives.
`tests/test_packaging.py` fails if a browser engine ever gets installed.

## Run

    .\run-desktop.ps1            # start, or bring the running one forward
    .\run-desktop.ps1 -Status
    .\run-desktop.ps1 -Stop

Close hides it to the tray, and the tray's **Quit** ends it. Only one runs
per user: a second launch brings the first forward. A lock file in the state
directory decides which one that is. `-Stop` is a hard kill and leaves the
lock behind, but the lock only counts while its owner is alive, so the next
launch takes it over.

## What it shows

- **Header:** the Ade OS pill, from `/v1/health` every 5 s:
  **UP**, **DOWN** (unreachable, or an error envelope), **BLOCKED**
  (`may_execute_tools: false`; Ade OS answers that with a 503 *and* a body),
  **DEGRADED** (a subsystem is down but tools may run), or **UNKNOWN** (the
  payload can't say). Hover over it for the reason. The brain name comes
  from `/v1/settings` → `resolved.brain` every 30 s.
- **Trader:** `D:\tradinglocal`'s real command center (`build_panel()`), with
  the same pills, RESTART TRADER, and the Desk, Decisions, Committee and
  Record screens, **minus the Chat dock**. If it can't be imported, the
  section says why and the rest of the app still starts.

## Settings (environment)

| Variable | Default | |
|---|---|---|
| `ADE_DESKTOP_ADE_URL` | `http://127.0.0.1:8300` | which Ade OS the header watches (the avatar's twin is `:8301`) |
| `ADE_DESKTOP_TRADER_ROOT` | `D:\tradinglocal` | the trader checkout to import |
| `ADE_DESKTOP_STATE_DIR` | `%APPDATA%\ade-desktop` | `window.json` and `desktop.log` |
| `COMMAND_CENTER_DESK` | the trader's own default, `:5961` | read by the trader, not by this app |

## Test

    .\.venv\Scripts\python.exe -m pytest -q
    .\.venv\Scripts\python.exe -m ade_desktop --smoke --smoke-out=smoke.png

`--smoke` builds the real window headless, polls for 4 s, prints what it
saw as JSON and writes a PNG. It passes with everything DOWN, because DOWN
is a correctly rendered state.

**If you ever hit a native crash in the tests** (`Windows fatal exception:
access violation`): check whether a widget a test drops has become a
reference cycle. PySide can crash when the garbage collector tears a window
down while a poller thread is delivering a signal. On 2026-09-17 that took
down tradinglocal's suite 6 times out of 6, until the cycle was broken so
dropped windows are freed at their last reference.
`test_a_dropped_window_is_freed_at_once_not_by_the_cycle_collector` in
tradinglocal pins it.

## What it runs

Nothing of its own. The only process it can start is the trader's own
**RESTART TRADER** (`stock-start.ps1`, behind the same confirm as the
standalone window). Every Ade action in later pieces goes through Ade OS and
its permission gate.
