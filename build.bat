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
set "APP_DIR=dist\UnitRegTimetable"
if exist "%APP_DIR%\config.ini" del "%APP_DIR%\config.ini"
copy "config.ini" "%APP_DIR%\"
if %ERRORLEVEL% neq 0 (
    echo Warning: Failed to copy config.ini file.
)

if exist "%APP_DIR%\resources" rmdir /s /q "%APP_DIR%\resources"
if exist "resources" (
    echo Copying resources folder...
    xcopy "resources" "%APP_DIR%\resources\" /E /I /Y
    if %ERRORLEVEL% neq 0 (
        echo Warning: Failed to copy resources folder.
    )
) else (
    echo Warning: Resources folder not found.
)

echo.
echo Build process complete.
echo The app folder is dist\UnitRegTimetable - run UnitRegTimetable.exe inside it.
echo.
echo Usage examples:
echo   UnitRegTimetable.exe
echo   UnitRegTimetable.exe --timetable-file MyTimetable.txt
echo   UnitRegTimetable.exe --method playwright
echo   UnitRegTimetable.exe --timetable-file MyTimetable.txt --method playwright
echo   UnitRegTimetable.exe --timetable-file MyTimetable.txt --method playwright --start
echo.

pause
