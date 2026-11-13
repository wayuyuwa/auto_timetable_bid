"""Plan runner tests against the in-process mock UTAR server.

Run on its own (config reads UTAR_BASE_URL at import time):
    venv\\Scripts\\python -m unittest tests/test_plan_runner.py
"""

import os
import tempfile
import threading
import time
import unittest

from src.mock_server import CLASH_MESSAGE, create_server, reset_state

SERVER = create_server()
threading.Thread(target=SERVER.serve_forever, daemon=True).start()
os.environ["UTAR_BASE_URL"] = f"http://127.0.0.1:{SERVER.server_port}{SERVER.base_path}"
# Playwright captures every mock page; keep them out of logs/debug during tests.
os.environ.setdefault("UTAR_DEBUG_DIR", tempfile.mkdtemp(prefix="utar_test_pages_"))
os.environ["UTAR_MOCK_CAPTCHA"] = "mock"

from src.models.course import Course  # noqa: E402
from src.scrapers.html_parser import (  # noqa: E402
    parse_registered_courses,
    parse_unit_slots,
    sessions_clash,
)
from src.services.plan_runner import PlanRunner, StatusBoard  # noqa: E402


def course(code, **slots):
    return Course(code=code, name=f"Course {code}", slots={key: list(value) for key, value in slots.items()})


def plan(name, *courses):
    return {"name": name, "courses": list(courses)}


class RunnerCase(unittest.TestCase):
    def setUp(self):
        reset_state(SERVER)
        SERVER.scenario = "success"

    def run_plans(self, plans, **options):
        runner = PlanRunner(plans, options=options, board=StatusBoard())
        runner.run("2103370", "pw")
        return runner.board.snapshot()

    def start_in_thread(self, plans, **options):
        runner = PlanRunner(plans, options=options, board=StatusBoard())
        thread = threading.Thread(target=runner.run, args=("2103370", "pw"), daemon=True)
        thread.start()
        return runner, thread

    def wait_phase(self, runner, phase, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if runner.board.snapshot()["phase"] == phase:
                return
            time.sleep(0.02)
        self.fail(f"phase {phase!r} not reached; status {runner.board.snapshot()}")


class VerificationTests(RunnerCase):
    def test_plan_a_success_is_confirmed_from_registered_list(self):
        status = self.run_plans([plan("Plan A", course("MOCK1001", L=[1], T=[2]), course("MOCK1002", L=[1]))])
        self.assertEqual(status["phase"], "complete")
        self.assertEqual({r["label"] for r in status["results"].values()}, {"Confirmed"})
        self.assertEqual(status["results"]["MOCK1001"]["registered"], "L1 T2")
        self.assertEqual({c["code"] for c in status["registered"]}, {"MOCK1001", "MOCK1002"})
        self.assertEqual(status["credit"], {"total": "6", "max": "20"})

    def test_registered_with_other_group_is_reported_not_rebid(self):
        SERVER.registered["MOCK1001"] = {"name": "X", "credit": 3.0, "classes": {"L": 1, "T": 3}}
        status = self.run_plans([plan("Plan A", course("MOCK1001", L=[1], T=[1]))])
        result = status["results"]["MOCK1001"]
        self.assertEqual(result["label"], "Different group")
        self.assertEqual(result["verified"], "different_group")
        self.assertEqual(status["total"], 0, "an already-registered course must not be bid again")
        self.assertEqual(status["phase"], "complete")

    def test_second_run_skips_registered_courses(self):
        plans = [plan("Plan A", course("MOCK1001", L=[1]), course("MOCK1002", L=[1]))]
        self.run_plans(plans)
        again = self.run_plans(plans)
        self.assertEqual(again["total"], 0)
        self.assertEqual(again["phase"], "complete")

    def test_real_clash_message_is_the_failure_reason(self):
        SERVER.slot_times[("MOCK1001", "L", 1)] = ("Mon", 9, 2)
        SERVER.slot_times[("MOCK1002", "L", 1)] = ("Mon", 10, 2)
        status = self.run_plans([plan("Plan A", course("MOCK1001", L=[1]), course("MOCK1002", L=[1]))])
        self.assertEqual(status["phase"], "error")
        self.assertEqual(status["results"]["MOCK1002"]["label"], "Not registered")
        self.assertIn(CLASH_MESSAGE, status["results"]["MOCK1002"]["message"])


class FallbackTests(RunnerCase):
    def test_full_slot_falls_back_to_plan_b(self):
        SERVER.full_slots.add(("MOCK1002", "T", 2))
        status = self.run_plans([
            plan("Plan A", course("MOCK1001", L=[1]), course("MOCK1002", L=[1], T=[2])),
            plan("Plan B", course("MOCK1001", L=[1]), course("MOCK1002", L=[1], T=[3])),
        ])
        self.assertEqual(status["phase"], "complete")
        result = status["results"]["MOCK1002"]
        self.assertEqual((result["plan"], result["label"], result["registered"]), ("Plan B", "Confirmed", "L1 T3"))
        self.assertTrue(any(line.startswith("Plan A:") for line in result["history"]))

    def test_fallback_skips_clashing_slot_and_uses_next_choice(self):
        SERVER.full_slots.add(("MOCK1002", "L", 1))
        SERVER.slot_times[("MOCK1001", "L", 1)] = ("Tue", 9, 2)
        SERVER.slot_times[("MOCK1002", "L", 2)] = ("Tue", 10, 2)   # clashes with MOCK1001 L1
        SERVER.slot_times[("MOCK1002", "L", 3)] = ("Wed", 10, 2)   # free
        status = self.run_plans([
            plan("Plan A", course("MOCK1001", L=[1]), course("MOCK1002", L=[1])),
            plan("Plan B", course("MOCK1002", L=[2, 3])),
        ])
        self.assertEqual(status["phase"], "complete")
        self.assertEqual(status["results"]["MOCK1002"]["registered"], "L3")

    def test_fallback_with_only_clashing_choice_is_skipped(self):
        SERVER.full_slots.add(("MOCK1002", "L", 1))
        SERVER.slot_times[("MOCK1001", "L", 1)] = ("Tue", 9, 2)
        SERVER.slot_times[("MOCK1002", "L", 2)] = ("Tue", 10, 2)
        status = self.run_plans([
            plan("Plan A", course("MOCK1001", L=[1]), course("MOCK1002", L=[1])),
            plan("Plan B", course("MOCK1002", L=[2])),
        ])
        self.assertEqual(status["phase"], "error")
        result = status["results"]["MOCK1002"]
        self.assertEqual(result["label"], "Skipped")
        self.assertIn("clashes with MOCK1001 L1", result["message"])
        self.assertNotIn("MOCK1002", SERVER.registered)

    def test_plan_b_not_used_when_plan_a_completes(self):
        status = self.run_plans([
            plan("Plan A", course("MOCK1001", L=[1])),
            plan("Plan B", course("MOCK1003", L=[1])),
        ])
        self.assertEqual(status["phase"], "complete")
        self.assertNotIn("MOCK1003", SERVER.registered)

    def test_ask_mode_waits_for_choice_and_respects_it(self):
        SERVER.full_slots.add(("MOCK1002", "L", 1))
        plans = [
            plan("Plan A", course("MOCK1001", L=[1]), course("MOCK1002", L=[1])),
            plan("Plan B", course("MOCK1002", L=[2]), course("MOCK1003", L=[1])),
        ]
        runner, thread = self.start_in_thread(plans, fallback_mode="ask")
        self.wait_phase(runner, "awaiting_choice")
        proposal = runner.board.snapshot()["proposal"]
        self.assertEqual(proposal["plan"], "Plan B")
        self.assertEqual({item["code"]: item["action"] for item in proposal["items"]},
                         {"MOCK1002": "add", "MOCK1003": "add"})
        runner.submit_choice(["MOCK1002"])
        thread.join(timeout=15)
        status = runner.board.snapshot()
        self.assertEqual(status["phase"], "complete")
        self.assertIn("MOCK1002", SERVER.registered)
        self.assertNotIn("MOCK1003", SERVER.registered)
        self.assertEqual(status["results"]["MOCK1003"]["label"], "Skipped")

    def test_cancel_while_waiting_for_choice(self):
        SERVER.full_slots.add(("MOCK1002", "L", 1))
        plans = [plan("Plan A", course("MOCK1002", L=[1])), plan("Plan B", course("MOCK1002", L=[2]))]
        runner, thread = self.start_in_thread(plans, fallback_mode="ask")
        self.wait_phase(runner, "awaiting_choice")
        runner.cancel()
        thread.join(timeout=15)
        self.assertEqual(runner.board.snapshot()["phase"], "cancelled")
        self.assertNotIn("MOCK1002", SERVER.registered)

    def test_switch_candidate_is_reported_not_changed(self):
        SERVER.full_slots.add(("MOCK1002", "L", 1))
        plans = [
            plan("Plan A", course("MOCK1001", L=[1], T=[1]), course("MOCK1002", L=[1])),
            plan("Plan B", course("MOCK1001", L=[1], T=[2]), course("MOCK1002", L=[2])),
        ]
        runner, thread = self.start_in_thread(plans, fallback_mode="ask")
        self.wait_phase(runner, "awaiting_choice")
        actions = {item["code"]: item["action"] for item in runner.board.snapshot()["proposal"]["items"]}
        self.assertEqual(actions, {"MOCK1001": "switch", "MOCK1002": "add"})
        runner.submit_choice(["MOCK1002"])
        thread.join(timeout=15)
        self.assertEqual(SERVER.registered["MOCK1001"]["classes"], {"L": 1, "T": 1})


class RetryAndScheduleTests(RunnerCase):
    def test_auto_retry_registers_when_a_slot_frees_up(self):
        SERVER.full_slots.add(("MOCK1001", "L", 1))
        runner, thread = self.start_in_thread([plan("Plan A", course("MOCK1001", L=[1]))],
                                              auto_retry_seconds=1, max_attempts=5)
        self.wait_phase(runner, "waiting_retry")
        SERVER.full_slots.clear()
        thread.join(timeout=20)
        status = runner.board.snapshot()
        self.assertEqual(status["phase"], "complete")
        self.assertGreaterEqual(status["attempt"], 2)
        self.assertEqual(status["results"]["MOCK1001"]["label"], "Confirmed")

    def test_auto_retry_stops_after_max_attempts(self):
        SERVER.full_slots.add(("MOCK1001", "L", 1))
        status = self.run_plans([plan("Plan A", course("MOCK1001", L=[1]))],
                                auto_retry_seconds=1, max_attempts=2)
        self.assertEqual(status["phase"], "error")
        self.assertEqual(status["attempt"], 2)

    def test_scheduled_start_waits_for_the_time(self):
        start_at = time.time() + 2.5
        runner = PlanRunner([plan("Plan A", course("MOCK1001", L=[1]))],
                            options={"start_at": start_at}, board=StatusBoard())
        runner.prelogin_seconds = 1
        thread = threading.Thread(target=runner.run, args=("2103370", "pw"), daemon=True)
        thread.start()
        self.wait_phase(runner, "scheduled")
        time.sleep(1.0)
        self.assertNotIn("MOCK1001", SERVER.registered, "must not bid before the scheduled time")
        thread.join(timeout=15)
        self.assertGreaterEqual(time.time(), start_at)
        self.assertEqual(runner.board.snapshot()["phase"], "complete")

    def test_cancel_while_scheduled(self):
        runner, thread = self.start_in_thread([plan("Plan A", course("MOCK1001", L=[1]))],
                                              start_at=time.time() + 600)
        self.wait_phase(runner, "scheduled")
        runner.cancel()
        thread.join(timeout=10)
        self.assertEqual(runner.board.snapshot()["phase"], "cancelled")


class PreflightTests(RunnerCase):
    def preflight(self, plans):
        runner = PlanRunner(plans, board=StatusBoard())
        runner.preflight("2103370", "pw")
        return runner.board.snapshot()

    def test_clean_plan_passes(self):
        status = self.preflight([plan("Plan A", course("MOCK1001", L=[1], T=[2]))])
        self.assertEqual(status["phase"], "preflight_done")
        self.assertEqual(status["preflight"]["problems"], 0)
        self.assertEqual(SERVER.registered, {}, "pre-flight must not register anything")

    def test_reports_unknown_code_missing_group_full_and_clash(self):
        SERVER.unknown_units.add("NOPE0000")
        SERVER.full_slots.add(("MOCK1002", "T", 1))
        SERVER.slot_times[("MOCK1001", "L", 1)] = ("Mon", 9, 2)
        SERVER.slot_times[("MOCK1003", "L", 1)] = ("Mon", 10, 2)
        status = self.preflight([plan(
            "Plan A",
            course("NOPE0000", L=[1]),
            course("MOCK1001", L=[1], T=[9]),
            course("MOCK1002", T=[1]),
            course("MOCK1003", L=[1]),
        )])
        texts = " | ".join(check["text"] for check in status["preflight"]["checks"])
        self.assertIn("NOPE0000 was not found", texts)
        self.assertIn("MOCK1001 has no group T9", texts)
        self.assertIn("MOCK1002 T choices are all full", texts)
        self.assertIn("MOCK1001 L1 clashes with MOCK1003 L1", texts)
        self.assertEqual(status["preflight"]["problems"], 2)

    def test_bad_credentials_fail_preflight(self):
        runner = PlanRunner([plan("Plan A", course("MOCK1001", L=[1]))], board=StatusBoard())
        runner.preflight("invalid", "pw")
        status = runner.board.snapshot()
        self.assertEqual(status["phase"], "error")
        self.assertIn("credentials", status["message"])


class ParserTests(unittest.TestCase):
    """Parsers against HTML in the real portal's layout (rowspan second meeting)."""

    REGISTERED = """
    <table><tr align="center"><td>No</td><td>Type</td><td>Group</td></tr>
    <tr valign="middle"><td class="normalTbl-sub3header" colspan="9">UCCD2044 - OBJECT-ORIENTED PROGRAMMING PRACTICES [FICT]
      | Credit Hour : 4.0 | <span class="red"><b>Register - Pending for Billing</b></span></td>
      <td colspan="2">Delete :<input name="reqRegId" type="checkbox" value="7077542004"></td></tr>
    <tr align="center"><td rowspan="2">1</td><td rowspan="2">L</td><td rowspan="2">1</td><td rowspan="2">Physical</td>
      <td rowspan="2">357</td><td>Tue</td><td>09:00 AM - 10:00 AM</td><td>1.0</td><td>1-14</td><td>LDK3</td>
      <td rowspan="2"><img onclick="changeClass('7899241004')"></td></tr>
    <tr align="center"><td>Wed</td><td>12:00 PM - 02:00 PM</td><td>2.0</td><td>1-14</td><td>LDK3</td></tr>
    <tr align="center"><td>2</td><td>P</td><td>11</td><td>Physical</td><td>20</td><td>Thu</td>
      <td>10:00 AM - 12:00 PM</td><td>2.0</td><td>1-14</td><td>N108(Lab)</td>
      <td><img onclick="changeClass('7899242004')"></td></tr></table>"""

    UNIT = """
    <table><tr align="center"><td>No</td><td>Type</td><td>Group</td><td>Mode</td><td>Class Size</td><td>Week</td>
      <td>Day</td><td>Time</td><td>Hour</td><td>Room</td><td>Reg.</td><td>Avail</td><td>Remark</td><td></td></tr>
    <tr align="center"><td>1</td><td>L</td><td>1</td><td>Physical</td><td>259</td><td>1-14</td><td>Mon</td>
      <td>04:00 PM - 06:00 PM</td><td>2.0</td><td>LDK5</td><td>96</td><td>39</td><td></td>
      <td><input type="checkbox" name="reqMid" value="624953"></td></tr>
    <tr align="center"><td>2</td><td>T</td><td>1</td><td>Physical</td><td>33</td><td>1-14</td><td>Thu</td>
      <td>12:00 PM - 01:00 PM</td><td>1.0</td><td>N106</td><td>32</td><td>0</td><td></td><td></td></tr></table>"""

    def test_registered_courses(self):
        courses = parse_registered_courses(self.REGISTERED)
        self.assertEqual(len(courses), 1)
        parsed = courses[0]
        self.assertEqual((parsed["code"], parsed["credit_hours"], parsed["status"]),
                         ("UCCD2044", 4.0, "Register - Pending for Billing"))
        self.assertEqual(parsed["name"], "OBJECT-ORIENTED PROGRAMMING PRACTICES")
        lecture, practical = parsed["classes"]
        self.assertEqual((lecture["type"], lecture["group"], lecture["rgsid"]), ("L", 1, "7899241004"))
        self.assertEqual([s["day"] for s in lecture["sessions"]], ["Tue", "Wed"])
        self.assertEqual((lecture["sessions"][1]["start"], lecture["sessions"][1]["end"]), (720, 840))
        self.assertEqual((practical["type"], practical["group"]), ("P", 11))

    def test_unit_slots_and_clash(self):
        lecture, tutorial = parse_unit_slots(self.UNIT)
        self.assertTrue(lecture["selectable"])
        self.assertEqual((lecture["mid"], lecture["available"], lecture["registered"]), ("624953", 39, 96))
        self.assertFalse(tutorial["selectable"])
        self.assertEqual(tutorial["available"], 0)
        self.assertEqual(lecture["sessions"][0]["weeks"], "1-14")
        self.assertFalse(sessions_clash(lecture["sessions"], tutorial["sessions"]))
        self.assertTrue(sessions_clash(lecture["sessions"], lecture["sessions"]))



class RegistrationClosedTests(RunnerCase):
    """Portal accepts the login, then answers 'session expired' to everything
    (what the real portal does when registration is closed). This used to
    deadlock in the scraper's relogin, freezing pre-flight and Stop."""

    def setUp(self):
        super().setUp()
        SERVER.scenario = "closed"

    def test_run_ends_with_login_error_instead_of_hanging(self):
        started = time.time()
        runner, thread = self.start_in_thread([plan("Plan A", course("MOCK1001", L=[1]))])
        thread.join(timeout=60)
        self.assertFalse(thread.is_alive(), "run hung when the portal kept expiring the session")
        status = runner.board.snapshot()
        self.assertEqual(status["phase"], "error")
        self.assertIn("Login", status["message"])
        self.assertIn("registration may be closed", status["message"])
        self.assertLess(time.time() - started, 45)

    def test_preflight_ends_instead_of_hanging(self):
        runner = PlanRunner([plan("Plan A", course("MOCK1001", L=[1]))], board=StatusBoard())
        thread = threading.Thread(target=runner.preflight, args=("2103370", "pw"), daemon=True)
        thread.start()
        thread.join(timeout=60)
        self.assertFalse(thread.is_alive(), "pre-flight hung")
        self.assertEqual(runner.board.snapshot()["phase"], "error")

    def test_stop_works_while_login_keeps_failing(self):
        runner, thread = self.start_in_thread([plan("Plan A", course("MOCK1001", L=[1]))])
        time.sleep(0.3)
        still_running = runner.board.snapshot()["running"]
        stopped_at = time.time()
        runner.cancel()
        thread.join(timeout=30)
        self.assertFalse(thread.is_alive(), "Stop did not end the run")
        # Login now gives up after two "closed" answers, so a run can end on
        # its own before Stop; if it was still running, it must end cancelled.
        if still_running:
            self.assertEqual(runner.board.snapshot()["phase"], "cancelled")
        self.assertFalse(runner.board.snapshot()["stopping"])
        self.assertLess(time.time() - stopped_at, 15)


class StopSafetyNetTests(RunnerCase):
    def test_stop_releases_the_app_even_if_the_worker_never_returns(self):
        import tempfile
        from unittest import mock

        from src.storage.database import Database
        from src.web_backend import DesktopApi

        api = DesktopApi(database=Database(os.path.join(tempfile.mkdtemp(), "app.db")))
        api.STOP_GRACE_SECONDS = 1
        api.save_courses([{"code": "MOCK1001", "name": "X", "slots": {"L": [1]}}])
        release = threading.Event()
        with mock.patch.object(PlanRunner, "run", lambda self, student_id, password: release.wait(60)):
            api.start("2103370", "pw")
            self.assertTrue(api.get_status()["running"])
            api.cancel()
            deadline = time.time() + 10
            while api.get_status()["running"] and time.time() < deadline:
                time.sleep(0.05)
            status = api.get_status()
            self.assertFalse(status["running"], "Stop left the app stuck")
            self.assertEqual(status["phase"], "cancelled")
        # A new run can start although the old worker is still blocked.
        SERVER.scenario = "success"
        api.start("2103370", "pw")
        deadline = time.time() + 20
        while api.get_status()["running"] and time.time() < deadline:
            time.sleep(0.05)
        self.assertEqual(api.get_status()["phase"], "complete")
        release.set()
        api.cleanup()

if __name__ == "__main__":
    unittest.main()
