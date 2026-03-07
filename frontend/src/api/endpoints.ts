import {
  AlarmEvent,
  Channel,
  DiscoveryResponse,
  Encounter,
  EncounterCreatePayload,
  EncounterDeleteResponse,
  EncounterMeasurementsResponse,
  EncounterUpdatePayload,
  MeasurementsResponse,
  NibpEvent,
  Patient,
  PatientAvailableReportDate,
  PatientCreatePayload,
  PatientDeleteResponse,
  PatientUpdatePayload,
  PatientUploadHistoryItem,
  PatientWithUploadCount,
  RecordingPeriod,
  Segment,
  Upload,
  UploadDeleteResponse,
  UploadMeasurementsResponse,
  UploadResponse,
} from "../types/api";
import { apiClient } from "./client";

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

export async function listPatients(query?: string): Promise<PatientWithUploadCount[]> {
  const response = await apiClient.get<PatientWithUploadCount[]>("/patients", {
    params: query ? { q: query } : undefined,
  });
  return response.data;
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

export async function listPatientUploads(patientId: number): Promise<PatientUploadHistoryItem[]> {
  const response = await apiClient.get<PatientUploadHistoryItem[]>(`/patients/${patientId}/uploads`);
  return response.data;
}

export async function listPatientEncounters(patientId: number): Promise<Encounter[]> {
  const response = await apiClient.get<Encounter[]>(`/patients/${patientId}/encounters`);
  return response.data;
}

export async function listPatientAvailableReportDates(patientId: number): Promise<PatientAvailableReportDate[]> {
  const response = await apiClient.get<PatientAvailableReportDate[]>(`/patients/${patientId}/available-report-dates`);
  return response.data;
}

export async function createUpload(formData: FormData): Promise<UploadResponse> {
  const response = await apiClient.post<UploadResponse>("/uploads", formData);
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

export async function deleteUpload(uploadId: number): Promise<UploadDeleteResponse> {
  const response = await apiClient.delete<UploadDeleteResponse>(`/uploads/${uploadId}`);
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

interface AlarmQueryOptions {
  segmentId?: number;
  fromTs?: string;
  toTs?: string;
}

export async function getAlarms(uploadId: number, options?: AlarmQueryOptions): Promise<AlarmEvent[]> {
  const response = await apiClient.get<AlarmEvent[]>(`/uploads/${uploadId}/alarms`, {
    params: {
      segment_id: options?.segmentId,
      from_ts: options?.fromTs,
      to_ts: options?.toTs,
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
  const response = await apiClient.get<NibpEvent[]>(`/uploads/${uploadId}/nibp-events`, {
    params: {
      segment_id: options?.segmentId,
      measurements_only: options?.measurementsOnly,
      from_ts: options?.fromTs,
      to_ts: options?.toTs,
    },
  });
  return response.data;
}

export async function getEncounterNibpEvents(encounterId: number, options?: Pick<NibpQueryOptions, "measurementsOnly">): Promise<NibpEvent[]> {
  const response = await apiClient.get<NibpEvent[]>(`/encounters/${encounterId}/nibp-events`, {
    params: {
      measurements_only: options?.measurementsOnly,
    },
  });
  return response.data;
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

  const base = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api").replace(/\/$/, "");
  return `${base}/uploads/${uploadId}/export?${params.toString()}`;
}

export function exportEncounterCsvUrl(encounterId: number, channelIds: number[]): string {
  const params = new URLSearchParams();
  if (channelIds.length > 0) {
    params.set("channels", channelIds.join(","));
  }

  const base = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api").replace(/\/$/, "");
  return `${base}/encounters/${encounterId}/export?${params.toString()}`;
}
