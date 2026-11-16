"""The mock portal's sessions behave like the real portal's.

Every rule below was observed on the real portal on 2026-11-16 with read-only probes
(see "Real-portal session behaviour" in docs/KNOWLEDGE.md). Things that were NOT measured
(idle timeout length, how the portal decides notSupportTab) are modelled in the simplest way
and marked as such.

    venv\\Scripts\\python -m unittest tests/test_mock_sessions.py
"""

import os
import time
import unittest

import requests

from tests.test_plan_runner import SERVER, RunnerCase  # noqa: F401 - sets UTAR_BASE_URL first
from tests.test_mock_server import log_in  # noqa: E402

from src.scrapers.playwright_scraper import PlaywrightScraper  # noqa: E402
from src.utils import browser_setup  # noqa: E402

BASE = os.environ["UTAR_BASE_URL"]
REG = f"{BASE}/registration/studentRegistrationSurvey.jsp"


def state(response):
    if "Log Out" in response.text:
        return "logged in"
    return "expired" if "sessionExpired" in response.text else "other"


class MockSessionTests(RunnerCase):
    def logged_in_client(self, user="2103370"):
        client = requests.Session()
        log_in(client, BASE, user)
        return client

    def test_pages_need_a_session_but_the_login_pages_do_not(self):
        self.assertEqual(requests.get(f"{BASE}/login.jsp").status_code, 200)
        self.assertEqual(requests.get(f"{BASE}/../Kaptcha.jpg").status_code, 200)
        answer = requests.get(REG)  # no cookie
        self.assertEqual(answer.status_code, 200)  # the real portal answers 200 with a short script
        self.assertEqual(state(answer), "expired")
        self.assertIn("window.parent.location.href", answer.text)
        self.assertLess(len(answer.text), 400)

    def test_login_sets_the_session_cookie_twice_with_both_paths(self):
        client = self.logged_in_client()
        paths = sorted(c.path for c in client.cookies if c.name == "JSESSIONID")
        self.assertEqual(paths, ["/portal", "/portal/courseRegStu"])
        self.assertEqual(state(client.get(REG)), "logged in")

    def test_the_session_is_only_the_cookie(self):
        client = self.logged_in_client()
        clone = requests.Session()
        for cookie in client.cookies:
            clone.cookies.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path)
        self.assertEqual(state(clone.get(REG, headers={"User-Agent": "another-browser/1.0"})), "logged in")
        self.assertEqual(state(clone.get(REG, headers={"Referer": ""})), "logged in")
        for cookie in list(clone.cookies):
            clone.cookies.clear(cookie.domain, cookie.path, cookie.name)
        self.assertEqual(state(clone.get(REG)), "expired")

    def test_either_session_cookie_alone_is_accepted(self):
        client = self.logged_in_client()
        for keep in ("/portal", "/portal/courseRegStu"):
            only = requests.Session()
            for cookie in client.cookies:
                if cookie.path == keep:
                    only.cookies.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path)
            self.assertEqual(state(only.get(REG)), "logged in", keep)

    def test_a_second_login_ends_the_first_session(self):
        first = self.logged_in_client()
        second = self.logged_in_client()  # same account, another window
        self.assertEqual(state(first.get(REG)), "expired")
        self.assertEqual(state(second.get(REG)), "logged in")

    def test_different_accounts_do_not_end_each_other(self):
        first = self.logged_in_client("2103370")
        second = self.logged_in_client("2103371")
        self.assertEqual(state(first.get(REG)), "logged in")
        self.assertEqual(state(second.get(REG)), "logged in")

    def test_single_session_can_be_switched_off(self):
        SERVER.single_session = False
        try:
            first = self.logged_in_client()
            second = self.logged_in_client()
            self.assertEqual(state(first.get(REG)), "logged in")
            self.assertEqual(state(second.get(REG)), "logged in")
        finally:
            SERVER.single_session = True

    def test_refused_login_gives_no_session(self):
        client = requests.Session()
        log_in(client, BASE, "invalid")
        self.assertEqual(state(client.get(REG)), "expired")

    def test_one_time_login_address_reused_gives_notsupporttab_and_ends_the_session(self):
        client = requests.Session()
        client.get(f"{BASE}/login.jsp")
        post = client.post(f"{BASE}/loginProSurvey.jsp", allow_redirects=False, data={
            "preKap": "x", "reqFregkey": "2103370", "reqPassword": "pw", "kaptchafield": "mock"})
        self.assertEqual(post.status_code, 302)
        passid_url = post.headers["Location"]
        self.assertIn("indexSurvey.jsp?passid=", passid_url)
        origin = BASE.split("/portal")[0]
        step1 = client.get(origin + passid_url, allow_redirects=False)  # the redirect chain right after login
        step2 = client.get(origin + step1.headers["Location"], allow_redirects=False)
        self.assertTrue(step2.headers["Location"].endswith("studentRegistrationSurvey.jsp"))
        self.assertEqual(state(client.get(REG)), "logged in")
        # pasted again, e.g. into a second tab
        again = client.get(origin + passid_url, allow_redirects=False)
        self.assertTrue(again.headers["Location"].endswith("login.jsp?message=notSupportTab"))
        self.assertEqual(state(client.get(REG)), "expired", "the first window's session ends too")
        page = requests.get(origin + again.headers["Location"])
        self.assertIn("not supported", page.text)

    def test_idle_session_ends_after_the_configured_time(self):
        # The real idle timeout was not measured; the mock default is "never".
        SERVER.session_timeout = 0.4
        try:
            client = self.logged_in_client()
            self.assertEqual(state(client.get(REG)), "logged in")
            time.sleep(0.7)
            self.assertEqual(state(client.get(REG)), "expired")
        finally:
            SERVER.session_timeout = None

    def test_requests_keep_an_idle_session_alive(self):
        SERVER.session_timeout = 1.0
        try:
            client = self.logged_in_client()
            for _ in range(3):
                time.sleep(0.5)
                self.assertEqual(state(client.get(REG)), "logged in")
        finally:
            SERVER.session_timeout = None

    def test_session_check_can_be_switched_off(self):
        SERVER.require_session = False
        try:
            self.assertEqual(state(requests.get(REG)), "logged in")
        finally:
            SERVER.require_session = True


@unittest.skipUnless(browser_setup.chromium_status()["installed"], "Playwright Chromium is not installed")
class MockBrowserSessionTests(RunnerCase):
    """What the owner saw in a browser: duplicate tab stays logged in, a window without the
    cookies does not, and the one-time login address in a second tab is refused."""

    def setUp(self):
        super().setUp()
        self.scraper = PlaywrightScraper()
        self.scraper.set_headless_mode(True)
        self.passid_urls = []
        page = self.scraper._owner.call(self.scraper._ensure_page)
        self.scraper._owner.call(lambda: page.on(
            "request", lambda r: self.passid_urls.append(r.url) if "passid=" in r.url else None))
        self.scraper.login("2103370", "pw")

    def tearDown(self):
        self.scraper.cleanup()

    def visit(self, make_page, url):
        def run():
            page = make_page()
            try:
                page.goto(url, wait_until="domcontentloaded")
                return page.url, page.content()
            finally:
                if page is not self.scraper.page:
                    page.close()
        return self.scraper._owner.call(run)

    def test_new_tab_in_the_same_context_stays_logged_in(self):
        url, html = self.visit(lambda: self.scraper.context.new_page(), REG)
        self.assertIn("Log Out", html)

    def test_new_window_without_the_cookies_gets_the_expired_page(self):
        def window():
            return self.scraper.browser.new_context().new_page()
        url, html = self.visit(window, REG)
        self.assertIn("sessionExpiredSurvey.jsp", url)

    def test_one_time_login_address_in_a_second_tab_is_refused_and_ends_the_first_window(self):
        self.assertTrue(self.passid_urls, "the login redirect chain went through a passid address")
        url, _html = self.visit(lambda: self.scraper.context.new_page(), self.passid_urls[0])
        self.assertIn("login.jsp?message=notSupportTab", url)
        url, html = self.visit(lambda: self.scraper.page, REG)
        self.assertIn("sessionExpiredSurvey.jsp", url)


if __name__ == "__main__":
    unittest.main()
