@echo off
rem Double-click this file (on Windows) to start CV Maker. It sets everything up the first time.
cd /d "%~dp0"

where python >nul 2>nul || (
  echo Python isn't installed. Get it from https://www.python.org/downloads/ and try again.
  pause
  exit /b 1
)

if not exist .venv (
  echo First run: setting up, this takes a minute...
  python -m venv .venv || (echo Couldn't set up Python. & pause & exit /b 1)
)
call .venv\Scripts\activate.bat

for /f %%h in ('certutil -hashfile requirements.txt SHA1 ^| find /v ":"') do set WANTED=%%h
set /p HAVE=<.venv\requirements-hash 2>nul
if not "%HAVE%"=="%WANTED%" (
  echo Installing what CV Maker needs...
  python -m pip install -q --upgrade pip >nul
  python -m pip install -q -r requirements.txt && echo %WANTED%> .venv\requirements-hash
)

echo Starting CV Maker. Keep this window open while you use it; close it to stop.
python -m cv_maker %*
pause
