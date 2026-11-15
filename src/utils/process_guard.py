"""Make child processes die with the app, even after a crash.

On Windows the app puts itself in a Job Object with
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE. Every process it starts afterwards
(Playwright's Node driver, Chromium, WebView2) inherits the job. When the app
exits for any reason, including a crash or "End task", Windows closes the job
handle and terminates exactly those processes. Other programs, including the
user's own Chrome or Edge windows, are never in this job and are not affected.

Normal shutdown still closes browsers politely first (DesktopApi.cleanup and
atexit); the job is the safety net.
"""

import sys

from .logger import setup_logger

logger = setup_logger(__name__)

_job_handle = None


def kill_children_on_exit() -> bool:
    """Returns True if the guard is active. Safe to call more than once."""
    global _job_handle
    if _job_handle is not None:
        return True
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class BASIC_LIMIT(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class EXTENDED_LIMIT(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BASIC_LIMIT),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
        KILL_ON_JOB_CLOSE = 0x2000
        BREAKAWAY_OK = 0x0800  # do not break child launches that ask to leave the job

        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise OSError(ctypes.get_last_error())
        info = EXTENDED_LIMIT()
        info.BasicLimitInformation.LimitFlags = KILL_ON_JOB_CLOSE | BREAKAWAY_OK
        if not kernel32.SetInformationJobObject(
                wintypes.HANDLE(job), JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError(ctypes.get_last_error())
        if not kernel32.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(kernel32.GetCurrentProcess())):
            raise OSError(ctypes.get_last_error())
        _job_handle = job  # keep the handle open for the life of the process
        logger.info("Child-process guard active (Windows job object)")
        return True
    except Exception as error:  # noqa: BLE001 - the app must still start
        logger.warning("Child-process guard not available: %s", error)
        return False
