import threading
import unittest
from http.server import ThreadingHTTPServer

import requests

from src.mock_server import MockHandler


def log_in(session, base_url, student_id="2103370"):
    """Log in the way a browser does: login page (session cookie), then the form."""
    session.get(f"{base_url}/login.jsp")
    return session.post(f"{base_url}/loginProSurvey.jsp", data={
        "preKap": "mock-prekap", "reqFregkey": student_id, "reqPassword": "pw", "kaptchafield": "mock",
    })


class MockServerTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
        self.server.daemon_threads = True
        self.server.base_path = "/portal/courseRegStu"
        self.server.scenario = "success"
        self.server.delay = 0
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}{self.server.base_path}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_login_and_unit_lookup_pages_match_scraper_contract(self):
        session = requests.Session()
        login = session.get(f"{self.base_url}/login.jsp")
        self.assertIn('form name="frmParam"', login.text)
        landed = log_in(session, self.base_url)
        self.assertIn("Log Out", landed.text)

        unit = session.post(
            f"{self.base_url}/registration/registerUnitSurvey.jsp",
            data={"reqUnit": "MOCK1001"},
        )
        self.assertIn('name="reqFregkey"', unit.text)
        self.assertIn('name="reqMid"', unit.text)

    def test_register_fail_scenario_returns_failure_message(self):
        self.server.scenario = "register-fail"
        session = requests.Session()
        log_in(session, self.base_url)
        response = session.post(f"{self.base_url}/registration/registerUnitProSurvey.jsp")
        self.assertIn("Mock registration failed", response.text)


if __name__ == "__main__":
    unittest.main()
