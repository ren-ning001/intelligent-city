$ErrorActionPreference = "Stop"
$Utf8 = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $Utf8
[Console]::OutputEncoding = $Utf8
$OutputEncoding = $Utf8

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if (-not (Test-Path ".env")) {
    Write-Warning ".env was not found. Copy .env.example to .env and set DEEPSEEK_API_KEY."
    Write-Warning "OSM and routing APIs still work, but Agent requests require credentials."
}

conda run --no-capture-output -n zyourroad `
    python -m uvicorn backend.app.main:app `
    --host 127.0.0.1 `
    --port 8000 `
    --reload
