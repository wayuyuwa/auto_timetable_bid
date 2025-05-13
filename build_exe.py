"""
Build script to create an executable using PyInstaller.
"""

import os
import sys
import shutil
import subprocess
import platform

def build_executable():
    """Build the executable using PyInstaller."""
    # Ensure PyInstaller is installed
    try:
        import PyInstaller
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
    
    # Get current directory
    cur_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Get icon path
    icon_path = os.path.join(cur_dir, "resources", "icon.ico")
    if not os.path.exists(icon_path):
        icon_path = None
        print("Warning: Icon file not found at", icon_path)
    
    # Determine separator based on platform
    sep = ";" if platform.system() == "Windows" else ":"
    
    # Find ddddocr model file path
    try:
        import ddddocr
        ddddocr_path = os.path.dirname(ddddocr.__file__)
        model_path = os.path.join(ddddocr_path, "common.onnx")
        if os.path.exists(model_path):
            print(f"Found ddddocr model at: {model_path}")
        else:
            print(f"Warning: ddddocr model file not found at {model_path}")
            model_path = None
    except ImportError:
        print("Warning: ddddocr package not found")
        model_path = None
    
    # Define PyInstaller command
    cmd = [
        "pyinstaller",
        "--name=UnitRegTimetable",
        "--onefile",  # Create a single executable
        "--windowed",  # Don't show console window for GUI app
    ]
    
    # Add icon if it exists
    if icon_path:
        cmd.append(f"--icon={icon_path}")
    
    # Add data files
    cmd.extend([
        f"--add-data=src{sep}src",  # Include source files
        f"--add-data=resources{sep}resources",  # Include resources
    ])
    
    # Add ddddocr model file if found
    if model_path:
        # Add model file to the same location it would be in the package
        cmd.append(f"--add-data={model_path}{sep}{os.path.join('ddddocr')}")
    
    # Add hidden imports
    cmd.extend([
        "--hidden-import=PyQt5",
        "--hidden-import=PyQt5.QtCore",
        "--hidden-import=PyQt5.QtGui",
        "--hidden-import=PyQt5.QtWidgets",
        "--hidden-import=requests",
        "--hidden-import=bs4",
        "--hidden-import=selenium",
        "--hidden-import=ddddocr",
    ])
    
    # Add main script
    cmd.append("main.py")
    
    print("Building executable with PyInstaller...")
    print("Command:", " ".join(cmd))
    
    # Run PyInstaller
    try:
        subprocess.check_call(cmd)
        print("\nBuild successful!")
        print("\nExecutable can be found in the 'dist' folder.")
        print("\nUsage examples:")
        print("  UnitRegTimetable.exe")
        print("  UnitRegTimetable.exe --timetable-file MyTimetable.txt")
        print("  UnitRegTimetable.exe --method selenium")
        print("  UnitRegTimetable.exe --timetable-file MyTimetable.txt --method selenium")
    except subprocess.CalledProcessError as e:
        print(f"Build failed with error: {e}")
        return False
    
    return True

if __name__ == "__main__":
    build_executable()
