"""One ConPTY per shell session.

**THE SPAWN CONTRACT IS THE FEATURE.** Ade OS's shell runs
`powershell -NoProfile -NonInteractive -NoLogo -ExecutionPolicy Bypass
-Command -`, and every one of those flags removes something Ray asked for:

    -NoProfile             no profile, so none of the modules  (req 9)
    -NonInteractive        no prompts, no Read-Host, no PSReadLine  (req 2)
    -ExecutionPolicy Bypass  WIDER than this machine's real policy  (req 5)
    -Command -             a pipe, not a console: no TUI, no colour

Dropping them is not a style choice; each removal IS a requirement. Only
`-NoLogo` is kept, because it suppresses a banner rather than a capability.

`env=None` is load-bearing. The pty inherits THIS process's environment,
and Ray launched this process, so that is his login environment --
requirement 4. Ade OS could never satisfy it: it is started through WMI
`Win32_Process.Create`, through which environment does not propagate, so a
server-side pty inherits something nobody chose.

**PERMISSIONS.** The pty runs under this app's own token: non-elevated
unless the app itself was launched elevated, with no self-elevation and no
`runas`. Elevation is `Start-Process pwsh -Verb RunAs`, which raises the
real Windows UAC dialog exactly as in any terminal. `Permission.check()` is
NOT consulted -- this is Ray's keyboard, in the posture
`adeos/api/terminal_session.py` documents for its own shell, and narrower:
this one has no HTTP route, no schema and no tool-registry entry, so no
model can reach it and `tailscale serve` has nothing to proxy.

pywinpty is synchronous, so one reader THREAD per session pumps `read()`
into a queued Qt signal -- the bridge shape Jupyter's terminado uses on
Windows, and the one `adeos/api/term.py` already uses here. Nothing in this
file touches a widget.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading

from PySide6.QtCore import QObject, Signal

log = logging.getLogger("ade_desktop.shell.pty")

READ_SIZE = 8192
# How long stop() waits for the reader thread to leave read() before it
# gives up on terminate(). Generous: the alternative to waiting is a crash.
JOIN_TIMEOUT_S = 3.0


def shell_command() -> str:
    """pwsh 7 when it is installed -- it is what Ray actually uses -- else
    Windows PowerShell, so a box without pwsh still gets a terminal."""
    exe = "pwsh.exe" if shutil.which("pwsh") else "powershell.exe"
    return f"{exe} -NoLogo"


def default_cwd() -> str:
    """Home, where a real shell opens. Not the checkout: a terminal that
    starts in the repo is a project tool, and requirement 2 is that this one
    navigates the whole computer."""
    return os.environ.get("USERPROFILE") or os.path.expanduser("~")


def _taskkill_tree(pid) -> None:
    """End the shell AND everything under it.

    Terminating pwsh alone leaves a native child (python, npm, pytest)
    running and holding the output pipe -- measured 2026-09-18 in the Code
    piece, and the reason terminal_session.py grew the same helper.
    """
    if not pid:
        return
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, timeout=15,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        pass                            # the caller's terminate() still follows


class PtySession(QObject):
    output = Signal(str)                # queued: emitted from the reader thread
    exited = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._proc = None
        self._thread: threading.Thread | None = None
        self._stopping = False

    @property
    def pid(self):
        return getattr(self._proc, "pid", None)

    def is_alive(self) -> bool:
        try:
            return self._proc is not None and self._proc.isalive()
        except Exception:               # noqa: BLE001 - the pty went away
            return False

    def start(self, cols: int = 120, rows: int = 30,
              cwd: str | None = None) -> None:
        if self._proc is not None:
            return
        from winpty import PtyProcess
        self._stopping = False
        self._proc = PtyProcess.spawn(
            shell_command(),
            cwd=cwd or default_cwd(),
            env=None,                   # inherit: THIS process's env is Ray's
            dimensions=(max(1, int(rows)), max(1, int(cols))),  # (rows, cols)
        )
        self._thread = threading.Thread(target=self._read_loop, daemon=True,
                                        args=(self._proc,),
                                        name=f"pty-{self._proc.pid}")
        self._thread.start()

    def _read_loop(self, proc) -> None:
        """THE READER OWNS THE TEARDOWN, and that is a safety property, not
        a style choice.

        pywinpty's `read()` is a socket `recv()` fed by pywinpty's own
        internal thread, and `terminate()` frees that socket. Calling
        terminate() from the GUI thread while this one is inside read() is
        a use-after-free, and Windows answers with `0xc0000005` -- which
        kills the process outright and cannot be caught. Measured
        2026-09-24: the end-to-end test crashed the interpreter on every
        run until teardown moved in here.

        So stop() only kills the process tree and returns. The dead shell
        closes the pty, read() raises EOFError, and THIS thread -- the only
        one that ever touches the socket -- terminates it on the way out.
        Nothing is freed under a reader, because the reader is the freer.
        """
        try:
            while proc.isalive():
                try:
                    data = proc.read(READ_SIZE)
                except EOFError:
                    break
                except OSError:
                    break
                if data:
                    self.output.emit(data)      # queued: crosses to the GUI thread
        except Exception:                       # noqa: BLE001 - the pty went away
            pass
        finally:
            stopping = self._stopping
            try:
                code = int(getattr(proc, "exitstatus", 0) or 0)
            except (TypeError, ValueError):
                code = 0
            try:
                proc.terminate(force=True)      # safe: we have left read()
            except Exception:                   # noqa: BLE001 - already dead
                pass
            if not stopping:
                self.exited.emit(code)

    def write(self, text: str) -> None:
        if self._proc is None or not text:
            return
        try:
            self._proc.write(text)
        except Exception:               # noqa: BLE001 - the shell exited under us
            log.debug("write to a dead pty")

    def resize(self, cols: int, rows: int) -> None:
        if self._proc is None:
            return
        try:
            self._proc.setwinsize(max(1, int(rows)), max(1, int(cols)))
        except Exception:               # noqa: BLE001 - a bad resize is not a dead shell
            pass

    def stop(self) -> None:
        """NO TAB, NO SHELL. Idempotent: quit calls it after a close did.

        Kills the process TREE and returns. The children go first, while
        they can still be found under the shell -- terminating the shell
        alone orphans a native child (python, npm, pytest) that keeps
        holding the pipe.

        It does NOT terminate the pty, and must not: the reader thread is
        sitting in a socket recv() and freeing that socket under it is an
        access violation, which kills the app rather than raising. The
        reader does it on the way out (see _read_loop). Nor does this wait
        for the reader -- measured 2026-09-24, it takes ~5.3 s to notice
        EOF, and quitting with four shells open must not take twenty
        seconds. The thread is a daemon; the OS reclaims it either way.
        """
        proc, self._proc = self._proc, None
        self._thread = None
        if proc is None:
            return
        self._stopping = True
        _taskkill_tree(getattr(proc, "pid", None))
