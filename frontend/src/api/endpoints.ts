import {
  AuthSession,
  AppSettings,
  AppSettingsUpdatePayload,
  ArchiveItem,
  ArchiveRunResult,
  BulkEncounterExportPayload,
  Channel,
  CsrfTokenResponse,
  DiscoveryResponse,
  DatabaseStats,
  Encounter,
  EncounterCreatePayload,
  EncounterDeleteResponse,
  EncounterMeasurementsResponse,
  EncounterUpdatePayload,
  AuthUser,
  LoginPayload,
  MeasurementsResponse,
  NibpEvent,
  PaginatedAuditLog,
  Patient,
  PatientAvailableReportDate,
  PatientCreatePayload,
  PatientDeleteResponse,
  PaginatedPatientList,
  PatientUpdatePayload,
  PatientUploadHistoryItem,
  RecordingPeriod,
  Segment,
  StagedEncounterCreatePayload,
  StagedUpload,
  StagedUploadDeleteResponse,
  TelemetryEventPayload,
  TelemetryStatus,
  UpdateStatus,
  Upload,
  UploadDeleteResponse,
  UploadMeasurementsResponse,
  UploadResponse,
} from "../types/api";
import type { DatabaseDiagnostics, PaginatedResponse } from "../types/api";
import { apiClient, buildApiUrl } from "./client";

export interface DecodeExportDownload {
  blob: Blob;
  filename: string | null;
}

export type DecodeJobStatus = "queued" | "processing" | "completed" | "error";

export interface DecodeJob {
  id: string;
  status: DecodeJobStatus;
  progress_percent: number;
  phase: string;
  detail: string | null;
  filename: string;
  error_message: string | null;
  selected_families: string[];
  created_at: string;
  updated_at: string;
}

export interface ListPatientsParams {
  q?: string;
  limit?: number;
  offset?: number;
  species?: string;
  owner_name?: string;
  patient_name?: string;
  gender?: string;
  age?: string;
  created_from?: string;
  created_to?: string;
}

export interface PaginationParams {
  limit?: number;
  offset?: number;
}

function parseContentDispositionFilename(headerValue: string | undefined): string | null {
  if (!headerValue) {
    return null;
  }

  const utf8Match = headerValue.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match) {
    return decodeURIComponent(utf8Match[1]);
  }

  const quotedMatch = headerValue.match(/filename="([^"]+)"/i);
  if (quotedMatch) {
    return quotedMatch[1];
  }

  const plainMatch = headerValue.match(/filename=([^;]+)/i);
  return plainMatch ? plainMatch[1].trim() : null;
}

export async function listPatients(params?: ListPatientsParams): Promise<PaginatedPatientList> {
  const response = await apiClient.get<PaginatedPatientList>("/patients", {
    params,
  });
  return response.data;
}

export async function listPatientSpecies(): Promise<string[]> {
  const response = await apiClient.get<string[]>("/patients/species");
  return response.data;
}

export async function loginWithPassword(payload: LoginPayload): Promise<AuthSession> {
  const response = await apiClient.post<AuthSession>("/auth/login", payload);
  return response.data;
}

export async function getAuthSession(signal?: AbortSignal): Promise<AuthSession> {
  const response = await apiClient.get<AuthSession>("/auth/session", { signal });
  return response.data;
}

export async function logoutCurrentSession(): Promise<void> {
  await apiClient.post("/auth/logout");
}

export async function getCurrentUser(): Promise<AuthUser> {
  const response = await apiClient.get<AuthUser>("/auth/me");
  return response.data;
}

export async function getAuthCsrfToken(): Promise<CsrfTokenResponse> {
  const response = await apiClient.get<CsrfTokenResponse>("/auth/csrf");
  return response.data;
}

export async function getUpdateStatus(signal?: AbortSignal): Promise<UpdateStatus> {
  const response = await apiClient.get<UpdateStatus>("/update-status", { signal });
  return response.data;
}

export async function getSettings(signal?: AbortSignal): Promise<AppSettings> {
  const response = await apiClient.get<AppSettings>("/settings", { signal });
  return response.data;
}

export async function getDatabaseDiagnostics(signal?: AbortSignal): Promise<DatabaseDiagnostics> {
  const response = await apiClient.get<DatabaseDiagnostics>("/settings/diagnostics", { signal });
  return response.data;
}

export async function getDatabaseStats(signal?: AbortSignal): Promise<DatabaseStats> {
  const response = await apiClient.get<DatabaseStats>("/database/stats", { signal });
  return response.data;
}

export async function updateSettings(payload: AppSettingsUpdatePayload): Promise<AppSettings> {
  const response = await apiClient.patch<AppSettings>("/settings", payload);
  return response.data;
}

export async function listArchives(signal?: AbortSignal): Promise<ArchiveItem[]> {
  const response = await apiClient.get<ArchiveItem[]>("/archives", { signal });
  return response.data;
}

export async function runArchival(): Promise<ArchiveRunResult> {
  const response = await apiClient.post<ArchiveRunResult>("/archives/run");
  return response.data;
}

export async function downloadArchive(archiveId: string): Promise<DecodeExportDownload> {
  const response = await apiClient.get(`/archives/${encodeURIComponent(archiveId)}/download`, {
    responseType: "blob",
  });
  return {
    blob: response.data as Blob,
    filename: parseContentDispositionFilename(response.headers["content-disposition"]) ?? archiveId,
  };
}

export async function listAuditLog(
  params?: { limit?: number; offset?: number; entityType?: string },
  signal?: AbortSignal,
): Promise<PaginatedAuditLog> {
  const response = await apiClient.get<PaginatedAuditLog>("/audit-log", {
    signal,
    params: {
      limit: params?.limit,
      offset: params?.offset,
      entity_type: params?.entityType,
    },
  });
  return response.data;
}

export async function getTelemetryStatus(signal?: AbortSignal): Promise<TelemetryStatus> {
  const response = await apiClient.get<TelemetryStatus>("/telemetry/status", { signal });
  return response.data;
}

export async function exportTelemetry(): Promise<DecodeExportDownload> {
  const response = await apiClient.get("/telemetry/export", {
    responseType: "blob",
  });
  return {
    blob: response.data as Blob,
    filename: parseContentDispositionFilename(response.headers["content-disposition"]) ?? "events.ndjson",
  };
}

export async function postTelemetryEvent(payload: TelemetryEventPayload): Promise<void> {
  await apiClient.post("/telemetry/events", payload);
}

export async function getPatient(patientId: number): Promise<Patient> {
  const response = await apiClient.get<Patient>(`/patients/${patientId}`);
  return response.data;
}

export async function searchPatients(query: string): Promise<Patient[]> {
  const response = await apiClient.get<Patient[]>("/patients/search", { params: { q: query } });
  return response.data;
}

export async function createPatient(payload: PatientCreatePayload): Promise<Patient> {
  const response = await apiClient.post<Patient>("/patients", payload);
  return response.data;
}

export async function updatePatient(patientId: number, payload: PatientUpdatePayload): Promise<Patient> {
  const response = await apiClient.patch<Patient>(`/patients/${patientId}`, payload);
  return response.data;
}

export async function deletePatient(patientId: number): Promise<PatientDeleteResponse> {
  const response = await apiClient.delete<PatientDeleteResponse>(`/patients/${patientId}`);
  return response.data;
}

export async function listPatientUploads(
  patientId: number,
  params?: PaginationParams,
): Promise<PaginatedResponse<PatientUploadHistoryItem>> {
  const response = await apiClient.get<PaginatedResponse<PatientUploadHistoryItem>>(`/patients/${patientId}/uploads`, {
    params,
  });
  return response.data;
}

export async function listPatientEncounters(patientId: number): Promise<Encounter[]> {
  return fetchAllPages<Encounter>(`/patients/${patientId}/encounters`);
}

export async function listPatientAvailableReportDates(patientId: number): Promise<PatientAvailableReportDate[]> {
  const response = await apiClient.get<PatientAvailableReportDate[]>(`/patients/${patientId}/available-report-dates`);
  return response.data;
}

export async function createUpload(formData: FormData): Promise<UploadResponse> {
  const response = await apiClient.post<UploadResponse>("/uploads", formData);
  return response.data;
}

export async function createStagedUpload(formData: FormData): Promise<StagedUpload> {
  const response = await apiClient.post<StagedUpload>("/staged-uploads", formData);
  return response.data;
}

export async function downloadDecodeExport(formData: FormData): Promise<DecodeExportDownload> {
  const response = await apiClient.post("/decode/export", formData, {
    responseType: "blob",
  });

  return {
    blob: response.data as Blob,
    filename: parseContentDispositionFilename(response.headers["content-disposition"]),
  };
}

export async function createDecodeJob(
  formData: FormData,
  onUploadProgress?: (progressPercent: number) => void,
): Promise<DecodeJob> {
  const response = await apiClient.post<DecodeJob>("/decode/jobs", formData, {
    onUploadProgress: (event) => {
      if (!onUploadProgress || !event.total) {
        return;
      }
      onUploadProgress(Math.max(0, Math.min(100, Math.round((event.loaded / event.total) * 100))));
    },
  });
  return response.data;
}

export async function getDecodeJob(jobId: string): Promise<DecodeJob> {
  const response = await apiClient.get<DecodeJob>(`/decode/jobs/${jobId}`);
  return response.data;
}

export async function downloadDecodeJob(jobId: string): Promise<DecodeExportDownload> {
  const response = await apiClient.get(`/decode/jobs/${jobId}/download`, {
    responseType: "blob",
  });

  return {
    blob: response.data as Blob,
    filename: parseContentDispositionFilename(response.headers["content-disposition"]),
  };
}

export async function getUpload(uploadId: number): Promise<Upload> {
  const response = await apiClient.get<Upload>(`/uploads/${uploadId}`);
  return response.data;
}

export async function getStagedUpload(stageId: string): Promise<StagedUpload> {
  const response = await apiClient.get<StagedUpload>(`/staged-uploads/${stageId}`);
  return response.data;
}

export async function deleteUpload(uploadId: number): Promise<UploadDeleteResponse> {
  const response = await apiClient.delete<UploadDeleteResponse>(`/uploads/${uploadId}`);
  return response.data;
}

export async function deleteStagedUpload(stageId: string): Promise<StagedUploadDeleteResponse> {
  const response = await apiClient.delete<StagedUploadDeleteResponse>(`/staged-uploads/${stageId}`);
  return response.data;
}

export async function getDiscovery(uploadId: number): Promise<DiscoveryResponse> {
  const response = await apiClient.get<DiscoveryResponse>(`/uploads/${uploadId}/discovery`);
  return response.data;
}

export async function createEncounterFromUpload(uploadId: number, payload: EncounterCreatePayload): Promise<Encounter> {
  const response = await apiClient.post<Encounter>(`/uploads/${uploadId}/encounters`, payload);
  return response.data;
}

export async function saveStagedUploadEncounter(stageId: string, payload: StagedEncounterCreatePayload): Promise<Encounter> {
  const response = await apiClient.post<Encounter>(`/staged-uploads/${stageId}/encounters`, payload);
  return response.data;
}

export async function getEncounter(encounterId: number): Promise<Encounter> {
  const response = await apiClient.get<Encounter>(`/encounters/${encounterId}`);
  return response.data;
}

export async function updateEncounter(encounterId: number, payload: EncounterUpdatePayload): Promise<Encounter> {
  const response = await apiClient.patch<Encounter>(`/encounters/${encounterId}`, payload);
  return response.data;
}

export async function deleteEncounter(encounterId: number): Promise<EncounterDeleteResponse> {
  const response = await apiClient.delete<EncounterDeleteResponse>(`/encounters/${encounterId}`);
  return response.data;
}

export async function getPeriods(uploadId: number): Promise<RecordingPeriod[]> {
  const response = await apiClient.get<RecordingPeriod[]>(`/uploads/${uploadId}/periods`);
  return response.data;
}

export async function getSegments(periodId: number): Promise<Segment[]> {
  const response = await apiClient.get<Segment[]>(`/periods/${periodId}/segments`);
  return response.data;
}

export async function getChannels(segmentId: number, sourceType: "all" | "trend" | "nibp" = "all"): Promise<Channel[]> {
  const response = await apiClient.get<Channel[]>(`/segments/${segmentId}/channels`, {
    params: { source_type: sourceType },
  });
  return response.data;
}

export async function getUploadChannels(uploadId: number, sourceType: "all" | "trend" | "nibp" = "all"): Promise<Channel[]> {
  const response = await apiClient.get<Channel[]>(`/uploads/${uploadId}/channels`, {
    params: { source_type: sourceType },
  });
  return response.data;
}

export async function getEncounterChannels(encounterId: number, sourceType: "all" | "trend" | "nibp" = "all"): Promise<Channel[]> {
  const response = await apiClient.get<Channel[]>(`/encounters/${encounterId}/channels`, {
    params: { source_type: sourceType },
  });
  return response.data;
}

export interface MeasurementQuery {
  channels?: number[];
  fromTs?: string;
  toTs?: string;
  maxPoints?: number;
  sourceType?: "trend" | "nibp";
}

export async function getMeasurements(segmentId: number, query: MeasurementQuery): Promise<MeasurementsResponse> {
  const response = await apiClient.get<MeasurementsResponse>(`/segments/${segmentId}/measurements`, {
    params: {
      channels: query.channels?.join(","),
      from_ts: query.fromTs,
      to_ts: query.toTs,
      max_points: query.maxPoints,
      source_type: query.sourceType ?? "trend",
    },
  });
  return response.data;
}

export async function getUploadMeasurements(uploadId: number, query: MeasurementQuery): Promise<UploadMeasurementsResponse> {
  const response = await apiClient.get<UploadMeasurementsResponse>(`/uploads/${uploadId}/measurements`, {
    params: {
      channels: query.channels?.join(","),
      from_ts: query.fromTs,
      to_ts: query.toTs,
      max_points: query.maxPoints,
      source_type: query.sourceType ?? "trend",
    },
  });
  return response.data;
}

export async function getEncounterMeasurements(encounterId: number, query: MeasurementQuery): Promise<EncounterMeasurementsResponse> {
  const response = await apiClient.get<EncounterMeasurementsResponse>(`/encounters/${encounterId}/measurements`, {
    params: {
      channels: query.channels?.join(","),
      max_points: query.maxPoints,
      source_type: query.sourceType ?? "trend",
    },
  });
  return response.data;
}

interface NibpQueryOptions {
  segmentId?: number;
  measurementsOnly?: boolean;
  fromTs?: string;
  toTs?: string;
}

export async function getNibpEvents(uploadId: number, options?: NibpQueryOptions): Promise<NibpEvent[]> {
  return fetchAllPages<NibpEvent>(`/uploads/${uploadId}/nibp-events`, {
    segment_id: options?.segmentId,
    measurements_only: options?.measurementsOnly,
    from_ts: options?.fromTs,
    to_ts: options?.toTs,
  });
}

export async function getEncounterNibpEvents(encounterId: number, options?: Pick<NibpQueryOptions, "measurementsOnly">): Promise<NibpEvent[]> {
  return fetchAllPages<NibpEvent>(`/encounters/${encounterId}/nibp-events`, {
    measurements_only: options?.measurementsOnly,
  });
}

export function exportCsvUrl(uploadId: number, segmentId: number, channelIds: number[], fromTs?: string, toTs?: string): string {
  const params = new URLSearchParams();
  params.set("segment_id", String(segmentId));
  if (channelIds.length > 0) {
    params.set("channels", channelIds.join(","));
  }
  if (fromTs) {
    params.set("from_ts", fromTs);
  }
  if (toTs) {
    params.set("to_ts", toTs);
  }

  return `${buildApiUrl(`/uploads/${uploadId}/export`)}?${params.toString()}`;
}

export function exportEncounterCsvUrl(encounterId: number, channelIds: number[]): string {
  const params = new URLSearchParams();
  if (channelIds.length > 0) {
    params.set("channels", channelIds.join(","));
  }

  return `${buildApiUrl(`/encounters/${encounterId}/export`)}?${params.toString()}`;
}

async function fetchAllPages<T>(path: string, params?: Record<string, unknown>): Promise<T[]> {
  const limit = 200;
  let offset = 0;
  const items: T[] = [];

  while (true) {
    const response = await apiClient.get<PaginatedResponse<T>>(path, {
      params: {
        ...params,
        limit,
        offset,
      },
    });
    items.push(...response.data.items);

    if (items.length >= response.data.total || response.data.items.length === 0) {
      break;
    }

    offset += response.data.limit;
  }

  return items;
}

export async function downloadEncounterExportZip(payload: BulkEncounterExportPayload): Promise<DecodeExportDownload> {
  const response = await apiClient.post("/encounters/export-zip", payload, {
    responseType: "blob",
  });
  return {
    blob: response.data as Blob,
    filename: parseContentDispositionFilename(response.headers["content-disposition"]) ?? "encounter_exports.zip",
  };
}
