"""Real-server integration test: log in and read student info, then stop.

    python main.py --test-real-server [--method bs|playwright] [--student-id ID] [--saved]
    UnitRegTimetable.exe --test-real-server ...

Password: env UTAR_PASSWORD, or --saved (the password saved in the app,
decrypted for this Windows user), or --prompt (hidden prompt; needs a console).

Stages: config -> credentials -> login -> student info -> registered courses.
It NEVER calls a registration/bidding endpoint: the scraper's submit methods
are replaced with functions that raise before anything is sent.

Exit code 0 = all stages passed, 1 = a stage failed, 2 = usage problem.
The report is printed and also written to logs/real-server-test.txt
(the windowed exe has no console).
"""

import argparse
import os
import sys
import time

from .utils.config import BASE_URL, LOG_DIR

REPORT_FILE = os.path.join(LOG_DIR, "real-server-test.txt")


class Report:
    def __init__(self):
        self.lines = []
        self.failed = False

    def out(self, text=""):
        self.lines.append(text)
        if sys.stdout:
            try:
                print(text, flush=True)
            except (OSError, ValueError):
                pass

    def stage(self, name, func):
        started = time.time()
        self.out(f"[....] {name}")
        try:
            detail = func()
        except Exception as error:  # noqa: BLE001
            self.failed = True
            self.out(f"[FAIL] {name} ({time.time() - started:.1f}s): {error}")
            return None
        self.out(f"[ OK ] {name} ({time.time() - started:.1f}s){': ' + str(detail) if detail else ''}")
        return detail if detail is not None else True

    def save(self):
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(REPORT_FILE, "w", encoding="utf-8") as file:
            file.write("\n".join(self.lines) + "\n")


def _forbid_submissions(scraper):
    def refuse(*_args, **_kwargs):
        raise RuntimeError("Submitting a registration is disabled in --test-real-server mode")

    for name in ("register_courses", "register_course", "_submit_bidding"):
        if hasattr(scraper, name):
            setattr(scraper, name, refuse)


def _password(args):
    if os.getenv("UTAR_PASSWORD"):
        return os.environ["UTAR_PASSWORD"], "env UTAR_PASSWORD"
    if args.saved:
        from .storage.database import Database
        from .web_backend import DesktopApi

        saved = DesktopApi(database=Database()).get_saved_credentials()
        if not args.student_id:
            args.student_id = saved["student_id"]
        if saved["password"]:
            return saved["password"], "saved in the app (decrypted)"
        raise RuntimeError("No saved password. Save it in the app first or set UTAR_PASSWORD.")
    if args.prompt:
        import getpass

        return getpass.getpass("UTAR password: "), "typed"
    raise RuntimeError("No password: set UTAR_PASSWORD, pass --saved, or pass --prompt in a console.")


def run(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="--test-real-server", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--test-real-server", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--method", choices=("bs", "playwright"), default="bs")
    parser.add_argument("--student-id", default=os.getenv("UTAR_STUDENT_ID", ""))
    parser.add_argument("--saved", action="store_true", help="use the login saved in the app")
    parser.add_argument("--prompt", action="store_true", help="type the password (needs a console)")
    parser.add_argument("--headed", action="store_true", help="show the browser (playwright)")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:
        return 2 if exit_.code else 0

    report = Report()
    report.out(f"Real-server test, {time.strftime('%Y-%m-%d %H:%M:%S')}")
    report.out(f"Portal: {BASE_URL}" + ("  (UTAR_BASE_URL override)" if os.getenv("UTAR_BASE_URL") else ""))
    report.out(f"Method: {args.method}. No registration endpoint is called.")
    report.out()

    try:
        password, source = _password(args)
    except RuntimeError as error:
        report.out(f"[FAIL] credentials: {error}")
        report.save()
        return 2
    if not args.student_id:
        report.out("[FAIL] credentials: no student ID (use --student-id, UTAR_STUDENT_ID or --saved)")
        report.save()
        return 2
    report.out(f"[ OK ] credentials: student ID given, password from {source}")

    if args.method == "playwright":
        from .utils.browser_setup import configure_browsers_path
        from .scrapers.playwright_scraper import PlaywrightScraper

        configure_browsers_path()
        scraper = PlaywrightScraper()
        scraper.set_headless_mode(not args.headed)
    else:
        from .scrapers.beautifulsoup_scraper import BeautifulSoupScraper

        scraper = BeautifulSoupScraper()
    _forbid_submissions(scraper)
    scraper.on_login_progress = lambda attempt, maximum, previous: report.out(
        f"       login attempt {attempt}/{maximum}" + (f" (previous: {previous})" if previous else ""))

    try:
        logged_in = report.stage("login", lambda: scraper.login(args.student_id, password) and "logged in")
        if logged_in:
            def student_info():
                data = scraper.get_home_page_data()
                info = data[0] if isinstance(data, tuple) else data
                if not info:
                    raise RuntimeError("the registration page had no student information table")
                keys = ", ".join(sorted(info)[:8])
                return f"{len(info)} field(s) parsed ({keys})"

            def registered():
                data = scraper.get_registered_courses()
                courses = data.get("courses", [])
                return f"{len(courses)} registered course(s) parsed: " + (
                    ", ".join(course["code"] for course in courses) or "none")

            report.stage("student info", student_info)
            report.stage("registered courses", registered)
    finally:
        try:
            scraper.cleanup()
        except Exception:  # noqa: BLE001
            pass

    report.out()
    report.out("RESULT: " + ("FAILED" if report.failed else "PASSED") + f" (report: {REPORT_FILE})")
    report.save()
    return 1 if report.failed else 0
