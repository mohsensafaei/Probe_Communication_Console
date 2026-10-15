@echo off
setlocal
cd /d "%~dp0"
if defined PROBE_PYTHON (
    "%PROBE_PYTHON%" windows_bootstrap.py %*
    goto :done
)
where py >nul 2>nul
if not errorlevel 1 (
    py -3 windows_bootstrap.py %*
    goto :done
)
python windows_bootstrap.py %*
:done
set "probe_exit=%errorlevel%"
if not "%probe_exit%"=="0" if not defined CI pause
exit /b %probe_exit%
