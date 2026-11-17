"""Registration closed: the run waits (checking every few seconds, until Stop) and then bids.

While registration is closed the real portal shows the registered-courses page and no registration
form (checked 2026-11-17); the mock reproduces that with SERVER.registration_open = False.
The first release (v1.0.0) waited the same way, for the missing Register button.

    venv\\Scripts\\python -m unittest tests/test_registration_open.py
"""

import threading
import time
import unittest

import requests

from tests.test_plan_runner import SERVER, RunnerCase, course, plan  # noqa: F401 - sets UTAR_BASE_URL first

from src.mock_server import expire_next  # noqa: E402
from src.scrapers.beautifulsoup_scraper import BeautifulSoupScraper  # noqa: E402
from src.scrapers.html_parser import registration_form_open  # noqa: E402
from src.scrapers.playwright_scraper import PlaywrightScraper  # noqa: E402
from src.services.plan_runner import PlanRunner, StatusBoard  # noqa: E402
from src.utils import browser_setup  # noqa: E402

CHROMIUM = browser_setup.chromium_status()["installed"]


class ParserTests(unittest.TestCase):
    def test_closed_page_has_no_registration_form(self):
        closed = ('<table id="tblGrid"></table><form name="frmSummary">'
                  '<input name="act"><input name="reqFregkey" value="x"><input name="reqRGSid"></form>')
        self.assertFalse(registration_form_open(closed))

    def test_unit_box_register_button_and_lookup_answer_count_as_open(self):
        self.assertTrue(registration_form_open('<input type="text" id="reqUnit" name="reqUnit">'))
        self.assertTrue(registration_form_open('<input name="Register" value="Register Course">'))
        answer = "".join(f'<input type="hidden" name="{n}" value="1">'
                         for n in ("reqPaperType", "reqSession", "reqSid", "reqWithClass"))
        self.assertTrue(registration_form_open(answer))


class ScraperTests(RunnerCase):
    def test_beautifulsoup_open_and_closed(self):
        scraper = BeautifulSoupScraper()
        try:
            scraper.login("2103370", "pw")
            for code in ("MOCK1001", None):  # with a unit lookup, and by reading the page
                self.assertTrue(scraper.registration_open(code), code)
            SERVER.registration_open = False
            for code in ("MOCK1001", None):
                self.assertFalse(scraper.registration_open(code), code)
        finally:
            scraper.cleanup()

    def test_beautifulsoup_check_logs_in_again_when_the_session_ended(self):
        scraper = BeautifulSoupScraper()
        try:
            scraper.login("2103370", "pw")
            expire_next(SERVER, "registerUnitSurvey.jsp", "js")
            self.assertTrue(scraper.registration_open("MOCK1001"))
        finally:
            scraper.cleanup()

    @unittest.skipUnless(CHROMIUM, "Playwright Chromium is not installed")
    def test_playwright_open_and_closed(self):
        scraper = PlaywrightScraper()
        scraper.set_headless_mode(True)
        try:
            scraper.login("2103370", "pw")
            self.assertTrue(scraper.registration_open())
            SERVER.registration_open = False
            self.assertFalse(scraper.registration_open())
        finally:
            scraper.cleanup()


class WaitTests(RunnerCase):
    METHODS = ["BeautifulSoup"] + (["Playwright"] if CHROMIUM else [])

    def start(self, method, **kwargs):
        runner = PlanRunner([plan("Plan A", course("MOCK1001", L=[1], T=[1]))], method=method, headless=True,
                            board=StatusBoard(), **kwargs)
        runner.open_check_seconds = 0.2
        thread = threading.Thread(target=runner.run, args=("2103370", "pw"), daemon=True)
        thread.start()
        self.addCleanup(self.stop, runner, thread)
        return runner, thread

    @staticmethod
    def stop(runner, thread):
        runner.cancel()
        thread.join(timeout=30)

    def wait_checks(self, runner, count, timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if runner.board.snapshot()["open_checks"] >= count:
                return
            time.sleep(0.05)
        self.fail(f"fewer than {count} checks: {runner.board.snapshot()}")

    def test_waits_while_closed_then_bids_once_it_opens(self):
        for method in self.METHODS:
            with self.subTest(method=method):
                SERVER.registered.clear()
                SERVER.processed_submits = 0
                SERVER.registration_open = False
                runner, thread = self.start(method)
                self.wait_phase(runner, "waiting_open", timeout=30)
                self.wait_checks(runner, 3)
                status = runner.board.snapshot()
                self.assertTrue(status["running"])
                self.assertEqual(SERVER.processed_submits, 0, "nothing may be bid while closed")
                self.assertEqual(status["attempt"], 1, "waiting must not use up attempts")
                self.assertIn("not open yet", status["message"])
                SERVER.registration_open = True
                thread.join(timeout=60)
                self.assertFalse(thread.is_alive())
                status = runner.board.snapshot()
                self.assertEqual(status["phase"], "complete", status["message"])
                self.assertEqual(status["results"]["MOCK1001"]["label"], "Confirmed")
                self.assertEqual(SERVER.processed_submits, 1)
                self.assertEqual(status["attempt"], 1)

    def test_each_look_after_the_first_logs_in_again(self):
        for method in self.METHODS:
            with self.subTest(method=method):
                SERVER.registration_open = False
                runner, thread = self.start(method)
                self.wait_checks(runner, 4, timeout=60)
                logins = SERVER.hits["loginProSurvey.jsp"]
                runner.cancel()
                thread.join(timeout=30)
                SERVER.hits["loginProSurvey.jsp"] = 0
                self.assertGreaterEqual(logins, 4, f"{method}: {logins} login(s) for 4 looks")

    def test_stop_ends_the_wait(self):
        for method in self.METHODS:
            with self.subTest(method=method):
                SERVER.registration_open = False
                runner, thread = self.start(method)
                self.wait_phase(runner, "waiting_open", timeout=30)
                started = time.time()
                runner.cancel()
                thread.join(timeout=30)
                self.assertFalse(thread.is_alive(), "Stop must end the wait")
                self.assertEqual(runner.board.snapshot()["phase"], "cancelled")
                self.assertLess(time.time() - started, 25)
                self.assertEqual(SERVER.processed_submits, 0)

    def test_a_failed_check_is_logged_and_tried_again(self):
        class Flaky(BeautifulSoupScraper):
            failures = 2

            def registration_open(self, unit_code=None):
                if Flaky.failures > 0:
                    Flaky.failures -= 1
                    raise requests.ConnectionError("portal not answering")
                return super().registration_open(unit_code)

        runner = PlanRunner([plan("Plan A", course("MOCK1001", L=[1], T=[1]))], board=StatusBoard(),
                            scraper_factory=lambda method, headless: Flaky())
        runner.open_check_seconds = 0.1
        runner.run("2103370", "pw")
        status = runner.board.snapshot()
        self.assertEqual(status["phase"], "complete", status["message"])
        self.assertTrue(any("Could not check whether registration is open" in entry["text"]
                            for entry in status["log"]))
        self.assertGreaterEqual(status["open_checks"], 2)

    def test_a_scraper_without_the_check_is_never_waited_for(self):
        class Legacy(BeautifulSoupScraper):
            registration_open = None  # no way to tell: assume open, do not wait forever

        runner = PlanRunner([plan("Plan A", course("MOCK1001", L=[1], T=[1]))], board=StatusBoard(),
                            scraper_factory=lambda method, headless: Legacy())
        SERVER.registration_open = False
        runner.run("2103370", "pw")  # the bid itself then finds the portal closed
        self.assertNotEqual(runner.board.snapshot()["phase"], "waiting_open")


class PreflightTests(RunnerCase):
    def run_preflight(self):
        runner = PlanRunner([plan("Plan A", course("MOCK1001", L=[1], T=[1]))], board=StatusBoard())
        runner.preflight("2103370", "pw")
        return runner.board.snapshot()

    def test_reports_that_registration_is_open(self):
        status = self.run_preflight()
        texts = [check["text"] for check in status["preflight"]["checks"]]
        self.assertIn("Registration is open.", texts)
        self.assertEqual([step["state"] for step in status["steps"]], ["ok", "ok", "ok", "ok"])

    def test_closed_registration_is_a_warning_and_skips_the_class_checks(self):
        SERVER.registration_open = False
        status = self.run_preflight()
        self.assertEqual(status["phase"], "preflight_done")
        checks = status["preflight"]["checks"]
        self.assertTrue(any(c["level"] == "warn" and "not open yet" in c["text"] for c in checks), checks)
        self.assertFalse(any(c["level"] == "error" for c in checks), "no errors for classes that cannot load")
        self.assertEqual([step["state"] for step in status["steps"]], ["ok", "ok", "skipped", "skipped"])


if __name__ == "__main__":
    unittest.main()
