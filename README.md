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
- **User-Friendly GUI**:
  - Modern PyQt5-based interface
  - Settings persistence
  - Progress feedback
  - Collapsible Playwright options
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

## Usage (For Learning Purposes)

1. Run the application:
```bash
python src/main.py
```

2. Configure settings:
  - Enter your student ID and password
  - Select BeautifulSoup or Playwright
   - Enter your UTAR credentials
   - (Optional) Select timetable file
  - (Optional) Configure Playwright options (headless mode)

3. Start scraping:
   - Click "Execute Scraping" to begin
   - Use "Stop" button to safely terminate the process
   - Monitor progress in the results display

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