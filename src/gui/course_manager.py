"""
Course management widget for the UTAR Course Registration Scraper.
"""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                           QLabel, QLineEdit, QTableWidget, QTableWidgetItem,
                           QHeaderView, QMessageBox, QGroupBox, QFormLayout, 
                           QFileDialog)
from PyQt5.QtCore import Qt, pyqtSignal
import json
import os
from ..utils.timetable_reader import TimetableReader, Course
from ..utils.logger import setup_logger
from ..utils.config import BASE_DIR
from ..storage.database import Database, CourseRepository

logger = setup_logger(__name__)

class DropLineEdit(QLineEdit):
    """A custom QLineEdit that accepts file drops."""
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
            # Process the file via the parent widget
            parent_widget = self.window().findChild(CourseManagerWidget)
            if parent_widget:
                parent_widget._process_imported_file(file_path)
            event.acceptProposedAction()

class CourseManagerWidget(QWidget):
    """Integrated Widget for managing courses."""
    
    course_updated = pyqtSignal(list)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Load existing courses
        app_data_dir = os.path.join(BASE_DIR, 'data')
        os.makedirs(app_data_dir, exist_ok=True)
        self.courses_file = os.path.join(app_data_dir, 'courses.json')
        self.course_repo = CourseRepository(Database())
        self.course_repo.migrate_from_json(self.courses_file)
        self.courses = self._load_courses()
        
        self.selected_course = None
        self._setup_ui()
        self._populate_course_list()
        
    def _setup_ui(self):
        """Set up the integrated user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # --- Import Group ---
        import_group = QGroupBox("Import Courses")
        import_layout = QHBoxLayout()
        
        self.import_path = DropLineEdit()
        self.import_path.setReadOnly(True)
        self.import_path.setPlaceholderText("Drag & drop a TTAP/courses json file here or click Browse...")
        
        import_btn = QPushButton("Browse...")
        import_btn.setObjectName("btn_import_course")
        import_btn.clicked.connect(self._import_courses)
        
        import_layout.addWidget(self.import_path)
        import_layout.addWidget(import_btn)
        import_group.setLayout(import_layout)
        layout.addWidget(import_group)
        
        # --- Main Content Area ---
        content_layout = QHBoxLayout()
        
        # Left side - Course list
        course_list_group = QGroupBox("Courses Priority List")
        course_list_layout = QVBoxLayout()
        
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
        
        course_buttons_layout = QHBoxLayout()
        self.move_up_button = QPushButton("Move Up")
        self.move_up_button.setObjectName("btn_move_up")
        self.move_up_button.clicked.connect(self._move_course_up)
        self.move_up_button.setEnabled(False)
        
        self.move_down_button = QPushButton("Move Down")
        self.move_down_button.setObjectName("btn_move_down")
        self.move_down_button.clicked.connect(self._move_course_down)
        self.move_down_button.setEnabled(False)
        
        course_buttons_layout.addWidget(self.move_up_button)
        course_buttons_layout.addWidget(self.move_down_button)
        
        course_list_layout.addWidget(self.course_table)
        course_list_layout.addLayout(course_buttons_layout)
        course_list_group.setLayout(course_list_layout)
        content_layout.addWidget(course_list_group)
        
        # Right side - Course details
        details_group = QGroupBox("Course Details")
        details_layout = QVBoxLayout()
        
        form_layout = QFormLayout()
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("e.g., UCCD1003")
        form_layout.addRow("Course Code:", self.code_input)
        
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g., Programming Concepts")
        form_layout.addRow("Course Name:", self.name_input)
        details_layout.addLayout(form_layout)
        
        # Slots section
        slots_group = QGroupBox("Slots")
        slots_layout = QVBoxLayout()
        
        lecture_layout = QHBoxLayout()
        lecture_layout.addWidget(QLabel("Lecture Slots:"))
        self.lecture_slots = QLineEdit()
        self.lecture_slots.setPlaceholderText("e.g., 1, 2, 3")
        lecture_layout.addWidget(self.lecture_slots)
        slots_layout.addLayout(lecture_layout)
        
        tutorial_layout = QHBoxLayout()
        tutorial_layout.addWidget(QLabel("Tutorial Slots:"))
        self.tutorial_slots = QLineEdit()
        self.tutorial_slots.setPlaceholderText("e.g., 1, 2, 3")
        tutorial_layout.addWidget(self.tutorial_slots)
        slots_layout.addLayout(tutorial_layout)
        
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
        self.add_button.setObjectName("btn_add_course")
        self.add_button.clicked.connect(self._add_course)
        
        self.update_button = QPushButton("Update Course")
        self.update_button.setObjectName("btn_update_course")
        self.update_button.clicked.connect(self._update_course)
        self.update_button.setEnabled(False)
        
        self.delete_button = QPushButton("Delete Course")
        self.delete_button.setObjectName("btn_delete_course")
        self.delete_button.clicked.connect(self._delete_course)
        self.delete_button.setEnabled(False)
        
        self.clear_button = QPushButton("Clear")
        self.clear_button.setObjectName("btn_clear_course")
        self.clear_button.clicked.connect(self._clear_inputs)
        
        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.update_button)
        button_layout.addWidget(self.delete_button)
        button_layout.addWidget(self.clear_button)
        
        details_layout.addLayout(button_layout)
        details_group.setLayout(details_layout)
        content_layout.addWidget(details_group)
        
        layout.addLayout(content_layout)
    
    def _populate_course_list(self):
        self.course_table.setRowCount(0)
        for course in self.courses:
            row_position = self.course_table.rowCount()
            self.course_table.insertRow(row_position)
            self.course_table.setItem(row_position, 0, QTableWidgetItem(course.code))
            self.course_table.setItem(row_position, 1, QTableWidgetItem(course.name))
    
    def _on_course_selected(self, row, column):
        self.selected_course = self.courses[row]
        self._populate_course_details(self.selected_course)
        self.update_button.setEnabled(True)
        self.delete_button.setEnabled(True)
        self.move_up_button.setEnabled(row > 0)
        self.move_down_button.setEnabled(row < len(self.courses) - 1)
    
    def _populate_course_details(self, course):
        self.code_input.setText(course.code)
        self.name_input.setText(course.name)
        self.lecture_slots.setText(", ".join(map(str, course.slots.get('L', []))))
        self.tutorial_slots.setText(", ".join(map(str, course.slots.get('T', []))))
        self.practical_slots.setText(", ".join(map(str, course.slots.get('P', []))))
    
    def _parse_slots(self, slot_text: str) -> list:
        if not slot_text.strip():
            return []
        return [int(s.strip()) for s in slot_text.split(',') if s.strip().isdigit()]
    
    def _add_course(self):
        code = self.code_input.text().strip().upper()
        name = self.name_input.text().strip()
        
        if not code or not name:
            QMessageBox.warning(self, "Error", "Please enter course code and name!")
            return
            
        if any(course.code == code for course in self.courses):
            QMessageBox.warning(self, "Error", "Course code already exists!")
            return
        
        slots = {
            'L': self._parse_slots(self.lecture_slots.text()),
            'T': self._parse_slots(self.tutorial_slots.text()),
            'P': self._parse_slots(self.practical_slots.text())
        }
        
        new_course = Course(code=code, name=name, slots=slots)
        self.courses.append(new_course)
        self._populate_course_list()
        self._clear_inputs()
        self._save_courses(show_message=False)
    
    def _update_course(self):
        if not self.selected_course:
            return
            
        code = self.code_input.text().strip().upper()
        name = self.name_input.text().strip()
        
        if not code or not name:
            QMessageBox.warning(self, "Error", "Please enter course code and name!")
            return
        
        if code != self.selected_course.code and any(course.code == code for course in self.courses):
            QMessageBox.warning(self, "Error", "Course code already exists!")
            return
        
        slots = {
            'L': self._parse_slots(self.lecture_slots.text()),
            'T': self._parse_slots(self.tutorial_slots.text()),
            'P': self._parse_slots(self.practical_slots.text())
        }
        
        self.selected_course.code = code
        self.selected_course.name = name
        self.selected_course.slots = slots
        
        self._populate_course_list()
        self._clear_inputs()
        self._save_courses(show_message=False)
    
    def _delete_course(self):
        if not self.selected_course:
            return
            
        self.courses.remove(self.selected_course)
        self._populate_course_list()
        self._clear_inputs()
        self._save_courses(show_message=False)
    
    def _clear_inputs(self):
        self.code_input.clear()
        self.name_input.clear()
        self.lecture_slots.clear()
        self.tutorial_slots.clear()
        self.practical_slots.clear()
        self.selected_course = None
        self.course_table.clearSelection()
        self.update_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        self.add_button.setEnabled(True)
        self.move_up_button.setEnabled(False)
        self.move_down_button.setEnabled(False)
    
    def _move_course_up(self):
        if not self.selected_course:
            return
        index = self.courses.index(self.selected_course)
        if index > 0:
            self.courses[index], self.courses[index - 1] = self.courses[index - 1], self.courses[index]
            self._populate_course_list()
            self.course_table.selectRow(index - 1)
            self.move_up_button.setEnabled(index - 1 > 0)
            self.move_down_button.setEnabled(True)
            self._save_courses(show_message=False)
    
    def _move_course_down(self):
        if not self.selected_course:
            return
        index = self.courses.index(self.selected_course)
        if index < len(self.courses) - 1:
            self.courses[index], self.courses[index + 1] = self.courses[index + 1], self.courses[index]
            self._populate_course_list()
            self.course_table.selectRow(index + 1)
            self.move_down_button.setEnabled(index + 1 < len(self.courses) - 1)
            self.move_up_button.setEnabled(True)
            self._save_courses(show_message=False)
    
    def _import_courses(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Select Course File", "", "Text Files (*.txt);;JSON Files (*.json);;All Files (*.*)"
        )
        if filename:
            self.import_path.setText(filename)
            self._process_imported_file(filename)
            
    def _process_imported_file(self, file_path):
        try:
            if file_path.lower().endswith('.json'):
                with open(file_path, 'r') as f:
                    data = json.load(f)
                    self.courses = [Course(**course) for course in data]
            else:
                self.courses = TimetableReader.read_timetable(file_path)
                
            self._populate_course_list()
            self._save_courses(show_message=False)
        except Exception as e:
            logger.error(f"Failed to process imported file: {str(e)}")
            QMessageBox.warning(self, "Error", f"Failed to process imported file: {str(e)}")
    
    def _load_courses(self) -> list[Course]:
        try:
            return self.course_repo.list_courses()
        except Exception as e:
            logger.error(f"Failed to load courses: {str(e)}")
            return []
    
    def _save_courses(self, show_message=True):
        try:
            self.course_repo.replace_courses(self.courses)
            self.course_updated.emit(self.courses)
            if show_message:
                QMessageBox.information(self, "Success", "Courses saved successfully!")
        except Exception as e:
            logger.error(f"Failed to save courses: {str(e)}")
            if show_message:
                QMessageBox.warning(self, "Error", f"Failed to save courses: {str(e)}")
    
    def set_courses(self, courses: list):
        self.courses = courses
        self._populate_course_list()
        self._save_courses(show_message=False)

    def get_courses(self) -> list:
        return self.courses