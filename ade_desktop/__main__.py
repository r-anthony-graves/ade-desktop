"""python -m ade_desktop -- the app.

    python -m ade_desktop            run it (a second launch brings the
                                     running one forward and exits)
    python -m ade_desktop --smoke    build it headless, poll for a moment,
                                     print what it saw as JSON, write a PNG
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

log = logging.getLogger("ade_desktop")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ade_desktop")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--smoke-wait", type=int, default=4000)
    parser.add_argument("--smoke-out", default="smoke.png")
    return parser.parse_args(argv)


def setup_logging(directory: Path) -> None:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(directory / "desktop.log",
                                      maxBytes=1_000_000, backupCount=3,
                                      encoding="utf-8")
    except OSError:
        return
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    # httpx logs every request at INFO -- the trader and the header poll
    # about once a second, which buried the transitions this log is for.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def configure_app(app) -> None:
    app.setApplicationName("Ade")
    # Close hides to the tray; DesktopWindow quits explicitly when it must.
    app.setQuitOnLastWindowClosed(False)


def claim_instance(guard, lock_dir: Path, *, wait_s: float = 2.0) -> bool:
    """True if this launch should run. False if another instance is running
    (or starting) and has been asked to show itself instead."""
    if guard.notify_running():
        log.info("already running: asked it to show itself")
        return False
    if guard.acquire(lock_dir):
        if not guard.listen():
            log.warning("single-instance listen failed; continuing anyway")
        return True
    # The lock is held but nobody answered: another launch began a moment
    # ago and is not listening yet. Give it a moment, then hand it "show".
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        time.sleep(0.1)
        if guard.notify_running(timeout_ms=200):
            log.info("already starting: asked it to show itself")
            return False
    log.warning("another instance holds the lock and never answered; "
                "not starting a second one (run-desktop.ps1 -Stop clears it)")
    return False


def connect_instance(guard, win) -> None:
    guard.show_requested.connect(win.show_and_raise)


def build_window(*, state_path: Path, quit_fn=None):
    from ade_desktop.ade_status import AdeStatusClient
    from ade_desktop.app import DesktopWindow
    from ade_desktop.conversation.approvals import ApprovalWatcher
    from ade_desktop.conversation.client import ConversationClient
    from ade_desktop.conversation.panel import ConversationPanel
    from ade_desktop.conversation.threads import ThreadStore
    from ade_desktop.sections import build_sections

    # threads.json sits beside window.json -- the smoke run passes a temp
    # state_path, so it never touches the real conversation either.
    store = ThreadStore(Path(state_path).with_name("threads.json"))
    panel = ConversationPanel(ConversationClient(), ApprovalWatcher(), store)
    return DesktopWindow(build_sections(), AdeStatusClient(),
                         state_path=state_path, quit_fn=quit_fn, panel=panel)


def smoke_report(win) -> dict:
    trader = next((s for s in win.sections if s.name == "Trader"), None)
    pills = {}
    if trader is not None and trader.placeholder_reason is None:
        for attr in ("pill_desk", "pill_kraken", "pill_engine", "pill_mode"):
            widget = getattr(trader.widget, attr, None)
            if widget is not None:
                pills[attr] = widget.text()
    registry = [s.name for s in win.sections]
    trader_ok = trader is not None and (
        trader.placeholder_reason is not None or len(pills) == 4)
    # `ok` is the STRUCTURE only: DOWN is a correctly rendered state, so a
    # smoke run against a stopped Ade OS still passes. Whether an answer
    # arrived at all is reported separately, as `ade_polled`.
    ok = bool(registry) and win.section_names() == registry and trader_ok
    return {
        "ok": ok,
        "sections": win.section_names(),
        "ade_polled": win.ade_pill.label != "—",
        "ade_pill": win.ade_pill.text(),
        "ade_tooltip": win.ade_pill.toolTip(),
        "brain": win.brain_label.text(),
        "trader": ("missing" if trader is None else
                   "placeholder" if trader.placeholder_reason else "panel"),
        "trader_reason": trader.placeholder_reason if trader else None,
        "trader_pills": pills,
        "panel": ({"tabs": [win.panel.tabs.tabText(i)
                            for i in range(win.panel.tabs.count())],
                   "open": win.panel_open()} if win.panel is not None else None),
    }


def run_smoke(app, args) -> int:
    # Never the real window.json: a smoke run must not move Ray's window.
    state = Path(tempfile.mkdtemp(prefix="ade-desktop-smoke-")) / "window.json"
    win = build_window(state_path=state, quit_fn=app.quit)
    win.start()
    win.show()
    deadline = time.monotonic() + max(0, args.smoke_wait) / 1000.0
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)
    app.processEvents()
    report = smoke_report(win)
    out = Path(args.smoke_out)
    report["png_written"] = bool(win.grab().save(str(out)))
    report["png"] = str(out.resolve())
    win.quit_app()
    print(json.dumps(report, indent=2))
    log.info("smoke: ok=%s", report["ok"])
    return 0 if report["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.smoke:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        # Headless Qt ships no fonts: without this every letter in the smoke
        # PNG is an empty box, and the picture proves only the layout.
        if os.name == "nt":
            os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(
                os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))

    from PySide6.QtWidgets import QApplication

    from ade_desktop.geometry import state_dir
    from ade_desktop.single_instance import SingleInstance

    app = QApplication(sys.argv[:1])
    configure_app(app)
    directory = state_dir()
    setup_logging(directory)
    log.info("starting (smoke=%s)", args.smoke)

    if args.smoke:
        return run_smoke(app, args)

    guard = SingleInstance()
    if not claim_instance(guard, directory):
        return 0

    win = build_window(state_path=directory / "window.json")
    connect_instance(guard, win)
    win.start()
    win.show_initial()
    code = app.exec()
    guard.release()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
