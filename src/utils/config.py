"""
Configuration loader for the UTAR Course Registration Scraper.
"""

import configparser
import os
import sys
import logging
from typing import Dict, List

# Configure logging
logger = logging.getLogger(__name__)

def load_config() -> configparser.ConfigParser:
    """Load configuration from config.ini file."""
    config = configparser.ConfigParser()
    
    # Try to find config.ini in different locations
    possible_locations = [
        # Current working directory (where the app is started from)
        os.path.join(os.getcwd(), 'config.ini'),
        # Executable directory (for packaged app)
        os.path.join(os.path.dirname(sys.executable), 'config.ini'),
        # Fallback to the traditional location
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'config.ini')
    ]
    
    config_path = None
    for location in possible_locations:
        if os.path.exists(location):
            config_path = location
            break
    
    # Check if config.ini exists
    if not config_path:
        logger.warning(f"Configuration file not found in any of the possible locations")
        logger.warning("Using default configuration values")
        # Create a default config object
        return create_default_config()
    
    logger.info(f"Loading configuration from: {config_path}")
    config.read(config_path)
    return config

def create_default_config() -> configparser.ConfigParser:
    """Create a default configuration when config.ini is missing."""
    config = configparser.ConfigParser()
    
    # Default URLs
    config['URLs'] = {
        'base_url': 'https://unitreg.utar.edu.my',
        'login_url': 'https://unitreg.utar.edu.my/portal/courseRegStu/login.jsp',
        'login_process_url': 'https://unitreg.utar.edu.my/portal/courseRegStu/login_proc.jsp',
        'registration_url': 'https://unitreg.utar.edu.my/portal/courseRegStu/registration/registerUnitSurvey.jsp',
        'home_url': 'https://unitreg.utar.edu.my/portal/courseRegStu/mainpage.jsp',
        'course_registration_url': 'https://unitreg.utar.edu.my/portal/courseRegStu/registration/registerCourse.jsp'
    }
    
    # Default Headers
    config['Headers'] = {
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9'
    }
    
    # Default Selenium Settings
    config['Selenium'] = {
        'options': 'disable-gpu,no-sandbox,disable-dev-shm-usage',
        'wait_time_very_short': '1',
        'wait_time_short': '3',
        'wait_time_long': '10'
    }
    
    # Default GUI Settings
    config['GUI'] = {
        'window_title': 'UTAR Course Registration Scraper',
        'window_width': '800',
        'window_height': '600',
        'window_x': '100',
        'window_y': '100'
    }
      # Default Logging Settings
    config['Logging'] = {
        'level': 'INFO',
        'format': '%%(asctime)s - %%(name)s - %%(levelname)s - %%(message)s'
    }
    
    return config

# Load configuration
config = load_config()

# URLs
BASE_URL = config['URLs']['base_url']
LOGIN_URL = config['URLs']['login_url']
LOGIN_PROCESS_URL = config['URLs']['login_process_url'] # Route for login form post method
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
WAIT_TIME_VERY_SHORT = float(config['Selenium']['wait_time_very_short'])
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

# Determine the base directory for logs
if getattr(sys, 'frozen', False):
    # Running as a bundled executable
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # Running as a script
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

LOG_DIR = os.path.join(BASE_DIR, 'logs')
LOG_FILE = os.path.join(LOG_DIR, 'scraper.log')
ERROR_LOG_FILE = os.path.join(LOG_DIR, 'error.log')

# Create logs directory if it doesn't exist
os.makedirs(LOG_DIR, exist_ok=True)