"""
Logging configuration for the UTAR Course Registration Scraper.
"""

import logging
import logging.handlers
import os
import sys
import traceback
from .config import LOG_LEVEL, LOG_FORMAT, LOG_FILE, ERROR_LOG_FILE

def setup_logger(name: str) -> logging.Logger:
    """
    Set up a logger with file and console handlers.
    
    Args:
        name (str): Name of the logger
        
    Returns:
        logging.Logger: Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(LOG_LEVEL)
    
    # Create formatters
    formatter = logging.Formatter(LOG_FORMAT)
    
    # Create and configure file handler for all logs
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE,
        maxBytes=5*1024*1024,  # 5MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(LOG_LEVEL)
    
    # Create and configure error file handler
    error_handler = logging.handlers.RotatingFileHandler(
        ERROR_LOG_FILE,
        maxBytes=5*1024*1024,  # 5MB
        backupCount=5,
        encoding='utf-8'
    )
    error_handler.setFormatter(formatter)
    error_handler.setLevel(logging.ERROR)
    
    # Create and configure console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(LOG_LEVEL)
    # Add handlers to logger
    logger.addHandler(file_handler)
    logger.addHandler(error_handler)
    logger.addHandler(console_handler)
    
    return logger

def handle_uncaught_exception(exc_type, exc_value, exc_traceback):
    """
    Handle uncaught exceptions by logging them before the application crashes.
    
    Args:
        exc_type: Exception type
        exc_value: Exception value
        exc_traceback: Exception traceback
    """
    if issubclass(exc_type, KeyboardInterrupt):
        # Don't handle KeyboardInterrupt specially
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    
    # Get the logger
    crash_logger = logging.getLogger('crash_logger')
    
    # Format the exception info
    exception_info = ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    
    # Log the exception with the full traceback
    crash_logger.critical(f"APPLICATION CRASH DETECTED:\n{exception_info}")
    
    # Call the original exception hook
    sys.__excepthook__(exc_type, exc_value, exc_traceback)

def setup_crash_logging():
    """
    Set up crash logging by installing a global exception hook.
    This will catch and log all uncaught exceptions.
    """
    # Create a dedicated logger for crashes
    crash_logger = setup_logger('crash_logger')
    
    # Set up the global exception hook
    sys.excepthook = handle_uncaught_exception
    
    return crash_logger