param(
    [string]$InstallRoot = ""
)

$ErrorActionPreference = "Stop"
$minimumPythonVersion = [Version]"3.11.0"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
    $InstallRoot = Resolve-Path (Join-Path $scriptDir "..\..")
}

$pythonPath = Join-Path $InstallRoot "python\python.exe"
if (-not (Test-Path $pythonPath)) {
    throw "Bundled Python runtime not found at $pythonPath"
}

try {
    $pythonVersionOutput = & $pythonPath -c "import sys; print('.'.join(str(part) for part in sys.version_info[:3]))"
} catch {
    throw "Bundled Python could not be started from $pythonPath"
}

if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($pythonVersionOutput)) {
    throw "Bundled Python could not report its version from $pythonPath"
}

$pythonVersion = [Version]$pythonVersionOutput.Trim()
if ($pythonVersion -lt $minimumPythonVersion) {
    throw "Bundled Python version $pythonVersion is too old. Melevet requires Python 3.11+."
}

$importCheck = @"
import fastapi
import uvicorn
import sqlalchemy
import pydantic_core
import greenlet
import httptools
import watchfiles
import argon2
print("ok")
"@

try {
    $importResult = & $pythonPath -c $importCheck 2>&1
} catch {
    throw "Bundled Python dependencies are not usable. Rebuild the package and try again."
}

if ($LASTEXITCODE -ne 0) {
    $detail = (($importResult | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine).Trim()
    if ([string]::IsNullOrWhiteSpace($detail)) {
        $detail = "Dependency import validation failed."
    }
    throw "Bundled Python dependencies are not usable.`n`n$detail"
}

$shortcutScript = Join-Path $scriptDir "create_shortcuts.ps1"
& $shortcutScript -InstallRoot $InstallRoot

Write-Host "Melevet installation completed."
Write-Host "Bundled Python: $pythonVersion"
Write-Host "Shortcuts created on the Desktop and Start Menu."
Write-Host "Launch Melevet from the shortcut to start the local app."
