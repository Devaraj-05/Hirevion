"""Live audio first (perf, 2026-11-24).

The interviewer listens and speaks in real time: its voice detector reads every 32 ms of the
candidate's microphone and its speech is cut into frames as it plays. On a busy machine it ran
at the same priority as a browser and an editor; on a PC at 90% CPU the detector fell 19 s behind
and the speech came out slower than it plays (heard as a stuck, flickering voice). It asks the
OS to run it before background work: on Windows the "above normal" class, elsewhere a nice of
-5, which needs CAP_SYS_NICE; without it the agent carries on as before.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from typing import Any

log = logging.getLogger(__name__)

NORMAL_PRIORITY_CLASS = 0x00000020
ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000
NICE = -5


def _kernel32() -> Any:
    """kernel32 with its handle types declared: left as ctypes' default int, the 64-bit process
    handle was cut to 32 bits and Windows refused the call."""
    from ctypes import wintypes

    kernel32 = getattr(ctypes, "windll").kernel32  # noqa: B009 - Windows only, typed off Windows
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.SetPriorityClass.restype = wintypes.BOOL
    kernel32.GetPriorityClass.argtypes = [wintypes.HANDLE]
    kernel32.GetPriorityClass.restype = wintypes.DWORD
    return kernel32


def _set_windows_priority(priority_class: int) -> bool:
    kernel32 = _kernel32()
    return bool(kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), priority_class))


def _priority_class() -> int:
    kernel32 = _kernel32()
    return int(kernel32.GetPriorityClass(kernel32.GetCurrentProcess()))


def favour_live_audio() -> bool:
    """Raises this process's scheduling priority; False when the OS refuses (it carries on)."""
    try:
        if sys.platform == "win32":
            raised = _set_windows_priority(ABOVE_NORMAL_PRIORITY_CLASS)
        else:
            # Set, never add (`os.nice` adds): main() and each job's prewarm both call this.
            prio_process = getattr(os, "PRIO_PROCESS", 0)
            if os.getpriority(prio_process, 0) > NICE:
                os.setpriority(prio_process, 0, NICE)
            raised = True
    except OSError:
        raised = False
    if not raised:
        log.info("Couldn't raise the interviewer's priority; live audio may lag on a busy machine")
    return raised
