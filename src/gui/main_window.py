"""
Main window implementation for the UTAR Course Registration Scraper GUI.
"""

import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                           QHBoxLayout, QPushButton, QLabel, QComboBox, 
                           QLineEdit, QTextEdit, QMessageBox, QFileDialog,
                           QCheckBox, QGroupBox)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
import logging
from ..scrapers.beautifulsoup_scraper import BeautifulSoupScraper
from ..scrapers.selenium_scraper import SeleniumScraper
from ..utils.config import (
    WINDOW_TITLE, WINDOW_SIZE, WINDOW_POSITION,
    LOGIN_URL
)
from ..utils.settings import Settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ScraperThread(QThread):
    """Thread for running scraper operations."""
    finished = pyqtSignal(bool, str)
    progress = pyqtSignal(str)
    
    def __init__(self, scraper, method, url, student_id, password, timetable_file=None):
        super().__init__()
        self.scraper = scraper
        self.method = method
        self.url = url
        self.student_id = student_id
        self.password = password
        self.timetable_file = timetable_file
        self.is_running = True
        
    def run(self):
        """Run the scraper operation."""
        try:
            if not self.is_running:
                self.finished.emit(True, "Operation cancelled by user")
                return

            if self.method == "BeautifulSoup":
                if self.scraper.login(self.student_id, self.password):
                    if self.timetable_file:
                        # TODO: Implement timetable-based scraping for BeautifulSoup
                        self.finished.emit(True, "BeautifulSoup timetable scraping not implemented yet")
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
            else:  # Selenium
                if not self.is_running:
                    self.finished.emit(True, "Operation cancelled by user")
                    return

                if self.scraper.login(self.student_id, self.password):
                    if not self.is_running:
                        self.finished.emit(True, "Operation cancelled by user")
                        return

                    if self.timetable_file:
                        if self.scraper.register_courses(self.timetable_file):
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
                self.scraper.cleanup()
            except Exception as e:
                logger.error(f"Error during cleanup: {str(e)}")

class MainWindow(QMainWindow):
    """Main window for the UTAR Course Registration Scraper."""
    
    def __init__(self):
        """Initialize the main window."""
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.setGeometry(*WINDOW_POSITION, *WINDOW_SIZE)
        
        # Initialize settings
        self.settings = Settings()
        
        # Initialize scrapers
        self.beautifulsoup_scraper = BeautifulSoupScraper()
        self.selenium_scraper = SeleniumScraper()
        
        # Initialize scraper thread
        self.scraper_thread = None
        
        self._setup_ui()
        self._load_settings()
        
    def _setup_ui(self):
        """Set up the user interface."""
        # Create central widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # Method selection
        method_layout = QHBoxLayout()
        method_label = QLabel("Select Scraping Method:")
        self.method_combo = QComboBox()
        self.method_combo.addItems(["BeautifulSoup", "Selenium"])
        self.method_combo.currentTextChanged.connect(self._on_method_changed)
        method_layout.addWidget(method_label)
        method_layout.addWidget(self.method_combo)
        layout.addLayout(method_layout)
        
        # Selenium options group
        self.selenium_group = QGroupBox("Selenium Options")
        selenium_layout = QVBoxLayout()
        
        # Headless mode checkbox
        self.headless_checkbox = QCheckBox("Run in headless mode")
        self.headless_checkbox.stateChanged.connect(self._on_headless_changed)
        selenium_layout.addWidget(self.headless_checkbox)
        
        self.selenium_group.setLayout(selenium_layout)
        layout.addWidget(self.selenium_group)
        
        # URL input
        url_layout = QHBoxLayout()
        url_label = QLabel("URL:")
        self.url_input = QLineEdit()
        self.url_input.setText(LOGIN_URL)
        url_layout.addWidget(url_label)
        url_layout.addWidget(self.url_input)
        layout.addLayout(url_layout)
        
        # Student ID input
        id_layout = QHBoxLayout()
        id_label = QLabel("Student ID:")
        self.id_input = QLineEdit()
        id_layout.addWidget(id_label)
        id_layout.addWidget(self.id_input)
        layout.addLayout(id_layout)
        
        # Password input
        pw_layout = QHBoxLayout()
        pw_label = QLabel("Password:")
        self.pw_input = QLineEdit()
        self.pw_input.setEchoMode(QLineEdit.Password)
        pw_layout.addWidget(pw_label)
        pw_layout.addWidget(self.pw_input)
        layout.addLayout(pw_layout)
        
        # Timetable file selection
        timetable_layout = QHBoxLayout()
        timetable_label = QLabel("Timetable File:")
        self.timetable_path = QLineEdit()
        self.timetable_path.setReadOnly(True)
        self.timetable_btn = QPushButton("Browse...")
        self.timetable_btn.clicked.connect(self._select_timetable)
        timetable_layout.addWidget(timetable_label)
        timetable_layout.addWidget(self.timetable_path)
        timetable_layout.addWidget(self.timetable_btn)
        layout.addLayout(timetable_layout)
        
        # Button layout
        button_layout = QHBoxLayout()
        
        # Execute button
        self.execute_button = QPushButton("Execute Scraping")
        self.execute_button.clicked.connect(self._execute_scraping)
        button_layout.addWidget(self.execute_button)
        
        # Stop button
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self._stop_scraping)
        self.stop_button.setEnabled(False)
        button_layout.addWidget(self.stop_button)
        
        layout.addLayout(button_layout)
        
        # Results display
        self.results_display = QTextEdit()
        self.results_display.setReadOnly(True)
        layout.addWidget(self.results_display)
    
    def _load_settings(self):
        """Load saved settings."""
        self.id_input.setText(self.settings.get_student_id())
        self.pw_input.setText(self.settings.get_password())
        self.timetable_path.setText(self.settings.get_timetable_file())
        last_method = self.settings.get_last_method()
        index = self.method_combo.findText(last_method)
        if index >= 0:
            self.method_combo.setCurrentIndex(index)
        self.headless_checkbox.setChecked(self.settings.get_headless_mode())
    
    def _save_settings(self):
        """Save current settings."""
        self.settings.update_settings(
            student_id=self.id_input.text(),
            password=self.pw_input.text(),
            timetable_file=self.timetable_path.text(),
            last_method=self.method_combo.currentText(),
            headless_mode=self.headless_checkbox.isChecked()
        )
    
    def _on_method_changed(self, method: str):
        """Handle method selection change."""
        self.selenium_group.setVisible(method == "Selenium")
    
    def _on_headless_changed(self, state: int):
        """Handle headless mode checkbox state change."""
        self._save_settings()
    
    def _select_timetable(self):
        """Open file dialog to select timetable file."""
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Select Timetable File",
            "",
            "Text Files (*.txt);;All Files (*.*)"
        )
        if filename:
            self.timetable_path.setText(filename)
            self._save_settings()
        
    def _execute_scraping(self):
        """Execute the selected scraping method."""
        method = self.method_combo.currentText()
        url = self.url_input.text()
        student_id = self.id_input.text()
        password = self.pw_input.text()
        timetable_file = self.timetable_path.text()
        
        if not student_id or not password:
            QMessageBox.warning(self, "Warning", "Please enter both Student ID and Password")
            return
        
        # Save settings before executing
        self._save_settings()
        
        # Disable execute button and enable stop button
        self.execute_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        
        # Create and start scraper thread
        scraper = self.selenium_scraper if method == "Selenium" else self.beautifulsoup_scraper
        if method == "Selenium":
            scraper.set_headless_mode(self.headless_checkbox.isChecked())
        self.scraper_thread = ScraperThread(
            scraper, method, url, student_id, password, timetable_file
        )
        self.scraper_thread.finished.connect(self._on_scraping_finished)
        self.scraper_thread.progress.connect(self._on_progress)
        self.scraper_thread.start()
    
    def _stop_scraping(self):
        """Stop the current scraping operation."""
        if self.scraper_thread and self.scraper_thread.isRunning():
            self.scraper_thread.stop()
            self.results_display.append("\nStopping WebDriver...")
        
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
            QMessageBox.information(self, "Success", "WebDriver stopped successfully")
        elif not success:
            QMessageBox.warning(self, "Warning", message)
    
    def _on_progress(self, message: str):
        """Handle progress updates."""
        self.results_display.append(message)

def main():
    """Main entry point for the application."""
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_()) 