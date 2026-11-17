"""Plan-based registration run.

Drives one registration run for the desktop app:

* logs in (optionally early, for a scheduled start);
* bids Plan A, then reads UTAR's registered-courses page to verify what was
  really registered instead of trusting the submit response;
* if a plan is incomplete, falls back to the next plan: every course of that
  plan that is not registered yet and does not clash with the timeslots already
  held is bid ("auto"), or offered to the user to choose first ("ask");
* optionally repeats the whole pass every N seconds until everything is
  registered (retry); courses already registered are always skipped, so
  starting again is a safe "retry failed";
* a pre-flight mode checks credentials, course codes, groups, availability and
  clashes without bidding.

Switching the group of an already-registered course is detected and reported
but not performed: the portal's change-class page has not been captured yet.
"""

import threading
import time
from copy import deepcopy
from datetime import datetime

from ..models.course import Course
from ..scrapers.errors import BrowserMissing, InvalidCredentials, LoginError, PortalClosed, PortalUnavailable
from ..scrapers.html_parser import sessions_clash
from ..utils.logger import setup_logger

logger = setup_logger(__name__)

SUCCESS_MESSAGE = "All courses registered successfully."
ATTENTION_MESSAGE = "Registration finished with items needing attention."
CANCELLED_MESSAGE = "Registration cancelled safely."


class StillClosed(Exception):
    """The portal accepted the login and then ended the session: registration is still closed."""


class Cancelled(Exception):
    """The user stopped the run."""


class RunError(Exception):
    """The run cannot continue; the message is shown to the user.

    source: "login" (shown in the login section) or "run".
    kind: finer reason, e.g. invalid_credentials, portal_closed, browser_missing.
    """

    def __init__(self, message, source="run", kind="error"):
        super().__init__(message)
        self.source = source
        self.kind = kind


LOG_LIMIT = 200


def empty_status() -> dict:
    return {
        "running": False,
        "phase": "idle",
        "message": "Ready",
        "completed": 0,
        "total": 0,
        "results": {},
        "registered": [],
        "credit": {},
        "plan": "",
        "attempt": 0,
        "proposal": None,
        "preflight": None,
        "start_at": None,
        "next_retry_at": None,
        # Waiting for registration to open: checks made so far and when the last one was (epoch s).
        "open_checks": 0,
        "last_check_at": None,
        # What is running: "run" or "preflight"; timers use started_at/ended_at (epoch s).
        "kind": "",
        "started_at": None,
        "ended_at": None,
        # Stop was requested; the run is finishing its current network call.
        "stopping": False,
        # Login progress: attempt n of max, reasons of failed attempts.
        "login": {"attempt": 0, "max": 0, "reasons": []},
        # Where the last error belongs: "login" or "run"; kind is finer detail.
        "error_source": None,
        "error_kind": None,
        # Pre-flight steps: [{id, label, state, detail, started_at, ended_at}]
        # state: pending | running | ok | warn | error | skipped
        "steps": [],
        # Activity log shown in the Logs tab: [{t, level, text}]
        "log": [],
    }


class StatusBoard:
    """Thread-safe run status shared with the UI."""

    def __init__(self):
        self._lock = threading.Lock()
        self._data = empty_status()

    def update(self, **values):
        with self._lock:
            message = values.get("message")
            if message and message != self._data.get("message"):
                level = "error" if values.get("phase") == "error" else "info"
                self._append_log(level, message)
            if values.get("running") is False and self._data.get("running") and "ended_at" not in values:
                values["ended_at"] = time.time()
            self._data.update(values)

    def _append_log(self, level, text):
        log = self._data.setdefault("log", [])
        log.append({"t": time.time(), "level": level, "text": text})
        del log[:-LOG_LIMIT]

    def log(self, text, level="info"):
        with self._lock:
            self._append_log(level, text)

    def mutate(self, function):
        with self._lock:
            function(self._data)

    def snapshot(self) -> dict:
        with self._lock:
            return deepcopy(self._data)


# ------------------------------------------------------------------ helpers

def slots_text(slots: dict) -> str:
    """{'L': [1, 2], 'T': [3]} -> 'L1/2 T3'."""
    parts = []
    for slot_type in ("L", "T", "P"):
        groups = slots.get(slot_type) or []
        if groups:
            parts.append(f"{slot_type}{'/'.join(str(group) for group in groups)}")
    return " ".join(parts)


def registered_groups(registered_course: dict) -> dict:
    return {item["type"]: item["group"] for item in registered_course.get("classes", [])}


def registered_text(registered_course: dict) -> str:
    return slots_text({key: [value] for key, value in registered_groups(registered_course).items()})


def verify_course(course: Course, registered_by_code: dict) -> str:
    """'confirmed' | 'different_group' | 'not_registered' for a wanted course."""
    registered = registered_by_code.get(course.code)
    if not registered:
        return "not_registered"
    groups = registered_groups(registered)
    for slot_type, wanted in course.slots.items():
        if wanted and groups.get(slot_type) not in wanted:
            return "different_group"
    return "confirmed"


def short_reason(text: str) -> str:
    """Last meaningful line of a scraper's multi-line result text."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[-1] if lines else "No response from the portal"


def create_scraper(method: str, headless: bool):
    # Imported here so importing this module stays cheap.
    if method == "Playwright":
        from ..scrapers.playwright_scraper import PlaywrightScraper

        scraper = PlaywrightScraper()
        scraper.set_headless_mode(bool(headless))
        return scraper
    from ..scrapers.beautifulsoup_scraper import BeautifulSoupScraper

    return BeautifulSoupScraper()


# ------------------------------------------------------------------- runner

MAX_TABS = 5  # browser tabs that may bid together


class PlanRunner:
    """One registration (or pre-flight) run over an ordered list of plans."""

    def __init__(self, plans, method="BeautifulSoup", headless=False, options=None, board=None,
                 scraper_factory=create_scraper):
        options = options or {}
        self.plans = [plan for plan in plans if plan["courses"]]
        self.method = method
        self.headless = headless
        self.fallback_mode = "ask" if options.get("fallback_mode") == "ask" else "auto"
        self.auto_retry_seconds = max(0, int(options.get("auto_retry_seconds") or 0))
        self.max_attempts = max(0, int(options.get("max_attempts") or 0))
        self.start_at = options.get("start_at") or None  # epoch seconds
        # Browser tabs bidding together (Playwright only; 1 = one course after another).
        self.tabs = max(1, min(MAX_TABS, int(options.get("tabs") or 1))) if method == "Playwright" else 1
        self._tabs_asked = max(1, min(MAX_TABS, int(options.get("tabs") or 1)))
        self.prelogin_seconds = 60
        # Scheduled runs: keep retrying login (never bidding) until this many
        # seconds after the start time while the portal looks closed/unreachable.
        self.login_grace_seconds = 180
        self.login_retry_seconds = 10
        self.closed_login_retry_seconds = 5  # start-now run: login retry while the portal is closed
        # While registration is closed (the portal shows no registration form) look again every
        # open_check_seconds, until it opens or the user presses Stop. Reading only, never bids.
        self.open_check_seconds = 2
        self._credentials = None
        self.board = board or StatusBoard()
        self._scraper_factory = scraper_factory
        self._scraper = None
        self._cancel = threading.Event()
        self._choice_ready = threading.Event()
        self._choice = None
        self._total = 0
        self._done = 0

    # ---- control from other threads
    def cancel(self):
        first = not self._cancel.is_set()
        self._cancel.set()
        self._choice_ready.set()
        if first and self.board.snapshot()["running"]:
            self.board.update(stopping=True, message="Stopping... waiting for the current step to finish safely.")
        scraper = self._scraper
        if scraper is not None:
            try:
                scraper.cancel()
            except Exception as error:  # noqa: BLE001
                logger.error("Error cancelling scraper: %s", error)

    def submit_choice(self, codes):
        """Answer an 'awaiting_choice' prompt with the course codes to bid."""
        self._choice = list(codes or [])
        self._choice_ready.set()

    # ---- small internals
    def _check_cancel(self):
        if self._cancel.is_set():
            raise Cancelled()

    def _sleep_until(self, deadline: float):
        while time.time() < deadline:
            self._check_cancel()
            time.sleep(min(0.2, max(0.0, deadline - time.time())))
        self._check_cancel()

    def _cleanup(self):
        scraper, self._scraper = self._scraper, None
        if scraper is not None:
            try:
                scraper.cleanup()
            except Exception as error:  # noqa: BLE001
                logger.error("Error during scraper cleanup: %s", error)

    @staticmethod
    def _final(phase, message, error=None):
        values = dict(running=False, phase=phase, message=message, proposal=None,
                      next_retry_at=None, stopping=False)
        if error is not None:
            values.update(error_source=error.source, error_kind=error.kind)
        return values

    # ---- pre-flight steps
    def _steps_init(self, steps):
        self.board.update(steps=[{"id": step_id, "label": label, "state": "pending", "detail": "",
                                  "started_at": None, "ended_at": None} for step_id, label in steps])

    def _step(self, step_id, state, detail=None):
        def apply(data):
            for step in data["steps"]:
                if step["id"] == step_id:
                    step["state"] = state
                    if detail is not None:
                        step["detail"] = detail
                    if state == "running":
                        step["started_at"] = time.time()
                        step["ended_at"] = None
                    elif step.get("started_at") and not step.get("ended_at"):
                        step["ended_at"] = time.time()
        self.board.mutate(apply)

    def _fail_running_steps(self, state, detail):
        def apply(data):
            for step in data["steps"]:
                if step["state"] == "running":
                    step["state"] = state
                    step["detail"] = detail
                    step["ended_at"] = time.time()
                elif step["state"] == "pending":
                    step["state"] = "skipped"
                    step["detail"] = "Not run because an earlier step did not finish."
        self.board.mutate(apply)

    # ---- entry points
    def _mark_started(self, kind):
        snapshot = self.board.snapshot()
        self.board.update(running=True, kind=snapshot["kind"] or kind,
                          started_at=snapshot["started_at"] or time.time(), ended_at=None)

    def run(self, student_id: str, password: str):
        final = None
        self._mark_started("run")
        try:
            if not self.plans:
                raise RunError("Add or import at least one course first.")
            self._scheduled_login(student_id, password)
            attempt = 0
            while True:
                attempt += 1
                self.board.update(attempt=attempt, next_retry_at=None)
                complete = self._run_plans()
                if complete or not self.auto_retry_seconds:
                    break
                if self.max_attempts and attempt >= self.max_attempts:
                    break
                retry_at = time.time() + self.auto_retry_seconds
                self.board.update(
                    phase="waiting_retry",
                    next_retry_at=retry_at,
                    message=f"Attempt {attempt} left courses unregistered. "
                            f"Retrying in {self.auto_retry_seconds}s...",
                )
                self._sleep_until(retry_at)
            final = self._final("complete" if complete else "error",
                                SUCCESS_MESSAGE if complete else ATTENTION_MESSAGE)
            if not complete:
                final.update(error_source="run", error_kind="incomplete")
        except Cancelled:
            final = self._final("cancelled", CANCELLED_MESSAGE)
        except RunError as error:
            final = self._final("error", str(error), error)
        except Exception as error:  # noqa: BLE001
            if self._cancel.is_set():
                final = self._final("cancelled", CANCELLED_MESSAGE)
            else:
                logger.exception("Registration run failed")
                final = self._final("error", f"Unexpected error: {error}", RunError("", "run", "unexpected"))
        finally:
            # Close the scraper first: once the status says 'finished' the user
            # may start again immediately, and the old browser must be gone.
            self._cleanup()
            if final is not None:
                self.board.update(**final)

    def preflight(self, student_id: str, password: str):
        """Check login, then (if there are plans) codes, groups, availability
        and clashes. Never bids. Works without any course plan: then only the
        login and registered-list checks run and the plan checks are skipped."""
        final = None
        self._mark_started("preflight")
        steps = [
            ("login", "Log in to the portal"),
            ("registered", "Read your registered courses"),
            ("plans", "Check course codes, groups and free places"),
            ("clashes", "Check your first choices for clashes"),
        ]
        if self.tabs > 1:
            steps.insert(2, ("tabs", f"Check {self.tabs} browser tabs on one login"))
        self._steps_init(steps)
        try:
            self._step("login", "running")
            self._login(student_id, password)
            self._step("login", "ok", "Login works.")
            self.board.update(phase="preflight", message="Pre-flight: reading your registered courses...")
            report = self._preflight_checks()
            problems = sum(1 for check in report if check["level"] == "error")
            warnings = sum(1 for check in report if check["level"] == "warn")
            if problems:
                message = f"Pre-flight found {problems} problem(s) and {warnings} warning(s)."
            elif warnings:
                message = f"Pre-flight passed with {warnings} warning(s)."
            elif not self.plans:
                message = "Pre-flight passed: login works. Course checks were skipped (no course plan yet)."
            else:
                message = "Pre-flight passed. Everything looks ready."
            final = self._final("preflight_done", message)
            final["preflight"] = {"problems": problems, "warnings": warnings, "checks": report}
        except Cancelled:
            self._fail_running_steps("skipped", "Stopped by you.")
            final = self._final("cancelled", "Pre-flight cancelled.")
        except RunError as error:
            self._fail_running_steps("error", str(error))
            final = self._final("error", str(error), error)
        except Exception as error:  # noqa: BLE001
            if self._cancel.is_set():
                self._fail_running_steps("skipped", "Stopped by you.")
                final = self._final("cancelled", "Pre-flight cancelled.")
            else:
                logger.exception("Pre-flight failed")
                self._fail_running_steps("error", f"Unexpected error: {error}")
                final = self._final("error", f"Unexpected error: {error}", RunError("", "run", "unexpected"))
        finally:
            # Close the scraper first: once the status says 'finished' the user
            # may start again immediately, and the old browser must be gone.
            self._cleanup()
            if final is not None:
                self.board.update(**final)

    # ---- login / scheduling
    def _login_progress(self, attempt, maximum, previous):
        reasons = []

        def apply(data):
            login = data.setdefault("login", {"attempt": 0, "max": 0, "reasons": []})
            if previous:
                login["reasons"] = (login.get("reasons") or []) + [previous]
            login["attempt"], login["max"] = attempt, maximum
            reasons.extend(login["reasons"])

        self.board.mutate(apply)
        text = f"Logging in: attempt {attempt}/{maximum}"
        if previous:
            text += f" (previous attempt: {previous})"
        self.board.update(message=text + "...")

    def _login(self, student_id: str, password: str):
        self._check_cancel()
        self._credentials = (student_id, password)
        self.board.update(phase="login", message="Connecting to UTAR course registration system...",
                          login={"attempt": 0, "max": 0, "reasons": []})
        if self._scraper is None:
            self._scraper = self._scraper_factory(self.method, self.headless)
        self._scraper.reset_cancellation()
        if hasattr(self._scraper, "on_login_progress"):
            self._scraper.on_login_progress = self._login_progress
        try:
            outcome = self._scraper.login(student_id, password)
        except InvalidCredentials as error:
            self._check_cancel()
            logger.warning("Login rejected (%s): %s", error.kind, error)
            raise RunError(str(error), "login", error.kind) from error
        except LoginError as error:
            self._check_cancel()
            logger.warning("Login failed (%s): %s", error.kind, error)
            if error.attempts:
                self.board.mutate(lambda data: data["login"].update(reasons=list(error.attempts)))
            raise RunError(str(error), "login", error.kind) from error
        except BrowserMissing as error:
            self._check_cancel()
            logger.warning("Login failed (%s): %s", error.kind, error)
            raise RunError(str(error), "login", error.kind) from error
        except Exception as error:  # noqa: BLE001
            self._check_cancel()
            raise RunError(f"Login error: {error}", "login", "login") from error
        self._check_cancel()
        if outcome is False:
            raise RunError("Login failed. Please check your credentials.", "login", "invalid_credentials")
        self.board.update(error_source=None, error_kind=None)

    def _scheduled_login(self, student_id: str, password: str):
        """Log in now, or shortly before a scheduled start, then wait for it.

        Before the registration window opens the portal may accept a login and
        then answer "session expired" (PortalClosed), or not answer at all.
        Logging in never submits a bid, so for a scheduled start we keep
        retrying the login every login_retry_seconds until
        login_grace_seconds after the start time. Wrong credentials stop at once.
        A start-now run that finds the portal closed at login retries every
        closed_login_retry_seconds until it gets in or Stop is pressed.
        """
        start_at = float(self.start_at) if self.start_at else None
        if not start_at or start_at <= time.time():
            tries = 0
            while True:  # portal closed at login: keep trying until it lets us in, or Stop
                tries += 1
                try:
                    self._login(student_id, password)
                    return
                except RunError as error:
                    if error.kind != "portal_closed":
                        raise
                    retry_at = time.time() + self.closed_login_retry_seconds
                    self.board.update(
                        phase="scheduled", next_retry_at=retry_at,
                        message=f"Login try {tries}: the portal accepted the login but registration looks closed. "
                                f"Trying again in {self.closed_login_retry_seconds:g}s until it opens; nothing has "
                                f"been bid. Press Stop to quit.")
                    self._sleep_until(retry_at)
        when = datetime.fromtimestamp(start_at).strftime("%H:%M:%S")
        self.board.update(phase="scheduled", start_at=start_at,
                          message=f"Waiting for scheduled start at {when}. Logging in "
                                  f"{self.prelogin_seconds}s before. Keep the app open.")
        self._sleep_until(start_at - self.prelogin_seconds)
        give_up_at = start_at + self.login_grace_seconds
        tries = 0
        while True:
            tries += 1
            try:
                self._login(student_id, password)
                break
            except RunError as error:
                if error.kind not in ("portal_closed", "portal_unavailable") or time.time() >= give_up_at:
                    raise
                retry_at = min(time.time() + self.login_retry_seconds, give_up_at)
                self.board.update(
                    phase="scheduled", next_retry_at=retry_at,
                    message=f"Login try {tries} before the start did not get in ({error.kind.replace('_', ' ')}). "
                            f"Trying again in {self.login_retry_seconds}s; nothing has been bid.",
                )
                self._sleep_until(retry_at)
        if time.time() < start_at:
            self.board.update(phase="scheduled", next_retry_at=None,
                              message=f"Logged in. Bidding starts at {when}. Keep the app open.")
            self._sleep_until(start_at)
        self.board.update(phase="verifying", next_retry_at=None, message="Starting: scheduled time reached.")

    # ---- registration open?
    def _first_course_code(self):
        return next((course.code for plan in self.plans for course in plan["courses"]), None)

    def _registration_open(self) -> bool:
        check = getattr(self._scraper, "registration_open", None)
        if check is None:
            return True  # a scraper without the check: never wait for something it cannot tell
        return bool(check(self._first_course_code()))

    def _login_again(self):
        """A new login before each look while registration is closed (the first version did this; reloading
        the page alone never makes the Register button appear). The portal answering "closed" or not
        answering is just "still closed"; wrong credentials and the like stop the run."""
        student_id, password = self._credentials
        scraper = self._scraper
        progress = getattr(scraper, "on_login_progress", None)
        scraper.on_login_progress = None  # keep the waiting message instead of "Logging in: attempt..."
        try:
            scraper.login(student_id, password)
        except PortalClosed as error:
            self._check_cancel()
            raise StillClosed() from error
        except PortalUnavailable as error:
            self._check_cancel()
            raise RuntimeError(f"logging in again failed: {error}") from error
        except LoginError as error:
            self._check_cancel()
            raise RunError(str(error), "login", error.kind) from error
        finally:
            scraper.on_login_progress = progress

    def _wait_until_open(self):
        """Wait, until Stop, for the portal to take bids. Nothing is bid while waiting and waiting does not
        use up retry attempts. Each look after the first logs in again first. A failed check is tried again."""
        checks = 0
        logged = set()
        while True:
            round_started = time.time()
            self._check_cancel()
            try:
                if checks:
                    self._login_again()  # reloading a closed page never shows the form: log in again
                is_open, problem = self._registration_open(), None
            except RunError:
                raise
            except StillClosed:
                is_open, problem = False, None
            except Exception as error:  # noqa: BLE001
                self._check_cancel()
                is_open, problem = False, str(error) or type(error).__name__
            checks += 1
            if is_open:
                if checks > 1:
                    self.board.update(phase="verifying", message="Registration is open. Starting...")
                return
            if problem and problem not in logged:
                logged.add(problem)
                self.board.log(f"Could not check whether registration is open: {problem}", "warn")
            wait = f"Checking again every {self.open_check_seconds:g}s. Press Stop to quit."
            self.board.update(
                phase="waiting_open", open_checks=checks, last_check_at=time.time(),
                message=(f"Could not check whether registration is open. {wait}" if problem
                         else f"Registration is not open yet. {wait} Nothing is bid while waiting."),
            )
            self._sleep_until(round_started + self.open_check_seconds)

    # ---- registered list
    def _refresh_registered(self, relogin=True) -> dict:
        """Read the registered-courses page; returns {code: registered_course}.

        If the session expired (e.g. after logging in early for a scheduled
        start) log in again once and re-read. Reading this page never bids,
        so the retry cannot cause a duplicate submission.
        """
        self._check_cancel()
        try:
            data = self._scraper.get_registered_courses()
        except Exception as error:  # noqa: BLE001
            self._check_cancel()
            if relogin and self._credentials and "expired" in str(error).lower():
                self.board.log("Session expired; logging in again before continuing.", "warn")
                self._login(*self._credentials)
                return self._refresh_registered(relogin=False)
            raise RunError(f"Could not read your registered courses: {error}") from error
        info = data.get("info") or {}
        self.board.update(
            registered=data.get("courses", []),
            credit={
                "total": info.get("Total Registered Credit Hour", ""),
                "max": info.get("Maximum Credit Hour", ""),
            },
        )
        return {course["code"]: course for course in data.get("courses", [])}

    # ---- results
    def _record(self, plan_name: str, course: Course, status: str, label: str, message: str,
                verified=None, registered=""):
        def apply(data):
            previous = data["results"].get(course.code, {})
            history = list(previous.get("history", []))
            line = f"{plan_name}: {message}"
            if not history or history[-1] != line:
                history.append(line)
            data["results"][course.code] = {
                "status": status,
                "label": label,
                "message": message,
                "plan": plan_name,
                "wanted": slots_text(course.slots),
                "registered": registered,
                "verified": verified,
                "history": history[-8:],
            }

        self.board.mutate(apply)

    def _apply_verification(self, plan_name: str, courses, snapshot: dict):
        """Replace submit-based results with what the portal actually shows."""
        current = self.board.snapshot()["results"]
        for course in courses:
            state = verify_course(course, snapshot)
            registered = registered_text(snapshot[course.code]) if course.code in snapshot else ""
            previous = current.get(course.code, {})
            if state == "confirmed":
                self._record(plan_name, course, "success", "Confirmed",
                             f"Registered as {registered}.", state, registered)
            elif state == "different_group":
                self._record(plan_name, course, "partial", "Different group",
                             f"Registered as {registered}; wanted {slots_text(course.slots)}.",
                             state, registered)
            else:
                if previous.get("status") == "success":
                    message = "The submit looked successful, but the course is not on your registered list."
                else:
                    message = previous.get("message") or "Not registered."
                self._record(plan_name, course, "failed", "Not registered", message, state, "")

    # ---- plans
    def _plan_complete(self, plan, snapshot: dict) -> bool:
        return all(course.code in snapshot for course in plan["courses"])

    def _run_plans(self) -> bool:
        """One pass over the plans. True when some plan is fully registered."""
        self._wait_until_open()
        self.board.update(phase="verifying", message="Reading your registered courses...")
        snapshot = self._refresh_registered()

        for index, plan in enumerate(self.plans):
            self._check_cancel()
            name = plan["name"]
            self.board.update(plan=name)

            if index == 0:
                targets = [course for course in plan["courses"] if course.code not in snapshot]
            else:
                targets = self._fallback_targets(plan, snapshot)

            self._bid(name, targets)

            self.board.update(phase="verifying", message=f"{name}: checking what was registered...")
            snapshot = self._refresh_registered()
            verify_these = plan["courses"] if index == 0 else targets
            self._apply_verification(name, verify_these, snapshot)

            if any(self._plan_complete(done, snapshot) for done in self.plans[:index + 1]):
                return True
        return False

    def _bid(self, plan_name: str, targets):
        self._total += len(targets)
        self.board.update(total=self._total)
        batch = getattr(self._scraper, "register_batch", None)
        if self.tabs > 1 and batch is not None:
            for start in range(0, len(targets), self.tabs):
                group = targets[start:start + self.tabs]
                self._check_cancel()
                self.board.update(
                    phase="bidding", completed=self._done,
                    message=f"{plan_name}: bidding {', '.join(c.code for c in group)} together "
                            f"({len(group)} tab(s))",
                )
                try:
                    answers = batch(group)
                except Exception as error:  # noqa: BLE001
                    self._check_cancel()
                    answers = [(str(error), False)] * len(group)
                for course, (text, success) in zip(group, answers):
                    self._record_bid(plan_name, course, text, success)
            return
        for course in targets:
            self._check_cancel()
            self.board.update(
                phase="bidding",
                completed=self._done,
                message=f"{plan_name}: bidding {course.code} - {course.name}",
            )
            try:
                text, success = self._scraper.register_courses([course])
            except Exception as error:  # noqa: BLE001
                self._check_cancel()
                text, success = str(error), False
            self._record_bid(plan_name, course, text, success)

    def _record_bid(self, plan_name: str, course: Course, text: str, success: bool):
        if not success:
            self._check_cancel()  # a stop mid-request is a cancel, not a failure
        self._done += 1
        if success:
            self._record(plan_name, course, "success", "Submitted", "Submitted; verifying...")
        else:
            self._record(plan_name, course, "failed", "Needs attention", short_reason(text))
        self.board.update(completed=self._done)

    # ---- fallback
    def _occupied(self, snapshot: dict) -> list:
        occupied = []
        for code, registered in snapshot.items():
            for item in registered.get("classes", []):
                occupied.append({
                    "code": code,
                    "label": f"{item['type']}{item['group']}",
                    "sessions": item["sessions"],
                })
        return occupied

    def _build_proposal(self, plan, snapshot: dict) -> list:
        """What the next plan would change, given what is registered now."""
        occupied = self._occupied(snapshot)
        items = []
        for course in plan["courses"]:
            self._check_cancel()
            item = {"code": course.code, "name": course.name, "wanted": slots_text(course.slots),
                    "action": "skip", "reason": "", "slots": {}}
            if course.code in snapshot:
                state = verify_course(course, snapshot)
                current = registered_text(snapshot[course.code])
                if state == "confirmed":
                    item.update(action="keep", reason=f"Already registered as {current}.")
                else:
                    item.update(
                        action="switch",
                        reason=f"Registered as {current}; this plan wants {item['wanted']}. "
                               "Switching groups is not automated yet.",
                    )
                items.append(item)
                continue

            try:
                offered = self._scraper.get_unit_slots(course.code)
            except Exception as error:  # noqa: BLE001
                self._check_cancel()
                item["reason"] = f"Could not load classes: {error}"
                items.append(item)
                continue
            if not offered:
                item["reason"] = "No classes found for this course code."
                items.append(item)
                continue

            chosen, reasons, picked_sessions = {}, [], []
            for slot_type, groups in course.slots.items():
                if not groups:
                    continue
                pick = None
                for group in groups:
                    slot = next((s for s in offered if s["type"] == slot_type and s["group"] == group), None)
                    label = f"{slot_type}{group}"
                    if slot is None:
                        reasons.append(f"{label} is not offered")
                        continue
                    if not slot["selectable"]:
                        reasons.append(f"{label} is full")
                        continue
                    clash = next((o for o in occupied + picked_sessions
                                  if sessions_clash(slot["sessions"], o["sessions"])), None)
                    if clash:
                        reasons.append(f"{label} clashes with {clash['code']} {clash['label']}")
                        continue
                    pick = slot
                    break
                if pick is None:
                    chosen = None
                    break
                chosen[slot_type] = [pick["group"]]
                picked_sessions.append({"code": course.code, "label": f"{slot_type}{pick['group']}",
                                        "sessions": pick["sessions"]})

            if chosen:
                item.update(action="add", slots=chosen,
                            reason=f"Free and no clash: {slots_text(chosen)}.")
                occupied.extend(picked_sessions)
            else:
                item["reason"] = "; ".join(reasons) or "No usable class."
            items.append(item)
        return items

    def _fallback_targets(self, plan, snapshot: dict) -> list:
        name = plan["name"]
        self.board.update(phase="verifying", message=f"{name}: checking which courses still fit...")
        proposal = self._build_proposal(plan, snapshot)
        by_code = {course.code: course for course in plan["courses"]}

        for item in proposal:
            if item["action"] == "skip":
                self._record(name, by_code[item["code"]], "failed", "Skipped", item["reason"])

        adds = [item for item in proposal if item["action"] == "add"]
        if adds and self.fallback_mode == "ask":
            chosen = self._ask(name, proposal)
            for item in adds:
                if item["code"] not in chosen:
                    self._record(name, by_code[item["code"]], "failed", "Skipped", "You chose not to bid this.")
            adds = [item for item in adds if item["code"] in chosen]

        return [Course(code=item["code"], name=item["name"], slots=item["slots"]) for item in adds]

    def _ask(self, plan_name: str, proposal: list) -> set:
        """Pause and let the user pick which fallback courses to bid."""
        self._choice_ready.clear()
        self._choice = None
        self.board.update(
            phase="awaiting_choice",
            proposal={"plan": plan_name, "items": proposal},
            message=f"{plan_name}: choose which courses to bid.",
        )
        while not self._choice_ready.wait(0.2):
            self._check_cancel()
        self._check_cancel()
        self.board.update(proposal=None)
        return set(self._choice or [])

    # ---- pre-flight
    def _preflight_tabs(self, add):
        """The several-tabs option: tabs of one login must all stay logged in (read-only check)."""
        if self._tabs_asked > 1 and self.method != "Playwright":
            add("warn", f"{self._tabs_asked} tabs were chosen, but tabs only work with the Playwright method. "
                        "This run will bid one course after another.")
            return
        if self.tabs <= 1:
            return
        if getattr(self._scraper, "check_tabs", None) is None:
            add("warn", "This connection cannot bid in several tabs; it will bid one course after another.")
            self._step("tabs", "skipped", "Not supported by this connection.")
            return
        self._step("tabs", "running")
        self.board.update(message=f"Pre-flight: opening {self.tabs} tabs on one login...")
        try:
            ok, detail = self._scraper.check_tabs(self.tabs)
        except Exception as error:  # noqa: BLE001
            self._check_cancel()
            ok, detail = False, f"could not check ({error})"
        if ok:
            add("ok", f"{self.tabs} browser tabs stay logged in together.")
            self._step("tabs", "ok", detail)
        else:
            add("warn", f"Several tabs may not work: {detail} Use 1 tab if bids fail.")
            self._step("tabs", "warn", detail)

    def _preflight_checks(self) -> list:
        checks = []

        def add(level, text):
            checks.append({"level": level, "text": text})

        self._step("registered", "running")
        snapshot = self._refresh_registered()
        credit = self.board.snapshot()["credit"]
        add("ok", "Login works.")
        if credit.get("total") or credit.get("max"):
            add("info", f"Credit hours registered: {credit.get('total') or '?'} of {credit.get('max') or '?'}.")
        self._step("registered", "ok", f"{len(snapshot)} course(s) registered at UTAR right now.")

        self._preflight_tabs(add)

        try:
            registration_is_open = self._registration_open()
        except Exception as error:  # noqa: BLE001
            self._check_cancel()
            registration_is_open = None
            add("warn", f"Could not tell whether registration is open ({error}).")
        if registration_is_open:
            add("ok", "Registration is open.")
        elif registration_is_open is False:
            add("warn", "Registration is not open yet. Start registration waits (checking every "
                       f"{self.open_check_seconds:g}s) until it opens; Stop ends the wait.")
            reason = "Registration is not open yet, so the classes cannot be checked."
            self._step("plans", "skipped", reason)
            self._step("clashes", "skipped", reason)
            return checks

        if not self.plans:
            reason = "No course plan yet. Add or import courses to check them."
            self._step("plans", "skipped", reason)
            self._step("clashes", "skipped", reason)
            add("info", "Course checks skipped: no course plan yet.")
            return checks

        self._step("plans", "running")
        self.board.update(message="Pre-flight: checking course codes, groups and free places...")
        clash_warnings = []
        for plan in self.plans:
            name = plan["name"]
            first_choices = []
            for course in plan["courses"]:
                self._check_cancel()
                if course.code in snapshot:
                    add("info", f"{name}: {course.code} is already registered "
                                f"as {registered_text(snapshot[course.code])}.")
                try:
                    offered = self._scraper.get_unit_slots(course.code)
                except Exception as error:  # noqa: BLE001
                    self._check_cancel()
                    add("error", f"{name}: {course.code} could not be loaded ({error}).")
                    continue
                if not offered:
                    add("error", f"{name}: {course.code} was not found or offers no classes.")
                    continue
                course_ok = True
                for slot_type, groups in course.slots.items():
                    if not groups:
                        continue
                    found = [next((s for s in offered if s["type"] == slot_type and s["group"] == group), None)
                             for group in groups]
                    missing = [f"{slot_type}{group}" for group, slot in zip(groups, found) if slot is None]
                    usable = [slot for slot in found if slot is not None and slot["selectable"]]
                    if missing:
                        add("error", f"{name}: {course.code} has no group {', '.join(missing)}.")
                        course_ok = False
                    if not usable:
                        if len(missing) < len(groups):
                            add("warn", f"{name}: {course.code} {slot_type} choices are all full right now.")
                        course_ok = False
                    else:
                        first_choices.append({"code": course.code,
                                              "label": f"{slot_type}{usable[0]['group']}",
                                              "sessions": usable[0]["sessions"]})
                if course_ok:
                    add("ok", f"{name}: {course.code} is available ({slots_text(course.slots)}).")
            for position, first in enumerate(first_choices):
                for second in first_choices[position + 1:]:
                    if first["code"] != second["code"] and sessions_clash(first["sessions"], second["sessions"]):
                        clash_warnings.append(f"{name}: {first['code']} {first['label']} clashes with "
                                              f"{second['code']} {second['label']}.")
        errors = sum(1 for check in checks if check["level"] == "error")
        warns = sum(1 for check in checks if check["level"] == "warn")
        self._step("plans", "error" if errors else "warn" if warns else "ok",
                   f"{errors} problem(s), {warns} warning(s)." if errors or warns else "All courses found.")
        self._step("clashes", "running")
        for text in clash_warnings:
            add("warn", text)
        self._step("clashes", "warn" if clash_warnings else "ok",
                   f"{len(clash_warnings)} clash(es)." if clash_warnings else "No clashes between first choices.")
        return checks
