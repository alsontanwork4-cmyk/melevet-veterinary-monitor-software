import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import axios from "axios";

import {
  deleteUpload,
  deletePatient,
  downloadEncounterExportZip,
  getEncounterChannels,
  getEncounterMeasurements,
  getEncounterNibpEvents,
  getSettings,
  listPatientSpecies,
  listPatientUploads,
  listPatientAvailableReportDates,
  listPatientEncounters,
  listPatients,
  type ListPatientsParams,
} from "../api/endpoints";
import { EditPatientModal } from "../components/patients/EditPatientModal";
import { HelpTip } from "../components/help/HelpTip";
import { PatientHistory } from "../components/patients/PatientHistory";
import { PatientList } from "../components/patients/PatientList";
import { NewPatientModal } from "../components/patients/NewPatientModal";
import { PatientVitalChart } from "../components/patients/PatientVitalChart";
import { helpTips } from "../content/helpContent";
import { resolvePreferredEncounter } from "../utils/patientReports";
import { resolveReportMetrics } from "../utils/reportMetrics";
import { buildSummaryNibpSeries } from "../utils/summaryReportMetrics";
import { resolveSpeciesThresholds } from "../utils/vitalThresholds";
import { PaginatedPatientList, PaginatedResponse, PatientUploadHistoryItem } from "../types/api";

const trendMetricConfig = [
  { key: "heart_rate", title: "Heart Rate", color: "#DC2626", yAxisLabel: "Heart Rate" },
  { key: "spo2", title: "SpO2", color: "#0EA5E9", yAxisLabel: "SpO2" },
] as const;
const PAGE_SIZE = 50;
const UPLOAD_HISTORY_PAGE_SIZE = 50;

function resolvePatientActionError(error: unknown, fallbackMessage: string): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string" && detail.trim().length > 0) {
      return detail;
    }
  }

  if (error instanceof Error && error.message.trim().length > 0) {
    return error.message;
  }

  return fallbackMessage;
}
type PatientFilterState = {
  createdDateFrom: string;
  createdDateTo: string;
  clientName: string;
  patientName: string;
  species: string;
  gender: string;
  age: string;
};

const defaultPatientFilters: PatientFilterState = {
  createdDateFrom: "",
  createdDateTo: "",
  clientName: "",
  patientName: "",
  species: "",
  gender: "",
  age: "",
};

type DeletePatientContext = {
  previousPatients: Array<[readonly unknown[], PaginatedPatientList | undefined]>;
};

type DeleteUploadContext = {
  previousUploads: Array<[readonly unknown[], PaginatedResponse<PatientUploadHistoryItem> | undefined]>;
};

export function PatientsPage() {
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [uploadHistoryPage, setUploadHistoryPage] = useState(1);
  const [isFilterOpen, setIsFilterOpen] = useState(false);
  const [draftFilters, setDraftFilters] = useState<PatientFilterState>(defaultPatientFilters);
  const [appliedFilters, setAppliedFilters] = useState<PatientFilterState>(defaultPatientFilters);
  const [filterError, setFilterError] = useState<string | null>(null);
  const [selectedPatientId, setSelectedPatientId] = useState<number | null>(null);
  const [selectedEncounterId, setSelectedEncounterId] = useState<number | null>(null);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [editingPatientId, setEditingPatientId] = useState<number | null>(null);
  const [patientActionError, setPatientActionError] = useState<string | null>(null);
  const [uploadActionError, setUploadActionError] = useState<string | null>(null);
  const [isBulkExportOpen, setIsBulkExportOpen] = useState(false);
  const [selectedExportEncounterIds, setSelectedExportEncounterIds] = useState<number[]>([]);
  const [exportError, setExportError] = useState<string | null>(null);
  const [isExporting, setIsExporting] = useState(false);
  const filterPanelRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const serverParams = useMemo<ListPatientsParams>(
    () => ({
      q: query.trim() || undefined,
      limit: PAGE_SIZE,
      offset: (page - 1) * PAGE_SIZE,
      species: appliedFilters.species || undefined,
      owner_name: appliedFilters.clientName.trim() || undefined,
      patient_name: appliedFilters.patientName.trim() || undefined,
      gender: appliedFilters.gender || undefined,
      age: appliedFilters.age.trim() || undefined,
      created_from: appliedFilters.createdDateFrom || undefined,
      created_to: appliedFilters.createdDateTo || undefined,
    }),
    [appliedFilters, page, query],
  );

  const patientsQuery = useQuery({
    queryKey: ["patients", serverParams],
    queryFn: () => listPatients(serverParams),
    placeholderData: (previousData) => previousData,
  });

  const patientSpeciesQuery = useQuery({
    queryKey: ["patient-species"],
    queryFn: () => listPatientSpecies(),
  });

  const settingsQuery = useQuery({
    queryKey: ["settings"],
    queryFn: () => getSettings(),
  });

  const speciesOptions = patientSpeciesQuery.data ?? [];
  const displayedPatients = patientsQuery.data?.items ?? [];
  const totalCount = patientsQuery.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE) || 1);

  const hasActiveFilters = useMemo(() => {
    return (
      appliedFilters.createdDateFrom !== defaultPatientFilters.createdDateFrom ||
      appliedFilters.createdDateTo !== defaultPatientFilters.createdDateTo ||
      appliedFilters.clientName !== defaultPatientFilters.clientName ||
      appliedFilters.patientName !== defaultPatientFilters.patientName ||
      appliedFilters.species !== defaultPatientFilters.species ||
      appliedFilters.gender !== defaultPatientFilters.gender ||
      appliedFilters.age !== defaultPatientFilters.age
    );
  }, [appliedFilters]);

  useEffect(() => {
    if (!isFilterOpen) {
      return;
    }

    function handlePointerDown(event: MouseEvent) {
      if (!(event.target instanceof Node)) {
        return;
      }
      if (filterPanelRef.current?.contains(event.target)) {
        return;
      }
      setIsFilterOpen(false);
    }

    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setIsFilterOpen(false);
      }
    }

    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [isFilterOpen]);

  function setDraftFilter<K extends keyof PatientFilterState>(key: K, value: PatientFilterState[K]) {
    setDraftFilters((current) => ({ ...current, [key]: value }));
    setFilterError(null);
  }

  function applyFilters() {
    if (
      draftFilters.createdDateFrom &&
      draftFilters.createdDateTo &&
      draftFilters.createdDateFrom > draftFilters.createdDateTo
    ) {
      setFilterError("Start Date cannot be after End Date.");
      return;
    }

    setAppliedFilters(draftFilters);
    setPage(1);
    setFilterError(null);
    setIsFilterOpen(false);
  }

  function clearFilters() {
    setDraftFilters(defaultPatientFilters);
    setAppliedFilters(defaultPatientFilters);
    setPage(1);
    setFilterError(null);
  }

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages);
    }
  }, [page, totalPages]);

  useEffect(() => {
    if (displayedPatients.length === 0) {
      setSelectedPatientId(null);
      return;
    }
    if (selectedPatientId === null) {
      setSelectedPatientId(displayedPatients[0].id);
      return;
    }
    const stillExists = displayedPatients.some((patient) => patient.id === selectedPatientId);
    if (!stillExists) {
      setSelectedPatientId(displayedPatients[0].id);
    }
  }, [displayedPatients, selectedPatientId]);

  const selectedPatient = useMemo(
    () => displayedPatients.find((patient) => patient.id === selectedPatientId) ?? null,
    [displayedPatients, selectedPatientId],
  );
  const editingPatient = useMemo(
    () => patientsQuery.data?.items?.find((patient) => patient.id === editingPatientId) ?? null,
    [editingPatientId, patientsQuery.data],
  );
  const editingReportDateOptionsQuery = useQuery({
    queryKey: ["patient-available-report-dates", editingPatientId],
    queryFn: () => listPatientAvailableReportDates(editingPatientId as number),
    enabled: editingPatientId !== null,
  });

  const deletePatientMutation = useMutation<Awaited<ReturnType<typeof deletePatient>>, unknown, number, DeletePatientContext>({
    mutationFn: (patientId: number) => deletePatient(patientId),
    onMutate: async (patientId) => {
      await queryClient.cancelQueries({ queryKey: ["patients"] });
      const previousPatients = queryClient.getQueriesData<PaginatedPatientList>({ queryKey: ["patients"] });

      queryClient.setQueriesData<PaginatedPatientList>(
        { queryKey: ["patients"] },
        (currentPatients) =>
          currentPatients
            ? {
                ...currentPatients,
                items: currentPatients.items.filter((patient) => patient.id !== patientId),
                total: Math.max(0, currentPatients.total - 1),
              }
            : currentPatients,
      );

      if (selectedPatientId === patientId) {
        setSelectedPatientId(null);
        setSelectedEncounterId(null);
      }
      if (editingPatientId === patientId) {
        setEditingPatientId(null);
      }

      return { previousPatients };
    },
    onSuccess: (_response, patientId) => {
      queryClient.removeQueries({ queryKey: ["patient-encounters", patientId], exact: true });
    },
    onError: (error, _patientId, context) => {
      context?.previousPatients.forEach(([queryKey, previousPatients]) => {
        queryClient.setQueryData(queryKey, previousPatients);
      });
      setPatientActionError(resolvePatientActionError(error, "Failed to delete patient. Please try again."));
    },
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["patients"] }),
        queryClient.invalidateQueries({ queryKey: ["patient-encounters"] }),
      ]);
    },
  });

  const encountersQuery = useQuery({
    queryKey: ["patient-encounters", selectedPatientId],
    queryFn: () => listPatientEncounters(selectedPatientId as number),
    enabled: selectedPatientId !== null,
  });

  const uploadsQuery = useQuery({
    queryKey: ["patient-uploads", selectedPatientId, uploadHistoryPage],
    queryFn: () =>
      listPatientUploads(selectedPatientId as number, {
        limit: UPLOAD_HISTORY_PAGE_SIZE,
        offset: (uploadHistoryPage - 1) * UPLOAD_HISTORY_PAGE_SIZE,
      }),
    enabled: selectedPatientId !== null,
  });

  useEffect(() => {
    setUploadHistoryPage(1);
  }, [selectedPatientId]);

  useEffect(() => {
    if (!uploadsQuery.data) {
      return;
    }

    const totalPages = Math.max(1, Math.ceil(uploadsQuery.data.total / UPLOAD_HISTORY_PAGE_SIZE));
    if (uploadHistoryPage > totalPages) {
      setUploadHistoryPage(totalPages);
    }
  }, [uploadHistoryPage, uploadsQuery.data]);

  useEffect(() => {
    if (!encountersQuery.data || encountersQuery.data.length === 0) {
      setSelectedEncounterId(null);
      setSelectedExportEncounterIds([]);
      return;
    }

    const preferredEncounter = resolvePreferredEncounter(
      encountersQuery.data,
      selectedPatient?.preferred_encounter_id ?? null,
    );
    setSelectedEncounterId(preferredEncounter?.id ?? encountersQuery.data[0].id);
  }, [encountersQuery.data, selectedPatient?.preferred_encounter_id]);

  useEffect(() => {
    if (!encountersQuery.data || encountersQuery.data.length === 0) {
      setSelectedExportEncounterIds([]);
      return;
    }
    setSelectedExportEncounterIds((current) => {
      if (current.length > 0) {
        return current.filter((encounterId) => encountersQuery.data.some((encounter) => encounter.id === encounterId));
      }
      return encountersQuery.data.map((encounter) => encounter.id);
    });
  }, [encountersQuery.data]);

  const selectedEncounter = useMemo(
    () => encountersQuery.data?.find((encounter) => encounter.id === selectedEncounterId) ?? null,
    [encountersQuery.data, selectedEncounterId],
  );
  const isSelectedEncounterArchived = Boolean(selectedEncounter?.archived_at && selectedEncounter?.archive_id);

  const deleteUploadMutation = useMutation<Awaited<ReturnType<typeof deleteUpload>>, unknown, number, DeleteUploadContext>({
    mutationFn: (uploadId: number) => deleteUpload(uploadId),
    onMutate: async (uploadId) => {
      await queryClient.cancelQueries({ queryKey: ["patient-uploads"] });
      const previousUploads = queryClient.getQueriesData<PaginatedResponse<PatientUploadHistoryItem>>({ queryKey: ["patient-uploads"] });

      queryClient.setQueriesData(
        { queryKey: ["patient-uploads"] },
        (currentUploads: unknown) =>
          currentUploads && typeof currentUploads === "object" && "items" in currentUploads && Array.isArray((currentUploads as { items?: unknown }).items)
            ? {
                ...(currentUploads as PaginatedResponse<PatientUploadHistoryItem>),
                items: (currentUploads as PaginatedResponse<PatientUploadHistoryItem>).items.filter((upload) => upload.id !== uploadId),
                total: Math.max(0, (currentUploads as PaginatedResponse<PatientUploadHistoryItem>).total - 1),
              }
            : currentUploads,
      );

      return { previousUploads };
    },
    onError: (error, _uploadId, context) => {
      context?.previousUploads.forEach(([queryKey, previousUploads]) => {
        queryClient.setQueryData(queryKey, previousUploads);
      });
      setUploadActionError(resolvePatientActionError(error, "Failed to delete upload. Please try again."));
    },
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["patient-uploads"] }),
        queryClient.invalidateQueries({ queryKey: ["patients"] }),
        queryClient.invalidateQueries({ queryKey: ["patient-encounters"] }),
      ]);
    },
  });

  const channelsQuery = useQuery({
    queryKey: ["encounter-channels", selectedEncounter?.id],
    queryFn: () => getEncounterChannels(selectedEncounter!.id, "all"),
    enabled: selectedEncounter !== null && !isSelectedEncounterArchived,
  });

  const resolvedMetrics = useMemo(() => resolveReportMetrics(channelsQuery.data ?? []), [channelsQuery.data]);

  const trendMeasurementsQuery = useQuery({
    queryKey: ["encounter-measurements", selectedEncounter?.id, resolvedMetrics.defaultTrendChannelIds],
    queryFn: () =>
      getEncounterMeasurements(selectedEncounter!.id, {
        channels: resolvedMetrics.defaultTrendChannelIds,
        maxPoints: 10000,
        sourceType: "trend",
      }),
    enabled: selectedEncounter !== null && resolvedMetrics.defaultTrendChannelIds.length > 0 && !isSelectedEncounterArchived,
  });

  const nibpQuery = useQuery({
    queryKey: ["encounter-nibp", selectedEncounter?.id],
    queryFn: () => getEncounterNibpEvents(selectedEncounter!.id, { measurementsOnly: true }),
    enabled: selectedEncounter !== null && !isSelectedEncounterArchived,
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

  const trendCharts = useMemo(
    () =>
      trendMetricConfig.map((metric) => {
        const channel = resolvedMetrics.coreTrendByMetric[metric.key];
        const data = channel ? trendPointsByChannelId[channel.id] ?? [] : [];
        return {
          ...metric,
          channel,
          data,
          seriesName: channel?.name ?? metric.title,
        };
      }),
    [resolvedMetrics.coreTrendByMetric, trendPointsByChannelId],
  );

  const nibpChartSeries = useMemo(() => {
    return buildSummaryNibpSeries(nibpQuery.data ?? [], resolvedMetrics.nibpChannels);
  }, [nibpQuery.data, resolvedMetrics.nibpChannels]);

  const speciesThresholds = useMemo(
    () => resolveSpeciesThresholds(settingsQuery.data?.vital_thresholds ?? {}, selectedPatient?.species),
    [selectedPatient?.species, settingsQuery.data?.vital_thresholds],
  );

  const summaryThresholds = useMemo(() => ({
    heart_rate: speciesThresholds?.heart_rate ? [{ label: "Heart Rate", ...speciesThresholds.heart_rate, color: "#DC2626" }] : [],
    spo2: speciesThresholds?.spo2 ? [{ label: "SpO2", ...speciesThresholds.spo2, color: "#0EA5E9" }] : [],
    nibp: [
      speciesThresholds?.nibp_systolic ? { label: "Systolic", ...speciesThresholds.nibp_systolic, color: "#1D4ED8" } : null,
      speciesThresholds?.nibp_map ? { label: "Mean", ...speciesThresholds.nibp_map, color: "#2563EB" } : null,
      speciesThresholds?.nibp_diastolic ? { label: "Diastolic", ...speciesThresholds.nibp_diastolic, color: "#3B82F6" } : null,
    ].filter(Boolean) as Array<{ label: string; low?: number | null; high?: number | null; color?: string }>,
  }), [speciesThresholds]);

  async function handleDeletePatient(patientId: number) {
    const patient = patientsQuery.data?.items?.find((item) => item.id === patientId);
    const patientLabel = patient ? `${patient.name} (${patient.patient_id_code})` : `patient #${patientId}`;
    const confirmed = window.confirm(`Delete ${patientLabel}? This action cannot be undone.`);
    if (!confirmed) {
      return;
    }

    setPatientActionError(null);
    try {
      await deletePatientMutation.mutateAsync(patientId);
    } catch {
      return;
    }
  }

  async function handleDeleteUpload(uploadId: number) {
    const confirmed = window.confirm(
      `Delete upload #${uploadId}? Canonical rows that are still referenced by other uploads or encounters will be kept.`,
    );
    if (!confirmed) {
      return;
    }

    setUploadActionError(null);
    try {
      await deleteUploadMutation.mutateAsync(uploadId);
    } catch {
      return;
    }
  }

  function toggleExportEncounter(encounterId: number) {
    setSelectedExportEncounterIds((current) => (
      current.includes(encounterId)
        ? current.filter((value) => value !== encounterId)
        : [...current, encounterId]
    ));
    setExportError(null);
  }

  async function handleBulkExport() {
    if (selectedExportEncounterIds.length === 0) {
      setExportError("Select at least one encounter to export.");
      return;
    }

    setIsExporting(true);
    setExportError(null);
    try {
      const result = await downloadEncounterExportZip({ encounter_ids: selectedExportEncounterIds });
      const objectUrl = URL.createObjectURL(result.blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = result.filename ?? "encounter_exports.zip";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);
    } catch (error) {
      setExportError(resolvePatientActionError(error, "Unable to export encounter ZIP."));
    } finally {
      setIsExporting(false);
    }
  }

  return (
    <div className="patients-page patients-dashboard stack-md">
      <div className="page-header">
        <h1>Patients</h1>
        <div className="patients-header-actions">
          <button
            type="button"
            className="button-muted"
            onClick={() => {
              if (selectedPatientId !== null) {
                navigate(`/patients/${selectedPatientId}/upload`);
                return;
              }
              setPatientActionError(null);
              setIsCreateModalOpen(true);
            }}
          >
            Upload Data
          </button>
          <button type="button" className="button-link" onClick={() => setIsCreateModalOpen(true)}>
            + New Patient
          </button>
        </div>
      </div>

      <div className="patients-split-shell">
        <div className="patients-split-layout">
          <div className="patients-left-pane stack-md">
            <div className="card">
              <div className="patients-list-controls">
                <input
                  className="patients-search-input"
                  placeholder="Search by patient code or name..."
                  value={query}
                  onChange={(event) => {
                    setQuery(event.target.value);
                    setPage(1);
                  }}
                />
                <div className="patients-filter-toolbar" ref={filterPanelRef}>
                  <button
                    type="button"
                    className={hasActiveFilters ? "button-muted patients-filter-button patients-filter-button-active" : "button-muted patients-filter-button"}
                    onClick={() => setIsFilterOpen((current) => !current)}
                    aria-expanded={isFilterOpen}
                    aria-haspopup="dialog"
                  >
                    Filter
                  </button>

                  {isFilterOpen && (
                    <div className="patients-filter-panel" role="dialog" aria-label="Patient filters">
                      <div className="patients-filter-panel-grid">
                        <label>
                          <span>Start Date</span>
                          <input
                            type="date"
                            value={draftFilters.createdDateFrom}
                            onChange={(event) => setDraftFilter("createdDateFrom", event.target.value)}
                          />
                        </label>
                        <label>
                          <span>End Date</span>
                          <input
                            type="date"
                            value={draftFilters.createdDateTo}
                            onChange={(event) => setDraftFilter("createdDateTo", event.target.value)}
                          />
                        </label>
                        <label>
                          <span>Client Name</span>
                          <input
                            value={draftFilters.clientName}
                            onChange={(event) => setDraftFilter("clientName", event.target.value)}
                            placeholder="Filter client name"
                          />
                        </label>
                        <label>
                          <span>Patient Name</span>
                          <input
                            value={draftFilters.patientName}
                            onChange={(event) => setDraftFilter("patientName", event.target.value)}
                            placeholder="Filter patient name"
                          />
                        </label>
                        <label>
                          <span>Species</span>
                          <select value={draftFilters.species} onChange={(event) => setDraftFilter("species", event.target.value)}>
                            <option value="">All species</option>
                            {speciesOptions.map((species) => (
                              <option key={species} value={species}>
                                {species}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label>
                          <span>Gender</span>
                          <select value={draftFilters.gender} onChange={(event) => setDraftFilter("gender", event.target.value)}>
                            <option value="">All genders</option>
                            <option value="Male">Male</option>
                            <option value="Female">Female</option>
                            <option value="Other">Other</option>
                          </select>
                        </label>
                        <label>
                          <span>Age</span>
                          <input
                            value={draftFilters.age}
                            onChange={(event) => setDraftFilter("age", event.target.value)}
                            placeholder="Filter age"
                          />
                        </label>
                      </div>
                      {filterError && <p className="error patients-filter-error">{filterError}</p>}
                      <div className="patients-filter-actions">
                        <button type="button" className="button-muted" onClick={clearFilters}>
                          Clear
                        </button>
                        <button type="button" onClick={applyFilters}>
                          Apply
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>

            {patientsQuery.isLoading && <div className="card">Loading patients...</div>}

            {patientsQuery.data && displayedPatients.length > 0 && (
              <PatientList
                patients={displayedPatients}
                page={page}
                totalPages={totalPages}
                totalCount={totalCount}
                selectedPatientId={selectedPatientId}
                onSelectPatient={setSelectedPatientId}
                onUploadPatient={(patientId) => navigate(`/patients/${patientId}/upload`)}
                onEditPatient={(patientId) => {
                  setPatientActionError(null);
                  setEditingPatientId(patientId);
                }}
                onDeletePatient={handleDeletePatient}
                onPageChange={setPage}
              />
            )}

            {patientActionError && (
              <div className="card">
                <p className="error">{patientActionError}</p>
              </div>
            )}

            {patientsQuery.data && totalCount === 0 && !query.trim() && !hasActiveFilters && (
              <div className="card empty-state">
                <div className="empty-state-message">
                  <h3>No patients yet</h3>
                  <p>Upload your first monitoring data to get started.</p>
                  <button type="button" className="button-link" onClick={() => setIsCreateModalOpen(true)}>
                    + New Patient
                  </button>
                </div>
              </div>
            )}

            {patientsQuery.data && totalCount === 0 && (query.trim().length > 0 || hasActiveFilters) && (
              <div className="card">
                <p className="helper-text">No patients match your search or filters.</p>
              </div>
            )}
          </div>

          <div className="patients-right-pane stack-md">
            {!selectedPatient && (
              <div className="card">
                <h3>Summary Report</h3>
                <p className="helper-text">Select a patient from the left panel to visualize the latest saved encounter.</p>
              </div>
            )}

            {selectedPatient && (
              <>
                <div className="patients-summary-header">
                  <h2>Summary Report</h2>
                  <div className="patients-summary-actions">
                    {encountersQuery.data && encountersQuery.data.length > 0 && (
                      <button
                        type="button"
                        className="button-muted"
                        onClick={() => setIsBulkExportOpen((current) => !current)}
                      >
                        {isBulkExportOpen ? "Hide Export" : "Export Encounters ZIP"}
                      </button>
                    )}
                    {selectedEncounter && (
                      <button
                        type="button"
                        className="button-link"
                        onClick={() => navigate(`/encounters/${selectedEncounter.id}/report`)}
                      >
                        Details Report
                      </button>
                    )}
                  </div>
                </div>

                {isBulkExportOpen && encountersQuery.data && encountersQuery.data.length > 0 && (
                  <div className="card stack-sm">
                    <h3>Bulk Encounter Export</h3>
                    <p className="helper-text">Select saved encounters to export as a single ZIP of CSV files.</p>
                    <HelpTip {...helpTips.patientArchive} />
                    <div className="stack-sm">
                      {encountersQuery.data.map((encounter) => (
                        <label key={encounter.id} className="checkbox-row">
                          <input
                            type="checkbox"
                            checked={selectedExportEncounterIds.includes(encounter.id)}
                            onChange={() => toggleExportEncounter(encounter.id)}
                          />
                          {encounter.label ?? encounter.encounter_date_local}
                        </label>
                      ))}
                    </div>
                    {exportError ? <div className="error">{exportError}</div> : null}
                    <div className="row-between">
                      <span className="helper-text">{selectedExportEncounterIds.length} selected</span>
                      <button type="button" onClick={() => void handleBulkExport()} disabled={isExporting}>
                        {isExporting ? "Exporting..." : "Download ZIP"}
                      </button>
                    </div>
                  </div>
                )}

                {(encountersQuery.isLoading || (!isSelectedEncounterArchived && (channelsQuery.isLoading || trendMeasurementsQuery.isLoading || nibpQuery.isLoading))) && (
                  <div className="card">Loading summary charts...</div>
                )}

                {(encountersQuery.isError || (!isSelectedEncounterArchived && (channelsQuery.isError || trendMeasurementsQuery.isError || nibpQuery.isError))) && (
                  <div className="card error">Unable to load summary chart data.</div>
                )}

                {!encountersQuery.isLoading && !encountersQuery.isError && !selectedEncounter && (
                  <div className="card">
                    <p className="helper-text">No saved encounter available for this patient yet.</p>
                    {selectedPatientId !== null && (
                      <button type="button" className="button-link" onClick={() => navigate(`/patients/${selectedPatientId}/upload`)}>
                        Upload Data
                      </button>
                    )}
                  </div>
                )}

                {selectedEncounter && (
                  <div className="stack-md">
                    {isSelectedEncounterArchived ? (
                      <div className="card archived-notice stack-sm">
                        <strong>Selected encounter is archived</strong>
                        <p className="helper-text">
                          Summary history is still visible, but detailed live report data for this encounter has been archived.
                        </p>
                      </div>
                    ) : null}
                    {!isSelectedEncounterArchived && trendCharts.map((chart) => {
                      if (!chart.channel) {
                        return null;
                      }
                      return (
                        <div key={chart.key} className="card patient-vital-card">
                          <div className="row-between">
                            <h4>{chart.title}</h4>
                            <span className="helper-text">{chart.channel.unit ?? "No unit"}</span>
                          </div>
                          {chart.data.length === 0 && <div className="patient-vital-empty">No data points for this saved encounter.</div>}
                          {chart.data.length > 0 && (
                            <PatientVitalChart
                              yAxisLabel={chart.yAxisLabel}
                              series={[
                                {
                                  name: chart.seriesName,
                                  color: chart.color,
                                  data: chart.data,
                                },
                              ]}
                              thresholds={summaryThresholds[chart.key]}
                            />
                          )}
                        </div>
                      );
                    })}

                    {!isSelectedEncounterArchived && nibpChartSeries.length > 0 && (
                      <div className="card patient-vital-card">
                        <div className="row-between">
                          <h4>NIBP (Blood Pressure)</h4>
                          <span className="helper-text">mmHg</span>
                        </div>
                        {nibpChartSeries.every((series) => series.data.length === 0) && (
                          <div className="patient-vital-empty">No NIBP points for this saved encounter.</div>
                        )}
                        {nibpChartSeries.some((series) => series.data.length > 0) && (
                          <PatientVitalChart
                            yAxisLabel="mmHg"
                            series={nibpChartSeries}
                            thresholds={summaryThresholds.nibp}
                          />
                        )}
                      </div>
                    )}
                  </div>
                )}

                {selectedPatientId !== null && uploadsQuery.isLoading && (
                  <div className="card">Loading upload history...</div>
                )}

                {selectedPatientId !== null && uploadsQuery.isError && (
                  <div className="card error">Unable to load upload history.</div>
                )}

                {selectedPatientId !== null && uploadsQuery.data && uploadsQuery.data.total > 0 && (
                  <PatientHistory
                    uploads={uploadsQuery.data.items}
                    page={uploadHistoryPage}
                    totalPages={Math.max(1, Math.ceil(uploadsQuery.data.total / UPLOAD_HISTORY_PAGE_SIZE))}
                    totalCount={uploadsQuery.data.total}
                    onPageChange={setUploadHistoryPage}
                    onDeleteUpload={handleDeleteUpload}
                    deletingUploadId={deleteUploadMutation.isPending ? deleteUploadMutation.variables ?? null : null}
                  />
                )}

                {uploadActionError && (
                  <div className="card">
                    <p className="error">{uploadActionError}</p>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>

      <NewPatientModal
        open={isCreateModalOpen}
        onClose={() => setIsCreateModalOpen(false)}
        onCreated={async (patient) => {
          setSelectedPatientId(patient.id);
          await queryClient.invalidateQueries({ queryKey: ["patients"] });
        }}
      />
      <EditPatientModal
        open={editingPatient !== null}
        patient={editingPatient}
        reportDateOptions={editingReportDateOptionsQuery.data ?? []}
        onClose={() => setEditingPatientId(null)}
        onUpdated={async () => {
          setPatientActionError(null);
          setSelectedEncounterId(null);
          await Promise.all([
            queryClient.invalidateQueries({ queryKey: ["patients"] }),
            queryClient.invalidateQueries({ queryKey: ["patient-encounters"] }),
            queryClient.invalidateQueries({ queryKey: ["patient-available-report-dates"] }),
          ]);
        }}
      />
    </div>
  );
}
