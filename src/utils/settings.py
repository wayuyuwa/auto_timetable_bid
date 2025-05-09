"""
Settings manager for the UTAR Course Registration Scraper.
"""

import json
import os
from typing import Optional, Dict, Any

class Settings:
    """Settings manager for the application."""
    
    def __init__(self, settings_file: str = "user_settings.json"):
        """
        Initialize the settings manager.
        
        Args:
            settings_file (str): Path to the settings file
        """
        self.settings_file = settings_file
        self.settings = self._load_settings()
    
    def _load_settings(self) -> Dict[str, Any]:
        """
        Load settings from file.
        
        Returns:
            Dict[str, Any]: Settings dictionary
        """
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                return self._get_default_settings()
        return self._get_default_settings()
    
    def _get_default_settings(self) -> Dict[str, Any]:
        """
        Get default settings.
        
        Returns:
            Dict[str, Any]: Default settings dictionary
        """
        return {
            'student_id': '',
            'password': '',
            'timetable_file': '',
            'last_method': 'Selenium',
            'headless_mode': False
        }
    
    def save_settings(self):
        """Save settings to file."""
        with open(self.settings_file, 'w') as f:
            json.dump(self.settings, f, indent=4)
    
    def get_student_id(self) -> str:
        """
        Get saved student ID.
        
        Returns:
            str: Student ID
        """
        return self.settings.get('student_id', '')
    
    def get_password(self) -> str:
        """
        Get saved password.
        
        Returns:
            str: Password
        """
        return self.settings.get('password', '')
    
    def get_timetable_file(self) -> str:
        """
        Get saved timetable file path.
        
        Returns:
            str: Timetable file path
        """
        return self.settings.get('timetable_file', '')
    
    def get_last_method(self) -> str:
        """
        Get last used scraping method.
        
        Returns:
            str: Last used method
        """
        return self.settings.get('last_method', 'Selenium')
    
    def get_headless_mode(self) -> bool:
        """
        Get headless mode setting.
        
        Returns:
            bool: Whether headless mode is enabled
        """
        return self.settings.get('headless_mode', False)
    
    def update_settings(self, student_id: Optional[str] = None, 
                       password: Optional[str] = None,
                       timetable_file: Optional[str] = None,
                       last_method: Optional[str] = None,
                       headless_mode: Optional[bool] = None):
        """
        Update settings.
        
        Args:
            student_id (Optional[str]): Student ID to save
            password (Optional[str]): Password to save
            timetable_file (Optional[str]): Timetable file path to save
            last_method (Optional[str]): Last used method to save
            headless_mode (Optional[bool]): Whether to enable headless mode
        """
        if student_id is not None:
            self.settings['student_id'] = student_id
        if password is not None:
            self.settings['password'] = password
        if timetable_file is not None:
            self.settings['timetable_file'] = timetable_file
        if last_method is not None:
            self.settings['last_method'] = last_method
        if headless_mode is not None:
            self.settings['headless_mode'] = headless_mode
        self.save_settings() 