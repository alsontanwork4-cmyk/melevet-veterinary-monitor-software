import { PatientUploadHistoryItem, RecordingPeriod, Segment } from "../types/api";
import { formatDateTime } from "./format";
import { formatUtcDayLabel, toUtcDayKey, toUtcDayRange } from "./reportDay";

function toTimestampMs(value: string | null | undefined): number {
  if (!value) {
    return Number.NEGATIVE_INFINITY;
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? Number.NEGATIVE_INFINITY : date.getTime();
}

export function getUploadReportDayKey(upload: Pick<PatientUploadHistoryItem, "latest_recorded_at">): string | null {
  if (!upload.latest_recorded_at) {
    return null;
  }
  return toUtcDayKey(upload.latest_recorded_at);
}

export function collectDuplicateReportDayKeys(
  uploads: Array<Pick<PatientUploadHistoryItem, "latest_recorded_at">>,
): Set<string> {
  const counts = new Map<string, number>();

  for (const upload of uploads) {
    const dayKey = getUploadReportDayKey(upload);
    if (!dayKey) {
      continue;
    }
    counts.set(dayKey, (counts.get(dayKey) ?? 0) + 1);
  }

  return new Set(Array.from(counts.entries()).filter(([, count]) => count > 1).map(([dayKey]) => dayKey));
}

export function formatPatientSummaryUploadLabel(
  upload: Pick<PatientUploadHistoryItem, "id" | "upload_time" | "latest_recorded_at">,
  duplicateDayKeys: Set<string>,
): string {
  const dayKey = getUploadReportDayKey(upload);
  if (!dayKey) {
    return formatDateTime(upload.upload_time);
  }

  const label = formatUtcDayLabel(dayKey);
  return duplicateDayKeys.has(dayKey) ? `${label} (Session #${upload.id})` : label;
}

export function sortCompletedUploads(uploads: PatientUploadHistoryItem[]): PatientUploadHistoryItem[] {
  return [...uploads]
    .filter((upload) => upload.status === "completed")
    .sort((a, b) => {
      const aRecorded = toTimestampMs(a.latest_recorded_at);
      const bRecorded = toTimestampMs(b.latest_recorded_at);
      if (aRecorded !== bRecorded) {
        return bRecorded - aRecorded;
      }

      const aUpload = toTimestampMs(a.upload_time);
      const bUpload = toTimestampMs(b.upload_time);
      if (aUpload !== bUpload) {
        return bUpload - aUpload;
      }

      return b.id - a.id;
    });
}

export function getLatestReportDayKey(periods: RecordingPeriod[]): string | null {
  const dayKeys = new Set<string>();

  for (const period of periods) {
    const startDay = toUtcDayKey(period.start_time);
    const endDay = toUtcDayKey(period.end_time);
    if (startDay) {
      dayKeys.add(startDay);
    }
    if (endDay) {
      dayKeys.add(endDay);
    }
  }

  const sortedDayKeys = Array.from(dayKeys).sort();
  return sortedDayKeys.length > 0 ? sortedDayKeys[sortedDayKeys.length - 1] : null;
}

export function selectLatestPeriod(periods: RecordingPeriod[]): RecordingPeriod | null {
  return [...periods].sort((a, b) => {
    const byEnd = toTimestampMs(b.end_time) - toTimestampMs(a.end_time);
    if (byEnd !== 0) {
      return byEnd;
    }

    const byStart = toTimestampMs(b.start_time) - toTimestampMs(a.start_time);
    if (byStart !== 0) {
      return byStart;
    }

    const byIndex = b.period_index - a.period_index;
    if (byIndex !== 0) {
      return byIndex;
    }

    return b.frame_count - a.frame_count;
  })[0] ?? null;
}

export function selectLatestSegment(segments: Segment[]): Segment | null {
  return [...segments].sort((a, b) => {
    const byEnd = toTimestampMs(b.end_time) - toTimestampMs(a.end_time);
    if (byEnd !== 0) {
      return byEnd;
    }

    const byStart = toTimestampMs(b.start_time) - toTimestampMs(a.start_time);
    if (byStart !== 0) {
      return byStart;
    }

    const byIndex = b.segment_index - a.segment_index;
    if (byIndex !== 0) {
      return byIndex;
    }

    return b.frame_count - a.frame_count;
  })[0] ?? null;
}

export function buildSummaryPreviewWindow(
  segment: Pick<Segment, "start_time" | "end_time">,
  dayKey: string,
): { fromTs: string; toTs: string } | null {
  const dayRange = toUtcDayRange(dayKey);
  if (!dayRange) {
    return null;
  }

  const segmentStartMs = toTimestampMs(segment.start_time);
  const segmentEndMs = toTimestampMs(segment.end_time);
  const dayStartMs = toTimestampMs(dayRange.fromTs);
  const dayEndMs = toTimestampMs(dayRange.toTs);
  if (
    !Number.isFinite(segmentStartMs) ||
    !Number.isFinite(segmentEndMs) ||
    !Number.isFinite(dayStartMs) ||
    !Number.isFinite(dayEndMs)
  ) {
    return null;
  }

  const previewEndMs = Math.min(segmentEndMs, dayEndMs);
  const previewStartMs = Math.max(segmentStartMs, dayStartMs, previewEndMs - 30 * 60 * 1000);
  if (previewStartMs > previewEndMs) {
    return null;
  }

  return {
    fromTs: new Date(previewStartMs).toISOString(),
    toTs: new Date(previewEndMs).toISOString(),
  };
}
