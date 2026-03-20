export type UploadStatus = "processing" | "completed" | "error";
export type SourceType = "trend" | "nibp";

export interface AuthUser {
  id: number;
  username: string;
}

export interface AuthSession {
  user: AuthUser;
  csrf_token: string;
  expires_at: string;
}

export interface LoginPayload {
  username: string;
  password: string;
}

export interface CsrfTokenResponse {
  csrf_token: string;
}

export interface VitalThresholdRange {
  low: number | null;
  high: number | null;
}

export interface SpeciesVitalThresholds {
  spo2: VitalThresholdRange;
  heart_rate: VitalThresholdRange;
  nibp_systolic: VitalThresholdRange;
  nibp_map: VitalThresholdRange;
  nibp_diastolic: VitalThresholdRange;
}

export interface AppSettings {
  archive_retention_days: number | null;
  link_table_warning_threshold: number;
  log_level: "DEBUG" | "INFO" | "WARNING" | "ERROR";
  orphan_upload_retention_days: number;
  segment_gap_seconds: number;
  recording_period_gap_seconds: number;
  usage_reporting_enabled: boolean;
  vital_thresholds: Record<string, SpeciesVitalThresholds>;
}

export interface AppSettingsUpdatePayload {
  archive_retention_days?: number | null;
  link_table_warning_threshold?: number;
  log_level?: AppSettings["log_level"];
  orphan_upload_retention_days?: number;
  segment_gap_seconds?: number;
  recording_period_gap_seconds?: number;
  usage_reporting_enabled?: boolean;
  vital_thresholds?: Record<string, SpeciesVitalThresholds>;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface DatabaseDiagnostics {
  database_kind: string;
  sqlite_file_size_bytes: number | null;
  measurement_count: number;
  upload_measurement_link_count: number;
  upload_nibp_event_link_count: number;
  link_table_warning_threshold: number;
  upload_measurement_links_over_threshold: boolean;
  upload_nibp_event_links_over_threshold: boolean;
}

export interface DatabaseStats {
  database_kind: string;
  sqlite_file_size_bytes: number | null;
  live_measurement_count: number;
  live_nibp_event_count: number;
  archived_upload_count: number;
  archive_file_count: number;
  archive_total_size_bytes: number;
  oldest_archive_at: string | null;
  newest_archive_at: string | null;
}

export interface UpdateStatus {
  current_version: string;
  latest_version: string | null;
  download_url: string | null;
  release_url: string | null;
  checked_at: string | null;
  is_update_available: boolean;
  error: string | null;
}

export interface TelemetryStatus {
  usage_reporting_enabled: boolean;
  queued_event_count: number;
  queued_size_bytes: number;
  crash_event_count: number;
  crash_size_bytes: number;
}

export interface TelemetryEventPayload {
  event_type: string;
  action_name?: string | null;
  route?: string | null;
  status?: string | null;
  duration_ms?: number | null;
  count?: number | null;
  app_version?: string | null;
  browser?: string | null;
  platform?: string | null;
  error_name?: string | null;
  error_message?: string | null;
  stack?: string | null;
  component_stack?: string | null;
  metadata?: Record<string, string | number | boolean | null>;
}

export interface ArchiveItem {
  id: string;
  filename: string;
  size_bytes: number;
  created_at: string;
  upload_id: number;
  patient_id: number | null;
  encounter_ids: number[];
  measurement_count: number;
  nibp_event_count: number;
}

export interface ArchiveRunResult {
  archived_upload_count: number;
  archives: ArchiveItem[];
}

export interface AuditLogEntry {
  id: number;
  action: string;
  entity_type: string;
  entity_id: string;
  actor: string;
  details_json: Record<string, unknown>;
  timestamp: string;
}

export interface PaginatedAuditLog {
  items: AuditLogEntry[];
  total: number;
}

export interface BulkEncounterExportPayload {
  encounter_ids: number[];
  include_nibp?: boolean;
}

export interface Patient {
  id: number;
  patient_id_code: string;
  name: string;
  species: string;
  age?: string | null;
  breed?: string | null;
  weight_kg?: number | null;
  owner_name?: string | null;
  notes?: string | null;
  preferred_encounter_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface PatientCreatePayload {
  patient_id_code: string;
  name: string;
  species: string;
  age?: string | null;
  breed?: string | null;
  weight_kg?: number | null;
  owner_name?: string | null;
  notes?: string | null;
}

export interface PatientUpdatePayload {
  patient_id_code?: string;
  name?: string;
  species?: string;
  age?: string | null;
  breed?: string | null;
  weight_kg?: number | null;
  owner_name?: string | null;
  notes?: string | null;
  preferred_encounter_id?: number | null;
}

export interface PatientDeleteResponse {
  deleted: boolean;
  patient_id: number;
}

export interface PatientWithUploadCount {
  id: number;
  patient_id_code: string;
  name: string;
  species: string;
  age?: string | null;
  owner_name?: string | null;
  notes?: string | null;
  preferred_encounter_id: number | null;
  created_at: string;
  upload_count: number;
  last_upload_time: string | null;
  latest_report_date: string | null;
  report_date: string | null;
}

export interface PaginatedPatientList {
  items: PatientWithUploadCount[];
  total: number;
}

export interface Upload {
  id: number;
  patient_id: number | null;
  origin_patient_id: number | null;
  exact_duplicate: boolean;
  upload_time: string;
  status: UploadStatus;
  phase: string;
  progress_current: number;
  progress_total: number;
  started_at: string | null;
  heartbeat_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  trend_frames: number;
  nibp_frames: number;
  combined_hash: string;
  detected_local_dates: string[];
  superseded_at: string | null;
  archived_at: string | null;
  archive_id: string | null;
  measurements_new: number;
  measurements_reused: number;
  nibp_new: number;
  nibp_reused: number;
}

export interface UploadResponse {
  upload: Upload;
  patient_id: number;
  period_count: number;
  segment_count: number;
  channel_count: number;
  reused_existing: boolean;
  exact_duplicate: boolean;
}

export interface UploadDeleteResponse {
  deleted: boolean;
  upload_id: number;
}

export interface StagedUploadPatient {
  patient_id: number | null;
  patient_id_code: string | null;
  patient_name: string | null;
  patient_species: string | null;
}

export interface DiscoveredChannel {
  source_type: SourceType;
  channel_index: number;
  name: string;
  unit: string | null;
  valid_count: number;
}

export interface StagedUpload {
  stage_id: string;
  status: UploadStatus;
  phase: string;
  progress_current: number;
  progress_total: number;
  created_at: string;
  updated_at: string;
  expires_at: string;
  error_message: string | null;
  timezone: string;
  trend_frames: number;
  nibp_frames: number;
  periods: number;
  segments: number;
  channels: DiscoveredChannel[];
  detected_local_dates: string[];
  patient_id: number | null;
  patient_id_code: string | null;
  patient_name: string | null;
  patient_species: string | null;
}

export interface StagedEncounterCreatePayload {
  encounter_date_local: string;
  timezone: string;
  label?: string | null;
  notes?: string | null;
}

export interface StagedUploadDeleteResponse {
  deleted: boolean;
  stage_id: string;
}

export interface RecordingPeriod {
  id: number;
  upload_id: number;
  period_index: number;
  start_time: string;
  end_time: string;
  frame_count: number;
  label: string;
}

export interface Segment {
  id: number;
  period_id: number;
  upload_id: number;
  segment_index: number;
  start_time: string;
  end_time: string;
  frame_count: number;
  duration_seconds: number;
}

export interface Channel {
  id: number;
  upload_id: number;
  source_type: SourceType;
  channel_index: number;
  name: string;
  unit: string | null;
  valid_count: number;
}

export interface DiscoveryResponse {
  upload_id: number;
  trend_frames: number;
  nibp_frames: number;
  periods: number;
  segments: number;
  channels: Channel[];
  detected_local_dates: string[];
  archived_at: string | null;
  archive_id: string | null;
}

export interface MeasurementPoint {
  timestamp: string;
  channel_id: number;
  channel_name: string;
  value: number | null;
}

export interface MeasurementsResponse {
  segment_id: number;
  points: MeasurementPoint[];
}

export interface UploadMeasurementsResponse {
  upload_id: number;
  points: MeasurementPoint[];
}

export interface EncounterMeasurementsResponse {
  encounter_id: number;
  points: MeasurementPoint[];
}

export interface NibpEvent {
  id: number;
  upload_id: number | null;
  segment_id: number | null;
  timestamp: string;
  channel_values: Record<string, number | null>;
  has_measurement: boolean;
}

export interface PatientUploadHistoryItem {
  id: number;
  upload_time: string;
  latest_recorded_at: string | null;
  status: UploadStatus;
  trend_frames: number;
  nibp_frames: number;
  measurements_new: number;
  measurements_reused: number;
  nibp_new: number;
  nibp_reused: number;
  archived_at: string | null;
  archive_id: string | null;
}

export interface PatientAvailableReportDate {
  encounter_date_local: string;
  upload_id: number;
  encounter_id: number | null;
  is_saved: boolean;
}

export interface Encounter {
  id: number;
  patient_id: number;
  upload_id: number;
  encounter_date_local: string;
  timezone: string;
  label: string | null;
  notes: string | null;
  trend_frames: number;
  nibp_frames: number;
  archived_at: string | null;
  archive_id: string | null;
  day_start_utc: string;
  day_end_utc: string;
  created_at: string;
  updated_at: string;
}

export interface EncounterCreatePayload {
  patient_id: number;
  encounter_date_local: string;
  timezone: string;
  label?: string | null;
  notes?: string | null;
}

export interface EncounterUpdatePayload {
  encounter_date_local?: string;
  timezone?: string;
  label?: string | null;
  notes?: string | null;
}

export interface EncounterDeleteResponse {
  deleted: boolean;
  encounter_id: number;
}
