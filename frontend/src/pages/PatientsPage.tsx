import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import axios from "axios";

import {
  deletePatient,
  getEncounterChannels,
  getEncounterMeasurements,
  getEncounterNibpEvents,
  listPatientAvailableReportDates,
  listPatientEncounters,
  listPatients,
} from "../api/endpoints";
import { EditPatientModal } from "../components/patients/EditPatientModal";
import { PatientList } from "../components/patients/PatientList";
import { NewPatientModal } from "../components/patients/NewPatientModal";
import { PatientVitalChart } from "../components/patients/PatientVitalChart";
import { resolvePreferredEncounter, sortPatientsByCreatedAt } from "../utils/patientReports";
import { resolveReportMetrics } from "../utils/reportMetrics";
import { buildSummaryNibpSeries } from "../utils/summaryReportMetrics";
import { PatientWithUploadCount } from "../types/api";

const trendMetricConfig = [
  { key: "heart_rate", title: "Heart Rate", color: "#DC2626", yAxisLabel: "Heart Rate" },
  { key: "spo2", title: "SpO2", color: "#0EA5E9", yAxisLabel: "SpO2" },
] as const;

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

export function PatientsPage() {
  const [query, setQuery] = useState("");
  const [createdAtSortOrder, setCreatedAtSortOrder] = useState<"asc" | "desc">("desc");
  const [selectedPatientId, setSelectedPatientId] = useState<number | null>(null);
  const [selectedEncounterId, setSelectedEncounterId] = useState<number | null>(null);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [editingPatientId, setEditingPatientId] = useState<number | null>(null);
  const [patientActionError, setPatientActionError] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const patientsQuery = useQuery({
    queryKey: ["patients", query],
    queryFn: () => listPatients(query || undefined),
  });

  const displayedPatients = useMemo(
    () => sortPatientsByCreatedAt(patientsQuery.data ?? [], createdAtSortOrder),
    [patientsQuery.data, createdAtSortOrder],
  );

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
    () => patientsQuery.data?.find((patient) => patient.id === editingPatientId) ?? null,
    [editingPatientId, patientsQuery.data],
  );
  const editingReportDateOptionsQuery = useQuery({
    queryKey: ["patient-available-report-dates", editingPatientId],
    queryFn: () => listPatientAvailableReportDates(editingPatientId as number),
    enabled: editingPatientId !== null,
  });

  const deletePatientMutation = useMutation({
    mutationFn: (patientId: number) => deletePatient(patientId),
    onSuccess: async (_response, patientId) => {
      queryClient.setQueriesData<PatientWithUploadCount[]>(
        { queryKey: ["patients"] },
        (currentPatients) => currentPatients?.filter((patient) => patient.id !== patientId) ?? currentPatients,
      );
      queryClient.removeQueries({ queryKey: ["patient-encounters", patientId], exact: true });
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

  useEffect(() => {
    if (!encountersQuery.data || encountersQuery.data.length === 0) {
      setSelectedEncounterId(null);
      return;
    }

    const preferredEncounter = resolvePreferredEncounter(
      encountersQuery.data,
      selectedPatient?.preferred_encounter_id ?? null,
    );
    setSelectedEncounterId(preferredEncounter?.id ?? encountersQuery.data[0].id);
  }, [encountersQuery.data, selectedPatient?.preferred_encounter_id]);

  const selectedEncounter = useMemo(
    () => encountersQuery.data?.find((encounter) => encounter.id === selectedEncounterId) ?? null,
    [encountersQuery.data, selectedEncounterId],
  );

  const channelsQuery = useQuery({
    queryKey: ["encounter-channels", selectedEncounter?.id],
    queryFn: () => getEncounterChannels(selectedEncounter!.id, "all"),
    enabled: selectedEncounter !== null,
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
    enabled: selectedEncounter !== null && resolvedMetrics.defaultTrendChannelIds.length > 0,
  });

  const nibpQuery = useQuery({
    queryKey: ["encounter-nibp", selectedEncounter?.id],
    queryFn: () => getEncounterNibpEvents(selectedEncounter!.id, { measurementsOnly: true }),
    enabled: selectedEncounter !== null,
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

  async function handleDeletePatient(patientId: number) {
    const patient = patientsQuery.data?.find((item) => item.id === patientId);
    const patientLabel = patient ? `${patient.name} (${patient.patient_id_code})` : `patient #${patientId}`;
    const confirmed = window.confirm(`Delete ${patientLabel}? This action cannot be undone.`);
    if (!confirmed) {
      return;
    }

    setPatientActionError(null);
    try {
      await deletePatientMutation.mutateAsync(patientId);
      if (selectedPatientId === patientId) {
        setSelectedPatientId(null);
        setSelectedEncounterId(null);
      }
      if (editingPatientId === patientId) {
        setEditingPatientId(null);
      }
    } catch (deleteError) {
      setPatientActionError(resolvePatientActionError(deleteError, "Failed to delete patient. Please try again."));
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
                  onChange={(event) => setQuery(event.target.value)}
                />
                <label className="patients-sort-control">
                  <span>Created Date</span>
                  <select value={createdAtSortOrder} onChange={(event) => setCreatedAtSortOrder(event.target.value as "asc" | "desc")}>
                    <option value="desc">Newest first</option>
                    <option value="asc">Oldest first</option>
                  </select>
                </label>
              </div>
            </div>

            {patientsQuery.isLoading && <div className="card">Loading patients...</div>}

            {patientsQuery.data && patientsQuery.data.length > 0 && (
              <PatientList
                patients={displayedPatients}
                selectedPatientId={selectedPatientId}
                onSelectPatient={setSelectedPatientId}
                onUploadPatient={(patientId) => navigate(`/patients/${patientId}/upload`)}
                onEditPatient={(patientId) => {
                  setPatientActionError(null);
                  setEditingPatientId(patientId);
                }}
                onDeletePatient={handleDeletePatient}
                deletingPatientId={deletePatientMutation.isPending ? deletePatientMutation.variables ?? null : null}
              />
            )}

            {patientActionError && (
              <div className="card">
                <p className="error">{patientActionError}</p>
              </div>
            )}

            {patientsQuery.data && patientsQuery.data.length === 0 && !query && (
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

            {patientsQuery.data && patientsQuery.data.length === 0 && query && (
              <div className="card">
                <p className="helper-text">No patients match your search.</p>
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

                {(encountersQuery.isLoading || channelsQuery.isLoading || trendMeasurementsQuery.isLoading || nibpQuery.isLoading) && (
                  <div className="card">Loading summary charts...</div>
                )}

                {(encountersQuery.isError || channelsQuery.isError || trendMeasurementsQuery.isError || nibpQuery.isError) && (
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
                    {trendCharts.map((chart) => {
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
                            />
                          )}
                        </div>
                      );
                    })}

                    {nibpChartSeries.length > 0 && (
                      <div className="card patient-vital-card">
                        <div className="row-between">
                          <h4>NIBP (Blood Pressure)</h4>
                          <span className="helper-text">mmHg</span>
                        </div>
                        {nibpChartSeries.every((series) => series.data.length === 0) && (
                          <div className="patient-vital-empty">No NIBP points for this saved encounter.</div>
                        )}
                        {nibpChartSeries.some((series) => series.data.length > 0) && (
                          <PatientVitalChart yAxisLabel="mmHg" series={nibpChartSeries} />
                        )}
                      </div>
                    )}
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
