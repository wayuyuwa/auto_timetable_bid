# Codebase knowledge map

Living map of this repo so any person or agent can find what to edit quickly.
**Rule: whenever code, config, tests or behaviour change, update this file in the same commit** (map, "where to edit", flows and the change log at the bottom).

Last updated: 2026-11-13 (commit after `bb2b1ed`).

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
main.py                         Entry point: src.web_backend.run()
main2.py                        Standalone OCR timing demo (not used by the app)
build_exe.py / build.bat        PyInstaller onedir build; bundles web/dist, copies config.ini
config.ini                      Portal URLs, headers, Playwright waits, [Storage] db path, logging level
requirements.txt                Python deps (PyQt5 only for the legacy GUI)
.github/workflows/build-and-release.yml   Windows build on v* tags
.claude/settings.json           {"worktree":{"bgIsolation":"none"}} - agents edit in place

src/
  web_backend.py                DesktopApi (Vue bridge): plans CRUD, import, start/preflight/choose/cancel/get_status,
                                STOP_GRACE_SECONDS safety net (_release_if_stuck), window creation (run)
  services/
    plan_runner.py              PlanRunner (the engine): login, scheduled start, bid plans, verify against UTAR's
                                registered list, fallback A->B->C (auto/ask), retry loop, preflight checks.
                                StatusBoard + empty_status() = the status dict polled by the UI.
    bidding_service.py          LEGACY single-list service (used by legacy PyQt GUI only)
    worker_thread.py            LEGACY QThread worker (PyQt)
  scrapers/
    beautifulsoup_scraper.py    requests-based scraper: login (+captcha), relogin (RLock + _relogin_active guard),
                                register_courses, get_registered_courses, get_unit_slots, _submit_bidding
    playwright_scraper.py       Chromium scraper; all Playwright calls run on one _OwnerThread
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
    captcha_solver.py, ocr/     ONNX captcha OCR (common_old.onnx + charset)
  gui/                          LEGACY PyQt5 GUI (main_window, course_manager). Not used by main.py.
  mock_server.py                Local mock of the UTAR portal. Scenarios: success, register-fail, timeout,
                                session-expired, closed. Serves the real sample Kaptcha.jpg.

web/
  src/App.vue                   Whole UI: plan tabs, course table + dialogs, credentials/options, preflight list,
                                proposal (ask) dialog, progress board, "Confirmed by UTAR" board, toasts.
                                Polls get_status(); all backend calls go through callApi().
  src/style.css                 All styles (teal/green palette - no purple, no decorative emoji)
  src/main.js, index.html, vite.config.js, package.json

tests/
  test_plan_runner.py           Engine unit tests (runner, verification, fallback, freeze/relogin regressions)
  test_mock_server.py           Mock server tests
  test_utar_html_parser.py      Parser tests vs real saved pages; auto-skips if F:\utar is missing
  e2e/run_e2e.py                Playwright drives the built Vue UI with real DesktopApi + mock server
                                (--no-build, --only <id>, --headed, env E2E_WIDTH). Screenshots gitignored.
  e2e/fixtures/*.txt            Timetable import fixtures (exempt from *.txt ignore)
  stress/run_stress.py          Repeat/cancel/concurrency/soak harness (--quick, --no-playwright) -> report.md
```

Not tracked / ignore: `src-tauri/` (leftover from the `tauri-rust` branch), `dist/`, `build/`, `data/`, `logs/`, `*.txt` (except e2e fixtures; note `issues.txt` is ignored).

## Where to edit for common changes

| I want to change...                                | Edit                                                        |
|----------------------------------------------------|-------------------------------------------------------------|
| Any UI text, layout, dialogs, toasts               | `web/src/App.vue` (+ `web/src/style.css`), then `npm run build` in `web/` |
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

**Phases:** idle, login, scheduled, preflight, preflight_done, bidding, verifying, awaiting_choice, waiting_retry, complete, error, cancelled.

**Result labels:** Confirmed / Different group ("Needs a switch") / Not registered / Skipped / Submitted.

**Preflight:** `DesktopApi.preflight()` → `PlanRunner.preflight` → login + `_preflight_checks` (codes, groups, availability, clashes); never bids.

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
Last known: engine 24/24, E2E 39/39 (commit `bb2b1ed`).

## Known gaps / open items

- Group switch not automated (needs `changeClass.jsp` capture).
- Registered-list parsing based on Dec 2023 page snapshots; not checked on the live "...Survey.jsp" flow.
- BS submit check looks for `div.red`, real pages use `span.red` (alert-text detection partly covers it).
- `README.zh.md` is behind `README.md`.
- Packaged exe needs Playwright Chromium available for the Playwright method.

## Change log (newest first)

- 2026-11-13: Added this knowledge map and `CLAUDE.md`.
- `bb2b1ed`: Fix freeze when portal expires session right after login (RLock relogin guard, Stop safety net, mock `closed` scenario, table layout).
- `954460a`: New icon, README for plans/verified status/retry/schedule.
- `7623eff`: Plans UI, verified status board, retry, schedule, preflight.
- `7c0b0f7`: Plan runner backend.
- `6fe40f2`: BS cancel responsive (no read-timeout retries).
- `126dcd0`: Stress harness.
