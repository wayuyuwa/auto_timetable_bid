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
from ..scrapers.html_parser import sessions_clash
from ..utils.logger import setup_logger

logger = setup_logger(__name__)

SUCCESS_MESSAGE = "All courses registered successfully."
ATTENTION_MESSAGE = "Registration finished with items needing attention."
CANCELLED_MESSAGE = "Registration cancelled safely."


class Cancelled(Exception):
    """The user stopped the run."""


class RunError(Exception):
    """The run cannot continue; the message is shown to the user."""


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
    }


class StatusBoard:
    """Thread-safe run status shared with the UI."""

    def __init__(self):
        self._lock = threading.Lock()
        self._data = empty_status()

    def update(self, **values):
        with self._lock:
            self._data.update(values)

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
        self.prelogin_seconds = 60
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
        self._cancel.set()
        self._choice_ready.set()
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

    # ---- entry points
    def run(self, student_id: str, password: str):
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
            self.board.update(
                running=False,
                phase="complete" if complete else "error",
                message=SUCCESS_MESSAGE if complete else ATTENTION_MESSAGE,
                proposal=None,
                next_retry_at=None,
            )
        except Cancelled:
            self.board.update(running=False, phase="cancelled", message=CANCELLED_MESSAGE,
                              proposal=None, next_retry_at=None)
        except RunError as error:
            self.board.update(running=False, phase="error", message=str(error),
                              proposal=None, next_retry_at=None)
        except Exception as error:  # noqa: BLE001
            if self._cancel.is_set():
                self.board.update(running=False, phase="cancelled", message=CANCELLED_MESSAGE,
                                  proposal=None, next_retry_at=None)
            else:
                logger.exception("Registration run failed")
                self.board.update(running=False, phase="error", message=f"Unexpected error: {error}",
                                  proposal=None, next_retry_at=None)
        finally:
            self._cleanup()

    def preflight(self, student_id: str, password: str):
        try:
            if not self.plans:
                raise RunError("Add or import at least one course first.")
            self._login(student_id, password)
            self.board.update(phase="preflight", message="Checking your plans against the portal...")
            report = self._preflight_checks()
            problems = sum(1 for check in report if check["level"] == "error")
            warnings = sum(1 for check in report if check["level"] == "warn")
            if problems:
                message = f"Pre-flight found {problems} problem(s) and {warnings} warning(s)."
            elif warnings:
                message = f"Pre-flight passed with {warnings} warning(s)."
            else:
                message = "Pre-flight passed. Everything looks ready."
            self.board.update(
                running=False,
                phase="preflight_done",
                message=message,
                preflight={"problems": problems, "warnings": warnings, "checks": report},
            )
        except Cancelled:
            self.board.update(running=False, phase="cancelled", message="Pre-flight cancelled.")
        except RunError as error:
            self.board.update(running=False, phase="error", message=str(error))
        except Exception as error:  # noqa: BLE001
            if self._cancel.is_set():
                self.board.update(running=False, phase="cancelled", message="Pre-flight cancelled.")
            else:
                logger.exception("Pre-flight failed")
                self.board.update(running=False, phase="error", message=f"Unexpected error: {error}")
        finally:
            self._cleanup()

    # ---- login / scheduling
    def _login(self, student_id: str, password: str):
        self._check_cancel()
        self.board.update(phase="login", message="Connecting to UTAR course registration system...")
        self._scraper = self._scraper_factory(self.method, self.headless)
        self._scraper.reset_cancellation()
        try:
            outcome = self._scraper.login(student_id, password)
        except Exception as error:  # noqa: BLE001
            self._check_cancel()
            raise RunError(f"Login error: {error}") from error
        self._check_cancel()
        if outcome is False:
            raise RunError("Login failed. Please check your credentials.")

    def _scheduled_login(self, student_id: str, password: str):
        """Log in now, or shortly before a scheduled start, then wait for it."""
        start_at = float(self.start_at) if self.start_at else None
        if not start_at or start_at <= time.time():
            self._login(student_id, password)
            return
        when = datetime.fromtimestamp(start_at).strftime("%H:%M:%S")
        self.board.update(phase="scheduled", start_at=start_at,
                          message=f"Scheduled. Logging in shortly before {when}.")
        self._sleep_until(start_at - self.prelogin_seconds)
        self._login(student_id, password)
        self.board.update(phase="scheduled", message=f"Logged in. Bidding starts at {when}.")
        self._sleep_until(start_at)

    # ---- registered list
    def _refresh_registered(self) -> dict:
        """Read the registered-courses page; returns {code: registered_course}."""
        self._check_cancel()
        try:
            data = self._scraper.get_registered_courses()
        except Exception as error:  # noqa: BLE001
            self._check_cancel()
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
    def _preflight_checks(self) -> list:
        checks = []

        def add(level, text):
            checks.append({"level": level, "text": text})

        snapshot = self._refresh_registered()
        credit = self.board.snapshot()["credit"]
        if credit.get("total") or credit.get("max"):
            add("info", f"Credit hours registered: {credit.get('total') or '?'} of {credit.get('max') or '?'}.")
        add("ok", "Login works.")

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
                        add("warn", f"{name}: {first['code']} {first['label']} clashes with "
                                    f"{second['code']} {second['label']}.")
        return checks
