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
    assert report["sections"] == ["Trader"]
    assert report["trader"] == "panel", report.get("trader_reason")
    assert set(report["trader_pills"]) == {
        "pill_desk", "pill_kraken", "pill_engine", "pill_mode"}
    assert report["png_written"] is True
    assert out.exists() and out.stat().st_size > 0
    # The smoke run used ADE_DESKTOP_STATE_DIR, never the real directory.
    assert (tmp_path / "state" / "desktop.log").exists()
