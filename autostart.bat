@echo off
setlocal enabledelayedexpansion
:: ---------------------------------------------------------------------------
:: Tempoy Autostart Manager (refactored)
:: Usage: autostart-tempoy.bat [--enable|--disable|--status|--help]
:: ---------------------------------------------------------------------------

set "SCRIPT_NAME=%~nx0"
set "REG_KEY=HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run"
set "REG_VALUE=Tempoy"
set "TEMPOY_HOME=%USERPROFILE%\.tempoy"
set "CANDIDATE_EXE1=%TEMPOY_HOME%\tempoy.exe"
set "CANDIDATE_EXE2=%~dp0dist\tempoy\tempoy.exe"
set "CANDIDATE_PYW_INSTALLED=%TEMPOY_HOME%\tempoy.pyw"
set "CANDIDATE_PYW=%~dp0tempoy.pyw"
set "LAUNCHER_VBS=%TEMPOY_HOME%\launch-tempoy.vbs"
set "ACTION=enable"

if "%1"=="--enable"  set "ACTION=enable"
if "%1"=="--disable" set "ACTION=disable"
if "%1"=="--status"  set "ACTION=status"
if "%1"=="--help"    goto :help
if "%1"=="/?"        goto :help

call :detect_exe || goto :noexe
call :ensure_launcher || goto :fail

if "%ACTION%"=="status"  goto :status
if "%ACTION%"=="disable" goto :disable
if "%ACTION%"=="enable"  goto :enable
goto :help

:enable
echo Enabling Tempoy autostart...
reg query "%REG_KEY%" /v "%REG_VALUE%" >nul 2>&1 && (
    echo Existing registration found.
    for /f "tokens=3*" %%a in ('reg query "%REG_KEY%" /v "%REG_VALUE%" ^| find "%REG_VALUE%"') do echo   Current: %%a %%b
    set /p "CONFIRM=Update it? (y/N): "
    if /i not "!CONFIRM!"=="y" goto :afterEnable
)

reg add "%REG_KEY%" /v "%REG_VALUE%" /t REG_SZ /d "wscript.exe //B \"%LAUNCHER_VBS%\"" /f >nul 2>&1 || (
    echo ERROR: Failed to add registry entry.
    goto :fail
)
echo Added registry entry pointing to launcher.

:afterEnable
reg query "%REG_KEY%" /v "%REG_VALUE%" >nul 2>&1 && (
    echo Autostart ENABLED.
    goto :end
) || (
    echo ERROR: Could not verify registration.
    goto :fail
)

:disable
echo Disabling Tempoy autostart...
reg query "%REG_KEY%" /v "%REG_VALUE%" >nul 2>&1 || (
    echo Already disabled.
    goto :end
)
reg delete "%REG_KEY%" /v "%REG_VALUE%" /f >nul 2>&1 || (
    echo ERROR: Failed to remove registry value.
    goto :fail
)
echo Autostart DISABLED.
goto :end

:status
echo --- Tempoy Autostart Status ---
reg query "%REG_KEY%" /v "%REG_VALUE%" >nul 2>&1 && (
    echo Status : ENABLED
    for /f "tokens=3*" %%a in ('reg query "%REG_KEY%" /v "%REG_VALUE%" ^| find "%REG_VALUE%"') do echo Command: %%a %%b
) || echo Status : DISABLED
if exist "%LAUNCHER_VBS%" (echo Launcher: %LAUNCHER_VBS%) else echo Launcher: (missing)
if exist "%TEMPOY_EXE%"  (echo Target  : %TEMPOY_EXE%) else echo Target  : (missing)
tasklist /fi "imagename eq tempoy.exe" 2>nul | find /i "tempoy.exe" >nul && echo Running : YES || (
    tasklist /fi "imagename eq pythonw.exe" 2>nul | find /i "pythonw.exe" >nul && echo Running : (pythonw present) || echo Running : NO
)
goto :end

:detect_exe
if exist "%CANDIDATE_EXE1%" set "TEMPOY_EXE=%CANDIDATE_EXE1%"
if not defined TEMPOY_EXE if exist "%CANDIDATE_EXE2%" set "TEMPOY_EXE=%CANDIDATE_EXE2%"
if not defined TEMPOY_EXE if exist "%CANDIDATE_PYW_INSTALLED%" set "TEMPOY_EXE=%CANDIDATE_PYW_INSTALLED%"
if not defined TEMPOY_EXE if exist "%CANDIDATE_PYW%" set "TEMPOY_EXE=%CANDIDATE_PYW%"
if defined TEMPOY_EXE (
    if /i "%TEMPOY_EXE:~-4%"==".pyw" (
        set "PY_CMD=pythonw.exe \"%TEMPOY_EXE%\""
    ) else (
        set "PY_CMD=\"%TEMPOY_EXE%\""
    )
    exit /b 0
) else (
    exit /b 1
)

:ensure_launcher
if not exist "%TEMPOY_HOME%" mkdir "%TEMPOY_HOME%" >nul 2>&1
set "RECREATE=0"
if not exist "%LAUNCHER_VBS%" set "RECREATE=1"
if exist "%LAUNCHER_VBS%" (
    for /f "usebackq delims=" %%l in ("%LAUNCHER_VBS%") do echo %%l | find /i "%TEMPOY_EXE%" >nul || set "RECREATE=1"
)
if "%RECREATE%"=="1" (
    echo Creating launcher VBS: %LAUNCHER_VBS%
    > "%LAUNCHER_VBS%" (
        echo Set oShell = CreateObject("WScript.Shell")
        echo oShell.Run %PY_CMD%,0
        echo Set oShell = Nothing
    )
)
if exist "%LAUNCHER_VBS%" exit /b 0
exit /b 1

:noexe
echo ERROR: Could not locate Tempoy executable.
echo Looked for:
echo   %CANDIDATE_EXE1%
echo   %CANDIDATE_EXE2%
echo   %CANDIDATE_PYW_INSTALLED%
echo   %CANDIDATE_PYW%
echo Build or install Tempoy first.
goto :fail

:help
echo Tempoy Autostart Manager
echo.
echo Usage:
echo   %SCRIPT_NAME% [--enable ^| --disable ^| --status ^| --help]
echo.
echo Actions:
echo   --enable   Register autostart (default)
echo   --disable  Remove autostart
echo   --status   Show registration and launcher status
echo   --help     Show this help
echo.
echo The script searches for a packaged tempoy.exe in:
echo   1. %CANDIDATE_EXE1%
echo   2. %CANDIDATE_EXE2%
echo Falls back to tempoy.pyw if no exe found.
echo A hidden launcher VBS is generated (launch-tempoy.vbs) and a HKCU Run entry created.
goto :end

:fail
echo.
echo Operation FAILED.
goto :end

:end
endlocal
exit /b 0