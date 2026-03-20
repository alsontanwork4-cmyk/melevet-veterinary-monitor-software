import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import axios from "axios";

import {
  createEncounterFromUpload,
  deleteStagedUpload,
  getDiscovery,
  getPatient,
  getStagedUpload,
  getUpload,
  listPatientEncounters,
  saveStagedUploadEncounter,
} from "../api/endpoints";
import { Breadcrumb } from "../components/layout/Breadcrumb";

const phaseLabels: Record<string, string> = {
  reading: "Reading files",
  writing_files: "Staging raw files",
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

function renderCanonicalImportSummary({
  measurementsNew,
  measurementsReused,
  nibpNew,
  nibpReused,
}: {
  measurementsNew: number;
  measurementsReused: number;
  nibpNew: number;
  nibpReused: number;
}): string {
  const newTotal = measurementsNew + nibpNew;
  const reusedTotal = measurementsReused + nibpReused;

  if (newTotal === 0 && reusedTotal === 0) {
    return "This upload has not written canonical rows yet.";
  }
  if (newTotal === 0 && reusedTotal > 0) {
    return `No new canonical rows were stored. Reused ${reusedTotal.toLocaleString()} existing rows from earlier imports.`;
  }
  return `Stored ${newTotal.toLocaleString()} new canonical rows and reused ${reusedTotal.toLocaleString()} existing rows.`;
}

export function DiscoveryPage() {
  const { uploadId, stageId } = useParams();
  const parsedUploadId = Number(uploadId);
  const activeStageId = stageId ?? "";
  const isStagedFlow = Boolean(stageId);

  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const requestedPatientId = Number(searchParams.get("patientId"));
  const resolvedRequestedPatientId = Number.isFinite(requestedPatientId) ? requestedPatientId : null;
  const reusedExisting = searchParams.get("reused") === "1";
  const exactDuplicate = searchParams.get("exactDuplicate") === "1";

  const [selectedDate, setSelectedDate] = useState<string>("");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [cancelError, setCancelError] = useState<string | null>(null);

  const stagedUploadQuery = useQuery({
    queryKey: ["staged-upload", activeStageId],
    queryFn: () => getStagedUpload(activeStageId),
    enabled: isStagedFlow,
    refetchInterval: (query) => (query.state.data?.status === "processing" ? 2000 : false),
    retry: false,
  });

  const uploadQuery = useQuery({
    queryKey: ["upload", parsedUploadId],
    queryFn: () => getUpload(parsedUploadId),
    enabled: !isStagedFlow && Number.isFinite(parsedUploadId),
    refetchInterval: (query) => (query.state.data?.status === "processing" ? 2000 : false),
  });

  const patientId = isStagedFlow
    ? (stagedUploadQuery.data?.patient_id ?? null)
    : (resolvedRequestedPatientId ?? uploadQuery.data?.origin_patient_id ?? uploadQuery.data?.patient_id ?? null);

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
    enabled: !isStagedFlow && Number.isFinite(parsedUploadId) && uploadQuery.data?.status === "completed",
  });

  const saveEncounterMutation = useMutation({
    mutationFn: (encounterDateLocal: string) => {
      const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
      if (isStagedFlow) {
        return saveStagedUploadEncounter(activeStageId, {
          encounter_date_local: encounterDateLocal,
          timezone,
        });
      }
      return createEncounterFromUpload(parsedUploadId, {
        patient_id: patientId as number,
        encounter_date_local: encounterDateLocal,
        timezone,
      });
    },
    onSuccess: async (encounter) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["patient-encounters", patientId] }),
        queryClient.invalidateQueries({ queryKey: ["patients"] }),
      ]);
      navigate(`/encounters/${encounter.id}/report`);
    },
  });

  const cancelStageMutation = useMutation({
    mutationFn: () => deleteStagedUpload(activeStageId),
    onSuccess: () => {
      navigate(patientId !== null ? `/patients/${patientId}/upload` : "/");
    },
  });

  const detectedDates = useMemo(() => {
    if (isStagedFlow) {
      return stagedUploadQuery.data?.detected_local_dates ?? [];
    }
    return discoveryQuery.data?.detected_local_dates ?? uploadQuery.data?.detected_local_dates ?? [];
  }, [discoveryQuery.data?.detected_local_dates, isStagedFlow, stagedUploadQuery.data?.detected_local_dates, uploadQuery.data?.detected_local_dates]);

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
    if (!selectedDate) {
      return;
    }

    const existing = encountersQuery.data?.find((encounter) => encounter.encounter_date_local === selectedDate);
    if (existing) {
      const confirmed = window.confirm(
        `An encounter already exists for ${formatEncounterDateLabel(selectedDate)}. Replace it with this saved report day?`,
      );
      if (!confirmed) {
        return;
      }
    }

    setSaveError(null);
    try {
      await saveEncounterMutation.mutateAsync(selectedDate);
    } catch (error) {
      if (axios.isAxiosError(error)) {
        const detail = error.response?.data?.detail;
        if (typeof detail === "string" && detail.trim().length > 0) {
          setSaveError(detail);
          return;
        }
      }
      setSaveError(error instanceof Error ? error.message : "Unable to save encounter.");
    }
  }

  async function handleCancelStage() {
    setCancelError(null);
    try {
      await cancelStageMutation.mutateAsync();
    } catch (error) {
      if (axios.isAxiosError(error)) {
        const detail = error.response?.data?.detail;
        if (typeof detail === "string" && detail.trim().length > 0) {
          setCancelError(detail);
          return;
        }
      }
      setCancelError(error instanceof Error ? error.message : "Unable to cancel staged upload.");
    }
  }

  if ((isStagedFlow && stagedUploadQuery.isLoading) || (!isStagedFlow && uploadQuery.isLoading)) {
    return <div className="card">Loading upload status...</div>;
  }

  if ((isStagedFlow && (stagedUploadQuery.isError || !stagedUploadQuery.data)) || (!isStagedFlow && (uploadQuery.isError || !uploadQuery.data))) {
    return <div className="card error">Unable to load upload status.</div>;
  }

  const activeItem = isStagedFlow ? stagedUploadQuery.data : uploadQuery.data;
  if (!activeItem) {
    return <div className="card error">Unable to load upload status.</div>;
  }

  const heading = isStagedFlow ? "Staged Upload Discovery" : `Upload #${parsedUploadId} Discovery`;
  const phaseLabel = phaseLabels[activeItem.phase] ?? activeItem.phase ?? "Processing";
  const progressTotal = Math.max(0, activeItem.progress_total ?? 0);
  const progressCurrent = Math.max(0, Math.min(activeItem.progress_current ?? 0, progressTotal || Number.MAX_SAFE_INTEGER));
  const progressPercent = progressTotal > 0 ? Math.min(100, Math.round((progressCurrent / progressTotal) * 100)) : 0;
  const startedAtRaw = isStagedFlow ? stagedUploadQuery.data?.created_at : uploadQuery.data?.started_at ?? uploadQuery.data?.upload_time;
  const heartbeatRaw = isStagedFlow ? stagedUploadQuery.data?.updated_at : uploadQuery.data?.heartbeat_at ?? uploadQuery.data?.started_at ?? uploadQuery.data?.upload_time;
  const elapsedSeconds = startedAtRaw ? Math.max(0, (Date.now() - Date.parse(startedAtRaw)) / 1000) : 0;
  const sinceHeartbeatSeconds = heartbeatRaw ? Math.max(0, (Date.now() - Date.parse(heartbeatRaw)) / 1000) : 0;

  if (activeItem.status === "processing") {
    return (
      <div className="stack-md">
        <h1>{heading}</h1>
        <div className="card stack-md">
          <div className="row-between">
            <strong>{phaseLabel}</strong>
            <button
              type="button"
              className="button-muted"
              onClick={() => (isStagedFlow ? stagedUploadQuery.refetch() : uploadQuery.refetch())}
              disabled={isStagedFlow ? stagedUploadQuery.isFetching : uploadQuery.isFetching}
            >
              {(isStagedFlow ? stagedUploadQuery.isFetching : uploadQuery.isFetching) ? "Refreshing..." : "Refresh now"}
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
          <div className="helper-text">
            {isStagedFlow
              ? "This staged upload is still parsing. Nothing has been written to SQLite yet."
              : "Upload is still processing. This page refreshes automatically every 2 seconds."}
          </div>
          {isStagedFlow && (
            <button type="button" className="button-muted" onClick={handleCancelStage} disabled={cancelStageMutation.isPending}>
              {cancelStageMutation.isPending ? "Cancelling..." : "Cancel Staged Upload"}
            </button>
          )}
          {cancelError && <div className="error">{cancelError}</div>}
        </div>
      </div>
    );
  }

  if (activeItem.status === "error") {
    return (
      <div className="stack-md">
        <h1>{heading}</h1>
        <div className="card stack-md">
          <div className="error">
            Parsing failed: {activeItem.error_message ?? "Unknown parsing error."}
          </div>
          <div className="row-between">
            <button
              type="button"
              className="button-muted"
              onClick={() => (isStagedFlow ? stagedUploadQuery.refetch() : uploadQuery.refetch())}
              disabled={isStagedFlow ? stagedUploadQuery.isFetching : uploadQuery.isFetching}
            >
              {(isStagedFlow ? stagedUploadQuery.isFetching : uploadQuery.isFetching) ? "Refreshing..." : "Refresh status"}
            </button>
            {isStagedFlow ? (
              <button type="button" className="button-muted" onClick={handleCancelStage} disabled={cancelStageMutation.isPending}>
                {cancelStageMutation.isPending ? "Cancelling..." : "Discard Staged Upload"}
              </button>
            ) : (
              <Link to="/patients" className="button-link">
                Retry Upload
              </Link>
            )}
          </div>
          {cancelError && <div className="error">{cancelError}</div>}
        </div>
      </div>
    );
  }

  if (!isStagedFlow && discoveryQuery.isLoading) {
    return <div className="card">Loading discovery report...</div>;
  }

  if (!isStagedFlow && (discoveryQuery.isError || !discoveryQuery.data)) {
    return <div className="card error">Unable to load discovery report.</div>;
  }

  const discovery = isStagedFlow ? stagedUploadQuery.data : discoveryQuery.data;
  const patientLabel = patientQuery.data
    ? `${patientQuery.data.name} (${patientQuery.data.species})`
    : (isStagedFlow
      ? `${stagedUploadQuery.data?.patient_name ?? stagedUploadQuery.data?.patient_id_code ?? "New Patient"}${stagedUploadQuery.data?.patient_species ? ` (${stagedUploadQuery.data.patient_species})` : ""}`
      : null);

  return (
    <div className="stack-md">
      {patientLabel && (
        <Breadcrumb
          items={[
            { label: "Patients", to: "/patients" },
            { label: patientLabel },
            { label: isStagedFlow ? `Staged Upload ${stagedUploadQuery.data?.stage_id}` : `Upload #${parsedUploadId}` },
          ]}
        />
      )}
      <h1>{heading}</h1>

      {!isStagedFlow && (exactDuplicate || reusedExisting) && (
        <div className="card stack-sm">
          {exactDuplicate ? (
            <div className="helper-text">Exact duplicate detected. Reused the existing upload instead of storing another copy.</div>
          ) : (
            <div className="helper-text">Existing rows were reused while importing this upload.</div>
          )}
        </div>
      )}

      {!isStagedFlow && uploadQuery.data && (
        <div className="card stack-sm">
          <h2>Canonical Import Summary</h2>
          <div className="helper-text">
            {renderCanonicalImportSummary({
              measurementsNew: uploadQuery.data.measurements_new,
              measurementsReused: uploadQuery.data.measurements_reused,
              nibpNew: uploadQuery.data.nibp_new,
              nibpReused: uploadQuery.data.nibp_reused,
            })}
          </div>
          <div className="helper-text">
            Uploaded monitor export files were used only for parsing. Melevet keeps canonical decoded rows and upload history, not the original raw files.
          </div>
        </div>
      )}

      <div className="card">
        <h2>{isStagedFlow ? "Discovery Summary" : "Channel Discovery Report"}</h2>
        <p>
          Trend Chart Records: <strong>{discovery?.trend_frames ?? 0}</strong> | NIBP Records: <strong>{discovery?.nibp_frames ?? 0}</strong>
        </p>
        <p>
          Recording Periods: <strong>{discovery?.periods ?? 0}</strong> | Segments: <strong>{discovery?.segments ?? 0}</strong>
          {isStagedFlow && <> | Channels: <strong>{stagedUploadQuery.data?.channels.length ?? 0}</strong></>}
        </p>
        {isStagedFlow && <p className="helper-text">This staged export is temporary. SQLite will only receive the selected encounter-day slice.</p>}
      </div>

      <div className="card stack-md">
        <h2>Save Patient Encounter</h2>
        <p className="helper-text">
          Choose the clinic-local collection date before opening the report. Only the selected encounter-day slice will be persisted.
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
          <button type="button" onClick={handleSaveEncounter} disabled={!selectedDate || saveEncounterMutation.isPending}>
            {saveEncounterMutation.isPending ? "Saving..." : "Save Encounter and View Report"}
          </button>
          {isStagedFlow ? (
            <button type="button" className="button-muted" onClick={handleCancelStage} disabled={cancelStageMutation.isPending}>
              {cancelStageMutation.isPending ? "Cancelling..." : "Cancel Staged Upload"}
            </button>
          ) : (
            <Link to="/patients" className="button-muted">
              Back to patients
            </Link>
          )}
        </div>

        {saveError && <div className="error">{saveError}</div>}
        {cancelError && <div className="error">{cancelError}</div>}
      </div>
    </div>
  );
}
