"""Settings manager backed by sqlite storage."""

import os
from typing import Optional, Dict, Any

from ..storage.database import Database, SettingsRepository

class Settings:
    """Settings manager for the application."""
    
    def __init__(self, settings_file: str = "user_settings.json"):
        """
        Initialize the settings manager.
        
        Args:
            settings_file (str): Path to the settings file
        """
        self.settings_file = settings_file
        self.database = Database()
        self.repo = SettingsRepository(self.database)
        self.repo.migrate_from_json(self.settings_file)
        self.settings = self._load_settings()
    
    def _load_settings(self) -> Dict[str, Any]:
        """
        Load settings from file.
        
        Returns:
            Dict[str, Any]: Settings dictionary
        """
        loaded = self.repo.load_settings()
        default = self._get_default_settings()
        default.update(loaded)
        return default
    
    def _get_default_settings(self) -> Dict[str, Any]:
        """
        Get default settings.
        
        Returns:
            Dict[str, Any]: Default settings dictionary
        """
        return {
            'student_id': '',
            'password': '',
            'method': 'Request',
            'headless_mode': False,
            'font_size': 13
        }
    
    def save_settings(self):
        """Save settings to file."""
        self.repo.save_settings(self.settings)
    
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
    
    def get_method(self) -> str:
        """
        Get last used scraping method.
        
        Returns:
            str: Last used method
        """
        return self.settings.get('method', 'Playwright')
    
    def get_headless_mode(self) -> bool:
        """
        Get headless mode setting.
        
        Returns:
            bool: Whether headless mode is enabled
        """
        return self.settings.get('headless_mode', False)
    
    def get_max_retries(self) -> int:
        """
        Get maximum number of retries for scraping.
        
        Returns:
            int: Maximum number of retries
        """
        return self.settings.get('max_retries', 3)

    def get_font_size(self) -> int:
        """Get configured UI font size."""
        return self.settings.get('font_size', 13)
    
    def update_settings(self, student_id: Optional[str] = None, 
                       password: Optional[str] = None,
                       method: Optional[str] = None,
                       headless_mode: Optional[bool] = None,
                       max_retries: Optional[int] = None,
                       font_size: Optional[int] = None,):
        """
        Update settings.
        
        Args:
            student_id (Optional[str]): Student ID to save
            password (Optional[str]): Password to save
            timetable_file (Optional[str]): Timetable file path to save
            method (Optional[str]): Last used method to save
            headless_mode (Optional[bool]): Whether to enable headless mode
            max_retries (Optional[int]): Maximum number of retries for scraping
            font_size (Optional[int]): UI font size in pixels
        """
        if student_id is not None:
            self.settings['student_id'] = student_id
        if password is not None:
            self.settings['password'] = password
        if method is not None:
            self.settings['method'] = method
        if headless_mode is not None:
            self.settings['headless_mode'] = headless_mode
        if max_retries is not None:
            self.settings['max_retries'] = max_retries
        if font_size is not None:
            self.settings['font_size'] = font_size
        self.save_settings() 