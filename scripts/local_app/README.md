# Local Windows App Support

This folder contains the packaging and launcher scripts for the self-contained Windows ZIP build of Melevet.

## Files

- `prepare_embedded_python.ps1`: Build-only helper that downloads the Python 3.11 embeddable runtime, vendors backend dependencies into it, and verifies imports.
- `package_local_app.ps1`: Builds the frontend, assembles the package folder, vendors the embedded Python runtime, and creates the final ZIP archive.
- `install.ps1`: One-time setup script for clinic IT. It validates the bundled runtime and creates Desktop and Start Menu shortcuts.
- `launch_melevet.ps1`: One-click launcher for packaged installs and local development fallbacks.
- `local_launcher.py`: Shared launcher logic that avoids duplicate starts, prepares runtime directories, starts the backend, and opens the browser.
- `create_shortcuts.ps1`: Creates Desktop and Start Menu shortcuts that point to the PowerShell launcher.

## Packaging Workflow

Run the package script from the repository root:

```powershell
scripts\local_app\package_local_app.ps1
```

Useful parameters:

- `-PythonVersion 3.11.9`: Override the bundled Python version.
- `-SkipPythonDownload`: Reuse the cached Python embed ZIP if it has already been downloaded.
- `-SkipFrontendBuild`: Reuse an existing `frontend\dist` folder.
- `-CacheDir <path>`: Override the download cache location.

The packaging flow requires internet access on the build machine. Clinic runtime machines do not need internet access.

## Package Layout

The generated package contains:

- `python\`: Embedded Python runtime and vendored backend dependencies.
- `frontend\dist\`: Pre-built frontend assets.
- `backend\`: FastAPI backend source, Alembic files, and pinned requirements.
- `scripts\local_app\`: Launcher, installer, shortcut script, and this README.
- `VERSION`

## Clinic Installation

On the clinic PC:

1. Extract the ZIP to a writable folder such as `C:\Melevet`.
2. Run `scripts\local_app\install.ps1`.
3. Launch Melevet from the Desktop or Start Menu shortcut.

No system Python, Node.js, or `.env` file is required on the clinic PC.

## Runtime Layout

By default the launcher uses `%LOCALAPPDATA%\Melevet\` for runtime data:

- `melevet.db`
- `staged_uploads\`
- `upload_spool\`
- `logs\`
- `archives\`
- `telemetry\`

If `LOCALAPPDATA` is unavailable, the launcher falls back to `output\local-app-data\` in the workspace.

## Runtime Behavior

- `local_launcher.py` checks `http://127.0.0.1:<port>/health` before starting a new backend process. If Melevet is already healthy, it opens the browser and exits without creating a second backend.
- If the port is already in use by some other process, the launcher shows a clear startup error instead of waiting for a generic health timeout.
- Local packaged launches force `APP_MODE=local` and disable update checks, so startup does not depend on internet connectivity.

## Troubleshooting

- If startup fails, inspect `%LOCALAPPDATA%\Melevet\logs\backend.stderr.log`.
- If `python\python.exe` is missing or corrupt, rerun packaging and replace the package on the clinic PC.
- If the install script reports missing imports, the embedded runtime was not packaged correctly. Rebuild the ZIP on the build machine.
- If port `8000` is already in use, close the conflicting local application before launching Melevet.
