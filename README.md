# UTAR Course Registration Scraper

[English](README.md) | [中文](README.zh.md)

> **DISCLAIMER**: This project is created for **EDUCATIONAL PURPOSES ONLY**. It demonstrates web scraping, automation, and GUI development concepts. Users are responsible for ensuring their use of this tool complies with UTAR's terms of service and policies. The developers are not responsible for any misuse or consequences arising from the use of this tool.

An educational project demonstrating web scraping and automation techniques using Python. This project showcases:
- Web scraping with BeautifulSoup and Selenium
- GUI development with PyQt5
- CAPTCHA solving
- Automated browser interaction
- Configuration management
- Threading and asynchronous operations

## Features

- **Dual Scraping Methods**:
  - BeautifulSoup for lightweight scraping
  - Selenium for full browser automation with CAPTCHA handling
- **Automated Course Registration**:
  - Support for timetable-based course registration
  - Automatic slot selection based on preferences
  - Session management and auto-relogin
- **User-Friendly GUI**:
  - Modern PyQt5-based interface
  - Settings persistence
  - Progress feedback
  - Collapsible Selenium options
- **Additional Features**:
  - Secure credential storage
  - CAPTCHA solving using ddddocr
  - Headless mode support

## Requirements

- Python 3.8+
- PyQt5
- Selenium
- BeautifulSoup4
- ddddocr
- Firefox WebDriver (for Selenium)

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
```

4. Download Firefox WebDriver:
   - Visit [Mozilla GeckoDriver releases](https://github.com/mozilla/geckodriver/releases)
   - Download the appropriate version for your system
   - Add the driver to your system PATH

## Usage (For Learning Purposes)

1. Run the application:
```bash
python src/main.py
```

2. Configure settings:
   - Select scraping method (BeautifulSoup or Selenium)
   - Enter your UTAR credentials
   - (Optional) Select timetable file
   - (Optional) Configure Selenium options (headless mode)

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
│   ├── selenium_scraper.py
│   └── __init__.py
├── utils/
│   ├── captcha_solver.py   # CAPTCHA solving utility
│   ├── config.py          # Configuration loader
│   ├── settings.py        # Settings manager
│   ├── timetable_reader.py # Timetable parsing
│   └── __init__.py
└── main.py                # Application entry point
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