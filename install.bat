@echo off
setlocal enabledelayedexpansion

:: ==============================================================================
:: Tempoy Windows Installation Script
:: ==============================================================================
:: This script installs Tempoy with all its dependencies on Windows.
:: Run with: install-tempoy.bat [--uninstall]

set "SCRIPT_NAME=%~nx0"
set "SCRIPT_DIR=%~dp0"
set "TEMPOY_DIR=%USERPROFILE%\.tempoy"
set "VENV_DIR=%TEMPOY_DIR%\venv"
set "CONFIG_FILE=%TEMPOY_DIR%\config.json"
set "PACKAGE_DIR=%TEMPOY_DIR%\tempoy_app"

:: Color codes for output
set "COLOR_GREEN=[92m"
set "COLOR_RED=[91m"
set "COLOR_YELLOW=[93m"
set "COLOR_BLUE=[94m"
set "COLOR_RESET=[0m"

:: Check for uninstall flag
if "%1"=="--uninstall" (
    goto :uninstall
)

echo %COLOR_BLUE%================================================================%COLOR_RESET%
echo %COLOR_BLUE%                     Tempoy Installation                        %COLOR_RESET%
echo %COLOR_BLUE%================================================================%COLOR_RESET%
echo.

:: Check if running as administrator (not required but gives better results)
net session >nul 2>&1
if %errorLevel% == 0 (
    echo %COLOR_YELLOW%Note: Running as administrator - this will provide better PATH integration.%COLOR_RESET%
) else (
    echo %COLOR_YELLOW%Note: Not running as administrator - PATH integration may be limited to current user.%COLOR_RESET%
)
echo.

:: Step 1: Check Python version
echo %COLOR_BLUE%[1/8] Checking Python installation...%COLOR_RESET%
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo %COLOR_RED%ERROR: Python is not installed or not in PATH.%COLOR_RESET%
    echo Please install Python 3.8 or later from https://python.org
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

for /f "tokens=2" %%a in ('python --version 2^>^&1') do set PYTHON_VERSION=%%a
for /f "tokens=1,2 delims=." %%a in ("%PYTHON_VERSION%") do (
    set MAJOR=%%a
    set MINOR=%%b
)

if %MAJOR% lss 3 (
    echo %COLOR_RED%ERROR: Python %PYTHON_VERSION% is too old. Python 3.8+ is required.%COLOR_RESET%
    pause
    exit /b 1
)

if %MAJOR% equ 3 if %MINOR% lss 8 (
    echo %COLOR_RED%ERROR: Python %PYTHON_VERSION% is too old. Python 3.8+ is required.%COLOR_RESET%
    pause
    exit /b 1
)

echo %COLOR_GREEN%✓ Python %PYTHON_VERSION% found%COLOR_RESET%

:: Step 2: Create Tempoy directory
echo.
echo %COLOR_BLUE%[2/8] Creating Tempoy directory...%COLOR_RESET%
if not exist "%TEMPOY_DIR%" (
    mkdir "%TEMPOY_DIR%" 2>nul
    if !errorlevel! neq 0 (
        echo %COLOR_RED%ERROR: Cannot create directory %TEMPOY_DIR%%COLOR_RESET%
        pause
        exit /b 1
    )
)
echo %COLOR_GREEN%✓ Directory created: %TEMPOY_DIR%%COLOR_RESET%

:: Step 3: Create virtual environment
echo.
echo %COLOR_BLUE%[3/8] Creating virtual environment...%COLOR_RESET%
if exist "%VENV_DIR%" (
    echo %COLOR_YELLOW%Virtual environment already exists. Recreating...%COLOR_RESET%
    rmdir /s /q "%VENV_DIR%" 2>nul
)

python -m venv "%VENV_DIR%"
if %errorlevel% neq 0 (
    echo %COLOR_RED%ERROR: Failed to create virtual environment%COLOR_RESET%
    pause
    exit /b 1
)
echo %COLOR_GREEN%✓ Virtual environment created%COLOR_RESET%

:: Step 4: Activate virtual environment and install dependencies
echo.
echo %COLOR_BLUE%[4/8] Installing dependencies...%COLOR_RESET%
call "%VENV_DIR%\Scripts\activate.bat"
if %errorlevel% neq 0 (
    echo %COLOR_RED%ERROR: Failed to activate virtual environment%COLOR_RESET%
    pause
    exit /b 1
)

:: Upgrade pip first
python -m pip install --upgrade pip >nul 2>&1

:: Install required packages
python -m pip install "PySide6>=6.7" "requests>=2.32"
if %errorlevel% neq 0 (
    echo %COLOR_RED%ERROR: Failed to install dependencies%COLOR_RESET%
    pause
    exit /b 1
)
echo %COLOR_GREEN%✓ Dependencies installed (PySide6, requests)%COLOR_RESET%

:: Step 5: Copy Tempoy application payload
echo.
echo %COLOR_BLUE%[5/8] Installing Tempoy application...%COLOR_RESET%
if not exist "%SCRIPT_DIR%tempoy.py" (
    echo %COLOR_RED%ERROR: tempoy.py not found in %SCRIPT_DIR%%COLOR_RESET%
    pause
    exit /b 1
)
if not exist "%SCRIPT_DIR%tempoy.pyw" (
    echo %COLOR_RED%ERROR: tempoy.pyw not found in %SCRIPT_DIR%%COLOR_RESET%
    pause
    exit /b 1
)
if not exist "%SCRIPT_DIR%tempoy_app\__main__.py" (
    echo %COLOR_RED%ERROR: tempoy_app package not found in %SCRIPT_DIR%%COLOR_RESET%
    pause
    exit /b 1
)

if exist "%TEMPOY_DIR%\tempoy.py" del "%TEMPOY_DIR%\tempoy.py" >nul 2>&1
if exist "%TEMPOY_DIR%\tempoy.pyw" del "%TEMPOY_DIR%\tempoy.pyw" >nul 2>&1
if exist "%PACKAGE_DIR%" rmdir /s /q "%PACKAGE_DIR%" >nul 2>&1
copy "%SCRIPT_DIR%tempoy.py" "%TEMPOY_DIR%\tempoy.py" >nul
if %errorlevel% neq 0 (
    echo %COLOR_RED%ERROR: Failed to copy tempoy.py%COLOR_RESET%
    pause
    exit /b 1
)
copy "%SCRIPT_DIR%tempoy.pyw" "%TEMPOY_DIR%\tempoy.pyw" >nul
if %errorlevel% neq 0 (
    echo %COLOR_RED%ERROR: Failed to copy tempoy.pyw%COLOR_RESET%
    pause
    exit /b 1
)
xcopy "%SCRIPT_DIR%tempoy_app" "%PACKAGE_DIR%\" /E /I /Y /Q >nul
if errorlevel 2 (
    echo %COLOR_RED%ERROR: Failed to copy tempoy_app package%COLOR_RESET%
    pause
    exit /b 1
)
echo %COLOR_GREEN%✓ Tempoy application payload installed%COLOR_RESET%

:: Step 6: Create launcher VBScript (runs without console window)
echo.
echo %COLOR_BLUE%[6/8] Creating launcher script...%COLOR_RESET%

:: Create VBS launcher that runs Python without console window
echo Set objShell = CreateObject("WScript.Shell") > "%TEMPOY_DIR%\tempoy.vbs"
echo Set objFSO = CreateObject("Scripting.FileSystemObject") >> "%TEMPOY_DIR%\tempoy.vbs"
echo strDir = objFSO.GetParentFolderName(WScript.ScriptFullName) >> "%TEMPOY_DIR%\tempoy.vbs"
echo strPython = strDir ^& "\venv\Scripts\pythonw.exe" >> "%TEMPOY_DIR%\tempoy.vbs"
echo strScript = strDir ^& "\tempoy.pyw" >> "%TEMPOY_DIR%\tempoy.vbs"
echo objShell.Run strPython ^& " " ^& strScript, 0, False >> "%TEMPOY_DIR%\tempoy.vbs"

:: Create batch launcher for command-line use
echo @echo off > "%TEMPOY_DIR%\tempoy.bat"
echo cd /d "%%~dp0" >> "%TEMPOY_DIR%\tempoy.bat"
echo call venv\Scripts\activate.bat >> "%TEMPOY_DIR%\tempoy.bat"
echo start /b pythonw tempoy.pyw %%* >> "%TEMPOY_DIR%\tempoy.bat"

echo %COLOR_GREEN%✓ Launcher scripts created%COLOR_RESET%

:: Step 7: Add to PATH / Create shortcuts
echo.
echo %COLOR_BLUE%[7/8] Setting up system integration...%COLOR_RESET%

:: Check if we can modify system PATH (requires admin) or user PATH
set "PATH_TARGET=USER"
net session >nul 2>&1
if %errorLevel% == 0 (
    set "PATH_TARGET=MACHINE"
    echo Creating system-wide integration...
) else (
    echo Creating user-level integration...
)

:: Add to PATH using PowerShell (more reliable than reg commands)
powershell -Command "& {$oldPath = [Environment]::GetEnvironmentVariable('PATH', '%PATH_TARGET%'); if ($oldPath -notlike '*%TEMPOY_DIR%*') { $newPath = $oldPath + ';%TEMPOY_DIR%'; [Environment]::SetEnvironmentVariable('PATH', $newPath, '%PATH_TARGET%'); Write-Host 'PATH updated' } else { Write-Host 'Already in PATH' }}" 2>nul

:: Create Start Menu shortcut
set "START_MENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs"
if "%PATH_TARGET%"=="MACHINE" (
    set "START_MENU=%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs"
)

:: Create shortcut using PowerShell
powershell -Command "& {$WshShell = New-Object -comObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut('%START_MENU%\Tempoy.lnk'); $Shortcut.TargetPath = '%TEMPOY_DIR%\tempoy.vbs'; $Shortcut.WorkingDirectory = '%TEMPOY_DIR%'; $Shortcut.Description = 'Tempoy - Time logging for Jira/Tempo'; $Shortcut.Save()}" 2>nul

echo %COLOR_GREEN%✓ System integration completed%COLOR_RESET%

:: Step 8: Test installation
echo.
echo %COLOR_BLUE%[8/8] Testing installation...%COLOR_RESET%

:: Test by running with --version flag (if supported, otherwise just check if it starts)
cd /d "%TEMPOY_DIR%"
call venv\Scripts\activate.bat
echo Testing Tempoy launch...
timeout /t 2 >nul

:: Try to verify imports and startup
set "VERIFY_OK=0"
python -c "import tempoy; import tempoy_app; print('✓ Tempoy modules load correctly')" >nul 2>&1
if %errorlevel% neq 0 (
    echo %COLOR_YELLOW%Warning: Module import verification failed.%COLOR_RESET%
) else (
    powershell -Command "& {$proc = Start-Process -FilePath '%VENV_DIR%\Scripts\python.exe' -ArgumentList 'tempoy.py' -WorkingDirectory '%TEMPOY_DIR%' -PassThru; Start-Sleep -Seconds 5; if ($proc.HasExited) { exit 1 } Stop-Process -Id $proc.Id -Force; exit 0 }" >nul 2>&1
    if !errorlevel! neq 0 (
        echo %COLOR_YELLOW%Warning: Launcher started incorrectly during verification.%COLOR_RESET%
    ) else (
        set "VERIFY_OK=1"
    )
)
if "%VERIFY_OK%"=="1" (
    echo %COLOR_GREEN%✓ Installation verified%COLOR_RESET%
)

:: Preserve existing config
if exist "%CONFIG_FILE%" (
    echo %COLOR_GREEN%✓ Existing configuration preserved%COLOR_RESET%
)

:: Installation complete
echo.
echo %COLOR_GREEN%================================================================%COLOR_RESET%
echo %COLOR_GREEN%                  Installation Complete!                        %COLOR_RESET%
echo %COLOR_GREEN%================================================================%COLOR_RESET%
echo.
echo %COLOR_BLUE%Tempoy has been installed to: %COLOR_RESET%%TEMPOY_DIR%
echo.
echo %COLOR_BLUE%To run Tempoy:%COLOR_RESET%
echo   • From Start Menu: Search for "Tempoy"
echo   • From command line: %COLOR_YELLOW%tempoy%COLOR_RESET% (after restarting your terminal)
echo   • Directly: %COLOR_YELLOW%wscript "%TEMPOY_DIR%\tempoy.vbs"%COLOR_RESET%
echo.
echo %COLOR_BLUE%To uninstall:%COLOR_RESET%
echo   • Run: %COLOR_YELLOW%"%~f0" --uninstall%COLOR_RESET%
echo.
echo %COLOR_BLUE%Configuration will be stored in:%COLOR_RESET%
echo   %TEMPOY_DIR%\config.json
echo.
echo %COLOR_YELLOW%Note: You may need to restart your terminal to use the 'tempoy' command.%COLOR_RESET%
echo.
pause
exit /b 0

:uninstall
echo %COLOR_BLUE%================================================================%COLOR_RESET%
echo %COLOR_BLUE%                    Tempoy Uninstallation                       %COLOR_RESET%
echo %COLOR_BLUE%================================================================%COLOR_RESET%
echo.
echo %COLOR_YELLOW%This will remove Tempoy but preserve your configuration.%COLOR_RESET%
set /p "CONFIRM=Are you sure? (y/N): "
if /i "!CONFIRM!" neq "y" (
    echo Uninstallation cancelled.
    pause
    exit /b 0
)

echo.
echo %COLOR_BLUE%Removing Tempoy installation...%COLOR_RESET%

:: Remove from PATH
echo Removing from PATH...
powershell -Command "& {$oldPath = [Environment]::GetEnvironmentVariable('PATH', 'USER'); $newPath = ($oldPath -split ';' | Where-Object { $_ -ne '%TEMPOY_DIR%' }) -join ';'; [Environment]::SetEnvironmentVariable('PATH', $newPath, 'USER')}" 2>nul

:: Try system PATH if we have admin rights
net session >nul 2>&1
if %errorLevel% == 0 (
    powershell -Command "& {$oldPath = [Environment]::GetEnvironmentVariable('PATH', 'MACHINE'); $newPath = ($oldPath -split ';' | Where-Object { $_ -ne '%TEMPOY_DIR%' }) -join ';'; [Environment]::SetEnvironmentVariable('PATH', $newPath, 'MACHINE')}" 2>nul
)

:: Remove Start Menu shortcuts
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Tempoy.lnk" 2>nul
del "%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs\Tempoy.lnk" 2>nul

:: Remove application files but preserve config
if exist "%TEMPOY_DIR%" (
    :: Backup config if it exists
    if exist "%CONFIG_FILE%" (
        copy "%CONFIG_FILE%" "%CONFIG_FILE%.backup" >nul 2>&1
    )
    
    :: Remove everything except config files
    if exist "%VENV_DIR%" rmdir /s /q "%VENV_DIR%" 2>nul
    del "%TEMPOY_DIR%\tempoy.py" 2>nul
    del "%TEMPOY_DIR%\tempoy.pyw" 2>nul
    del "%TEMPOY_DIR%\tempoy.vbs" 2>nul
    del "%TEMPOY_DIR%\tempoy.bat" 2>nul
    if exist "%PACKAGE_DIR%" rmdir /s /q "%PACKAGE_DIR%" 2>nul
    
    :: Restore config
    if exist "%CONFIG_FILE%.backup" (
        move "%CONFIG_FILE%.backup" "%CONFIG_FILE%" >nul 2>&1
        echo %COLOR_GREEN%Configuration preserved in %CONFIG_FILE%%COLOR_RESET%
    )
)

echo.
echo %COLOR_GREEN%================================================================%COLOR_RESET%
echo %COLOR_GREEN%                 Uninstallation Complete!                      %COLOR_RESET%
echo %COLOR_GREEN%================================================================%COLOR_RESET%
echo.
echo %COLOR_BLUE%Tempoy has been removed from your system.%COLOR_RESET%
echo %COLOR_BLUE%Your configuration has been preserved in: %COLOR_RESET%%TEMPOY_DIR%
echo.
echo %COLOR_YELLOW%To completely remove all traces including configuration:%COLOR_RESET%
echo   rmdir /s /q "%TEMPOY_DIR%"
echo.
pause
exit /b 0