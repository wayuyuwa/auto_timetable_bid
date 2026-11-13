"""Tests for the issues.txt fixes (login retries, scheduled start, pre-flight
without a plan, stopping status, credentials, import modes, Playwright browser
path, diagnostics, real-server test mode, child-process cleanup).

Uses the in-process mock server from test_plan_runner (imported first so the
portal URL points at the mock before src.utils.config is loaded):
    venv\\Scripts\\python -m unittest tests/test_issue_fixes.py
"""

import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from tests.test_plan_runner import SERVER, RunnerCase, course, plan  # noqa: F401 - sets UTAR_BASE_URL

from src.services.plan_runner import PlanRunner, RunError, StatusBoard  # noqa: E402
from src.storage.database import Database  # noqa: E402
from src.utils import browser_setup, diagnostics, secret_store  # noqa: E402
from src.web_backend import DesktopApi  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def new_api():
    return DesktopApi(database=Database(os.path.join(tempfile.mkdtemp(), "app.db")))


class LoginTests(RunnerCase):
    def test_login_progress_and_invalid_credentials_kind(self):
        runner = PlanRunner([plan("Plan A", course("MOCK1001", L=[1]))], board=StatusBoard())
        runner.run("invalid", "pw")
        status = runner.board.snapshot()
        self.assertEqual(status["phase"], "error")
        self.assertEqual((status["error_source"], status["error_kind"]), ("login", "invalid_credentials"))
        self.assertEqual(status["login"]["attempt"], 1)
        self.assertEqual(status["login"]["max"], 5)

    def test_closed_portal_gives_up_fast_with_reasons(self):
        SERVER.scenario = "closed"
        started = time.time()
        runner = PlanRunner([plan("Plan A", course("MOCK1001", L=[1]))], board=StatusBoard())
        runner.run("2103370", "pw")
        status = runner.board.snapshot()
        self.assertEqual(status["error_kind"], "portal_closed")
        self.assertEqual(len(status["login"]["reasons"]), 2)
        self.assertLess(time.time() - started, 15)
        self.assertEqual(SERVER.registered, {})

    def test_stopping_flag_while_running(self):
        SERVER.scenario = "timeout"
        runner, thread = self.start_in_thread([plan("Plan A", course("MOCK1001", L=[1]))])
        self.wait_phase(runner, "bidding", timeout=20)
        runner.cancel()
        snap = runner.board.snapshot()
        self.assertTrue(snap["running"] and snap["stopping"])
        self.assertIn("Stopping", snap["message"])
        thread.join(timeout=30)
        final = runner.board.snapshot()
        self.assertEqual(final["phase"], "cancelled")
        self.assertFalse(final["stopping"])
        self.assertIsNotNone(final["ended_at"])

    def test_activity_log_records_messages(self):
        runner = PlanRunner([plan("Plan A", course("MOCK1001", L=[1]))], board=StatusBoard())
        runner.run("2103370", "pw")
        texts = [entry["text"] for entry in runner.board.snapshot()["log"]]
        self.assertTrue(any("Logging in" in text for text in texts), texts)
        self.assertIn("All courses registered successfully.", texts)


class AccountRefusedTests(RunnerCase):
    """Real portal (logs 2026-11-13): an accepted password can still be refused,
    with a redirect to login.jsp?message=notActive / notConsultAdviser."""

    def run_method(self, method, scenario):
        SERVER.scenario = scenario
        started = time.time()
        runner = PlanRunner([plan("Plan A", course("MOCK1001", L=[1]))], method=method, headless=True,
                            board=StatusBoard())
        runner.run("2103370", "pw")
        return runner.board.snapshot(), time.time() - started

    def check_refused(self, method, scenario, text):
        status, elapsed = self.run_method(method, scenario)
        self.assertEqual((status["phase"], status["error_source"], status["error_kind"]),
                         ("error", "login", "account_not_allowed"), status["message"])
        self.assertIn(text, status["message"])
        self.assertEqual(status["login"]["attempt"], 1, "a refused account must not be retried")
        self.assertNotIn("registration may be closed", status["message"])
        self.assertLess(elapsed, 45)  # generous: a busy PC slows the browser; attempt==1 is the real check
        self.assertEqual(SERVER.registered, {})

    def test_bs_not_active(self):
        self.check_refused("BeautifulSoup", "not-active", "study status is not allowed")

    def test_bs_not_consult_adviser(self):
        self.check_refused("BeautifulSoup", "not-adviser", "notConsultAdviser")

    def test_playwright_not_active(self):
        self.check_refused("Playwright", "not-active", "study status is not allowed")

    def test_playwright_not_consult_adviser(self):
        self.check_refused("Playwright", "not-adviser", "notConsultAdviser")

    def test_scheduled_start_does_not_retry_a_refused_account(self):
        SERVER.scenario = "not-active"
        runner = PlanRunner([plan("Plan A", course("MOCK1001", L=[1]))],
                            options={"start_at": time.time() + 30}, board=StatusBoard())
        started = time.time()
        runner.run("2103370", "pw")
        self.assertEqual(runner.board.snapshot()["error_kind"], "account_not_allowed")
        self.assertLess(time.time() - started, 15)


class ScheduleTests(RunnerCase):
    def test_scheduled_start_retries_login_while_closed_then_bids(self):
        SERVER.scenario = "closed"
        runner = PlanRunner([plan("Plan A", course("MOCK1001", L=[1]))],
                            options={"start_at": time.time() + 4}, board=StatusBoard())
        runner.login_retry_seconds = 1
        thread = threading.Thread(target=runner.run, args=("2103370", "pw"), daemon=True)
        thread.start()
        deadline = time.time() + 20
        while "Trying again" not in runner.board.snapshot()["message"] and time.time() < deadline:
            time.sleep(0.05)
        self.assertIn("nothing has been bid", runner.board.snapshot()["message"])
        self.assertEqual(SERVER.registered, {})
        SERVER.scenario = "success"  # registration opens
        thread.join(timeout=40)
        status = runner.board.snapshot()
        self.assertEqual(status["phase"], "complete", status["message"])
        self.assertIn("MOCK1001", SERVER.registered)

    def test_scheduled_start_gives_up_after_grace(self):
        SERVER.scenario = "closed"
        runner = PlanRunner([plan("Plan A", course("MOCK1001", L=[1]))],
                            options={"start_at": time.time() + 1}, board=StatusBoard())
        runner.login_retry_seconds, runner.login_grace_seconds = 1, 2
        runner.run("2103370", "pw")
        status = runner.board.snapshot()
        self.assertEqual((status["phase"], status["error_kind"]), ("error", "portal_closed"))
        self.assertEqual(SERVER.registered, {})

    def test_session_expired_at_start_relogs_in_once(self):
        runner = PlanRunner([plan("Plan A", course("MOCK1001", L=[1]))], board=StatusBoard())
        runner._login("2103370", "pw")
        real = runner._scraper.get_registered_courses
        calls = []

        def expire_once():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("Session expired")
            return real()

        runner._scraper.get_registered_courses = expire_once
        snapshot = runner._refresh_registered()
        self.assertEqual(snapshot, {})
        self.assertEqual(len(calls), 2)
        runner._cleanup()


class PreflightTests(RunnerCase):
    def test_preflight_without_any_plan_checks_login_only(self):
        runner = PlanRunner([], board=StatusBoard())
        runner.preflight("2103370", "pw")
        status = runner.board.snapshot()
        self.assertEqual(status["phase"], "preflight_done", status["message"])
        self.assertEqual([s["state"] for s in status["steps"]], ["ok", "ok", "skipped", "skipped"])
        self.assertIn("No course plan yet", status["steps"][2]["detail"])

    def test_failed_login_marks_later_steps_skipped(self):
        runner = PlanRunner([plan("Plan A", course("MOCK1001", L=[1]))], board=StatusBoard())
        runner.preflight("invalid", "pw")
        steps = runner.board.snapshot()["steps"]
        self.assertEqual([s["state"] for s in steps], ["error", "skipped", "skipped", "skipped"])


class DesktopApiTests(unittest.TestCase):
    @unittest.skipUnless(secret_store.available(), "DPAPI is Windows-only")
    def test_credentials_are_encrypted_and_restored(self):
        api = new_api()
        api.save_credentials("2103370", "Pässword!", True)
        rows = dict(api.settings_repo.database._connect().execute("SELECT key, value FROM app_settings").fetchall())
        self.assertNotIn("Pässword!", str(rows))
        self.assertTrue(rows["password_protected"].startswith("dpapi:"))
        again = DesktopApi(database=api.settings_repo.database).get_saved_credentials()
        self.assertEqual((again["student_id"], again["password"]), ("2103370", "Pässword!"))
        api.save_credentials("2103370", "x", False)
        self.assertEqual(api.get_saved_credentials()["password"], "")

    def test_import_modes(self):
        api = new_api()
        api.save_courses([{"code": "A1", "name": "A", "slots": {"L": [1]}}])
        content = '[{"code": "B1", "name": "B", "slots": {"L": [2]}}]'
        plans = api.import_courses("b.json", content, 0, "new", "Imported")
        self.assertEqual([p["name"] for p in plans], ["Plan A", "Imported"])
        self.assertEqual(plans[0]["courses"][0]["code"], "A1")
        plans = api.import_courses("b.json", content, 0, "replace")
        self.assertEqual(plans[0]["courses"][0]["code"], "B1")
        for name, text in (("x.pdf", "x"), ("x.txt", " "), ("x.json", "{")):
            with self.assertRaises(ValueError):
                api.preview_import(name, text)

    def test_preflight_allowed_without_courses(self):
        SERVER.scenario = "success"  # other test classes may leave a failing scenario behind
        api = new_api()
        api.save_plans([{"name": "Plan A", "courses": []}])
        api.preflight("2103370", "pw")
        deadline = time.time() + 30
        while api.get_status()["running"] and time.time() < deadline:
            time.sleep(0.1)
        status = api.get_status()
        self.assertEqual(status["phase"], "preflight_done", status["message"])
        self.assertEqual(status["kind"], "preflight")
        self.assertTrue(status["started_at"] and status["ended_at"] >= status["started_at"])


class BrowserPathTests(unittest.TestCase):
    def test_frozen_app_uses_per_user_browser_folder(self):
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.dict(os.environ, {"PLAYWRIGHT_BROWSERS_PATH": "0"}):
            path = browser_setup.configure_browsers_path()
            self.assertEqual(path, str(browser_setup.default_browsers_path()))

    def test_explicit_path_is_kept(self):
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.dict(os.environ, {"PLAYWRIGHT_BROWSERS_PATH": r"D:\browsers"}):
            self.assertEqual(browser_setup.configure_browsers_path(), r"D:\browsers")

    def test_missing_browser_gives_actionable_error(self):
        from src.scrapers.errors import BrowserMissing
        from src.scrapers.playwright_scraper import PlaywrightScraper

        with mock.patch.dict(os.environ, {"PLAYWRIGHT_BROWSERS_PATH": tempfile.mkdtemp()}):
            self.assertFalse(browser_setup.chromium_status()["installed"])
            scraper = PlaywrightScraper()
            scraper.set_headless_mode(True)
            try:
                with self.assertRaises(BrowserMissing) as caught:
                    scraper.login("2103370", "pw")
                self.assertIn("Install browser", str(caught.exception))
            finally:
                scraper.cleanup()


class DiagnosticsTests(unittest.TestCase):
    def test_sanitizers_mask_secrets(self):
        self.assertEqual(diagnostics.sanitize_form({"reqPassword": "x", "reqUnit": "1"}),
                         {"reqPassword": "***", "reqUnit": "1"})
        self.assertEqual(diagnostics.sanitize_headers({"Cookie": "JSESSIONID=abc", "Accept": "a"}),
                         {"Cookie": "***", "Accept": "a"})
        text = diagnostics.sanitize_text("IC 990101-14-5678 url;jsessionid=ABC123 <input name='reqPassword' value='pw'>"
                                         " indexSurvey.jsp?passid=TOKEN%3D <input name='reqFregkey' value='2103370'>")
        self.assertNotIn("990101-14-5678", text)
        self.assertNotIn("ABC123", text)
        self.assertNotIn("TOKEN", text)
        self.assertNotIn("2103370", text)
        self.assertEqual(diagnostics.sanitize_form({"reqFregkey": "2103370"}), {"reqFregkey": "***"})
        self.assertNotIn("value='pw'", text)


class DebugPageTests(RunnerCase):
    def test_playwright_saves_sanitised_html_and_screenshot(self):
        from src.scrapers.playwright_scraper import PlaywrightScraper

        out = tempfile.mkdtemp()
        SERVER.scenario = "not-active"
        with mock.patch.object(diagnostics, "DEBUG_DUMPS", True), mock.patch.object(diagnostics, "DEBUG_DIR", out):
            scraper = PlaywrightScraper()
            scraper.set_headless_mode(True)
            try:
                with self.assertRaises(Exception):
                    scraper.login("2103370", "Secret-pw-77")
            finally:
                scraper.cleanup()
        files = os.listdir(out)
        html = [name for name in files if name.endswith(".html")]
        self.assertTrue(html and any(name.endswith(".png") for name in files), files)
        content = open(os.path.join(out, html[0]), encoding="utf-8").read()
        self.assertIn("study status is not allowed", content)
        self.assertNotIn("Secret-pw-77", content)


class RealServerTestModeTests(RunnerCase):
    def run_cli(self, *args, env=None):
        environment = {**os.environ, "UTAR_PASSWORD": "pw", **(env or {})}
        return subprocess.run([sys.executable, "main.py", "--test-real-server", *args], cwd=ROOT, env=environment,
                              capture_output=True, text=True, timeout=120)

    def test_passes_against_mock_and_never_registers(self):
        result = self.run_cli("--student-id", "2103370")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("RESULT: PASSED", result.stdout)
        self.assertIn("student info", result.stdout)
        self.assertEqual(SERVER.registered, {})

    def test_fails_with_exit_code_on_bad_login(self):
        result = self.run_cli("--student-id", "invalid")
        self.assertEqual(result.returncode, 1)
        self.assertIn("[FAIL] login", result.stdout)

    def test_usage_error_without_password(self):
        result = self.run_cli("--student-id", "1", env={"UTAR_PASSWORD": ""})
        self.assertEqual(result.returncode, 2)

    def test_submission_methods_are_disabled(self):
        from src.real_server_test import _forbid_submissions
        from src.scrapers.beautifulsoup_scraper import BeautifulSoupScraper

        scraper = BeautifulSoupScraper()
        _forbid_submissions(scraper)
        with self.assertRaises(RuntimeError):
            scraper.register_courses([course("MOCK1001", L=[1])])
        with self.assertRaises(RuntimeError):
            scraper._submit_bidding("MOCK1001", "1", "x", [], {})


@unittest.skipUnless(sys.platform == "win32", "job objects are Windows-only")
class ProcessGuardTests(unittest.TestCase):
    def test_children_die_when_the_app_is_killed(self):
        script = (
            "import subprocess, sys, time\n"
            "from src.utils.process_guard import kill_children_on_exit\n"
            "assert kill_children_on_exit()\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            "print(child.pid, flush=True)\n"
            "time.sleep(60)\n"
        )
        parent = subprocess.Popen([sys.executable, "-c", script], cwd=ROOT, stdout=subprocess.PIPE, text=True)
        child_pid = int(parent.stdout.readline())
        import psutil

        self.assertTrue(psutil.pid_exists(child_pid))
        parent.kill()  # hard kill, like a crash: no cleanup code runs
        parent.wait(10)
        deadline = time.time() + 10
        while psutil.pid_exists(child_pid) and time.time() < deadline:
            time.sleep(0.1)
        self.assertFalse(psutil.pid_exists(child_pid), "child survived the app")


if __name__ == "__main__":
    unittest.main()
