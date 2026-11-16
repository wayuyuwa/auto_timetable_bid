"""Session expiry in both scrapers, against the mock portal.

The mock answers a chosen request once as "session expired" (expire_next):
  js            the portal's "session expired" script (what the real portal sends)
  loginpage     the plain login page (HTTP 200)
  hang          no answer until after the client timed out
  apply-then-js the bid is processed, then "session expired" is answered (answer lost)

Rules checked: reading steps log in again and carry on; a bid is never sent twice when it
may already have reached the portal; repeated expiry ends instead of looping.

    venv\\Scripts\\python -m unittest tests/test_session_expiry.py
"""

import time
import unittest

from tests.test_plan_runner import SERVER, RunnerCase, course  # noqa: F401 - sets UTAR_BASE_URL first

from src.mock_server import expire_next  # noqa: E402
from src.scrapers.beautifulsoup_scraper import BeautifulSoupScraper, SessionExpiredException  # noqa: E402
from src.scrapers.playwright_scraper import PlaywrightScraper, SessionExpired  # noqa: E402
from src.utils import browser_setup  # noqa: E402

REG = "studentRegistrationSurvey.jsp"
UNIT = "registerUnitSurvey.jsp"
SUBMIT = "registerUnitProSurvey.jsp"
LOGIN_POST = "loginProSurvey.jsp"
WANTED = course("MOCK1001", L=[1], T=[1])


class HangDelay:
    """Temporarily set how long a 'hang' answer takes."""

    def __init__(self, seconds):
        self.seconds = seconds

    def __enter__(self):
        self.old = SERVER.delay
        SERVER.delay = self.seconds

    def __exit__(self, *exc):
        SERVER.delay = self.old


class BeautifulSoupExpiryTests(RunnerCase):
    def setUp(self):
        super().setUp()
        self.scraper = BeautifulSoupScraper()
        self.scraper.connection_timeout = 1
        self.scraper.login("2103370", "pw")
        SERVER.hits.clear()

    def tearDown(self):
        self.scraper.cleanup()

    def test_registered_list_logs_in_again_after_expired_answer(self):
        expire_next(SERVER, REG, "js")
        data = self.scraper.get_registered_courses()
        self.assertTrue(data["info"])
        self.assertEqual(SERVER.hits[LOGIN_POST], 1)

    def test_registered_list_treats_a_login_page_as_ended_session(self):
        # Without this an empty page would read as "nothing registered".
        expire_next(SERVER, REG, "loginpage")
        data = self.scraper.get_registered_courses()
        self.assertTrue(data["info"], "the page after logging in again must be the real one")
        self.assertEqual(SERVER.hits[LOGIN_POST], 1)

    def test_unit_slots_login_page_logs_in_again(self):
        expire_next(SERVER, UNIT, "loginpage")
        self.assertEqual(len(self.scraper.get_unit_slots("MOCK1001")), 9)
        self.assertEqual(SERVER.hits[LOGIN_POST], 1)

    def test_login_form_answering_the_login_post_is_not_read_as_expiry(self):
        # A wrong captcha also answers with the login form, so login keeps its own handling.
        # Read as "session expired" it would count as a closed portal and log in a 2nd time.
        expire_next(SERVER, LOGIN_POST, "loginpage")
        result = self.scraper.login("2103370", "pw")
        self.assertIn("success", result)
        self.assertEqual(SERVER.hits[LOGIN_POST], 1)

    def test_bid_answered_with_expired_page_is_sent_again_once_after_login(self):
        expire_next(SERVER, SUBMIT, "js")
        text, ok = self.scraper.register_courses([WANTED])
        self.assertTrue(ok, text)
        self.assertEqual(SERVER.processed_submits, 1)  # the expired answer was not a processed bid
        self.assertEqual(SERVER.hits[SUBMIT], 2)
        self.assertEqual(SERVER.hits[LOGIN_POST], 1)

    def test_bid_processed_but_answer_lost_is_not_sent_again(self):
        expire_next(SERVER, SUBMIT, "apply-then-js")
        text, ok = self.scraper.register_courses([WANTED])
        self.assertTrue(ok, text)
        self.assertIn("Already registered", text)
        self.assertEqual(SERVER.processed_submits, 1)
        self.assertEqual(SERVER.hits[SUBMIT], 1)

    def test_timed_out_bid_is_not_sent_again(self):
        with HangDelay(2.5):
            expire_next(SERVER, SUBMIT, "hang")
            text, ok = self.scraper.register_courses([WANTED])
        self.assertFalse(ok)
        self.assertIn("outcome is unknown", text)
        self.assertEqual(SERVER.hits[SUBMIT], 1)

    def test_read_timeout_is_retried_and_success_is_reported(self):
        with HangDelay(2.5):
            expire_next(SERVER, UNIT, "hang")  # first read of the course page times out
            text, ok = self.scraper.register_courses([WANTED])
        self.assertTrue(ok, text)  # used to stay False after a failed first pass
        self.assertIn("MOCK1001", SERVER.registered)
        self.assertEqual(SERVER.processed_submits, 1)

    def test_session_that_ends_on_every_bid_gives_up(self):
        expire_next(SERVER, SUBMIT, "js", times=10)
        started = time.time()
        text, ok = self.scraper.register_courses([WANTED])
        self.assertFalse(ok)
        self.assertEqual(SERVER.processed_submits, 0)
        self.assertLessEqual(SERVER.hits[SUBMIT], 2)
        self.assertLess(time.time() - started, 30)

    def test_registered_list_gives_up_when_login_cannot_be_restored(self):
        expire_next(SERVER, REG, "js", times=10)
        with self.assertRaises(SessionExpiredException):
            self.scraper.get_registered_courses()
        self.assertLessEqual(SERVER.hits[LOGIN_POST], BeautifulSoupScraper.RELOGIN_LIMIT)

    def test_relogin_limit_stops_a_login_loop(self):
        now = time.monotonic()
        self.scraper._relogin_times.extend([now] * BeautifulSoupScraper.RELOGIN_LIMIT)
        self.scraper._is_logged_in = False
        SERVER.hits.clear()
        self.assertFalse(self.scraper._try_relogin())
        self.assertEqual(SERVER.hits["login.jsp"], 0, "no new login may start past the limit")


@unittest.skipUnless(browser_setup.chromium_status()["installed"], "Playwright Chromium is not installed")
class PlaywrightExpiryTests(RunnerCase):
    def setUp(self):
        super().setUp()
        self.scraper = PlaywrightScraper()
        self.scraper.set_headless_mode(True)
        self.scraper.login("2103370", "pw")
        SERVER.hits.clear()

    def tearDown(self):
        self.scraper.cleanup()

    def test_registered_list_logs_in_again_after_expired_page(self):
        expire_next(SERVER, REG, "js")
        data = self.scraper.get_registered_courses()
        self.assertTrue(data["info"])
        self.assertEqual(SERVER.hits[LOGIN_POST], 1)

    def test_registered_list_treats_a_login_page_as_ended_session(self):
        expire_next(SERVER, REG, "loginpage")
        data = self.scraper.get_registered_courses()
        self.assertTrue(data["info"])
        self.assertEqual(SERVER.hits[LOGIN_POST], 1)

    def test_home_page_data_logs_in_again(self):
        expire_next(SERVER, REG, "js")
        data, _cookies = self.scraper.get_home_page_data()
        self.assertTrue(data)
        self.assertEqual(SERVER.hits[LOGIN_POST], 1)

    def test_unit_slots_expiry_during_lookup_logs_in_again(self):
        expire_next(SERVER, UNIT, "js")  # the page opens, the lookup is answered "expired"
        self.assertEqual(len(self.scraper.get_unit_slots("MOCK1001")), 9)
        self.assertEqual(SERVER.hits[LOGIN_POST], 1)

    def test_bid_expiry_when_opening_the_page(self):
        expire_next(SERVER, REG, "js")
        message, ok = self.scraper.register_course(WANTED)
        self.assertTrue(ok, message)
        self.assertEqual(SERVER.processed_submits, 1)

    def test_bid_expiry_during_lookup(self):
        expire_next(SERVER, UNIT, "js")
        message, ok = self.scraper.register_course(WANTED)
        self.assertTrue(ok, message)
        self.assertEqual(SERVER.processed_submits, 1)

    def test_bid_answered_with_expired_page_is_not_reported_as_registered(self):
        expire_next(SERVER, SUBMIT, "js")
        message, ok = self.scraper.register_course(WANTED)
        self.assertTrue(ok, message)  # after logging in again and sending it once more
        self.assertEqual(SERVER.processed_submits, 1)
        self.assertEqual(SERVER.hits[SUBMIT], 2)
        self.assertIn("MOCK1001", SERVER.registered)

    def test_bid_processed_but_answer_lost_is_not_sent_again(self):
        expire_next(SERVER, SUBMIT, "apply-then-js")
        message, ok = self.scraper.register_course(WANTED)
        self.assertTrue(ok, message)
        self.assertEqual(SERVER.processed_submits, 1)
        self.assertEqual(SERVER.hits[SUBMIT], 1)

    def test_timed_out_bid_is_not_sent_again(self):
        with HangDelay(5):
            expire_next(SERVER, SUBMIT, "hang")
            text, ok = self.scraper.register_courses([WANTED])
        self.assertFalse(ok)
        self.assertEqual(SERVER.hits[SUBMIT], 1)
        self.assertEqual(SERVER.processed_submits, 0)

    def test_ended_session_that_cannot_be_restored_reports_expired(self):
        expire_next(SERVER, REG, "js", times=10)
        with self.assertRaises(SessionExpired) as caught:
            self.scraper.get_registered_courses()
        self.assertIn("expired", str(caught.exception).lower())

    def test_register_courses_stops_with_expired_message_when_login_cannot_be_restored(self):
        expire_next(SERVER, REG, "js", times=10)
        text, ok = self.scraper.register_courses([WANTED, course("MOCK1002", L=[1])])
        self.assertFalse(ok)
        self.assertIn("expired", text.lower())
        self.assertEqual(SERVER.processed_submits, 0)


if __name__ == "__main__":
    unittest.main()
