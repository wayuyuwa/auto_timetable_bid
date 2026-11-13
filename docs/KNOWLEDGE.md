# Codebase knowledge map

Living map of this repo so any person or agent can find what to edit quickly.
**Rule: whenever code, config, tests or behaviour change, update this file in the same commit** (map, "where to edit", flows and the change log at the bottom). Every change-log row names its commit hash and files.

Last updated: 2026-11-13 (issues.txt overnight run).

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
                                keeps the user's dist data/, logs/ and config.ini across rebuilds (build/keep-user-files)
tools/bundle_size.py            Size report of dist/UnitRegTimetable (largest folders/files)
config.ini                      Portal URLs, headers, Playwright waits, [Storage] db path,
                                [Logging] level (env UTAR_LOG_LEVEL overrides) and debug_dumps (env UTAR_DEBUG_DUMPS)
requirements.txt                Python deps (PyQt5 only for the legacy GUI)
.github/workflows/build-and-release.yml   Windows build on v* tags
.claude/settings.json           {"worktree":{"bgIsolation":"none"}} - agents edit in place
.claude/skills/utar-verify/     Skill: how to test/build/verify (commands, pitfalls, pre-commit checklist)

src/
  web_backend.py                DesktopApi (Vue bridge): plans CRUD, preview_import/import_courses(mode replace|new),
                                get/save_saved_credentials (DPAPI), browser_status/install_browser, open_logs_folder,
                                start/preflight/choose/cancel/get_status, STOP_GRACE_SECONDS safety net (_release_if_stuck).
                                run(): process guard + Playwright browser path + window + atexit cleanup
  real_server_test.py           `--test-real-server`: login -> student info -> registered list, never submits (exit 0/1/2)
  services/
    plan_runner.py              PlanRunner (the engine): login (+progress), scheduled start (login retry while the
                                portal looks closed), bid plans, verify against UTAR's registered list, fallback
                                A->B->C (auto/ask), retry loop, pre-flight steps (works without a plan).
                                StatusBoard + empty_status() = the status dict polled by the UI (incl. steps, log,
                                login attempts, stopping, started_at/ended_at, error_source/error_kind).
    bidding_service.py          LEGACY single-list service (used by legacy PyQt GUI only)
    worker_thread.py            LEGACY QThread worker (PyQt)
  scrapers/
    errors.py                   LoginError -> InvalidCredentials / AccountNotAllowed / PortalClosed / PortalUnavailable;
                                BrowserMissing; portal_rejection(code, text) maps login.jsp?message=<code> redirects
    beautifulsoup_scraper.py    requests-based scraper: login() loops _login_once() (progress callback, typed errors,
                                stops after 2 "closed" answers), relogin (RLock + _relogin_active guard; no nested
                                relogin inside login), register_courses, get_registered_courses, get_unit_slots
    playwright_scraper.py       Chromium scraper; all Playwright calls run on one _OwnerThread. login() retries
                                (typed errors), missing Chromium -> BrowserMissing, screenshots via diagnostics
    html_parser.py              Pure HTML parsing: student data, course values, home page,
                                parse_registered_courses, parse_unit_slots, parse_time_range, sessions_clash
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
| Saved data / schema                                | `src/storage/database.py`                                   |
| Timetable .txt import format                       | `src/utils/timetable_reader.py`; JSON import in `DesktopApi.import_courses` |
| Mock portal behaviour / new test scenario          | `src/mock_server.py` (+ `tests/test_mock_server.py`)        |
| Exe packaging                                      | `build_exe.py`                                              |
| Window title / size                                | `run()` in `src/web_backend.py`                             |
| App icon                                           | `resources/icon.ico`                                        |

## Key flows

**Run (Start):** App.vue `startRun()` → `DesktopApi.start()` → `_begin()` creates `StatusBoard` + `PlanRunner`, runs `PlanRunner.run` on a daemon thread → (optional `start_at`: logs in 60 s early, waits) → login → read registered list → skip already-registered → bid Plan A → verify against UTAR's registered list → missing courses fall back to next plan (`auto` adds non-clashing courses; `ask` sets phase `awaiting_choice` and waits for `DesktopApi.choose(codes)`) → retry every `auto_retry_seconds` up to `max_attempts` → `complete`/`error`/`cancelled`. UI polls `get_status()`.

**Phases:** idle, login, scheduled, preflight, preflight_done, bidding, verifying, awaiting_choice, waiting_retry, complete, error, cancelled. `stopping=True` (with running) means Stop was pressed and the run is finishing its current call.

**Login errors (scrapers/errors.py → status.error_kind):** invalid_credentials (stop; UI blocks Start until the credentials change), account_not_allowed (password accepted but UTAR refuses the account: the real portal redirects to `login.jsp?message=notActive` "study status is not allowed..." or `notConsultAdviser`; `loginError` = wrong ID/password; stop, no retry, shows UTAR's red text), portal_closed (login accepted, then "session expired" = registration not open), portal_unavailable (no/odd response), browser_missing (Playwright Chromium not installed). error_source "login" shows the panel in Login & settings.

**Scheduled start (task 16 decision):** log in `prelogin_seconds` (60) before the start; if the portal looks closed/unreachable keep retrying the *login only* every 10 s until 180 s after the start (logging in never bids); at the start, `_refresh_registered` re-logs in once if the session expired. Bids are never retried blindly: every pass re-reads the registered list first. UI modes: now / at clock time / after N minutes (counted from clicking Start).

**Result labels:** Confirmed / Different group ("Needs a switch") / Not registered / Skipped / Submitted.

**Preflight:** `DesktopApi.preflight()` → `PlanRunner.preflight` → steps login / registered / plans / clashes (state pending|running|ok|warn|error|skipped with timings); never bids. With no plan, the plan steps are "skipped" and login is still checked.

**Packaged exe and Playwright:** Playwright sets PLAYWRIGHT_BROWSERS_PATH=0 when frozen (looks inside the bundle). `browser_setup.configure_browsers_path()` points it at `%LOCALAPPDATA%\ms-playwright` instead; missing Chromium → BrowserMissing with an "Install browser" button (runs the bundled driver's `install chromium`).

**Stop:** `DesktopApi.cancel()` → runner cancel → scraper cancel; watchdog marks the run cancelled after `STOP_GRACE_SECONDS` (25 s) if the worker hangs. BS cancel floor ~10 s is deliberate (avoid double-submitting a bid).

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
venv\Scripts\python main.py --test-real-server --student-id ID --prompt   # REAL portal, login + read only
```
Last known: see docs/run-report.md (issues.txt run).
```

## Known gaps / open items

- Group switch not automated (needs `changeClass.jsp` capture).
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
