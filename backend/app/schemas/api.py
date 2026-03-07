from __future__ import annotations

from datetime import UTC, date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from ..models import AlarmCategory, SourceType, UploadStatus


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
    alarm_frames: int
    combined_hash: str
    detected_local_dates: list[str]
    superseded_at: datetime | None = None
    measurements_new: int = 0
    measurements_reused: int = 0
    nibp_new: int = 0
    nibp_reused: int = 0
    alarms_new: int = 0
    alarms_reused: int = 0


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


class DiscoveryResponse(ApiModel):
    upload_id: int
    trend_frames: int
    nibp_frames: int
    alarm_frames: int
    periods: int
    segments: int
    channels: list[ChannelOut]
    detected_local_dates: list[str]


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


class AlarmOut(ApiModel):
    id: int
    upload_id: int
    segment_id: int
    timestamp: datetime
    flag_hi: int
    flag_lo: int
    alarm_category: AlarmCategory
    message: str


class NibpEventOut(ApiModel):
    id: int
    upload_id: int
    segment_id: int
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
    alarm_frames: int


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
    alarm_frames: int
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


class UploadDeleteResponse(ApiModel):
    deleted: bool
    upload_id: int


class PatientDeleteResponse(ApiModel):
    deleted: bool
    patient_id: int

