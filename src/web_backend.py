"""Python API used by the Vue desktop frontend."""

import json
import os
import sys
import tempfile
import threading
from copy import deepcopy

import webview

from .models.course import Course
from .services.bidding_service import BiddingService
from .utils.config import BASE_DIR
from .utils.timetable_reader import TimetableReader
from .utils.logger import setup_logger

logger = setup_logger(__name__)


class DesktopApi:
    """Small local API exposed to Vue through pywebview."""

    def __init__(self):
        self.courses_file = os.path.join(BASE_DIR, "data", "courses.json")
        os.makedirs(os.path.dirname(self.courses_file), exist_ok=True)
        self.service = BiddingService()
        self.service.login_progress.connect(self._on_login_progress)
        self.service.login_completed.connect(self._on_login_completed)
        self.service.bid_started.connect(self._on_bid_started)
        self.service.bid_progress.connect(self._on_bid_progress)
        self.service.bid_course_completed.connect(self._on_course_completed)
        self.service.bid_all_completed.connect(self._on_bid_completed)
        self.service.session_expired.connect(self._on_session_expired)
        self.service.network_error.connect(self._on_network_error)
        self.service.operation_cancelled.connect(self._on_cancelled)
        self._lock = threading.Lock()
        self._thread = None
        self._courses = self._load_courses()
        self._status = self._empty_status()

    def _empty_status(self):
        return {
            "running": False,
            "phase": "idle",
            "message": "Ready",
            "completed": 0,
            "total": 0,
            "results": {},
        }

    def _load_courses(self):
        try:
            if not os.path.exists(self.courses_file):
                return []
            with open(self.courses_file, "r", encoding="utf-8") as file:
                return [Course(**course) for course in json.load(file)]
        except (OSError, ValueError, TypeError) as error:
            logger.error("Failed to load courses: %s", error)
            return []

    def get_courses(self):
        return [course.__dict__ for course in self._courses]

    def save_courses(self, courses):
        parsed = [Course(**course) for course in courses]
        with open(self.courses_file, "w", encoding="utf-8") as file:
            json.dump([course.__dict__ for course in parsed], file, indent=4)
        self._courses = parsed
        return self.get_courses()

    def import_courses(self, filename, content):
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
        self._courses = courses
        self.save_courses(self.get_courses())
        return self.get_courses()

    def start(self, student_id, password, method="BeautifulSoup", headless=False):
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise RuntimeError("A registration run is already in progress")
            self.service.set_scraper_type(method)
            self.service.set_headless_mode(bool(headless))
            self.service.reset_cancellation()
            self._status = self._empty_status()
            self._status.update({
                "running": True,
                "phase": "login",
                "message": "Preparing login...",
                "total": len(self._courses),
            })
            self._thread = threading.Thread(target=self.service.login, args=(student_id, password), daemon=True)
            self._thread.start()
        return self.get_status()

    def cancel(self):
        self.service.cancel()
        return self.get_status()

    def get_status(self):
        with self._lock:
            return deepcopy(self._status)

    def _update(self, **values):
        with self._lock:
            self._status.update(values)

    def _on_login_progress(self, message):
        self._update(phase="login", message=message)

    def _on_login_completed(self, success, message):
        if not success:
            self._update(running=False, phase="error", message=message)
            return
        self._update(phase="bidding", message="Login successful. Starting course registration...")
        self.service.bid_courses(self._courses)

    def _on_bid_started(self, total):
        self._update(phase="bidding", total=total, message=f"Starting registration for {total} course(s)...")

    def _on_bid_progress(self, message, current, total):
        self._update(phase="bidding", completed=current - 1, total=total, message=message)

    def _on_course_completed(self, result):
        status = "success" if result.is_successful() else "failed"
        with self._lock:
            self._status["results"][result.course_code] = {
                "status": status,
                "label": "Success" if status == "success" else "Needs attention",
                "message": result.message,
            }
            self._status["completed"] = len(self._status["results"])
            self._status["message"] = result.message

    def _on_bid_completed(self, success, results):
        self._update(
            running=False,
            phase="complete" if success else "error",
            completed=len(results),
            message="All courses registered successfully." if success else "Registration finished with items needing attention.",
        )

    def _on_session_expired(self):
        self._update(running=False, phase="error", message="Your session expired. Please log in again.")

    def _on_network_error(self, message):
        self._update(running=False, phase="error", message=message)

    def _on_cancelled(self):
        self._update(running=False, phase="cancelled", message="Registration cancelled safely.")

    def cleanup(self):
        self.service.cancel()
        self.service.cleanup()


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
