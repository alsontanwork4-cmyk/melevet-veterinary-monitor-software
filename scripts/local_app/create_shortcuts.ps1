param(
    [string]$InstallRoot = "",
    [switch]$DesktopShortcut = $true,
    [switch]$StartMenuShortcut = $true
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
    $InstallRoot = Resolve-Path (Join-Path $scriptDir "..\..")
}

$launcherPath = Join-Path $InstallRoot "scripts\local_app\launch_melevet.ps1"
if (-not (Test-Path $launcherPath)) {
    throw "Launcher not found at $launcherPath"
}

$iconCandidates = @(
    (Join-Path $InstallRoot "assets\melevet.ico"),
    (Join-Path $InstallRoot "scripts\local_app\melevet.ico")
)
$iconPath = $iconCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

$shell = New-Object -ComObject WScript.Shell

function New-MelevetShortcut {
    param(
        [string]$ShortcutPath
    )

    $shortcut = $shell.CreateShortcut($ShortcutPath)
    $shortcut.TargetPath = "powershell.exe"
    $shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$launcherPath`""
    $shortcut.WorkingDirectory = $InstallRoot
    $shortcut.WindowStyle = 1
    $shortcut.Description = "Launch Melevet local app"
    if ($iconPath) {
        $shortcut.IconLocation = $iconPath
    }
    $shortcut.Save()
}

if ($DesktopShortcut) {
    New-MelevetShortcut -ShortcutPath (Join-Path ([Environment]::GetFolderPath("Desktop")) "Melevet.lnk")
}

if ($StartMenuShortcut) {
    $menuDir = Join-Path ([Environment]::GetFolderPath("Programs")) "Melevet"
    New-Item -ItemType Directory -Force -Path $menuDir | Out-Null
    New-MelevetShortcut -ShortcutPath (Join-Path $menuDir "Melevet.lnk")
}
