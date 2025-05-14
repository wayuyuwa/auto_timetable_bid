"""
Main window implementation for the UTAR Course Registration Scraper GUI.
"""

import sys
import socket
import requests
import time
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                           QHBoxLayout, QPushButton, QLabel, QComboBox, 
                           QLineEdit, QTextEdit, QMessageBox, QFileDialog,
                           QCheckBox, QGroupBox, QTabWidget, QToolButton, QStyle)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QIcon, QFont
import logging
import os
from ..scrapers.beautifulsoup_scraper import BeautifulSoupScraper
from ..scrapers.selenium_scraper import SeleniumScraper
from ..utils.config import (
    WINDOW_TITLE, WINDOW_SIZE, WINDOW_POSITION,
    LOGIN_URL
)
from ..utils.settings import Settings
from ..utils.logger import setup_logger, setup_crash_logging
from .course_manager import CourseManager

# Configure logging
logger = setup_logger(__name__)
crash_logger = setup_crash_logging()

class GUILogHandler(logging.Handler):
    """Custom logging handler that emits log messages to the GUI."""
    
    def __init__(self, text_widget):
        """Initialize the handler with a text widget."""
        super().__init__()
        self.text_widget = text_widget
        self.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    
    def emit(self, record):
        """Emit a log record to the text widget."""
        msg = self.format(record)
        self.text_widget.append(msg)

class ScraperThread(QThread):
    """Thread for running scraper operations."""
    finished = pyqtSignal(bool, str)
    progress = pyqtSignal(str)
    
    def __init__(self, scraper, method, student_id, password, courses=None):
        super().__init__()
        self.scraper = scraper
        self.method = method
        self.student_id = student_id
        self.password = password
        self.courses = courses or []
        self.is_running = True
        
    def run(self):
        """Run the scraper operation."""
        try:
            if not self.is_running:
                self.finished.emit(True, "Operation cancelled by user")
                return

            if self.method == "BeautifulSoup":
                try:
                    # Emit progress update for login attempt
                    self.progress.emit("Attempting to log in to UTAR course registration system...")
                    
                    if self.scraper.login(self.student_id, self.password):
                        if self.courses:
                            try:
                                self.progress.emit(f"Login successful. Attempting to register {len(self.courses)} courses...")
                                result_text, success = self.scraper.register_courses(self.courses)
                                self.finished.emit(success, result_text)
                            except Exception as e:
                                # Critical error that couldn't be handled in register_courses
                                logger.error(f"Critical error in course registration: {str(e)}")
                                self.finished.emit(False, f"Critical error in BeautifulSoup course registration: {str(e)}")
                        else:
                            home_data = self.scraper.get_home_page_data()
                            result_text = "BeautifulSoup Scraping Results:\n\n"
                            if home_data:
                                result_text += "Home Page Data:\n"
                                for key, value in home_data.items():
                                    result_text += f"{key}: {value}\n"
                            else:
                                result_text += "No data found on home page.\n"
                            self.finished.emit(True, result_text)
                except Exception as e:
                    # Unexpected error
                    logger.error(f"Unexpected error: {str(e)}")
                    self.finished.emit(False, f"An unexpected error occurred: {str(e)}")
            else:  # Selenium
                if not self.is_running:
                    self.finished.emit(True, "Operation cancelled by user")
                    return

                if self.scraper.login(self.student_id, self.password):
                    if not self.is_running:
                        self.finished.emit(True, "Operation cancelled by user")
                        return

                    if self.courses:
                        if self.scraper.register_courses(self.courses):
                            self.finished.emit(True, "Course registration completed successfully!")
                        else:
                            self.finished.emit(False, "Course registration failed. Check the logs for details.")
                    else:
                        # TODO: Implement basic scraping for Selenium
                        self.finished.emit(True, "Selenium basic scraping not implemented yet")
        except Exception as e:
            error_msg = str(e)
            if "WebDriver is being cleaned up" in error_msg:
                self.finished.emit(True, "WebDriver stopped successfully")
            else:
                self.finished.emit(False, f"Scraping failed: {error_msg}")
        finally:
            if self.method == "Selenium":
                try:
                    self.scraper.cleanup()
                except Exception as e:
                    logger.error(f"Error during cleanup: {str(e)}")
    
    def stop(self):
        """Stop the scraper operation."""
        self.is_running = False
        if self.method == "Selenium":
            try:
                self.scraper.cancel()
                self.scraper.cleanup()
            except Exception as e:
                logger.error(f"Error during cleanup: {str(e)}")
        elif self.method == "BeautifulSoup":
            try:
                self.scraper.cancel()
            except Exception as e:
                logger.error(f"Error during cancellation: {str(e)}")

class MainWindow(QMainWindow):
    """Main window for the UTAR Course Registration Scraper."""
    
    def __init__(self):
        """Initialize the main window."""
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.setGeometry(*WINDOW_POSITION, *WINDOW_SIZE)
        
        # Set window icon
        resources_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "resources")
        icon_path = os.path.join(resources_dir, "icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            logger.info(f"Set application icon from: {icon_path}")
        else:
            logger.warning(f"Icon file not found at: {icon_path}")
        
        # Initialize settings
        self.settings = Settings()
        
        # Initialize scrapers
        self.beautifulsoup_scraper = BeautifulSoupScraper()
        self.selenium_scraper = SeleniumScraper()
        
        # Initialize scraper thread
        self.scraper_thread = None
        
        # Initialize course list
        self.courses = []
        
        self._setup_ui()
        self._setup_logging()
        self._load_settings()
        self._load_courses()
    
    def _setup_logging(self):
        """Set up logging to GUI."""
        # Create GUI log handler
        self.gui_handler = GUILogHandler(self.results_display)
        self.gui_handler.setLevel(logging.INFO)
        
        # Add handler to root logger
        root_logger = logging.getLogger()
        root_logger.addHandler(self.gui_handler)
        
        # Log initial message
        logger.info("Application started")
    
    def _setup_ui(self):
        """Set up the user interface."""
        # Create central widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # Create tab widget
        tab_widget = QTabWidget()
        layout.addWidget(tab_widget)
        
        # Create scraping tab
        scraping_tab = QWidget()
        scraping_layout = QVBoxLayout(scraping_tab)
        
        # Method selection
        method_group = QGroupBox("Scraping Method")
        method_layout = QHBoxLayout()
        method_label = QLabel("Select Method:")
        self.method_combo = QComboBox()
        self.method_combo.addItems(["BeautifulSoup", "Selenium"])
        self.method_combo.currentTextChanged.connect(self._on_method_changed)
        method_layout.addWidget(method_label)
        method_layout.addWidget(self.method_combo)
        
        # Add info button
        info_button = QToolButton()
        info_button.setIcon(self.style().standardIcon(QStyle.SP_MessageBoxInformation))
        info_button.setToolTip("Click to learn about the differences between methods")
        info_button.setStyleSheet("background: transparent; border: none;")
        info_button.setCursor(Qt.PointingHandCursor)
        info_button.clicked.connect(self._show_method_info)
        method_layout.addWidget(info_button)
        
        method_group.setLayout(method_layout)
        scraping_layout.addWidget(method_group)
        
        # Selenium options group
        self.selenium_group = QGroupBox("Selenium Options")
        selenium_layout = QVBoxLayout()
        self.headless_checkbox = QCheckBox("Run in headless mode")
        self.headless_checkbox.setToolTip("Run Selenium in headless mode (no GUI)")
        self.headless_checkbox.stateChanged.connect(self._on_headless_changed)
        selenium_layout.addWidget(self.headless_checkbox)
        self.selenium_group.setLayout(selenium_layout)
        scraping_layout.addWidget(self.selenium_group)

        # Registration options group
        registration_group = QGroupBox("Registration Options (Not applicable for Selenium)")
        registration_layout = QHBoxLayout()
        retry_label = QLabel("Max Retries:")
        self.retry_combo = QComboBox()
        self.retry_combo.addItems(["1", "2", "3", "5", "10", "50", "100", "999"])
        self.retry_combo.setCurrentText("999")
        self.retry_combo.currentTextChanged.connect(self._on_retry_changed)
        registration_layout.addWidget(retry_label)
        registration_layout.addWidget(self.retry_combo)
        registration_group.setLayout(registration_layout)
        scraping_layout.addWidget(registration_group)
        
        # Credentials group
        credentials_group = QGroupBox("Login Credentials")
        credentials_layout = QVBoxLayout()
        
        # Student ID input
        id_layout = QHBoxLayout()
        id_label = QLabel("Student ID:")
        self.id_input = QLineEdit()
        self.id_input.setPlaceholderText("Enter your student ID e.g. 2101234")
        self.id_input.editingFinished.connect(self._save_settings)
        id_layout.addWidget(id_label)
        id_layout.addWidget(self.id_input)
        credentials_layout.addLayout(id_layout)
        
        # Password input
        pw_layout = QHBoxLayout()
        pw_label = QLabel("Password:")
        self.pw_input = QLineEdit()
        self.pw_input.setPlaceholderText("Enter your password")
        self.pw_input.editingFinished.connect(self._save_settings)
        self.pw_input.setEchoMode(QLineEdit.Password)
        
        # Create custom eye icons
        resources_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "resources")
        eye_open_path = os.path.join(resources_dir, "eye-open.svg")
        eye_closed_path = os.path.join(resources_dir, "eye-closed.svg")
        
        # Create the show/hide password button with custom icons
        show_pw_button = QToolButton()
        show_pw_button.setStyleSheet("background: transparent; border: none;")
        self.eye_open_icon = QIcon(eye_open_path)
        self.eye_closed_icon = QIcon(eye_closed_path)
        
        # Set the initial icon (closed eye when password is hidden)
        show_pw_button.setIcon(self.eye_closed_icon)
        # show_pw_button.setIconSize(Qt.QSize(16, 16))
        show_pw_button.setCheckable(True)
        show_pw_button.setToolTip("Show password")
        
        # Toggle password visibility and icon when button is clicked
        show_pw_button.toggled.connect(lambda checked: [
            self.pw_input.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password),
            show_pw_button.setIcon(self.eye_open_icon if checked else self.eye_closed_icon),
            show_pw_button.setToolTip("Hide password" if checked else "Show password")
        ])
        
        pw_layout.addWidget(pw_label)
        pw_layout.addWidget(self.pw_input)
        pw_layout.addWidget(show_pw_button)
        credentials_layout.addLayout(pw_layout)
        
        credentials_group.setLayout(credentials_layout)
        scraping_layout.addWidget(credentials_group)
        
        # Course management group
        course_group = QGroupBox("Course Management")
        course_layout = QVBoxLayout()
        
        # Course management button
        manage_courses_btn = QPushButton("Manage Courses")
        manage_courses_btn.clicked.connect(self._open_course_manager)
        manage_courses_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                padding: 8px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        course_layout.addWidget(manage_courses_btn)
        
        course_group.setLayout(course_layout)
        scraping_layout.addWidget(course_group)
        
        # Action buttons
        button_group = QGroupBox("Actions")
        button_layout = QHBoxLayout()
        
        self.execute_button = QPushButton("Execute Scraping")
        self.execute_button.clicked.connect(self._execute_scraping)
        self.execute_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 8px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)
        
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self._stop_scraping)
        self.stop_button.setEnabled(False)
        self.stop_button.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                padding: 8px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #d32f2f;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)
        
        button_layout.addWidget(self.execute_button)
        button_layout.addWidget(self.stop_button)
        button_group.setLayout(button_layout)
        scraping_layout.addWidget(button_group)
        
        # Results display
        results_group = QGroupBox("Results")
        results_layout = QVBoxLayout()
        self.results_display = QTextEdit()
        self.results_display.setReadOnly(True)
        # Auto-scroll to bottom when content is added
        self.results_display.textChanged.connect(
            lambda: self.results_display.verticalScrollBar().setValue(
            self.results_display.verticalScrollBar().maximum()
            )
        )
        results_layout.addWidget(self.results_display)
        results_group.setLayout(results_layout)
        scraping_layout.addWidget(results_group)
        
        # Add scraping tab
        tab_widget.addTab(scraping_tab, "Course Registration")
        
        # Set window style
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #ddd;
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QLineEdit, QComboBox {
                padding: 6px;
                border: 1px solid #ddd;
                border-radius: 4px;
                background-color: white;
            }
            QTextEdit {
                border: 1px solid #ddd;
                border-radius: 4px;
                background-color: white;
            }
            QTabWidget::pane {
                border: 1px solid #ddd;
                border-radius: 4px;
                background-color: white;
            }
            QTabBar::tab {
                background-color: #f8f9fa;
                border: 1px solid #ddd;
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                padding: 8px 16px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background-color: white;
                border-bottom: 1px solid white;
            }
        """)
    
    def _load_settings(self):
        """Load saved settings."""
        self.id_input.setText(self.settings.get_student_id())
        self.pw_input.setText(self.settings.get_password())
        self.method_combo.setCurrentText(self.settings.get_method())
        self._on_method_changed(self.method_combo.currentText())
        self.headless_checkbox.setChecked(self.settings.get_headless_mode())
        self.retry_combo.setCurrentText = str(self.settings.get_max_retries())
    
    def _save_settings(self):
        """Save current settings."""
        self.settings.update_settings(
            student_id=self.id_input.text(),
            password=self.pw_input.text(),
            method=self.method_combo.currentText(),
            headless_mode=self.headless_checkbox.isChecked(),
            max_retries=int(self.retry_combo.currentText())
        )
    
    def _on_method_changed(self, method: str):
        """Handle method selection change."""
        self.selenium_group.setVisible(method == "Selenium")
        self._save_settings()
        logger.info(f"Scraping method changed to: {method}")
    
    def _on_headless_changed(self, state: int):
        """Handle headless mode checkbox state change."""
        self._save_settings()
        logger.info(f"Headless mode {'enabled' if state else 'disabled'}")

    def _on_retry_changed(self, value: str):
        """Handle max retries selection change."""
        self._save_settings()
        logger.info(f"Max retries changed to: {value}")
    
    def _execute_scraping(self):
        """Execute the selected scraping method."""
        method = self.method_combo.currentText()
        student_id = self.id_input.text()
        password = self.pw_input.text()
        
        if not student_id or not password:
            QMessageBox.warning(self, "Warning", "Please enter both Student ID and Password")
            return
        
        if not self.courses:
            QMessageBox.warning(self, "Warning", "Please add courses in the Course Manager first")
            return
        
        # Disable execute button and enable stop button
        self.execute_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        
        logger.info(f"Starting {method} scraping with {len(self.courses)} courses...")
        
        # Create and start scraper thread
        scraper = self.selenium_scraper if method == "Selenium" else self.beautifulsoup_scraper
        if method == "Selenium":
            scraper.set_headless_mode(self.headless_checkbox.isChecked())
        elif method == "BeautifulSoup":
            scraper.set_max_retries(int(self.retry_combo.currentText()))

        self.scraper_thread = ScraperThread(
            scraper, method, student_id, password, self.courses
        )
        self.scraper_thread.finished.connect(self._on_scraping_finished)
        self.scraper_thread.progress.connect(self._on_progress)
        self.scraper_thread.start()
    
    def _stop_scraping(self):
        """Stop the current scraping operation."""
        if self.scraper_thread and self.scraper_thread.isRunning():
            logger.info("Stopping scraping operation...")
            self.scraper_thread.stop()
        
        # Reset button states
        self.execute_button.setEnabled(True)
        self.stop_button.setEnabled(False)
    
    def _on_scraping_finished(self, success: bool, message: str):
        """Handle scraping completion."""
        self.results_display.setText(message)
        
        # Reset button states
        self.execute_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        
        if "WebDriver stopped successfully" in message:
            logger.info("WebDriver stopped successfully")
            QMessageBox.information(self, "Success", "WebDriver stopped successfully")
        elif not success:
            logger.error(f"Scraping failed: {message}")
            QMessageBox.warning(self, "Warning", message)
        else:
            logger.info("Scraping completed successfully")
    
    def _on_progress(self, message: str):
        """Handle progress updates."""
        self.results_display.append(message)
        logger.info(message)
    
    def _open_course_manager(self):
        """Open the course manager dialog."""
        logger.info("Opening course manager...")
        dialog = CourseManager(self)
        dialog.course_updated.connect(self._on_courses_updated)
        dialog.exec_()
    def _on_courses_updated(self, courses):
        """Handle course updates."""
        self.courses = courses
        logger.info(f"Courses updated: {len(courses)} courses loaded")

    def _show_method_info(self):
        """Show information about the different scraping methods."""
        info_text = """
        <h3>Scraping Methods</h3>
        <p><b>BeautifulSoup:</b> Faster execution, lower resource usage, no browser required.</p>
        <p><b>Selenium:</b> Handles dynamic content, executes JavaScript, simulates real browser behavior.</p>
        <p><b>Note:</b> BeautifulSoup should be faster but I didn't test both.</p>
        """
        
        msg = QMessageBox(self)
        msg.setWindowTitle("Scraping Methods Information")
        msg.setTextFormat(Qt.RichText)
        msg.setText(info_text)
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec_()

    def _load_courses(self):
        """Load courses from the course manager."""
        try:
            from .course_manager import CourseManager
            course_manager = CourseManager(self)
            self.courses = course_manager.get_courses()
            logger.info(f"Loaded {len(self.courses)} courses on startup")
        except Exception as e:
            logger.error(f"Failed to load courses on startup: {str(e)}")
            self.courses = []
            
    def set_timetable_file(self, file_path):
        """Set the timetable file path."""
        if file_path and os.path.exists(file_path):
            try:
                # Determine file type by extension
                if file_path.lower().endswith('.json'):
                    # Import from JSON
                    import json
                    with open(file_path, 'r') as f:
                        data = json.load(f)
                        from ..utils.timetable_reader import Course
                        courses = [Course(**course) for course in data]
                else:
                    # Default to timetable text file format
                    from ..utils.timetable_reader import TimetableReader
                    courses = TimetableReader.read_timetable(file_path)
                
                if courses:
                    from .course_manager import CourseManager
                    course_manager = CourseManager(self)
                    course_manager.set_courses(courses)  # Set courses in the course manager
                    self.courses = courses
                    logger.info(f"Loaded {len(courses)} courses from file: {file_path}")
                    return True
                else:
                    logger.warning(f"No courses found in file: {file_path}")
            except Exception as e:
                logger.error(f"Failed to load courses from file: {str(e)}")
        else:
            logger.error(f"File not found or invalid path: {file_path}")
        return False
    
    def set_method(self, method):
        """Set the scraping method."""
        if method and method.lower() in ['beautifulsoup', 'selenium']:
            method_map = {
                'beautifulsoup': 'BeautifulSoup',
                'selenium': 'Selenium'
            }
            formatted_method = method_map.get(method.lower())
            if formatted_method:
                self.method_combo.setCurrentText(formatted_method)
                self.settings.save_settings()
                logger.info(f"Set scraping method to: {formatted_method}")
                return True
        return False

def main(args=None):
    """Main entry point for the application."""
    app = QApplication(sys.argv)
    window = MainWindow()
    # Apply command line arguments if provided
    if args:
        if args.timetable_file:
            window.set_timetable_file(args.timetable_file)
        if args.method:
            window.set_method(args.method)
        if args.start:
            # Automatically start the scraping process
            window._execute_scraping()
    window.show()
    sys.exit(app.exec_())