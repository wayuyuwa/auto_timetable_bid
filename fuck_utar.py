import os
import json
from time import sleep

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from config import *
import fuck_kaptcha

# Wait time for page loading
WAIT_TIME_SHORT = 3   #  3 seconds short waiting
WAIT_TIME_LONG  = 10  # 10 seconds long waiting

# Global constant variable, URLs
URL = "https://unitreg.utar.edu.my/portal/courseRegStu"
LOGIN_URL = URL + "/login.jsp"
REGISTER_URL = URL + "/registration/studentRegistrationSurvey.jsp"

# The function try to login the system if cookies are stored before
def tryLoginWithCookies(driver: webdriver):

    # If cookies.txt does not exist in current directory
    if not os.path.isfile("cookies.txt"):
        # Just back to the login page to login again
        return False

    # Open the file and read out all the cookies
    with open("cookies.txt", "r") as file:
        cookies = json.load(file)
        # Go to an 404 page to ensure cookies are set for the same site
        driver.get(URL+"/fuckyouutar")
        driver.delete_all_cookies()
        # Set cookies!
        for cookie in cookies:
            driver.add_cookie(cookie)
    # Go to the register url to see if login successful (The cookies may expired)
    driver.get(REGISTER_URL)
    try:
        expired = bool(driver.find_elements(
            By.XPATH, "//*[contains(text(), 'Session Expired')]"
        ))
    finally:
        if expired:
            return False
    
    return True
        
def login(driver: webdriver):
    # Say my appreciation to UTAR
    print("Fuck you UTAR!")
    print("Trying to login...")

    if not STUDENT_ID or not PASSWORD:
        raise Exception(
            "Student ID or password is not set! " \
            "Please refer to the guide in " \
            "https://github.com/Chin-Wai-Yee/auto_timetable_bid to set it"
        )

    # Go to login page
    driver.get(LOGIN_URL)

    # Wait for the page to be loaded
    try:
        WebDriverWait(driver, WAIT_TIME_SHORT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "form[name=frmParam]"))
        )
    except TimeoutException:
        driver.refresh()
        return False

    # Locate the input fields
    try:
        student_id_input = driver.find_element(By.CSS_SELECTOR, "input[name=reqFregkey]")
        password_input = driver.find_element(By.CSS_SELECTOR, "input[name=reqPassword]")
        kaptcha_input = driver.find_element(By.CSS_SELECTOR, "input[name=kaptchafield]")
    except NoSuchElementException:
        print("Element not found")
        return False

    # Solve kaptcha
    try:
        kaptcha_img = driver.find_element(
            # This XPATH find:
            # XPATH                    MEANING
            # //                       the element shall locate at anywhere
            # input                    the element shall be an input
            # [@name='kaptchafield']   the name attribute shall have the name "kaptchafield"
            # /..                      go to its parent
            # /img[i]                  and get the first img child
            By.XPATH, "//input[@name='kaptchafield']/../img[1]"
        ).screenshot_as_png
    except NoSuchElementException:
        print("Kaptcha not found")
        return False

    kaptcha_pass = fuck_kaptcha.getKaptchaText(kaptcha_img)

    # Enter all infomation and press enter
    student_id_input.send_keys(STUDENT_ID)
    password_input.send_keys(PASSWORD)
    kaptcha_input.send_keys(kaptcha_pass)
    kaptcha_input.send_keys(Keys.RETURN)

    # Wait to see if user successfully logged in
    try:
        WebDriverWait(driver, WAIT_TIME_SHORT).until(
            EC.presence_of_element_located((By.XPATH, "//span[contains(text(), 'Log Out')]"))
        )
    except TimeoutException:
        try:
            alert = driver.find_element(By.CLASS_NAME, "red").text
        finally:
            if "Invalid Student ID or Password" in alert:
                raise Exception(
                    "Your student ID or password is invalid"
                )
            return False
    
    return True

def storeCookies(driver: webdriver):
    cookies = driver.get_cookies()
    with open("cookies.txt", "w+") as file:
        json.dump(cookies, file)
        print("Cookies saved")

# Create a new instance of the Firefox driver
if __name__ == "__main__":
    
    driver = webdriver.Chrome()

    logged_in = tryLoginWithCookies(driver)

    if not logged_in:
        while(not login(driver)):
            print("Oh shit! Failed to login! UTAR sucks!")
            print("No worry lets try again!")

    print("We are in!")

    print("Storing cookies...yum yum yum")
    storeCookies(driver)

    driver.get(REGISTER_URL)

    # Wait for a minute
    sleep(60)

    # Close the driver
    driver.quit()