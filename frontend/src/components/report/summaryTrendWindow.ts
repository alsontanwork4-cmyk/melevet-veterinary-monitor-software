export interface TrendSeriesInput {
  name: string;
  data: Array<[string, number]>;
  color?: string;
  presentation?: "line" | "connected-points";
}

function seriesTimestampBoundsMs(series: TrendSeriesInput[]): { start: number; end: number } | null {
  let earliest: number | null = null;
  let latest: number | null = null;

  for (const item of series) {
    for (const [timestamp] of item.data) {
      const ms = new Date(timestamp).getTime();
      if (!Number.isFinite(ms)) {
        continue;
      }

      if (earliest === null || ms < earliest) {
        earliest = ms;
      }

      if (latest === null || ms > latest) {
        latest = ms;
      }
    }
  }

  if (earliest === null || latest === null) {
    return null;
  }

  return { start: earliest, end: latest };
}

export function buildSeriesBounds(
  dayStartIso: string,
  dayEndIso: string,
  series: TrendSeriesInput[] = [],
): { start: string; end: string } {
  const dayStartMs = new Date(dayStartIso).getTime();
  const dayEndMs = new Date(dayEndIso).getTime();

  if (Number.isNaN(dayStartMs) || Number.isNaN(dayEndMs) || dayStartMs >= dayEndMs) {
    return { start: dayStartIso, end: dayEndIso };
  }

  const dataBounds = seriesTimestampBoundsMs(series);
  if (!dataBounds) {
    return { start: dayStartIso, end: dayEndIso };
  }

  const clampedStartMs = Math.min(dayEndMs, Math.max(dayStartMs, dataBounds.start));
  const clampedEndMs = Math.min(dayEndMs, Math.max(dayStartMs, dataBounds.end));
  return { start: new Date(clampedStartMs).toISOString(), end: new Date(clampedEndMs).toISOString() };
}

export function buildWindowBounds(
  dayStartIso: string,
  dayEndIso: string,
  windowMinutes: number,
  series: TrendSeriesInput[] = [],
): { start: string; end: string } {
  const dataBounds = buildSeriesBounds(dayStartIso, dayEndIso, series);
  const dayStartMs = new Date(dataBounds.start).getTime();
  const dayEndMs = new Date(dataBounds.end).getTime();

  if (Number.isNaN(dayStartMs) || Number.isNaN(dayEndMs) || dayStartMs >= dayEndMs) {
    return { start: dataBounds.start, end: dataBounds.end };
  }

  const windowDurationMs = Math.max(0, windowMinutes) * 60 * 1000;
  const windowEndMs = dayEndMs;
  const windowStartMs = Math.max(dayStartMs, windowEndMs - windowDurationMs);

  return { start: new Date(windowStartMs).toISOString(), end: new Date(windowEndMs).toISOString() };
}
