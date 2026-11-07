"""
Base scraper abstract class defining the common interface for all scrapers.
"""

from abc import ABC, abstractmethod
from typing import List, Tuple, Optional
from ..models.course import Course
from ..models.bid_result import BidResult


class BaseScraper(ABC):
    """Abstract base class for all scraper implementations."""
    
    def __init__(self):
        """Initialize the base scraper."""
        self._is_logged_in = False
        self._is_cancelled = False
    
    @abstractmethod
    def login(self, student_id: str, password: str) -> bool:
        """
        Login to the course registration system.
        
        Args:
            student_id: Student ID
            password: Password
            
        Returns:
            bool: True if login successful, False otherwise
        """
        pass
    
    @abstractmethod
    def register_courses(self, courses: List[Course]) -> Tuple[str, bool]:
        """
        Register for multiple courses.
        
        Args:
            courses: List of Course objects to register
            
        Returns:
            Tuple[str, bool]: (result message, success status)
        """
        pass
    
    @abstractmethod
    def get_home_page_data(self) -> Optional[dict]:
        """
        Get data from the home page.
        
        Returns:
            Optional[dict]: Dictionary containing home page data, or None if failed
        """
        pass
    
    def cancel(self):
        """Cancel ongoing operations."""
        self._is_cancelled = True
    
    def reset_cancellation(self):
        """Reset the cancellation flag."""
        self._is_cancelled = False
    
    def is_logged_in(self) -> bool:
        """Check if currently logged in."""
        return self._is_logged_in
    
    def is_cancelled(self) -> bool:
        """Check if operation has been cancelled."""
        return self._is_cancelled
    
    @abstractmethod
    def cleanup(self):
        """Clean up resources (e.g., close browser, session)."""
        pass
