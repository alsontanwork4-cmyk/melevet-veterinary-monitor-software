from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Melevet Monitor Platform"
    api_prefix: str = "/api"
    database_url: str = "sqlite:///./melevet.db"
    cors_origins: str = "*"
    channel_map_path: str = "channel_map.json"

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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def invalid_u16_set(self) -> set[int]:
        values: set[int] = set()
        for token in self.invalid_u16_values.split(","):
            token = token.strip()
            if not token:
                continue
            values.add(int(token))
        return values


settings = Settings()
