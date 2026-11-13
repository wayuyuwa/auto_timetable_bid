---
name: utar-verify
description: Runs and checks this repo's tests and builds the proven way - unit tests, the E2E UI run against the mock UTAR portal, a mock portal by hand, the PyInstaller exe build (including when VS Code locks dist) and the --test-real-server check. Use after any code change here, before committing, or when asked to test, build, verify or check the app.
---

# Verify a change (UTAR course bidding app)

Read `docs/KNOWLEDGE.md` first for where things live. All commands run from the repo root with the venv Python. **Never contact the real UTAR server** except through `--test-real-server`, and only when the user asks for it.

## 1. Unit tests (≈40 s, mock only)
```
venv/Scripts/python -m unittest tests/test_issue_fixes.py tests/test_plan_runner.py tests/test_mock_server.py tests/test_utar_html_parser.py
```
- `test_utar_html_parser` skips itself when `F:\utar` (real saved pages) is missing. That is expected.
- New tests that need the mock: `from tests.test_plan_runner import SERVER, RunnerCase, course, plan` **first**. That import sets `UTAR_BASE_URL`, `UTAR_MOCK_CAPTCHA` and a temp `UTAR_DEBUG_DIR` before `src.utils.config` loads.
- `RunnerCase.setUp` resets mock state and the scenario. Plain `unittest.TestCase` classes do not, so set `SERVER.scenario = "success"` yourself.

## 2. E2E UI run (≈6–8 min; run in the background)
```
venv/Scripts/python tests/e2e/run_e2e.py            # builds web/ first
venv/Scripts/python tests/e2e/run_e2e.py --no-build --only pw_   # subset, reuse web/dist
```
- Output and report: `tests/e2e/screenshots/report.md` (gitignored). Playwright cases also get `<case>-app/` with what the app's own browser saw on every mock page.
- UI sections are tabs. In cases use `h.tab("Login & settings")`, `h.fill_credentials()` (switches tab), `h.import_file(path, mode)`, and `h.row(code)` (switches to Courses).
- Start opens the Registration tab, pre-flight opens Pre-flight, and a login error opens Login. Switch back before touching a control on another tab.
- Toasts: target a specific toast (`.toast` with has_text) and use the dismiss button inside it.

## 3. Mock portal by hand
```
venv/Scripts/python -m src.mock_server --port 8765 --scenario success
# scenarios: success register-fail timeout session-expired closed not-active not-adviser
$env:UTAR_BASE_URL = "http://127.0.0.1:8765/portal/courseRegStu"; venv/Scripts/python main.py
```
- When `UTAR_BASE_URL` is set, Playwright saves a screenshot and HTML of every page to `UTAR_DEBUG_DIR` or `logs/debug`.
- Stop a server you started by its PID or with TaskStop, never with a broad `taskkill`.

## 4. Real-portal smoke test (login + read only, never bids)
```
venv/Scripts/python main.py --test-real-server --student-id ID --prompt      # or --saved, or env UTAR_PASSWORD
dist/UnitRegTimetable/UnitRegTimetable.exe --test-real-server --saved        # report: dist/UnitRegTimetable/logs/real-server-test.txt
```
- Exit codes: 0 passed, 1 a stage failed, 2 usage problem.
- To exercise it without the real server, set `UTAR_BASE_URL` to a running mock.

## 5. Build the exe (only when the user asks)
```
venv/Scripts/python build_exe.py      # keeps dist data/, logs/, config.ini (copy in build/keep-user-files)
venv/Scripts/python tools/bundle_size.py
```
- If the clean step fails with `PermissionError ... vcruntime140.dll`, VS Code has the dist folder open. Do not close the user's editor. Instead, run PyInstaller with `--distpath/--workpath/--specpath` in a temp dir, using absolute `--add-data`/`--icon` paths, then copy files over. Skip byte-identical locked files, remove stale ones, and restore `data/`, `logs/` and `config.ini`.
- Check the exe: `--test-real-server` against a mock with `--method bs` and `--method playwright`. Then launch it and check the window title "UTAR Course Bidding" and that `logs/error.log` is empty.

## 6. Before committing
- Every test passes (unit + E2E). Push only then.
- Update `docs/KNOWLEDGE.md`: the map, "where to edit", and a change-log row (`(pending)` → fill in the hash in the next commit).
- Small focused commits on `develop`. No new branches, no worktrees.

## Editing tips that saved retries
- Write multi-line Python patch scripts with the Write tool into the job tmp dir and run them. Git Bash heredocs mangle `\\` escapes and quotes.
- Patch scripts must assert that each old string occurs exactly once. Some files have trailing spaces.
- Never print personal data (name, IC, student ID, password) from `dist/.../logs`. Mask digits (`sed -E 's/[0-9]{5,}/<num>/g'`) when showing logs.
