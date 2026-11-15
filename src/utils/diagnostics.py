"""Opt-in diagnostic files for troubleshooting (config.ini [Logging] debug_dumps).

Files go to logs/debug/ with a timestamp and the operation name. Everything is
sanitised first: passwords, captcha answers, cookies, session ids and
IC numbers are masked, and bodies are truncated.
"""

import os
import re
import threading
import time

from .config import DEBUG_DIR, DEBUG_DUMPS
from .logger import setup_logger

logger = setup_logger(__name__)

MAX_BODY = 20_000
# reqFregkey is the student ID: personal data, not needed to debug a run.
SECRET_FIELDS = {"reqpassword", "password", "kaptchafield", "prekap", "reqfregkey"}
SECRET_HEADERS = {"cookie", "set-cookie", "authorization"}
_IC_NUMBER = re.compile(r"\b\d{6}-\d{2}-\d{4}\b")
_SESSION_ID = re.compile(r"(jsessionid=|passid=)[^;&\s\"']+", re.IGNORECASE)
_STUDENT_ID_VALUE = re.compile(r"(name=[\"']?reqFregkey[\"']?[^>]*value=[\"'])[^\"']*", re.IGNORECASE)
_PASSWORD_VALUE = re.compile(r"(name=[\"']?reqPassword[\"']?[^>]*value=[\"'])[^\"']*", re.IGNORECASE)
_counter_lock = threading.Lock()
_counter = 0


def enabled() -> bool:
    return DEBUG_DUMPS


def on_mock() -> bool:
    """True when the app talks to a mock portal (UTAR_BASE_URL is only set for that)."""
    return bool(os.getenv("UTAR_BASE_URL"))


def pages_enabled() -> bool:
    """Playwright page captures: on with debug_dumps, and always against the mock."""
    return DEBUG_DUMPS or on_mock()


def debug_dir() -> str:
    """Where captures go; UTAR_DEBUG_DIR overrides logs/debug (used by the E2E run)."""
    return os.getenv("UTAR_DEBUG_DIR") or DEBUG_DIR


def sanitize_text(text: str) -> str:
    text = _IC_NUMBER.sub("XXXXXX-XX-XXXX", text or "")
    text = _SESSION_ID.sub(r"\1***", text)
    text = _STUDENT_ID_VALUE.sub(r"\1***", text)
    return _PASSWORD_VALUE.sub(r"\1***", text)


def sanitize_form(data) -> dict:
    if not isinstance(data, dict):
        return {}
    return {key: ("***" if key.lower() in SECRET_FIELDS else value) for key, value in data.items()}


def sanitize_headers(headers) -> dict:
    return {key: ("***" if key.lower() in SECRET_HEADERS else value) for key, value in dict(headers or {}).items()}


def _path(operation: str, extension: str) -> str:
    global _counter
    with _counter_lock:
        _counter += 1
        number = _counter
    folder = debug_dir()
    os.makedirs(folder, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", operation)[:60]
    return os.path.join(folder, f"{time.strftime('%Y%m%d-%H%M%S')}-{number:04d}-{safe}.{extension}")


def dump_http(operation: str, response, form=None):
    """Write one sanitised request/response summary. Never raises."""
    if not DEBUG_DUMPS or response is None:
        return None
    try:
        request = response.request
        body = sanitize_text(response.text)
        if len(body) > MAX_BODY:
            body = body[:MAX_BODY] + f"\n... [truncated, {len(response.text)} chars total]"
        lines = [
            f"operation: {operation}",
            f"time: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"request: {request.method} {sanitize_text(request.url)}",
            f"request headers: {sanitize_headers(request.headers)}",
            f"form: {sanitize_form(form)}",
            f"status: {response.status_code} ({response.elapsed.total_seconds():.2f}s)",
            f"response headers: {sanitize_headers(response.headers)}",
            "",
            body,
        ]
        path = _path(operation, "txt")
        with open(path, "w", encoding="utf-8") as file:
            file.write("\n".join(lines))
        return path
    except Exception as error:  # noqa: BLE001 - diagnostics must never break a run
        logger.debug("Could not write HTTP dump for %s: %s", operation, error)
        return None


def save_page(page, operation: str):
    """Playwright: save a screenshot and the page HTML (sanitised). Never raises.
    Active with debug_dumps, and always when running against the mock portal."""
    if not pages_enabled() or page is None:
        return None
    save_screenshot(page, operation)
    try:
        html = sanitize_text(page.content())
        path = _path(operation, "html")
        with open(path, "w", encoding="utf-8") as file:
            file.write(f"<!-- {operation} | {time.strftime('%Y-%m-%d %H:%M:%S')} | {sanitize_text(page.url)} -->\n")
            file.write(html)
        return path
    except Exception as error:  # noqa: BLE001
        logger.debug("Could not save page HTML for %s: %s", operation, error)
        return None


def save_screenshot(page, operation: str):
    """Save a Playwright page screenshot. Never raises."""
    if not pages_enabled() or page is None:
        return None
    try:
        path = _path(operation, "png")
        page.screenshot(path=path, full_page=True)
        return path
    except Exception as error:  # noqa: BLE001
        logger.debug("Could not save screenshot for %s: %s", operation, error)
        return None
