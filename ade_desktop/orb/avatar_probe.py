"""Is the Electron avatar running? Read-only, and without running anything:
a Toolhelp process snapshot through ctypes (spawning `tasklist` would be
the app EXECUTING something, which it never does).

The avatar runs as ...\\adeos\\avatar\\node_modules\\electron\\dist\\electron.exe
(measured 2026-09-18), so the executable's own path says whose Electron it
is -- no command line needed. Anything that goes wrong reads as "not
running": this only decides whether the orb's microphone starts muted.
"""

from __future__ import annotations

import ctypes
import logging
import os
from ctypes import wintypes

log = logging.getLogger("ade_desktop.orb.avatar_probe")

AVATAR_PART = os.sep + os.path.join("adeos", "avatar") + os.sep
TH32CS_SNAPPROCESS = 0x2
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]


def _electron_pids() -> list[int]:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == wintypes.HANDLE(-1).value:
        return []
    pids = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == "electron.exe":
                pids.append(int(entry.th32ProcessID))
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return pids


def _image_path(pid: int) -> str:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        k32.CloseHandle(handle)


def is_avatar_path(path: str) -> bool:
    return AVATAR_PART.lower() in str(path).lower()


def avatar_running() -> bool:
    if os.name != "nt":
        return False
    try:
        return any(is_avatar_path(_image_path(pid)) for pid in _electron_pids())
    except Exception:  # noqa: BLE001 -- cannot tell reads as "not running"
        log.exception("avatar probe failed")
        return False
