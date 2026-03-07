import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import { getAlarms, getChannels, getNibpEvents, getPatient, getPeriods, getSegments, getUpload } from "../api/endpoints";
import { Breadcrumb } from "../components/layout/Breadcrumb";
import { AlarmTable } from "../components/alarms/AlarmTable";
import { AlarmMarkers } from "../components/session/AlarmMarkers";
import { CsvExportButton } from "../components/session/CsvExportButton";
import { NibpOverlay } from "../components/session/NibpOverlay";
import { PeriodSelector } from "../components/session/PeriodSelector";
import { SegmentSelector } from "../components/session/SegmentSelector";
import { TrendChart } from "../components/session/TrendChart";
import { VitalSelector } from "../components/session/VitalSelector";
import { WindowSelector } from "../components/session/WindowSelector";
import { useChartData } from "../hooks/useChartData";
import { formatNumber } from "../utils/format";
import { buildSegmentWindowQuery } from "../utils/sessionWindowQuery";
import {
  channelDisplayLabel,
  friendlyChannelName,
  isKeyVitalChannel,
  keyVitalPriority,
  parseNibpReading,
} from "../utils/vitals";

interface LatestVitalReading {
  label: string;
  value: number;
  unit: string | null;
  priority: number;
}

function latestNumericValue(points: Array<{ value: number | null }>): number | null {
  for (let index = points.length - 1; index >= 0; index -= 1) {
    const value = points[index].value;
    if (typeof value === "number" && Number.isFinite(value)) {
      return value;
    }
  }
  return null;
}

export function SessionPage() {
  const { uploadId } = useParams();
  const parsedUploadId = Number(uploadId);
  const sessionTitle = `Upload #${parsedUploadId} Data Review`;

  const [selectedPeriodId, setSelectedPeriodId] = useState<number | null>(null);
  const [selectedSegmentId, setSelectedSegmentId] = useState<number | null>(null);
  const [windowMinutes, setWindowMinutes] = useState(5);
  const [selectedChannelIds, setSelectedChannelIds] = useState<number[]>([]);

  useEffect(() => {
    setSelectedPeriodId(null);
    setSelectedSegmentId(null);
    setSelectedChannelIds([]);
  }, [parsedUploadId]);

  const uploadQuery = useQuery({
    queryKey: ["upload", parsedUploadId],
    queryFn: () => getUpload(parsedUploadId),
    enabled: Number.isFinite(parsedUploadId),
    refetchInterval: (query) => (query.state.data?.status === "processing" ? 2000 : false),
  });

  const uploadPatientId = uploadQuery.data?.patient_id ?? uploadQuery.data?.origin_patient_id ?? null;

  const patientQuery = useQuery({
    queryKey: ["patient", uploadPatientId],
    queryFn: () => getPatient(uploadPatientId as number),
    enabled: uploadPatientId !== null,
  });

  const isUploadReady = Number.isFinite(parsedUploadId) && uploadQuery.data?.status === "completed";

  const periodsQuery = useQuery({
    queryKey: ["periods", parsedUploadId],
    queryFn: () => getPeriods(parsedUploadId),
    enabled: isUploadReady,
  });

  useEffect(() => {
    if (!periodsQuery.data || periodsQuery.data.length === 0 || selectedPeriodId !== null) {
      return;
    }
    const defaultPeriod = [...periodsQuery.data].sort((a, b) => b.frame_count - a.frame_count)[0];
    setSelectedPeriodId(defaultPeriod.id);
  }, [periodsQuery.data, selectedPeriodId]);

  const segmentsQuery = useQuery({
    queryKey: ["segments", selectedPeriodId],
    queryFn: () => getSegments(selectedPeriodId as number),
    enabled: isUploadReady && selectedPeriodId !== null,
  });

  useEffect(() => {
    if (!segmentsQuery.data || segmentsQuery.data.length === 0 || selectedSegmentId !== null) {
      return;
    }
    const defaultSegment = [...segmentsQuery.data].sort((a, b) => b.frame_count - a.frame_count)[0];
    setSelectedSegmentId(defaultSegment.id);
  }, [segmentsQuery.data, selectedSegmentId]);

  const channelsQuery = useQuery({
    queryKey: ["channels", selectedSegmentId],
    queryFn: () => getChannels(selectedSegmentId as number, "trend"),
    enabled: isUploadReady && selectedSegmentId !== null,
  });

  useEffect(() => {
    if (!channelsQuery.data || channelsQuery.data.length === 0 || selectedChannelIds.length > 0) {
      return;
    }

    const preferredVitals = [...channelsQuery.data]
      .filter((channel) => isKeyVitalChannel(channel.name))
      .sort((a, b) => {
        const priorityDelta = keyVitalPriority(a.name) - keyVitalPriority(b.name);
        if (priorityDelta !== 0) {
          return priorityDelta;
        }
        const validDelta = b.valid_count - a.valid_count;
        if (validDelta !== 0) {
          return validDelta;
        }
        return a.channel_index - b.channel_index;
      })
      .slice(0, 6)
      .map((channel) => channel.id);

    if (preferredVitals.length > 0) {
      setSelectedChannelIds(preferredVitals);
      return;
    }

    const fallback = [...channelsQuery.data]
      .sort((a, b) => b.valid_count - a.valid_count)
      .slice(0, 3)
      .map((channel) => channel.id);
    setSelectedChannelIds(fallback);
  }, [channelsQuery.data, selectedChannelIds.length]);

  const selectedSegment = useMemo(() => {
    if (!segmentsQuery.data || selectedSegmentId === null) {
      return null;
    }
    return segmentsQuery.data.find((segment) => segment.id === selectedSegmentId) ?? null;
  }, [segmentsQuery.data, selectedSegmentId]);

  const [fromTs, toTs] = useMemo(() => {
    if (!selectedSegment) {
      return [undefined, undefined] as [string | undefined, string | undefined];
    }
    const segmentEnd = new Date(selectedSegment.end_time);
    const segmentStart = new Date(selectedSegment.start_time);
    const windowStart = new Date(segmentEnd.getTime() - windowMinutes * 60 * 1000);
    const effectiveStart = windowStart > segmentStart ? windowStart : segmentStart;
    return [effectiveStart.toISOString(), segmentEnd.toISOString()] as [string, string];
  }, [selectedSegment, windowMinutes]);

  const chartQuery = useChartData(isUploadReady ? selectedSegmentId : null, {
    channels: selectedChannelIds,
    fromTs,
    toTs,
    maxPoints: 12000,
    sourceType: "trend",
  });

  const alarmsQuery = useQuery({
    queryKey: ["alarms", parsedUploadId, selectedSegmentId, fromTs, toTs],
    queryFn: () => getAlarms(parsedUploadId, buildSegmentWindowQuery(selectedSegmentId, fromTs, toTs)),
    enabled: isUploadReady && selectedSegmentId !== null && fromTs !== undefined && toTs !== undefined,
  });

  const nibpQuery = useQuery({
    queryKey: ["nibp", parsedUploadId, selectedSegmentId, fromTs, toTs],
    queryFn: () => getNibpEvents(parsedUploadId, buildSegmentWindowQuery(selectedSegmentId, fromTs, toTs)),
    enabled: isUploadReady && selectedSegmentId !== null && fromTs !== undefined && toTs !== undefined,
  });

  const chartSeriesLabelByChannel = useMemo(() => {
    const labels: Record<string, string> = {};
    for (const channel of channelsQuery.data ?? []) {
      labels[channel.name] = channelDisplayLabel(channel.name, channel.unit);
    }
    return labels;
  }, [channelsQuery.data]);

  const latestVitalReadings = useMemo(() => {
    if (!channelsQuery.data || selectedChannelIds.length === 0) {
      return [] as LatestVitalReading[];
    }

    const selectedChannels = channelsQuery.data.filter((channel) => selectedChannelIds.includes(channel.id));
    const readings: LatestVitalReading[] = [];

    for (const channel of selectedChannels) {
      const points = chartQuery.byChannel[channel.name] ?? [];
      const latestValue = latestNumericValue(points);
      if (latestValue === null) {
        continue;
      }

      readings.push({
        label: friendlyChannelName(channel.name),
        value: latestValue,
        unit: channel.unit,
        priority: keyVitalPriority(channel.name),
      });
    }

    readings.sort((a, b) => {
      const priorityDelta = a.priority - b.priority;
      if (priorityDelta !== 0) {
        return priorityDelta;
      }
      return a.label.localeCompare(b.label);
    });

    const deduped: LatestVitalReading[] = [];
    const seenLabels = new Set<string>();
    for (const reading of readings) {
      if (seenLabels.has(reading.label)) {
        continue;
      }
      seenLabels.add(reading.label);
      deduped.push(reading);
    }

    return deduped.slice(0, 8);
  }, [channelsQuery.data, selectedChannelIds, chartQuery.byChannel]);

  const parsedNibpReadings = useMemo(
    () => (nibpQuery.data ?? []).map((event) => ({ event, reading: parseNibpReading(event) })),
    [nibpQuery.data]
  );

  const nibpReadingCount = useMemo(
    () => parsedNibpReadings.filter((item) => item.reading.representative !== null).length,
    [parsedNibpReadings]
  );

  const latestNibpSummary = useMemo(() => {
    for (let index = parsedNibpReadings.length - 1; index >= 0; index -= 1) {
      const reading = parsedNibpReadings[index].reading;
      if (reading.representative !== null) {
        return reading.summary;
      }
    }
    return null;
  }, [parsedNibpReadings]);

  if (uploadQuery.isLoading) {
    return <div className="card">Loading upload status...</div>;
  }

  if (uploadQuery.isError || !uploadQuery.data) {
    return <div className="card error">Unable to load upload status.</div>;
  }

  if (uploadQuery.data.status === "processing") {
    return (
      <div className="stack-md">
        <h1>{sessionTitle}</h1>
        <div className="card">Parsing is in progress. This page refreshes automatically every 2 seconds.</div>
      </div>
    );
  }

  if (uploadQuery.data.status === "error") {
    return (
      <div className="stack-md">
        <h1>{sessionTitle}</h1>
        <div className="card error">
          Parsing failed: {uploadQuery.data.error_message ?? "Unknown parsing error."}
        </div>
      </div>
    );
  }

  if (periodsQuery.isLoading) {
    return <div className="card">Loading session...</div>;
  }

  if (periodsQuery.isError || !periodsQuery.data) {
    return <div className="card error">Unable to load session periods.</div>;
  }

  if (periodsQuery.data.length === 0) {
    return (
      <div className="stack-md">
        <h1>{sessionTitle}</h1>
        <div className="card">No recording periods were generated for this upload.</div>
      </div>
    );
  }

  return (
    <div className="stack-md">
      {patientQuery.data && (
        <Breadcrumb
          items={[
            { label: "Patients", to: "/patients" },
            { label: `${patientQuery.data.name} (${patientQuery.data.species})` },
            { label: `Session #${parsedUploadId} Data Review` },
          ]}
        />
      )}
      <h1>{sessionTitle}</h1>

      <div className="card">
        <h3>Simple Vitals View</h3>
        <p className="helper-text">
          Focus on validated core monitor metrics first: Heart Rate, SpO2, and NIBP (Blood Pressure).
        </p>
      </div>

      <div className="grid grid-2">
        <PeriodSelector
          periods={periodsQuery.data}
          selectedPeriodId={selectedPeriodId}
          onChange={(periodId) => {
            setSelectedPeriodId(periodId);
            setSelectedSegmentId(null);
            setSelectedChannelIds([]);
          }}
        />
        {segmentsQuery.data && (
          <SegmentSelector
            segments={segmentsQuery.data}
            selectedSegmentId={selectedSegmentId}
            onChange={(segmentId) => {
              setSelectedSegmentId(segmentId);
              setSelectedChannelIds([]);
            }}
          />
        )}
        <WindowSelector value={windowMinutes} onChange={setWindowMinutes} />
        {channelsQuery.data && (
          <VitalSelector
            channels={channelsQuery.data}
            selectedChannelIds={selectedChannelIds}
            onChange={setSelectedChannelIds}
          />
        )}
      </div>

      {selectedSegmentId !== null && (
        <div className="card">
          <h3>Latest Vital Readings</h3>
          <div className="vitals-summary-grid">
            {latestVitalReadings.map((reading) => (
              <div key={reading.label} className="vital-reading-card">
                <div className="vital-reading-label">{reading.label}</div>
                <div className="vital-reading-value">
                  {formatNumber(reading.value, 1)}
                  {reading.unit ? ` ${reading.unit}` : ""}
                </div>
              </div>
            ))}
            {latestNibpSummary && (
              <div className="vital-reading-card">
                <div className="vital-reading-label">NIBP (Blood Pressure)</div>
                <div className="vital-reading-value">{latestNibpSummary}</div>
              </div>
            )}
            {latestVitalReadings.length === 0 && !latestNibpSummary && (
              <div className="helper-text">No vital readings available for this selected time range.</div>
            )}
          </div>
        </div>
      )}

      {selectedSegmentId !== null && (
        <div className="card row-between">
          <div>
            <NibpOverlay count={nibpReadingCount} /> <AlarmMarkers count={alarmsQuery.data?.length ?? 0} />
          </div>
          <CsvExportButton
            uploadId={parsedUploadId}
            segmentId={selectedSegmentId}
            channelIds={selectedChannelIds}
            fromTs={fromTs}
            toTs={toTs}
          />
        </div>
      )}

      <div className="card">
        {chartQuery.isLoading && <div>Loading chart...</div>}
        {chartQuery.data && (
          <TrendChart
            groupedData={chartQuery.byChannel}
            nibpEvents={nibpQuery.data ?? []}
            alarms={alarmsQuery.data ?? []}
            seriesLabelByChannel={chartSeriesLabelByChannel}
          />
        )}
      </div>

      <AlarmTable alarms={alarmsQuery.data ?? []} />
    </div>
  );
}
