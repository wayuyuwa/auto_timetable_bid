"""
BeautifulSoup implementation for scraping UTAR course registration data.
"""

import requests
from bs4 import BeautifulSoup
import urllib3
import socket
from time import sleep
from threading import Event
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from ..utils.config import (
    BASE_URL, LOGIN_URL, LOGIN_PROCESS_URL, REGISTRATION_URL,
    HOME_URL, COURSE_REGISTRATION_URL, DEFAULT_HEADERS
)
from ..utils.captcha_solver import CaptchaSolver
from ..utils.logger import setup_logger
from ..utils.timetable_reader import Course
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configure logging
logger = setup_logger(__name__)

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
        # Configure session with retry strategy
        self.session = requests.Session()
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=connection_retries,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"]
        )
        
        # Mount adapter with retry strategy
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize
        )
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        self.headers = DEFAULT_HEADERS
        self.captcha_solver = CaptchaSolver()
        self.max_retries = 2
        
        # Add cancellation token
        self._cancellation_token = Event()
        logger.info("BeautifulSoupScraper initialized")

    def cancel(self):
        """Set the cancellation token to stop ongoing operations."""
        self._cancellation_token.set()
        logger.info("Cancellation requested")

    def reset_cancellation(self):
        """Reset the cancellation token."""
        self._cancellation_token.clear()
        logger.info("Cancellation token reset")

    def _check_cancellation(self):
        """Check if operation has been cancelled and raise exception if needed."""
        if self._cancellation_token.is_set():
            logger.info("Operation cancelled by user")
            raise Exception("Operation cancelled by user")

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
                verify=False
            )
            
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
                verify=False
            )
            
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
            
        except Exception as e:
            # Check if cancellation was the cause
            self._check_cancellation()
            # If we get here, it was another exception
            raise Exception(f'Request failed: {str(e)}')
    
    def login(self, student_id: str, password: str, max_retries: int = 3) -> dict:
        """
        Handle the login process including CAPTCHA.
        
        Args:
            student_id (str): Student ID for login
            password (str): Password for login
            max_retries (int): Maximum number of retry attempts
            
        Returns:
            dict: Dictionary containing login result and student data
            
        Raises:
            Exception: Only for critical issues like invalid credentials or missing required data
        """
        # Critical validation
        if not student_id or not password:
            raise Exception("Student ID and password are required!")

        retry_count = 0
        while retry_count < max_retries:
            try:
                self._check_cancellation()
                
                # Get login page
                logger.info(f"Attempting to get login page (attempt {retry_count+1}/{max_retries})")
                response = self.session.get(LOGIN_URL, headers=self.headers, verify=False)
                
                self._check_cancellation()
                
                if response.status_code != 200:
                    logger.warning(f"Failed to get login page. Status: {response.status_code}")
                    retry_count += 1
                    sleep(1)
                    continue

                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Find CAPTCHA image
                captcha_img = soup.find('img', {'src': lambda src: src and 'Kaptcha.jpg' in src})
                if not captcha_img:
                    logger.warning("CAPTCHA image not found, retrying...")
                    retry_count += 1
                    sleep(1)
                    continue
                
                # Get CAPTCHA image
                captcha_src = captcha_img['src'].lstrip('../')
                captcha_url = f"{BASE_URL}/../{captcha_src}"
                
                self._check_cancellation()
                
                try:
                    logger.info(f"Attempting to retrieve CAPTCHA image")
                    captcha_response = self.session.get(captcha_url, headers=self.headers, verify=False)
                    
                    self._check_cancellation()
                    
                    if captcha_response.status_code != 200:
                        logger.warning(f"Failed to retrieve CAPTCHA image from {captcha_url}. Status: {captcha_response.status_code}")
                        retry_count += 1
                        sleep(1)
                        continue
                    
                    # Solve CAPTCHA using CaptchaSolver
                    try:
                        self._check_cancellation()
                        captcha_solution = self.captcha_solver.solve(captcha_response.content)
                        logger.info(f'CAPTCHA solved: {captcha_solution}')
                    except ConnectionError as ce:
                        logger.warning(f"Connection error during CAPTCHA solving: {str(ce)}")
                        retry_count += 1
                        sleep(2)  # Slightly longer sleep for connection issues
                        continue
                
                except (requests.RequestException, socket.error) as e:
                    self._check_cancellation()
                    logger.warning(f"Network error retrieving CAPTCHA: {str(e)}")
                    retry_count += 1
                    sleep(2)
                    continue
                
                self._check_cancellation()
                
                # Get preKap value
                prekap_input = soup.find('input', {'name': 'preKap'})
                if not prekap_input:
                    logger.warning("preKap value not found, retrying...")
                    retry_count += 1
                    sleep(1)
                    continue
                
                prekap_value = prekap_input.get('value')
                
                # Attempt login
                payload = {
                    'preKap': prekap_value,
                    'reqFregkey': student_id,
                    'reqPassword': password,
                    'kaptchafield': captcha_solution
                }
                
                self._check_cancellation()
                
                login_response = self.session.post(
                    LOGIN_PROCESS_URL,
                    headers=self.headers,
                    data=payload,
                    verify=False
                )
                
                self._check_cancellation()
                
                if 'Invalid' in login_response.text:
                    # This is a critical error - invalid credentials
                    raise Exception('Login failed. Please check your credentials.')
                
                # Get home page data
                home_data = self.get_home_page_data()
                if not home_data:
                    logger.warning("Failed to get home page data, retrying...")
                    retry_count += 1
                    sleep(1)
                    continue
                
                return {
                    'success': 'Login successful',
                    'students_data': home_data
                }
                
            except requests.RequestException as e:
                logger.warning(f"Request failed: {str(e)}, retrying...")
                retry_count += 1
                sleep(1)
                continue
            except Exception as e:
                # Check if it was a cancellation
                self._check_cancellation()
                
                # If we get here, it wasn't a cancellation
                if "check your credentials" in str(e):
                    # Re-raise critical errors
                    raise
                
                logger.warning(f"Login attempt failed: {str(e)}, retrying...")
                retry_count += 1
                sleep(1)
                continue
        
        # If we've exhausted all retries
        raise Exception(f"Login failed after {max_retries} attempts. Please try again later.")

    def get_home_page_data(self) -> tuple:
        """
        Get data from the home page after successful login.
        
        Returns:
            tuple: (data dictionary, cookies dictionary)
        """
        try:
            self._check_cancellation()
            
            response = self.session.get(COURSE_REGISTRATION_URL, headers=self.headers, verify=False)
            
            if response.status_code != 200:
                logger.info(f'Failed to retrieve home page. Status code: {response.status_code}')
                return None, self.session.cookies.get_dict()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            table = soup.find('table', {'id': 'tblGrid'})
            
            if not table:
                logger.info('Table not found.')
                return None, self.session.cookies.get_dict()
            
            data = {}
            rows = table.find_all('tr', align='left')
            
            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 2:
                    key = cols[0].get_text(strip=True)
                    if len(cols) == 4:
                        data[key] = cols[1].get_text(strip=True)
                        second_key = cols[2].get_text(strip=True)
                        data[second_key] = cols[3].get_text(strip=True)
                    else:
                        data[key] = cols[1].get_text(strip=True)
            
            logger.info('Extracted Data:')
            for key, value in data.items():
                logger.info(f'{key}: {value}')
            
            return data, self.session.cookies.get_dict()
            
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
            
            for course in list(failed_courses):  # Create a copy for safe iteration
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
                    if len(class_values) < len(course.slots):
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
                    
                except Exception as e:
                    self._check_cancellation()  # Check if it was cancelled
                    
                    logger.error(f"Error registering course {course.code}: {str(e)}")
                    result_text += f"Error: {str(e)}\n"
                    registration_success = False
                
                result_text += "\n"
            
            retry_count += 1
        
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
                verify=False
            )
            
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
                verify=False
            )
            
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
            
        except Exception as e:
            self._check_cancellation()
            logger.error(f"Error fetching course value: {str(e)}")
            return None
    
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
                'https://unitreg.utar.edu.my/portal/courseRegStu/registration/registerUnitProSurvey.jsp',
                headers=headers,
                data=data_bundle,
                verify=False
            )
            
            if response.status_code != 200:
                return {
                    'success': False,
                    'error': f"Received status code {response.status_code}"
                }
            
            # Parse the response to check for success or error messages
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Check for error messages
            error_msg = soup.find('font', {'color': 'red'})
            if error_msg:
                error_text = error_msg.get_text(strip=True)
                
                # Check specific error messages
                if "exceeded the maximum number of credit hours" in error_text.lower():
                    return {
                        'success': False,
                        'error': "Maximum credit hours reached"
                    }
                elif "the time of selected units are clashed" in error_text.lower():
                    return {
                        'success': False,
                        'error': "Time clash with other registered courses"
                    }
                elif "please select a valid class combination" in error_text.lower():
                    return {
                        'success': False,
                        'error': "Invalid class combination"
                    }
                else:
                    return {
                        'success': False,
                        'error': error_text
                    }
            
            # Check for success messages
            success_msg = soup.find('font', {'color': 'blue'})
            if success_msg and "successful" in success_msg.get_text(strip=True).lower():
                return {
                    'success': True,
                    'message': "Course registration successful!"
                }
            
            # Check if the course appears in the registration table
            reg_table = soup.find('table', {'id': 'tblGrid'})
            if reg_table and unit_code in reg_table.get_text():
                return {
                    'success': True,
                    'message': "Course registration confirmed in timetable"
                }
            
            # If we can't definitively determine the status
            return {
                'success': False,
                'message': "Bidding request submitted, but status unclear"
            }
            
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
            self.session.close()
            self._cancellation_token.set()
            logger.info("Session cancelled successfully.")
        except Exception as e:
            logger.error(f"Error cancelling session: {str(e)}")

    def set_max_retries(self, max_retries: int):
        """
        Set the maximum number of retries for requests.
        
        Args:
            max_retries (int): Maximum number of retries
        """
        self.max_retries = max_retries
        logger.info(f"Max retries set to {self.max_retries}")