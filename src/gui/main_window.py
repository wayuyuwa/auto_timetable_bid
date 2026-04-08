"""Main window implementation for the UTAR Course Registration Scraper GUI."""

import json
import logging
import os
import sys
import threading
import time

from ..scrapers.playwright_scraper import PlaywrightScraper
from ..scrapers.request_scraper import RequestScraper

from PyQt5 import uic
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QApplication, QComboBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
    QTextEdit, QVBoxLayout, QWidget,
)
from ..utils.config import BASE_DIR, WINDOW_POSITION, WINDOW_SIZE, WINDOW_TITLE
from ..utils.logger import setup_crash_logging, setup_logger
from ..utils.settings import Settings
from .course_manager import CourseManagerWidget
from .styles import apply_stylesheet

logger = setup_logger(__name__)
setup_crash_logging()


class GUILogHandler(logging.Handler):
    """Custom logging handler that emits log messages to the GUI."""

    def __init__(self, text_widget: QTextEdit):
        super().__init__()
        self.text_widget = text_widget
        self.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

    def emit(self, record):
        msg = self.format(record)
        if self.text_widget:
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
        try:
            if not self.is_running:
                self.finished.emit(True, "Operation cancelled by user")
                return

            self.scraper.reset_cancellation()
            if self.method == "Request":
                try:
                    self.progress.emit("Attempting to log in to UTAR course registration system...")
                    if self.scraper.login(self.student_id, self.password):
                        if self.courses:
                            try:
                                self.progress.emit(
                                    f"Login successful. Attempting to register {len(self.courses)} courses..."
                                )
                                result_text, success = self.scraper.register_courses(self.courses)
                                self.finished.emit(success, result_text)
                            except Exception as error:
                                logger.error(f"Critical error in course registration: {error}")
                                self.finished.emit(
                                    False,
                                    f"Critical error in request mode course registration: {error}",
                                )
                        else:
                            home_data = self.scraper.get_home_page_data()
                            result_text = "Request Mode Results:\n\n"
                            if home_data:
                                result_text += "Home Page Data:\n"
                                for key, value in home_data.items():
                                    result_text += f"{key}: {value}\n"
                            else:
                                result_text += "No data found on home page.\n"
                            self.finished.emit(True, result_text)
                except Exception as error:
                    logger.error(f"Unexpected error: {error}")
                    self.finished.emit(False, f"An unexpected error occurred: {error}")
            else:
                if not self.is_running:
                    self.finished.emit(True, "Operation cancelled by user")
                    return

                try:
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
                            self.finished.emit(True, "Playwright browser flow completed")
                except Exception as error:
                    self.finished.emit(False, str(error))
        except Exception as error:
            error_msg = str(error)
            if "Operation cancelled by user" in error_msg or "WebDriver is being cleaned up" in error_msg:
                self.finished.emit(True, "Operation cancelled by user")
            else:
                self.finished.emit(False, f"Scraping failed: {error_msg}")
        finally:
            if self.method == "Playwright" and self.scraper:
                try:
                    self.scraper.cleanup()
                except Exception as error:
                    logger.error(f"Error during cleanup: {error}")

    def stop(self):
        """Stop the scraper operation."""

        self.is_running = False
        if self.scraper:
            try:
                self.scraper.cancel()
                if self.method == "Playwright":

                    def force_quit_after_timeout():
                        time.sleep(5)
                        if hasattr(self.scraper, "driver") and self.scraper.driver:
                            logger.warning("Forcing driver quit after timeout")
                            try:
                                driver_ref = self.scraper.driver
                                if driver_ref:
                                    driver_ref.quit()
                                self.scraper.driver = None
                            except Exception as error:
                                logger.error(f"Error during forced driver quit: {error}")

                    threading.Thread(target=force_quit_after_timeout, daemon=True).start()
            except Exception as error:
                logger.error(f"Error during cancellation: {error}")

class MainWindow(QMainWindow):
    """Main window for the UTAR Course Registration Scraper."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.setGeometry(*WINDOW_POSITION, *WINDOW_SIZE)

        resources_dir = os.path.join(BASE_DIR, "resources")
        icon_path = os.path.join(resources_dir, "icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.settings = Settings()
        self.request_scraper = RequestScraper()
        self.playwright_scraper = PlaywrightScraper()
        self.scraper_thread = None
        self.courses = []

        self._setup_ui()
        self._setup_logging()
        self._load_settings()
        self._load_courses()
        self._save_settings()

    def _setup_ui(self):
        """Load Qt Designer UI and wire signals."""
        ui_path = os.path.join(os.path.dirname(__file__), "main_window.ui")
        uic.loadUi(ui_path, self)

        apply_stylesheet(self)

        self.id_input = self.input_student_id
        self.pw_input = self.input_password
        self.headless_checkbox = self.check_headless
        self.execute_button = self.btn_start
        self.stop_button = self.btn_stop
        self.font_size_spin = self.spin_font_size
        
        # Inject the integrated Course Manager widget
        self.course_manager = CourseManagerWidget(self)
        self.page_courses.layout().addWidget(self.course_manager)
        self.course_manager.course_updated.connect(self._on_courses_updated)

        self._setup_navigation()
        self._setup_dynamic_controls()
        self._setup_connections()

    def _setup_navigation(self):
        """Wire sidebar navigation to stacked pages."""
        self.btn_login.clicked.connect(lambda: self.stackedWidget.setCurrentWidget(self.page_login))
        self.btn_courses.clicked.connect(lambda: self.stackedWidget.setCurrentWidget(self.page_courses))
        self.btn_config.clicked.connect(lambda: self.stackedWidget.setCurrentWidget(self.page_config))

        self.btn_login.setChecked(True)
        self.stackedWidget.setCurrentWidget(self.page_login)

    def _setup_dynamic_controls(self):
        """Add runtime controls needed by existing logic but not present in UI file."""
        form_extra = self.findChild(QFormLayout, "formLayout_extra")
        self.retry_label = QLabel("Max Retries")
        self.retry_combo = QComboBox()
        self.retry_combo.addItems(["1", "2", "3", "5", "10", "50", "100", "999"])
        self.retry_combo.setCurrentText("999")
        form_extra.addRow(self.retry_label, self.retry_combo)

        results_group = QGroupBox("Results")
        results_layout = QVBoxLayout(results_group)
        self.results_display = QTextEdit()
        self.results_display.setReadOnly(True)
        self.results_display.textChanged.connect(
            lambda: self.results_display.verticalScrollBar().setValue(
                self.results_display.verticalScrollBar().maximum()
            )
        )
        results_layout.addWidget(self.results_display)

        main_layout = self.findChild(QVBoxLayout, "verticalLayout_mainArea")
        main_layout.insertWidget(main_layout.count() - 1, results_group)

        self.pw_input.setEchoMode(QLineEdit.Password)
        self.show_pw_button = QPushButton("Show")
        self.show_pw_button.setCheckable(True)
        self.show_pw_button.setObjectName("btn_toggle_password")
        self.show_pw_button.toggled.connect(self._toggle_password_visibility)

        login_form = self.findChild(QFormLayout, "formLayout_login")
        pw_container = QWidget()
        pw_layout = QHBoxLayout(pw_container)
        pw_layout.setContentsMargins(0, 0, 0, 0)
        pw_layout.setSpacing(8)
        login_form.removeWidget(self.pw_input)
        pw_layout.addWidget(self.pw_input)
        pw_layout.addWidget(self.show_pw_button)
        login_form.setWidget(1, QFormLayout.FieldRole, pw_container)

    def _setup_connections(self):
        self.execute_button.clicked.connect(self._execute_scraping)
        self.stop_button.clicked.connect(self._stop_scraping)
        self.stop_button.setEnabled(False)

        self.id_input.editingFinished.connect(self._save_settings)
        self.pw_input.editingFinished.connect(self._save_settings)
        self.headless_checkbox.stateChanged.connect(self._on_headless_changed)
        self.retry_combo.currentTextChanged.connect(self._on_retry_changed)
        self.font_size_spin.valueChanged.connect(self._on_font_size_changed)

        self.radio_bs4.toggled.connect(self._on_engine_selection_changed)
        self.radio_playwright.toggled.connect(self._on_engine_selection_changed)

    def _setup_logging(self):
        self.gui_handler = GUILogHandler(self.results_display)
        self.gui_handler.setLevel(logging.INFO)
        logging.getLogger().addHandler(self.gui_handler)
        logger.info("Application started")

    def _toggle_password_visibility(self, checked: bool):
        self.pw_input.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        self.show_pw_button.setText("Hide" if checked else "Show")

    def _get_selected_method(self) -> str:
        if self.radio_bs4.isChecked(): return "Request"
        if self.radio_playwright.isChecked(): return "Playwright"
        return "Request"

    def _set_method_controls(self, method: str):
        if method == "Playwright": self.radio_playwright.setChecked(True)
        else: self.radio_bs4.setChecked(True)

    def _load_settings(self):
        self.id_input.setText(self.settings.get_student_id())
        self.pw_input.setText(self.settings.get_password())

        method = self.settings.get_method()
        if method == "BeautifulSoup": method = "Request"
        else: method = "Playwright"

        self._set_method_controls(method)
        self.headless_checkbox.setChecked(self.settings.get_headless_mode())
        self.retry_combo.setCurrentText(str(self.settings.get_max_retries()))
        self.font_size_spin.setValue(self.settings.get_font_size())
        self._apply_font_size(self.font_size_spin.value())
        self._on_method_changed(method)

    def _save_settings(self):
        self.settings.update_settings(
            student_id=self.id_input.text(),
            password=self.pw_input.text(),
            method=self._get_selected_method(),
            headless_mode=self.headless_checkbox.isChecked(),
            max_retries=int(self.retry_combo.currentText()),
            font_size=int(self.font_size_spin.value()),
        )

    def _apply_font_size(self, value: int):
        apply_stylesheet(self, value)

    def _on_font_size_changed(self, value: int):
        self._apply_font_size(value)
        self._save_settings()

    def _on_engine_selection_changed(self):
        self._on_method_changed(self._get_selected_method())

    def _on_method_changed(self, method: str):
        is_playwright = method == "Playwright"
        self.headless_checkbox.setVisible(is_playwright)
        self.label_timeout.setVisible(is_playwright)
        self.timeout.setVisible(is_playwright)
        self.retry_label.setVisible(not is_playwright)
        self.retry_combo.setVisible(not is_playwright)
        self._save_settings()
        logger.info(f"Scraping method changed to: {method}")

    def _on_headless_changed(self, state: int):
        self._save_settings()
        logger.info(f"Headless mode {'enabled' if state else 'disabled'}")

    def _on_retry_changed(self, value: str):
        self._save_settings()
        logger.info(f"Max retries changed to: {value}")

    def _execute_scraping(self):
        method = self._get_selected_method()
        student_id = self.id_input.text().strip()
        password = self.pw_input.text().strip()

        if not student_id or not password:
            QMessageBox.warning(self, "Warning", "Please enter both Student ID and Password")
            self.btn_login.setChecked(True)
            self.stackedWidget.setCurrentWidget(self.page_login)
            return

        if not self.courses:
            QMessageBox.warning(self, "Warning", "Please add courses first")
            self.btn_courses.setChecked(True)
            self.stackedWidget.setCurrentWidget(self.page_courses)
            return

        self.execute_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        logger.info(f"Starting {method} scraping with {len(self.courses)} courses...")

        scraper = self.playwright_scraper if method == "Playwright" else self.request_scraper
        if method == "Playwright":
            scraper.set_headless_mode(self.headless_checkbox.isChecked())
        else:
            scraper.set_max_retries(int(self.retry_combo.currentText()))

        self.scraper_thread = ScraperThread(scraper, method, student_id, password, self.courses)
        self.scraper_thread.finished.connect(self._on_scraping_finished)
        self.scraper_thread.progress.connect(self._on_progress)
        self.scraper_thread.start()

    def _stop_scraping(self):
        if self.scraper_thread and self.scraper_thread.isRunning():
            logger.info("Stopping scraping operation...")
            self.scraper_thread.stop()
        self.execute_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def _on_scraping_finished(self, success: bool, message: str):
        self.results_display.setText(message)
        self.execute_button.setEnabled(True)
        self.stop_button.setEnabled(False)

        if "stopped successfully" in message:
            logger.info("Browser automation stopped successfully")
            QMessageBox.information(self, "Success", "Browser automation stopped successfully")
        elif not success:
            logger.error(f"Scraping failed: {message}")
            QMessageBox.warning(self, "Warning", message)
        else:
            logger.info("Scraping completed successfully")

    def _on_progress(self, message: str):
        self.results_display.append(message)
        logger.info(message)

    def _on_courses_updated(self, courses):
        self.courses = courses
        logger.info(f"Courses updated: {len(courses)} courses loaded")

    def _load_courses(self):
        try:
            self.courses = self.course_manager.get_courses()
            logger.info(f"Loaded {len(self.courses)} courses on startup")
        except Exception as error:
            logger.error(f"Failed to load courses on startup: {error}")
            self.courses = []

    def set_timetable_file(self, file_path):
        if file_path and os.path.exists(file_path):
            try:
                if file_path.lower().endswith(".json"):
                    with open(file_path, "r", encoding="utf-8") as file:
                        data = json.load(file)
                        from ..utils.timetable_reader import Course
                        courses = [Course(**course) for course in data]
                else:
                    from ..utils.timetable_reader import TimetableReader
                    courses = TimetableReader.read_timetable(file_path)

                if courses:
                    self.course_manager.set_courses(courses)
                    self.courses = courses
                    logger.info(f"Loaded {len(courses)} courses from file: {file_path}")
                    return True
                logger.warning(f"No courses found in file: {file_path}")
            except Exception as error:
                logger.error(f"Failed to load courses from file: {error}")
        else:
            logger.error(f"File not found or invalid path: {file_path}")
        return False

    def set_method(self, method):
        method_map = {
            "request": "Request", "playwright": "Playwright",
            "beautifulsoup": "Request",
        }
        if method and method.lower() in method_map.keys():
            formatted_method = method_map.get(method.lower())
            if formatted_method:
                self._set_method_controls(formatted_method)
                self._on_method_changed(formatted_method)
                self.settings.save_settings()
                logger.info(f"Set scraping method to: {formatted_method}")
                return True
        return False

    def closeEvent(self, event):
        if self.scraper_thread and self.scraper_thread.isRunning():
            logger.info("Application closing: Stopping scraper thread...")
            try:
                self.scraper_thread.stop()
                self.scraper_thread.wait(1000)
            except Exception as error:
                logger.error(f"Error during shutdown cleanup: {error}")
        self._save_settings()
        event.accept()

def main(args=None):
    """Main entry point for the application."""

    app = QApplication(sys.argv)
    window = MainWindow()

    if args:
        if args.timetable_file:
            window.set_timetable_file(args.timetable_file)
        if args.method:
            window.set_method(args.method)
        if args.start:
            window._execute_scraping()

    window.show()
    sys.exit(app.exec_())
