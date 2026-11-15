"""Where Playwright's Chromium lives, and how to install it.

Why this exists: when the app runs as a PyInstaller exe, Playwright sets
PLAYWRIGHT_BROWSERS_PATH=0 by itself (playwright/_impl/transport.py), which
makes it look for Chromium *inside* the bundle
(_internal/playwright/driver/package/.local-browsers). The bundle does not ship
a browser (it would add ~300 MB), so login failed with "Executable doesn't
exist". We point Playwright at the normal per-user browser folder instead
(the same one `playwright install` uses), and offer a one-click install.
"""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from .logger import setup_logger

logger = setup_logger(__name__)

ENV = "PLAYWRIGHT_BROWSERS_PATH"


def default_browsers_path() -> Path:
    """Playwright's standard per-user browser folder."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
        return Path(base) / "ms-playwright"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "ms-playwright"


def configure_browsers_path() -> str:
    """Call once at startup, before Playwright starts.

    Only the packaged app needs this. A path the user set explicitly is kept,
    except "0" (inside the bundle), which can never work for this app.
    """
    frozen = getattr(sys, "frozen", False)
    current = os.environ.get(ENV)
    if frozen and (not current or current == "0"):
        os.environ[ENV] = str(default_browsers_path())
        logger.info("Playwright browsers path set to %s", os.environ[ENV])
    return os.environ.get(ENV, "")


def browsers_path() -> Path:
    current = os.environ.get(ENV)
    if current and current != "0":
        return Path(current)
    return default_browsers_path()


def _driver_dir() -> Path:
    import playwright

    return Path(playwright.__file__).parent / "driver"


def expected_chromium_revision() -> str:
    try:
        data = json.loads((_driver_dir() / "package" / "browsers.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        logger.warning("Cannot read Playwright browsers.json: %s", error)
        return ""
    for browser in data.get("browsers", []):
        if browser.get("name") == "chromium":
            return str(browser.get("revision", ""))
    return ""


def chromium_status() -> dict:
    """{'installed': bool, 'path': folder, 'revision': str} without starting a browser."""
    revision = expected_chromium_revision()
    folder = browsers_path() / f"chromium-{revision}" if revision else browsers_path()
    installed = bool(revision) and (folder / "INSTALLATION_COMPLETE").exists()
    return {"installed": installed, "path": str(folder), "revision": revision}


def missing_browser_message() -> str:
    status = chromium_status()
    return (
        "The Playwright method needs its Chromium browser, which is not installed yet "
        f"(expected in {status['path']}). Click \"Install browser\" in Login & settings "
        "(about 150 MB download, one time), or switch the connection method to BeautifulSoup."
    )


_install_lock = threading.Lock()


def install_chromium(on_output=None, timeout=900) -> tuple[bool, str]:
    """Download Chromium with Playwright's bundled driver (works in the exe too).

    Returns (ok, last output line). Only one install runs at a time.
    """
    from playwright._impl._driver import compute_driver_executable, get_driver_env

    if not _install_lock.acquire(blocking=False):
        return False, "An install is already running."
    try:
        node, cli = compute_driver_executable()
        env = get_driver_env()
        env[ENV] = str(browsers_path())
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        process = subprocess.Popen(
            [node, cli, "install", "chromium"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=flags,
        )
        last = ""
        for line in process.stdout:
            line = line.strip()
            if line:
                last = line
                if on_output:
                    on_output(line)
        code = process.wait(timeout=timeout)
        ok = code == 0 and chromium_status()["installed"]
        logger.info("Chromium install finished with code %s (installed=%s)", code, ok)
        return ok, last or f"Installer exited with code {code}"
    except Exception as error:  # noqa: BLE001
        logger.error("Chromium install failed: %s", error)
        return False, str(error)
    finally:
        _install_lock.release()
