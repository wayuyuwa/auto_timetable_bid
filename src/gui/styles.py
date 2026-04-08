APP_STYLE = """
QMainWindow {
    background-color: #f2f4f8;
}

QWidget {
    color: #1f2a37;
    font-size: 13px;
}

QFrame#sidebar {
    background-color: #0f2743;
    border: 1px solid #17395f;
    border-radius: 12px;
}

QLabel#sidebarTitle {
    color: #f8fbff;
    font-size: 20px;
    font-weight: 700;
}

QFrame#mainArea,
QFrame#titleCard,
QFrame#footerActions {
    background-color: #ffffff;
    border: 1px solid #d7dee8;
    border-radius: 12px;
}

QLabel#pageTitle {
    font-size: 18px;
    font-weight: 700;
    color: #1d3557;
}

QLabel#pageSubtitle {
    font-size: 12px;
    color: #55697f;
}

QGroupBox {
    font-weight: 700;
    color: #1d3557;
    border: 1px solid #d7dee8;
    border-radius: 10px;
    margin-top: 14px;
    padding-top: 12px;
    background: #fbfcfe;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}

/* Button Base Styles */
QPushButton {
    border: none;
    border-radius: 8px;
    padding: 10px 12px;
    font-weight: 600;
    background-color: #2b7dbd;
    color: #ffffff;
}
QPushButton:hover { background-color: #256aa0; }
QPushButton:pressed { background-color: #1f5a87; }
QPushButton:disabled { background-color: #bcc8d6; color: #666666; }

/* Sidebar Navigation */
QPushButton#btn_login,
QPushButton#btn_courses,
QPushButton#btn_config {
    text-align: left;
    padding: 10px 12px;
    border-radius: 8px;
    background-color: #153655;
    color: #dce9f7;
    border: 1px solid #214d76;
}
QPushButton#btn_login:hover,
QPushButton#btn_courses:hover,
QPushButton#btn_config:hover { background-color: #1c446a; }
QPushButton#btn_login:checked,
QPushButton#btn_courses:checked,
QPushButton#btn_config:checked {
    background-color: #2b7dbd;
    border-color: #5ba4dd;
    color: #ffffff;
}

/* Execution Actions */
QPushButton#btn_start { background-color: #2f9d5c; }
QPushButton#btn_start:hover { background-color: #27844d; }
QPushButton#btn_stop { background-color: #d14a3f; }
QPushButton#btn_stop:hover { background-color: #b83f36; }

/* Course Manager Actions */
QPushButton#btn_add_course { background-color: #4CAF50; }
QPushButton#btn_add_course:hover { background-color: #45a049; }
QPushButton#btn_update_course, QPushButton#btn_import_course { background-color: #2196F3; }
QPushButton#btn_update_course:hover, QPushButton#btn_import_course:hover { background-color: #1976D2; }
QPushButton#btn_delete_course { background-color: #f44336; }
QPushButton#btn_delete_course:hover { background-color: #d32f2f; }
QPushButton#btn_clear_course, QPushButton#btn_move_up, QPushButton#btn_move_down { background-color: #607D8B; }
QPushButton#btn_clear_course:hover, QPushButton#btn_move_up:hover, QPushButton#btn_move_down:hover { background-color: #455A64; }

/* Inputs and Selectors */
QLineEdit,
QTextEdit,
QComboBox,
QSpinBox {
    background-color: #ffffff;
    border: 1px solid #c7d2de;
    border-radius: 8px;
    padding: 8px 10px;
}

QLineEdit:focus,
QTextEdit:focus,
QComboBox:focus,
QSpinBox:focus {
    border: 1px solid #2b7dbd;
}

QRadioButton,
QCheckBox {
    spacing: 8px;
}

/* Table Design */
QTableWidget {
    border: 1px solid #c7d2de;
    border-radius: 8px;
    background-color: #ffffff;
    gridline-color: #e5e7eb;
}
QTableWidget::item { padding: 6px; }
QTableWidget::item:selected { background-color: #e3f2fd; color: #1d3557; }
QTableWidget:focus { outline: none; }
QHeaderView::section {
    background-color: #f2f4f8;
    padding: 6px;
    border: 1px solid #c7d2de;
    font-weight: 700;
}
"""

def apply_stylesheet(window, font_size=16):
    """Apply the shared application stylesheet to a Qt window."""
    size = int(font_size) if font_size else 16
    stylesheet = APP_STYLE.replace("font-size: 13px;", f"font-size: {size}px;", 1)
    window.setStyleSheet(stylesheet)