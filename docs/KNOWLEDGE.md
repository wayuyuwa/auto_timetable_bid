# Codebase knowledge map

Living map of this repo so any person or agent can find what to edit quickly.
**Rule: whenever code, config, tests or behaviour change, update this file in the same commit** (map, "where to edit", flows and the change log at the bottom).

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
build_exe.py / build.bat        PyInstaller onedir build; bundles web/dist + OCR model files only (not all of src/)
tools/bundle_size.py            Size report of dist/UnitRegTimetable (largest folders/files)
config.ini                      Portal URLs, headers, Playwright waits, [Storage] db path,
                                [Logging] level (env UTAR_LOG_LEVEL overrides) and debug_dumps (env UTAR_DEBUG_DUMPS)
requirements.txt                Python deps (PyQt5 only for the legacy GUI)
.github/workflows/build-and-release.yml   Windows build on v* tags
.claude/settings.json           {"worktree":{"bgIsolation":"none"}} - agents edit in place

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
    errors.py                   LoginError -> InvalidCredentials / PortalClosed / PortalUnavailable; BrowserMissing
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
    diagnostics.py              Opt-in sanitised HTTP dumps + screenshots to logs/debug
    process_guard.py            Windows job object: children (Chromium, driver, WebView2) die with the app
    captcha_solver.py, ocr/     ONNX captcha OCR (common_old.onnx + charset)
  gui/                          LEGACY PyQt5 GUI (main_window, course_manager). Not used by main.py.
  mock_server.py                Local mock of the UTAR portal. Scenarios: success, register-fail, timeout,
                                session-expired, closed. Serves the real sample Kaptcha.jpg.

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

**Login errors (scrapers/errors.py → status.error_kind):** invalid_credentials (stop; UI blocks Start until the credentials change), portal_closed (login accepted, then "session expired" = registration not open), portal_unavailable (no/odd response), browser_missing (Playwright Chromium not installed). error_source "login" shows the panel in Login & settings.

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

- 2026-11-13 issues.txt run: tabbed UI, toast queue, pre-flight steps (works without a plan), Stopping status,
  elapsed timers, login retry progress + typed login errors + login error panel, scheduled start modes and
  closed-portal login retry, password toggle, drag-and-drop + import mode, saved credentials (DPAPI),
  diagnostics/log level, Playwright browser path fix + install button, process guard, `--test-real-server`,
  smaller bundle (no src/ copy). See docs/run-report.md.
- 2026-11-13: Added this knowledge map and `CLAUDE.md`.
- `bb2b1ed`: Fix freeze when portal expires session right after login (RLock relogin guard, Stop safety net, mock `closed` scenario, table layout).
- `954460a`: New icon, README for plans/verified status/retry/schedule.
- `7623eff`: Plans UI, verified status board, retry, schedule, preflight.
- `7c0b0f7`: Plan runner backend.
- `6fe40f2`: BS cancel responsive (no read-timeout retries).
- `126dcd0`: Stress harness.
