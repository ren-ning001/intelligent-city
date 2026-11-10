$ErrorActionPreference = "Stop"
$Utf8 = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $Utf8
[Console]::OutputEncoding = $Utf8
$OutputEncoding = $Utf8

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$EnvironmentName = "zyourroad"

Set-Location $ProjectRoot

$Existing = conda env list | Select-String "\b$EnvironmentName\b"
if (-not $Existing) {
    conda create -n $EnvironmentName python=3.12 -y
}

conda run -n $EnvironmentName python -m pip install --upgrade pip
conda run -n $EnvironmentName python -m pip install -r .\backend\requirements.txt

Write-Host "Conda environment is ready: $EnvironmentName" -ForegroundColor Green
Write-Host "Activate with: conda activate $EnvironmentName"
