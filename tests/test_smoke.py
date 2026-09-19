"""--smoke builds the real window headless, lets it poll, and says what it
saw. It must pass with Ade OS and the desk both DOWN -- DOWN is a correctly
rendered state, not a failure."""

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _closed_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_smoke_exits_zero_writes_a_png_and_reports(tmp_path):
    out = tmp_path / "smoke.png"
    env = dict(os.environ)
    env.update({
        "ADE_DESKTOP_STATE_DIR": str(tmp_path / "state"),
        "ADE_DESKTOP_ADE_URL": f"http://127.0.0.1:{_closed_port()}",
        "COMMAND_CENTER_DESK": f"http://127.0.0.1:{_closed_port()}",
        "QT_QPA_PLATFORM": "offscreen",
    })
    proc = subprocess.run(
        [sys.executable, "-m", "ade_desktop", "--smoke", "--smoke-wait=500",
         f"--smoke-out={out}"],
        cwd=str(REPO), env=env, capture_output=True, text=True, timeout=90)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(proc.stdout)
    assert report["ok"] is True
    assert isinstance(report["ade_polled"], bool)
    assert report["sections"] == ["General", "Trader", "PM", "QA", "Path", "Code"]
    assert report["panel"] == {"tabs": ["Chat", "Shell"], "open": True}
    # a chat per section, each on its own Ade OS topic (2026-09-18)
    assert report["chats"] == ["General", "Trader", "PM", "QA", "Path", "Code"]
    assert len(report["chat_topics"]) == 6 and "u/local/desktop" in report["chat_topics"]
    assert report["trader"] == "panel", report.get("trader_reason")
    assert set(report["trader_pills"]) == {
        "pill_desk", "pill_kraken", "pill_engine", "pill_mode"}
    assert report["png_written"] is True
    assert out.exists() and out.stat().st_size > 0
    orb = report["orb"]
    assert orb["shown"] is True and orb["frame"] is not None
    assert orb["mic_open"] is False            # a smoke run never opens the mic
    assert orb["mute_button"] == "Unmute"      # the header's button, wired and truthful
    assert orb["online"] is False and orb["mood"] == "dormant"   # Ade OS is DOWN here
    assert orb["png_written"] is True
    # The smoke run used ADE_DESKTOP_STATE_DIR, never the real directory.
    assert (tmp_path / "state" / "desktop.log").exists()


def test_the_log_records_transitions_not_every_poll(tmp_path):
    """Measured 2026-09-17 on the first live run: httpx logged every request
    at INFO, about one line a second, burying the transitions."""
    import logging

    from ade_desktop.__main__ import setup_logging

    root = logging.getLogger()
    before = list(root.handlers)
    levels = {n: logging.getLogger(n).level for n in ("httpx", "httpcore")}
    try:
        setup_logging(tmp_path)
        assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
        assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING
        assert logging.getLogger("ade_desktop").getEffectiveLevel() <= logging.INFO
    finally:
        for handler in [h for h in root.handlers if h not in before]:
            root.removeHandler(handler)
            handler.close()
        for name, level in levels.items():
            logging.getLogger(name).setLevel(level)
