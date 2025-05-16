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
echo Preparing distribution package...
if exist "dist\config.ini" del "dist\config.ini"
copy "config.ini" "dist\"
if %ERRORLEVEL% neq 0 (
    echo Warning: Failed to copy config.ini file.
)

if exist "dist\resources" rmdir /s /q "dist\resources"
if exist "resources" (
    echo Copying resources folder...
    xcopy "resources" "dist\resources\" /E /I /Y
    if %ERRORLEVEL% neq 0 (
        echo Warning: Failed to copy resources folder.
    )
) else (
    echo Warning: Resources folder not found.
)

echo.
echo Build process complete.
echo Executable and required files can be found in the 'dist' folder.
echo.
echo Usage examples:
echo   UnitRegTimetable.exe
echo   UnitRegTimetable.exe --timetable-file MyTimetable.txt
echo   UnitRegTimetable.exe --method selenium
echo   UnitRegTimetable.exe --timetable-file MyTimetable.txt --method selenium
echo   UnitRegTimetable.exe --timetable-file MyTimetable.txt --method selenium --start
echo.

pause
