"""Python API used by the Vue desktop frontend."""

import atexit
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time

import webview

from .models.course import Course
from .services.plan_runner import PlanRunner, StatusBoard
from .storage.database import CourseRepository, Database, PlanRepository, SettingsRepository
from .utils import browser_setup, secret_store
from .utils.config import BASE_DIR, LOG_DIR
from .utils.timetable_reader import TimetableReader
from .utils.logger import setup_logger

logger = setup_logger(__name__)


class DesktopApi:
    """Small local API exposed to Vue through pywebview."""

    STOP_GRACE_SECONDS = 25

    def __init__(self, database=None):
        # Courses live in SQLite; the old JSON file is imported once if the table is empty.
        database = database or Database()
        self.courses_file = os.path.join(BASE_DIR, "data", "courses.json")
        self.course_repo = CourseRepository(database)
        self.course_repo.migrate_from_json(self.courses_file)
        # Timetable plans (Plan A, B, ...). The legacy single list becomes Plan A.
        self.plan_repo = PlanRepository(database)
        self.plan_repo.ensure_initial_plan(self.course_repo)
        self.settings_repo = SettingsRepository(database)
        self._browser_install = {"running": False, "ok": None, "message": ""}
        self._lock = threading.Lock()
        self._thread = None
        self._runner = None
        self._board = StatusBoard()
        self._plans = self._load_plans()

    # ------------------------------------------------------------- plans
    def _load_plans(self):
        try:
            plans = self.plan_repo.list_plans()
        except (sqlite3.Error, ValueError, TypeError) as error:
            logger.error("Failed to load plans: %s", error)
            plans = []
        return plans or [{"name": PlanRepository.DEFAULT_PLAN_NAME, "courses": []}]

    def _persist(self):
        self.plan_repo.replace_plans(self._plans)

    def get_plans(self):
        return [
            {"name": plan["name"], "courses": [course.__dict__ for course in plan["courses"]]}
            for plan in self._plans
        ]

    def save_plans(self, plans):
        parsed = []
        for index, plan in enumerate(plans or []):
            name = str(plan.get("name") or "").strip() or f"Plan {chr(ord('A') + index)}"
            courses = [Course(**course) for course in plan.get("courses", [])]
            parsed.append({"name": name, "courses": courses})
        self._plans = parsed or [{"name": PlanRepository.DEFAULT_PLAN_NAME, "courses": []}]
        self._persist()
        return self.get_plans()

    # Plan A shortcuts, kept for callers that manage a single course list.
    def get_courses(self):
        return [course.__dict__ for course in self._plans[0]["courses"]]

    def save_courses(self, courses):
        self._plans[0]["courses"] = [Course(**course) for course in courses]
        self._persist()
        return self.get_courses()

    IMPORT_TYPES = (".txt", ".json")

    @classmethod
    def _parse_import(cls, filename, content):
        name = str(filename or "")
        if not name.lower().endswith(cls.IMPORT_TYPES):
            raise ValueError(f"{name or 'This file'} is not supported. Import a UTAR timetable .txt "
                             "file or a .json course list.")
        if not str(content or "").strip():
            raise ValueError(f"{name} is empty.")
        try:
            if name.lower().endswith(".json"):
                courses = [Course(**course) for course in json.loads(content)]
            else:
                with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as file:
                    file.write(content)
                    temp_path = file.name
                try:
                    courses = TimetableReader.read_timetable(temp_path)
                finally:
                    os.unlink(temp_path)
        except (ValueError, TypeError, KeyError) as error:
            raise ValueError(f"{name} could not be read as a course list: {error}") from error
        if not courses:
            raise ValueError(f"No courses were found in {name}.")
        return courses

    def preview_import(self, filename, content):
        """Parse a file without saving it, so the UI can ask how to import it."""
        return [course.__dict__ for course in self._parse_import(filename, content)]

    def import_courses(self, filename, content, plan_index=0, mode="replace", new_name=None):
        """mode "replace": replace the courses of plan_index.
        mode "new": add a new plan (named new_name) and keep all existing plans.
        Returns the full plan list."""
        courses = self._parse_import(filename, content)
        if mode == "new":
            name = str(new_name or "").strip() or f"Plan {chr(ord('A') + len(self._plans))}"
            self._plans.append({"name": name, "courses": courses})
        else:
            plan_index = int(plan_index or 0)
            if not 0 <= plan_index < len(self._plans):
                raise ValueError("That plan does not exist")
            self._plans[plan_index]["courses"] = courses
        self._persist()
        return self.get_plans()

    # ------------------------------------------------------- credentials
    def get_saved_credentials(self):
        """Saved login for the form. The password is decrypted only here, in
        memory, and only for this Windows user (DPAPI)."""
        settings = self.settings_repo.load_settings()
        remember = settings.get("remember_login", "true") != "false"
        password = ""
        stored = settings.get("password_protected", "")
        if stored:
            try:
                password = secret_store.unprotect(stored)
            except ValueError as error:
                logger.warning("Saved password could not be decrypted: %s", error)
        return {
            "student_id": settings.get("student_id", "") if remember else "",
            "password": password if remember else "",
            "remember": remember,
            "secure_storage": secret_store.available(),
        }

    def save_credentials(self, student_id, password, remember=True):
        """Remember the login (password encrypted with DPAPI) or forget it."""
        values = {"remember_login": "true" if remember else "false", "password": ""}
        if remember:
            values["student_id"] = str(student_id or "").strip()
            values["password_protected"] = (
                secret_store.protect(str(password)) if password and secret_store.available() else ""
            )
        else:
            values["student_id"] = ""
            values["password_protected"] = ""
        self.settings_repo.save_settings(values)
        return self.get_saved_credentials()

    # ------------------------------------------------------- browser
    def browser_status(self):
        status = browser_setup.chromium_status()
        status["install"] = dict(self._browser_install)
        return status

    def install_browser(self):
        if self._browser_install["running"]:
            return self.browser_status()
        self._browser_install = {"running": True, "ok": None, "message": "Starting download..."}

        def work():
            def output(line):
                self._browser_install["message"] = line[-160:]

            ok, last = browser_setup.install_chromium(on_output=output)
            self._browser_install = {
                "running": False,
                "ok": ok,
                "message": "Browser installed." if ok else f"Install failed: {last}",
            }

        threading.Thread(target=work, name="browser-install", daemon=True).start()
        return self.browser_status()

    # ------------------------------------------------------- diagnostics
    def open_logs_folder(self):
        os.makedirs(LOG_DIR, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(LOG_DIR)  # noqa: S606 - opens Explorer on our own folder
        else:
            subprocess.Popen(["xdg-open", LOG_DIR])
        return LOG_DIR

    # --------------------------------------------------------------- runs
    def _begin(self, method, headless, options, target_name, student_id, password, message, kind="run"):
        with self._lock:
            if self._thread and self._thread.is_alive():
                if self._board.snapshot()["running"]:
                    raise RuntimeError("A registration run is already in progress")
                # The last run has reported its result and is just winding down.
                self._thread.join(timeout=10)
                if self._thread.is_alive():
                    raise RuntimeError("The previous run is still shutting down. Try again in a moment.")
            self._board = StatusBoard()
            self._board.update(
                running=True,
                phase="login",
                message=message,
                total=len(self._plans[0]["courses"]),
                kind=kind,
                started_at=time.time(),
            )
            self._runner = PlanRunner(
                plans=[{"name": plan["name"], "courses": list(plan["courses"])} for plan in self._plans],
                method=method,
                headless=bool(headless),
                options=options or {},
                board=self._board,
            )
            target = getattr(self._runner, target_name)
            self._thread = threading.Thread(target=target, args=(student_id, password), daemon=True)
            self._thread.start()
        return self.get_status()

    def start(self, student_id, password, method="BeautifulSoup", headless=False, options=None):
        """Start a registration run.

        options: fallback_mode ("auto" | "ask"), auto_retry_seconds, max_attempts,
        start_at (epoch seconds for a scheduled start). Courses that are already
        registered are skipped, so starting again retries only what is missing.
        """
        return self._begin(method, headless, options, "run", student_id, password, "Preparing login...")

    def preflight(self, student_id, password, method="BeautifulSoup", headless=False):
        """Check credentials, course codes, groups, availability and clashes without bidding."""
        return self._begin(method, headless, None, "preflight", student_id, password,
                           "Preparing pre-flight check...", kind="preflight")

    def choose(self, codes):
        """Answer a fallback prompt with the course codes to bid."""
        runner = self._runner
        if runner is not None:
            runner.submit_choice(codes)
        return self.get_status()

    def cancel(self):
        runner, thread, board = self._runner, self._thread, self._board
        if runner is not None:
            runner.cancel()
            if thread is not None and thread.is_alive():
                watchdog = threading.Thread(
                    target=self._release_if_stuck, args=(thread, board), daemon=True
                )
                watchdog.start()
        return self.get_status()

    def _release_if_stuck(self, thread, board):
        """Safety net: Stop must never leave the app stuck.

        If the worker has not finished within STOP_GRACE_SECONDS of a stop
        (for example a network call that never returns), report the run as
        stopped and let the user start again; the old worker is abandoned.
        """
        thread.join(timeout=self.STOP_GRACE_SECONDS)
        if not thread.is_alive():
            return
        logger.error("Worker did not stop within %s s; abandoning it", self.STOP_GRACE_SECONDS)
        board.update(
            running=False,
            phase="cancelled",
            message="Stopped. A request to the portal did not respond and was abandoned.",
            proposal=None,
            next_retry_at=None,
            stopping=False,
        )
        with self._lock:
            if self._thread is thread:
                self._thread = None
                self._runner = None

    def get_status(self):
        return self._board.snapshot()

    def cleanup(self):
        runner, thread = self._runner, self._thread
        if runner is not None:
            runner.cancel()
        if thread is not None and thread.is_alive():
            thread.join(timeout=20)


def run():
    from .utils.process_guard import kill_children_on_exit

    kill_children_on_exit()
    browser_setup.configure_browsers_path()
    api = DesktopApi()
    atexit.register(api.cleanup)
    index_path = _frontend_index_path()
    if not os.path.exists(index_path):
        raise FileNotFoundError("Vue frontend is not built. Run npm install and npm run build in web/.")
    webview.create_window(
        "UTAR Course Bidding",
        index_path,
        js_api=api,
        width=1280,
        height=850,
        min_size=(960, 680),
        background_color="#e8eee8",
    )
    try:
        webview.start(debug=False)
    finally:
        api.cleanup()


def _frontend_index_path():
    """Return the Vue entry file from source or PyInstaller's extracted bundle."""
    bundle_dir = getattr(sys, "_MEIPASS", BASE_DIR)
    return os.path.join(bundle_dir, "web", "dist", "index.html")
