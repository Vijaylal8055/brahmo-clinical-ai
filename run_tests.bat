@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (
  echo Virtual environment not found. Run run_app.bat once first.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
python -m pytest -q
pause
