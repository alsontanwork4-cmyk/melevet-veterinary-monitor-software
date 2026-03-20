from __future__ import annotations

import enum
from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from ..utils import normalize_dedup_timestamp


class UploadStatus(str, enum.Enum):
    processing = "processing"
    completed = "completed"
    error = "error"


class SourceType(str, enum.Enum):
    trend = "trend"
    nibp = "nibp"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    sessions: Mapped[list["UserSession"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserSession(Base):
    __tablename__ = "user_sessions"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_user_sessions_token_hash"),
        Index("ix_user_sessions_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    csrf_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="sessions")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(64), index=True)
    entity_id: Mapped[str] = mapped_column(String(128), index=True)
    actor: Mapped[str] = mapped_column(String(128))
    details_json: Mapped[dict] = mapped_column(JSON, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, server_default=func.now())


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    species: Mapped[str] = mapped_column(String(64), index=True)
    age: Mapped[str | None] = mapped_column(String(64), nullable=True)
    breed: Mapped[str | None] = mapped_column(String(128), nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    owner_name: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    preferred_encounter_id: Mapped[int | None] = mapped_column(
        ForeignKey("encounters.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    uploads: Mapped[list[Upload]] = relationship(back_populates="patient", cascade="all, delete-orphan")
    encounters: Mapped[list[Encounter]] = relationship(
        back_populates="patient",
        cascade="all, delete-orphan",
        foreign_keys="Encounter.patient_id",
    )
    preferred_encounter: Mapped[Encounter | None] = relationship(foreign_keys=[preferred_encounter_id])


class Upload(Base):
    __tablename__ = "uploads"
    __table_args__ = (
        UniqueConstraint("combined_hash", name="uq_upload_combined_hash"),
        Index("ix_uploads_combined_hash_status", "combined_hash", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[int | None] = mapped_column(
        ForeignKey("patients.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    upload_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[UploadStatus] = mapped_column(Enum(UploadStatus), default=UploadStatus.processing)
    phase: Mapped[str] = mapped_column(String(64), default="reading")
    progress_current: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    trend_frames: Mapped[int] = mapped_column(Integer, default=0)
    nibp_frames: Mapped[int] = mapped_column(Integer, default=0)

    trend_sha256: Mapped[str] = mapped_column(String(64))
    trend_index_sha256: Mapped[str] = mapped_column(String(64))
    nibp_sha256: Mapped[str] = mapped_column(String(64))
    nibp_index_sha256: Mapped[str] = mapped_column(String(64))
    combined_hash: Mapped[str] = mapped_column(String(64), default="")
    detected_local_dates: Mapped[list[str]] = mapped_column(JSON, default=list)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archive_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    measurements_new: Mapped[int] = mapped_column(Integer, default=0)
    measurements_reused: Mapped[int] = mapped_column(Integer, default=0)
    nibp_new: Mapped[int] = mapped_column(Integer, default=0)
    nibp_reused: Mapped[int] = mapped_column(Integer, default=0)

    patient: Mapped[Patient | None] = relationship(back_populates="uploads")
    periods: Mapped[list[RecordingPeriod]] = relationship(
        back_populates="upload", cascade="all, delete-orphan"
    )
    segments: Mapped[list[Segment]] = relationship(back_populates="upload", cascade="all, delete-orphan")
    channels: Mapped[list[Channel]] = relationship(back_populates="upload", cascade="all, delete-orphan")
    measurements: Mapped[list[Measurement]] = relationship(back_populates="upload")
    nibp_events: Mapped[list[NibpEvent]] = relationship(back_populates="upload")
    measurement_links: Mapped[list[UploadMeasurementLink]] = relationship(
        back_populates="upload", cascade="all, delete-orphan"
    )
    nibp_event_links: Mapped[list[UploadNibpEventLink]] = relationship(
        back_populates="upload", cascade="all, delete-orphan"
    )
    encounters: Mapped[list[Encounter]] = relationship(back_populates="upload")

    @property
    def origin_patient_id(self) -> int | None:
        return self.patient_id

    @property
    def latest_recorded_at(self) -> datetime | None:
        if not self.periods:
            return None
        return max(period.end_time for period in self.periods)

    @property
    def exact_duplicate(self) -> bool:
        return False


class Encounter(Base):
    __tablename__ = "encounters"
    __table_args__ = (
        UniqueConstraint("patient_id", "encounter_date_local", name="uq_patient_encounter_date"),
        Index("ix_encounters_upload_patient", "upload_id", "patient_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"), index=True)
    encounter_date_local: Mapped[date] = mapped_column(Date, index=True)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    patient: Mapped[Patient] = relationship(back_populates="encounters", foreign_keys=[patient_id])
    upload: Mapped[Upload] = relationship(back_populates="encounters")

    @property
    def trend_frames(self) -> int:
        return self.upload.trend_frames if self.upload is not None else 0

    @property
    def nibp_frames(self) -> int:
        return self.upload.nibp_frames if self.upload is not None else 0

    @property
    def archived_at(self) -> datetime | None:
        return self.upload.archived_at if self.upload is not None else None

    @property
    def archive_id(self) -> str | None:
        return self.upload.archive_id if self.upload is not None else None

    @property
    def day_start_utc(self) -> datetime:
        from ..services.encounter_service import encounter_day_window

        start_time, _ = encounter_day_window(self.encounter_date_local, self.timezone)
        return start_time.replace(tzinfo=UTC)

    @property
    def day_end_utc(self) -> datetime:
        from ..services.encounter_service import encounter_day_window

        _, end_time = encounter_day_window(self.encounter_date_local, self.timezone)
        return end_time.replace(tzinfo=UTC)


class RecordingPeriod(Base):
    __tablename__ = "recording_periods"
    __table_args__ = (UniqueConstraint("upload_id", "period_index", name="uq_upload_period"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"), index=True)
    period_index: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    frame_count: Mapped[int] = mapped_column(Integer, default=0)
    label: Mapped[str] = mapped_column(String(128))

    upload: Mapped[Upload] = relationship(back_populates="periods")
    segments: Mapped[list[Segment]] = relationship(back_populates="period", cascade="all, delete-orphan")


class Segment(Base):
    __tablename__ = "segments"
    __table_args__ = (
        UniqueConstraint("period_id", "segment_index", name="uq_period_segment"),
        Index("ix_segments_upload_start", "upload_id", "start_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("recording_periods.id", ondelete="CASCADE"), index=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"), index=True)
    segment_index: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    frame_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)

    period: Mapped[RecordingPeriod] = relationship(back_populates="segments")
    upload: Mapped[Upload] = relationship(back_populates="segments")
    measurements: Mapped[list[Measurement]] = relationship(back_populates="segment")
    nibp_events: Mapped[list[NibpEvent]] = relationship(back_populates="segment")
    measurement_links: Mapped[list[UploadMeasurementLink]] = relationship(
        back_populates="segment", cascade="all, delete-orphan"
    )
    nibp_event_links: Mapped[list[UploadNibpEventLink]] = relationship(
        back_populates="segment", cascade="all, delete-orphan"
    )


class Channel(Base):
    __tablename__ = "channels"
    __table_args__ = (
        UniqueConstraint("upload_id", "source_type", "channel_index", name="uq_upload_source_channel"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"), index=True)
    source_type: Mapped[SourceType] = mapped_column(Enum(SourceType), index=True)
    channel_index: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(128))
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    valid_count: Mapped[int] = mapped_column(Integer, default=0)

    upload: Mapped[Upload] = relationship(back_populates="channels")
    measurements: Mapped[list[Measurement]] = relationship(back_populates="channel")
    measurement_links: Mapped[list[UploadMeasurementLink]] = relationship(
        back_populates="channel", cascade="all, delete-orphan"
    )


class Measurement(Base):
    __tablename__ = "measurements"
    __table_args__ = (
        UniqueConstraint("dedup_key", name="uq_measurements_dedup_key"),
        Index("ix_measurements_ts", "timestamp"),
        Index("ix_measurements_dedup_key", "dedup_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    upload_id: Mapped[int | None] = mapped_column(
        ForeignKey("uploads.id", ondelete="SET NULL"), index=True, nullable=True
    )
    segment_id: Mapped[int | None] = mapped_column(
        ForeignKey("segments.id", ondelete="SET NULL"), index=True, nullable=True
    )
    channel_id: Mapped[int | None] = mapped_column(
        ForeignKey("channels.id", ondelete="SET NULL"), index=True, nullable=True
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    dedup_key: Mapped[str] = mapped_column(String(255), nullable=False)

    upload: Mapped[Upload | None] = relationship(back_populates="measurements")
    segment: Mapped[Segment | None] = relationship(back_populates="measurements")
    channel: Mapped[Channel | None] = relationship(back_populates="measurements")
    upload_links: Mapped[list[UploadMeasurementLink]] = relationship(
        back_populates="measurement", cascade="all, delete-orphan"
    )


class UploadMeasurementLink(Base):
    __tablename__ = "upload_measurement_links"
    __table_args__ = (
        UniqueConstraint(
            "upload_id",
            "segment_id",
            "channel_id",
            "measurement_id",
            name="uq_upload_segment_channel_measurement",
        ),
        Index("ix_upload_measurement_upload_channel_ts", "upload_id", "channel_id", "timestamp"),
        Index("ix_upload_measurement_segment_ts", "segment_id", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"), index=True)
    segment_id: Mapped[int] = mapped_column(ForeignKey("segments.id", ondelete="CASCADE"), index=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    measurement_id: Mapped[int] = mapped_column(ForeignKey("measurements.id", ondelete="CASCADE"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    upload: Mapped[Upload] = relationship(back_populates="measurement_links")
    segment: Mapped[Segment] = relationship(back_populates="measurement_links")
    channel: Mapped[Channel] = relationship(back_populates="measurement_links")
    measurement: Mapped[Measurement] = relationship(back_populates="upload_links")


class NibpEvent(Base):
    __tablename__ = "nibp_events"
    __table_args__ = (
        UniqueConstraint("dedup_key", name="uq_nibp_events_dedup_key"),
        Index("ix_nibp_events_ts", "timestamp"),
        Index("ix_nibp_events_dedup_key", "dedup_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    upload_id: Mapped[int | None] = mapped_column(
        ForeignKey("uploads.id", ondelete="SET NULL"), index=True, nullable=True
    )
    segment_id: Mapped[int | None] = mapped_column(
        ForeignKey("segments.id", ondelete="SET NULL"), index=True, nullable=True
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    channel_values: Mapped[dict] = mapped_column(JSON)
    has_measurement: Mapped[bool] = mapped_column(Boolean, default=False)
    dedup_key: Mapped[str] = mapped_column(String(255), nullable=False)

    upload: Mapped[Upload | None] = relationship(back_populates="nibp_events")
    segment: Mapped[Segment | None] = relationship(back_populates="nibp_events")
    upload_links: Mapped[list[UploadNibpEventLink]] = relationship(
        back_populates="nibp_event", cascade="all, delete-orphan"
    )


class UploadNibpEventLink(Base):
    __tablename__ = "upload_nibp_event_links"
    __table_args__ = (
        UniqueConstraint("upload_id", "segment_id", "nibp_event_id", name="uq_upload_segment_nibp_event"),
        Index("ix_upload_nibp_upload_ts", "upload_id", "timestamp"),
        Index("ix_upload_nibp_segment_ts", "segment_id", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"), index=True)
    segment_id: Mapped[int] = mapped_column(ForeignKey("segments.id", ondelete="CASCADE"), index=True)
    nibp_event_id: Mapped[int] = mapped_column(ForeignKey("nibp_events.id", ondelete="CASCADE"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    upload: Mapped[Upload] = relationship(back_populates="nibp_event_links")
    segment: Mapped[Segment] = relationship(back_populates="nibp_event_links")
    nibp_event: Mapped[NibpEvent] = relationship(back_populates="upload_links")

@event.listens_for(Measurement, "before_insert")
def _populate_measurement_dedup_key(_mapper, connection, target: Measurement) -> None:
    if target.dedup_key:
        return
    source_type: str | None = None
    channel_index: int | None = None
    if target.channel is not None:
        source_type = target.channel.source_type.value
        channel_index = target.channel.channel_index
    elif target.channel_id is not None:
        row = connection.exec_driver_sql(
            "SELECT source_type, channel_index FROM channels WHERE id = ?",
            (target.channel_id,),
        ).fetchone()
        if row is not None:
            source_type = str(row[0])
            channel_index = int(row[1])
    if source_type is None or channel_index is None:
        raise ValueError("Measurement dedup_key requires a resolved channel")
    target.dedup_key = f"{normalize_dedup_timestamp(target.timestamp)}|{source_type}|{channel_index}"


@event.listens_for(NibpEvent, "before_insert")
def _populate_nibp_dedup_key(_mapper, _connection, target: NibpEvent) -> None:
    if target.dedup_key:
        return
    target.dedup_key = normalize_dedup_timestamp(target.timestamp)
