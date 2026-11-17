"""Several browser tabs bidding together (Playwright option) and the notSupportTab login refusal.

Rules checked: every course is registered once (never sent twice, also when the session ends
mid-batch), tabs are ignored by BeautifulSoup, pre-flight tests the tabs, and UTAR's
login.jsp?message=notSupportTab is reported as "close the other tab/window".

    venv\\Scripts\\python -m unittest tests/test_multi_tab.py
"""

import unittest

from tests.test_plan_runner import SERVER, RunnerCase, course, plan  # noqa: F401 - sets UTAR_BASE_URL first

from src.mock_server import expire_next  # noqa: E402
from src.scrapers.errors import MultipleTabs, portal_rejection  # noqa: E402
from src.scrapers.playwright_scraper import PlaywrightScraper  # noqa: E402
from src.services.plan_runner import PlanRunner, StatusBoard  # noqa: E402
from src.utils import browser_setup  # noqa: E402

CHROMIUM = browser_setup.chromium_status()["installed"]
SUBMIT = "registerUnitProSurvey.jsp"
CODES = ["MOCK1001", "MOCK1002", "MOCK1003"]


def courses():
    return [course(code, L=[1], T=[1]) for code in CODES]


class Recording(PlaywrightScraper):
    batches = []

    def register_batch(self, group):
        Recording.batches.append([c.code for c in group])
        return super().register_batch(group)


def recording_factory(method, headless):
    scraper = Recording()
    scraper.set_headless_mode(True)
    return scraper


class NotSupportTabTests(unittest.TestCase):
    def test_code_is_reported_as_multiple_tabs(self):
        for text in ("", "Multiple tabs or windows are not supported"):
            error = portal_rejection("notSupportTab", text)
            self.assertIsInstance(error, MultipleTabs)
            self.assertEqual(error.kind, "multiple_tabs")
            self.assertIn("another browser tab or window", str(error))


@unittest.skipUnless(CHROMIUM, "Playwright Chromium is not installed")
class TabsTests(RunnerCase):
    def setUp(self):
        super().setUp()
        Recording.batches = []

    def run_with(self, tabs, **extra):
        runner = PlanRunner([plan("Plan A", *courses())], method="Playwright", headless=True,
                            options={"tabs": tabs}, board=StatusBoard(), scraper_factory=recording_factory)
        runner.run("2103370", "pw")
        return runner, runner.board.snapshot()

    def test_three_tabs_bid_three_courses_together(self):
        _runner, status = self.run_with(3)
        self.assertEqual(status["phase"], "complete", status["message"])
        self.assertEqual(Recording.batches, [CODES])
        self.assertEqual(sorted(SERVER.registered), CODES)
        self.assertEqual(SERVER.processed_submits, 3)
        self.assertEqual({r["label"] for r in status["results"].values()}, {"Confirmed"})

    def test_two_tabs_make_batches_of_two_and_one(self):
        _runner, status = self.run_with(2)
        self.assertEqual(status["phase"], "complete", status["message"])
        self.assertEqual(Recording.batches, [CODES[:2], CODES[2:]])
        self.assertEqual(SERVER.processed_submits, 3)

    def test_one_tab_is_the_old_way(self):
        _runner, status = self.run_with(1)
        self.assertEqual(status["phase"], "complete", status["message"])
        self.assertEqual(Recording.batches, [])
        self.assertEqual(SERVER.processed_submits, 3)

    def test_a_course_that_cannot_be_bid_does_not_stop_the_others(self):
        runner = PlanRunner([plan("Plan A", course("MOCK1001", L=[1], T=[1]), course("MOCK1002", L=[99], T=[1]),
                                  course("MOCK1003", L=[1], T=[1]))],
                            method="Playwright", headless=True, options={"tabs": 3, "max_attempts": 1},
                            board=StatusBoard(), scraper_factory=recording_factory)
        runner.run("2103370", "pw")
        self.assertEqual(sorted(SERVER.registered), ["MOCK1001", "MOCK1003"])
        self.assertEqual(SERVER.processed_submits, 2)

    def test_session_ended_before_the_bids_logs_in_and_sends_each_once(self):
        expire_next(SERVER, "registerUnitSurvey.jsp", "js")  # the second tab's lookup is answered "expired"
        _runner, status = self.run_with(3)
        self.assertEqual(status["phase"], "complete", status["message"])
        self.assertEqual(sorted(SERVER.registered), CODES)
        self.assertEqual(SERVER.processed_submits, 3, "no bid may be sent twice")

    def test_answer_lost_after_a_submit_is_not_sent_again(self):
        expire_next(SERVER, SUBMIT, "apply-then-js")  # the first bid is applied, its answer is "expired"
        _runner, status = self.run_with(3)
        self.assertEqual(status["phase"], "complete", status["message"])
        self.assertEqual(sorted(SERVER.registered), CODES)
        self.assertEqual(SERVER.processed_submits, 3, "no bid may be sent twice")

    def test_extra_tabs_are_closed_afterwards(self):
        scraper = PlaywrightScraper()
        scraper.set_headless_mode(True)
        try:
            scraper.login("2103370", "pw")
            self.assertEqual([r[1] for r in scraper.register_batch(courses())], [True] * 3)
            self.assertEqual(len(scraper.context.pages), 1)
        finally:
            scraper.cleanup()

    def test_beautifulsoup_ignores_tabs(self):
        runner = PlanRunner([plan("Plan A", *courses())], method="BeautifulSoup",
                            options={"tabs": 3}, board=StatusBoard())
        self.assertEqual(runner.tabs, 1)
        runner.run("2103370", "pw")
        self.assertEqual(runner.board.snapshot()["phase"], "complete")
        self.assertEqual(SERVER.processed_submits, 3)


class PreflightTabsTests(RunnerCase):
    def preflight(self, method, tabs):
        runner = PlanRunner([plan("Plan A", course("MOCK1001", L=[1], T=[1]))], method=method, headless=True,
                            options={"tabs": tabs}, board=StatusBoard())
        runner.preflight("2103370", "pw")
        return runner.board.snapshot()

    @unittest.skipUnless(CHROMIUM, "Playwright Chromium is not installed")
    def test_playwright_checks_the_tabs(self):
        status = self.preflight("Playwright", 3)
        self.assertEqual(status["phase"], "preflight_done", status["message"])
        self.assertEqual([step["id"] for step in status["steps"]],
                         ["login", "registered", "tabs", "plans", "clashes"])
        self.assertEqual([step["state"] for step in status["steps"]], ["ok"] * 5)
        self.assertIn("3 browser tabs stay logged in together.",
                      [check["text"] for check in status["preflight"]["checks"]])

    @unittest.skipUnless(CHROMIUM, "Playwright Chromium is not installed")
    def test_a_tab_the_portal_logs_out_is_a_warning(self):
        original = PlaywrightScraper.check_tabs

        def refused(self, count):
            return False, "Tab 2 was logged out by the portal."

        PlaywrightScraper.check_tabs = refused
        try:
            status = self.preflight("Playwright", 2)
        finally:
            PlaywrightScraper.check_tabs = original
        tabs_step = next(step for step in status["steps"] if step["id"] == "tabs")
        self.assertEqual(tabs_step["state"], "warn")
        self.assertTrue(any(c["level"] == "warn" and "Tab 2" in c["text"] for c in status["preflight"]["checks"]))

    def test_one_tab_adds_no_step(self):
        status = self.preflight("BeautifulSoup", 1)
        self.assertEqual([step["id"] for step in status["steps"]], ["login", "registered", "plans", "clashes"])

    def test_beautifulsoup_with_tabs_warns_that_tabs_are_ignored(self):
        status = self.preflight("BeautifulSoup", 3)
        self.assertEqual([step["id"] for step in status["steps"]], ["login", "registered", "plans", "clashes"])
        self.assertTrue(any(c["level"] == "warn" and "only work with the Playwright" in c["text"]
                            for c in status["preflight"]["checks"]))


if __name__ == "__main__":
    unittest.main()
