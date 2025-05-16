"""
Selenium implementation for scraping UTAR course registration data.
"""

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.alert import Alert
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, UnexpectedAlertPresentException, WebDriverException
import json
import threading
import time
from time import sleep
from threading import Event
from ..utils.config import (
    LOGIN_URL, LOGIN_PROCESS_URL, REGISTRATION_URL,
    HOME_URL, COURSE_REGISTRATION_URL, SELENIUM_OPTIONS,
    WAIT_TIME_VERY_SHORT, WAIT_TIME_SHORT, WAIT_TIME_LONG
)
from ..utils.captcha_solver import CaptchaSolver
from ..utils.timetable_reader import Course
from ..utils.logger import setup_logger

# Configure logging
logger = setup_logger(__name__)

class SeleniumScraper:
    """Scraper implementation using Selenium."""
    
    def __init__(self):
        """Initialize the scraper with Chrome options."""
        self.options = Options()
        for option in SELENIUM_OPTIONS:
            self.options.add_argument(option)
        self.driver = None
        self.captcha_solver = CaptchaSolver()
        self.student_id = None
        self.password = None
        self._is_cleaning_up = False
        self._headless_mode = False
        self._cancellation_token = Event()
        logger.info("SeleniumScraper initialized")

    def cancel(self):
        """Set the cancellation token to stop ongoing operations."""
        self._cancellation_token.set()
        logger.info("Cancellation requested")
        
        # Force interrupt any running operations by starting cleanup in a separate thread
        if self.driver and not self._is_cleaning_up:
            # Start a watchdog thread to force quit if cleanup takes too long
            watchdog_thread = threading.Thread(
                target=self._force_quit_watchdog,
                daemon=True
            )
            watchdog_thread.start()

    def _force_quit_watchdog(self):
        """Watchdog that force quits the driver if cleanup is taking too long."""
        # Wait a short time for normal cleanup
        wait_time = 5  # seconds
        start_time = time.time()
        
        while time.time() - start_time < wait_time:
            if not self.driver:  # Driver already cleaned up
                return
            time.sleep(0.5)
            
        logger.warning("Cleanup taking too long, force quitting WebDriver")
        # If we reach here, cleanup is taking too long, force quit the driver
        try:
            if self.driver:
                # Keep a reference to avoid issues if driver gets nulled
                driver_ref = self.driver
                try:
                    driver_ref.quit()
                except Exception as e:
                    logger.error(f"Error during force quit: {str(e)}")
                finally:
                    self.driver = None
        except Exception as e:
            logger.error(f"Error during force driver quit: {str(e)}")

    def reset_cancellation(self):
        """Reset the cancellation token."""
        self._cancellation_token.clear()

    def _check_cancellation(self):
        """Check if operation has been cancelled."""
        if self._cancellation_token.is_set():
            raise Exception("Operation cancelled by user")

    def set_headless_mode(self, enabled: bool):
        """
        Set headless mode.
        
        Args:
            enabled (bool): Whether to enable headless mode
        """
        self._headless_mode = enabled
        if self.driver:
            logger.warning("Headless mode change will take effect on next initialization")

    def _initialize_driver(self):
        """Initialize the Chrome WebDriver if not already initialized."""
        if self._is_cleaning_up:
            raise WebDriverException("WebDriver is being cleaned up")
            
        if self.driver is None:
            options = webdriver.ChromeOptions()
            for option in SELENIUM_OPTIONS:
                options.add_argument(option)
            if self._headless_mode:
                options.add_argument('--headless')
            self.driver = webdriver.Chrome(options=options)
            self.driver.set_window_size(1920, 1080)

    def _wait_for_element(self, by: By, value: str, timeout: int = WAIT_TIME_SHORT):
        """Wait for an element to be present on the page."""
        if not self.driver or self._is_cleaning_up:
            raise WebDriverException("WebDriver is not initialized or is being cleaned up")
        
        # Create a wait with more frequent checks for cancellation
        wait = WebDriverWait(self.driver, timeout, poll_frequency=0.5)
        
        # Define a custom condition that checks for cancellation
        def element_present_with_cancellation_check(driver):
            self._check_cancellation()
            element = driver.find_element(by, value)
            return element if element else False
        
        # Use the custom condition
        try:
            return wait.until(element_present_with_cancellation_check)
        except Exception as e:
            # Check if cancellation was requested
            self._check_cancellation()
            # If not, re-raise the original exception
            raise e

    def session_expired(self) -> bool:
        """Check if the session has expired."""
        if not self.driver or self._is_cleaning_up:
            return True
        try:
            return bool(self.driver.find_elements(By.XPATH, "//*[contains(text(), 'Session Expired')]"))
        except WebDriverException:
            return True

    def login(self, student_id: str, password: str) -> bool:
        """
        Handle the login process including CAPTCHA.
        
        Args:
            student_id (str): Student ID for login
            password (str): Password for login
            
        Returns:
            bool: True if login successful
        """
        if not student_id or not password:
            raise Exception("Student ID or password is not set!")

        if self._is_cleaning_up:
            raise WebDriverException("WebDriver is being cleaned up")

        self.student_id = student_id
        self.password = password

        logger.info("Trying to login...")
        self._initialize_driver()
        
        try:
            self._check_cancellation()
            self.driver.get(LOGIN_URL)
        except WebDriverException as e:
            logger.error(f"Failed to navigate to login page: {str(e)}")
            return False

        try:
            # Wait for the login form
            self._check_cancellation()
            self._wait_for_element(By.CSS_SELECTOR, "form[name=frmParam]")
        except (TimeoutException, WebDriverException):
            if self.driver:
                self.driver.refresh()
            return False

        try:
            # Locate input fields
            student_id_input = self.driver.find_element(By.CSS_SELECTOR, "input[name=reqFregkey]")
            password_input = self.driver.find_element(By.CSS_SELECTOR, "input[name=reqPassword]")
            kaptcha_input = self.driver.find_element(By.CSS_SELECTOR, "input[name=kaptchafield]")
        except (NoSuchElementException, WebDriverException):
            logger.error("Element not found")
            return False

        try:
            # Get CAPTCHA image
            kaptcha_img = self.driver.find_element(
                By.XPATH, "//input[@name='kaptchafield']/../img[1]"
            ).screenshot_as_png
        except (NoSuchElementException, WebDriverException):
            logger.error("Kaptcha not found")
            return False

        # Solve CAPTCHA
        kaptcha_pass = self.captcha_solver.solve(kaptcha_img)
        logger.info(f"Solved CAPTCHA: {kaptcha_pass}")

        try:
            # Enter credentials and submit
            student_id_input.send_keys(student_id)
            password_input.send_keys(password)
            kaptcha_input.send_keys(kaptcha_pass)
            kaptcha_input.send_keys(Keys.RETURN)
            
            # Check login success
            self._wait_for_element(
                By.XPATH, "//span[contains(text(), 'Log Out')]",
                timeout=WAIT_TIME_VERY_SHORT
            )
        except (TimeoutException, WebDriverException):
            try:
                if self.driver:
                    alert = self.driver.find_element(By.CLASS_NAME, "red").text
                    if "Invalid Student ID or Password" in alert:
                        raise Exception("Your student ID or password is invalid")
            except:
                pass
            return False

        logger.info("Login successful!")
        return True

    def store_cookies(self):
        """Store cookies to a file."""
        if not self.driver or self._is_cleaning_up:
            return
        try:
            cookies = self.driver.get_cookies()
            with open("cookies.txt", "w+") as file:
                json.dump(cookies, file)
                logger.info("Cookies saved")
        except WebDriverException:
            logger.error("Failed to store cookies")

    def register_course(self, course: Course) -> bool:
        """
        Register for a course.
        
        Args:
            course (Course): Course to register for
            
        Returns:
            bool: True if registration successful
        """
        if not self.driver or self._is_cleaning_up:
            return False

        try:
            self._check_cancellation()
            self.driver.get(COURSE_REGISTRATION_URL)
        except WebDriverException:
            return False

        try:
            self._check_cancellation()
            self._wait_for_element(By.CSS_SELECTOR, "table#tblGrid")
        except (TimeoutException, WebDriverException):
            if self.session_expired():
                self.login(self.student_id, self.password)
            return False

        try:
            course_input = self.driver.find_element(By.CSS_SELECTOR, "input#reqUnit[name=reqUnit]")
        except (NoSuchElementException, WebDriverException):
            logger.error("Element not found in register course...")
            return False

        logger.info(f"Registering course {course.code} - {course.name}...")
        try:
            self._check_cancellation()
            course_input.send_keys(course.code)
            course_input.send_keys(Keys.RETURN)
        except WebDriverException:
            return False

        try:
            self._check_cancellation()
            self._wait_for_element(By.CSS_SELECTOR, "form[name=frmSummary]")
        except (TimeoutException, WebDriverException):
            if self.driver:
                self.driver.refresh()
            return False

        try:
            timetable = self.driver.find_elements(By.CSS_SELECTOR, "form[name=frmSummary] tr:nth-child(n+3):has(input)")
            submit_btn = timetable.pop().find_element(By.CSS_SELECTOR, "input[name=Submit]")
        except (NoSuchElementException, IndexError, WebDriverException):
            logger.error("No timetable found")
            return False

        max_slots = len(course.slots)
        slot_priority = {"L": 99, "T": 99, "P": 99}
        selected_checkboxes = {"L": None, "T": None, "P": None}

        for row in timetable:
            self._check_cancellation()
            try:
                class_type = row.find_element(By.CSS_SELECTOR, "td:nth-child(2)").text
                class_slot = int(row.find_element(By.CSS_SELECTOR, "td:nth-child(3)").text)
            except (NoSuchElementException, WebDriverException):
                logger.error("Element not found in register course...")
                return False

            class_slots = course.slots.get(class_type)
            if class_slots and class_slot in class_slots:
                current_slot_priority = class_slots.index(class_slot)

                if current_slot_priority > slot_priority[class_type]:
                    continue

                try:
                    checkbox = row.find_element(By.CSS_SELECTOR, "input[type=checkbox]")
                except (NoSuchElementException, WebDriverException):
                    logger.error("Slot not available!")
                else:
                    if slot_priority[class_type] == 99:
                        max_slots -= 1
                    else:
                        try:
                            selected_checkboxes[class_type].click()
                        except WebDriverException:
                            pass

                    try:
                        checkbox.click()
                        selected_checkboxes[class_type] = checkbox
                        slot_priority[class_type] = current_slot_priority
                    except WebDriverException:
                        pass

        if max_slots > 0:
            logger.error("No available slots!")
            try:
                self.driver.get(REGISTRATION_URL)
            except WebDriverException:
                pass
            return True

        try:
            self._check_cancellation()
            submit_btn.click()
        except WebDriverException:
            return False
            
        try:
            # Using a shorter timeout with check_cancellation
            wait = WebDriverWait(self.driver, WAIT_TIME_VERY_SHORT, poll_frequency=0.2)
            
            def alert_present_with_cancellation_check(driver):
                self._check_cancellation()
                try:
                    alert = driver.switch_to.alert
                    return alert
                except:
                    return False
            
            alert = wait.until(alert_present_with_cancellation_check)
        except (TimeoutException, WebDriverException):
            logger.info("Registered!")
            return True
        except Exception:
            # Check if cancelled
            self._check_cancellation()
            return True

        try:
            alert = Alert(self.driver)
            if "please select a valid class combination" in alert.text:
                logger.error("Something went wrong when selecting...")
                return False
            elif "the time of selected units are clashed" in alert.text:
                logger.error("Invalid timetable! Please check again!")
                return True
            elif "exceeded the maximum number of credit hours" in alert.text:
                logger.error("Maximum credit hours reached!")
                return True
        except WebDriverException:
            return False

        return True

    def register_courses(self, courses: list[Course]) -> bool:
        """
        Register multiple courses from a timetable file.
        
        Args:
            courses (list[Course]): List of courses to register
            
        Returns:
            bool: True if all registrations successful
        """
        if not self.driver or self._is_cleaning_up:
            return False
        
        try:
            self._check_cancellation()
            self.driver.get(REGISTRATION_URL)
        except WebDriverException:
            return False

        try:
            self._check_cancellation()
            self._wait_for_element(By.CSS_SELECTOR, "table#tblGrid")
        except (TimeoutException, WebDriverException):
            if self.session_expired():
                self.login(self.student_id, self.password)
            return False

        for course in courses:
            self._check_cancellation()
            if self._is_cleaning_up:
                return False

            loop = True
            while loop and not self._is_cleaning_up:
                self._check_cancellation()
                try:
                    self._wait_for_element(
                        By.CSS_SELECTOR, "input[name=Register]",
                        timeout=WAIT_TIME_VERY_SHORT
                    )
                except (TimeoutException, WebDriverException):
                    logger.info("Registration is not open yet!")
                    logger.info("Trying to relogin...")
                    while not self.login(self.student_id, self.password) and not self._is_cleaning_up:
                        self._check_cancellation()
                        logger.info("Can't login, retrying...")
                    if not self._is_cleaning_up:
                        try:
                            self.driver.get(REGISTRATION_URL)
                        except WebDriverException:
                            return False
                except UnexpectedAlertPresentException:
                    logger.error("Unexpected alert present!")
                    continue

                try:
                    self._check_cancellation()
                    register_btn = self.driver.find_element(By.CSS_SELECTOR, "input[name=Register]")
                except (NoSuchElementException, WebDriverException):
                    logger.error("Something went wrong...")
                    continue

                try:
                    self._check_cancellation()
                    register_btn.click()
                except WebDriverException:
                    continue

                logger.info("Bidding course...")
                if self.register_course(course):
                    logger.info("")
                    loop = False

        logger.info("Done!")
        return True

    def cleanup(self):
        """Clean up resources."""
        # If already cleaning up, don't try again
        if self._is_cleaning_up:
            return
            
        self._is_cleaning_up = True
        try:
            # Copy the reference in case it gets nulled during cleanup
            driver_ref = self.driver
            if driver_ref:
                try:
                    # Set a page load timeout to prevent hanging
                    driver_ref.set_page_load_timeout(5)
                    driver_ref.quit()
                except WebDriverException as e:
                    # Log the error but don't raise it since this is cleanup
                    logger.warning(f"Error during WebDriver cleanup: {str(e)}")
                except Exception as e:
                    # Catch any other unexpected errors during cleanup
                    logger.warning(f"Unexpected error during WebDriver cleanup: {str(e)}")
                finally:
                    # Ensure driver is nulled even if an exception occurred
                    self.driver = None
        finally:
            # Always ensure the cleanup flag is reset and cancellation token is cleared
            self._is_cleaning_up = False
            self.reset_cancellation()
