param(
    [int]$Port = 8000,
    [string]$RuntimeRoot = ""
)

$ErrorActionPreference = "Stop"
$minimumPythonVersion = [Version]"3.11.0"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$workspaceRoot = Resolve-Path (Join-Path $scriptDir "..\..")
$launcherScript = Join-Path $scriptDir "local_launcher.py"

function Show-LauncherError {
    param(
        [string]$Message
    )

    try {
        Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
        [void][System.Windows.Forms.MessageBox]::Show(
            $Message,
            "Melevet Startup Error",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error
        )
    } catch {
        Write-Error $Message
    }
}

function Get-PythonVersion {
    param(
        [string]$CommandPath
    )

    try {
        $output = & $CommandPath -c "import sys; print('.'.join(str(part) for part in sys.version_info[:3]))" 2>$null
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($output)) {
            return $null
        }
        return [Version]($output.Trim())
    } catch {
        return $null
    }
}

function Resolve-PythonCommand {
    $errors = New-Object System.Collections.Generic.List[string]
    $candidates = @(
        @{ Path = (Join-Path $workspaceRoot "python\python.exe"); Label = "bundled Python" },
        @{ Path = (Join-Path $workspaceRoot "backend\.venv\Scripts\python.exe"); Label = "backend virtualenv Python" },
        @{ Path = "python"; Label = "system Python"; IsCommand = $true }
    )

    foreach ($candidate in $candidates) {
        $path = [string]$candidate.Path
        $exists = $candidate.IsCommand -or (Test-Path $path)
        if (-not $exists) {
            continue
        }

        $version = Get-PythonVersion -CommandPath $path
        if (-not $version) {
            $errors.Add("Found $($candidate.Label) at '$path' but it could not be executed.")
            continue
        }
        if ($version -lt $minimumPythonVersion) {
            $errors.Add("Found $($candidate.Label) at '$path' with version $version, but Melevet requires Python 3.11+.")
            continue
        }

        return $path
    }

    if ($errors.Count -gt 0) {
        throw ("Unable to locate a usable Python runtime for Melevet.`n`n" + ($errors -join "`n"))
    }
    throw "Unable to locate Python for scripts\local_app\local_launcher.py"
}

if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) {
    if ($env:LOCALAPPDATA) {
        $RuntimeRoot = Join-Path $env:LOCALAPPDATA "Melevet"
    } else {
        $RuntimeRoot = Join-Path $workspaceRoot "output\local-app-data"
    }
}

try {
    $pythonCommand = Resolve-PythonCommand
} catch {
    Show-LauncherError -Message $_.Exception.Message
    exit 1
}

$launcherOutput = & $pythonCommand $launcherScript --port $Port --runtime-root $RuntimeRoot 2>&1
$launcherExitCode = $LASTEXITCODE

if ($launcherOutput) {
    $launcherOutput | ForEach-Object { Write-Host $_ }
}

if ($launcherExitCode -ne 0) {
    $message = (($launcherOutput | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine).Trim()
    if ([string]::IsNullOrWhiteSpace($message)) {
        $message = "Melevet failed to start. Check the logs under $RuntimeRoot\logs for details."
    }
    Show-LauncherError -Message $message
    exit $launcherExitCode
}
