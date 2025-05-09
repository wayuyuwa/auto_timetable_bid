"""
Configuration loader for the UTAR Course Registration Scraper.
"""

import configparser
import os
from typing import Dict, List

def load_config() -> configparser.ConfigParser:
    """Load configuration from config.ini file."""
    config = configparser.ConfigParser()
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'config.ini')
    config.read(config_path)
    return config

# Load configuration
config = load_config()

# URLs
BASE_URL = config['URLs']['base_url']
LOGIN_URL = config['URLs']['login_url']
LOGIN_PROCESS_URL = config['URLs']['login_process_url']
REGISTRATION_URL = config['URLs']['registration_url']
HOME_URL = config['URLs']['home_url']
COURSE_REGISTRATION_URL = config['URLs']['course_registration_url']

# Headers
DEFAULT_HEADERS = {
    'User-Agent': config['Headers']['user_agent'],
    'Accept': config['Headers']['accept']
}

# Selenium Settings
SELENIUM_OPTIONS = config['Selenium']['options'].split(',')
WAIT_TIME_VELI_SHORT = float(config['Selenium']['wait_time_veli_short'])
WAIT_TIME_SHORT = float(config['Selenium']['wait_time_short'])
WAIT_TIME_LONG = float(config['Selenium']['wait_time_long'])

# GUI Settings
WINDOW_TITLE = config['GUI']['window_title']
WINDOW_SIZE = (
    int(config['GUI']['window_width']),
    int(config['GUI']['window_height'])
)
WINDOW_POSITION = (
    int(config['GUI']['window_x']),
    int(config['GUI']['window_y'])
)

# Logging
LOG_LEVEL = config['Logging']['level']
LOG_FORMAT = config['Logging']['format'] 