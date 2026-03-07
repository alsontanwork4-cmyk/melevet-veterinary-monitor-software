export type UploadStatus = "processing" | "completed" | "error";
export type SourceType = "trend" | "nibp";
export type AlarmCategory =
  | "technical"
  | "physiological_warning"
  | "physiological_critical"
  | "technical_critical"
  | "system"
  | "informational";

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
  alarm_frames: number;
  combined_hash: string;
  detected_local_dates: string[];
  superseded_at: string | null;
  measurements_new: number;
  measurements_reused: number;
  nibp_new: number;
  nibp_reused: number;
  alarms_new: number;
  alarms_reused: number;
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
  alarm_frames: number;
  periods: number;
  segments: number;
  channels: Channel[];
  detected_local_dates: string[];
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

export interface AlarmEvent {
  id: number;
  upload_id: number;
  segment_id: number;
  timestamp: string;
  flag_hi: number;
  flag_lo: number;
  alarm_category: AlarmCategory;
  message: string;
}

export interface NibpEvent {
  id: number;
  upload_id: number;
  segment_id: number;
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
  alarm_frames: number;
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
  alarm_frames: number;
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
