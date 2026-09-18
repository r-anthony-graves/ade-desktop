"""The Trader: D:\\tradinglocal's real command center, minus its Chat dock.

Imported, not copied: build_panel() holds wiring that each cost a real bug
to learn (the journal is chosen by the UTC date, because the desk's 20:00-ET
ticks land in the next day's file). Any failure to import or build becomes
a readable placeholder -- the rest of the app must start.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
import traceback
from pathlib import Path

from ade_desktop.sections import Section, placeholder

DEFAULT_ROOT = Path(r"D:\tradinglocal")
log = logging.getLogger("ade_desktop.trader")


def trader_root() -> Path:
    return Path(os.environ.get("ADE_DESKTOP_TRADER_ROOT") or DEFAULT_ROOT)


def build_trader_section(root: Path) -> Section:
    root = Path(root)
    if not (root / "agent" / "command_center").is_dir():
        return placeholder(
            "Trader",
            f"Trader not found at {root}. Set ADE_DESKTOP_TRADER_ROOT to the "
            "tradinglocal checkout.")
    # APPENDED, not inserted first: tradinglocal also has an `adeos`
    # package, and at the front of sys.path it would answer any later
    # `import adeos` in this process (found in review, 2026-09-17). Its own
    # names (`agent`, `engine`) are claimed by nothing else here.
    if str(root) not in sys.path:
        sys.path.append(str(root))
    try:
        cc_main = importlib.import_module("agent.command_center.__main__")
        services = importlib.import_module("agent.command_center.services")
        cc_app = importlib.import_module("agent.command_center.app")
        desk = services.DeskClient()
        panel = cc_main.build_panel(desk)
    except Exception as exc:  # noqa: BLE001 -- a broken trader is a state
        log.exception("trader could not be loaded from %s", root)
        last = traceback.format_exception_only(type(exc), exc)[-1].strip()
        return placeholder(
            "Trader", f"The trader at {root} could not be loaded:\n{last}")
    log.info("trader loaded from %s", root)
    return Section("Trader", panel, start=desk.start, stop=None,
                   qss=getattr(cc_app, "DARK_QSS", None))
