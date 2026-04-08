"""
Playwright implementation for browser-based bidding.
"""

from threading import Event
from typing import List

from playwright.sync_api import Error, TimeoutError as PlaywrightTimeoutError, sync_playwright

from ..utils.config import COURSE_REGISTRATION_URL, LOGIN_URL, PLAYWRIGHT_OPTIONS, WAIT_TIME_SHORT
from ..utils.captcha_solver import CaptchaSolver
from ..utils.logger import setup_logger
from ..utils.timetable_reader import Course

logger = setup_logger(__name__)


class PlaywrightScraper:
    """Browser automation scraper powered by Playwright."""

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._student_id = ""
        self._password = ""
        self._headless_mode = False
        self._cancellation_token = Event()
        self.captcha_solver = CaptchaSolver()

    def set_headless_mode(self, enabled: bool) -> None:
        self._headless_mode = enabled

    def cancel(self) -> None:
        self._cancellation_token.set()

    def reset_cancellation(self) -> None:
        self._cancellation_token.clear()

    def _check_cancellation(self) -> None:
        if self._cancellation_token.is_set():
            raise Exception("Operation cancelled by user")

    def _ensure_browser(self) -> None:
        if self._browser:
            return

        self._playwright = sync_playwright().start()
        launch_args = {"headless": self._headless_mode}
        extra_args = [opt for opt in PLAYWRIGHT_OPTIONS if opt]
        if extra_args:
            launch_args["args"] = extra_args

        self._browser = self._playwright.chromium.launch(**launch_args)
        self._context = self._browser.new_context()
        self._page = self._context.new_page()
        self._page.on("dialog", self._handle_dialog)

    def _handle_dialog(self, dialog) -> None:
        """Log and accept browser dialog prompts from registration flow."""
        text = dialog.message or ""
        logger.info(f"[Playwright] Dialog: {text}")
        dialog.accept()

    def _safe_int(self, value: str) -> int:
        try:
            return int(value.strip())
        except Exception:
            return -1

    def login(self, student_id: str, password: str) -> bool:
        if not student_id or not password:
            raise Exception("Student ID or password is not set")

        self._student_id = student_id
        self._password = password

        self._ensure_browser()
        self._check_cancellation()

        try:
            self._page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=int(WAIT_TIME_SHORT * 1000) * 4)
            self._page.fill("input[name=reqFregkey]", student_id)
            self._page.fill("input[name=reqPassword]", password)

            # Try OCR flow if CAPTCHA exists.
            captcha = self._page.locator("xpath=//input[@name='kaptchafield']/../img[1]")
            if captcha.count() > 0:
                captcha_bytes = captcha.screenshot()
                captcha_pass = self.captcha_solver.solve(captcha_bytes)
                self._page.fill("input[name=kaptchafield]", captcha_pass)

            self._page.press("input[name=kaptchafield]", "Enter")
            self._page.wait_for_selector("text=Log Out", timeout=int(WAIT_TIME_SHORT * 1000))
            logger.info("Playwright login successful")
            return True
        except (PlaywrightTimeoutError, Error) as exc:
            logger.error(f"Playwright login failed: {exc}")
            return False

    def register_courses(self, courses: List[Course]) -> bool:
        if not self._page:
            return False

        for course in courses:
            self._check_cancellation()
            logger.info(f"[Playwright] Attempting bid for {course.code} - {course.name}")
            if not self.register_course(course):
                logger.warning(f"[Playwright] Registration flow failed for {course.code}")

        return True

    def register_course(self, course: Course) -> bool:
        """Register one course by choosing first available slot based on priority."""
        if not self._page:
            return False

        try:
            self._check_cancellation()
            self._page.goto(COURSE_REGISTRATION_URL, wait_until="domcontentloaded", timeout=int(WAIT_TIME_SHORT * 1000) * 4)
            self._page.wait_for_selector("table#tblGrid", timeout=int(WAIT_TIME_SHORT * 1000) * 2)

            self._page.fill("input#reqUnit[name=reqUnit]", course.code)
            self._page.press("input#reqUnit[name=reqUnit]", "Enter")
            self._page.wait_for_selector("form[name=frmSummary]", timeout=int(WAIT_TIME_SHORT * 1000) * 2)

            rows = self._page.locator("form[name=frmSummary] tr")
            row_count = rows.count()
            best_priority = {"L": 10**9, "T": 10**9, "P": 10**9}
            selected_rows = {"L": None, "T": None, "P": None}

            for i in range(row_count):
                self._check_cancellation()
                row = rows.nth(i)
                checkbox = row.locator("input[type=checkbox]")
                if checkbox.count() == 0:
                    continue

                tds = row.locator("td")
                if tds.count() < 3:
                    continue

                class_type = tds.nth(1).inner_text().strip()
                class_slot = self._safe_int(tds.nth(2).inner_text())

                if class_type not in course.slots:
                    continue
                desired_slots = course.slots.get(class_type, [])
                if class_slot not in desired_slots:
                    continue

                priority = desired_slots.index(class_slot)
                if priority >= best_priority[class_type]:
                    continue

                best_priority[class_type] = priority
                selected_rows[class_type] = row

            required_types = [key for key, values in course.slots.items() if values]
            for class_type in required_types:
                target_row = selected_rows.get(class_type)
                if not target_row:
                    logger.warning(f"[Playwright] No valid slot for {course.code} class {class_type}")
                    return True
                target_row.locator("input[type=checkbox]").first.check(force=True)

            submit_button = self._page.locator("form[name=frmSummary] input[name=Submit]")
            if submit_button.count() == 0:
                logger.warning(f"[Playwright] Submit button missing for {course.code}")
                return False

            submit_button.first.click()
            self._page.wait_for_timeout(500)
            return True
        except (PlaywrightTimeoutError, Error) as exc:
            logger.warning(f"[Playwright] Failed processing course {course.code}: {exc}")
            return False

    def cleanup(self) -> None:
        try:
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
        finally:
            self._context = None
            self._browser = None
            self._page = None
            if self._playwright:
                self._playwright.stop()
            self._playwright = None
