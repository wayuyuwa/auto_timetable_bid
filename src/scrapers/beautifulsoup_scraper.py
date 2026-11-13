"""
BeautifulSoup implementation for scraping UTAR course registration data.
"""

import re
import requests
from bs4 import BeautifulSoup
import urllib3
import socket
import os
from time import sleep
from threading import Event, Lock, RLock
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from ..utils.config import (
    BASE_URL, LOGIN_URL, LOGIN_PROCESS_URL, REGISTRATION_URL,
    HOME_URL, COURSE_REGISTRATION_URL, REGISTER_UNIT_PRO_URL, DEFAULT_HEADERS
)
from ..utils.captcha_solver import CaptchaSolver
from ..utils.logger import setup_logger
from ..models.course import Course
from ..utils.diagnostics import dump_http
from .errors import InvalidCredentials, LoginError, PortalClosed, PortalUnavailable, portal_rejection
from .html_parser import (
    find_course_value,
    parse_home_page,
    parse_registered_courses,
    parse_unit_slots,
)

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configure logging
logger = setup_logger(__name__)

LOGIN_MESSAGE_REDIRECT = re.compile(r"login\.jsp\?message=([A-Za-z]+)")


class SessionExpiredException(Exception):
    """Exception raised when the session has expired."""
    pass

class BeautifulSoupScraper:
    """Scraper implementation using BeautifulSoup."""
    
    def __init__(self, connection_retries=3, connection_timeout=10, pool_connections=10, pool_maxsize=10):
        """
        Initialize the scraper with a session and headers.
        
        Args:
            connection_retries (int): Number of connection retries
            connection_timeout (int): Connection timeout in seconds
            pool_connections (int): Number of connection pools
            pool_maxsize (int): Maximum connections per pool
        """
        self._connection_retries = connection_retries
        self._pool_connections = pool_connections
        self._pool_maxsize = pool_maxsize
        self.session = self._new_session()

        self.headers = DEFAULT_HEADERS
        self.connection_timeout = connection_timeout
        self.captcha_solver = CaptchaSolver()
        self.max_retries = 2
        
        # Add cancellation token
        self._cancellation_token = Event()
        
        # Store credentials for auto-relogin
        self._student_id = None
        self._password = None
        self._is_logged_in = False
        self._relogin_lock = RLock()  # Lock to prevent multiple relogin attempts
        self._relogin_active = False  # True while a relogin is running
        self._logging_in = False  # True inside login(); disables nested relogin
        self._home_data = None
        self.on_login_progress = None  # optional callback(attempt, max, previous_reason)
        
        logger.info("BeautifulSoupScraper initialized")

    def _new_session(self):
        """Build the HTTP session.

        read=0: do NOT retry read timeouts at the adapter level. A hanging
        request otherwise blocks ~connection_retries x connection_timeout
        (~40s) before the cancellation check runs, so "Stop safely" feels
        unresponsive. Connection-drop retries are kept for resilience, and
        register_courses() has its own cancellation-aware retry loop.
        """
        session = requests.Session()
        retry_strategy = Retry(
            total=self._connection_retries,
            connect=self._connection_retries,
            read=0,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=self._pool_connections,
            pool_maxsize=self._pool_maxsize,
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def cancel(self):
        """Set the cancellation token to stop ongoing operations."""
        self._cancellation_token.set()
        logger.info("Cancellation requested")

    def reset_cancellation(self):
        """Reset the cancellation token."""
        self._cancellation_token.clear()
        logger.info("Cancellation token reset")

    def is_cancelled(self) -> bool:
        """Return True when cancellation has been requested."""
        return self._cancellation_token.is_set()

    def is_logged_in(self) -> bool:
        """Return True after a successful login."""
        return self._is_logged_in

    def _check_cancellation(self):
        """Check if operation has been cancelled and raise exception if needed."""
        if self._cancellation_token.is_set():
            logger.info("Operation cancelled by user")
            raise Exception("Operation cancelled by user")
            
    def _check_session_expired(self, response):
        """
        Check if the session has expired based on the response content.
        
        Args:
            response (Response): The HTTP response object
            
        Raises:
            SessionExpiredException: If the session has expired
        """
        if response.status_code == 200:
            content = response.content.decode('utf-8', errors='ignore')
            # Check for session expired redirects in JavaScript
            if "window.parent.location.href" in content and "sessionExpired" in content:
                logger.warning("Session has expired")
                self._is_logged_in = False
                raise SessionExpiredException("Session has expired. Please log in again.")

    def _try_relogin(self):
        """
        Attempt to relogin if credentials are available.
        
        Returns:
            bool: True if relogin was successful, False otherwise
        """
        # Skip if no credentials available
        if not self._student_id or not self._password:
            logger.warning("Cannot relogin: No stored credentials")
            return False
            
        # Prevent multiple simultaneous relogin attempts
        with self._relogin_lock:
            if self._relogin_active:
                # login() itself hit "session expired" (for example when
                # registration is closed). Starting another relogin from inside
                # a relogin used to deadlock on this lock; give up instead.
                logger.warning("Session expired again during relogin; not retrying")
                return False
            if self._is_logged_in:
                # Another thread already relogged in successfully
                return True

            logger.info("Attempting to relogin due to session expiration")
            self._relogin_active = True
            try:
                self._check_cancellation()
                # Clear the session and create a new one
                self.session.close()
                self.session = self._new_session()

                # Attempt login with stored credentials
                login_result = self.login(self._student_id, self._password, max_retries=1)

                if 'success' in login_result:
                    self._is_logged_in = True
                    logger.info("Successfully relogged in after session expiration")
                    return True
                else:
                    logger.error("Failed to relogin after session expiration")
                    return False

            except Exception as e:
                logger.error(f"Error during relogin attempt: {str(e)}")
                return False
            finally:
                self._relogin_active = False

    async def fetch_student_info(self, unit_code: str, group_code: str) -> dict:
        """
        Fetch student information from the registration page.
        
        Args:
            unit_code (str): The unit code to fetch information for
            group_code (str): The group code to fetch information for
            
        Returns:
            dict: Dictionary containing student information
        """
        data = {
            'reqPaperType': 'M',
            'reqFregkey': '',
            'reqUnit': unit_code,
            'Save': 'View'
        }
        
        try:
            response = self.session.post(
                REGISTRATION_URL,
                headers=self.headers,
                data=data,
                verify=False,
                timeout=self.connection_timeout
            )
            
            self._check_session_expired(response)
            self._check_cancellation()
            
            if response.status_code != 200:
                raise Exception(f'Failed to fetch course data for {group_code}. Status: {response.status_code}')
            
            soup = BeautifulSoup(response.content, 'html.parser')
            # Extract required values
            req_fregkey_input = soup.find('input', {'name': 'reqFregkey'})
            req_paper_type = soup.find('input', {'name': 'reqPaperType'})
            req_session_value = soup.find('input', {'name': 'reqSession'})
            req_sid = soup.find('input', {'name': 'reqSid'})
            req_with_class = soup.find('input', {'name': 'reqWithClass'})
            if not req_fregkey_input or not req_fregkey_input.get('value'):
                raise Exception('Student ID not found.')
            
            result = {
                'student_id': req_fregkey_input['value'],
                'paper_type': req_paper_type['value'],
                'req_session': req_session_value['value'],
                'reqsid': req_sid['value'],
                'req_with_class': req_with_class['value']
            }
            
            logger.info(f'student_id: {result["student_id"]}, paper_type: {result["paper_type"]}, '
                       f'req_session: {result["req_session"]}, reqsid: {result["reqsid"]}, '
                       f'req_with_class: {result["req_with_class"]}')
            
            return result
            
        except SessionExpiredException:
            # Try to relogin and retry the operation
            if self._try_relogin():
                logger.info("Retrying fetch_student_info after successful relogin")
                return await self.fetch_student_info(unit_code, group_code)
            else:
                raise Exception('Session expired and relogin failed')
        except Exception as e:
            # Check if cancellation was the cause
            self._check_cancellation()
            # If we get here, it was another exception
            raise Exception(f'Request failed: {str(e)}')

    async def fetch_course_value(self, unit_code: str, group_code: str) -> str:
        """
        Fetch course value for a specific unit and group.
        
        Args:
            unit_code (str): The unit code to fetch
            group_code (str): The group code to fetch
            
        Returns:
            str: The course value
        """
        self._check_cancellation()
        
        data = {
            'reqPaperType': 'M',
            'reqFregkey': '',
            'reqUnit': unit_code,
            'Save': 'View'
        }
        
        try:
            response = self.session.post(
                REGISTRATION_URL,
                headers=self.headers,
                data=data,
                verify=False,
                timeout=self.connection_timeout
            )
            
            self._check_session_expired(response)
            self._check_cancellation()
            
            if response.status_code != 200:
                raise Exception(f'Failed to fetch course data for {group_code}. Status: {response.status_code}')
            
            soup = BeautifulSoup(response.content, 'html.parser')
            rows = soup.find_all('tr', align='center')
            
            for row in rows:
                self._check_cancellation()
                
                cols = row.find_all('td')
                if len(cols) >= 3:
                    group_col = cols[2].get_text(strip=True)
                    group_type = cols[1].get_text(strip=True)
                    
                    if f'{group_type}{group_col}' == group_code:
                        checkbox = row.find('input', {'name': 'reqMid'})
                        if checkbox and checkbox.get('value'):
                            return checkbox['value']
            
            raise Exception(f'Group {group_code} not found for unit {unit_code}')
            
        except SessionExpiredException:
            # Try to relogin and retry the operation
            if self._try_relogin():
                logger.info("Retrying fetch_course_value after successful relogin")
                return await self.fetch_course_value(unit_code, group_code)
            else:
                raise Exception('Session expired and relogin failed')
        except Exception as e:
            # Check if cancellation was the cause
            self._check_cancellation()
            # If we get here, it was another exception
            raise Exception(f'Request failed: {str(e)}')
    
    # Consecutive "login accepted, then session expired" answers after which the
    # portal is treated as closed (registration not open) instead of retrying on.
    CLOSED_AFTER = 2

    def _wait(self, seconds: float):
        """Pause between attempts; returns early (and raises) on cancel."""
        if self._cancellation_token.wait(seconds):
            self._check_cancellation()

    def login(self, student_id: str, password: str, max_retries: int = 5, progress=None) -> dict:
        """
        Log in, solving the CAPTCHA. Retries wrong captchas and transient errors.

        progress(attempt, max_attempts, previous_failure_reason_or_None) is called
        before each attempt so the UI can show "Login attempt 2/5".

        Raises InvalidCredentials, PortalClosed or PortalUnavailable (all
        LoginError) with the per-attempt reasons in .attempts.
        """
        if not student_id or not password:
            raise InvalidCredentials("Student ID and password are required.")

        # Store credentials for potential relogin
        self._student_id = student_id
        self._password = password
        self._is_logged_in = False
        progress = progress or self.on_login_progress

        reasons = []
        closed_streak = 0
        self._logging_in = True
        try:
            for attempt in range(1, max_retries + 1):
                self._check_cancellation()
                if progress:
                    try:
                        progress(attempt, max_retries, reasons[-1] if reasons else None)
                    except Exception:  # noqa: BLE001 - a UI callback must not break login
                        pass
                reason, closed = self._login_once(student_id, password, attempt, max_retries)
                if reason is None:
                    self._is_logged_in = True
                    return {"success": "Login successful", "students_data": self._home_data}
                reasons.append(reason)
                logger.warning("Login attempt %s/%s failed: %s", attempt, max_retries, reason)
                closed_streak = closed_streak + 1 if closed else 0
                if closed_streak >= self.CLOSED_AFTER:
                    break  # the portal answers consistently; more attempts only waste time
                if attempt < max_retries:
                    # Wrong captcha: retry at once. Anything else: short back-off.
                    self._wait(0 if reason == "Wrong captcha" else min(1.0 * attempt, 3.0))
        finally:
            self._logging_in = False

        self._is_logged_in = False
        self._check_cancellation()
        summary = "; ".join(f"{index}: {text}" for index, text in enumerate(reasons, 1))
        if closed_streak >= self.CLOSED_AFTER or (reasons and all("session expired" in r for r in reasons)):
            raise PortalClosed(
                f"Login failed after {len(reasons)} attempt(s). The portal accepted the login but "
                "then answered 'session expired'; course registration may be closed right now. "
                f"({summary})",
                reasons,
            )
        raise PortalUnavailable(f"Login failed after {len(reasons)} attempt(s). ({summary})", reasons)

    def _portal_message(self, code: str) -> str:
        """Red message text the portal shows on login.jsp?message=<code>."""
        try:
            response = self.session.get(f"{LOGIN_URL}?message={code}", headers=self.headers, verify=False,
                                        timeout=self.connection_timeout)
            dump_http(f"login-message-{code}", response)
            soup = BeautifulSoup(response.text, 'html.parser')
            for element in soup.select('.red'):
                text = " ".join(element.get_text(" ").split())
                if text:
                    return text
        except requests.RequestException as error:
            logger.debug("Could not read the portal message for %s: %s", code, error)
        return ""

    def _login_once(self, student_id, password, attempt, max_retries):
        """One login attempt. Returns (None, False) on success, else
        (reason, looks_closed). Raises InvalidCredentials or on cancellation."""
        try:
            logger.info("Login attempt %s/%s: loading login page", attempt, max_retries)
            response = self.session.get(LOGIN_URL, headers=self.headers, verify=False,
                                        timeout=self.connection_timeout)
            dump_http("login-page", response)
            self._check_cancellation()
            if response.status_code != 200:
                return f"Login page returned HTTP {response.status_code}", False

            soup = BeautifulSoup(response.text, 'html.parser')
            captcha_img = soup.find('img', {'src': lambda src: src and 'Kaptcha.jpg' in src})
            prekap_input = soup.find('input', {'name': 'preKap'})
            if not captcha_img or not prekap_input:
                return "Login page did not contain the captcha form", False

            captcha_src = captcha_img['src'].lstrip('../')
            captcha_url = f"{BASE_URL}/../{captcha_src}"
            captcha_response = self.session.get(captcha_url, headers=self.headers, verify=False,
                                                timeout=self.connection_timeout)
            self._check_cancellation()
            if captcha_response.status_code != 200:
                return f"Captcha image returned HTTP {captcha_response.status_code}", False
            captcha_solution = os.getenv("UTAR_MOCK_CAPTCHA") or self.captcha_solver.solve(captcha_response.content)
            logger.info("Captcha solved: %s", captcha_solution)

            payload = {
                'preKap': prekap_input.get('value'),
                'reqFregkey': student_id,
                'reqPassword': password,
                'kaptchafield': captcha_solution,
            }
            self._check_cancellation()
            login_response = self.session.post(LOGIN_PROCESS_URL, headers=self.headers, data=payload,
                                               verify=False, timeout=self.connection_timeout)
            dump_http("login-submit", login_response, payload)
            self._check_cancellation()
            try:
                self._check_session_expired(login_response)
            except SessionExpiredException:
                return "Portal answered session expired at login", True

            if 'Invalid code' in login_response.text:
                return "Wrong captcha", False
            # The portal refuses some logins by sending the browser back to
            # login.jsp?message=<code> (seen: loginError, notActive, notConsultAdviser).
            redirect = LOGIN_MESSAGE_REDIRECT.search(login_response.text)
            if redirect:
                code = redirect.group(1)
                text = self._portal_message(code)
                rejection = portal_rejection(code, text)
                if rejection is not None:
                    raise rejection
                return f"Portal sent the login back ({code}): {text or 'no message'}", False
            if 'Invalid' in login_response.text:
                self._is_logged_in = False
                raise InvalidCredentials("Login failed: the portal rejected the student ID or password. "
                                         "Please check your credentials.")

            try:
                home_data = self.get_home_page_data()
            except SessionExpiredException:
                return "Login accepted, then the portal answered session expired", True
            if not home_data or not home_data[0]:
                return "Logged in, but the registration page could not be read", False
            self._home_data = home_data
            return None, False
        except LoginError:
            raise
        except requests.Timeout:
            self._check_cancellation()
            return f"No response within {self.connection_timeout}s", False
        except (requests.RequestException, socket.error) as error:
            self._check_cancellation()
            return f"Network error: {type(error).__name__}", False
        except Exception as error:  # noqa: BLE001
            self._check_cancellation()
            return str(error) or type(error).__name__, False

    def get_home_page_data(self) -> tuple:
        """
        Get data from the home page after successful login.
        
        Returns:
            tuple: (data dictionary, cookies dictionary)
        """
        try:
            self._check_cancellation()
            
            response = self.session.get(
                COURSE_REGISTRATION_URL,
                headers=self.headers,
                verify=False,
                timeout=self.connection_timeout,
            )
            
            dump_http("registration-page", response)
            self._check_session_expired(response)
            
            if response.status_code != 200:
                logger.info(f'Failed to retrieve home page. Status code: {response.status_code}')
                return None, self.session.cookies.get_dict()
            
            data = parse_home_page(response.content.decode('utf-8', errors='ignore'))
            if not data:
                logger.info('Table not found.')
                return None, self.session.cookies.get_dict()
            
            logger.info('Extracted Data:')
            for key, value in data.items():
                logger.info(f'{key}: {value}')
            
            return data, self.session.cookies.get_dict()
            
        except SessionExpiredException:
            if self._logging_in:
                raise  # login() decides what to do; never a nested relogin
            # Try to relogin and retry the operation
            if self._try_relogin():
                logger.info("Retrying get_home_page_data after successful relogin")
                return self.get_home_page_data()
            else:
                raise Exception('Session expired and relogin failed')
        except Exception as e:
            # Check if cancellation was the cause
            self._check_cancellation()
            # If we get here, it was another exception
            raise Exception(f'Failed to get home page data: {str(e)}')
            
    def register_courses(self, courses: list[Course]) -> tuple:
        """
        Register multiple courses using BeautifulSoup with optimized bidding strategy.
        Includes retry mechanism for failed course registrations.
        
        Args:
            courses (list): List of Course objects to register
            
        Returns:
            tuple: (result_text, success_status)
            - result_text: Detailed text of registration process results
            - success_status: Boolean indicating overall success
        """
        if not courses:
            logger.warning("No courses provided for registration")
            return "No courses provided for registration", False
        
        result_text = "BeautifulSoup Course Registration Results:\n\n"
        registration_success = True
        
        # Track courses that need retry
        failed_courses = courses[:]
        successful_courses = []
        retry_count = 0
        
        while failed_courses and retry_count < self.max_retries:
            self._check_cancellation()
            
            for course in list(failed_courses):
                self._check_cancellation()
                
                logger.info(f"Attempting to register course: {course.code} - {course.name}")
                result_text += f"Course: {course.code} - {course.name}\n"
                
                try:
                    # Step 1: Fetch student info for the course
                    student_data = self._fetch_student_info(course.code)
                    if not student_data:
                        logger.warning(f"Could not fetch student info for {course.code}")
                        result_text += f"Failed to fetch student information\n"
                        continue
                    
                    self._check_cancellation()
                    
                    # Extract required values from student data
                    student_id = student_data.get('student_id')
                    paper_type = student_data.get('paper_type')
                    req_session = student_data.get('req_session')
                    req_sid = student_data.get('reqsid')
                    req_with_class = student_data.get('req_with_class')
                    
                    result_text += f"Student ID: {student_id}\n"
                    
                    # Step 2: Get all class types and their corresponding values
                    class_values = {}
                    
                    # Group classes by type (L, T, P)
                    for class_type, slot_numbers in course.slots.items():
                        if not slot_numbers:  # Skip empty slots
                            continue
                        
                        # For each slot number in priority order
                        for slot_number in slot_numbers:
                            class_code = f"{class_type}{slot_number}"
                            course_value = self._fetch_course_value(course.code, class_code)
                            
                            if course_value:
                                class_values[class_code] = course_value
                                result_text += f"Found {class_code} value: {course_value[:8]}...\n"
                                break  # Stop after finding the first available slot for each type
                            else:
                                result_text += f"Could not find {class_code} value\n"
                    
                    # Check if we found values for all required class types
                    if len(class_values) < sum(1 for slots in course.slots.values() if slots):
                        missing_types = set(course.slots.keys()) - {code[0] for code in class_values.keys()}
                        logger.warning(f"Could not find values for all required class types: {missing_types}")
                        result_text += f"Missing values for class types: {', '.join(missing_types)}\n"
                        continue
                    
                    # Step 3: Submit registration using the bidding approach
                    bidding_result = self._submit_bidding(
                        course.code,
                        student_id,
                        paper_type,
                        req_session,
                        req_sid,
                        req_with_class,
                        list(class_values.values())
                    )
                    
                    if bidding_result.get('success'):
                        logger.info(f"Successfully registered {course.code}")
                        result_text += f"{bidding_result.get('message', 'Registration successful!')}\n"
                        successful_courses.append(course)
                        failed_courses.remove(course)
                    else:
                        logger.warning(f"Registration failed for {course.code}: {bidding_result.get('error')}")
                        result_text += f"{bidding_result.get('error', 'Registration failed')}\n"
                        registration_success = False
                
                except SessionExpiredException:
                    logger.warning(f"Session expired while registering {course.code}, attempting relogin")
                    # Try to relogin and continue
                    if self._try_relogin():
                        logger.info(f"Successfully relogged in, continuing with registration for {course.code}")
                        result_text += "Session expired but successfully relogged in\n"
                        # Don't mark as failure, just continue with this course in the next iteration
                    else:
                        logger.error(f"Session expired and relogin failed while registering {course.code}")
                        result_text += "Session expired and relogin failed. Please log in again.\n"
                        registration_success = False
                        return result_text, registration_success
                    
                except Exception as e:
                    self._check_cancellation()  # Check if it was cancelled
                    
                    logger.error(f"Error registering course {course.code}: {str(e)}")
                    result_text += f"Error: {str(e)}\n"
                    registration_success = False
                
                result_text += "\n"
            
            retry_count += 1

        # A course skipped for a missing/full class never reached the submit;
        # that is a failure, not a success.
        if failed_courses:
            registration_success = False

        return result_text, registration_success

    def _fetch_student_info(self, unit_code: str) -> dict:
        """
        Fetch student information from the registration page.
        
        Args:
            unit_code (str): The unit code to fetch information for
            
        Returns:
            dict: Dictionary containing student information or None if failed
        """
        self._check_cancellation()
        
        data = {
            'reqPaperType': 'M',
            'reqFregkey': '',
            'reqUnit': unit_code,
            'Save': 'View'
        }
        
        try:
            response = self.session.post(
                REGISTRATION_URL,
                headers=self.headers,
                data=data,
                verify=False,
                timeout=self.connection_timeout
            )
            
            self._check_session_expired(response)
            self._check_cancellation()
            
            if response.status_code != 200:
                logger.warning(f"Failed to fetch course data. Status: {response.status_code}")
                return None
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract required values
            req_fregkey_input = soup.find('input', {'name': 'reqFregkey'})
            req_paper_type = soup.find('input', {'name': 'reqPaperType'})
            req_session_value = soup.find('input', {'name': 'reqSession'})
            req_sid = soup.find('input', {'name': 'reqSid'})
            req_with_class = soup.find('input', {'name': 'reqWithClass'})
            
            if not req_fregkey_input or not req_fregkey_input.get('value'):
                logger.warning("Student ID not found.")
                return None
            
            result = {
                'student_id': req_fregkey_input['value'],
                'paper_type': req_paper_type['value'],
                'req_session': req_session_value['value'],
                'reqsid': req_sid['value'],
                'req_with_class': req_with_class['value']
            }
            
            logger.info(f"Student info fetched: {result['student_id']}")
            return result
            
        except SessionExpiredException:
            # Try to relogin and retry the operation
            if self._try_relogin():
                logger.info("Retrying _fetch_student_info after successful relogin")
                return self._fetch_student_info(unit_code)
            else:
                logger.error("Failed to relogin after session expiration")
                return None
        except Exception as e:
            self._check_cancellation()
            logger.error(f"Error fetching student info: {str(e)}")
            return None
    
    def _fetch_course_value(self, unit_code: str, group_code: str) -> str:
        """
        Fetch course value for a specific unit and group.
        
        Args:
            unit_code (str): The unit code to fetch
            group_code (str): The group code to fetch (e.g. "L1", "T2", "P1")
            
        Returns:
            str: The course value or None if not found
        """
        self._check_cancellation()
        
        data = {
            'reqPaperType': 'M',
            'reqFregkey': '',
            'reqUnit': unit_code,
            'Save': 'View'
        }
        
        try:
            response = self.session.post(
                REGISTRATION_URL,
                headers=self.headers,
                data=data,
                verify=False,
                timeout=self.connection_timeout
            )
            
            self._check_session_expired(response)
            self._check_cancellation()
            
            if response.status_code != 200:
                logger.warning(f"Failed to fetch course data for {group_code}. Status: {response.status_code}")
                return None
            
            soup = BeautifulSoup(response.content, 'html.parser')
            rows = soup.find_all('tr', align='center')
            
            for row in rows:
                self._check_cancellation()
                
                cols = row.find_all('td')
                if len(cols) >= 3:
                    group_col = cols[2].get_text(strip=True)
                    group_type = cols[1].get_text(strip=True)
                    
                    if f'{group_type}{group_col}' == group_code:
                        checkbox = row.find('input', {'name': 'reqMid'})
                        if checkbox and checkbox.get('value'):
                            return checkbox['value']
            
            logger.warning(f"Group {group_code} not found for unit {unit_code}")
            return None
            
        except SessionExpiredException:
            # Try to relogin and retry the operation
            if self._try_relogin():
                logger.info("Retrying _fetch_course_value after successful relogin")
                return self._fetch_course_value(unit_code, group_code)
            else:
                logger.error("Failed to relogin after session expiration")
                return None
        except Exception as e:
            self._check_cancellation()
            logger.error(f"Error fetching course value: {str(e)}")
            return None
    
    def get_registered_courses(self) -> dict:
        """Read the registered-courses page: the source of truth for what is
        actually registered. Returns {"courses": [...], "info": {...}}."""
        self._check_cancellation()
        try:
            response = self.session.get(
                COURSE_REGISTRATION_URL,
                headers=self.headers,
                verify=False,
                timeout=self.connection_timeout,
            )
            self._check_session_expired(response)
        except SessionExpiredException:
            if not self._try_relogin():
                raise
            return self.get_registered_courses()
        html = response.content.decode('utf-8', errors='ignore')
        return {"courses": parse_registered_courses(html), "info": parse_home_page(html)}

    def get_unit_slots(self, unit_code: str) -> list:
        """Class slots offered for a unit (timing, availability, selectable)."""
        self._check_cancellation()
        data = {
            'reqPaperType': 'M',
            'reqFregkey': '',
            'reqUnit': unit_code,
            'Save': 'View'
        }
        try:
            response = self.session.post(
                REGISTRATION_URL,
                headers=self.headers,
                data=data,
                verify=False,
                timeout=self.connection_timeout,
            )
            self._check_session_expired(response)
        except SessionExpiredException:
            if not self._try_relogin():
                raise
            return self.get_unit_slots(unit_code)
        return parse_unit_slots(response.content.decode('utf-8', errors='ignore'))

    def _submit_bidding(self, unit_code: str, student_id: str, paper_type: str, 
                       req_session: str, req_sid: str, req_with_class: str, req_mids: list) -> dict:
        """
        Submit the bidding request with multiple class values.
        
        Args:
            unit_code (str): Course code
            student_id (str): Student ID
            paper_type (str): Paper type
            req_session (str): Session value
            req_sid (str): SID value
            req_with_class (str): WithClass value
            req_mids (list): List of course values (reqMid)
            
        Returns:
            dict: Result of the bidding process
        """
        try:
            # Prepare the data bundle for bidding
            data_bundle = {
                'reqUnit': unit_code,
                'reqSid': req_sid,
                'reqSession': req_session,
                'reqFregkey': student_id,
                'reqPaperType': paper_type,
                'reqWithClass': req_with_class,
                'act': 'insert',
                'reqMid': req_mids  # List of values
            }
            
            # Set headers for the request
            headers = {
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Content-Type': 'application/x-www-form-urlencoded',
                'Origin': 'https://unitreg.utar.edu.my',
                'Referer': 'https://unitreg.utar.edu.my/portal/courseRegStu/registration/registerUnitSurvey.jsp'
            }
            
            # Send the bidding request
            response = self.session.post(
                REGISTER_UNIT_PRO_URL,
                headers=headers,
                data=data_bundle,
                verify=False,
                timeout=self.connection_timeout
            )
            
            self._check_session_expired(response)
            
            if response.status_code != 200:
                return {
                    'success': False,
                    'error': f"Received status code {response.status_code}"
                }
            
            # Parse the response to check for success or error messages
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Check for success messages with class = red
            success_msg = soup.find('div', class_='red')
            # check if insert-success is in response.url
            if response.url and "insert-success" in response.url or\
                success_msg and "success" in success_msg.get_text(strip=True).lower():
                return {
                    'success': True,
                    'message': "Course registration successful!"
                }
            
            alert = re.search(r"alert\(\s*['\"]([^'\"]*failed[^'\"]*)['\"]", response.text, re.I)
            if alert:
                return {
                    'success': False,
                    'error': alert.group(1).strip()
                }

            # If we can't definitively determine the status
            return {
                'success': False,
                'error': "Bidding request submitted, but status unclear"
            }
            
        except SessionExpiredException:
            # Try to relogin and retry the operation
            if self._try_relogin():
                logger.info("Retrying _submit_bidding after successful relogin")
                return self._submit_bidding(unit_code, student_id, paper_type, req_session, req_sid, req_with_class, req_mids)
            else:
                # Propagate the session expired exception to be handled by the caller
                raise
        except Exception as e:
            logger.error(f"Error in bidding submission: {str(e)}")
            return {
                'success': False,
                'error': f"Error in bidding submission: {str(e)}"
            }
    
    def cancel(self):
        """
        Cancel the current session.
        """
        try:
            self._cancellation_token.set()
            self.session.close()
            self._is_logged_in = False
            logger.info("Session cancelled successfully.")
        except Exception as e:
            logger.error(f"Error cancelling session: {str(e)}")

    def cleanup(self):
        """Close the HTTP session and release scraper state."""
        self.cancel()
        self.reset_cancellation()

    def set_max_retries(self, max_retries: int):
        """
        Set the maximum number of retries for requests.
        
        Args:
            max_retries (int): Maximum number of retries
        """
        self.max_retries = max_retries
        logger.info(f"Max retries set to {self.max_retries}")