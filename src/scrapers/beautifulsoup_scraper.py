"""
BeautifulSoup implementation for scraping UTAR course registration data.
"""

import requests
from bs4 import BeautifulSoup
import logging
import urllib3
import base64
from requests import post
from ..utils.config import (
    LOGIN_URL, LOGIN_PROCESS_URL, REGISTRATION_URL,
    HOME_URL, COURSE_REGISTRATION_URL, DEFAULT_HEADERS
)
from ..utils.captcha_solver import CaptchaSolver

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BeautifulSoupScraper:
    """Scraper implementation using BeautifulSoup."""
    
    def __init__(self):
        """Initialize the scraper with a session and headers."""
        self.session = requests.Session()
        self.headers = DEFAULT_HEADERS
        self.captcha_solver = CaptchaSolver()

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
            
            if response.status_code != 200:
                raise Exception(f'Failed to fetch course data for {group_code}. Status: {response.status_code}')
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract required values
            req_fregkey_input = soup.find('input', {'name': 'reqFregkey'})
            req_Paper_Type = soup.find('input', {'name': 'reqPaperType'})
            req_Session_value = soup.find('input', {'name': 'reqSession'})
            req_Sid = soup.find('input', {'name': 'reqSid'})
            req_with_class = soup.find('input', {'name': 'reqWithClass'})
            
            if not req_fregkey_input or not req_fregkey_input.get('value'):
                raise Exception('Student ID not found.')
            
            result = {
                'student_id': req_fregkey_input['value'],
                'paper_type': req_Paper_Type['value'],
                'req_session': req_Session_value['value'],
                'reqsid': req_Sid['value'],
                'req_with_class': req_with_class['value']
            }
            
            logger.info(f'student_id: {result["student_id"]}, paper_type: {result["paper_type"]}, '
                       f'req_session: {result["req_session"]}, reqsid: {result["reqsid"]}, '
                       f'req_with_class: {result["req_with_class"]}')
            
            return result
            
        except requests.RequestException as e:
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
            
            if response.status_code != 200:
                raise Exception(f'Failed to fetch course data for {group_code}. Status: {response.status_code}')
            
            soup = BeautifulSoup(response.content, 'html.parser')
            rows = soup.find_all('tr', align='center')
            
            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 3:
                    group_col = cols[2].get_text(strip=True)
                    group_type = cols[1].get_text(strip=True)
                    
                    if f'{group_type}{group_col}' == group_code:
                        checkbox = row.find('input', {'name': 'reqMid'})
                        if checkbox and checkbox.get('value'):
                            return checkbox['value']
            
            raise Exception(f'Group {group_code} not found for unit {unit_code}')
            
        except requests.RequestException as e:
            raise Exception(f'Request failed: {str(e)}')

    def login(self, student_id: str, password: str) -> dict:
        """
        Handle the login process including CAPTCHA.
        
        Args:
            student_id (str): Student ID for login
            password (str): Password for login
            
        Returns:
            dict: Dictionary containing login result and student data
        """
        try:
            # Get login page
            response = self.session.get(LOGIN_URL, headers=self.headers, verify=False)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find CAPTCHA image
            captcha_img = soup.find('img', {'src': lambda src: src and 'Kaptcha.jpg' in src})
            if not captcha_img:
                raise Exception('CAPTCHA image not found')
            
            # Get CAPTCHA image
            captcha_src = captcha_img['src'].lstrip('../')
            captcha_url = f"{LOGIN_URL.rsplit('/', 1)[0]}/{captcha_src}"
            captcha_response = self.session.get(captcha_url, headers=self.headers, verify=False)
            
            if captcha_response.status_code != 200:
                raise Exception('Failed to retrieve CAPTCHA image')
            
            # Solve CAPTCHA using CaptchaSolver
            captcha_solution = self.captcha_solver.solve(captcha_response.content)
            logger.info(f'CAPTCHA solved successfully: {captcha_solution}')
            
            # Get preKap value
            prekap_input = soup.find('input', {'name': 'preKap'})
            if not prekap_input:
                raise Exception('preKap value not found')
            
            prekap_value = prekap_input.get('value')
            
            # Attempt login
            payload = {
                'preKap': prekap_value,
                'reqFregkey': student_id,
                'reqPassword': password,
                'kaptchafield': captcha_solution
            }
            
            login_response = self.session.post(
                LOGIN_PROCESS_URL,
                headers=self.headers,
                data=payload,
                verify=False
            )
            
            if 'Invalid' in login_response.text:
                raise Exception('Login failed. Please check your credentials.')
            
            # Get home page data
            home_data = self.get_home_page_data()
            
            return {
                'success': 'Login successful',
                'students_data': home_data
            }
            
        except Exception as e:
            raise Exception(f'Login process failed: {str(e)}')

    def get_home_page_data(self) -> tuple:
        """
        Get data from the home page after successful login.
        
        Returns:
            tuple: (data dictionary, cookies dictionary)
        """
        try:
            resp1 = self.session.get(HOME_URL, headers=self.headers, verify=False)
            resp2 = self.session.get(COURSE_REGISTRATION_URL, headers=self.headers, verify=False)
            
            if resp2.status_code != 200:
                logger.info(f'Failed to retrieve home page. Status code: {resp2.status_code}')
                return None, self.session.cookies.get_dict()
            
            soup = BeautifulSoup(resp2.content, 'html.parser')
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
            raise Exception(f'Failed to get home page data: {str(e)}') 