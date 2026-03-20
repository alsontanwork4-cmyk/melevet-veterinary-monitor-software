from __future__ import annotations

from datetime import UTC, date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from ..models import SourceType, UploadStatus


def _serialize_datetime_utc(value: datetime) -> str:
    normalized = value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.isoformat().replace("+00:00", "Z")


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_serializer("*", when_used="json", check_fields=False)
    def _serialize_fields(self, value):
        return _normalize_datetime_values(value)


def _normalize_datetime_values(value):
    if isinstance(value, datetime):
        return _serialize_datetime_utc(value)
    if isinstance(value, list):
        return [_normalize_datetime_values(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_normalize_datetime_values(item) for item in value)
    if isinstance(value, dict):
        return {key: _normalize_datetime_values(item) for key, item in value.items()}
    return value


class PatientBase(ApiModel):
    patient_id_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    species: str = Field(min_length=1, max_length=64)
    age: str | None = None
    breed: str | None = None
    weight_kg: float | None = None
    owner_name: str | None = None
    notes: str | None = None


class AuthLoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class AuthUserOut(ApiModel):
    id: int
    username: str


class AuthSessionOut(ApiModel):
    user: AuthUserOut
    csrf_token: str
    expires_at: datetime


class CsrfTokenOut(ApiModel):
    csrf_token: str


class LogoutResponse(ApiModel):
    logged_out: bool


class VitalThresholdRange(ApiModel):
    low: float | None = None
    high: float | None = None


class SpeciesVitalThresholds(ApiModel):
    spo2: VitalThresholdRange = Field(default_factory=VitalThresholdRange)
    heart_rate: VitalThresholdRange = Field(default_factory=VitalThresholdRange)
    nibp_systolic: VitalThresholdRange = Field(default_factory=VitalThresholdRange)
    nibp_map: VitalThresholdRange = Field(default_factory=VitalThresholdRange)
    nibp_diastolic: VitalThresholdRange = Field(default_factory=VitalThresholdRange)


class AppSettingsOut(ApiModel):
    archive_retention_days: int | None = None
    link_table_warning_threshold: int
    log_level: str
    orphan_upload_retention_days: int
    segment_gap_seconds: int
    recording_period_gap_seconds: int
    usage_reporting_enabled: bool = False
    vital_thresholds: dict[str, SpeciesVitalThresholds] = Field(default_factory=dict)


class AppSettingsUpdate(ApiModel):
    archive_retention_days: int | None = Field(default=None, ge=1)
    link_table_warning_threshold: int | None = Field(default=None, ge=1)
    log_level: str | None = Field(default=None, max_length=16)
    orphan_upload_retention_days: int | None = Field(default=None, ge=1)
    segment_gap_seconds: int | None = Field(default=None, ge=60)
    recording_period_gap_seconds: int | None = Field(default=None, ge=60)
    usage_reporting_enabled: bool | None = None
    vital_thresholds: dict[str, SpeciesVitalThresholds] | None = None

class UpdateStatusOut(ApiModel):
    current_version: str
    latest_version: str | None = None
    download_url: str | None = None
    release_url: str | None = None
    checked_at: datetime | None = None
    is_update_available: bool
    error: str | None = None


class AuditLogOut(ApiModel):
    id: int
    action: str
    entity_type: str
    entity_id: str
    actor: str
    details_json: dict[str, object] = Field(default_factory=dict)
    timestamp: datetime


class PaginatedAuditLog(ApiModel):
    items: list[AuditLogOut]
    total: int


class BulkEncounterExportRequest(BaseModel):
    encounter_ids: list[int] = Field(min_length=1, max_length=200)
    include_nibp: bool = True


class PatientCreate(PatientBase):
    pass


class PatientUpdate(ApiModel):
    patient_id_code: str | None = None
    name: str | None = None
    species: str | None = None
    age: str | None = None
    breed: str | None = None
    weight_kg: float | None = None
    owner_name: str | None = None
    notes: str | None = None
    preferred_encounter_id: int | None = None


class PatientOut(PatientBase):
    id: int
    preferred_encounter_id: int | None = None
    created_at: datetime
    updated_at: datetime


class UploadOut(ApiModel):
    id: int
    patient_id: int | None = None
    origin_patient_id: int | None = None
    exact_duplicate: bool = False
    upload_time: datetime
    status: UploadStatus
    phase: str
    progress_current: int
    progress_total: int
    started_at: datetime | None = None
    heartbeat_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    trend_frames: int
    nibp_frames: int
    combined_hash: str
    detected_local_dates: list[str]
    superseded_at: datetime | None = None
    archived_at: datetime | None = None
    archive_id: str | None = None
    measurements_new: int = 0
    measurements_reused: int = 0
    nibp_new: int = 0
    nibp_reused: int = 0


class RecordingPeriodOut(ApiModel):
    id: int
    upload_id: int
    period_index: int
    start_time: datetime
    end_time: datetime
    frame_count: int
    label: str


class SegmentOut(ApiModel):
    id: int
    period_id: int
    upload_id: int
    segment_index: int
    start_time: datetime
    end_time: datetime
    frame_count: int
    duration_seconds: int


class ChannelOut(ApiModel):
    id: int
    upload_id: int
    source_type: SourceType
    channel_index: int
    name: str
    unit: str | None
    valid_count: int


class DiscoveredChannelOut(ApiModel):
    source_type: SourceType
    channel_index: int
    name: str
    unit: str | None
    valid_count: int


class DiscoveryResponse(ApiModel):
    upload_id: int
    trend_frames: int
    nibp_frames: int
    periods: int
    segments: int
    channels: list[ChannelOut]
    detected_local_dates: list[str]
    archived_at: datetime | None = None
    archive_id: str | None = None


class MeasurementPoint(ApiModel):
    timestamp: datetime
    channel_id: int
    channel_name: str
    value: float | None


class MeasurementsResponse(ApiModel):
    segment_id: int
    points: list[MeasurementPoint]


class UploadMeasurementsResponse(ApiModel):
    upload_id: int
    points: list[MeasurementPoint]


class EncounterMeasurementsResponse(ApiModel):
    encounter_id: int
    points: list[MeasurementPoint]


class NibpEventOut(ApiModel):
    id: int
    upload_id: int | None
    segment_id: int | None
    timestamp: datetime
    channel_values: dict[str, int | None]
    has_measurement: bool


class UploadResponse(ApiModel):
    upload: UploadOut
    patient_id: int
    period_count: int
    segment_count: int
    channel_count: int
    reused_existing: bool = False
    exact_duplicate: bool = False


class PatientUploadHistoryItem(ApiModel):
    id: int
    upload_time: datetime
    latest_recorded_at: datetime | None = None
    status: UploadStatus
    trend_frames: int
    nibp_frames: int
    measurements_new: int = 0
    measurements_reused: int = 0
    nibp_new: int = 0
    nibp_reused: int = 0
    archived_at: datetime | None = None
    archive_id: str | None = None


class EncounterBase(ApiModel):
    encounter_date_local: date
    timezone: str = Field(min_length=1, max_length=64)
    label: str | None = Field(default=None, max_length=128)
    notes: str | None = None


class EncounterCreate(EncounterBase):
    patient_id: int


class EncounterUpdate(ApiModel):
    encounter_date_local: date | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    label: str | None = Field(default=None, max_length=128)
    notes: str | None = None


class EncounterOut(EncounterBase):
    id: int
    patient_id: int
    upload_id: int
    trend_frames: int
    nibp_frames: int
    archived_at: datetime | None = None
    archive_id: str | None = None
    day_start_utc: datetime
    day_end_utc: datetime
    created_at: datetime
    updated_at: datetime


class PatientEncounterHistoryItem(EncounterOut):
    pass


class PatientAvailableReportDate(ApiModel):
    encounter_date_local: date
    upload_id: int
    encounter_id: int | None = None
    is_saved: bool


class EncounterDeleteResponse(ApiModel):
    deleted: bool
    encounter_id: int


class PatientWithUploadCount(ApiModel):
    id: int
    patient_id_code: str
    name: str
    species: str
    age: str | None = None
    owner_name: str | None = None
    notes: str | None = None
    preferred_encounter_id: int | None = None
    created_at: datetime
    upload_count: int
    last_upload_time: datetime | None
    latest_report_date: date | None
    report_date: date | None


class PaginatedPatientList(ApiModel):
    items: list[PatientWithUploadCount]
    total: int


class PaginatedPatientUploadHistory(ApiModel):
    items: list[PatientUploadHistoryItem]
    total: int
    limit: int
    offset: int


class PaginatedPatientEncounterHistory(ApiModel):
    items: list[PatientEncounterHistoryItem]
    total: int
    limit: int
    offset: int


class PaginatedNibpEventList(ApiModel):
    items: list[NibpEventOut]
    total: int
    limit: int
    offset: int


class DatabaseDiagnostics(ApiModel):
    database_kind: str
    sqlite_file_size_bytes: int | None = None
    measurement_count: int
    upload_measurement_link_count: int
    upload_nibp_event_link_count: int
    link_table_warning_threshold: int
    upload_measurement_links_over_threshold: bool
    upload_nibp_event_links_over_threshold: bool


class ArchiveOut(ApiModel):
    id: str
    filename: str
    size_bytes: int
    created_at: datetime
    upload_id: int
    patient_id: int | None = None
    encounter_ids: list[int] = Field(default_factory=list)
    measurement_count: int = 0
    nibp_event_count: int = 0


class ArchiveRunResponse(ApiModel):
    archived_upload_count: int
    archives: list[ArchiveOut] = Field(default_factory=list)


class DatabaseStatsOut(ApiModel):
    database_kind: str
    sqlite_file_size_bytes: int | None = None
    live_measurement_count: int
    live_nibp_event_count: int
    archived_upload_count: int
    archive_file_count: int
    archive_total_size_bytes: int
    oldest_archive_at: datetime | None = None
    newest_archive_at: datetime | None = None


class TelemetryEventIn(ApiModel):
    event_type: str = Field(min_length=1, max_length=64)
    action_name: str | None = Field(default=None, max_length=128)
    route: str | None = Field(default=None, max_length=256)
    status: str | None = Field(default=None, max_length=64)
    duration_ms: int | None = Field(default=None, ge=0)
    count: int | None = Field(default=None, ge=0)
    app_version: str | None = Field(default=None, max_length=64)
    browser: str | None = Field(default=None, max_length=256)
    platform: str | None = Field(default=None, max_length=256)
    error_name: str | None = Field(default=None, max_length=128)
    error_message: str | None = Field(default=None, max_length=2000)
    stack: str | None = None
    component_stack: str | None = None
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class TelemetryStatusOut(ApiModel):
    usage_reporting_enabled: bool
    queued_event_count: int
    queued_size_bytes: int
    crash_event_count: int
    crash_size_bytes: int


class UploadDeleteResponse(ApiModel):
    deleted: bool
    upload_id: int


class PatientDeleteResponse(ApiModel):
    deleted: bool
    patient_id: int


class StagedUploadPatient(ApiModel):
    patient_id: int | None = None
    patient_id_code: str | None = None
    patient_name: str | None = None
    patient_species: str | None = None


class StagedUploadOut(ApiModel):
    stage_id: str
    status: UploadStatus
    phase: str
    progress_current: int
    progress_total: int
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    error_message: str | None = None
    timezone: str
    trend_frames: int = 0
    nibp_frames: int = 0
    periods: int = 0
    segments: int = 0
    channels: list[DiscoveredChannelOut] = Field(default_factory=list)
    detected_local_dates: list[str] = Field(default_factory=list)
    patient_id: int | None = None
    patient_id_code: str | None = None
    patient_name: str | None = None
    patient_species: str | None = None


class StagedEncounterCreate(EncounterBase):
    pass


class StagedUploadDeleteResponse(ApiModel):
    deleted: bool
    stage_id: str

