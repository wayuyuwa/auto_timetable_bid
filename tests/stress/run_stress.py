"""
Stress test for the Python (pywebview) backend. No real UTAR, no AI: everything
runs against an in-process copy of src/mock_server.py.

Phases (both BeautifulSoup and Playwright methods):
  A. Repeat + cancel cycles  - many sequential runs, then rapid start/cancel
                               mid-run, stressing thread/browser startup+shutdown
                               and the "stop safely" path.
  B. Concurrent load         - many scraper clients hitting the mock at once.
  C. Soak / duration         - back-to-back runs for a fixed time, watching for
                               memory growth, thread leaks, or slowdown.

Run:
    venv\\Scripts\\python tests\\stress\\run_stress.py
    venv\\Scripts\\python tests\\stress\\run_stress.py --quick
    venv\\Scripts\\python tests\\stress\\run_stress.py --no-playwright

Writes tests/stress/report.md and prints a summary. Exit code 1 if any phase
records a hard failure (crash, leak over threshold, or unexpected run outcome).
"""

import argparse
import os
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import ThreadingHTTPServer

import psutil

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(ROOT, "tests", "stress")

# Leak thresholds: lingering threads / browser processes above baseline that we
# treat as a failure.
THREAD_LEAK_LIMIT = 4
PROC_LEAK_LIMIT = 2


def log(msg):
    print(msg, flush=True)


# --------------------------------------------------------------- infrastructure

def start_mock():
    """Start the mock UTAR server in-process; return (server, base_url)."""
    from src.mock_server import MockHandler

    class QuietHandler(MockHandler):
        def log_message(self, *args):
            pass

        def handle(self):
            try:
                super().handle()
            except (ConnectionError, OSError):
                pass  # client hung up on a delayed/cancelled response

    server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
    server.daemon_threads = True
    server.base_path = "/portal/courseRegStu"
    server.scenario = "success"
    server.delay = 30  # timeout-scenario delay (s); long enough to cancel mid-flight
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base_url = f"http://127.0.0.1:{server.server_port}{server.base_path}"
    return server, base_url


def make_courses(n):
    from src.models.course import Course

    return [
        Course(code=f"MOCK{1000 + i}", name=f"Course {i}", slots={"L": [1], "T": [2]})
        for i in range(n)
    ]


def chrome_proc_count():
    """Browser processes started by this test (children), not the user's own."""
    count = 0
    for p in psutil.Process().children(recursive=True):
        try:
            name = (p.name() or "").lower()
            if "chrome" in name or "headless_shell" in name or "msedge" in name:
                count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return count


def snapshot():
    proc = psutil.Process()
    return {
        "threads": threading.active_count(),
        "rss_mb": proc.memory_info().rss / (1024 * 1024),
        "chrome": chrome_proc_count(),
    }


class Report:
    def __init__(self):
        self.sections = []
        self.failures = []

    def add(self, title, rows):
        self.sections.append((title, rows))

    def fail(self, msg):
        self.failures.append(msg)
        log(f"  !! FAILURE: {msg}")

    def write(self):
        lines = ["# Python backend stress test", ""]
        lines.append(f"Generated {time.strftime('%Y-%m-%d %H:%M:%S')} against src/mock_server.py (in-process).")
        lines.append("")
        lines.append(f"**Result: {'FAIL' if self.failures else 'PASS'}** "
                     f"({len(self.failures)} hard failure(s)).")
        lines.append("")
        if self.failures:
            lines.append("## Failures")
            lines += [f"- {f}" for f in self.failures] + [""]
        for title, rows in self.sections:
            lines.append(f"## {title}")
            lines.append("")
            lines.append("| Metric | Value |")
            lines.append("|---|---|")
            for k, v in rows:
                lines.append(f"| {k} | {v} |")
            lines.append("")
        os.makedirs(OUT_DIR, exist_ok=True)
        with open(os.path.join(OUT_DIR, "report.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


# --------------------------------------------------------------------- phases

def one_run(DesktopApi, Database, api, method, courses, timeout=120, server=None):
    """Drive a single start->finish run through the real DesktopApi threading path."""
    if server is not None:
        from src.mock_server import reset_state
        reset_state(server)  # registered courses are skipped, so start each run clean
    api.save_courses([c.__dict__ for c in courses])
    api.start("2103370", "pw", method, True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = api.get_status()
        if not st["running"] and st["phase"] != "idle":
            return st
        time.sleep(0.05)
    return {"phase": "TIMEOUT", "running": True, "results": {}}


def phase_repeat_cancel(ctx, method, repeats, cancels):
    from src.web_backend import DesktopApi
    from src.storage.database import Database

    rows = []
    base = snapshot()
    courses = make_courses(3)
    db = Database(os.path.join(ctx["tmp"], f"repeat_{method}.db"))
    api = DesktopApi(database=db)

    # Sequential repeats (success scenario)
    ctx["server"].scenario = "success"
    ok = 0
    t0 = time.time()
    for i in range(repeats):
        st = one_run(DesktopApi, Database, api, method, courses, server=ctx["server"])
        if st["phase"] == "complete":
            ok += 1
        else:
            ctx["report"].fail(f"{method} repeat #{i}: phase={st['phase']} msg={st.get('message')!r}")
    repeat_elapsed = time.time() - t0
    rows.append((f"Sequential runs ({method})", repeats))
    rows.append(("Completed OK", ok))
    rows.append(("Total time", f"{repeat_elapsed:.1f}s"))
    rows.append(("Avg per run", f"{repeat_elapsed / max(repeats,1):.2f}s"))

    # Rapid start/cancel mid-run (timeout scenario so the run is slow enough to cancel)
    ctx["server"].scenario = "timeout"
    cancel_latencies = []
    cancelled_ok = 0
    from src.mock_server import reset_state
    for i in range(cancels):
        reset_state(ctx["server"])
        api.save_courses([c.__dict__ for c in courses])
        api.start("2103370", "pw", method, True)
        # wait until bidding actually starts
        entered = False
        wait_deadline = time.time() + 30
        while time.time() < wait_deadline:
            if api.get_status()["phase"] == "bidding":
                entered = True
                break
            time.sleep(0.02)
        time.sleep(0.3)  # let a request get in flight
        tc = time.time()
        api.cancel()
        fin_deadline = time.time() + 60
        final = None
        while time.time() < fin_deadline:
            st = api.get_status()
            if not st["running"]:
                final = st
                break
            time.sleep(0.02)
        latency = time.time() - tc
        if final is None:
            ctx["report"].fail(f"{method} cancel #{i}: run never stopped (hang)")
        elif final["phase"] != "cancelled":
            ctx["report"].fail(f"{method} cancel #{i}: ended {final['phase']!r}, expected 'cancelled'")
        else:
            cancelled_ok += 1
            cancel_latencies.append(latency)
        if not entered:
            # not necessarily fatal, but note it
            rows.append((f"cancel #{i} note", "bidding phase not observed before cancel"))

    rows.append((f"Cancel cycles ({method})", cancels))
    rows.append(("Ended as 'cancelled'", cancelled_ok))
    if cancel_latencies:
        rows.append(("Cancel latency avg", f"{statistics.mean(cancel_latencies):.1f}s"))
        rows.append(("Cancel latency max", f"{max(cancel_latencies):.1f}s"))

    api.cleanup()
    time.sleep(1.5)  # allow threads/browsers to wind down
    after = snapshot()
    thread_delta = after["threads"] - base["threads"]
    chrome_delta = after["chrome"] - base["chrome"]
    rows.append(("Thread delta (after-before)", thread_delta))
    rows.append(("Browser proc delta", chrome_delta))
    rows.append(("RSS before/after", f"{base['rss_mb']:.0f} / {after['rss_mb']:.0f} MB"))
    if thread_delta > THREAD_LEAK_LIMIT:
        ctx["report"].fail(f"{method} repeat/cancel: thread leak +{thread_delta}")
    if chrome_delta > PROC_LEAK_LIMIT:
        ctx["report"].fail(f"{method} repeat/cancel: browser process leak +{chrome_delta}")

    ctx["report"].add(f"A. Repeat + cancel - {method}", rows)


def _one_client(method, course):
    """One independent scraper: login + register. Returns (ok, latency, err)."""
    from src.scrapers.beautifulsoup_scraper import BeautifulSoupScraper
    from src.scrapers.playwright_scraper import PlaywrightScraper

    t0 = time.perf_counter()
    scraper = None
    try:
        if method == "BeautifulSoup":
            scraper = BeautifulSoupScraper()
            scraper.reset_cancellation()
            scraper.login("2103370", "pw")
        else:
            scraper = PlaywrightScraper()
            scraper.set_headless_mode(True)
            scraper.reset_cancellation()
            if not scraper.login("2103370", "pw"):
                return (False, time.perf_counter() - t0, "login returned False")
        _text, ok = scraper.register_courses([course])
        return (bool(ok), time.perf_counter() - t0, None if ok else "register not ok")
    except Exception as e:  # noqa: BLE001 - we want every failure recorded
        return (False, time.perf_counter() - t0, f"{type(e).__name__}: {e}")
    finally:
        if scraper is not None:
            try:
                scraper.cleanup()
            except Exception:
                pass


def phase_concurrent(ctx, method, workers, tasks):
    rows = []
    base = snapshot()
    ctx["server"].scenario = "success"
    course = make_courses(1)[0]

    latencies = []
    ok = 0
    errors = {}
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(_one_client, method, course) for _ in range(tasks)]
        for fut in as_completed(futs):
            success, latency, err = fut.result()
            latencies.append(latency)
            if success:
                ok += 1
            else:
                errors[err] = errors.get(err, 0) + 1
    wall = time.time() - t0

    rows.append((f"Method", method))
    rows.append(("Concurrency (workers)", workers))
    rows.append(("Total clients", tasks))
    rows.append(("Succeeded", ok))
    rows.append(("Failed", tasks - ok))
    rows.append(("Wall time", f"{wall:.1f}s"))
    rows.append(("Throughput", f"{tasks / wall:.1f} clients/s"))
    if latencies:
        latencies.sort()
        rows.append(("Latency avg", f"{statistics.mean(latencies):.2f}s"))
        rows.append(("Latency p50", f"{latencies[len(latencies)//2]:.2f}s"))
        rows.append(("Latency p95", f"{latencies[int(len(latencies)*0.95)-1]:.2f}s"))
        rows.append(("Latency max", f"{max(latencies):.2f}s"))
    for err, n in errors.items():
        rows.append((f"error: {err}", n))

    time.sleep(1.5)
    after = snapshot()
    rows.append(("Thread delta", after["threads"] - base["threads"]))
    rows.append(("Browser proc delta", after["chrome"] - base["chrome"]))
    if tasks - ok > 0:
        ctx["report"].fail(f"{method} concurrent: {tasks-ok}/{tasks} clients failed")
    if after["chrome"] - base["chrome"] > PROC_LEAK_LIMIT:
        ctx["report"].fail(f"{method} concurrent: browser process leak +{after['chrome']-base['chrome']}")

    ctx["report"].add(f"B. Concurrent load - {method}", rows)


def phase_soak(ctx, method, duration):
    from src.web_backend import DesktopApi
    from src.storage.database import Database

    rows = []
    ctx["server"].scenario = "success"
    courses = make_courses(3)
    db = Database(os.path.join(ctx["tmp"], f"soak_{method}.db"))
    api = DesktopApi(database=db)

    samples = []
    runs = 0
    ok = 0
    start = time.time()
    first_run_time = None
    last_run_time = None
    while time.time() - start < duration:
        t0 = time.time()
        st = one_run(DesktopApi, Database, api, method, courses, server=ctx["server"])
        dt = time.time() - t0
        runs += 1
        if st["phase"] == "complete":
            ok += 1
        else:
            ctx["report"].fail(f"{method} soak run #{runs}: phase={st['phase']}")
        if first_run_time is None:
            first_run_time = dt
        last_run_time = dt
        samples.append(snapshot()["rss_mb"])

    api.cleanup()
    rows.append(("Method", method))
    rows.append(("Duration target", f"{duration}s"))
    rows.append(("Runs completed", runs))
    rows.append(("Succeeded", ok))
    rows.append(("First run time", f"{first_run_time:.2f}s" if first_run_time else "n/a"))
    rows.append(("Last run time", f"{last_run_time:.2f}s" if last_run_time else "n/a"))
    if samples:
        rows.append(("RSS start/end", f"{samples[0]:.0f} / {samples[-1]:.0f} MB"))
        rows.append(("RSS growth", f"{samples[-1] - samples[0]:+.0f} MB"))
        # Flag runaway growth
        if samples[-1] - samples[0] > 150:
            ctx["report"].fail(f"{method} soak: RSS grew {samples[-1]-samples[0]:.0f} MB (possible leak)")
    ctx["report"].add(f"C. Soak - {method}", rows)


# ------------------------------------------------------------------------ main

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quick", action="store_true", help="smaller counts for a fast check")
    parser.add_argument("--no-playwright", action="store_true", help="BeautifulSoup only")
    args = parser.parse_args()

    # Sizing
    if args.quick:
        cfg = dict(bs_repeat=5, bs_cancel=3, pw_repeat=2, pw_cancel=2,
                   bs_conc_workers=10, bs_conc_tasks=20, pw_conc_workers=2, pw_conc_tasks=4,
                   bs_soak=15, pw_soak=10)
    else:
        cfg = dict(bs_repeat=25, bs_cancel=10, pw_repeat=3, pw_cancel=3,
                   bs_conc_workers=30, bs_conc_tasks=60, pw_conc_workers=3, pw_conc_tasks=6,
                   bs_soak=60, pw_soak=25)

    import tempfile
    tmp = tempfile.mkdtemp(prefix="utar_stress_")

    # Start the mock BEFORE importing config-dependent modules, then point the
    # whole backend at it via env (config reads UTAR_BASE_URL at import time).
    sys.path.insert(0, ROOT)
    server, base_url = start_mock()
    os.environ["UTAR_BASE_URL"] = base_url
    os.environ["UTAR_MOCK_CAPTCHA"] = "mock"  # BeautifulSoup honours this; Playwright still runs OCR
    log(f"Mock server: {base_url}")

    report = Report()
    ctx = {"server": server, "report": report, "tmp": tmp}

    methods = ["BeautifulSoup"] if args.no_playwright else ["BeautifulSoup", "Playwright"]

    overall_start = time.time()
    for method in methods:
        log(f"\n=== {method} ===")
        rc = (cfg["bs_repeat"], cfg["bs_cancel"]) if method == "BeautifulSoup" else (cfg["pw_repeat"], cfg["pw_cancel"])
        log(f"[A] repeat+cancel ({rc[0]} runs, {rc[1]} cancels)")
        phase_repeat_cancel(ctx, method, rc[0], rc[1])

        if method == "BeautifulSoup":
            cw, ct = cfg["bs_conc_workers"], cfg["bs_conc_tasks"]
            soak = cfg["bs_soak"]
        else:
            cw, ct = cfg["pw_conc_workers"], cfg["pw_conc_tasks"]
            soak = cfg["pw_soak"]
        log(f"[B] concurrent ({cw} workers x {ct} clients)")
        phase_concurrent(ctx, method, cw, ct)
        log(f"[C] soak ({soak}s)")
        phase_soak(ctx, method, soak)

    report.add("Run info", [
        ("Total wall time", f"{time.time() - overall_start:.0f}s"),
        ("Methods", ", ".join(methods)),
        ("Profile", "quick" if args.quick else "full"),
    ])
    report.write()

    log("\n" + "=" * 60)
    log(f"RESULT: {'FAIL' if report.failures else 'PASS'} "
        f"({len(report.failures)} hard failure(s))")
    for f in report.failures:
        log(f"  - {f}")
    log(f"Report: {os.path.join(OUT_DIR, 'report.md')}")
    return 1 if report.failures else 0


if __name__ == "__main__":
    sys.exit(main())
