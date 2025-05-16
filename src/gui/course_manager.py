"""
Course management window for the UTAR Course Registration Scraper.
"""

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                           QLabel, QLineEdit, QTableWidget, QTableWidgetItem,
                           QHeaderView, QMessageBox, QComboBox, QSpinBox,
                           QGroupBox, QFormLayout, QFileDialog, QListWidget,
                           QListWidgetItem)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QIcon, QFont
import json
import os
import csv
from ..utils.timetable_reader import TimetableReader, Course
from ..utils.logger import setup_logger
from ..utils.config import BASE_DIR

logger = setup_logger(__name__)

class CourseManager(QDialog):
    """Dialog for managing courses."""
    
    course_updated = pyqtSignal(list)  # Signal emitted when courses are updated
    
    def __init__(self, parent=None):
        """Initialize the course manager dialog."""
        super().__init__(parent)
        self.setWindowTitle("Course Manager")
        self.setMinimumSize(1000, 800)
        
        # Load existing courses
        app_data_dir = os.path.join(BASE_DIR, 'data')
        os.makedirs(app_data_dir, exist_ok=True)
        self.courses_file = os.path.join(app_data_dir, 'courses.json')
        self.courses = self._load_courses()
        
        # Track currently selected course for editing
        self.selected_course = None
        
        self._setup_ui()
        
    def _setup_ui(self):
        """Set up the user interface."""
        layout = QVBoxLayout(self)
        
        # Import group
        import_group = QGroupBox("Import Courses")
        import_layout = QHBoxLayout()
        
        # Create a custom QLineEdit that accepts drops
        class DropLineEdit(QLineEdit):
            def __init__(self, parent=None):
                super().__init__(parent)
                self.setAcceptDrops(True)
                
            def dragEnterEvent(self, event):
                if event.mimeData().hasUrls() and len(event.mimeData().urls()) == 1:
                    event.acceptProposedAction()
                    
            def dragMoveEvent(self, event):
                if event.mimeData().hasUrls() and len(event.mimeData().urls()) == 1:
                    event.acceptProposedAction()
                    
            def dropEvent(self, event):
                if event.mimeData().hasUrls() and len(event.mimeData().urls()) == 1:
                    file_path = event.mimeData().urls()[0].toLocalFile()
                    self.setText(file_path)
                    self.parent().parent()._process_imported_file(file_path)
                    event.acceptProposedAction()
        
        self.import_path = DropLineEdit()
        self.import_path.setReadOnly(True)
        self.import_path.setPlaceholderText("Drag & drop a TTAP/courses json file here or click Browse...")
        
        import_btn = QPushButton("Browse...")
        import_btn.clicked.connect(self._import_courses)
        import_btn.setStyleSheet("""
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
        
        import_layout.addWidget(self.import_path)
        import_layout.addWidget(import_btn)
        import_group.setLayout(import_layout)
        layout.addWidget(import_group)
        
        # Main content area
        content_layout = QHBoxLayout()
        
        # Left side - Course list
        course_list_group = QGroupBox("Courses")
        course_list_layout = QVBoxLayout()
        
        # Course list table
        self.course_table = QTableWidget()
        self.course_table.setColumnCount(2)
        self.course_table.setHorizontalHeaderLabels(["Course Code", "Course Name"])
        self.course_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.course_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.course_table.setSelectionMode(QTableWidget.SingleSelection)
        self.course_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.course_table.verticalHeader().setVisible(False)
        self.course_table.setAlternatingRowColors(True)
        self.course_table.cellClicked.connect(self._on_course_selected)
        
        # Add up/down buttons for reordering courses
        course_buttons_layout = QHBoxLayout()
        
        self.move_up_button = QPushButton("Move Up")
        self.move_up_button.clicked.connect(self._move_course_up)
        self.move_up_button.setEnabled(False)
        self.move_up_button.setStyleSheet("""
            QPushButton {
                background-color: #607D8B;
                color: white;
                border: none;
                padding: 6px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #455A64;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)
        
        self.move_down_button = QPushButton("Move Down")
        self.move_down_button.clicked.connect(self._move_course_down)
        self.move_down_button.setEnabled(False)
        self.move_down_button.setStyleSheet("""
            QPushButton {
                background-color: #607D8B;
                color: white;
                border: none;
                padding: 6px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #455A64;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)
        
        course_buttons_layout.addWidget(self.move_up_button)
        course_buttons_layout.addWidget(self.move_down_button)
        
        course_list_layout.addWidget(self.course_table)
        course_list_layout.addLayout(course_buttons_layout)
        
        course_list_group.setLayout(course_list_layout)
        content_layout.addWidget(course_list_group)
        
        # Right side - Course details
        details_group = QGroupBox("Course Details")
        details_layout = QVBoxLayout()
        
        # Course code and name
        form_layout = QFormLayout()
        
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("e.g., UCCD1003")
        form_layout.addRow("Course Code:", self.code_input)
        
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g., Programming Concepts and Problem Solving")
        form_layout.addRow("Course Name:", self.name_input)
        
        details_layout.addLayout(form_layout)
        
        # Slots section
        slots_group = QGroupBox("Slots")
        slots_layout = QVBoxLayout()
        
        # Lecture slots
        lecture_layout = QHBoxLayout()
        lecture_layout.addWidget(QLabel("Lecture Slots:"))
        self.lecture_slots = QLineEdit()
        self.lecture_slots.setPlaceholderText("e.g., 1, 2, 3")
        lecture_layout.addWidget(self.lecture_slots)
        slots_layout.addLayout(lecture_layout)
        
        # Tutorial slots
        tutorial_layout = QHBoxLayout()
        tutorial_layout.addWidget(QLabel("Tutorial Slots:"))
        self.tutorial_slots = QLineEdit()
        self.tutorial_slots.setPlaceholderText("e.g., 1, 2, 3")
        tutorial_layout.addWidget(self.tutorial_slots)
        slots_layout.addLayout(tutorial_layout)
        
        # Practical slots
        practical_layout = QHBoxLayout()
        practical_layout.addWidget(QLabel("Practical Slots:"))
        self.practical_slots = QLineEdit()
        self.practical_slots.setPlaceholderText("e.g., 1, 2, 3")
        practical_layout.addWidget(self.practical_slots)
        slots_layout.addLayout(practical_layout)
        
        slots_group.setLayout(slots_layout)
        details_layout.addWidget(slots_group)
        
        # Action buttons
        button_layout = QHBoxLayout()
        
        self.add_button = QPushButton("Add Course")
        self.add_button.clicked.connect(self._add_course)
        self.add_button.setStyleSheet("""
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
        """)
        
        self.update_button = QPushButton("Update Course")
        self.update_button.clicked.connect(self._update_course)
        self.update_button.setEnabled(False)
        self.update_button.setStyleSheet("""
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
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)
        
        self.delete_button = QPushButton("Delete Course")
        self.delete_button.clicked.connect(self._delete_course)
        self.delete_button.setEnabled(False)
        self.delete_button.setStyleSheet("""
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
        
        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self._clear_inputs)
        self.clear_button.setStyleSheet("""
            QPushButton {
                background-color: #9e9e9e;
                color: white;
                border: none;
                padding: 8px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #757575;
            }
        """)
        
        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.update_button)
        button_layout.addWidget(self.delete_button)
        button_layout.addWidget(self.clear_button)
        
        details_layout.addLayout(button_layout)
        details_group.setLayout(details_layout)
        content_layout.addWidget(details_group)
        
        layout.addLayout(content_layout)
        
        # Bottom buttons
        bottom_layout = QHBoxLayout()
        
        save_button = QPushButton("Save Changes")
        save_button.clicked.connect(lambda : self._save_courses(show_message=True))
        save_button.setStyleSheet("""
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
        
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        close_button.setStyleSheet("""
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
        """)
        
        bottom_layout.addWidget(save_button)
        bottom_layout.addWidget(close_button)
        layout.addLayout(bottom_layout)
        
        # Set window style
        self.setStyleSheet("""
            QDialog {
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
            QLineEdit, QComboBox, QSpinBox {
                padding: 6px;
                border: 1px solid #ddd;
                border-radius: 4px;
                background-color: white;
            }
            QTableWidget {
                border: 1px solid #ddd;
                border-radius: 4px;
                background-color: white;
                gridline-color: #ddd;
            }
            QTableWidget::item {
                padding: 4px;
            }
            QTableWidget::item:selected {
                background-color: #e3f2fd;
                color: black;
            }
            QTableWidget:focus {
                outline: none;
            }
            QHeaderView::section {
                background-color: #f0f0f0;
                padding: 4px;
                border: 1px solid #ddd;
                font-weight: bold;
            }
        """)
        
        # Populate course list
        self._populate_course_list()
    
    def _populate_course_list(self):
        """Populate the course list."""
        self.course_table.setRowCount(0)
        for course in self.courses:
            row_position = self.course_table.rowCount()
            self.course_table.insertRow(row_position)
            self.course_table.setItem(row_position, 0, QTableWidgetItem(course.code))
            self.course_table.setItem(row_position, 1, QTableWidgetItem(course.name))
    
    def _on_course_selected(self, row, column):
        """Handle course selection."""
        self.selected_course = self.courses[row]
        self._populate_course_details(self.selected_course)
        self.update_button.setEnabled(True)
        self.delete_button.setEnabled(True)
        self.move_up_button.setEnabled(row > 0)
        self.move_down_button.setEnabled(row < len(self.courses) - 1)
    
    def _populate_course_details(self, course):
        """Populate course details in the form."""
        self.code_input.setText(course.code)
        self.name_input.setText(course.name)
        self.lecture_slots.setText(", ".join(map(str, course.slots.get('L', []))))
        self.tutorial_slots.setText(", ".join(map(str, course.slots.get('T', []))))
        self.practical_slots.setText(", ".join(map(str, course.slots.get('P', []))))
    
    def _parse_slots(self, slot_text: str) -> list:
        """Parse slot numbers from text."""
        if not slot_text.strip():
            return []
        return [int(s.strip()) for s in slot_text.split(',') if s.strip().isdigit()]
    
    def _add_course(self):
        """Add a new course."""
        code = self.code_input.text().strip().upper()
        name = self.name_input.text().strip()
        
        if not code or not name:
            QMessageBox.warning(self, "Error", "Please enter course code and name!")
            return
        
        # Check if course already exists
        for course in self.courses:
            if course.code == code:
                QMessageBox.warning(self, "Error", "Course code already exists!")
                return
        
        # Parse slots
        slots = {
            'L': self._parse_slots(self.lecture_slots.text()),
            'T': self._parse_slots(self.tutorial_slots.text()),
            'P': self._parse_slots(self.practical_slots.text())
        }
        
        # Create new course
        new_course = Course(
            code=code,
            name=name,
            slots=slots
        )
        
        self.courses.append(new_course)
        self._populate_course_list()
        self._clear_inputs()
    
    def _update_course(self):
        """Update the selected course."""
        if not self.selected_course:
            return
            
        code = self.code_input.text().strip().upper()
        name = self.name_input.text().strip()
        
        if not code or not name:
            QMessageBox.warning(self, "Error", "Please enter course code and name!")
            return
        
        # Check if code is changed and already exists
        if code != self.selected_course.code:
            for course in self.courses:
                if course.code == code:
                    QMessageBox.warning(self, "Error", "Course code already exists!")
                    return
        
        # Parse slots
        slots = {
            'L': self._parse_slots(self.lecture_slots.text()),
            'T': self._parse_slots(self.tutorial_slots.text()),
            'P': self._parse_slots(self.practical_slots.text())
        }
        
        # Update course
        self.selected_course.code = code
        self.selected_course.name = name
        self.selected_course.slots = slots
        
        self._populate_course_list()
        self._clear_inputs()
    
    def _delete_course(self):
        """Delete the selected course."""
        if not self.selected_course:
            return
            
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Are you sure you want to delete course {self.selected_course.code}?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.courses.remove(self.selected_course)
            self._populate_course_list()
            self._clear_inputs()
    
    def _clear_inputs(self):
        """Clear input fields."""
        self.code_input.clear()
        self.name_input.clear()
        self.lecture_slots.clear()
        self.tutorial_slots.clear()
        self.practical_slots.clear()
        self.selected_course = None
        self.update_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        self.add_button.setEnabled(True)
        self.move_up_button.setEnabled(False)
        self.move_down_button.setEnabled(False)
    
    def _move_course_up(self):
        """Move the selected course up in the list."""
        if not self.selected_course:
            return
        
        index = self.courses.index(self.selected_course)
        if index > 0:
            self.courses[index], self.courses[index - 1] = self.courses[index - 1], self.courses[index]
            self._populate_course_list()
            self.course_table.selectRow(index - 1)
            if index - 1 == 0:
                self.move_up_button.setEnabled(False)
            self.move_down_button.setEnabled(True)
    
    def _move_course_down(self):
        """Move the selected course down in the list."""
        if not self.selected_course:
            return
        
        index = self.courses.index(self.selected_course)
        if index < len(self.courses) - 1:
            self.courses[index], self.courses[index + 1] = self.courses[index + 1], self.courses[index]
            self._populate_course_list()
            self.course_table.selectRow(index + 1)
            if index + 1 == len(self.courses) - 1:
                self.move_down_button.setEnabled(False)
            self.move_up_button.setEnabled(True)
    
    def _import_courses(self):
        """Import courses from a file."""
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Select Course File",
            "",
            "Text Files (*.txt);;JSON Files (*.json);;All Files (*.*)"
        )
        
        if not filename:
            return
            
        self.import_path.setText(filename)
        
        try:
            # Determine file type by extension
            if filename.lower().endswith('.json'):
                # Import from JSON
                with open(filename, 'r') as f:
                    data = json.load(f)
                    self.courses = [Course(**course) for course in data]
            else:
                # Default to timetable text file format
                self.courses = TimetableReader.read_timetable(filename)
                
            self._populate_course_list()
            QMessageBox.information(self, "Success", "Courses imported successfully!")
            
        except Exception as e:
            logger.error(f"Failed to import courses: {str(e)}")
            QMessageBox.warning(self, "Error", f"Failed to import courses: {str(e)}")
    
    def _process_imported_file(self, file_path):
        """Process the imported file."""
        try:
            # Determine file type by extension
            if file_path.lower().endswith('.json'):
                # Import from JSON
                with open(file_path, 'r') as f:
                    data = json.load(f)
                    self.courses = [Course(**course) for course in data]
            else:
                # Default to timetable text file format
                self.courses = TimetableReader.read_timetable(file_path)
                
            self._populate_course_list()
            QMessageBox.information(self, "Success", "Courses imported successfully!")
            
        except Exception as e:
            logger.error(f"Failed to process imported file: {str(e)}")
            QMessageBox.warning(self, "Error", f"Failed to process imported file: {str(e)}")
    
    def _load_courses(self) -> list[Course]:
        """Load courses from JSON file."""
        try:
            os.makedirs(os.path.dirname(self.courses_file), exist_ok=True)
            if os.path.exists(self.courses_file):
                with open(self.courses_file, 'r') as f:
                    data = json.load(f)
                    return [Course(**course) for course in data]
            return []
        except Exception as e:
            logger.error(f"Failed to load courses: {str(e)}")
            return []
    
    def _save_courses(self, show_message=True):
        """Save courses to JSON file."""
        try:
            with open(self.courses_file, 'w') as f:
                json.dump([course.__dict__ for course in self.courses], f, indent=4)
            self.course_updated.emit(self.courses)
            if show_message:
                QMessageBox.information(self, "Success", "Courses saved successfully!")
        except Exception as e:
            logger.error(f"Failed to save courses: {str(e)}")
            if show_message:
                QMessageBox.warning(self, "Error", f"Failed to save courses: {str(e)}")
            else:
                logger.error("Failed to save courses without showing message.")
    
    def set_courses(self, courses: list):
        """Set the list of courses.
        
        Args:
            courses (list): List of Course objects
        """
        self.courses = courses
        self._save_courses(show_message=False)

    def get_courses(self) -> list:
        """Get the list of courses.
        
        Returns:
            list: List of Course objects
        """
        return self.courses