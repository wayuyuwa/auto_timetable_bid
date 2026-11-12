# UTAR Course Registration Scraper

[English](README.md) | [中文](README.zh.md)

> **DISCLAIMER**: This project is created for **EDUCATIONAL PURPOSES ONLY**. It demonstrates web scraping, automation, and GUI development concepts. Users are responsible for ensuring their use of this tool complies with UTAR's terms of service and policies. The developers are not responsible for any misuse or consequences arising from the use of this tool.

An educational project demonstrating web scraping and automation techniques using Python. This project showcases:
- Web scraping with BeautifulSoup and Playwright
- GUI development with PyQt5
- CAPTCHA solving
- Automated browser interaction
- Configuration management
- Threading and asynchronous operations

## Features

- **Dual Scraping Methods**:
  - BeautifulSoup for lightweight scraping
  - Playwright for full browser automation with CAPTCHA handling
- **Automated Course Registration**:
  - Support for timetable-based course registration
  - Automatic slot selection based on preferences
  - Session management and auto-relogin
- **Timetable plans with fallback**:
  - Keep several full timetables (Plan A, Plan B, ...). Plans are tried in order
  - A later plan is used only for courses still missing, and only for classes
    that are free and do not clash with the timeslots already held
  - Fallback can run automatically or ask you what to bid first
- **Verified status**:
  - After each plan the app reads UTAR's own registered-courses page, so the
    result (Confirmed / Different group / Not registered) reflects what is
    really registered, not just the submit response
  - Shows registered classes, times, rooms and credit hours used
- **Retry, scheduling and pre-flight**:
  - Starting again retries only the courses that are still missing
  - Optional retry on a timer until a class frees up
  - Start at a set time: logs in shortly before and bids at the exact second
  - Pre-flight check: verifies login, course codes, groups, availability and
    clashes without registering anything
- **Desktop interface**:
  - Vue frontend shown in a pywebview window
  - Courses and plans stored in SQLite (`data/app.db`)
  - Live progress and per-course outcome
- **Additional Features**:
  - Secure credential storage
  - CAPTCHA solving using ddddocr
  - Headless mode support

## Requirements

- Python 3.8+
- Node.js 18+ and npm (to build the Vue frontend)
- PyQt5
- pywebview
- Playwright and Chromium
- BeautifulSoup4
- ddddocr

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/utar-course-registration-scraper.git
cd utar-course-registration-scraper
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
cd web
npm install
npm run build
cd ..
```

4. Install the Playwright browser:
```bash
python -m playwright install chromium
```

## Mock server integration testing

Run the local UTAR-compatible mock server in one terminal:

```powershell
python -m src.mock_server --scenario success
```

In a second terminal, point the app to it. The CAPTCHA override avoids loading OCR during this test:

```powershell
$env:UTAR_BASE_URL = "http://127.0.0.1:8765/portal/courseRegStu"
$env:UTAR_MOCK_CAPTCHA = "mock"
python main.py
```

Use a different scenario when starting the mock server:

```powershell
python -m src.mock_server --scenario register-fail
python -m src.mock_server --scenario timeout --delay 15
python -m src.mock_server --scenario session-expired
```

Unset `UTAR_BASE_URL` and `UTAR_MOCK_CAPTCHA` to return to the real UTAR endpoints. The mock server is local-only and does not contact UTAR.

The mock keeps state like the real portal: it records registrations, renders the
registered-courses page and the unit slot table in the real layout, treats slots
as full or clashing, and returns the portal's real clash message.

### Automated tests

All tests run against the mock server; none contact UTAR.

```powershell
# Engine tests: verification, plan fallback, retry, schedule, pre-flight, parsers
venv\Scripts\python -m unittest tests/test_plan_runner.py

# End-to-end UI run with one screenshot per case (tests/e2e/screenshots/, gitignored)
venv\Scripts\python tests\e2e\run_e2e.py

# Stress test: repeat + cancel cycles, concurrent load, soak (tests/stress/report.md)
venv\Scripts\python tests\stress\run_stress.py --quick
```

### Known limitation: switching groups

UTAR lets you move a registered course to another group without dropping it
(the edit icon on the registered-courses page, `changeClass.jsp`). The app
detects when a later plan would need this and reports it, but does not perform
the switch yet.

## Usage (For Learning Purposes)

1. Run the application:
```bash
python main.py
```

2. Set up:
   - Enter your student ID and password
   - Select BeautifulSoup or Playwright
   - Add courses to Plan A, or import a timetable `.txt` / `.json`
   - (Optional) Add backup plans with "Add plan"
   - (Optional) Choose what happens when a plan cannot be completed, turn on
     "Retry until registered", or set a start time

3. Check and run:
   - "Run pre-flight check" confirms everything is ready without registering
   - "Start registration" bids the plans in order
   - "Stop safely" ends the run
   - The "Confirmed by UTAR" panel shows what is really registered; if anything
     is missing, the button becomes "Retry missing courses"

## Configuration

The application uses several configuration files:

- `config.ini`: Main configuration file for URLs, timeouts, and other settings
- `user_settings.json`: User-specific settings (credentials, preferences)
- `.gitignore`: Configured to exclude sensitive files

## Project Structure

```
src/
├── gui/
│   ├── main_window.py      # Main GUI implementation
│   └── __init__.py
├── scrapers/
│   ├── beautifulsoup_scraper.py
│   ├── playwright_scraper.py
│   ├── html_parser.py
│   └── __init__.py
├── utils/
│   ├── captcha_solver.py   # CAPTCHA solving utility
│   ├── config.py          # Configuration loader
│   ├── settings.py        # Settings manager
│   ├── timetable_reader.py # Timetable parsing
│   └── __init__.py
└── main.py                # Application entry point

web/
├── src/                    # Vue frontend
└── dist/                   # Production bundle loaded by pywebview
```

## Security Notes

- Credentials are stored locally in `user_settings.json`
- This file is excluded from git via `.gitignore`
- Consider using environment variables for sensitive data in production

## Educational Value

This project serves as a learning resource for:
- Web scraping techniques
- Browser automation
- GUI development
- Threading and asynchronous programming
- Configuration management
- Security best practices
- Error handling and logging

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.