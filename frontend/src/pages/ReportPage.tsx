import { useMemo, useState, type CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import {
  getEncounter,
  getEncounterChannels,
  getEncounterMeasurements,
  getEncounterNibpEvents,
  getPatient,
} from "../api/endpoints";
import { Breadcrumb } from "../components/layout/Breadcrumb";
import { SummaryTrendChart } from "../components/report/SummaryTrendChart";
import {
  buildSummaryNibpSeries,
  SummaryMetricId,
  resolveSummaryMetrics,
  summaryMetricDefinitions,
} from "../utils/summaryReportMetrics";

const minuteOptions = [1, 3, 5] as const;

function formatWindowOptionLabel(minutes: number, maxWindowMinutes: number): string {
  if (minutes === maxWindowMinutes && !minuteOptions.includes(minutes as (typeof minuteOptions)[number])) {
    return "All";
  }

  return `${minutes} min`;
}

function defaultVisibleMetrics(): Record<SummaryMetricId, boolean> {
  return {
    spo2: true,
    heart_rate: true,
    nibp: true,
  };
}

function defaultWindowByMetric(): Record<SummaryMetricId, number> {
  return {
    spo2: Number.MAX_SAFE_INTEGER,
    heart_rate: Number.MAX_SAFE_INTEGER,
    nibp: Number.MAX_SAFE_INTEGER,
  };
}

function maxWindowMinutesForSeries(series: Array<{ data: Array<[string, number]> }>): number {
  let earliestMs: number | null = null;
  let latestMs: number | null = null;

  for (const entry of series) {
    for (const [timestamp] of entry.data) {
      const ms = new Date(timestamp).getTime();
      if (!Number.isFinite(ms)) {
        continue;
      }
      if (earliestMs === null || ms < earliestMs) {
        earliestMs = ms;
      }
      if (latestMs === null || ms > latestMs) {
        latestMs = ms;
      }
    }
  }

  if (earliestMs === null || latestMs === null) {
    return 1;
  }

  return Math.max(1, Math.ceil((latestMs - earliestMs) / 60000));
}

function buildMetricEmptyMessage(
  metricId: SummaryMetricId,
  metricLabel: string,
  encounterLabel: string,
  hasResolvedSource: boolean,
  nibpFrameCount: number,
  nibpEventCount: number,
): string {
  if (metricId === "nibp") {
    if (nibpFrameCount === 0) {
      return "This upload snapshot has no parsed NIBP frames, so there is no blood pressure graph to render.";
    }
    if (!hasResolvedSource) {
      return "No systolic or diastolic blood pressure channels were detected for this encounter.";
    }
    if (nibpEventCount === 0) {
      return `No systolic or diastolic blood pressure events were parsed for ${encounterLabel}.`;
    }
    return `No systolic or diastolic blood pressure points were available for ${encounterLabel}.`;
  }

  if (!hasResolvedSource) {
    return `No ${metricLabel} channel was detected for this encounter.`;
  }

  return `No data available for ${metricLabel} on ${encounterLabel}.`;
}

function formatEncounterDateLabel(value: string): string {
  const [year, month, day] = value.split("-").map(Number);
  if (!year || !month || !day) {
    return value;
  }
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString();
}

export function ReportPage() {
  const { encounterId } = useParams();
  const parsedEncounterId = Number(encounterId);

  const [visibleMetrics, setVisibleMetrics] = useState<Record<SummaryMetricId, boolean>>(defaultVisibleMetrics);
  const [windowByMetric, setWindowByMetric] = useState<Record<SummaryMetricId, number>>(defaultWindowByMetric);

  const encounterQuery = useQuery({
    queryKey: ["encounter", parsedEncounterId],
    queryFn: () => getEncounter(parsedEncounterId),
    enabled: Number.isFinite(parsedEncounterId),
  });

  const patientQuery = useQuery({
    queryKey: ["patient", encounterQuery.data?.patient_id],
    queryFn: () => getPatient(encounterQuery.data!.patient_id),
    enabled: encounterQuery.data?.patient_id !== undefined,
  });

  const channelsQuery = useQuery({
    queryKey: ["encounter-channels", parsedEncounterId],
    queryFn: () => getEncounterChannels(parsedEncounterId, "all"),
    enabled: Number.isFinite(parsedEncounterId),
  });

  const resolvedMetrics = useMemo(() => resolveSummaryMetrics(channelsQuery.data ?? []), [channelsQuery.data]);

  const trendChannelIds = useMemo(() => {
    return Array.from(
      new Set(
        Object.values(resolvedMetrics.trendByMetric)
          .filter((channel): channel is NonNullable<typeof channel> => channel !== undefined)
          .map((channel) => channel.id),
      ),
    );
  }, [resolvedMetrics.trendByMetric]);

  const trendMeasurementsQuery = useQuery({
    queryKey: ["encounter-measurements", parsedEncounterId, trendChannelIds],
    queryFn: () =>
      getEncounterMeasurements(parsedEncounterId, {
        channels: trendChannelIds,
        maxPoints: 18000,
        sourceType: "trend",
      }),
    enabled: Number.isFinite(parsedEncounterId) && trendChannelIds.length > 0,
  });

  const nibpQuery = useQuery({
    queryKey: ["encounter-nibp-events", parsedEncounterId],
    queryFn: () => getEncounterNibpEvents(parsedEncounterId, { measurementsOnly: true }),
    enabled: Number.isFinite(parsedEncounterId),
  });

  const trendPointsByChannelId = useMemo(() => {
    const grouped: Record<number, Array<[string, number]>> = {};
    for (const point of trendMeasurementsQuery.data?.points ?? []) {
      if (point.value === null || !Number.isFinite(point.value)) {
        continue;
      }
      if (!grouped[point.channel_id]) {
        grouped[point.channel_id] = [];
      }
      grouped[point.channel_id].push([point.timestamp, point.value]);
    }
    return grouped;
  }, [trendMeasurementsQuery.data]);

  const nibpSeries = useMemo(() => {
    return buildSummaryNibpSeries(nibpQuery.data ?? [], resolvedMetrics.nibpChannels);
  }, [nibpQuery.data, resolvedMetrics.nibpChannels]);

  const metricSeries = useMemo(() => {
    const spo2Channel = resolvedMetrics.trendByMetric.spo2;
    const heartRateChannel = resolvedMetrics.trendByMetric.heart_rate;

    return {
      spo2: spo2Channel
        ? [
          {
            name: spo2Channel.unit ? `SpO2 (${spo2Channel.unit})` : "SpO2",
            data: trendPointsByChannelId[spo2Channel.id] ?? [],
            color: "#0EA5E9",
          },
        ]
        : [],
      heart_rate: heartRateChannel
        ? [
          {
            name: heartRateChannel.unit ? `Heart Rate (${heartRateChannel.unit})` : "Heart Rate",
            data: trendPointsByChannelId[heartRateChannel.id] ?? [],
            color: "#22C55E",
          },
        ]
        : [],
      nibp: nibpSeries,
    };
  }, [nibpSeries, resolvedMetrics.trendByMetric.heart_rate, resolvedMetrics.trendByMetric.spo2, trendPointsByChannelId]);

  if (encounterQuery.isLoading) {
    return <div className="card">Loading encounter...</div>;
  }

  if (encounterQuery.isError || !encounterQuery.data) {
    return <div className="card error">Unable to load encounter.</div>;
  }

  const encounter = encounterQuery.data;
  const encounterLabel = formatEncounterDateLabel(encounter.encounter_date_local);
  const chartIsLoading = trendMeasurementsQuery.isLoading || channelsQuery.isLoading || nibpQuery.isLoading;
  const chartIsError = trendMeasurementsQuery.isError || channelsQuery.isError || nibpQuery.isError;
  const visibleMetricCount = Math.max(1, summaryMetricDefinitions.filter((metric) => visibleMetrics[metric.id]).length);
  const summaryMetricGridStyle = {
    "--summary-metric-columns": String(Math.min(visibleMetricCount, 3)),
  } as CSSProperties;

  return (
    <div className="stack-lg report-page">
      {patientQuery.data && (
        <Breadcrumb
          items={[
            { label: "Patients", to: "/patients" },
            { label: `${patientQuery.data.name} (${patientQuery.data.species})` },
            { label: encounter.label ?? encounterLabel },
          ]}
        />
      )}

      <h1>Summary Report</h1>

      <div className="card summary-controls-card">
        <div className="summary-controls-grid">
          <div className="summary-control-group">
            <span>Encounter</span>
            <div>{encounterLabel}</div>
            <div className="helper-text">{encounter.timezone}</div>
          </div>

          <div className="summary-control-group">
            <span>Parameters</span>
            <div className="summary-checkbox-list">
              {summaryMetricDefinitions.map((metric) => (
                <label key={metric.id} className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={visibleMetrics[metric.id]}
                    onChange={() =>
                      setVisibleMetrics((current) => ({ ...current, [metric.id]: !current[metric.id] }))
                    }
                  />
                  {metric.label}
                </label>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="summary-metric-grid" style={summaryMetricGridStyle}>
        {summaryMetricDefinitions.map((metric) => {
          if (!visibleMetrics[metric.id]) {
            return null;
          }

          const chartSeries = metricSeries[metric.id];
          const hasSeriesData = chartSeries.some((series) => series.data.length > 0);
          const metricHasResolvedSource = metric.id === "nibp"
            ? Boolean(resolvedMetrics.nibpChannels.systolic && resolvedMetrics.nibpChannels.diastolic)
            : Boolean(resolvedMetrics.trendByMetric[metric.id]);
          const emptyMessage = buildMetricEmptyMessage(
            metric.id,
            metric.label,
            encounterLabel,
            metricHasResolvedSource,
            encounter.nibp_frames,
            nibpQuery.data?.length ?? 0,
          );
          const maxWindowMinutes = maxWindowMinutesForSeries(chartSeries);
          const availableWindowOptions = Array.from(
            new Set([...minuteOptions.filter((minutes) => minutes <= maxWindowMinutes), maxWindowMinutes]),
          ).sort((a, b) => a - b);
          const selectedWindowMinutes = Math.min(windowByMetric[metric.id], maxWindowMinutes);
          const yAxisLabel = metric.id === "nibp"
            ? "mmHg"
            : chartSeries[0]?.name.match(/\((.+)\)$/)?.[1] ?? "Value";

          return (
            <div key={metric.id} className="card summary-metric-card">
              <div className="summary-metric-header">
                <h3>{metric.label}</h3>
                {hasSeriesData && (
                  <div className="chips">
                    {availableWindowOptions.map((minutes) => (
                      <button
                        key={`${metric.id}-${minutes}`}
                        type="button"
                        className={selectedWindowMinutes === minutes ? "chip chip-active" : "chip"}
                        onClick={() => setWindowByMetric((current) => ({ ...current, [metric.id]: minutes }))}
                      >
                        {formatWindowOptionLabel(minutes, maxWindowMinutes)}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {chartIsLoading && <div>Loading chart...</div>}
              {chartIsError && <div className="error">Unable to load chart data.</div>}
              {!chartIsLoading && !chartIsError && hasSeriesData && (
                <SummaryTrendChart
                  series={chartSeries}
                  yAxisLabel={yAxisLabel}
                  windowMinutes={selectedWindowMinutes}
                  dayStartIso={encounter.day_start_utc}
                  dayEndIso={encounter.day_end_utc}
                />
              )}
              {!chartIsLoading && !chartIsError && !hasSeriesData && (
                <div className="summary-empty-state">
                  <p>{emptyMessage}</p>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
