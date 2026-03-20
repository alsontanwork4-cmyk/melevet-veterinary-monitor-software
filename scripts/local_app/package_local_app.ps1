param(
    [string]$OutputDir = "",
    [switch]$SkipFrontendBuild,
    [string]$PythonVersion = "3.11.9",
    [string]$CacheDir = "",
    [switch]$SkipPythonDownload
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$workspaceRoot = Resolve-Path (Join-Path $scriptDir "..\..")
$versionFile = Join-Path $workspaceRoot "VERSION"

if (-not (Test-Path $versionFile)) {
    throw "VERSION file not found at $versionFile"
}

$appVersion = (Get-Content $versionFile -Raw).Trim()
if ([string]::IsNullOrWhiteSpace($appVersion)) {
    throw "VERSION file is empty."
}

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $workspaceRoot "output\local-app-package"
}

$packageRoot = Join-Path $OutputDir "Melevet"
$zipPath = Join-Path $OutputDir ("Melevet-v{0}-windows-x64.zip" -f $appVersion)
$backendPackage = Join-Path $packageRoot "backend"
$frontendPackage = Join-Path $packageRoot "frontend"
$scriptsPackage = Join-Path $packageRoot "scripts\local_app"
$preparePythonScript = Join-Path $scriptDir "prepare_embedded_python.ps1"

if (Test-Path $packageRoot) {
    Remove-Item $packageRoot -Recurse -Force
}

if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}

New-Item -ItemType Directory -Force -Path $backendPackage | Out-Null
New-Item -ItemType Directory -Force -Path $frontendPackage | Out-Null
New-Item -ItemType Directory -Force -Path $scriptsPackage | Out-Null

if (-not $SkipFrontendBuild) {
    Push-Location (Join-Path $workspaceRoot "frontend")
    try {
        $env:VITE_LOCAL_APP_MODE = "true"
        $env:VITE_APP_VERSION = $appVersion
        npm run build
    } finally {
        Remove-Item Env:VITE_APP_VERSION -ErrorAction SilentlyContinue
        Remove-Item Env:VITE_LOCAL_APP_MODE -ErrorAction SilentlyContinue
        Pop-Location
    }
}

$frontendDist = Join-Path $workspaceRoot "frontend\dist"
if (-not (Test-Path $frontendDist)) {
    throw "Frontend dist not found at $frontendDist. Run the frontend build or omit -SkipFrontendBuild."
}

Copy-Item $versionFile -Destination (Join-Path $packageRoot "VERSION") -Force
Copy-Item $frontendDist -Destination $frontendPackage -Recurse -Force
Copy-Item (Join-Path $workspaceRoot "backend\app") -Destination $backendPackage -Recurse -Force
Copy-Item (Join-Path $workspaceRoot "backend\alembic") -Destination $backendPackage -Recurse -Force
Copy-Item (Join-Path $workspaceRoot "backend\alembic.ini") -Destination $backendPackage -Force
Copy-Item (Join-Path $workspaceRoot "backend\requirements.lock") -Destination $backendPackage -Force
Copy-Item (Join-Path $workspaceRoot "backend\requirements.txt") -Destination $backendPackage -Force

$clientScriptFiles = @(
    "launch_melevet.ps1",
    "local_launcher.py",
    "install.ps1",
    "create_shortcuts.ps1",
    "README.md"
)

foreach ($fileName in $clientScriptFiles) {
    Copy-Item (Join-Path $scriptDir $fileName) -Destination $scriptsPackage -Force
}

& $preparePythonScript `
    -PackageRoot $packageRoot `
    -PythonVersion $PythonVersion `
    -CacheDir $CacheDir `
    -SkipPythonDownload:$SkipPythonDownload

$notes = @"
Package created at:
$packageRoot

This package includes:
- python\ (embedded Python runtime plus vendored dependencies)
- frontend\dist
- backend source tree
- local launcher scripts

Install on the clinic PC with:
scripts\local_app\install.ps1

Archive:
$zipPath

Bundled Python version:
$PythonVersion
"@

Set-Content -Path (Join-Path $packageRoot "PACKAGING_NOTES.txt") -Value $notes -Encoding utf8
Compress-Archive -Path $packageRoot -DestinationPath $zipPath -Force

Write-Host "Local app package created at $packageRoot"
Write-Host "ZIP archive created at $zipPath"
