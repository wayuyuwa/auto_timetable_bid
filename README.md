# Auto timetable bid robot with selenium

## Introduction
You hate UTAR? So do I! So I made this bot to bid for my timetable. This bot is written in Python and uses Selenium to automate the bidding process.

## Installation
1. Install Python 3.7 or above
2. Downlaod this repository
   In git bash, run the following command:
    ```bash
    git clone
    ```
    Or you can download the repository as a zip file and extract it.
2. I will suggest you to create a virtual environment for this project to avoid any conflicts with your existing Python packages. You can do so by running the following command:
    ```console
    python -m venv venv
    ```
    This will create a virtual environment in the `venv` folder in current directory.  
    Theb activate the virtual environment by running the following command:
    ```console
    venv\Scripts\activate
    ```
    You may also skip this step if you want to install the packages globally.
4. Install the required packages by running the following command:
    ```console
    pip install -r requirements.txt
    ```
    If you are in a virtual environment, the packages will be installed in the virtual environment. Otherwise, the packages will be installed globally.
5. Create a file called `config.py` in the current directory of the project. You can copy the content of `config_template.py` to `config.py` and fill in the required information.
    ```python
    # config.py
    STUDENT_ID = "your_student_id"
    PASSWORD = "your_password"
    ```
    Replace `your_student_id` and `your_password` with your UTAR student ID and password.  
    etc:
    ```python
    # config.py
    STUDENT_ID = "123456789"
    PASSWORD = "password"
    ```
6. Run the bot by running the following command:
    ```console
    python fuck_utar.py
    ```
    The bot will open a browser and start the bidding process.

## License Disclaimer

This project is licensed under the GNU General Public License v3.0. 

[GNU GPLv3.0](https://choosealicense.com/licenses/gpl-3.0)

## Disclaimer
Although I made this bot, it is for educational purposes only. Please use it responsibly.