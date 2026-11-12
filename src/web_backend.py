"""Python API used by the Vue desktop frontend."""

import json
import os
import sqlite3
import sys
import tempfile
import threading
from copy import deepcopy

import webview

from .models.course import Course
from .services.plan_runner import PlanRunner, StatusBoard
from .storage.database import CourseRepository, Database, PlanRepository
from .utils.config import BASE_DIR
from .utils.timetable_reader import TimetableReader
from .utils.logger import setup_logger

logger = setup_logger(__name__)


class DesktopApi:
    """Small local API exposed to Vue through pywebview."""

    def __init__(self, database=None):
        # Courses live in SQLite; the old JSON file is imported once if the table is empty.
        database = database or Database()
        self.courses_file = os.path.join(BASE_DIR, "data", "courses.json")
        self.course_repo = CourseRepository(database)
        self.course_repo.migrate_from_json(self.courses_file)
        # Timetable plans (Plan A, B, ...). The legacy single list becomes Plan A.
        self.plan_repo = PlanRepository(database)
        self.plan_repo.ensure_initial_plan(self.course_repo)
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

    def import_courses(self, filename, content, plan_index=0):
        if filename.lower().endswith(".json"):
            courses = [Course(**course) for course in json.loads(content)]
        else:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as file:
                file.write(content)
                temp_path = file.name
            try:
                courses = TimetableReader.read_timetable(temp_path)
            finally:
                os.unlink(temp_path)
        plan_index = int(plan_index or 0)
        if not 0 <= plan_index < len(self._plans):
            raise ValueError("That plan does not exist")
        self._plans[plan_index]["courses"] = courses
        self._persist()
        return [course.__dict__ for course in courses]

    # --------------------------------------------------------------- runs
    def _begin(self, method, headless, options, target_name, student_id, password, message):
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise RuntimeError("A registration run is already in progress")
            self._board = StatusBoard()
            self._board.update(
                running=True,
                phase="login",
                message=message,
                total=len(self._plans[0]["courses"]),
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
        return self._begin(method, headless, None, "preflight", student_id, password, "Preparing pre-flight check...")

    def choose(self, codes):
        """Answer a fallback prompt with the course codes to bid."""
        runner = self._runner
        if runner is not None:
            runner.submit_choice(codes)
        return self.get_status()

    def cancel(self):
        runner = self._runner
        if runner is not None:
            runner.cancel()
        return self.get_status()

    def get_status(self):
        return self._board.snapshot()

    def cleanup(self):
        runner, thread = self._runner, self._thread
        if runner is not None:
            runner.cancel()
        if thread is not None and thread.is_alive():
            thread.join(timeout=20)


def run():
    api = DesktopApi()
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
