# issues.txt run report (unattended, 2026-11-13)

Work was done directly on `develop`, with no questions asked. Where something was ambiguous, I took the conservative option and recorded the decision below.

Nothing contacted the real UTAR server. All tests ran against `src/mock_server.py`.

## Summary

| # | Task | Status |
|---|------|--------|
| 1 | Pre-flight check UX | Done + tested |
| 2 | Playwright browser in the packaged app | Done + tested in the rebuilt exe |
| 3 | Remove "Desktop ready" | Done + tested |
| 4 | Shorter header | Done + tested |
| 5 | Bundle size | Done: 231 MB → 221.3 MB, measured |
| 6 | Toast queue | Done + tested |
| 7 | "Stopping..." status | Done + tested |
| 8 | Elapsed timers | Done + tested |
| 9 | Login retry behaviour | Done + tested (mock) |
| 10 | Password show/hide | Done + tested |
| 11 | Drag-and-drop import | Done + tested in Chromium. Not tested by real drag into the WebView2 window (see below) |
| 12 | Import mode (replace / new plan) | Done + tested |
| 13 | Pre-flight without a course plan | Done + tested |
| 14 | Start-time options | Done + tested |
| 15 | Login error handling | Done + tested |
| 16 | Login timing vs bidding timing | Implemented + tested on the mock. Real-portal behaviour not verified (no credentials, portal closed) |
| 17 | Process cleanup after crashes | Done + tested (source and exe) |
| 18 | Remember student ID + password | Done + tested |
| 19 | Debug logging and diagnostics | Done + tested |
| 20 | Layout for smaller screens (tabs) | Done + tested at 600 px |
| 21 | Real-server integration test mode | Implemented + tested against the mock and in the exe. Not run against the real server (by rule) |

Extra bug found and fixed:
- Without `config.ini` the app used wrong built-in portal URLs (`login_proc.jsp`, `registerCourse.jsp`), and `UTAR_BASE_URL` could not override them.
- `build_exe.py` did not copy `config.ini` into the exe folder.

## Per task

**1. Pre-flight UX.**
- Pre-flight now runs four steps: log in, read registered courses, check codes/groups/places, check clashes.
- Each step shows Waiting, Running (with a spinner), Done, Warning, Failed or Skipped, plus a detail line and its own timer.
- While login runs, it shows the attempt, for example "Attempt 2/5, previous: Wrong captcha".
- If a step fails, the error appears on that step and the remaining steps are marked "Skipped" with the reason.
- Tests: `pf_03_steps_visible`, `pf_02_no_plan`, `PreflightTests`.

**2. Playwright browser in the exe.**
- Root cause: when frozen, Playwright sets `PLAYWRIGHT_BROWSERS_PATH=0` itself (`playwright/_impl/transport.py:130`). It then looks inside `_internal/.../.local-browsers`, which the bundle doesn't contain.
- Fix (`src/utils/browser_setup.py`): at startup the exe uses the normal per-user folder `%LOCALAPPDATA%\ms-playwright` instead, where `playwright install` puts browsers.
- If Chromium is missing there, login stops with an actionable message, and Login & settings shows an "Install browser" button. The button runs the exe's own bundled driver, so no separate tool is needed.
- If the browser fails to launch, the driver process is now stopped too.
- Verified in the rebuilt exe:
  - `--test-real-server --method playwright` passes against the mock (this is the case that failed before).
  - With an empty browser folder it fails with the "Install browser" message, and no driver process is left behind.
  - The bundled installer downloaded Chromium in 45 s, after which the exe passed.
- Decision: Chromium is not bundled. It would add about 300 MB, which works against task 5.

**3 and 4. Header.**
- The header is now a single line, "UTAR Course Bidding". The subtitle and the "Desktop ready" pill are gone.
- In their place is a run-status chip: phase, login attempt, countdown and elapsed time.
- A bridge warning appears only if the desktop bridge is actually missing.
- Test: `ux_01_header_and_tabs`.

**5. Bundle size.**
- Measured with the new `tools/bundle_size.py`: 231 MB → 221.3 MB.
- Removed:
  - the full copy of `src/` (sources, caches, the legacy PyQt GUI); now only the OCR model and charset are added;
  - stale `ddddocr` build code;
  - tkinter;
  - Pillow's AVIF plugin (7.5 MB; captchas are JPEG).
- What remains is needed at runtime:
  - Playwright's Node.js driver: 95.5 MB
  - onnxruntime: 37.5 MB
  - numpy and its OpenBLAS library: 26 MB
  - the captcha model: 13 MB
  - Python and its DLLs: about 15 MB
- Assessment: reasonable for an app that ships a headless-browser driver plus an ML runtime.
- The only big further saving would be downloading the Playwright driver on demand. That would change how Playwright is shipped, so I left it.
- The README documents the breakdown.

**6. Toasts.**
- Root cause: the 700 ms status poll called `setNotice()` on every tick, so the toast was re-shown and its timer restarted forever.
- Now:
  - toasts are queued and shown one at a time, switching strictly in sequence;
  - they dismiss themselves after 3.2 s (errors after 6.5 s) and have a close button;
  - duplicates are dropped and at most 4 are queued;
  - the poll only toasts when a run finishes.
- Test: `ux_05_toast_queue`.

**7. Stopping.**
- Stop sets `stopping=True` straight away. The chip and button then read "Stopping..." while the run is still alive.
- "Cancelled" appears only after the worker has really ended.
- The 25 s safety net still applies, and it also clears `stopping`.
- Tests: `run_01_stopping_and_timer`, `test_stopping_flag_while_running`.

**8. Elapsed timers.**
- The backend now records `started_at`/`ended_at` for each run or pre-flight and for each pre-flight step.
- The UI shows a live mm:ss once 3 s have passed: in the status chip, the status line, and next to each step.
- The timer stops when the run completes, fails or is cancelled.
- Test: `run_01` checks that the timer counts while running and freezes after the end.

**9. Login retries.**
- Why it was slow:
  - every failure slept a fixed time;
  - inside each attempt, the "session expired" handler started a hidden nested re-login, doubling the requests;
  - with the portal closed, all 5 attempts ran.
- Now:
  - one set of requests per attempt;
  - a wrong captcha retries immediately, other failures back off 1–3 s;
  - pauses end at once when Stop is pressed;
  - after 2 consecutive "login accepted, then session expired" answers the login stops and reports "portal closed";
  - each attempt's reason is recorded and shown, for example "Login attempt 2/5 (previous attempt: Wrong captcha)";
  - errors are typed (`src/scrapers/errors.py`: InvalidCredentials, PortalClosed, PortalUnavailable, BrowserMissing).
- Playwright gets the same behaviour (3 attempts).
- Reliability is unchanged for real failures, since wrong captchas and network errors still get up to 5 attempts.
- Measured: closed-portal unit tests went from 33.8 s to 13 s.

**10. Password toggle.**
- The UI had no show/hide toggle, so I added one.
- It's a `type="button"` outside the form label, and it only switches the input type, so the value is never touched.
- It keeps working after validation errors and repeated clicks.
- Test: `ux_02_password_toggle`.

**11. Drag and drop.**
- Before this change the UI had no drop handling at all. Dropping a file onto WebView2 made the window navigate to the file itself.
- Now:
  - the window blocks file drops everywhere;
  - the Courses panel is a drop zone with a highlight and an overlay;
  - only `.txt`/`.json` are accepted, with clear errors for other types, empty files and unreadable files;
  - the file picker still works.
- Test: `ux_03_drag_drop_import`, which dispatches real DragEvents with a File in Chromium. WebView2 uses the same engine.
- Not tested: an actual mouse drag from Explorer into the packaged window. That can't be automated here, so please try it once.

**12. Import mode.**
- Every import now opens a dialog with two choices:
  - "Import as new plan" (with a name), which keeps all plans;
  - "Replace <plan>", which explains that its N courses are replaced and cannot be restored.
- It defaults to "new plan" whenever the current plan has courses, to prevent accidental overwrites.
- New API: `preview_import`, plus `import_courses(..., mode, new_name)`.
- Tests: `ux_04_import_mode`, `test_import_modes`.

**13. Pre-flight without a plan.**
- Allowed now. Login and the registered list are checked, and the plan and clash steps show "Skipped: No course plan yet...".
- A missing plan is never reported as a login failure. Start still requires courses.
- Tests: `pf_02_no_plan`, `test_preflight_without_any_plan_checks_login_only`, `test_preflight_allowed_without_courses`.

**14. Start time.**
- "When should bidding start?" has three options: immediately, at a clock time, or after N minutes counted from clicking Start.
- The chip shows a countdown ("starts in 04:12"), and the app warns you to keep it open and the computer awake.
- If login takes longer than expected, bidding starts as soon as login finishes.
- Decision: "after N minutes" counts from clicking Start, not from login, so the time is predictable.
- Tests: `schedule_01_start_at_time`, `schedule_02_after_delay`.

**15. Login errors.**
- Login failures now carry `error_source="login"` and a kind.
- The UI opens Login & settings and shows a persistent panel with:
  - a title and message;
  - one line per attempt;
  - a hint for that kind of failure;
  - a Dismiss button.
- For wrong credentials, both fields are outlined, and Start and Pre-flight are blocked until you change them. The rest of the app stays consistent.
- The fast-changing log no longer drives toasts (see task 6). Registration errors are kept separate from login errors.
- Test: `login_01_error_panel`.

**16. Early login vs bidding window.**
- What I could establish:
  - your exe log, and the earlier freeze, showed the real portal accepting the login and then answering "session expired" when registration is closed;
  - you also reported that, in a browser, refreshing a page you logged into early doesn't show the Register button.
- I could not check whether a session logged in before opening becomes usable once registration opens (no credentials, portal closed).
- Strategy implemented (safe either way):
  - log in 60 s early;
  - while the portal looks closed or unreachable, retry **only the login** every 10 s until 180 s after the start. Logging in never bids;
  - wrong credentials stop at once;
  - at the start time, every pass first re-reads the registered list. If that says "session expired", the app logs in again once and re-reads;
  - Playwright now reports an expired session instead of reading it as "nothing registered";
  - bids are never retried blindly, because each pass re-reads UTAR's registered list first.
- Login retries and countdowns are visible in the UI.
- Tests: `test_scheduled_start_retries_login_while_closed_then_bids`, `test_scheduled_start_gives_up_after_grace`, `test_session_expired_at_start_relogs_in_once`, `closed_02_stop_while_login_fails`.
- To verify on the real portal, run `--test-real-server` just before and after registration opens.

**17. Process cleanup.**
- New `src/utils/process_guard.py`: at startup the app puts itself in a Windows job object with kill-on-close. Chromium, the Playwright driver and WebView2 die with the app, even after a crash or End task.
- Your own browsers are never in this job, so they are unaffected.
- Normal cleanup also runs at exit.
- A failed browser launch now stops the driver as well.
- Tested:
  - unit test: hard-killing a parent kills its child;
  - packaged exe: a hard kill took all 6 WebView2 processes down within 4 s.

**18. Credentials.**
- Student ID and password are saved when you edit them (debounced) if "Remember on this computer" is on, which is the default.
- The password is encrypted with Windows DPAPI via ctypes: no new dependency and no key stored in the program. It's decrypted only in memory.
- The fields are prefilled at startup, and unticking deletes the saved login.
- The old plaintext `password` setting is always written empty. I checked that none of your existing databases held one.
- On non-Windows systems only the student ID is remembered.
- Tests: `login_02_remember_credentials` (also checks the database has no plain text), `test_credentials_are_encrypted_and_restored`.
- Decision: remember is on by default, because you asked for persistence. You can untick it in the UI.

**19. Diagnostics.**
- Log level is set by `config.ini [Logging] level` or `UTAR_LOG_LEVEL`, and the log format now includes the thread name.
- `debug_dumps = true` (or `UTAR_DEBUG_DUMPS=1`) writes sanitised HTTP request/response files (status, headers, form, body) and Playwright screenshots of failed login attempts to `logs/debug/`.
- These dumps mask passwords, captcha answers, cookies, session ids and IC numbers, and truncate bodies.
- New Logs tab: activity log with times, plus an "Open logs folder" button.
- Verified that 3 dump files are written during a login, with the password masked.

**20. Layout.**
- Tabs: Courses, Login & settings, Pre-flight, Registration, Logs.
- Start, Pre-flight and Stop, plus the status chip, status line and last notice, are on every tab.
- The app switches tabs automatically: to Registration on Start, to Pre-flight on pre-flight, to Login on a login error.
- Large screens use two-column grids; under 900 px everything stacks, and under 560 px the slots column is hidden.
- Test: `ux_06_narrow_window` checks each tab at 600 px for sideways scrolling.

**21. Real-server test.**
- New mode `main.py --test-real-server` (also works with the exe). Options: `--method bs|playwright`, `--student-id`, `--saved`, `--prompt`, `--headed`.
- Stages: credentials, login, student info, registered courses, each with OK/FAIL and timing.
- The scraper's submit methods are replaced with functions that raise, so no registration endpoint can be called.
- Exit codes: 0 passed, 1 failed, 2 usage problem. The report also goes to `logs/real-server-test.txt`, since the exe has no console.
- Tested against the mock from source (unit tests) and with the packaged exe (both methods, plus bad login).
- Never run against the real server.

## Files changed

- `src/scrapers/errors.py` (new): typed login and browser errors.
- `src/scrapers/beautifulsoup_scraper.py`: login loop with progress, typed errors, closed-portal detection, no nested relogin, cancellable pauses, debug dumps.
- `src/scrapers/playwright_scraper.py`: login retries, typed errors, expired-session detection, BrowserMissing, driver cleanup when launch fails, screenshots.
- `src/services/plan_runner.py`:
  - status fields: steps, log, login, stopping, timers, error source/kind;
  - pre-flight steps, including with no plan;
  - scheduled login retry while closed;
  - relogin once on an expired session.
- `src/web_backend.py`: credentials, browser status/install, import preview/modes, logs folder, timers, process guard and browser path at startup, atexit cleanup.
- `src/real_server_test.py` (new), `main.py`: `--test-real-server`.
- `src/utils/secret_store.py`, `browser_setup.py`, `diagnostics.py`, `process_guard.py` (all new).
- `src/utils/config.py`: log level override, debug dumps, debug dir, built-in default URLs fixed. `config.ini` gets the new `[Logging]` keys.
- `web/src/App.vue`, `web/src/style.css`: new tabbed UI and every UI task above.
- `build_exe.py`: smaller data set, excludes, copies `config.ini`. `tools/bundle_size.py` (new): size report.
- Tests: `tests/test_issue_fixes.py` (new, 21 tests). `tests/e2e/run_e2e.py` gets tab helpers, adapts existing cases, and adds 13 cases. `tests/test_plan_runner.py`: one timing-dependent test adapted to the faster login.
- Docs: `docs/KNOWLEDGE.md`, `README.md`, this report.

## Test results

All runs are against the mock server.

| Suite | Before (baseline) | After |
|---|---|---|
| Unit: `test_plan_runner`, `test_mock_server`, `test_utar_html_parser` | 29/29 (33.8 s) | 29/29 (about 13 s) |
| Unit: `test_issue_fixes` (new) | none | 21/21 |
| E2E: `tests/e2e/run_e2e.py` | 39/39 | 52/52 (13 new cases; 7 existing cases adapted to the tabs, import dialog and faster login) |
| Stress: `run_stress.py --quick` | PASS | PASS (0 failures, cancel about 10 s by design, browser process delta 0) |
| Packaged exe | none | `--test-real-server` passes with bs and playwright; missing-browser path, browser install, window launch and crash cleanup all checked |

No earlier behaviour regressed. The adapted E2E cases now navigate the new tabs and confirm the import dialog. `closed_02` now covers a scheduled start while the portal is closed, because plain login now gives up within seconds, before Stop could be pressed.

## Packaged app

- Rebuilt at `dist\UnitRegTimetable\UnitRegTimetable.exe`, 221.3 MB (was 231 MB). Your `data\app.db` is restored and `config.ini` is copied.
- `build_exe.py` could not clean the old folder, because VS Code (your editor, pid 5552) had `_internal\vcruntime140.dll` loaded from it.
  - I built into a temporary folder and copied the files over.
  - The locked DLL is byte-identical to the new one, so I left it in place.
  - I removed 2 stale old web assets.
  - I did not close VS Code.
- Checked in the exe:
  - window opens ("UTAR Course Bidding");
  - `--test-real-server` passes with both methods against the mock;
  - with a missing browser, the error is actionable;
  - the browser install works;
  - after a hard kill, every child process exits;
  - `error.log` is empty.

## Commands for you

```powershell
# Real portal, login + read only (never bids). Use while registration is open, and once just before it opens:
venv\Scripts\python main.py --test-real-server --student-id <ID> --prompt
dist\UnitRegTimetable\UnitRegTimetable.exe --test-real-server --saved      # report in dist\UnitRegTimetable\logs\real-server-test.txt

# Size breakdown after a build
venv\Scripts\python tools\bundle_size.py

# Rebuild (close VS Code windows that have the dist folder open first)
venv\Scripts\python build_exe.py
```

## Not done / open questions

- Task 11: please drag a timetable file from Explorer into the packaged window once. Only the automated Chromium test has been run.
- Task 16: whether an early session still works once the window opens, and what the portal shows before opening, can only be confirmed on the live portal. The app's behaviour is safe either way.
- `README.zh.md` is still not updated.
- Group switching is still not automated; it needs a capture of `changeClass.jsp`.

---

# Run 2: exe logs and updated issues.txt (2026-11-13, 15:10)

The input was `dist\UnitRegTimetable\logs` (scraper.log, error.log, real-server-test.txt, debug/) from your pre-flights between 13:58 and 14:03, plus the updated `issues.txt`. No personal data from the logs is repeated here.

## What the logs showed

| # | Problem in the logs | Cause | Status |
|---|---|---|---|
| L1 | BeautifulSoup pre-flights: "Login accepted, then the portal answered session expired" twice, reported as "registration may be closed" | The debug dumps show the portal did not expire the session. After the password was accepted it redirected to `login.jsp?message=notActive` ("Your study status is not allowed to access this system, please check with faculty officer") or `message=notConsultAdviser`. That means UTAR refused the account. The scraper ignored the redirect, so the next page said "session expired". | Done + tested. New `AccountNotAllowed` error: shown at once with UTAR's own red text, no retries, never called "portal closed". A scheduled start does not keep retrying it either. |
| L2 | Playwright pre-flights: "The portal did not answer within 3s", 3 times | Same refusal. The browser landed on the login page with the red message, but the login only waited for "Log Out" or "Invalid", so it ran out the full wait (3 s in your exe `config.ini`) three times. | Done + tested. The Playwright login now watches for `login.jsp?message=<code>` and stops on the first attempt. |
| L3 | A pre-flight at 14:01:36 stopped after the captcha with nothing in the log | The portal answered "Invalid Student ID or Password" (`message=loginError`). The app handled it correctly but never logged it. | Done. Every login error is now written to `scraper.log` with its kind. |
| L4 | Debug dumps contained the `passid=` login token from the redirect URL and the student ID in the form | Masking covered only the password, captcha, cookies and jsessionid | Done + tested. `passid` and the student ID (`reqFregkey`) are now masked too. |
| L5 | The first Playwright captcha took up to 14 s on a busy PC | Each scraper loaded the 13 MB OCR model again (about 1.5 s, plus about 3 s for the first import) | Done + tested. One shared model per app, loaded in the background at startup. |
| L6 | `error.log` is empty and `real-server-test.txt` is from the 04:04 mock check | Nothing to fix | None |

**What this means for you.** These pre-flights did not fail because registration is closed or because of the app. UTAR's login refused the account with its own message: study status not allowed, and in later attempts "notConsultAdviser". That has to be sorted out with UTAR (faculty officer or academic adviser). The app now says so plainly in the Login & settings panel.

## issues.txt (updated)

| Item | Status |
|---|---|
| "For playwright allow save the web html too (if possible) on debug" | Done + tested. With `debug_dumps = true`, the Playwright scraper saves a screenshot **and** the sanitised page HTML (`.html`, with the URL in a header comment) to `logs/debug/`. This happens for every failed or refused login attempt, the registered-courses page, and the result page after each submit. Test: `DebugPageTests`. |

## Tests

| Suite | Result |
|---|---|
| Unit: `test_issue_fixes`, `test_plan_runner`, `test_mock_server`, `test_utar_html_parser` | 56/56 OK. New: 5 refused-account tests (both methods, both codes, scheduled start), the debug HTML test, extended sanitizer checks |
| E2E: `tests/e2e/run_e2e.py` | 53/53 passed (new: `login_03_account_refused`) |

New mock scenarios `not-active` and `not-adviser` copy the portal's redirect. The `notConsultAdviser` page wording in the mock is a stand-in, because your logs had only the code. The app shows whatever red text the real portal returns.

## Not done

- The exe was not rebuilt, because the updated issues.txt does not ask for a packaged-app check. To get these fixes in the exe, run `venv\Scripts\python build_exe.py`. Close any VS Code window with the dist folder open first, or the clean step fails.
- Related fix found while writing this: a rebuild used to wipe `dist\UnitRegTimetable` including your `data\app.db`, and since run 1 it also overwrote your edited `config.ini`. `build_exe.py` now keeps `data\`, `logs\` and `config.ini` (a copy stays in `build\keep-user-files`) and restores them after the build. I tested this with a simulated build in a temp folder; your dist folder was not touched.
