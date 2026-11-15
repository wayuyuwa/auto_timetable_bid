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


class AccountNotAllowed(LoginError):
    """The portal refused this account (e.g. study status not active, adviser
    not consulted). The message is the portal's own text. Retrying will not help."""

    kind = "account_not_allowed"


# login.jsp?message=<code> redirects seen on the real portal.
REJECTION_CODES = {"notActive", "notConsultAdviser"}
INVALID_CREDENTIAL_CODES = {"loginError"}
FALLBACK_TEXT = {
    "notActive": "Your study status is not allowed to access this system, please check with faculty officer",
    "notConsultAdviser": "The portal requires you to consult your academic adviser before registration",
    "loginError": "Invalid Student ID or Password",
}


def portal_rejection(code: str, portal_text: str):
    """Exception for a login.jsp?message=<code> redirect, or None if the code
    is unknown (the caller then retries and records the text as the reason)."""
    text = (portal_text or FALLBACK_TEXT.get(code, "")).strip()
    if code in INVALID_CREDENTIAL_CODES:
        return InvalidCredentials(f"Login failed: UTAR says \"{text or 'Invalid Student ID or Password'}\". "
                                  "Please check your credentials.")
    if code in REJECTION_CODES:
        return AccountNotAllowed(f"UTAR refused this account: \"{text or code}\" (code {code}). "
                                 "This is decided by UTAR, not the app; retrying will not help until it is resolved.")
    return None


class BrowserMissing(RuntimeError):
    """Playwright's Chromium browser is not installed where Playwright looks."""

    kind = "browser_missing"
