import { flushSync } from "react-dom";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import {
  downloadArchive,
  getEncounter,
  getEncounterChannels,
  getEncounterMeasurements,
  getEncounterNibpEvents,
  getSettings,
  getPatient,
} from "../api/endpoints";
import { HelpTip } from "../components/help/HelpTip";
import { Breadcrumb } from "../components/layout/Breadcrumb";
import { SummaryTrendChart, type ChartThresholdOverlay, type SummaryTrendChartHandle } from "../components/report/SummaryTrendChart";
import { helpTips } from "../content/helpContent";
import { getAgeFromNotes, getFreeTextNotes, getGenderFromNotes, getTelFromNotes } from "../utils/patientNotes";
import {
  buildSummaryNibpSeries,
  SummaryMetricId,
  resolveSummaryMetrics,
  summaryMetricDefinitions,
} from "../utils/summaryReportMetrics";
import { formatDateTime } from "../utils/format";
import { countOutOfRange, resolveSpeciesThresholds } from "../utils/vitalThresholds";
import { computeVitalStats, type VitalStats } from "../utils/vitalStats";

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

function formatDetailValue(value: string | null | undefined): string {
  const trimmedValue = value?.trim();
  return trimmedValue ? trimmedValue : "-";
}

function formatVitalValue(value: number): string {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(value);
}

function buildSeriesValues(series: Array<{ data: Array<[string, number]> }>): number[] {
  const values: number[] = [];

  for (const item of series) {
    for (const [, value] of item.data) {
      if (Number.isFinite(value)) {
        values.push(value);
      }
    }
  }

  return values;
}

function buildSeriesStatEntriesWithThresholds(
  series: Array<{ name: string; data: Array<[string, number]> }>,
  thresholdsByLabel: Record<string, { low: number | null; high: number | null } | undefined>,
): Array<{
  label: string;
  stats: VitalStats;
  outOfRangeCount: number;
}> {
  return series
    .map((item) => {
      const stats = computeVitalStats(buildSeriesValues([item]));
      const values = buildSeriesValues([item]);
      return stats
        ? {
            label: item.name,
            stats,
            outOfRangeCount: countOutOfRange(values, thresholdsByLabel[item.name]),
          }
        : null;
    })
    .filter((entry): entry is { label: string; stats: VitalStats; outOfRangeCount: number } => entry !== null);
}

function downloadBlob(blob: Blob, filename: string) {
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(objectUrl);
}

export function ReportPage() {
  const { encounterId } = useParams();
  const parsedEncounterId = Number(encounterId);

  const [visibleMetrics, setVisibleMetrics] = useState<Record<SummaryMetricId, boolean>>(defaultVisibleMetrics);
  const [windowByMetric, setWindowByMetric] = useState<Record<SummaryMetricId, number>>(defaultWindowByMetric);
  const [isFilterOpen, setIsFilterOpen] = useState(false);
  const [printTimestamp, setPrintTimestamp] = useState<string | null>(null);
  const filterRef = useRef<HTMLDivElement>(null);
  const chartRefs = useRef<Partial<Record<SummaryMetricId, SummaryTrendChartHandle | null>>>({});
  const printArtifactsRef = useRef<HTMLImageElement[]>([]);

  const cleanupPrintArtifacts = useCallback(() => {
    for (const image of printArtifactsRef.current) {
      image.remove();
    }
    printArtifactsRef.current = [];
  }, []);

  useEffect(() => {
    if (!isFilterOpen) return;
    function handleClickOutside(e: MouseEvent) {
      if (filterRef.current && !filterRef.current.contains(e.target as Node)) {
        setIsFilterOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isFilterOpen]);

  useEffect(() => {
    const handleAfterPrint = () => cleanupPrintArtifacts();
    window.addEventListener("afterprint", handleAfterPrint);
    return () => {
      window.removeEventListener("afterprint", handleAfterPrint);
      cleanupPrintArtifacts();
    };
  }, [cleanupPrintArtifacts]);

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

  const settingsQuery = useQuery({
    queryKey: ["settings"],
    queryFn: () => getSettings(),
  });

  const channelsQuery = useQuery({
    queryKey: ["encounter-channels", parsedEncounterId],
    queryFn: () => getEncounterChannels(parsedEncounterId, "all"),
    enabled: Number.isFinite(parsedEncounterId) && !encounterQuery.data?.archived_at,
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
    enabled: Number.isFinite(parsedEncounterId) && trendChannelIds.length > 0 && !encounterQuery.data?.archived_at,
  });

  const nibpQuery = useQuery({
    queryKey: ["encounter-nibp-events", parsedEncounterId],
    queryFn: () => getEncounterNibpEvents(parsedEncounterId, { measurementsOnly: true }),
    enabled: Number.isFinite(parsedEncounterId) && !encounterQuery.data?.archived_at,
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

  const speciesThresholds = useMemo(
    () => resolveSpeciesThresholds(settingsQuery.data?.vital_thresholds ?? {}, patientQuery.data?.species),
    [patientQuery.data?.species, settingsQuery.data?.vital_thresholds],
  );

  const metricThresholdOverlays = useMemo<Record<SummaryMetricId, ChartThresholdOverlay[]>>(() => ({
    spo2: speciesThresholds?.spo2 ? [{ label: "SpO2", ...speciesThresholds.spo2, color: "#B45309" }] : [],
    heart_rate: speciesThresholds?.heart_rate ? [{ label: "Heart Rate", ...speciesThresholds.heart_rate, color: "#B45309" }] : [],
    nibp: [
      speciesThresholds?.nibp_systolic ? { label: "Systolic", ...speciesThresholds.nibp_systolic, color: "#1D4ED8" } : null,
      speciesThresholds?.nibp_map ? { label: "Mean", ...speciesThresholds.nibp_map, color: "#2563EB" } : null,
      speciesThresholds?.nibp_diastolic ? { label: "Diastolic", ...speciesThresholds.nibp_diastolic, color: "#3B82F6" } : null,
    ].filter(Boolean) as ChartThresholdOverlay[],
  }), [speciesThresholds]);

  const metricThresholdMap = useMemo(() => ({
    spo2: {
      [metricSeries.spo2[0]?.name ?? "SpO2"]: speciesThresholds?.spo2,
    },
    heart_rate: {
      [metricSeries.heart_rate[0]?.name ?? "Heart Rate"]: speciesThresholds?.heart_rate,
    },
    nibp: {
      "Systolic Pressure": speciesThresholds?.nibp_systolic,
      "Mean Pressure": speciesThresholds?.nibp_map,
      "Diastolic Pressure": speciesThresholds?.nibp_diastolic,
    },
  }), [metricSeries.heart_rate, metricSeries.spo2, speciesThresholds]);

  const metricStats = useMemo(() => {
    return {
      spo2: buildSeriesStatEntriesWithThresholds(metricSeries.spo2, metricThresholdMap.spo2),
      heart_rate: buildSeriesStatEntriesWithThresholds(metricSeries.heart_rate, metricThresholdMap.heart_rate),
      nibp: buildSeriesStatEntriesWithThresholds(metricSeries.nibp, metricThresholdMap.nibp),
    };
  }, [metricSeries, metricThresholdMap]);

  const handlePrintReport = useCallback(async () => {
    const timestamp = new Date().toISOString();
    try {
      flushSync(() => {
        setPrintTimestamp(timestamp);
      });

      cleanupPrintArtifacts();

      const printCharts: Array<{ id: SummaryMetricId; label: string; instance: NonNullable<ReturnType<SummaryTrendChartHandle["getEchartsInstance"]>> }> = [];
      for (const metric of summaryMetricDefinitions) {
        if (!visibleMetrics[metric.id]) {
          continue;
        }

        const instance = chartRefs.current[metric.id]?.getEchartsInstance();
        if (instance) {
          printCharts.push({ id: metric.id, label: metric.label, instance });
        }
      }

      for (const { id, label, instance } of printCharts) {
        const chartDom = instance.getDom();
        const image = document.createElement("img");
        image.className = "report-print-chart-image";
        image.alt = `${label} chart for printing`;
        image.src = instance.getDataURL({ type: "png", pixelRatio: 2, backgroundColor: "#FFFFFF" });
        chartDom.after(image);
        printArtifactsRef.current.push(image);
        image.dataset.metricId = id;
      }

      await new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      });

      window.print();
    } finally {
      cleanupPrintArtifacts();
    }
  }, [cleanupPrintArtifacts, visibleMetrics]);

  if (encounterQuery.isLoading) {
    return <div className="card">Loading encounter...</div>;
  }

  if (encounterQuery.isError || !encounterQuery.data) {
    return <div className="card error">Unable to load encounter.</div>;
  }

  const encounter = encounterQuery.data;
  const isArchivedEncounter = Boolean(encounter.archived_at && encounter.archive_id);
  const encounterLabel = formatEncounterDateLabel(encounter.encounter_date_local);
  const patient = patientQuery.data;
  const patientGender = getGenderFromNotes(patient?.notes);
  const patientTel = getTelFromNotes(patient?.notes);
  const patientAge = patient?.age?.trim() || getAgeFromNotes(patient?.notes);
  const patientNotes = getFreeTextNotes(patient?.notes);
  const chartIsLoading = trendMeasurementsQuery.isLoading || channelsQuery.isLoading || nibpQuery.isLoading;
  const chartIsError = trendMeasurementsQuery.isError || channelsQuery.isError || nibpQuery.isError;
  const visibleMetricCount = Math.max(1, summaryMetricDefinitions.filter((metric) => visibleMetrics[metric.id]).length);
  const printHeaderEncounterLabel = encounter.label ?? encounterLabel;
  const summaryMetricGridStyle = {
    "--summary-metric-columns": String(Math.min(visibleMetricCount, 3)),
  } as CSSProperties;

  async function handleDownloadArchive() {
    if (!encounter.archive_id) {
      return;
    }
    const result = await downloadArchive(encounter.archive_id);
    downloadBlob(result.blob, result.filename ?? encounter.archive_id);
  }

  return (
    <div className="stack-lg report-page">
      <div className="print-header" aria-hidden="true">
        <div className="print-header-title">Summary Report</div>
        <div>Patient: {formatDetailValue(patient?.name)}</div>
        <div>Patient ID: {formatDetailValue(patient?.patient_id_code)}</div>
        <div>Encounter: {printHeaderEncounterLabel}</div>
        <div>Printed: {formatDateTime(printTimestamp ?? new Date().toISOString())}</div>
      </div>

      {patientQuery.data && (
        <Breadcrumb
          items={[
            { label: "Patients", to: "/patients" },
            { label: `${patientQuery.data.name} (${patientQuery.data.species})` },
            { label: encounter.label ?? encounterLabel },
          ]}
        />
      )}

      <div className="report-page-title-row">
        <div>
          <h1>Summary Report</h1>
          <p className="report-page-encounter-meta">{encounterLabel} · {encounter.timezone}</p>
        </div>
        {!isArchivedEncounter && (
          <div className="report-page-actions">
            <button type="button" className="report-print-btn" onClick={() => void handlePrintReport()}>
              Print Report
            </button>
            <div className="report-filter-anchor" ref={filterRef}>
              <button
                type="button"
                className={`report-filter-btn${isFilterOpen ? " report-filter-btn-active" : ""}`}
                onClick={() => setIsFilterOpen((v) => !v)}
              >
                <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                  <path d="M2 4h12M4 8h8M6 12h4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>
                </svg>
                Parameters
              </button>
              {isFilterOpen && (
                <div className="report-filter-dropdown">
                  <div className="report-filter-dropdown-title">Show charts</div>
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
              )}
            </div>
          </div>
        )}
      </div>

      {isArchivedEncounter && (
        <div className="card archived-notice stack-md">
          <div className="row-between">
            <div>
              <h2>Archived encounter data</h2>
              <p className="helper-text">
                This encounter remains in history, but its live measurement rows were moved into an archive on{" "}
                {encounter.archived_at ? formatDateTime(encounter.archived_at) : "a previous maintenance run"}.
              </p>
            </div>
            <button type="button" className="button-muted" onClick={() => void handleDownloadArchive()}>
              Download archive ZIP
            </button>
          </div>
          <HelpTip {...helpTips.archivedReport} />
        </div>
      )}

      {patient && (
        <div className="card patient-details-card">
          <div className="patient-details-header">
            <div>
              <h2>Patient Details</h2>
              <p className="patient-details-subtitle">Patient details are shown before the charts for quick review.</p>
            </div>
          </div>

          <div className="patient-details-grid">
            <div className="patient-detail-item">
              <span className="patient-detail-label">Patient ID</span>
              <div className="patient-detail-value">{formatDetailValue(patient.patient_id_code)}</div>
            </div>
            <div className="patient-detail-item">
              <span className="patient-detail-label">Client Name</span>
              <div className="patient-detail-value">{formatDetailValue(patient.owner_name)}</div>
            </div>
            <div className="patient-detail-item">
              <span className="patient-detail-label">Patient Name</span>
              <div className="patient-detail-value">{formatDetailValue(patient.name)}</div>
            </div>
            <div className="patient-detail-item">
              <span className="patient-detail-label">Species</span>
              <div className="patient-detail-value">{formatDetailValue(patient.species)}</div>
            </div>
            <div className="patient-detail-item">
              <span className="patient-detail-label">Gender</span>
              <div className="patient-detail-value">{formatDetailValue(patientGender)}</div>
            </div>
            <div className="patient-detail-item">
              <span className="patient-detail-label">Age</span>
              <div className="patient-detail-value">{formatDetailValue(patientAge)}</div>
            </div>
            <div className="patient-detail-item">
              <span className="patient-detail-label">Tel</span>
              <div className="patient-detail-value">{formatDetailValue(patientTel)}</div>
            </div>
          </div>

          <div className="patient-detail-notes">
            <span className="patient-detail-label">Notes</span>
            <div className="patient-detail-notes-body">{formatDetailValue(patientNotes)}</div>
          </div>
        </div>
      )}

      {!isArchivedEncounter && <HelpTip {...helpTips.archivedReport} />}

      {!isArchivedEncounter && (
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
                    ref={(instance) => {
                      chartRefs.current[metric.id] = instance;
                    }}
                    series={chartSeries}
                    yAxisLabel={yAxisLabel}
                    windowMinutes={selectedWindowMinutes}
                    dayStartIso={encounter.day_start_utc}
                    dayEndIso={encounter.day_end_utc}
                    thresholds={metricThresholdOverlays[metric.id]}
                  />
                )}
                {!chartIsLoading && !chartIsError && !hasSeriesData && (
                  <div className="summary-empty-state">
                    <p>{emptyMessage}</p>
                  </div>
                )}
                {!chartIsLoading && !chartIsError && metricStats[metric.id].length > 0 && (
                  <div className="summary-metric-stats" aria-label={`${metric.label} statistics`}>
                    {metricStats[metric.id].map(({ label, outOfRangeCount, stats }) => (
                      <div key={label} className="summary-metric-stat">
                        <div className="summary-metric-stat-label">{label}</div>
                        <div className="summary-metric-stat-values">
                          <span><strong>Min</strong> {formatVitalValue(stats.min)}</span>
                          <span><strong>Max</strong> {formatVitalValue(stats.max)}</span>
                          <span><strong>Avg</strong> {formatVitalValue(stats.mean)}</span>
                          <span><strong>N</strong> {stats.count}</span>
                          {outOfRangeCount > 0 && <span><strong>Out</strong> {outOfRangeCount}</span>}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
