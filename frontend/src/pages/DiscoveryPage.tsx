import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { createEncounterFromUpload, getDiscovery, getPatient, getUpload, listPatientEncounters } from "../api/endpoints";
import { Breadcrumb } from "../components/layout/Breadcrumb";

const phaseLabels: Record<string, string> = {
  reading: "Reading files",
  parsing: "Parsing data frames",
  segmenting: "Building sessions and channels",
  writing_measurements: "Writing measurements",
  writing_events: "Writing events",
  finalizing: "Finalizing upload",
  completed: "Completed",
  error: "Failed",
};

function formatDuration(totalSeconds: number): string {
  if (!Number.isFinite(totalSeconds) || totalSeconds < 0) {
    return "0s";
  }
  const rounded = Math.floor(totalSeconds);
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.floor((rounded % 3600) / 60);
  const seconds = rounded % 60;

  if (hours > 0) {
    return `${hours}h ${minutes}m ${seconds}s`;
  }
  if (minutes > 0) {
    return `${minutes}m ${seconds}s`;
  }
  return `${seconds}s`;
}

function formatEncounterDateLabel(value: string): string {
  const [year, month, day] = value.split("-").map(Number);
  if (!year || !month || !day) {
    return value;
  }
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString();
}

export function DiscoveryPage() {
  const { uploadId } = useParams();
  const parsedUploadId = Number(uploadId);
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const requestedPatientId = Number(searchParams.get("patientId"));
  const resolvedRequestedPatientId = Number.isFinite(requestedPatientId) ? requestedPatientId : null;
  const reusedExisting = searchParams.get("reused") === "1";
  const exactDuplicate = searchParams.get("exactDuplicate") === "1";

  const [selectedDate, setSelectedDate] = useState<string>("");
  const [saveError, setSaveError] = useState<string | null>(null);

  const uploadQuery = useQuery({
    queryKey: ["upload", parsedUploadId],
    queryFn: () => getUpload(parsedUploadId),
    enabled: Number.isFinite(parsedUploadId),
    refetchInterval: (query) => (query.state.data?.status === "processing" ? 2000 : false),
  });

  const patientId = resolvedRequestedPatientId ?? uploadQuery.data?.origin_patient_id ?? uploadQuery.data?.patient_id ?? null;

  const patientQuery = useQuery({
    queryKey: ["patient", patientId],
    queryFn: () => getPatient(patientId as number),
    enabled: patientId !== null,
  });

  const encountersQuery = useQuery({
    queryKey: ["patient-encounters", patientId],
    queryFn: () => listPatientEncounters(patientId as number),
    enabled: patientId !== null,
  });

  const discoveryQuery = useQuery({
    queryKey: ["discovery", parsedUploadId],
    queryFn: () => getDiscovery(parsedUploadId),
    enabled: Number.isFinite(parsedUploadId) && uploadQuery.data?.status === "completed",
  });

  const createEncounterMutation = useMutation({
    mutationFn: (encounterDateLocal: string) =>
      createEncounterFromUpload(parsedUploadId, {
        patient_id: patientId as number,
        encounter_date_local: encounterDateLocal,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
      }),
    onSuccess: async (encounter) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["patient-encounters", patientId] }),
        queryClient.invalidateQueries({ queryKey: ["patients"] }),
      ]);
      navigate(`/encounters/${encounter.id}/report`);
    },
  });

  const detectedDates = useMemo(
    () => discoveryQuery.data?.detected_local_dates ?? uploadQuery.data?.detected_local_dates ?? [],
    [discoveryQuery.data?.detected_local_dates, uploadQuery.data?.detected_local_dates],
  );

  useEffect(() => {
    if (detectedDates.length === 0) {
      setSelectedDate("");
      return;
    }
    if (selectedDate && detectedDates.includes(selectedDate)) {
      return;
    }
    setSelectedDate(detectedDates[detectedDates.length - 1]);
  }, [detectedDates, selectedDate]);

  async function handleSaveEncounter() {
    if (!patientId || !selectedDate) {
      return;
    }

    const existing = encountersQuery.data?.find((encounter) => encounter.encounter_date_local === selectedDate);
    if (existing) {
      const confirmed = window.confirm(
        `An encounter already exists for ${formatEncounterDateLabel(selectedDate)}. Replace it with this newer snapshot?`,
      );
      if (!confirmed) {
        return;
      }
    }

    setSaveError(null);
    try {
      await createEncounterMutation.mutateAsync(selectedDate);
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : "Unable to save encounter.");
    }
  }

  if (uploadQuery.isLoading) {
    return <div className="card">Loading upload status...</div>;
  }

  if (uploadQuery.isError || !uploadQuery.data) {
    return <div className="card error">Unable to load upload status.</div>;
  }

  const upload = uploadQuery.data;
  const startedAtMs = Date.parse(upload.started_at ?? upload.upload_time);
  const heartbeatAtMs = Date.parse(upload.heartbeat_at ?? upload.started_at ?? upload.upload_time);
  const nowMs = Date.now();

  const elapsedSeconds = Number.isFinite(startedAtMs) ? Math.max(0, (nowMs - startedAtMs) / 1000) : 0;
  const sinceHeartbeatSeconds = Number.isFinite(heartbeatAtMs) ? Math.max(0, (nowMs - heartbeatAtMs) / 1000) : 0;

  const progressTotal = Math.max(0, upload.progress_total ?? 0);
  const progressCurrent = Math.max(0, Math.min(upload.progress_current ?? 0, progressTotal || Number.MAX_SAFE_INTEGER));
  const progressPercent = progressTotal > 0 ? Math.min(100, Math.round((progressCurrent / progressTotal) * 100)) : 0;
  const phaseLabel = phaseLabels[upload.phase] ?? upload.phase ?? "Processing";

  const heartbeatStaleWarning = sinceHeartbeatSeconds >= 10 && sinceHeartbeatSeconds < 180;
  const dedupSummary = [
    upload.measurements_reused > 0 || upload.measurements_new > 0
      ? `Measurements: ${upload.measurements_reused} reused, ${upload.measurements_new} new`
      : null,
    upload.nibp_reused > 0 || upload.nibp_new > 0 ? `NIBP: ${upload.nibp_reused} reused, ${upload.nibp_new} new` : null,
    upload.alarms_reused > 0 || upload.alarms_new > 0 ? `Alarms: ${upload.alarms_reused} reused, ${upload.alarms_new} new` : null,
  ]
    .filter((value): value is string => Boolean(value))
    .join(" | ");

  if (upload.status === "processing") {
    return (
      <div className="stack-md">
        <h1>Upload #{parsedUploadId} Discovery</h1>
        <div className="card stack-md">
          <div className="row-between">
            <strong>{phaseLabel}</strong>
            <button type="button" className="button-muted" onClick={() => uploadQuery.refetch()} disabled={uploadQuery.isFetching}>
              {uploadQuery.isFetching ? "Refreshing..." : "Refresh now"}
            </button>
          </div>

          <div className="progress-track" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progressPercent}>
            <div className="progress-fill" style={{ width: `${progressPercent}%` }} />
          </div>
          <div className="helper-text">
            {progressTotal > 0
              ? `${progressCurrent.toLocaleString()} / ${progressTotal.toLocaleString()} (${progressPercent}%)`
              : "Preparing progress details..."}
          </div>
          <div className="helper-text">
            Elapsed: {formatDuration(elapsedSeconds)} | Last update: {formatDuration(sinceHeartbeatSeconds)} ago
          </div>
          <div className={heartbeatStaleWarning ? "warning-text" : "helper-text"}>
            {heartbeatStaleWarning
              ? "Still working, retrying status..."
              : "Upload is still processing. This page refreshes automatically every 2 seconds."}
          </div>
        </div>
      </div>
    );
  }

  if (upload.status === "error") {
    return (
      <div className="stack-md">
        <h1>Upload #{parsedUploadId} Discovery</h1>
        <div className="card stack-md">
          <div className="error">
            Parsing failed: {upload.error_message ?? "Unknown parsing error."}
          </div>
          <div className="row-between">
            <button type="button" className="button-muted" onClick={() => uploadQuery.refetch()} disabled={uploadQuery.isFetching}>
              {uploadQuery.isFetching ? "Refreshing..." : "Refresh status"}
            </button>
            <Link to="/patients" className="button-link">
              Retry Upload
            </Link>
          </div>
        </div>
      </div>
    );
  }

  if (discoveryQuery.isLoading) {
    return <div className="card">Loading discovery report...</div>;
  }

  if (discoveryQuery.isError || !discoveryQuery.data) {
    return <div className="card error">Unable to load discovery report.</div>;
  }

  return (
    <div className="stack-md">
      {patientQuery.data && (
        <Breadcrumb
          items={[
            { label: "Patients", to: "/patients" },
            { label: `${patientQuery.data.name} (${patientQuery.data.species})` },
            { label: `Snapshot #${parsedUploadId}` },
          ]}
        />
      )}
      <h1>Upload #{parsedUploadId} Discovery</h1>

      {(exactDuplicate || reusedExisting || dedupSummary) && (
        <div className="card stack-sm">
          {exactDuplicate ? (
            <div className="helper-text">Exact duplicate detected. Reused the existing upload instead of storing another copy.</div>
          ) : reusedExisting ? (
            <div className="helper-text">Existing rows were reused while importing this upload.</div>
          ) : null}
          {dedupSummary ? <div className="helper-text">{dedupSummary}</div> : null}
        </div>
      )}

      <div className="card">
        <h2>Channel Discovery Report</h2>
        <p>
          Trend Chart Records: <strong>{discoveryQuery.data.trend_frames}</strong> | NIBP Records: <strong>{discoveryQuery.data.nibp_frames}</strong> | Alarm Events: <strong>{discoveryQuery.data.alarm_frames}</strong>
        </p>
        <p>
          Recording Periods: <strong>{discoveryQuery.data.periods}</strong> | Segments: <strong>{discoveryQuery.data.segments}</strong>
        </p>
      </div>

      <div className="card stack-md">
        <h2>Save Patient Encounter</h2>
        <p className="helper-text">
          Choose the clinic-local collection date before opening the report. This locks the report to the selected patient encounter instead of the full monitor history snapshot.
        </p>

        {detectedDates.length > 0 ? (
          <label>
            Encounter date
            <select value={selectedDate} onChange={(event) => setSelectedDate(event.target.value)}>
              {detectedDates.map((value) => (
                <option key={value} value={value}>
                  {formatEncounterDateLabel(value)}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <div className="helper-text">No encounter dates were detected for this upload.</div>
        )}

        <div className="row-between">
          <button
            type="button"
            onClick={handleSaveEncounter}
            disabled={!selectedDate || patientId === null || createEncounterMutation.isPending}
          >
            {createEncounterMutation.isPending ? "Saving..." : "Save Encounter and View Report"}
          </button>
          {patientId !== null && (
            <Link to="/patients" className="button-muted">
              Back to patients
            </Link>
          )}
        </div>

        {saveError && <div className="error">{saveError}</div>}
      </div>
    </div>
  );
}
