"""The shell: a real ConPTY terminal, local to this app.

**THIS IS RAY'S KEYBOARD, NOT A CAPABILITY.** It is registered in no tool
registry, reachable by no model, and `Permission.check()` is never consulted
-- the same way it is not consulted when Ray opens PowerShell himself. That
is the posture `adeos/api/terminal_session.py` and `adeos/api/term.py`
already document for their own shells.

It is NARROWER than either of those. Ade OS's `/v1/terminal` is an HTTP
endpoint on a server that `tailscale serve` proxies to the tailnet, and
`/ws/terminal` would be the same. This pty lives inside the desktop
process: there is no route to it, no schema for it, and nothing to serve.

Why local rather than through Ade OS at all (Ray, 2026-09-24, requirements
2, 4 and 5): a pty spawned by the API server inherits the SERVER's
environment, and Ade OS is started through WMI `Win32_Process.Create`,
through which environment does not propagate. "The Windows system env must
be available" is therefore unreachable from that side of the wire at any
price. Spawned here, the pty inherits this process's environment -- and
Ray launched this process, so that is his login environment.

This package imports NOTHING at its top level, deliberately. `screen.py` and
`keys.py` are pure -- no Qt, no process -- so their behaviour is testable
headless, and re-exporting `ShellPane` here would drag Qt into every one of
those tests. Import `ade_desktop.shell.pane.ShellPane` directly.
"""
