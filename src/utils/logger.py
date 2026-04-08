"""Logging utilities with structured context support."""

import contextvars
import logging
import logging.handlers
import sys
import traceback
import uuid

from .config import ERROR_LOG_FILE, LOG_FILE, LOG_LEVEL

_configured = False
_run_id = uuid.uuid4().hex[:8]
_task_context = contextvars.ContextVar("task_context", default="main")


class ContextFilter(logging.Filter):
    """Inject stable context fields into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = _run_id
        record.task = _task_context.get()
        return True


def _configure_root_logger() -> None:
    global _configured
    if _configured:
        return

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, str(LOG_LEVEL).upper(), logging.INFO))

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | run=%(run_id)s task=%(task)s | %(message)s"
    )

    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    error_handler = logging.handlers.RotatingFileHandler(
        ERROR_LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    context_filter = ContextFilter()
    file_handler.addFilter(context_filter)
    error_handler.addFilter(context_filter)
    console_handler.addFilter(context_filter)

    root_logger.handlers = []
    root_logger.addHandler(file_handler)
    root_logger.addHandler(error_handler)
    root_logger.addHandler(console_handler)
    _configured = True


def setup_logger(name: str) -> logging.Logger:
    """Return a configured namespaced logger."""
    _configure_root_logger()
    return logging.getLogger(name)


def set_log_context(task_name: str) -> contextvars.Token:
    """Set thread/task-local logging context label."""
    return _task_context.set(task_name)


def reset_log_context(token: contextvars.Token) -> None:
    """Reset thread/task-local logging context label."""
    _task_context.reset(token)


def handle_uncaught_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    crash_logger = logging.getLogger("crash_logger")
    exception_info = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    crash_logger.critical(f"APPLICATION CRASH DETECTED:\n{exception_info}")
    sys.__excepthook__(exc_type, exc_value, exc_traceback)


def setup_crash_logging():
    crash_logger = setup_logger("crash_logger")
    sys.excepthook = handle_uncaught_exception
    return crash_logger