@echo off
title Riddle-FUVT  -  Riddle FiveM Ultimate Vehicle Tool
setlocal EnableExtensions
cd /d "%~dp0"

set "VENVW=%~dp0.venv\Scripts\pythonw.exe"
set "VENVC=%~dp0.venv\Scripts\python.exe"
set "READY=%~dp0.venv\.ready"
set "APP=app\main.py"

REM ---------------------------------------------------------------------------
REM Maintenance flags. Everything here used to live in a second .bat.
REM
REM   --diag       run with the dev console, for a bug report
REM   --repair     delete .venv and install everything again
REM   --check      show what is installed and which unpackers were found
REM   --shortcut   put a shortcut with the icon on the desktop
REM ---------------------------------------------------------------------------
if /i "%~1"=="--help"     goto :usage
if /i "%~1"=="-h"         goto :usage
if /i "%~1"=="/?"         goto :usage
if /i "%~1"=="--repair"   goto :repair
if /i "%~1"=="--check"    goto :check
if /i "%~1"=="--shortcut" goto :shortcut

REM ---------------------------------------------------------------------------
REM Warm start. Once the environment exists there is nothing to check, so the
REM app opens with no console work at all. Everything below runs on first launch.
REM ---------------------------------------------------------------------------
if exist "%VENVW%" if exist "%READY%" goto :launch

REM ---------------------------------------------------------------------------
REM Find a Python to bootstrap with. The py launcher is asked for 3.10 or newer
REM explicitly - "is py installed" is not the same question, and a leftover 3.8
REM would otherwise get all the way to an import error.
REM ---------------------------------------------------------------------------
call :findpy
if defined PY goto :bootstrap

echo.
echo   Riddle-FUVT needs Python 3.10 or newer, and none was found.
echo.
where winget >nul 2>nul
if errorlevel 1 (
  echo   Install it from  https://www.python.org/downloads/
  echo   and tick "Add python.exe to PATH" in the installer, then run this again.
  echo.
  pause
  exit /b 1
)
echo   Windows can install it for you now with winget.
echo   Nothing else on your machine is changed.
echo.
choice /c YN /m "  Install Python 3.12 now"
if errorlevel 2 (
  echo.
  echo   No problem. Install it from https://www.python.org/downloads/
  echo   and run this again.
  echo.
  pause
  exit /b 1
)
echo.
echo   Installing Python. This can take a couple of minutes...
winget install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
  echo.
  echo   winget could not install Python. Get it from
  echo   https://www.python.org/downloads/  and run this again.
  echo.
  pause
  exit /b 1
)
REM winget adds Python to PATH for new processes, not this one.
echo.
echo   Python installed. Close this window and run Riddle-FUVT again to finish.
echo.
pause
exit /b 0

REM ---------------------------------------------------------------------------
REM Build the private environment. bootstrap.py owns the real work. Installing
REM takes a minute or two with no output while pip works.
REM ---------------------------------------------------------------------------
:bootstrap
echo.
%PY% "scripts\bootstrap.py" %*
if errorlevel 1 (
  echo.
  pause
  exit /b 1
)

if not exist "%VENVW%" (
  echo.
  echo   Setup finished but the environment is missing.
  echo   Run  Riddle-FUVT.bat --repair  to rebuild it.
  echo.
  pause
  exit /b 1
)

REM ---------------------------------------------------------------------------
REM pythonw.exe keeps the console from flashing up behind the window. If the app
REM cannot start, rerun it with python.exe so the error is actually visible
REM instead of vanishing with the hidden console.
REM ---------------------------------------------------------------------------
:launch
if /i "%~1"=="--diag" goto :diag
start "" /wait "%VENVW%" "%APP%"
if errorlevel 1 (
  echo.
  echo   Riddle-FUVT closed with an error. Running again to show it:
  echo.
  "%VENVC%" "%APP%"
  echo.
  pause
)
exit /b 0


REM ===========================================================================
:diag
echo.
echo   Starting with diagnostics on. Check the dev console's Console tab for
echo   the [boot] line.
echo.
"%VENVC%" "%APP%" --diag
echo.
echo   Window closed. Copy everything above, plus the [boot] line from the
echo   dev console, into a GitHub issue.
goto :done


REM ===========================================================================
:repair
echo.
echo   This deletes the .venv folder and installs everything again.
echo   Nothing outside this folder is touched, and no settings are lost.
echo.
choice /c YN /m "  Continue"
if errorlevel 2 exit /b 0

call :findpy
if not defined PY goto :nopython
echo.
%PY% "scripts\bootstrap.py" --repair
goto :done


REM ===========================================================================
:check
if not exist "%VENVC%" goto :notinstalled
echo.
"%VENVC%" -c "import sys, importlib.metadata as m; print('  python    ', sys.version.split()[0]); print('  pywebview ', m.version('pywebview'))"
"%VENVC%" -c "import importlib.metadata as m; print('  py7zr     ', m.version('py7zr'))" 2>nul || echo   py7zr      not installed - .7z archives unsupported
"%VENVC%" -c "import sys; sys.path.insert(0, 'app'); import riddle_archives as r; b=r.backends(); print('  7-Zip     ', b['sevenzip'] or 'not found'); print('  UnRAR     ', b['unrar'] or 'not found')"
goto :done


REM ===========================================================================
:shortcut
REM Prefer the app's own environment, but this works from any Python - the
REM script only needs the standard library and PowerShell.
set "PY="
if exist "%VENVC%" set PY="%VENVC%"
if not defined PY call :findpy
if not defined PY goto :nopython
echo.
%PY% "scripts\make_shortcut.py" --desktop
goto :done


REM ===========================================================================
:usage
echo.
echo   Riddle-FUVT
echo.
echo     Riddle-FUVT.bat              start the app
echo     Riddle-FUVT.bat --diag       start with the dev console, for bug reports
echo     Riddle-FUVT.bat --repair     rebuild the environment
echo     Riddle-FUVT.bat --check      show what is installed
echo     Riddle-FUVT.bat --shortcut   add a desktop shortcut
echo.
exit /b 0


REM ===========================================================================
REM Find a Python 3.10+. Sets PY, or leaves it undefined.
REM
REM `if defined` is a runtime test, so this works inside the for loop without
REM delayed expansion. Reading %PY% inside a parenthesised block would not -
REM that expands when the block is parsed, before the loop has run.
REM ===========================================================================
:findpy
set "PY="
for %%V in (3.13 3.12 3.11 3.10) do (
    if not defined PY py -%%V -c "import sys" >nul 2>nul && set "PY=py -%%V"
)
if defined PY exit /b 0
python -c "import sys; raise SystemExit(0 if sys.version_info>=(3,10) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=python"
exit /b 0


REM ===========================================================================
:nopython
echo.
echo   No Python 3.10 or newer was found.
echo   Install it from https://www.python.org/downloads/ and run this again.
goto :done

:notinstalled
echo.
echo   Nothing is installed yet. Run Riddle-FUVT.bat once first.
goto :done

:done
echo.
pause
exit /b 0
