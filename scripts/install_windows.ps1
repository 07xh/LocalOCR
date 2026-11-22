$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
if (!(Test-Path '.venv\Scripts\python.exe')) { py -3 -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
Write-Host 'Installation finished. Run scripts\start_windows.bat'
Write-Host 'Note: RapidOCR model files may require an initial download.'
