"""
Main window implementation for the UTAR Course Registration Scraper GUI.
"""

import sys
import os
import logging
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                           QHBoxLayout, QPushButton, QLabel, QComboBox, 
                           QLineEdit, QTextEdit, QMessageBox, QFileDialog,
                           QCheckBox, QGroupBox, QTabWidget, QToolButton, QStyle)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon
from ..services.bidding_service import BiddingService
from ..services.worker_thread import WorkerThreadManager
from ..models.course import Course
from ..models.bid_result import BidResult, BidStatus
from ..utils.config import (
    WINDOW_TITLE, WINDOW_SIZE, WINDOW_POSITION,
    BASE_DIR
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

class MainWindow(QMainWindow):
    """Main window for the UTAR Course Registration Scraper."""
    
    def __init__(self):
        """Initialize the main window."""
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.setGeometry(*WINDOW_POSITION, *WINDOW_SIZE)
        
        # Set window icon
        resources_dir = os.path.join(BASE_DIR, "resources")
        icon_path = os.path.join(resources_dir, "icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            logger.info(f"Set application icon from: {icon_path}")
        else:
            logger.warning(f"Icon file not found at: {icon_path}")
        
        # Initialize settings
        self.settings = Settings()
        
        # Initialize service layer
        self.bidding_service = BiddingService()
        self.thread_manager = WorkerThreadManager()
        
        # Initialize course list
        self.courses = []
        
        self._setup_ui()
        self._setup_logging()
        self._connect_service_signals()
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
    
    def _connect_service_signals(self):
        """Connect bidding service signals to GUI update methods."""
        # Login signals
        self.bidding_service.login_progress.connect(self._on_login_progress)
        self.bidding_service.login_completed.connect(self._on_login_completed)
        
        # Bidding signals
        self.bidding_service.bid_started.connect(self._on_bidding_started)
        self.bidding_service.bid_progress.connect(self._on_bid_progress)
        self.bidding_service.bid_course_completed.connect(self._on_course_completed)
        self.bidding_service.bid_all_completed.connect(self._on_bidding_completed)
        
        # Error signals
        self.bidding_service.session_expired.connect(self._on_session_expired)
        self.bidding_service.network_error.connect(self._on_network_error)
        self.bidding_service.operation_cancelled.connect(self._on_operation_cancelled)
    
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
        self.method_combo.addItems(["BeautifulSoup", "Playwright"])
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
        
        # Playwright options group
        self.playwright_group = QGroupBox("Playwright Options")
        playwright_layout = QVBoxLayout()
        self.headless_checkbox = QCheckBox("Run in headless mode")
        self.headless_checkbox.setToolTip("Run Playwright in headless mode (no GUI)")
        self.headless_checkbox.stateChanged.connect(self._on_headless_changed)
        playwright_layout.addWidget(self.headless_checkbox)
        self.playwright_group.setLayout(playwright_layout)
        scraping_layout.addWidget(self.playwright_group)

        # Registration options group
        registration_group = QGroupBox("Registration Options")
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
        resources_dir = os.path.join(BASE_DIR, "resources")
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
        self.headless_checkbox.setChecked(self.settings.get_headless_mode())
        print(str(self.settings.get_max_retries()))
        self.retry_combo.setCurrentText(str(self.settings.get_max_retries()))
        self._on_method_changed(self.method_combo.currentText())
    
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
        self.playwright_group.setVisible(method == "Playwright")
        self.retry_combo.setVisible(method == "BeautifulSoup")
        self.bidding_service.set_scraper_type(method)
        self._save_settings()
        logger.info(f"Scraping method changed to: {method}")
    
    def _on_headless_changed(self, state: int):
        """Handle headless mode checkbox state change."""
        self.bidding_service.set_headless_mode(bool(state))
        self._save_settings()
        logger.info(f"Headless mode {'enabled' if state else 'disabled'}")

    def _on_retry_changed(self, value: str):
        """Handle max retries selection change."""
        self._save_settings()
        logger.info(f"Max retries changed to: {value}")
    
    def _execute_scraping(self):
        """Execute the bidding operation using the service layer."""
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
        self.results_display.clear()
        
        logger.info(f"Starting bidding with {len(self.courses)} courses...")
        
        # Start login in worker thread
        self.thread_manager.start_worker(
            self.bidding_service.login,
            student_id,
            password
        )
    
    def _stop_scraping(self):
        """Stop the current bidding operation."""
        logger.info("Stopping bidding operation...")
        self.bidding_service.cancel()
        self.thread_manager.stop_all()
        
        # Reset button states
        self.execute_button.setEnabled(True)
        self.stop_button.setEnabled(False)
    
    def _on_login_progress(self, message: str):
        """Handle login progress updates."""
        self.results_display.append(f"[LOGIN] {message}")
    
    def _on_login_completed(self, success: bool, message: str):
        """Handle login completion."""
        if success:
            self.results_display.append(f"[LOGIN] ✓ {message}")
            # Start bidding after successful login
            self.thread_manager.start_worker(
                self.bidding_service.bid_courses,
                self.courses
            )
        else:
            self.results_display.append(f"[LOGIN] ✗ {message}")
            QMessageBox.warning(self, "Login Failed", message)
            self.execute_button.setEnabled(True)
            self.stop_button.setEnabled(False)
    
    def _on_bidding_started(self, total: int):
        """Handle bidding start."""
        self.results_display.append(f"\n[BIDDING] Starting to bid {total} courses...\n")
    
    def _on_bid_progress(self, message: str, current: int, total: int):
        """Handle bidding progress updates."""
        self.results_display.append(f"[{current}/{total}] {message}")
    
    def _on_course_completed(self, result: BidResult):
        """Handle individual course bidding completion."""
        status_symbol = "✓" if result.is_successful() else "✗"
        self.results_display.append(f"  {status_symbol} {result.course_code}: {result.message}")
    
    def _on_bidding_completed(self, success: bool, results: list):
        """Handle overall bidding completion."""
        self.results_display.append(f"\n[RESULT] Bidding completed.")
        
        # Count successes
        successful = sum(1 for r in results if r.is_successful())
        total = len(results)
        self.results_display.append(f"Successfully registered: {successful}/{total}")
        
        # Reset button states
        self.execute_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        
        if success:
            QMessageBox.information(self, "Success", f"All courses registered successfully!")
        else:
            QMessageBox.warning(self, "Completed with Errors", 
                              f"Registered {successful} out of {total} courses.")
    
    def _on_session_expired(self):
        """Handle session expiration."""
        self.results_display.append("\n[ERROR] Session expired. Please login again.")
        QMessageBox.warning(self, "Session Expired", "Your session has expired. Please try again.")
        self.execute_button.setEnabled(True)
        self.stop_button.setEnabled(False)
    
    def _on_network_error(self, error_msg: str):
        """Handle network errors."""
        self.results_display.append(f"\n[ERROR] Network error: {error_msg}")
        QMessageBox.critical(self, "Network Error", f"A network error occurred: {error_msg}")
        self.execute_button.setEnabled(True)
        self.stop_button.setEnabled(False)
    
    def _on_operation_cancelled(self):
        """Handle operation cancellation."""
        self.results_display.append("\n[CANCELLED] Operation cancelled by user.")
        self.execute_button.setEnabled(True)
        self.stop_button.setEnabled(False)
    
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
        <p><b>Playwright:</b> Handles dynamic content and executes JavaScript in a managed browser context.</p>
        <p><b>Note:</b> BeautifulSoup uses direct HTTP requests and is faster when JavaScript is not required.</p>
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
        if method and method.lower() in ['beautifulsoup', 'playwright']:
            method_map = {
                'beautifulsoup': 'BeautifulSoup',
                'playwright': 'Playwright'
            }
            formatted_method = method_map.get(method.lower())
            if formatted_method:
                self.method_combo.setCurrentText(formatted_method)
                self.settings.save_settings()
                logger.info(f"Set scraping method to: {formatted_method}")
                return True
        return False

    def closeEvent(self, event):
        """Handle the window close event to ensure proper cleanup."""
        # Stop any running operations
        if self.thread_manager.has_active_threads():
            logger.info("Application closing: Stopping active operations...")
            try:
                self.bidding_service.cancel()
                self.thread_manager.stop_all()
            except Exception as e:
                logger.error(f"Error during thread cleanup: {str(e)}")
        
        # Clean up service resources
        try:
            self.bidding_service.cleanup()
        except Exception as e:
            logger.error(f"Error during service cleanup: {str(e)}")
        
        # Save settings
        self._save_settings()
        
        # Accept the close event
        event.accept()