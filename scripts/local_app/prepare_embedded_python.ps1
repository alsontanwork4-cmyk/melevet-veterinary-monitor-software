param(
    [Parameter(Mandatory = $true)]
    [string]$PackageRoot,
    [string]$PythonVersion = "3.11.9",
    [string]$CacheDir = "",
    [switch]$SkipPythonDownload
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$workspaceRoot = Resolve-Path (Join-Path $scriptDir "..\..")
$packageRootPath = Resolve-Path $PackageRoot

if ([string]::IsNullOrWhiteSpace($CacheDir)) {
    $CacheDir = Join-Path $workspaceRoot "output\local-app-cache"
}

$pythonCacheDir = Join-Path $CacheDir "python"
$pythonPackageDir = Join-Path $packageRootPath "python"
$sitePackagesDir = Join-Path $pythonPackageDir "Lib\site-packages"
$requirementsLock = Join-Path $packageRootPath "backend\requirements.lock"

if (-not (Test-Path $requirementsLock)) {
    throw "requirements.lock not found in package scaffold at $requirementsLock"
}

$pythonArchiveName = "python-$PythonVersion-embed-amd64.zip"
$pythonArchivePath = Join-Path $pythonCacheDir $pythonArchiveName
$pythonArchiveUrl = "https://www.python.org/ftp/python/$PythonVersion/$pythonArchiveName"
$getPipPath = Join-Path $pythonCacheDir "get-pip.py"
$getPipUrl = "https://bootstrap.pypa.io/get-pip.py"

function Download-File {
    param(
        [string]$Url,
        [string]$Destination,
        [switch]$ReuseExisting
    )

    if ($ReuseExisting -and (Test-Path $Destination)) {
        return
    }

    Write-Host "Downloading $Url"
    try {
        Invoke-WebRequest -Uri $Url -OutFile $Destination
    } catch {
        $message = "Failed to download $Url"
        if ($_.Exception.Message -match "404") {
            $message += ". The requested Python version may not publish Windows embeddable binaries. Python 3.11.9 is the last Python 3.11 release with Windows binaries."
        }
        throw $message
    }
}

function Update-PythonPathFile {
    param(
        [string]$PathFile
    )

    $lines = Get-Content $PathFile
    $normalized = New-Object System.Collections.Generic.List[string]
    $sitePackagesLine = "Lib\site-packages"
    $sawSitePackages = $false
    $sawImportSite = $false

    foreach ($line in $lines) {
        $trimmed = $line.Trim()
        if ($trimmed -eq $sitePackagesLine) {
            $sawSitePackages = $true
            $normalized.Add($sitePackagesLine)
            continue
        }
        if ($trimmed -eq "#import site" -or $trimmed -eq "import site") {
            $sawImportSite = $true
            $normalized.Add("import site")
            continue
        }
        $normalized.Add($line)
    }

    if (-not $sawSitePackages) {
        $normalized.Add($sitePackagesLine)
    }
    if (-not $sawImportSite) {
        $normalized.Add("import site")
    }

    Set-Content -Path $PathFile -Value $normalized -Encoding ascii
}

New-Item -ItemType Directory -Force -Path $pythonCacheDir | Out-Null

Download-File -Url $pythonArchiveUrl -Destination $pythonArchivePath -ReuseExisting:$SkipPythonDownload
Download-File -Url $getPipUrl -Destination $getPipPath -ReuseExisting

if (Test-Path $pythonPackageDir) {
    Remove-Item $pythonPackageDir -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $pythonPackageDir | Out-Null
Expand-Archive -Path $pythonArchivePath -DestinationPath $pythonPackageDir -Force
New-Item -ItemType Directory -Force -Path $sitePackagesDir | Out-Null

$pathFile = Get-ChildItem -Path $pythonPackageDir -Filter "python*._pth" | Select-Object -First 1
if (-not $pathFile) {
    throw "Unable to locate the Python ._pth file in $pythonPackageDir"
}

Update-PythonPathFile -PathFile $pathFile.FullName

$pythonExe = Join-Path $pythonPackageDir "python.exe"
if (-not (Test-Path $pythonExe)) {
    throw "Embedded Python executable not found at $pythonExe"
}

Write-Host "Bootstrapping pip into embedded Python"
& $pythonExe $getPipPath --no-warn-script-location
if ($LASTEXITCODE -ne 0) {
    throw "Failed to bootstrap pip into the embedded Python runtime."
}

Write-Host "Vendoring backend Python dependencies"
& $pythonExe -m pip install `
    --disable-pip-version-check `
    --no-warn-script-location `
    --only-binary=:all: `
    --upgrade `
    --requirement $requirementsLock `
    --target $sitePackagesDir
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install backend dependencies into the embedded Python runtime."
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

Write-Host "Verifying bundled Python imports"
$importOutput = & $pythonExe -c $importCheck 2>&1
if ($LASTEXITCODE -ne 0) {
    $detail = (($importOutput | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine).Trim()
    if ([string]::IsNullOrWhiteSpace($detail)) {
        $detail = "Import verification failed."
    }
    throw "Embedded Python verification failed.`n`n$detail"
}

$resolvedVersion = & $pythonExe -c "import sys; print('.'.join(str(part) for part in sys.version_info[:3]))"
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($resolvedVersion)) {
    throw "Embedded Python could not report its version after installation."
}

$buildInfo = @"
PythonVersion=$resolvedVersion
PythonArchive=$pythonArchiveName
PythonArchiveUrl=$pythonArchiveUrl
"@

Set-Content -Path (Join-Path $pythonPackageDir "BUILD_INFO.txt") -Value $buildInfo -Encoding ascii
Write-Host "Embedded Python prepared at $pythonPackageDir"
