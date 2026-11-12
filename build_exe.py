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
    frontend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
    frontend_index = os.path.join(frontend_dir, "dist", "index.html")
    if not os.path.exists(frontend_index):
        npm = shutil.which("npm")
        if not npm:
            raise RuntimeError("npm is required to build the Vue frontend")
        print("Building Vue frontend...")
        subprocess.check_call([npm, "install"], cwd=frontend_dir)
        subprocess.check_call([npm, "run", "build"], cwd=frontend_dir)

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
    
    # Define PyInstaller command
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name=UnitRegTimetable",
        "--onedir",  # Folder build: no per-launch unpacking of one large exe, so it starts fast
        "--noconfirm",  # Replace an existing dist/UnitRegTimetable folder
        "--windowed",  # Don't show console window for GUI app
    ]
    
    # Add icon if it exists
    if icon_path:
        cmd.append(f"--icon={icon_path}")
    
    # Add data files. Python code is bundled by PyInstaller from the imports;
    # only files read at runtime are added here (not the whole src/ folder, which
    # also held the unused legacy PyQt GUI, duplicate sources and caches).
    ocr_dir = os.path.join("src", "utils", "ocr")
    cmd.extend([
        f"--add-data={os.path.join(ocr_dir, 'common_old.onnx')}{sep}{ocr_dir}",  # captcha OCR model
        f"--add-data={os.path.join(ocr_dir, 'common_old_charset.json')}{sep}{ocr_dir}",
        f"--add-data=resources{sep}resources",  # Include resources
        f"--add-data={os.path.join('web', 'dist')}{sep}{os.path.join('web', 'dist')}",  # Built Vue frontend only (not node_modules)
    ])

    # Add hidden imports
    cmd.extend([
        "--hidden-import=requests",
        "--hidden-import=bs4",
        "--hidden-import=playwright",
        "--hidden-import=webview",
        # The pywebview app does not use Qt; keep the legacy PyQt5 GUI out of the bundle
        "--exclude-module=PyQt5",
        "--exclude-module=src.gui",
        # Not used at runtime (captchas are JPEG; AVIF support alone is ~7.5 MB)
        "--exclude-module=tkinter",
        "--exclude-module=PIL.AvifImagePlugin",
        "--exclude-module=PIL._avif",
    ])
    
    # Add main script
    cmd.append("main.py")
    
    print("Building executable with PyInstaller...")
    print("Command:", " ".join(cmd))
    
    # Run PyInstaller
    try:
        subprocess.check_call(cmd)
        # The app reads config.ini next to the exe (portal URLs, logging).
        shutil.copy2(os.path.join(cur_dir, "config.ini"), os.path.join(cur_dir, "dist", "UnitRegTimetable", "config.ini"))
        print("\nBuild successful!")
        print("\nApp folder: dist/UnitRegTimetable (run UnitRegTimetable.exe inside it;")
        print("distribute the whole folder, not only the exe).")
        print("\nUsage:")
        print("  UnitRegTimetable.exe")
        print("  UnitRegTimetable.exe --test-real-server --student-id ID --saved   (report: logs/real-server-test.txt)")
        print("\nSize report: python tools/bundle_size.py")
    except subprocess.CalledProcessError as e:
        print(f"Build failed with error: {e}")
        return False
    
    return True

if __name__ == "__main__":
    build_executable()
