from __future__ import annotations

import argparse
import ctypes
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

REQUIRED_PYTHON = (3, 11)


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_runtime_root() -> Path:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / "Melevet"
    return _workspace_root() / "output" / "local-app-data"


def _windows_sqlite_url(path: Path) -> str:
    normalized = path.resolve().as_posix()
    return f"sqlite:///{normalized}"


def _can_connect(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.settimeout(0.25)
        return client.connect_ex(("127.0.0.1", port)) == 0


def _wait_for_health(base_url: str, *, timeout_seconds: float = 45.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    health_url = f"{base_url.rstrip('/')}/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=1.5) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.5)
    return False


def _show_windows_error(message: str, *, title: str = "Melevet Startup Error") -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
    except Exception:
        pass


def _emit_critical_error(message: str) -> None:
    print(message, file=sys.stderr)
    _show_windows_error(message)


def _runtime_stderr_path(runtime_root: Path) -> Path:
    return runtime_root / "logs" / "backend.stderr.log"


def _tail_text(path: Path, *, max_lines: int = 20, max_chars: int = 4000) -> str:
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    if not lines:
        return ""
    tail = "\n".join(lines[-max_lines:])
    return tail[-max_chars:]


def _python_version_string(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)


def _probe_python_version(python_path: Path) -> tuple[int, int, int]:
    command = [
        str(python_path),
        "-c",
        "import sys; print('.'.join(str(part) for part in sys.version_info[:3]))",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
    except OSError as exc:
        raise RuntimeError(f"Failed to execute Python runtime at {python_path}: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Timed out while checking Python runtime at {python_path}.") from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "no output").strip()
        raise RuntimeError(f"Python runtime at {python_path} is not usable: {detail}")

    raw_version = result.stdout.strip()
    parts = raw_version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise RuntimeError(f"Python runtime at {python_path} returned an invalid version string: {raw_version!r}")

    return tuple(int(part) for part in parts)


def _resolve_backend_command(root: Path) -> tuple[list[str], Path]:
    candidates = [
        root / "backend-dist" / "MelevetBackend.exe",
        root / "backend" / "dist" / "MelevetBackend.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return ([str(candidate)], candidate.parent)

    python_candidates = [
        root / "python" / "python.exe",
        root / "backend" / ".venv" / "Scripts" / "python.exe",
        Path(sys.executable),
    ]
    seen: set[Path] = set()
    errors: list[str] = []
    for candidate in python_candidates:
        resolved = candidate.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        if not candidate.exists():
            continue

        try:
            version = _probe_python_version(candidate)
        except RuntimeError as exc:
            errors.append(str(exc))
            continue
        if version < REQUIRED_PYTHON:
            errors.append(
                f"Python {_python_version_string(version)} found at {candidate}, but Melevet requires "
                f"{REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]}+."
            )
            continue

        return (
            [
                str(candidate),
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                os.environ.get("MELEVET_PORT", "8000"),
            ],
            root / "backend",
        )

    detail = "\n".join(f"- {item}" for item in errors)
    if detail:
        raise RuntimeError(f"Unable to locate a usable Python runtime for Melevet.\n{detail}")
    raise FileNotFoundError("Unable to locate a backend executable or Python runtime.")


def _build_runtime_env(root: Path, runtime_root: Path, port: int) -> dict[str, str]:
    runtime_root.mkdir(parents=True, exist_ok=True)
    db_path = runtime_root / "melevet.db"
    stage_dir = runtime_root / "staged_uploads"
    spool_dir = runtime_root / "upload_spool"
    logs_dir = runtime_root / "logs"
    frontend_dist = root / "frontend" / "dist"

    for directory in (stage_dir, spool_dir, logs_dir):
        directory.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.update(
        {
            "APP_ENV": "production",
            "APP_MODE": "local",
            "ENABLE_DOCS": "false",
            "DATABASE_URL": _windows_sqlite_url(db_path),
            "STAGE_STORAGE_DIR": str(stage_dir),
            "STAGED_UPLOAD_DIR": str(stage_dir),
            "UPLOAD_SPOOL_DIR": str(spool_dir),
            "CORS_ORIGINS": env.get("CORS_ORIGINS", f"http://127.0.0.1:{port},http://localhost:{port}"),
            "MELEVET_RUNTIME_ROOT": str(runtime_root),
            "MELEVET_LOG_DIR": str(logs_dir),
            "MELEVET_FRONTEND_DIST": str(frontend_dist),
            "MELEVET_PORT": str(port),
            "UPDATE_CHECK_ENABLED": "false",
            "PYTHONUNBUFFERED": "1",
        }
    )
    return env


def _start_backend(root: Path, runtime_root: Path, port: int) -> subprocess.Popen[bytes]:
    command, workdir = _resolve_backend_command(root)
    env = _build_runtime_env(root, runtime_root, port)
    logs_dir = runtime_root / "logs"
    stdout_path = logs_dir / "backend.stdout.log"
    stderr_path = logs_dir / "backend.stderr.log"
    stdout_handle = stdout_path.open("ab")
    stderr_handle = stderr_path.open("ab")

    creation_flags = 0
    if os.name == "nt":
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

    try:
        return subprocess.Popen(
            command,
            cwd=workdir,
            env=env,
            stdout=stdout_handle,
            stderr=stderr_handle,
            stdin=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
    finally:
        stdout_handle.close()
        stderr_handle.close()


def _port_conflict_message(port: int) -> str:
    return (
        f"Port {port} is already in use by another application, so Melevet cannot start.\n\n"
        "Close the other application using this port, then try again."
    )


def _startup_failure_message(base_url: str, stderr_path: Path) -> str:
    message = [
        f"Melevet backend did not become healthy at {base_url}/health.",
        "",
        f"See the startup log for details: {stderr_path}",
    ]
    stderr_tail = _tail_text(stderr_path)
    if stderr_tail:
        message.extend(["", "Recent backend error output:", stderr_tail])
    return "\n".join(message)


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch or attach to the local Melevet Windows app.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("MELEVET_PORT", "8000")))
    parser.add_argument("--runtime-root", type=Path, default=_default_runtime_root())
    parser.add_argument("--skip-browser", action="store_true")
    args = parser.parse_args()

    root = _workspace_root()
    base_url = f"http://127.0.0.1:{args.port}"

    try:
        if _can_connect(args.port):
            if _wait_for_health(base_url, timeout_seconds=2.0):
                if not args.skip_browser:
                    webbrowser.open(base_url)
                return 0
            raise RuntimeError(_port_conflict_message(args.port))

        _start_backend(root, args.runtime_root, args.port)
        stderr_path = _runtime_stderr_path(args.runtime_root)
        if not _wait_for_health(base_url):
            raise RuntimeError(_startup_failure_message(base_url, stderr_path))
    except (FileNotFoundError, RuntimeError, OSError) as exc:
        _emit_critical_error(str(exc))
        return 1

    if not args.skip_browser:
        webbrowser.open(base_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
