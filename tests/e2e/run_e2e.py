"""
End-to-end test run with screenshots. No AI involved; run it any time:

    venv\\Scripts\\python tests\\e2e\\run_e2e.py            # build frontend, run all cases
    venv\\Scripts\\python tests\\e2e\\run_e2e.py --no-build # reuse web/dist
    venv\\Scripts\\python tests\\e2e\\run_e2e.py --only bs_  # cases whose id contains "bs_"
    venv\\Scripts\\python tests\\e2e\\run_e2e.py --headed    # watch the UI while it runs

How it works:
- Builds the Vue app (web/dist) and serves it on a local port.
- Starts src/mock_server.py in-process (UTAR look-alike, no real UTAR traffic).
- Opens the UI in Chromium and replaces pywebview's window.pywebview.api with a
  bridge to the real Python DesktopApi, so UI + backend + scrapers run for real.
- Every case uses a fresh temporary SQLite database.
- Writes one PNG per case and report.md to tests/e2e/screenshots/ (gitignored).
Exit code is 1 if any case fails.
"""

import argparse
import functools
import http.server
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
E2E_DIR = os.path.join(ROOT, "tests", "e2e")
FIXTURES = os.path.join(E2E_DIR, "fixtures")
OUT_DIR = os.path.join(E2E_DIR, "screenshots")
WEB_DIR = os.path.join(ROOT, "web")
DIST_DIR = os.path.join(WEB_DIR, "dist")

# Mock delay for the timeout scenario; the BeautifulSoup scraper times out after 10 s.
TIMEOUT_SCENARIO_DELAY = 12
RUN_TIMEOUT_SECONDS = 180

MOCK_COURSE = {"code": "MOCK1001", "name": "Mock Course", "slots": {"L": [1], "T": [2]}}

BRIDGE_SCRIPT = """
(() => {
  const handler = { get: (_, name) => (...args) => window.__desktopCall(String(name), args) };
  window.pywebview = { api: new Proxy({}, handler) };
})();
"""


# ---------------------------------------------------------------- infrastructure

def build_frontend():
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("npm is required to build web/ (or pass --no-build)")
    if not os.path.isdir(os.path.join(WEB_DIR, "node_modules")):
        subprocess.check_call([npm, "ci", "--no-audit", "--no-fund"], cwd=WEB_DIR)
    subprocess.check_call([npm, "run", "build"], cwd=WEB_DIR)


def start_static_server(directory):
    handler = functools.partial(QuietStaticHandler, directory=directory)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class QuietStaticHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def start_mock_server():
    from src.mock_server import MockHandler

    class QuietMockHandler(MockHandler):
        def log_message(self, *args):
            pass

        def handle(self):
            try:
                super().handle()
            except (ConnectionError, OSError):
                pass  # client gave up on a delayed response (timeout/cancel cases)

    server = ThreadingHTTPServer(("127.0.0.1", 0), QuietMockHandler)
    server.daemon_threads = True
    server.base_path = "/portal/courseRegStu"
    server.scenario = "success"
    server.delay = TIMEOUT_SCENARIO_DELAY
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class CaseFailed(AssertionError):
    pass


def check(condition, message):
    if not condition:
        raise CaseFailed(message)


class Harness:
    """Shared browser, servers, and per-case app instances."""

    def __init__(self, browser, app_url, mock, show_app_browser):
        self.browser = browser
        self.app_url = app_url
        self.mock = mock
        self.show_app_browser = show_app_browser
        self.tmp = tempfile.mkdtemp(prefix="utar_e2e_")
        self.page = None
        self.api = None
        self.calls = []
        self.dry_start = False

    # --- app lifecycle
    def open_app(self, courses=None, db_name=None, scenario="success", plans=None, keep_mock_state=False):
        from src.mock_server import reset_state
        from src.storage.database import Database
        from src.web_backend import DesktopApi

        self.close_app()
        if not keep_mock_state:
            reset_state(self.mock)  # registrations must not leak between cases
        self.mock.scenario = scenario
        self.calls = []
        self.dry_start = False
        db_path = os.path.join(self.tmp, db_name or f"{time.time_ns()}.db")
        self.db_path = db_path
        self.api = DesktopApi(database=Database(db_path))
        if courses is not None:
            self.api.save_courses(courses)
        if plans is not None:
            self.api.save_plans(plans)
        self.page = self.browser.new_page(
            viewport={"width": int(os.environ.get("E2E_WIDTH", "1280")), "height": 900})
        self.page.expose_function("__desktopCall", self._bridge)
        self.page.add_init_script(BRIDGE_SCRIPT)
        self.page.goto(self.app_url)
        self.page.locator("[data-bridge=ready]").wait_for(timeout=10_000)
        self.page.locator(".notice", has_text="course(s) ready").wait_for(timeout=10_000)
        return self.page

    def close_app(self):
        if self.api:
            self.api.cleanup()
            self.api = None
        if self.page:
            self.page.close()
            self.page = None

    def _bridge(self, method, args):
        self.calls.append((method, list(args)))
        if method.startswith("_") or not callable(getattr(self.api, method, None)):
            raise RuntimeError(f"Unknown desktop API method: {method}")
        if method == "start" and self.dry_start:
            return self.api.get_status()
        return getattr(self.api, method)(*args)

    # --- UI helpers
    def tab(self, name):
        """Open a section tab (Courses, Login & settings, Pre-flight, Registration, Logs)."""
        self.page.locator("nav.tabs").get_by_role("tab", name=name).click()

    def import_file(self, path, mode=None, new_name=None):
        """Pick a file and finish the import dialog (mode: None = dialog default)."""
        self.tab("Courses")
        self.page.locator("input[type=file]").set_input_files(path)
        dialog = self.page.locator(".modal-dialog", has_text="IMPORT TIMETABLE")
        dialog.wait_for()
        if mode == "new":
            dialog.get_by_text("Import as new plan", exact=True).click()
            if new_name:
                dialog.get_by_label("New plan name").fill(new_name)
        elif mode == "replace":
            dialog.locator("input[value=replace]").check()
        dialog.locator("button[type=submit]").click()

    def notice(self):
        return self.page.locator(".notice").inner_text().strip()

    def wait_notice(self, text, timeout=10_000):
        self.page.locator(".notice", has_text=text).wait_for(timeout=timeout)

    def row(self, code):
        if not self.page.locator("nav.tabs [aria-selected=true]", has_text="Courses").count():
            self.tab("Courses")
        return self.page.locator("tbody tr", has_text=code)

    def fill_course_dialog(self, code="", name="", lecture="", tutorial="", practical=""):
        page = self.page
        page.get_by_label("Course code").fill(code)
        page.get_by_label("Course name").fill(name)
        page.get_by_label("Lecture slots").fill(lecture)
        page.get_by_label("Tutorial slots").fill(tutorial)
        page.get_by_label("Practical slots").fill(practical)

    def fill_credentials(self, student_id="2103370", password="mock-password"):
        self.tab("Login & settings")
        self.page.get_by_label("Student ID").fill(student_id)
        self.page.get_by_label("Password", exact=True).fill(password)

    def choose_method(self, method):
        self.tab("Login & settings")
        self.page.get_by_label("Connection method").select_option(method)
        if method == "Playwright":
            self.page.get_by_label("Browser visible").set_checked(self.show_app_browser, force=True)

    def wait_run_finished(self, timeout=RUN_TIMEOUT_SECONDS):
        deadline = time.time() + timeout
        status = self.api.get_status()
        while time.time() < deadline:
            status = self.api.get_status()
            if not status["running"] and status["phase"] != "idle":
                break
            self.page.wait_for_timeout(300)  # keeps the page/bridge event loop running
        else:
            raise CaseFailed(f"Run did not finish within {timeout}s; last status {status}")
        # Let the UI's 700 ms status poll render the final state.
        self.page.locator(".current-message", has_text=status["message"][:40]).wait_for(timeout=5_000)
        self.page.wait_for_timeout(300)
        return status

    def wait_phase(self, phase, timeout=60):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.api.get_status()["phase"] == phase:
                return
            self.page.wait_for_timeout(200)
        raise CaseFailed(f"Phase {phase!r} not reached; status {self.api.get_status()}")

    def shot(self, path):
        self.page.screenshot(path=path, full_page=True)


# ---------------------------------------------------------------- test cases
# Each case: (id, title, expectation, function(h, shot)) where shot(suffix="") saves a PNG.

CASES = []


def case(case_id, title, expectation):
    def register(func):
        CASES.append((case_id, title, expectation, func))
        return func
    return register


@case("ui_01_empty_state", "App loads with empty course list", "Bridge connected, empty-state message shown")
def _(h, shot):
    h.open_app(courses=[])
    shot()
    check(h.page.get_by_text("Your course list is empty.").is_visible(), "empty state not shown")
    check("0 course(s) ready." in h.notice(), f"unexpected notice: {h.notice()}")


@case("ui_02_add_course_dialog", "Add course dialog", "Dialog opens and accepts input")
def _(h, shot):
    h.open_app(courses=[])
    h.page.get_by_role("button", name="Add course").click()
    h.fill_course_dialog("UCCD1004", "Programming Concepts", "1, 2", "3", "1")
    shot()
    check(h.page.get_by_role("heading", name="Add course").is_visible(), "dialog heading missing")


@case("ui_03_add_course_saved", "Save a new course", "Row appears and is stored in SQLite")
def _(h, shot):
    h.open_app(courses=[])
    h.page.get_by_role("button", name="Add course").click()
    h.fill_course_dialog("uccd1004", "Programming Concepts", "1, 2", "3", "1")
    h.page.get_by_role("button", name="Save course").click()
    h.wait_notice("Course list saved.")
    shot()
    check(h.row("UCCD1004").is_visible(), "row UCCD1004 missing (code should be upper-cased)")
    stored = [c["code"] for c in h.api.get_courses()]
    check(stored == ["UCCD1004"], f"SQLite has {stored}")


@case("ui_04_validation_missing_name", "Validation: missing course name", "Error notice, dialog stays open")
def _(h, shot):
    h.open_app(courses=[])
    h.page.get_by_role("button", name="Add course").click()
    h.fill_course_dialog("UCCD1004", "")
    h.page.get_by_role("button", name="Save course").click()
    h.wait_notice("Course code and course name are required.")
    shot()


@case("ui_05_validation_bad_slots", "Validation: non-numeric slots", "Error notice about slot format")
def _(h, shot):
    h.open_app(courses=[])
    h.page.get_by_role("button", name="Add course").click()
    h.fill_course_dialog("UCCD1004", "Programming Concepts", "1, a")
    h.page.get_by_role("button", name="Save course").click()
    h.wait_notice("Slot numbers must be comma-separated numbers")
    shot()


@case("ui_06_validation_duplicate", "Validation: duplicate course code", "Error notice, no second row")
def _(h, shot):
    h.open_app(courses=[MOCK_COURSE])
    h.page.get_by_role("button", name="Add course").click()
    h.fill_course_dialog(MOCK_COURSE["code"], "Again", "1")
    h.page.get_by_role("button", name="Save course").click()
    h.wait_notice("is already in your course list.")
    shot()
    check(h.page.locator("tbody tr").count() == 1, "duplicate row was added")


@case("ui_07_edit_course", "Edit a course", "Name and slots updated in table and SQLite")
def _(h, shot):
    h.open_app(courses=[MOCK_COURSE])
    h.row(MOCK_COURSE["code"]).get_by_role("button", name="Edit").click()
    h.fill_course_dialog(MOCK_COURSE["code"], "Renamed Course", "2", "1, 3", "")
    h.page.get_by_role("button", name="Save course").click()
    h.wait_notice("Course list saved.")
    shot()
    check("Renamed Course" in h.row(MOCK_COURSE["code"]).inner_text(), "row not renamed")
    stored = h.api.get_courses()[0]
    check(stored["name"] == "Renamed Course" and stored["slots"] == {"L": [2], "T": [1, 3], "P": []},
          f"SQLite has {stored}")


@case("ui_08_remove_dialog", "Remove course: confirmation dialog", "Confirmation dialog names the course")
def _(h, shot):
    h.open_app(courses=[MOCK_COURSE])
    h.row(MOCK_COURSE["code"]).get_by_role("button", name="Remove").click()
    h.page.get_by_role("heading", name=f"Remove {MOCK_COURSE['code']}?").wait_for()
    shot()


@case("ui_09_remove_confirmed", "Remove course: confirmed", "Row removed, empty state, SQLite empty")
def _(h, shot):
    h.open_app(courses=[MOCK_COURSE])
    h.row(MOCK_COURSE["code"]).get_by_role("button", name="Remove").click()
    h.page.get_by_role("button", name="Remove course").click()
    h.wait_notice("Course list saved.")
    shot()
    check(h.page.get_by_text("Your course list is empty.").is_visible(), "empty state not shown")
    check(h.api.get_courses() == [], "SQLite not empty")


@case("ui_10_import_txt", "Import timetable .txt", "2 courses parsed with slot preferences")
def _(h, shot):
    h.open_app(courses=[])
    h.import_file(os.path.join(FIXTURES, "timetable.txt"))
    h.wait_notice("Loaded 2 course(s) from timetable.txt.")
    shot()
    check(h.row("UCCD1004").is_visible() and h.row("UCCD1024").is_visible(), "imported rows missing")
    check("L 1, 2" in h.row("UCCD1004").inner_text(), "slots not parsed")


@case("ui_11_import_json", "Import courses .json", "3 courses loaded")
def _(h, shot):
    h.open_app(courses=[])
    h.import_file(os.path.join(FIXTURES, "courses.json"))
    h.wait_notice("Loaded 3 course(s) from courses.json.")
    shot()
    check(h.page.locator("tbody tr").count() == 3, "expected 3 rows")


@case("ui_12_persistence", "Courses persist across restarts (SQLite)", "Reopened app shows saved courses")
def _(h, shot):
    h.open_app(courses=[], db_name="persist.db")
    h.import_file(os.path.join(FIXTURES, "courses.json"))
    h.wait_notice("Loaded 3 course(s)")
    h.open_app(db_name="persist.db")  # new DesktopApi + new page on the same database
    h.wait_notice("3 course(s) ready.")
    shot()


@case("start_01_no_credentials", "Start without credentials", "Error asks for student ID and password")
def _(h, shot):
    h.open_app(courses=[MOCK_COURSE])
    h.page.get_by_role("button", name="Start registration").click()
    h.wait_notice("Enter your student ID and password first.")
    shot()
    check(not any(m == "start" for m, _ in h.calls), "backend start was called")


@case("start_02_no_courses", "Start with no courses", "Error asks to add courses")
def _(h, shot):
    h.open_app(courses=[])
    h.fill_credentials()
    h.page.get_by_role("button", name="Start registration").click()
    h.wait_notice("Add or import at least one course first.")
    shot()
    check(not any(m == "start" for m, _ in h.calls), "backend start was called")


@case("start_03_browser_visible_toggle", "'Browser visible' toggle maps to headless flag",
      "Unticked sends headless=True, ticked sends headless=False")
def _(h, shot):
    h.open_app(courses=[MOCK_COURSE])
    h.dry_start = True
    h.fill_credentials()
    h.page.get_by_label("Connection method").select_option("Playwright")
    toggle = h.page.get_by_label("Browser visible")
    check(toggle.is_checked(), "toggle should default to ticked (browser visible)")
    toggle.set_checked(False, force=True)
    h.page.get_by_role("button", name="Start registration").click()
    h.tab("Login & settings")  # Start opens the Registration tab
    toggle.set_checked(True, force=True)
    h.page.get_by_role("button", name="Start registration").click()
    h.page.wait_for_timeout(300)
    shot()
    starts = [args for m, args in h.calls if m == "start"]
    check(len(starts) == 2, f"expected 2 start calls, got {starts}")
    check(starts[0][3] is True and starts[1][3] is False, f"headless flags were {[s[3] for s in starts]}")


COURSE_A = {"code": "MOCK1001", "name": "Mock Course One", "slots": {"L": [1], "T": [1]}}
COURSE_B = {"code": "MOCK1002", "name": "Mock Course Two", "slots": {"L": [1], "T": [2]}}
COURSE_B_ALT = {"code": "MOCK1002", "name": "Mock Course Two", "slots": {"L": [1], "T": [3]}}
COURSE_C = {"code": "MOCK1003", "name": "Mock Course Three", "slots": {"L": [1]}}
TWO_PLANS = [
    {"name": "Plan A", "courses": [COURSE_A, COURSE_B]},
    {"name": "Plan B", "courses": [COURSE_A, COURSE_B_ALT, COURSE_C]},
]


def _start(h, method="BeautifulSoup"):
    h.fill_credentials()
    h.choose_method(method)
    h.page.get_by_role("button", name="Start registration").click()


@case("plans_01_add_plan", "Add a backup plan", "Plan B tab appears and is saved")
def _(h, shot):
    h.open_app(courses=[COURSE_A])
    h.page.get_by_role("button", name="Add plan").click()
    h.wait_notice("Plan B added.")
    h.page.get_by_role("button", name="Add course").click()
    h.fill_course_dialog("MOCK1002", "Mock Course Two", "1", "3")
    h.page.get_by_role("button", name="Save course").click()
    h.wait_notice("Course list saved.")
    shot()
    saved = h.api.get_plans()
    check([p["name"] for p in saved] == ["Plan A", "Plan B"], f"plans {saved}")
    check([c["code"] for c in saved[1]["courses"]] == ["MOCK1002"], f"Plan B courses {saved[1]}")
    check([c["code"] for c in saved[0]["courses"]] == ["MOCK1001"], "Plan A changed")


@case("plans_02_fallback_auto", "Plan A slot full: falls back to Plan B automatically",
      "Missing course is registered from Plan B; nothing dropped")
def _(h, shot):
    h.open_app(plans=TWO_PLANS)
    h.mock.full_slots.add(("MOCK1002", "T", 2))
    _start(h)
    status = h.wait_run_finished()
    shot()
    check(status["phase"] == "complete", f"phase {status['phase']!r}: {status['message']!r}")
    result = status["results"]["MOCK1002"]
    check(result["plan"] == "Plan B" and result["registered"] == "L1 T3", f"result {result}")
    check(h.mock.registered["MOCK1001"]["classes"] == {"L": 1, "T": 1}, "Plan A course was changed")
    check("via Plan B" in h.row("MOCK1002").inner_text(), "row does not say it came via Plan B")


@case("plans_03_fallback_ask", "Fallback asks before bidding", "Dialog lists Plan B choices; only the ticked one is bid")
def _(h, shot):
    h.open_app(plans=TWO_PLANS)
    h.mock.full_slots.add(("MOCK1002", "T", 2))
    h.fill_credentials()
    h.page.get_by_label("If a plan cannot be completed").select_option("ask")
    h.page.get_by_role("button", name="Start registration").click()
    h.page.get_by_role("heading", name="Plan B: what should be bid?").wait_for(timeout=20_000)
    h.page.locator(".proposal-list li", has_text="MOCK1003").get_by_role("checkbox").uncheck()
    h.page.wait_for_timeout(1600)  # several status polls: the untick must survive them
    shot("_1_dialog")
    items = {i["code"]: i["action"] for i in h.api.get_status()["proposal"]["items"]}
    check(items == {"MOCK1001": "keep", "MOCK1002": "add", "MOCK1003": "add"}, f"proposal {items}")
    h.page.get_by_role("button", name="Bid selected courses").click()
    status = h.wait_run_finished()
    shot("_2_result")
    check(status["phase"] == "complete", f"phase {status['phase']!r}")
    check("MOCK1002" in h.mock.registered and "MOCK1003" not in h.mock.registered,
          f"registered {sorted(h.mock.registered)}")


@case("plans_04_fallback_clash", "Fallback skips a class that clashes with a held timeslot",
      "Clashing Plan B course is skipped with the reason shown")
def _(h, shot):
    h.open_app(plans=[
        {"name": "Plan A", "courses": [COURSE_A, {"code": "MOCK1002", "name": "Mock Course Two", "slots": {"L": [1]}}]},
        {"name": "Plan B", "courses": [{"code": "MOCK1002", "name": "Mock Course Two", "slots": {"L": [2]}}]},
    ])
    h.mock.full_slots.add(("MOCK1002", "L", 1))
    h.mock.slot_times[("MOCK1001", "L", 1)] = ("Tue", 9, 2)
    h.mock.slot_times[("MOCK1002", "L", 2)] = ("Tue", 10, 2)
    _start(h)
    status = h.wait_run_finished()
    h.tab("Courses")
    h.page.locator(".plan-tabs").get_by_role("tab", name="Plan B").click()
    shot()
    result = status["results"]["MOCK1002"]
    check(status["phase"] == "error" and result["label"] == "Skipped", f"status {status['phase']} {result}")
    check("clashes with MOCK1001 L1" in result["message"], f"message {result['message']!r}")
    check("MOCK1002" not in h.mock.registered, "clashing course was registered")


@case("status_01_registered_board", "Verified status board", "Registered courses and credit hours read from UTAR's page")
def _(h, shot):
    h.open_app(courses=[COURSE_A, COURSE_B])
    _start(h)
    status = h.wait_run_finished()
    h.page.locator(".registered-card", has_text="MOCK1002").wait_for()
    shot()
    check(status["credit"] == {"total": "6", "max": "20"}, f"credit {status['credit']}")
    check(h.page.locator(".registered-card").count() == 2, "expected 2 registered cards")
    check("6 of 20 credit hours" in h.page.locator(".credit-meter").inner_text(), "credit meter wrong")
    check(h.row("MOCK1001").locator(".row-status").inner_text().strip() == "Confirmed", "row not Confirmed")


@case("status_02_different_group", "Course held in a different group", "Row shows Different group and is not re-bid")
def _(h, shot):
    h.open_app(courses=[COURSE_A])
    h.mock.registered["MOCK1001"] = {"name": "MOCK COURSE MOCK1001", "credit": 3.0, "classes": {"L": 1, "T": 3}}
    _start(h)
    status = h.wait_run_finished()
    shot()
    result = status["results"]["MOCK1001"]
    check(result["label"] == "Different group" and status["total"] == 0, f"result {result}, total {status['total']}")
    check(h.mock.registered["MOCK1001"]["classes"] == {"L": 1, "T": 3}, "registration was changed")


@case("retry_01_retry_missing", "Retry only the missing course", "Second start skips the registered course and gets the freed one")
def _(h, shot):
    h.open_app(courses=[COURSE_A, COURSE_B])
    h.mock.full_slots.add(("MOCK1002", "T", 2))
    _start(h)
    first = h.wait_run_finished()
    check(first["phase"] == "error", f"first run phase {first['phase']!r}")
    h.page.get_by_role("button", name="Retry missing courses").wait_for()
    shot("_1_after_first_run")
    h.mock.full_slots.clear()
    previous_board = h.api._board
    h.page.get_by_role("button", name="Retry missing courses").click()
    for _ in range(200):  # a new run replaces the status board
        if h.api._board is not previous_board:
            break
        h.page.wait_for_timeout(50)
    second = h.wait_run_finished()
    shot("_2_after_retry")
    check(second["phase"] == "complete", f"retry phase {second['phase']!r}")
    check(second["total"] == 1, f"retry bid {second['total']} courses, expected 1")


@case("retry_02_auto_retry", "Retry until registered", "App retries on a timer and registers once the slot frees up")
def _(h, shot):
    h.open_app(courses=[COURSE_B])
    h.mock.full_slots.add(("MOCK1002", "T", 2))
    h.fill_credentials()
    h.page.get_by_label("Retry until registered").set_checked(True, force=True)
    h.page.get_by_label("Retry every (seconds)").fill("5")
    h.page.get_by_role("button", name="Start registration").click()
    h.wait_phase("waiting_retry", timeout=30)
    h.page.locator(".current-message", has_text="Retrying in").wait_for(timeout=5_000)
    shot("_1_waiting")
    h.mock.full_slots.clear()
    status = h.wait_run_finished()
    shot("_2_registered")
    check(status["phase"] == "complete" and status["attempt"] >= 2, f"phase {status['phase']} attempt {status['attempt']}")


@case("schedule_01_start_at_time", "Scheduled start", "Logs in, waits, and only bids at the set time")
def _(h, shot):
    h.open_app(courses=[COURSE_A])
    h.fill_credentials()
    h.page.get_by_label("When should bidding start?").select_option("at")
    start = time.localtime(time.time() + 8)
    h.page.get_by_label("Bidding opens at").fill(time.strftime("%H:%M:%S", start))
    h.page.get_by_role("button", name="Start registration").click()
    h.wait_phase("scheduled", timeout=10)
    h.page.locator(".current-message", has_text="Bidding starts at").wait_for(timeout=8_000)
    shot("_1_waiting")
    check("MOCK1001" not in h.mock.registered, "bid before the scheduled time")
    status = h.wait_run_finished()
    shot("_2_done")
    check(status["phase"] == "complete", f"phase {status['phase']!r}")
    check(time.time() >= time.mktime(start), "finished before the scheduled time")


@case("preflight_01_report", "Pre-flight check", "Problems and warnings listed; nothing registered")
def _(h, shot):
    h.open_app(courses=[
        COURSE_A,
        {"code": "NOPE0000", "name": "Unknown Course", "slots": {"L": [1]}},
        {"code": "MOCK1002", "name": "Mock Course Two", "slots": {"L": [1], "T": [9]}},
    ])
    h.mock.unknown_units.add("NOPE0000")
    h.fill_credentials()
    h.page.get_by_role("button", name="Run pre-flight check").click()
    status = h.wait_run_finished()
    h.page.locator(".preflight li", has_text="NOPE0000").wait_for()
    shot()
    check(status["phase"] == "preflight_done", f"phase {status['phase']!r}")
    check(status["preflight"]["problems"] == 2, f"problems {status['preflight']}")
    check(h.mock.registered == {}, "pre-flight registered something")


@case("closed_01_registration_closed", "Portal closed: session expires right after login",
      "Run ends with a clear login error instead of hanging")
def _(h, shot):
    h.open_app(courses=[COURSE_A], scenario="closed")
    _start(h)
    status = h.wait_run_finished(timeout=60)
    shot()
    check(status["phase"] == "error", f"phase {status['phase']!r}")
    check("registration may be closed" in status["message"], f"message {status['message']!r}")
    h.page.get_by_role("button", name="Start registration").wait_for()


@case("closed_02_stop_while_login_fails", "Scheduled start while the portal is closed, then Stop",
      "Login keeps retrying (nothing bid); Stop ends the run within seconds; the app is usable again")
def _(h, shot):
    h.open_app(courses=[COURSE_A], scenario="closed")
    h.fill_credentials()
    h.page.get_by_label("When should bidding start?").select_option("at")
    h.page.get_by_label("Bidding opens at").fill(time.strftime("%H:%M:%S", time.localtime(time.time() + 20)))
    h.page.get_by_role("button", name="Start registration").click()
    h.page.locator(".current-message", has_text="Trying again in").wait_for(timeout=30_000)
    check(h.api.get_status()["running"], "scheduled run should keep retrying the login")
    check(h.mock.registered == {}, "something was bid while the portal was closed")
    h.page.get_by_role("button", name="Stop safely").click()
    stopped = time.time()
    status = h.wait_run_finished(timeout=30)
    shot()
    check(status["phase"] == "cancelled", f"phase {status['phase']!r}: {status['message']!r}")
    check(time.time() - stopped < 15, "Stop took too long")
    h.page.get_by_role("button", name="Start registration").wait_for()


# ---------------------------------------------------------------- issues.txt cases

DROP_SCRIPT = """
async ([name, content, selector]) => {
  const file = new File([content], name, { type: "text/plain" });
  const data = new DataTransfer();
  data.items.add(file);
  const target = document.querySelector(selector);
  for (const type of ["dragenter", "dragover"]) {
    target.dispatchEvent(new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: data }));
  }
  const overlay = Boolean(document.querySelector(".drop-overlay"));
  await new Promise((resolve) => setTimeout(resolve, 50));
  const overlayShown = overlay || Boolean(document.querySelector(".drop-overlay"));
  target.dispatchEvent(new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: data }));
  return overlayShown;
}
"""


@case("ux_01_header_and_tabs", "Short header, no 'Desktop ready', section tabs",
      "Header is one short title; run status chip instead of the bridge pill; five tabs")
def _(h, shot):
    h.open_app(courses=[MOCK_COURSE])
    shot()
    check(h.page.locator("h1").inner_text().strip() == "UTAR Course Bidding", "header text")
    check(h.page.get_by_text("Desktop ready").count() == 0, "'Desktop ready' still shown")
    check(h.page.get_by_text("Choose your courses with confidence").count() == 0, "old long header still shown")
    tabs = [t.strip() for t in h.page.locator("nav.tabs [role=tab]").all_inner_texts()]
    check(tabs == ["Courses", "Login & settings", "Pre-flight", "Registration", "Logs"], f"tabs {tabs}")
    check(h.page.locator(".run-chip").inner_text().strip().startswith("Ready"), "status chip")


@case("ux_02_password_toggle", "Password show/hide toggle",
      "Toggles type each time, keeps the value, works after a validation error")
def _(h, shot):
    h.open_app(courses=[MOCK_COURSE])
    h.tab("Login & settings")
    field = h.page.get_by_label("Password", exact=True)
    field.fill("Secret-123")
    reveal = h.page.locator(".reveal-button")
    for expected in ("text", "password", "text", "password"):
        reveal.click()
        check(field.get_attribute("type") == expected, f"type should be {expected}")
        check(field.input_value() == "Secret-123", "toggle changed the password")
    h.page.get_by_role("button", name="Start registration").click()  # no student ID -> validation error
    h.wait_notice("Enter your student ID and password first.")
    reveal.click()
    check(field.get_attribute("type") == "text" and field.input_value() == "Secret-123", "toggle broken after validation error")
    shot()
    reveal.click()
    check(field.get_attribute("type") == "password", "did not hide again")


@case("ux_03_drag_drop_import", "Drag and drop a timetable file",
      "Drop area highlights; dropped .txt opens the import dialog; unsupported type is rejected")
def _(h, shot):
    h.open_app(courses=[])
    content = open(os.path.join(FIXTURES, "timetable.txt"), encoding="utf-8").read()
    overlay = h.page.evaluate(DROP_SCRIPT, ["timetable.txt", content, ".course-panel"])
    check(overlay, "drop area did not highlight while dragging")
    dialog = h.page.locator(".modal-dialog", has_text="IMPORT TIMETABLE")
    dialog.wait_for()
    shot("_1_dialog")
    dialog.locator("button[type=submit]").click()
    h.wait_notice("Loaded 2 course(s) from timetable.txt.")
    check(h.row("UCCD1004").is_visible(), "dropped file not imported")
    h.page.evaluate(DROP_SCRIPT, ["notes.pdf", "x", ".course-panel"])
    h.wait_notice("notes.pdf is not supported")
    shot("_2_rejected")


@case("ux_04_import_mode", "Import as a new plan or replace", "New plan keeps Plan A; replace overwrites only the current plan")
def _(h, shot):
    h.open_app(courses=[MOCK_COURSE])
    h.tab("Courses")
    h.page.locator("input[type=file]").set_input_files(os.path.join(FIXTURES, "courses.json"))
    dialog = h.page.locator(".modal-dialog", has_text="IMPORT TIMETABLE")
    dialog.wait_for()
    check(dialog.locator("input[value=new]").is_checked(), "a non-empty plan must default to 'new plan'")
    check("cannot be restored" in dialog.inner_text(), "replace consequence not explained")
    shot("_1_dialog")
    dialog.get_by_label("New plan name").fill("Imported plan")
    dialog.locator("button[type=submit]").click()
    h.wait_notice("into new plan Imported plan")
    saved = h.api.get_plans()
    check([p["name"] for p in saved] == ["Plan A", "Imported plan"], f"plans {[p['name'] for p in saved]}")
    check([c["code"] for c in saved[0]["courses"]] == [MOCK_COURSE["code"]], "Plan A was changed")
    h.import_file(os.path.join(FIXTURES, "timetable.txt"), mode="replace")
    h.wait_notice("Loaded 2 course(s) from timetable.txt.")
    shot("_2_replaced")
    saved = h.api.get_plans()
    check(len(saved[1]["courses"]) == 2 and saved[0]["courses"][0]["code"] == MOCK_COURSE["code"], "replace hit the wrong plan")


@case("ux_05_toast_queue", "Toast notifications queue", "One toast at a time, next shows after dismiss, no duplicates")
def _(h, shot):
    h.open_app(courses=[])
    h.page.get_by_role("button", name="Start registration").click()  # toast A
    h.page.get_by_role("button", name="Start registration").click()  # duplicate of A: ignored
    h.tab("Courses")
    h.page.get_by_role("button", name="Add course").click()
    h.page.get_by_role("button", name="Save course").click()  # toast B, queued
    h.page.get_by_role("button", name="Cancel").click()
    check(h.page.locator(".toast").count() == 1, "toasts overlap")
    check("student ID" in h.page.locator(".toast").inner_text(), "first toast should be shown first")
    shot()
    h.page.locator(".toast", has_text="student ID").get_by_role("button", name="Dismiss notification").click()
    second = h.page.locator(".toast", has_text="Course code and course name are required")
    second.wait_for(timeout=3_000)
    check(h.page.locator(".toast").count() == 1, "toasts overlap while switching")
    second.get_by_role("button", name="Dismiss notification").click()
    h.page.wait_for_timeout(400)
    check(h.page.locator(".toast").count() == 0, "duplicate toast was queued")
    h.page.get_by_role("button", name="Start registration").click()
    h.page.locator(".toast").wait_for()
    h.page.wait_for_timeout(7_000)
    check(h.page.locator(".toast").count() == 0, "toast did not dismiss itself")


@case("ux_06_narrow_window", "Narrow window (600 px)", "Every tab fits without sideways scrolling; actions stay reachable")
def _(h, shot):
    h.open_app(courses=[COURSE_A, COURSE_B])
    h.page.set_viewport_size({"width": 600, "height": 900})
    for name in ("Courses", "Login & settings", "Pre-flight", "Registration", "Logs"):
        h.tab(name)
        h.page.wait_for_timeout(100)
        overflow = h.page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        check(overflow <= 1, f"{name}: page scrolls sideways by {overflow}px")
        shot(f"_{name.split()[0].lower()}")
    check(h.page.get_by_role("button", name="Start registration").is_visible(), "Start not reachable")


@case("pf_02_no_plan", "Pre-flight without a course plan", "Login is checked; plan checks are skipped with a reason")
def _(h, shot):
    h.open_app(courses=[])
    h.fill_credentials()
    h.page.get_by_role("button", name="Run pre-flight check").click()
    status = h.wait_run_finished()
    h.page.locator(".step", has_text="Check course codes").wait_for()
    shot()
    check(status["phase"] == "preflight_done", f"phase {status['phase']!r}: {status['message']!r}")
    states = {step["id"]: step["state"] for step in status["steps"]}
    check(states == {"login": "ok", "registered": "ok", "plans": "skipped", "clashes": "skipped"}, f"steps {states}")
    check("No course plan yet" in h.page.locator(".step", has_text="Check course codes").inner_text(), "skip reason missing")


@case("pf_03_steps_visible", "Pre-flight shows each step while it runs", "A running step and the login attempt are shown")
def _(h, shot):
    h.open_app(courses=[COURSE_A])
    h.fill_credentials()
    h.page.get_by_role("button", name="Run pre-flight check").click()
    h.page.locator(".step.running, .step.ok").first.wait_for(timeout=10_000)
    status = h.wait_run_finished()
    shot()
    check([step["state"] for step in status["steps"]] == ["ok", "ok", "ok", "ok"], f"steps {status['steps']}")
    check(all(step["started_at"] and step["ended_at"] for step in status["steps"]), "step timings missing")


@case("run_01_stopping_and_timer", "Stop shows Stopping..., elapsed timer runs",
      "Chip shows elapsed time; after Stop it reads Stopping... until the run has really ended, then Cancelled")
def _(h, shot):
    h.open_app(courses=[MOCK_COURSE], scenario="timeout")
    _start(h)
    h.wait_phase("bidding")
    h.page.locator(".run-chip-time").wait_for(timeout=10_000)
    first = h.page.locator(".run-chip-time").inner_text()
    h.page.wait_for_timeout(1_200)
    check(h.page.locator(".run-chip-time").inner_text() != first, "timer is not counting")
    h.page.get_by_role("button", name="Stop safely").click()
    h.page.locator(".run-chip", has_text="Stopping...").wait_for(timeout=2_000)
    check(h.api.get_status()["running"], "run already over; Stopping was not observable")
    shot("_1_stopping")
    status = h.wait_run_finished()
    shot("_2_cancelled")
    check(status["phase"] == "cancelled" and not status["stopping"], f"status {status['phase']} stopping={status['stopping']}")
    check(h.page.locator(".run-chip").inner_text().startswith("Cancelled"), "chip did not end as Cancelled")
    frozen = h.page.locator(".run-chip-time").inner_text()
    h.page.wait_for_timeout(1_200)
    check(h.page.locator(".run-chip-time").inner_text() == frozen, "timer kept running after the run ended")


@case("login_01_error_panel", "Rejected login shows in the login section and blocks Start",
      "Error stays visible in Login & settings; Start is blocked until the credentials change")
def _(h, shot):
    h.open_app(courses=[MOCK_COURSE])
    h.fill_credentials(student_id="invalid")
    h.page.get_by_role("button", name="Start registration").click()
    status = h.wait_run_finished()
    check(status["error_source"] == "login" and status["error_kind"] == "invalid_credentials", f"status {status}")
    panel = h.page.locator(".login-error")
    panel.wait_for()
    check(h.page.locator("nav.tabs [aria-selected=true]").inner_text().startswith("Login"), "did not open the Login tab")
    shot("_1_error")
    calls_before = len([c for c in h.calls if c[0] == "start"])
    h.page.get_by_role("button", name="Start registration").click()
    h.wait_notice("UTAR rejected this student ID or password")
    check(len([c for c in h.calls if c[0] == "start"]) == calls_before, "Start was not blocked")
    check(panel.is_visible(), "error disappeared")
    h.page.get_by_label("Student ID").fill("2103370")
    h.page.wait_for_timeout(200)
    check(h.page.locator(".login-error").count() == 0, "error should clear after editing the credentials")
    shot("_2_cleared")


@case("login_02_remember_credentials", "Remember the login (encrypted)", "Reopened app is prefilled; untick forgets it")
def _(h, shot):
    h.open_app(courses=[MOCK_COURSE], db_name="cred.db")
    h.fill_credentials(student_id="2103370", password="Pw-remember-1")
    h.page.wait_for_timeout(900)
    import sqlite3
    rows = dict(sqlite3.connect(h.db_path).execute("SELECT key, value FROM app_settings").fetchall())
    check("Pw-remember-1" not in str(rows), "password stored in plain text")
    check(rows.get("password_protected", "").startswith("dpapi:"), f"password not encrypted: {list(rows)}")
    h.open_app(db_name="cred.db")
    h.tab("Login & settings")
    h.page.wait_for_timeout(300)
    check(h.page.get_by_label("Student ID").input_value() == "2103370", "student ID not remembered")
    check(h.page.get_by_label("Password", exact=True).input_value() == "Pw-remember-1", "password not remembered")
    shot()
    h.page.get_by_label("Remember on this computer").set_checked(False, force=True)
    h.page.wait_for_timeout(900)
    h.open_app(db_name="cred.db")
    h.tab("Login & settings")
    h.page.wait_for_timeout(300)
    check(h.page.get_by_label("Password", exact=True).input_value() == "", "password kept after untick")


@case("schedule_02_after_delay", "Start after a delay", "Countdown shown; bids only after the delay")
def _(h, shot):
    h.open_app(courses=[COURSE_A])
    h.fill_credentials()
    h.page.get_by_label("When should bidding start?").select_option("after")
    h.page.get_by_label("Start after (minutes)").fill("0.15")
    clicked = time.time()
    h.page.get_by_role("button", name="Start registration").click()
    h.page.locator(".run-chip", has_text="starts in").wait_for(timeout=8_000)
    shot("_1_countdown")
    check("MOCK1001" not in h.mock.registered, "bid before the delay")
    status = h.wait_run_finished()
    check(status["phase"] == "complete", f"phase {status['phase']!r}")
    check(time.time() - clicked >= 9, "finished before the delay")


@case("logs_01_activity_log", "Logs tab", "Run steps are listed with times")
def _(h, shot):
    h.open_app(courses=[COURSE_A])
    _start(h)
    h.wait_run_finished()
    h.tab("Logs")
    h.page.locator(".activity-log li").first.wait_for()
    shot()
    text = h.page.locator(".activity-log").inner_text()
    check("Logging in" in text and "All courses registered" in text, f"log {text[:300]}")



def _run_case(method, scenario, student_id, expect_phase, expect_text=None, expect_row=None):
    def body(h, shot):
        h.open_app(courses=[MOCK_COURSE], scenario=scenario)
        h.fill_credentials(student_id=student_id)
        h.choose_method(method)
        h.page.get_by_role("button", name="Start registration").click()
        status = h.wait_run_finished()
        shot()
        check(status["phase"] == expect_phase, f"phase {status['phase']!r}, message {status['message']!r}")
        if expect_text:
            check(expect_text in status["message"], f"message {status['message']!r}")
        if expect_row:
            label = h.row(MOCK_COURSE["code"]).locator(".row-status").inner_text().strip()
            check(label == expect_row, f"row status {label!r}")
    return body


def _cancel_case(method):
    def body(h, shot):
        h.open_app(courses=[MOCK_COURSE], scenario="timeout")
        h.fill_credentials()
        h.choose_method(method)
        h.page.get_by_role("button", name="Start registration").click()
        h.wait_phase("bidding")
        h.page.wait_for_timeout(1500)  # registration request is now in flight
        h.page.get_by_role("button", name="Stop safely").wait_for()
        shot("_1_running")
        h.page.get_by_role("button", name="Stop safely").click()
        status = h.wait_run_finished()
        shot("_2_stopped")
        check(status["phase"] == "cancelled", f"phase {status['phase']!r}, message {status['message']!r}")
    return body


for _prefix, _method in (("bs", "BeautifulSoup"), ("pw", "Playwright")):
    for _suffix, _title, _expect, _fn in (
        ("01_success", "success", "All courses registered; row shows Confirmed",
         _run_case(_method, "success", "2103370", "complete", "All courses registered", "Confirmed")),
        ("02_register_fail", "register-fail", "Run ends with course marked Not registered",
         _run_case(_method, "register-fail", "2103370", "error", None, "Not registered")),
        ("03_session_expired", "session-expired", "Run ends with a login error",
         _run_case(_method, "session-expired", "2103370", "error", "Login")),
        ("04_invalid_credentials", "invalid credentials", "Run ends with a credentials error",
         _run_case(_method, "success", "invalid", "error", "credentials")),
        ("05_timeout", "timeout", "Slow server: course marked Not registered",
         _run_case(_method, "timeout", "2103370", "error", None, "Not registered")),
        ("06_cancel", "Stop safely during slow request", "Run ends as cancelled",
         _cancel_case(_method)),
    ):
        case(f"{_prefix}_{_suffix}", f"{_method}: {_title}", _expect)(_fn)


# ---------------------------------------------------------------- runner

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-build", action="store_true", help="reuse existing web/dist")
    parser.add_argument("--only", default="", help="run only case ids containing this text")
    parser.add_argument("--headed", action="store_true", help="show the test browser")
    parser.add_argument("--show-app-browser", action="store_true",
                        help="let the app's own Playwright browser be visible during Playwright cases")
    args = parser.parse_args()

    os.chdir(ROOT)  # config.ini is resolved from the working directory
    sys.path.insert(0, ROOT)
    mock = start_mock_server()
    os.environ["UTAR_BASE_URL"] = f"http://127.0.0.1:{mock.server_port}{mock.base_path}"
    os.environ.pop("UTAR_MOCK_CAPTCHA", None)  # exercise the real OCR on the sample captcha

    if not args.no_build:
        build_frontend()
    if not os.path.exists(os.path.join(DIST_DIR, "index.html")):
        raise SystemExit("web/dist/index.html not found; run without --no-build")

    shutil.rmtree(OUT_DIR, ignore_errors=True)
    os.makedirs(OUT_DIR)
    static = start_static_server(DIST_DIR)
    app_url = f"http://127.0.0.1:{static.server_port}/index.html"

    from playwright.sync_api import sync_playwright

    selected = [c for c in CASES if args.only in c[0]]
    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        harness = Harness(browser, app_url, mock, args.show_app_browser)
        for index, (case_id, title, expectation, func) in enumerate(selected, 1):
            shots = []

            def shot(suffix="", _id=case_id):
                path = os.path.join(OUT_DIR, f"{_id}{suffix}.png")
                harness.shot(path)
                shots.append(os.path.basename(path))

            started = time.time()
            print(f"[{index}/{len(selected)}] {case_id} ... ", end="", flush=True)
            try:
                func(harness, shot)
                outcome, detail = "PASS", ""
            except Exception as error:
                outcome = "FAIL"
                detail = str(error) if isinstance(error, CaseFailed) else traceback.format_exc(limit=3)
                if harness.page and not shots:
                    try:
                        shot("_failure")
                    except Exception:
                        pass
            elapsed = time.time() - started
            print(f"{outcome} ({elapsed:.1f}s){' - ' + detail.splitlines()[0] if detail else ''}")
            results.append((case_id, title, expectation, outcome, detail, shots, elapsed))
        harness.close_app()
        browser.close()

    write_report(results)
    failed = [r for r in results if r[3] == "FAIL"]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed. Report: {os.path.join(OUT_DIR, 'report.md')}")
    return 1 if failed else 0


def write_report(results):
    lines = [
        "# E2E test report",
        "",
        f"Generated {time.strftime('%Y-%m-%d %H:%M:%S')} by tests/e2e/run_e2e.py against src/mock_server.py.",
        "",
        "| Case | Title | Expected | Result | Time | Screenshots |",
        "|---|---|---|---|---|---|",
    ]
    for case_id, title, expectation, outcome, detail, shots, elapsed in results:
        links = " ".join(f"[{s}]({s})" for s in shots)
        lines.append(f"| {case_id} | {title} | {expectation} | {outcome} | {elapsed:.1f}s | {links} |")
    failures = [r for r in results if r[3] == "FAIL"]
    if failures:
        lines += ["", "## Failures", ""]
        for case_id, _, _, _, detail, _, _ in failures:
            lines += [f"### {case_id}", "", "```", detail.strip(), "```", ""]
    with open(os.path.join(OUT_DIR, "report.md"), "w", encoding="utf-8") as file:
        file.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    sys.exit(main())
