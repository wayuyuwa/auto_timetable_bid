"""Playwright implementation for UTAR course registration."""

import functools
import json
import queue
import threading
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError
from threading import Event

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from ..models.course import Course
from ..utils.captcha_solver import CaptchaSolver
from ..utils.config import (
    COURSE_REGISTRATION_URL,
    LOGIN_URL,
    PLAYWRIGHT_ARGS,
    WAIT_TIME_LONG,
    WAIT_TIME_SHORT,
)
from ..utils.logger import setup_logger
from .html_parser import parse_home_page

logger = setup_logger(__name__)

# How long cleanup() waits for an in-flight browser operation before giving up.
CLEANUP_WAIT_SECONDS = 15


class _OwnerThread:
    """Single daemon thread that owns the Playwright sync API objects.

    Playwright's sync API must be used from the thread that started it, but
    login/bid run on worker threads and cleanup runs on the UI thread, so every
    browser call is funnelled through this one thread.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._queue = None
        self._thread = None

    def _ensure_started(self):
        with self._lock:
            if self._thread is None:
                self._queue = queue.Queue()
                self._thread = threading.Thread(
                    target=self._run, args=(self._queue,), name="playwright-owner", daemon=True
                )
                self._thread.start()
            return self._queue

    @staticmethod
    def _run(work_queue):
        while True:
            func, future = work_queue.get()
            if func is None:
                return
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(func())
            except BaseException as error:
                future.set_exception(error)

    def call(self, func, timeout=None):
        if threading.current_thread() is self._thread:
            return func()
        future = Future()
        self._ensure_started().put((func, future))
        return future.result(timeout)

    def stop(self):
        """Let the thread exit after queued work; a later call() starts a new one."""
        with self._lock:
            if self._thread is None:
                return
            self._queue.put((None, None))
            self._queue = None
            self._thread = None


def _on_owner_thread(method):
    """Run a PlaywrightScraper method on its owner thread."""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        return self._owner.call(lambda: method(self, *args, **kwargs))

    return wrapper


class PlaywrightScraper:
    """Browser scraper with explicit ownership of Playwright resources."""

    def __init__(self):
        self._playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.captcha_solver = CaptchaSolver()
        self.student_id = None
        self.password = None
        self._headless_mode = False
        self._is_cleaning_up = False
        self._cancellation_token = Event()
        self._is_logged_in = False
        self._owner = _OwnerThread()

    def set_headless_mode(self, enabled: bool):
        self._headless_mode = enabled

    def reset_cancellation(self):
        self._cancellation_token.clear()

    def cancel(self):
        self._cancellation_token.set()
        logger.info("Playwright cancellation requested")

    def _check_cancellation(self):
        if self._cancellation_token.is_set():
            raise RuntimeError("Operation cancelled by user")
        if self._is_cleaning_up:
            raise RuntimeError("Playwright scraper is being cleaned up")

    def is_cancelled(self) -> bool:
        return self._cancellation_token.is_set()

    def is_logged_in(self) -> bool:
        return self._is_logged_in

    def _ensure_page(self):
        if self.page:
            return self.page
        if self._is_cleaning_up:
            raise RuntimeError("Playwright scraper is being cleaned up")

        self._playwright = sync_playwright().start()
        args = [option for option in PLAYWRIGHT_ARGS if option]
        self.browser = self._playwright.chromium.launch(
            headless=self._headless_mode,
            args=args,
        )
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        self.page.set_default_timeout(WAIT_TIME_LONG * 1000)
        return self.page

    def _goto(self, url: str):
        self._check_cancellation()
        self._ensure_page().goto(url, wait_until="domcontentloaded")
        self._check_cancellation()

    @_on_owner_thread
    def login(self, student_id: str, password: str) -> bool:
        if not student_id or not password:
            raise ValueError("Student ID and password are required")

        self.student_id = student_id
        self.password = password
        self._is_logged_in = False
        page = self._ensure_page()

        try:
            self._goto(LOGIN_URL)
            page.locator("form[name=frmParam]").wait_for(state="visible", timeout=WAIT_TIME_SHORT * 1000)
            page.locator("input[name=reqFregkey]").fill(student_id)
            page.locator("input[name=reqPassword]").fill(password)
            captcha = page.locator("input[name=kaptchafield]").locator("xpath=preceding-sibling::img[1]")
            captcha_bytes = captcha.screenshot()
            page.locator("input[name=kaptchafield]").fill(self.captcha_solver.solve(captcha_bytes))
            page.locator("input[name=kaptchafield]").press("Enter")
            page.locator("span", has_text="Log Out").wait_for(
                state="visible", timeout=WAIT_TIME_SHORT * 1000
            )
            self._is_logged_in = True
            return True
        except PlaywrightTimeoutError:
            return False
        except PlaywrightError as error:
            logger.error("Playwright login failed: %s", error)
            return False

    @_on_owner_thread
    def get_home_page_data(self):
        page = self._ensure_page()
        self._goto(COURSE_REGISTRATION_URL)
        return parse_home_page(page.content()), self.context.cookies()

    @_on_owner_thread
    def store_cookies(self, path: str = "cookies.txt"):
        if self.context:
            with open(path, "w", encoding="utf-8") as file:
                json.dump(self.context.cookies(), file)

    @_on_owner_thread
    def register_course(self, course: Course) -> tuple[str, bool]:
        page = self._ensure_page()
        self._goto(COURSE_REGISTRATION_URL)
        page.locator("table#tblGrid").wait_for(state="visible")
        page.locator("input#reqUnit[name=reqUnit]").fill(course.code)
        page.locator("input#reqUnit[name=reqUnit]").press("Enter")
        page.locator("form[name=frmSummary]").wait_for(state="visible")

        selected = {}
        rows = page.locator("form[name=frmSummary] tr").all()
        for row in rows:
            self._check_cancellation()
            columns = row.locator("td")
            if columns.count() < 3:
                continue
            class_type = columns.nth(1).inner_text().strip()
            try:
                class_slot = int(columns.nth(2).inner_text().strip())
            except ValueError:
                continue
            if class_slot not in course.slots.get(class_type, []):
                continue
            checkbox = row.locator("input[name=reqMid]")
            if not checkbox.count():
                continue
            if class_type in selected:
                selected[class_type].uncheck()
            checkbox.check()
            selected[class_type] = checkbox

        required_types = {key for key, slots in course.slots.items() if slots}
        if set(selected) != required_types:
            return f"No available slots for {course.code}", False

        dialog_message = []

        def handle_dialog(dialog):
            dialog_message.append(dialog.message)
            dialog.accept()

        page.once("dialog", handle_dialog)
        page.locator("input[name=Submit]").last.click()
        self._check_cancellation()
        message = dialog_message[0].lower() if dialog_message else ""
        if "valid class combination" in message:
            return "Invalid timetable", False
        return f"Registered {course.code}", True

    @_on_owner_thread
    def register_courses(self, courses: list[Course]) -> tuple[str, bool]:
        if not courses:
            return "No courses provided for registration", False
        results = []
        success = True
        for course in courses:
            self._check_cancellation()
            try:
                message, course_success = self.register_course(course)
            except (PlaywrightError, PlaywrightTimeoutError) as error:
                message, course_success = f"Registration error: {error}", False
            results.append(message)
            success = success and course_success
        return "\n".join(results), success

    def cleanup(self):
        """Close the browser on its owner thread; safe to call from any thread."""
        self.cancel()  # make an in-flight operation stop at its next checkpoint
        try:
            self._owner.call(self._close_browser, timeout=CLEANUP_WAIT_SECONDS)
        except FutureTimeoutError:
            logger.warning("Playwright did not shut down within %s s", CLEANUP_WAIT_SECONDS)
        finally:
            self._owner.stop()

    def _close_browser(self):
        if self._is_cleaning_up:
            return
        self._is_cleaning_up = True
        try:
            if self.context:
                self.context.close()
            if self.browser:
                self.browser.close()
            if self._playwright:
                self._playwright.stop()
        finally:
            self.page = None
            self.context = None
            self.browser = None
            self._playwright = None
            self._is_logged_in = False
            self._is_cleaning_up = False
            self.reset_cancellation()
