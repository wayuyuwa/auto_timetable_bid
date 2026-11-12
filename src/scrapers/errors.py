"""Typed login/portal errors shared by both scrapers.

They let the runner and the UI tell apart failures that need different
handling: wrong credentials (stop, ask the user), the portal answering
"session expired" right after login (usually: registration not open yet),
and the portal not responding at all.
"""


class LoginError(Exception):
    """Base class for login failures. `attempts` lists one reason per attempt."""

    kind = "login"

    def __init__(self, message, attempts=None):
        super().__init__(message)
        self.attempts = list(attempts or [])


class InvalidCredentials(LoginError):
    """The portal rejected the student ID or password. Retrying will not help."""

    kind = "invalid_credentials"


class PortalClosed(LoginError):
    """Login was accepted but every page answered "session expired".

    This is what the real portal does outside the registration window.
    Retrying later is safe: logging in never submits a bid.
    """

    kind = "portal_closed"


class PortalUnavailable(LoginError):
    """The portal did not respond, or kept failing for other reasons."""

    kind = "portal_unavailable"


class BrowserMissing(RuntimeError):
    """Playwright's Chromium browser is not installed where Playwright looks."""

    kind = "browser_missing"
