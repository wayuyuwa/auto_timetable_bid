@echo off
echo ===== UTAR Course Registration Scraper - Build Process =====
echo.

echo Installing required dependencies...
pip install -r requirements.txt
if %ERRORLEVEL% neq 0 (
    echo Failed to install dependencies. Please check requirements.txt.
    pause
    exit /b 1
)

echo.
echo Building executable...
python build_exe.py
if %ERRORLEVEL% neq 0 (
    echo Failed to build executable.
    pause
    exit /b 1
)

echo.
echo Build process complete.
echo Executable can be found in the 'dist' folder.
echo.
echo Usage examples:
echo   UnitRegTimetable.exe
echo   UnitRegTimetable.exe --timetable-file MyTimetable.txt
echo   UnitRegTimetable.exe --method selenium
echo   UnitRegTimetable.exe --timetable-file MyTimetable.txt --method selenium
echo   UnitRegTimetable.exe --timetable-file MyTimetable.txt --method selenium --start
echo.

pause
