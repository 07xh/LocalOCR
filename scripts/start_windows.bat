@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
if not exist .venv\Scripts\python.exe (
  echo [LocalOCR] Missing virtual environment.
  echo Run: powershell -ExecutionPolicy Bypass -File scripts\install_windows.ps1
  pause
  exit /b 1
)
echo LocalOCR Studio is opening locally.
echo If a key is needed, run: .venv\Scripts\python.exe -m localocr key
".venv\Scripts\python.exe" -m localocr studio --port 18765
pause
