param([int]$Port = 8765)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create Python virtual environment.' }
}
& '.venv/Scripts/python.exe' -m pip install -r requirements.txt --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
Write-Host "Lianzheng AI: http://127.0.0.1:$Port"
& '.venv/Scripts/python.exe' -m uvicorn lianzheng.app:app --host 127.0.0.1 --port $Port
