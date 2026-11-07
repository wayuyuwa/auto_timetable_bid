"""Playwright implementation for UTAR course registration."""

import json
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

    def get_home_page_data(self):
        page = self._ensure_page()
        self._goto(COURSE_REGISTRATION_URL)
        return parse_home_page(page.content()), self.context.cookies()

    def store_cookies(self, path: str = "cookies.txt"):
        if self.context:
            with open(path, "w", encoding="utf-8") as file:
                json.dump(self.context.cookies(), file)

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
