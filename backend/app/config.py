import os
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _project_root_path() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_project_version() -> str:
    version_path = _project_root_path() / "VERSION"
    version = version_path.read_text(encoding="utf-8").strip()
    if not version:
        raise RuntimeError("VERSION file is empty.")
    return version


def _default_local_appdata_root(app_name: str) -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / app_name
    return Path.home() / "AppData" / "Local" / app_name


def _sqlite_url_for_path(path: Path) -> str:
    return f"sqlite:///{path.resolve().as_posix()}"


_PERSISTED_SAFE_FIELDS = {
    "archive_retention_days",
    "link_table_warning_threshold",
    "log_level",
    "orphan_upload_retention_days",
    "segment_gap_seconds",
    "recording_period_gap_seconds",
    "usage_reporting_enabled",
}


class Settings(BaseSettings):
    app_mode: str = "server"
    app_env: str = "development"
    app_name: str = "Melevet Monitor Platform"
    api_prefix: str = "/api"
    database_url: str = "sqlite:///./melevet.db"
    cors_origins: str = "http://localhost:5173"
    cors_allow_credentials: bool = False
    channel_map_path: str = "channel_map.json"
    staged_upload_dir: str = ".staged_uploads"
    staged_upload_retention_minutes: int = 30
    upload_spool_dir: str = ".upload_spool"
    max_upload_file_bytes: int = 64 * 1024 * 1024
    max_upload_request_bytes: int = 128 * 1024 * 1024

    auth_bootstrap_username: str | None = None
    auth_bootstrap_password: str | None = None
    session_cookie_name: str = "melevet_session"
    csrf_cookie_name: str = "melevet_csrf"
    session_ttl_hours: int = 12
    session_cookie_secure: bool | None = None
    csrf_header_name: str = "X-CSRF-Token"
    enable_docs: bool | None = None
    sqlite_connect_timeout_seconds: float = 5.0
    sqlite_busy_timeout_ms: int = 5000
    sqlite_lock_retry_attempts: int = 3
    sqlite_lock_retry_delay_ms: int = 250

    # Gap thresholds (seconds)
    recording_period_gap_seconds: int = 24 * 60 * 60
    segment_gap_seconds: int = 10 * 60

    # Parser assumptions
    frame_size: int = 124
    payload_size: int = 122
    invalid_u16_values: str = "65535,21845"  # 0xFFFF, 0x5555

    upload_timeout_seconds: int = 180
    measurement_insert_batch_size: int = 5000
    event_insert_batch_size: int = 1000
    orphan_upload_retention_days: int = 7
    stage_storage_dir: str = ".staged_uploads"
    stage_expiry_seconds: int = 1800
    data_root_dir: str | None = None
    frontend_dist_dir: str | None = Field(default=None, validation_alias="MELEVET_FRONTEND_DIST")
    archive_retention_days: int | None = None
    link_table_warning_threshold: int = 1_000_000
    log_level: str = "INFO"
    update_check_enabled: bool = True
    update_check_repo: str = "alsontanwork4-cmyk/melevet-veterinary-monitor-software"
    update_check_api_base: str = "https://api.github.com"
    update_check_interval_hours: int = 6
    usage_reporting_enabled: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() == "production"

    @property
    def is_local_app(self) -> bool:
        return self.app_mode.strip().lower() == "local"

    @property
    def project_root_path(self) -> Path:
        return _project_root_path()

    @property
    def backend_root_path(self) -> Path:
        return Path(__file__).resolve().parents[1]

    @property
    def app_root_path(self) -> Path:
        return Path(__file__).resolve().parent

    @property
    def data_root_path(self) -> Path:
        if self.data_root_dir:
            return Path(self.data_root_dir).expanduser().resolve()
        if self.is_local_app:
            return _default_local_appdata_root("Melevet")
        return self.backend_root_path

    @property
    def frontend_dist_path(self) -> Path:
        if self.frontend_dist_dir:
            return Path(self.frontend_dist_dir).expanduser().resolve()
        return (self.project_root_path / "frontend" / "dist").resolve()

    @property
    def channel_map_file_path(self) -> Path:
        configured_path = Path(self.channel_map_path).expanduser()
        if configured_path.is_absolute():
            return configured_path.resolve()
        return (self.app_root_path / configured_path).resolve()

    @property
    def resolved_database_url(self) -> str:
        configured_url = self.database_url.strip()
        if self.is_local_app and configured_url == "sqlite:///./melevet.db":
            return _sqlite_url_for_path(self.data_root_path / "melevet.db")
        return configured_url

    @property
    def resolved_stage_storage_dir(self) -> Path:
        configured_path = Path(self.stage_storage_dir).expanduser()
        if configured_path.is_absolute():
            return configured_path.resolve()
        if self.is_local_app and self.stage_storage_dir == ".staged_uploads":
            return (self.data_root_path / "staged_uploads").resolve()
        return (self.backend_root_path / configured_path).resolve()

    @property
    def resolved_upload_spool_dir(self) -> Path:
        configured_path = Path(self.upload_spool_dir).expanduser()
        if configured_path.is_absolute():
            return configured_path.resolve()
        if self.is_local_app and self.upload_spool_dir == ".upload_spool":
            return (self.data_root_path / "upload_spool").resolve()
        return (self.backend_root_path / configured_path).resolve()

    @property
    def log_dir_path(self) -> Path:
        return (self.data_root_path / "logs").resolve()

    @property
    def archive_dir_path(self) -> Path:
        return (self.data_root_path / "archives").resolve()

    @property
    def telemetry_dir_path(self) -> Path:
        return (self.data_root_path / "telemetry").resolve()

    @property
    def runtime_log_path(self) -> Path:
        return self.log_dir_path / "melevet.log"

    @property
    def docs_enabled(self) -> bool:
        if self.is_local_app:
            return False
        if self.enable_docs is not None:
            return self.enable_docs
        return not self.is_production

    @property
    def effective_session_cookie_secure(self) -> bool:
        if self.is_local_app:
            return False
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure
        return self.is_production

    @property
    def invalid_u16_set(self) -> set[int]:
        values: set[int] = set()
        for token in self.invalid_u16_values.split(","):
            token = token.strip()
            if not token:
                continue
            values.add(int(token))
        return values

    def validate_runtime_settings(self) -> None:
        if self.log_level.strip().upper() not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            raise ValueError("LOG_LEVEL must be one of DEBUG, INFO, WARNING, or ERROR.")
        if any(origin == "*" for origin in self.cors_origin_list):
            raise ValueError("CORS_ORIGINS must not contain '*'; configure explicit origins instead.")
        if self.cors_allow_credentials and not self.cors_origin_list:
            raise ValueError("Credentialed CORS requires at least one explicit origin.")
        if not self.is_local_app:
            for origin in self.cors_origin_list:
                parsed = urlparse(origin)
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    raise ValueError(f"Invalid CORS origin {origin!r}; use absolute http(s) origins.")
        if self.is_production and not self.is_local_app:
            if not self.cors_origin_list:
                raise ValueError("Production requires explicit CORS_ORIGINS.")
            for origin in self.cors_origin_list:
                parsed = urlparse(origin)
                if parsed.scheme != "https":
                    raise ValueError("Production CORS_ORIGINS must use HTTPS origins.")
        if self.max_upload_file_bytes <= 0 or self.max_upload_request_bytes <= 0:
            raise ValueError("Upload size limits must be positive.")
        if self.max_upload_file_bytes > self.max_upload_request_bytes:
            raise ValueError("MAX_UPLOAD_FILE_BYTES cannot exceed MAX_UPLOAD_REQUEST_BYTES.")
        if self.session_ttl_hours <= 0:
            raise ValueError("SESSION_TTL_HOURS must be positive.")
        if self.sqlite_connect_timeout_seconds <= 0:
            raise ValueError("SQLITE_CONNECT_TIMEOUT_SECONDS must be positive.")
        if self.sqlite_busy_timeout_ms <= 0:
            raise ValueError("SQLITE_BUSY_TIMEOUT_MS must be positive.")
        if self.sqlite_lock_retry_attempts <= 0:
            raise ValueError("SQLITE_LOCK_RETRY_ATTEMPTS must be positive.")
        if self.sqlite_lock_retry_delay_ms <= 0:
            raise ValueError("SQLITE_LOCK_RETRY_DELAY_MS must be positive.")
        if self.archive_retention_days is not None and self.archive_retention_days <= 0:
            raise ValueError("ARCHIVE_RETENTION_DAYS must be positive when configured.")
        if self.link_table_warning_threshold <= 0:
            raise ValueError("LINK_TABLE_WARNING_THRESHOLD must be positive.")
        if self.orphan_upload_retention_days <= 0:
            raise ValueError("ORPHAN_UPLOAD_RETENTION_DAYS must be positive.")
        if self.segment_gap_seconds < 60:
            raise ValueError("SEGMENT_GAP_SECONDS must be at least 60.")
        if self.recording_period_gap_seconds < 60:
            raise ValueError("RECORDING_PERIOD_GAP_SECONDS must be at least 60.")
        if self.update_check_interval_hours <= 0:
            raise ValueError("UPDATE_CHECK_INTERVAL_HOURS must be positive.")


APP_VERSION = _read_project_version()


def _load_base_settings() -> Settings:
    base_settings = Settings()
    persisted_path = base_settings.data_root_path / "settings.json"
    if not persisted_path.exists():
        return base_settings

    import json

    with persisted_path.open("r", encoding="utf-8") as handle:
        persisted_data = json.load(handle)
    if not isinstance(persisted_data, dict):
        raise RuntimeError(f"Persisted settings file must contain a JSON object: {persisted_path}")

    persisted_overrides = {
        key: value
        for key, value in persisted_data.items()
        if key in _PERSISTED_SAFE_FIELDS
    }
    return Settings(**{**base_settings.model_dump(mode="python"), **persisted_overrides})


settings = _load_base_settings()
