"""
Main entry point for UTAR Course Auto-Bidding System.
"""
import sys
from PyQt5.QtWidgets import QApplication
from src.gui.main_window import MainWindow

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setApplicationName("UTAR Auto Timetable Bidding")
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())