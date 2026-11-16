# Codebase knowledge map

Living map of this repo so any person or agent can find what to edit quickly.
**Rule: whenever code, config, tests or behaviour change, update this file in the same commit** (map, "where to edit", flows and the change log at the bottom). Every change-log row names its commit hash and files.

Last updated: 2026-11-17 (registration-not-open wait).

## What the app is

UTAR course-registration bidding desktop app.
- UI: Vue 3 + Vite (`web/`), shown in a **pywebview** window (Edge WebView2 on Windows). Not Electron.
- Backend: Python. Vue calls Python through `window.pywebview.api.<method>` → `DesktopApi` in `src/web_backend.py`.
- Two scraping methods: **BeautifulSoup** (requests, fast) and **Playwright** (real Chromium).
- Captcha solved locally with an ONNX OCR model (`src/utils/ocr/`).
- Data in SQLite `data/app.db` (path from `config.ini` `[Storage]`).
- Packaged with PyInstaller `--onedir` → `dist/UnitRegTimetable/UnitRegTimetable.exe` (~231 MB folder).

## File tree (what each file does)

```
main.py                         Entry point: src.web_backend.run(); `--test-real-server` runs src/real_server_test.py
main2.py                        Standalone OCR timing demo (not used by the app)
build_exe.py / build.bat        PyInstaller onedir build; bundles web/dist + OCR model files only (not all of src/);
                                keeps the user's dist data/, logs/ and config.ini across rebuilds (build/keep-user-files);
                                exits 1 when the build fails (build.bat and the workflow rely on it)
tools/bundle_size.py            Size report of dist/UnitRegTimetable (largest folders/files)
config.ini                      Portal URLs, headers, Playwright waits, [Storage] db path,
                                [Logging] level (env UTAR_LOG_LEVEL overrides) and debug_dumps (env UTAR_DEBUG_DUMPS)
requirements.txt                Python deps (PyQt5 only for the legacy GUI)
.github/workflows/build-and-release.yml   Windows build -> UnitRegTimetable.zip -> GitHub Release (permanent).
                                Runs on v* tags and on manual "Run workflow" (see "Releases" under Key flows)
.claude/settings.json           {"worktree":{"bgIsolation":"none"}} - agents edit in place
.claude/skills/utar-verify/     Skill: how to test/build/verify (commands, pitfalls, pre-commit checklist)
.claude/skills/systematic-debugging/, verification-before-completion/
                                Skills adapted from obra/superpowers (MIT, LICENSE-superpowers.txt inside):
                                root cause before fixes; evidence (command + counts) before "done" claims

src/
  web_backend.py                DesktopApi (Vue bridge): plans CRUD, preview_import/import_courses(mode replace|new),
                                get/save_saved_credentials (DPAPI), browser_status/install_browser, open_logs_folder,
                                start/preflight/choose/cancel/get_status, STOP_GRACE_SECONDS safety net (_release_if_stuck).
                                run(): process guard + Playwright browser path + window + atexit cleanup
  real_server_test.py           `--test-real-server`: login -> student info -> registered list, never submits (exit 0/1/2)
  services/
    plan_runner.py              PlanRunner (the engine): login (+progress), scheduled start (login retry while the
                                portal looks closed), bid plans, verify against UTAR's registered list, fallback
                                A->B->C (auto/ask), retry loop, pre-flight steps (works without a plan),
                                _wait_until_open (waits while registration is closed, open_check_seconds = 2).
                                StatusBoard + empty_status() = the status dict polled by the UI (incl. steps, log,
                                login attempts, stopping, started_at/ended_at, error_source/error_kind).
    bidding_service.py          LEGACY single-list service (used by legacy PyQt GUI only)
    worker_thread.py            LEGACY QThread worker (PyQt)
  scrapers/
    errors.py                   LoginError -> InvalidCredentials / AccountNotAllowed / PortalClosed / PortalUnavailable;
                                BrowserMissing; portal_rejection(code, text) maps login.jsp?message=<code> redirects
    beautifulsoup_scraper.py    requests-based scraper: login() loops _login_once() (progress callback, typed errors,
                                stops after 2 "closed" answers), relogin (RLock + _relogin_active guard; no nested
                                relogin inside login; at most RELOGIN_LIMIT relogins per RELOGIN_WINDOW), register_courses
                                (a bid is never re-sent when it may have reached the portal), get_registered_courses,
                                get_unit_slots; _check_session_expired(login_page_means_expired=True) on every
                                registration step
    playwright_scraper.py       Chromium scraper; all Playwright calls run on one _OwnerThread. login() retries
                                (typed errors), missing Chromium -> BrowserMissing, screenshots via diagnostics.
                                _open() + _with_relogin() (SessionExpired, relogin once) around every read; register_course
                                checks the registered list before re-sending a bid that may have gone through
    html_parser.py              Pure HTML parsing: student data, course values, home page,
                                parse_registered_courses, parse_unit_slots, parse_time_range, sessions_clash,
                                registration_form_open (is the registration form on the page?)
    base_scraper.py             Abstract interface
  models/                       Course (code, name, slots), BidResult/BidStatus
  storage/database.py           Database + SettingsRepository, CourseRepository, PlanRepository
                                Tables: app_settings, courses, plans, plan_courses
  utils/
    config.py                   BASE_DIR (exe-aware), load_config/create_default_config
    logger.py                   setup_logger, crash logging
    settings.py                 LEGACY user_settings.json reader
    signals.py                  Tiny Signal class (replaced PyQt signals in services)
    timetable_reader.py         Parses UTAR timetable .txt export into Course list
    secret_store.py             DPAPI encrypt/decrypt for the saved password (Windows only)
    browser_setup.py            Playwright Chromium path for the exe (fixes PLAYWRIGHT_BROWSERS_PATH=0), status, install
    diagnostics.py              Sanitised HTTP dumps (debug_dumps) and Playwright screenshots + page HTML (save_page):
                                with debug_dumps, and ALWAYS when UTAR_BASE_URL (mock) is set; folder = UTAR_DEBUG_DIR or logs/debug;
                                masks password, captcha, student ID, cookies, jsessionid/passid tokens, IC numbers
    process_guard.py            Windows job object: children (Chromium, driver, WebView2) die with the app
    captcha_solver.py, ocr/     ONNX captcha OCR (common_old.onnx + charset); one shared model per process,
                                warm_up() loads it in the background at app start
  gui/                          LEGACY PyQt5 GUI (main_window, course_manager). Not used by main.py.
  mock_server.py                Local mock of the UTAR portal. Scenarios: success, register-fail, timeout,
                                session-expired, closed, not-active, not-adviser (login refused with
                                login.jsp?message=<code>). Serves the real sample Kaptcha.jpg.
                                Sessions like the real portal (verified 2026-11-16): pages need the JSESSIONID cookie of a logged-in
                                session (else the expired script page), cookie set at login.jsp (Path=/portal) and again after login
                                (Path=/portal/courseRegStu), a 2nd login of the same student ends the 1st session, login redirects
                                via indexSurvey.jsp?passid= (a 3rd visit -> login.jsp?message=notSupportTab and the session ends).
                                Switches: server.registration_open (False = closed like the real portal: no registration form;
                                scenario registration-closed; reset_state sets it True), require_session, single_session,
                                session_timeout (idle seconds, default none;
                                the real value is not measured). reset_state keeps them. Not modelled: other real redirect hops.
                                expire_next(server, page, mode, times) makes the next request(s) fail once (js / loginpage /
                                hang / apply-then-js); server.hits and server.processed_submits count requests / bids processed.

web/
  src/App.vue                   Whole UI. Header (title, run chip with phase/elapsed/countdown, Start/Pre-flight/Stop),
                                section tabs: Courses (plans, table, drag-drop import), Login & settings (credentials,
                                show/hide, remember, login error panel, browser install, start mode now/at/after,
                                fallback, retry), Pre-flight (steps), Registration (results, confirmed board), Logs.
                                Status strip (.current-message + .notice) is visible on every tab. Toast queue.
                                Polls get_status(); all backend calls go through callApi().
  src/style.css                 All styles (teal/green palette - no purple, no decorative emoji)
  src/main.js, index.html, vite.config.js, package.json

tests/
  test_plan_runner.py           Engine unit tests (runner, verification, fallback, freeze/relogin regressions)
  test_mock_server.py           Mock server tests
  test_registration_open.py     Registration closed: scraper check, wait then bid (both methods), Stop, flaky check, pre-flight
  test_session_expiry.py        Session expiry in BS and Playwright (expire_next rules): relogin, no double bid, give-up limits,
                                a hung bid/lookup gives up at the timeout
  test_mock_sessions.py         The mock's sessions behave like the real portal (cookie, single session, passid/notSupportTab,
                                tab vs window in a browser)
  test_utar_html_parser.py      Parser tests vs real saved pages; auto-skips if F:\utar is missing
  test_issue_fixes.py           issues.txt features: login kinds, scheduled login retry, preflight w/o plan, stopping,
                                credentials, import modes, browser path, diagnostics, real-server CLI, process guard
  e2e/run_e2e.py                Playwright drives the built Vue UI with real DesktopApi + mock server
                                (--no-build, --only <id>, --headed, env E2E_WIDTH). Screenshots gitignored.
                                Helpers: h.tab(name), h.import_file(path, mode), h.fill_credentials().
  e2e/fixtures/*.txt            Timetable import fixtures (exempt from *.txt ignore)
  stress/run_stress.py          Repeat/cancel/concurrency/soak harness (--quick, --no-playwright) -> report.md
```

Not tracked / ignore: `src-tauri/` (leftover from the `tauri-rust` branch), `dist/`, `build/`, `data/`, `logs/`, `*.txt` (except e2e fixtures; note `issues.txt` is ignored).

## Where to edit for common changes

| I want to change...                                | Edit                                                        |
|----------------------------------------------------|-------------------------------------------------------------|
| Any UI text, layout, dialogs, toasts               | `web/src/App.vue` (+ `web/src/style.css`), then `npm run build` in `web/` |
| Tabs / which tab opens automatically               | `TABS` and `activeTab` in App.vue (`startRun`, `runPreflight`, `handleFinished`) |
| Toast timing / queue                               | `showToast`, `TOAST_MS` in App.vue                           |
| Login error panel / blocking Start                 | `handleFinished`, `LOGIN_TITLES`, `credentialsRejected` in App.vue; kinds from `scrapers/errors.py` |
| Login retries, attempt count, delays               | `login`/`_login_once` (BS), `LOGIN_ATTEMPTS`/`login` (Playwright), `CLOSED_AFTER` |
| Waiting for registration to open (interval, detection) | `PlanRunner.open_check_seconds`, `_wait_until_open`; `registration_form_open` (html_parser); `registration_open` in both scrapers |
| Scheduled start / early login behaviour            | `_scheduled_login` (`prelogin_seconds`, `login_grace_seconds`, `login_retry_seconds`); UI `scheduledEpoch()` |
| Pre-flight steps                                   | `PlanRunner.preflight` (`_steps_init`, `_step`) and `_preflight_checks` |
| Saved credentials                                  | `DesktopApi.get_saved_credentials/save_credentials`, `utils/secret_store.py` |
| Playwright browser not found / install             | `utils/browser_setup.py`, `PlaywrightScraper._ensure_page`  |
| Diagnostics / log level                            | `config.ini [Logging]`, `utils/diagnostics.py`, `utils/config.py` |
| Child-process cleanup                              | `utils/process_guard.py`, `run()` in web_backend, `PlanRunner._cleanup` |
| Real-server check (no bids)                        | `src/real_server_test.py`                                   |
| A new backend call from the UI                     | Add method on `DesktopApi` (`src/web_backend.py`), call via `callApi()` in App.vue |
| Run flow / retry / fallback / schedule / preflight | `src/services/plan_runner.py` (`run`, `_run_plans`, `_bid`, `_build_proposal`, `_preflight_checks`, `_scheduled_login`) |
| Status fields shown in UI                          | `empty_status()` in `plan_runner.py` and the `status` reactive in App.vue |
| Stop / cancel behaviour                            | `PlanRunner.cancel`, `DesktopApi.cancel/_release_if_stuck`, scraper `cancel()` |
| Login, captcha, session expiry (BS)                | `beautifulsoup_scraper.py` `login`, `_try_relogin`, `_check_session_expired`, `_new_session` |
| Login / browser (Playwright)                       | `playwright_scraper.py` (`_ensure_page`, `login`, `_close_browser`) |
| Parsing UTAR pages                                 | `src/scrapers/html_parser.py` (+ tests in `test_utar_html_parser.py`) |
| Portal URLs, timeouts, log level                   | `config.ini` (defaults in `src/utils/config.py`)             |
| Playwright wait times                              | `config.ini [Playwright]` `wait_time_long` 3 s (page default timeout, login answer), `wait_time_short` 1 s (wait after a bid submit), `wait_time_very_short` 0.5 s (not used in code); same defaults in `src/utils/config.py` |
| Saved data / schema                                | `src/storage/database.py`                                   |
| Timetable .txt import format                       | `src/utils/timetable_reader.py`; JSON import in `DesktopApi.import_courses` |
| Mock portal behaviour / new test scenario          | `src/mock_server.py` (+ `tests/test_mock_server.py`)        |
| Exe packaging                                      | `build_exe.py`                                              |
| GitHub build, zip contents, release naming/triggers | `.github/workflows/build-and-release.yml`                  |
| Window title / size                                | `run()` in `src/web_backend.py`                             |
| App icon                                           | `resources/icon.ico`                                        |

## Key flows

**Run (Start):** App.vue `startRun()` → `DesktopApi.start()` → `_begin()` creates `StatusBoard` + `PlanRunner`, runs `PlanRunner.run` on a daemon thread → (optional `start_at`: logs in 60 s early, waits) → login → read registered list → skip already-registered → bid Plan A → verify against UTAR's registered list → missing courses fall back to next plan (`auto` adds non-clashing courses; `ask` sets phase `awaiting_choice` and waits for `DesktopApi.choose(codes)`) → retry every `auto_retry_seconds` up to `max_attempts` → `complete`/`error`/`cancelled`. UI polls `get_status()`.

**Phases:** idle, login, scheduled, preflight, preflight_done, waiting_open, bidding, verifying, awaiting_choice, waiting_retry, complete, error, cancelled. `stopping=True` (with running) means Stop was pressed and the run is finishing its current call.

**Login errors (scrapers/errors.py → status.error_kind):** invalid_credentials (stop; UI blocks Start until the credentials change), account_not_allowed (password accepted but UTAR refuses the account: the real portal redirects to `login.jsp?message=notActive` "study status is not allowed..." or `notConsultAdviser`; `loginError` = wrong ID/password; stop, no retry, shows UTAR's red text), portal_closed (login accepted, then "session expired" = registration not open), portal_unavailable (no/odd response), browser_missing (Playwright Chromium not installed). error_source "login" shows the panel in Login & settings.

**Registration not open yet (owner decision 2026-11-17: check every 2 s, wait until Stop, both methods):** at the start of every `_run_plans` pass `_wait_until_open` asks the scraper `registration_open(first course code)` (read only). BeautifulSoup posts the unit lookup, Playwright opens the registration page; both use `html_parser.registration_form_open` (unit box `reqUnit`, Register button or the hidden lookup fields). While it is False the phase is `waiting_open` (status `open_checks`, `last_check_at`), nothing is bid, no attempt is used, a failed check is logged once and tried again, Stop ends the wait; when the form appears the run goes on at once. Real portal while closed (2026-11-17): the registration page and the lookup answer only show the registered-courses form. This is the check the first release (v1.0.0 `fuck_utar.py`, Selenium releases up to v1.3.0) had as "Registration is not open yet" (missing Register button, relogin + reload forever); the Playwright migration dropped it. Pre-flight reports "Registration is open" / a warning and skips the class checks while closed. A scraper without `registration_open` is treated as open (never waits). Login-time "portal closed" in start-now mode still stops with the login error (unchanged).

**Scheduled start (task 16 decision):** log in `prelogin_seconds` (60) before the start; if the portal looks closed/unreachable keep retrying the *login only* every 10 s until 180 s after the start (logging in never bids); at the start, `_refresh_registered` re-logs in once if the session expired. Bids are never retried blindly: every pass re-reads the registered list first. UI modes: now / at clock time / after N minutes (counted from clicking Start).

**Result labels:** Confirmed / Different group ("Needs a switch") / Not registered / Skipped / Submitted.

**Preflight:** `DesktopApi.preflight()` → `PlanRunner.preflight` → steps login / registered / plans / clashes (state pending|running|ok|warn|error|skipped with timings); never bids. With no plan, the plan steps are "skipped" and login is still checked.

**Packaged exe and Playwright:** Playwright sets PLAYWRIGHT_BROWSERS_PATH=0 when frozen (looks inside the bundle). `browser_setup.configure_browsers_path()` points it at `%LOCALAPPDATA%\ms-playwright` instead; missing Chromium → BrowserMissing with an "Install browser" button (runs the bundled driver's `install chromium`).

**Real-portal session behaviour (verified 2026-11-16, read-only probes):** one active session per account (a second login invalidates the first); a request without a valid session gets HTTP 200 with a short `sessionExpired` script (never a plain login page); a new tab in the same Playwright context stays logged in, a fresh context does not. Consequences: any parallel bidding (issue #3) must share one session/cookie jar, and an automatic relogin logs out every other window of the account.

How it works from the outside (headers only; no server source seen): Apache 2.4.23 + mod_jk in front of Java JSP (`JSESSIONID`). `login.jsp` sets `JSESSIONID` (Path=/portal; Secure; HttpOnly); the `loginProSurvey.jsp` answer (302) sets `JSESSIONID` again with no attributes, so it is scoped to `/portal/courseRegStu` - two same-named cookies; each alone is accepted. Redirect chain after login: `indexSurvey.jsp?passid=<token>` -> `registrationSurvey.jsp` -> `masterSessionSurvey.jsp` (adds `reqSid`) -> schedule / registration pages. The session is just the cookie: a client holding only the cookie values works, a different User-Agent or no Referer still works, no cookie gives the expired page, 4 parallel requests on one session work. The expired page is a ~237-byte 200 whose script sets `window.parent.location.href` to a `sessionExpired` page (written for frames; the registration page itself has no frames). Not measured: idle timeout, whether session ids rotate at login, how the "second login ends the first" rule is implemented.

**Multi-tab check (Playwright, real portal, 2026-11-16, read-only):** opening the one-time login address `indexSurvey.jsp?passid=<token>` in a second tab is answered with `login.jsp?message=notSupportTab`, and the original window's session is then dead too (expired page). Opening the plain `studentRegistrationSurvey.jsp` address in a new tab, or in a new browser context holding the same cookies, stays logged in; a context without the cookies gets the expired page. After login Playwright's address is `.../registration/studentRegistrationSurvey.jsp` (no `passid`). `notSupportTab` is not mapped in `scrapers/errors.py` (the app would show it as a generic "Portal sent the login back"). Not yet tested: lookups from two tabs at once, and what the owner's browser showed in the address bar when a pasted address logged them out (guess, unverified: the `passid` address, or a tab marker such as sessionStorage that a duplicated tab copies and a new window lacks).

**Session expiry (both scrapers):** a read (registered list, home data, unit slots, class lookup) that gets the portal's expired page - or, new, a plain login page - logs in again once and repeats the read (BS: `_try_relogin`, capped at 3 per minute; Playwright: `_with_relogin`, cookies cleared first). A bid is never sent twice when it may have reached the portal: an expired answer to a bid is followed by a login, a look at the registered list (already there = done) and only then one more bid with freshly read values; a timeout, an unclear answer or an error leaves the bid unsent-again and reported as outcome unknown (the runner's registered-list check settles it). After a Playwright timeout only the page address is checked for the expired page (`_session_gone(deep=False)`): reading the page while the portal has not answered waits for that answer. If the session cannot be restored both raise a message containing "expired" (Playwright `SessionExpired`, BS `SessionExpiredException`) and the runner's own relogin handles the rest.

**Stop:** `DesktopApi.cancel()` → runner cancel → scraper cancel; watchdog marks the run cancelled after `STOP_GRACE_SECONDS` (25 s) if the worker hangs. BS cancel floor ~10 s is deliberate (avoid double-submitting a bid).

**Releases (GitHub workflow):** job `build` (windows-latest, Python 3.10, Node 22) runs `build_exe.py`, fails if `dist\UnitRegTimetable\UnitRegTimetable.exe` is missing, zips the app folder + `config.ini` + `resources\` into `UnitRegTimetable.zip` and hands it to job `release` as an Actions artifact. That artifact is only a hand-over: GitHub deletes artifacts after the repo's retention period (90 days at most on a public repo), so it is not the permanent copy. Job `release` attaches the zip to a GitHub Release, which never expires.
- Push of a `v*` tag → release named `UnitRegTimetable <tag>` on that tag; pre-release when the tag ends in `beta`.
- Manual "Run workflow" on a branch → pre-release with the new tag `build-<run number>` on the built commit (owner's choice 2026-11-15: tags + manual runs, no release on ordinary pushes). Re-running the same run reuses its run number, so it updates that release.
- The version is whatever tag name is pushed; nothing is numbered automatically except `build-<run number>`.
- The workflow cannot be run locally; a change is only proven by a real run on GitHub. Without the `gh` CLI, read the result from the public API: `https://api.github.com/repos/wayuyuwa/auto_timetable_bid/actions/runs` and `.../releases/tags/<tag>`.
- Last verified run: tag `v1.4.0-beta` (2026-11-15, run 12) - both jobs succeeded, pre-release created with `UnitRegTimetable.zip` (86.2 MB). The manual-run path (`build-<run number>`) has not been run yet.

## Conventions and owner rules

- Work directly on `develop` in the main checkout. No new branches or worktrees (exception: owner explicitly asked for `tauri-rust`).
- Never assume: verify in code/tests; ask the owner when ambiguous (unattended runs: take the conservative option and report it).
- Minimal focused changes; no new dependencies without reason.
- UI: no purple-dominant palettes, no decorative emoji, no generic AI-looking UI.
- UTAR "switch" moves a registered course to another slot; never drop-then-add. Group switch is detected but not automated yet (needs a capture of `changeClass.jsp`).
- Never add code that can double-submit a bid; never hit the real UTAR server in tests.
- Build the exe only when the owner asks.
- Commits end with the Co-Authored-By line for the model used.

## Tests

```
venv\Scripts\python -m unittest tests/test_plan_runner.py tests/test_mock_server.py tests/test_utar_html_parser.py
venv\Scripts\python tests\e2e\run_e2e.py            # builds web/, all UI cases
venv\Scripts\python tests\stress\run_stress.py --quick
venv\Scripts\python -m src.mock_server --scenario closed   # run the mock by hand
```
venv\Scripts\python -m unittest tests/test_issue_fixes.py   # issues.txt features (uses the mock)
venv\Scripts\python -m unittest tests/test_session_expiry.py   # session expiry, both scrapers (~100 s)
venv\Scripts\python -m unittest tests/test_mock_sessions.py    # the mock's sessions match the real portal
venv\Scripts\python -m unittest tests/test_registration_open.py   # registration closed: wait, then bid
venv\Scripts\python main.py --test-real-server --student-id ID --prompt   # REAL portal, login + read only
```
Last known: see docs/run-report.md (issues.txt run).
```

## Known gaps / open items

- Group switch not automated (needs `changeClass.jsp` capture).
- The open state of the real registration page has not been seen live since the registration-open check was added; detection (reqUnit box, Register button, hidden lookup fields) rests on the selectors from earlier real pages. If a real open page is judged "not open", a run would wait until Stop: compare with the portal and adjust `registration_form_open`.
- Stress harness (`tests/stress/run_stress.py`) sets `single_session = False` on its mock: its concurrent phase logs several clients in as one student on purpose.
- Session-expiry handling is proven on the mock (tests/test_session_expiry.py) and, for the Playwright registered-list relogin, on the real portal (2026-11-17). The real lookup and bid path could not be exercised: right after a normal login the real registration page had no `input#reqUnit` (registration probably not open for the account; unverified).
- Registered-list parsing based on Dec 2023 page snapshots; not checked on the live "...Survey.jsp" flow.
- BS submit check looks for `div.red`, real pages use `span.red` (alert-text detection partly covers it).
- `README.zh.md` is behind `README.md`.
- Packaged exe: Chromium is not bundled (would add ~300 MB); the app finds/installs it in %LOCALAPPDATA%\ms-playwright.
- Real-server behaviour of early login (task 16) and the registration-closed detection are based on the mock and on
  the owner's report; verify with `--test-real-server` when the portal is open.
- Drag-and-drop is tested in Chromium (E2E); WebView2 inside pywebview should behave the same but was checked manually only if noted in docs/run-report.md.

## Change log (newest first)

Every change is listed with its git commit, so `git show <hash>` gives the exact diff.
A commit cannot contain its own hash, so a new entry is first written as `(pending)` and the
hash is filled in by the next commit. Run `git log --oneline` for anything missing here.

| Commit | Date | What changed | Files |
|---|---|---|---|
| `fe3c045` | 2026-11-17 | Registration not open yet is handled again (it was lost in the Playwright migration; first release v1.0.0 had it): both methods look every 2 s until the registration form appears or Stop is pressed, nothing is bid and no attempt used while waiting; new phase `waiting_open` with check count/time in the UI; pre-flight reports it and skips class checks while closed. `registration_open()` in both scrapers, `registration_form_open` parser, mock switch `registration_open` + scenario `registration-closed`. New `tests/test_registration_open.py` (11) and 3 E2E cases `notopen_*` | src/scrapers/html_parser.py, src/scrapers/beautifulsoup_scraper.py, src/scrapers/playwright_scraper.py, src/services/plan_runner.py, src/mock_server.py, web/src/App.vue, tests/test_registration_open.py, tests/e2e/run_e2e.py, README.md, docs/KNOWLEDGE.md |
| `9fa18e7` | 2026-11-17 | Fix a regression from `659c611` (also in the exe built from `8cf95dd`): a Playwright bid or lookup that timed out only gave up when the portal finally answered (30.5 s in the test instead of 3.3 s; Stop held up, stress showed 25 s cancel + 4 leaked browser processes). The session check after a timeout now reads only the page address. Mock now behaves like the real portal's sessions (cookie, 2nd login ends the 1st, passid/notSupportTab, optional idle timeout; switches require_session / single_session / session_timeout); old mock tests log in first; stress harness sets single_session=False. New `tests/test_mock_sessions.py` (15) and 2 hang tests in `tests/test_session_expiry.py` | src/scrapers/playwright_scraper.py, src/mock_server.py, tests/test_mock_sessions.py, tests/test_session_expiry.py, tests/test_mock_server.py, tests/stress/run_stress.py, README.md, .claude/skills/utar-verify/SKILL.md, docs/KNOWLEDGE.md |
| `659c611` | 2026-11-17 | Session expiry fixed in both scrapers. Playwright: `_open`/`_with_relogin` give every read an expiry check and one relogin (cookies cleared); a bid answered with the expired page is no longer reported "Registered"; a bid that may have gone through is checked against the registered list before being re-sent. BS: a plain login page counts as an ended session on registration steps; relogin capped (3 per 60 s); `_submit_bidding` no longer relogs in and re-sends with old values; no automatic re-send after a timeout or unclear answer (outcome unknown); success flag no longer sticks at False after a retried read. Mock: `expire_next`, `hits`, `processed_submits`. New `tests/test_session_expiry.py` (22 tests). Verified on the real portal: Playwright registered-list relogin after cleared cookies | src/scrapers/beautifulsoup_scraper.py, src/scrapers/playwright_scraper.py, src/mock_server.py, tests/test_session_expiry.py, README.md, .claude/skills/utar-verify/SKILL.md, docs/KNOWLEDGE.md |
| `69715db` | 2026-11-16 | Docs only: portal `notSupportTab` multi-tab check found by pasting addresses in new tab/window (Playwright, read-only) | docs/KNOWLEDGE.md |
| `845c266` | 2026-11-16 | Docs only: how the real portal session works (cookies, redirect chain, expired page) from read-only header probes | docs/KNOWLEDGE.md |
| `d659750` | 2026-11-16 | Docs only: real-portal session behaviour verified with read-only probes (one session per account, expired-page shape, tab vs window) and the session-expiry gaps found by the mock probe | docs/KNOWLEDGE.md |
| `6697b7a` | 2026-11-15 | Playwright wait times shortened (owner request): long 10 -> 3 s, short 3 -> 1 s, very short default 1 -> 0.5 s | config.ini, src/utils/config.py, docs/KNOWLEDGE.md |
| `4e08576` | 2026-11-15 | GitHub workflow: manual runs now also publish a permanent pre-release `build-<run number>` (before: only `v*` tags released; manual runs left an expiring artifact). Fails early when the exe or zip is missing; artifact holds only the zip; Node 22 set up explicitly; actions updated (checkout v4, setup-python v5, action-gh-release v2). `build_exe.py` exits 1 on a failed build (it always exited 0). README "Building and releases". Checked locally: YAML parse, packaging step dry run on a fake dist, unit tests + E2E. Proven on GitHub by tag `v1.4.0-beta` (run 12, success, zip attached); manual-run path not run yet | .github/workflows/build-and-release.yml, build_exe.py, README.md, docs/KNOWLEDGE.md |
| `673e911` | 2026-11-14 | Exe rebuilt from `6424c57` (temp build + copy, VS Code lock); checked with --test-real-server on the mock (bs/playwright, success and not-active) and a GUI launch; results in docs/run-report.md | docs/run-report.md, docs/KNOWLEDGE.md |
| `c1d5dd1` | 2026-11-13 | Adopted proven public skills after reading them: `systematic-debugging` (+ `root-cause-tracing.md`) and `verification-before-completion` from obra/superpowers (MIT; adapted cross-refs and examples to this repo, scripts not copied). CLAUDE.md: rules 6-7 and "Compact instructions" (official Claude Code guidance); utar-verify description in third person per skill-authoring guide | .claude/skills/systematic-debugging/*, .claude/skills/verification-before-completion/*, .claude/skills/utar-verify/SKILL.md, CLAUDE.md, docs/KNOWLEDGE.md |
| `039acdc` | 2026-11-13 | Skill `utar-verify` (test/build/verify routine). Mock runs: Playwright saves a screenshot + sanitised HTML of **every page it visits** whenever `UTAR_BASE_URL` is set (always on for the mock, even without `debug_dumps`); `UTAR_DEBUG_DIR` overrides the folder. E2E: each case gets `screenshots/<case>-app/` with the app browser's pages, linked in report.md. Unit/stress tests send captures to a temp dir. Change log converted to this commit table. | src/utils/diagnostics.py, src/scrapers/playwright_scraper.py, tests/e2e/run_e2e.py, tests/test_issue_fixes.py, tests/test_plan_runner.py, tests/stress/run_stress.py, .claude/skills/utar-verify/SKILL.md, CLAUDE.md, docs/KNOWLEDGE.md |
| `4339c08` | 2026-11-13 | `build_exe.py` keeps the user's dist `data/`, `logs/`, `config.ini` across rebuilds (copy in build/keep-user-files); run 2 report | build_exe.py, docs/run-report.md |
| `b2375b7` | 2026-11-13 | Playwright `save_page()` (screenshot + HTML) on debug for failed/refused logins, registered page, submit results; dumps mask student ID and `passid`; one shared OCR model, warmed up at app start | src/utils/diagnostics.py, src/utils/captcha_solver.py, src/web_backend.py |
| `8a93f2b` | 2026-11-13 | Real-portal logs: account refused via `login.jsp?message=notActive / notConsultAdviser` was misreported (BS "portal closed", Playwright "did not answer"). New `AccountNotAllowed` + `portal_rejection()`; login errors logged; mock scenarios `not-active` / `not-adviser`; UI login panel text; tests | src/scrapers/errors.py, src/scrapers/beautifulsoup_scraper.py, src/scrapers/playwright_scraper.py, src/mock_server.py, src/services/plan_runner.py, web/src/App.vue, tests/test_issue_fixes.py, tests/e2e/run_e2e.py, docs/KNOWLEDGE.md |
| `674f335` | 2026-11-13 | Smaller exe (231 → 221 MB): only OCR model files as data, no ddddocr, excludes tkinter + Pillow AVIF, copies config.ini; `tools/bundle_size.py`; README; issues.txt run report | build_exe.py, tools/bundle_size.py, README.md, docs/KNOWLEDGE.md, docs/run-report.md |
| `314d9bd` | 2026-11-13 | Tabbed UI (Courses, Login & settings, Pre-flight, Registration, Logs); run chip with phase/elapsed/countdown; Stopping status; toast queue; pre-flight steps; login error panel; password toggle; start now/at/after; drag-and-drop + import mode dialog; E2E +13 cases | web/src/App.vue, web/src/style.css, tests/e2e/run_e2e.py |
| `9d89b35` | 2026-11-13 | Saved login (DPAPI); Playwright browser path fix for the exe + install button; log level + sanitised debug dumps; Windows job-object process guard; `--test-real-server`; import preview/modes; default portal URLs fixed | src/utils/secret_store.py, src/utils/browser_setup.py, src/utils/diagnostics.py, src/utils/process_guard.py, src/utils/config.py, config.ini, src/web_backend.py, src/real_server_test.py, main.py, tests/test_issue_fixes.py |
| `a4d8f4d` | 2026-11-13 | Login retries with progress + typed errors (InvalidCredentials / PortalClosed / PortalUnavailable / BrowserMissing), stop after 2 "closed" answers, no nested relogin; runner status fields (steps, log, login, stopping, timers, error source/kind); pre-flight without a plan; scheduled start retries login while closed | src/scrapers/errors.py, src/scrapers/beautifulsoup_scraper.py, src/scrapers/playwright_scraper.py, src/services/plan_runner.py, tests/test_plan_runner.py |
| `05ed3a8` | 2026-11-13 | This knowledge map + `CLAUDE.md` | CLAUDE.md, docs/KNOWLEDGE.md |
| `bb2b1ed` | 2026-11-12 | Fix freeze when the portal expires the session right after login (RLock relogin guard, Stop safety net, mock `closed`, table layout) | src/scrapers/beautifulsoup_scraper.py, src/web_backend.py, src/mock_server.py, web/src/style.css, tests |
| `954460a` | 2026-11-12 | New icon, README for plans/verified status/retry/schedule | resources/icon.ico, README.md |
| `7623eff` | 2026-11-12 | Plans UI, verified status board, retry, schedule, pre-flight in the app | web/src/App.vue, web/src/style.css |
| `7c0b0f7` | 2026-11-12 | Plan runner backend: verified status, plan fallback, retry, schedule, pre-flight | src/services/plan_runner.py, src/scrapers/*, src/storage/database.py |
| `6fe40f2` | 2026-11-12 | BeautifulSoup cancel responsive (no read-timeout retries) | src/scrapers/beautifulsoup_scraper.py |
| `126dcd0` | 2026-11-12 | Stress-test harness | tests/stress/run_stress.py |
