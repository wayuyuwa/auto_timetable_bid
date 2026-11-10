"""
Bidding service layer - handles all bidding operations with proper signal/slot architecture.
"""

from threading import Event
from typing import List, Optional
from ..models.course import Course
from ..models.bid_result import BidResult, BidStatus
from ..scrapers.beautifulsoup_scraper import BeautifulSoupScraper
from ..scrapers.playwright_scraper import PlaywrightScraper
from ..utils.logger import setup_logger
from ..utils.signals import Signal

logger = setup_logger(__name__)


class BiddingService:
    """Service layer for handling bidding operations."""

    def __init__(self):
        """Initialize the bidding service."""
        # Signals (slots run on the emitting worker thread)
        self.login_progress = Signal()  # message
        self.login_completed = Signal()  # success, message

        self.bid_started = Signal()  # total courses
        self.bid_progress = Signal()  # message, current, total
        self.bid_course_completed = Signal()  # BidResult
        self.bid_all_completed = Signal()  # overall success, list of BidResult

        self.session_expired = Signal()
        self.network_error = Signal()
        self.operation_cancelled = Signal()

        self._scraper: Optional[BeautifulSoupScraper | PlaywrightScraper] = None
        self._is_running = False
        self._cancel_requested = Event()
        self._scraper_type = "BeautifulSoup"
        self._headless_mode = False
        logger.info("BiddingService initialized")

    def set_headless_mode(self, enabled: bool):
        """Set browser headless mode for the next Playwright scraper."""
        self._headless_mode = enabled
        if isinstance(self._scraper, PlaywrightScraper):
            self._scraper.set_headless_mode(enabled)
    
    def set_scraper_type(self, scraper_type: str):
        """
        Set the scraper type to use.
        
        Args:
            scraper_type: "BeautifulSoup" or "Playwright"
        """
        self._scraper_type = scraper_type
        logger.info(f"Scraper type set to: {scraper_type}")
    
    def _initialize_scraper(self):
        """Initialize the scraper based on the selected type."""
        if self._scraper:
            try:
                self._scraper.cleanup()
            except Exception as e:
                logger.error(f"Error cleaning up previous scraper: {e}")
        
        if self._scraper_type == "BeautifulSoup":
            self._scraper = BeautifulSoupScraper()
        else:
            self._scraper = PlaywrightScraper()
            self._scraper.set_headless_mode(self._headless_mode)
        
        logger.info(f"Initialized {self._scraper_type} scraper")
    
    def login(self, student_id: str, password: str):
        """
        Perform login operation.
        
        Args:
            student_id: Student ID
            password: Password
        """
        try:
            self._is_running = True
            self._initialize_scraper()
            
            self.login_progress.emit("Connecting to UTAR course registration system...")
            
            if self._scraper:
                self._scraper.reset_cancellation()
                success = self._scraper.login(student_id, password)
                
                if success:
                    self.login_completed.emit(True, "Login successful!")
                    logger.info("Login successful")
                else:
                    self.login_completed.emit(False, "Login failed. Please check your credentials.")
                    logger.warning("Login failed")
            else:
                self.login_completed.emit(False, "Failed to initialize scraper")
                logger.error("Scraper initialization failed")
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Login error: {error_msg}")
            
            if "cancelled" in error_msg.lower():
                self.operation_cancelled.emit()
            else:
                self.login_completed.emit(False, f"Login error: {error_msg}")
        finally:
            self._is_running = False
    
    def bid_courses(self, courses: List[Course]):
        """
        Bid for multiple courses.
        
        Args:
            courses: List of Course objects to bid for
        """
        try:
            self._is_running = True

            if self._was_cancelled():
                logger.info("Bidding not started: cancellation was requested")
                self.operation_cancelled.emit()
                return

            if not self._scraper or not self._scraper.is_logged_in():
                self.bid_all_completed.emit(False, [])
                logger.error("Not logged in - cannot bid courses")
                return
            
            total = len(courses)
            self.bid_started.emit(total)
            logger.info(f"Starting to bid {total} courses")
            
            results = []
            
            for i, course in enumerate(courses):
                if self._was_cancelled():
                    logger.info("Bidding cancelled by user")
                    self.operation_cancelled.emit()
                    return  # a cancelled run must not also report completion
                
                current = i + 1
                self.bid_progress.emit(
                    f"Bidding {course.code} - {course.name}",
                    current,
                    total
                )
                
                # Perform the actual bidding through the scraper
                try:
                    result_text, success = self._scraper.register_courses([course])

                    if not success and self._was_cancelled():
                        # Unsuccessful because the user stopped mid-request (e.g. the
                        # Playwright scraper returns a timeout result instead of raising).
                        logger.info(f"Bidding cancelled by user during {course.code}")
                        self.operation_cancelled.emit()
                        return

                    # Create result object
                    if success:
                        status = BidStatus.SUCCESS
                        message = "Successfully registered"
                    else:
                        status = BidStatus.FAILED
                        message = result_text
                    
                    result = BidResult(
                        course_code=course.code,
                        course_name=course.name,
                        status=status,
                        message=message
                    )
                    
                    results.append(result)
                    self.bid_course_completed.emit(result)
                    logger.info(f"Course {course.code}: {status.value}")
                    
                except Exception as course_error:
                    if self._was_cancelled():
                        # The scraper aborted this course because the user pressed stop.
                        logger.info(f"Bidding cancelled by user during {course.code}")
                        self.operation_cancelled.emit()
                        return
                    logger.error(f"Error bidding {course.code}: {course_error}")
                    result = BidResult(
                        course_code=course.code,
                        course_name=course.name,
                        status=BidStatus.FAILED,
                        message=str(course_error),
                        error_details=str(course_error)
                    )
                    results.append(result)
                    self.bid_course_completed.emit(result)
            
            # Emit completion signal
            overall_success = all(r.is_successful() for r in results)
            self.bid_all_completed.emit(overall_success, results)
            logger.info(f"Bidding completed. Success: {overall_success}")
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Bidding error: {error_msg}")
            
            if "session" in error_msg.lower() and "expired" in error_msg.lower():
                self.session_expired.emit()
            elif "cancelled" in error_msg.lower():
                self.operation_cancelled.emit()
            else:
                self.network_error.emit(error_msg)
                self.bid_all_completed.emit(False, [])
        finally:
            self._is_running = False
    
    def cancel(self):
        """Cancel ongoing operations."""
        logger.info("Cancellation requested")
        self._cancel_requested.set()
        self._is_running = False
        if self._scraper:
            self._scraper.cancel()

    def _was_cancelled(self) -> bool:
        return self._cancel_requested.is_set() or bool(self._scraper and self._scraper.is_cancelled())

    def reset_cancellation(self):
        """Clear cancellation state before starting a new operation."""
        self._cancel_requested.clear()
        if self._scraper:
            self._scraper.reset_cancellation()
    
    def cleanup(self):
        """Clean up resources."""
        logger.info("Cleaning up bidding service")
        self._is_running = False
        if self._scraper:
            try:
                self._scraper.cleanup()
            except Exception as e:
                logger.error(f"Error during cleanup: {e}")
            finally:
                self._scraper = None
    
    def get_home_page_data(self):
        """
        Get home page data from the scraper.
        
        Returns:
            dict: Home page data or None
        """
        if self._scraper and self._scraper.is_logged_in():
            try:
                return self._scraper.get_home_page_data()
            except Exception as e:
                logger.error(f"Error getting home page data: {e}")
                return None
        return None
