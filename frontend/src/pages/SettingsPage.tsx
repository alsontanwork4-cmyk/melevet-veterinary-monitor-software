import { FormEvent, useEffect, useState } from "react";
import axios from "axios";

import {
  downloadArchive,
  exportTelemetry,
  getDatabaseDiagnostics,
  getDatabaseStats,
  getSettings,
  getTelemetryStatus,
  listArchives,
  runArchival,
  updateSettings,
} from "../api/endpoints";
import { HelpTip } from "../components/help/HelpTip";
import { helpTips } from "../content/helpContent";
import { formatDateTime } from "../utils/format";
import type {
  AppSettings,
  AppSettingsUpdatePayload,
  ArchiveItem,
  DatabaseStats,
  DatabaseDiagnostics,
  SpeciesVitalThresholds,
  TelemetryStatus,
  VitalThresholdRange,
} from "../types/api";
import { replayOnboarding } from "../utils/onboarding";
import { emptySpeciesThresholds } from "../utils/vitalThresholds";

type SettingsFormState = {
  archive_retention_days: string;
  link_table_warning_threshold: string;
  log_level: AppSettings["log_level"];
  orphan_upload_retention_days: string;
  segment_gap_seconds: string;
  recording_period_gap_seconds: string;
  usage_reporting_enabled: boolean;
  vital_thresholds: Record<string, SpeciesVitalThresholds>;
};

const defaultSettings: SettingsFormState = {
  archive_retention_days: "",
  link_table_warning_threshold: "1000000",
  log_level: "INFO",
  orphan_upload_retention_days: "7",
  segment_gap_seconds: String(10 * 60),
  recording_period_gap_seconds: String(24 * 60 * 60),
  usage_reporting_enabled: false,
  vital_thresholds: {},
};

function toFormState(settings: AppSettings): SettingsFormState {
  return {
    archive_retention_days: settings.archive_retention_days === null ? "" : String(settings.archive_retention_days),
    link_table_warning_threshold: String(settings.link_table_warning_threshold),
    log_level: settings.log_level,
    orphan_upload_retention_days: String(settings.orphan_upload_retention_days),
    segment_gap_seconds: String(settings.segment_gap_seconds),
    recording_period_gap_seconds: String(settings.recording_period_gap_seconds),
    usage_reporting_enabled: settings.usage_reporting_enabled,
    vital_thresholds: JSON.parse(JSON.stringify(settings.vital_thresholds ?? {})) as Record<string, SpeciesVitalThresholds>,
  };
}

function toPayload(form: SettingsFormState): AppSettingsUpdatePayload {
  return {
    archive_retention_days: form.archive_retention_days.trim() === "" ? null : Number(form.archive_retention_days),
    link_table_warning_threshold: Number(form.link_table_warning_threshold),
    log_level: form.log_level,
    orphan_upload_retention_days: Number(form.orphan_upload_retention_days),
    segment_gap_seconds: Number(form.segment_gap_seconds),
    recording_period_gap_seconds: Number(form.recording_period_gap_seconds),
    usage_reporting_enabled: form.usage_reporting_enabled,
    vital_thresholds: form.vital_thresholds,
  };
}

function settingsEqual(left: SettingsFormState, right: SettingsFormState) {
  return JSON.stringify(left) === JSON.stringify(right);
}

function formatBytes(value: number | null): string {
  if (value === null) {
    return "Unavailable";
  }
  if (value < 1024) {
    return `${value} B`;
  }

  const units = ["KB", "MB", "GB", "TB"];
  let size = value;
  let unitIndex = -1;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size.toFixed(size >= 10 ? 0 : 1)} ${units[unitIndex]}`;
}

function resolveSettingsError(error: unknown, fallbackMessage: string): string {
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

const thresholdMetrics: Array<{ key: keyof SpeciesVitalThresholds; label: string }> = [
  { key: "spo2", label: "SpO2" },
  { key: "heart_rate", label: "Heart Rate" },
  { key: "nibp_systolic", label: "NIBP Systolic" },
  { key: "nibp_map", label: "NIBP Mean" },
  { key: "nibp_diastolic", label: "NIBP Diastolic" },
];

export function SettingsPage() {
  const [formState, setFormState] = useState<SettingsFormState>(defaultSettings);
  const [initialState, setInitialState] = useState<SettingsFormState>(defaultSettings);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [archives, setArchives] = useState<ArchiveItem[]>([]);
  const [archiveError, setArchiveError] = useState<string | null>(null);
  const [archiveMessage, setArchiveMessage] = useState<string | null>(null);
  const [isArchiveLoading, setIsArchiveLoading] = useState(true);
  const [isRunningArchival, setIsRunningArchival] = useState(false);
  const [downloadingArchiveId, setDownloadingArchiveId] = useState<string | null>(null);
  const [newSpeciesName, setNewSpeciesName] = useState("");
  const [diagnostics, setDiagnostics] = useState<DatabaseDiagnostics | null>(null);
  const [diagnosticsError, setDiagnosticsError] = useState<string | null>(null);
  const [isDiagnosticsLoading, setIsDiagnosticsLoading] = useState(true);
  const [databaseStats, setDatabaseStats] = useState<DatabaseStats | null>(null);
  const [databaseStatsError, setDatabaseStatsError] = useState<string | null>(null);
  const [isDatabaseStatsLoading, setIsDatabaseStatsLoading] = useState(true);
  const [telemetryStatus, setTelemetryStatus] = useState<TelemetryStatus | null>(null);
  const [telemetryError, setTelemetryError] = useState<string | null>(null);
  const [isTelemetryLoading, setIsTelemetryLoading] = useState(true);
  const [isTelemetryExporting, setIsTelemetryExporting] = useState(false);

  async function loadSettings(signal?: AbortSignal) {
    setIsLoading(true);
    setLoadError(null);

    try {
      const settings = await getSettings(signal);
      const nextState = toFormState(settings);
      setFormState(nextState);
      setInitialState(nextState);
    } catch (error) {
      if (!signal?.aborted) {
        setLoadError(resolveSettingsError(error, "Unable to load settings."));
      }
    } finally {
      if (!signal?.aborted) {
        setIsLoading(false);
      }
    }
  }

  async function loadArchiveList(signal?: AbortSignal) {
    setIsArchiveLoading(true);
    setArchiveError(null);
    try {
      const items = await listArchives(signal);
      if (!signal?.aborted) {
        setArchives(items);
      }
    } catch (error) {
      if (!signal?.aborted) {
        setArchiveError(resolveSettingsError(error, "Unable to load archives."));
      }
    } finally {
      if (!signal?.aborted) {
        setIsArchiveLoading(false);
      }
    }
  }

  async function loadDiagnostics(signal?: AbortSignal) {
    setIsDiagnosticsLoading(true);
    setDiagnosticsError(null);
    try {
      const payload = await getDatabaseDiagnostics(signal);
      if (!signal?.aborted) {
        setDiagnostics(payload);
      }
    } catch (error) {
      if (!signal?.aborted) {
        setDiagnosticsError(resolveSettingsError(error, "Unable to load database diagnostics."));
      }
    } finally {
      if (!signal?.aborted) {
        setIsDiagnosticsLoading(false);
      }
    }
  }

  async function loadDatabaseStats(signal?: AbortSignal) {
    setIsDatabaseStatsLoading(true);
    setDatabaseStatsError(null);
    try {
      const payload = await getDatabaseStats(signal);
      if (!signal?.aborted) {
        setDatabaseStats(payload);
      }
    } catch (error) {
      if (!signal?.aborted) {
        setDatabaseStatsError(resolveSettingsError(error, "Unable to load database stats."));
      }
    } finally {
      if (!signal?.aborted) {
        setIsDatabaseStatsLoading(false);
      }
    }
  }

  async function loadTelemetryStatus(signal?: AbortSignal) {
    setIsTelemetryLoading(true);
    setTelemetryError(null);
    try {
      const payload = await getTelemetryStatus(signal);
      if (!signal?.aborted) {
        setTelemetryStatus(payload);
      }
    } catch (error) {
      if (!signal?.aborted) {
        setTelemetryError(resolveSettingsError(error, "Unable to load telemetry status."));
      }
    } finally {
      if (!signal?.aborted) {
        setIsTelemetryLoading(false);
      }
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([
      loadSettings(controller.signal),
      loadArchiveList(controller.signal),
      loadDiagnostics(controller.signal),
      loadDatabaseStats(controller.signal),
      loadTelemetryStatus(controller.signal),
    ]);
    return () => controller.abort();
  }, []);

  function setField<K extends keyof SettingsFormState>(key: K, value: SettingsFormState[K]) {
    setFormState((current) => ({ ...current, [key]: value }));
    setSaveError(null);
    setSaveMessage(null);
  }

  function setThresholdValue(
    species: string,
    metric: keyof SpeciesVitalThresholds,
    bound: keyof VitalThresholdRange,
    rawValue: string,
  ) {
    setFormState((current) => ({
      ...current,
      vital_thresholds: {
        ...current.vital_thresholds,
        [species]: {
          ...current.vital_thresholds[species],
          [metric]: {
            ...current.vital_thresholds[species][metric],
            [bound]: rawValue === "" ? null : Number(rawValue),
          },
        },
      },
    }));
    setSaveError(null);
    setSaveMessage(null);
  }

  function addSpeciesThreshold() {
    const species = newSpeciesName.trim();
    if (!species) {
      setSaveError("Enter a species name before adding thresholds.");
      return;
    }
    const exists = Object.keys(formState.vital_thresholds).some((key) => key.trim().toLowerCase() === species.toLowerCase());
    if (exists) {
      setSaveError("That species already has threshold settings.");
      return;
    }
    setFormState((current) => ({
      ...current,
      vital_thresholds: {
        ...current.vital_thresholds,
        [species]: emptySpeciesThresholds(),
      },
    }));
    setNewSpeciesName("");
    setSaveError(null);
    setSaveMessage(null);
  }

  function removeSpeciesThreshold(species: string) {
    setFormState((current) => {
      const nextThresholds = { ...current.vital_thresholds };
      delete nextThresholds[species];
      return { ...current, vital_thresholds: nextThresholds };
    });
    setSaveError(null);
    setSaveMessage(null);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSaving(true);
    setSaveError(null);
    setSaveMessage(null);

    try {
      const updatedSettings = await updateSettings(toPayload(formState));
      const nextState = toFormState(updatedSettings);
      setFormState(nextState);
      setInitialState(nextState);
      setSaveMessage("Settings saved.");
      await Promise.all([loadDiagnostics(), loadDatabaseStats(), loadTelemetryStatus()]);
    } catch (error) {
      setSaveError(resolveSettingsError(error, "Unable to save settings."));
    } finally {
      setIsSaving(false);
    }
  }

  async function handleRunArchival() {
    setIsRunningArchival(true);
    setArchiveError(null);
    setArchiveMessage(null);
    try {
      const result = await runArchival();
      setArchiveMessage(
        result.archived_upload_count > 0
          ? `Archived ${result.archived_upload_count} upload${result.archived_upload_count === 1 ? "" : "s"}.`
          : "No uploads were eligible for archival.",
      );
      await Promise.all([loadArchiveList(), loadDatabaseStats(), loadDiagnostics()]);
    } catch (error) {
      setArchiveError(resolveSettingsError(error, "Unable to run archival."));
    } finally {
      setIsRunningArchival(false);
    }
  }

  async function handleDownloadArchive(archiveId: string) {
    setDownloadingArchiveId(archiveId);
    setArchiveError(null);
    try {
      const result = await downloadArchive(archiveId);
      downloadBlob(result.blob, result.filename ?? archiveId);
    } catch (error) {
      setArchiveError(resolveSettingsError(error, "Unable to download archive."));
    } finally {
      setDownloadingArchiveId(null);
    }
  }

  async function handleExportTelemetry() {
    setIsTelemetryExporting(true);
    setTelemetryError(null);
    try {
      const result = await exportTelemetry();
      downloadBlob(result.blob, result.filename ?? "events.ndjson");
    } catch (error) {
      setTelemetryError(resolveSettingsError(error, "Unable to export telemetry."));
    } finally {
      setIsTelemetryExporting(false);
    }
  }

  const hasChanges = !settingsEqual(formState, initialState);
  const sortedSpecies = Object.keys(formState.vital_thresholds).sort((left, right) => left.localeCompare(right));

  return (
    <div className="stack-lg">
      <div>
        <h1>Settings</h1>
        <p className="helper-text">
          Manage the clinic-safe runtime settings, alert thresholds, and local database archives for this machine.
        </p>
        <div className="backup-actions">
          <button type="button" className="button-muted" onClick={() => replayOnboarding()}>
            Replay walkthrough
          </button>
        </div>
      </div>

      {isLoading ? (
        <div className="card">
          <p className="helper-text">Loading settings...</p>
        </div>
      ) : loadError ? (
        <div className="card stack-md">
          <div className="error">{loadError}</div>
          <button type="button" onClick={() => void loadSettings()}>
            Retry
          </button>
        </div>
      ) : (
        <form className="stack-lg" onSubmit={handleSubmit}>
          <section className="card stack-md">
            <div>
              <h2>Retention</h2>
              <p className="helper-text">Controls how long archives and orphaned uploads are retained.</p>
            </div>
            <HelpTip {...helpTips.retentionSettings} />

            <div className="grid grid-2">
              <label>
                Archive retention days
                <input
                  type="number"
                  min={1}
                  step={1}
                  value={formState.archive_retention_days}
                  onChange={(event) => setField("archive_retention_days", event.target.value)}
                  disabled={isSaving}
                  placeholder="Disabled"
                />
              </label>

              <label>
                Orphan upload retention days
                <input
                  type="number"
                  min={1}
                  step={1}
                  required
                  value={formState.orphan_upload_retention_days}
                  onChange={(event) => setField("orphan_upload_retention_days", event.target.value)}
                  disabled={isSaving}
                />
              </label>

              <label>
                Link table warning threshold
                <input
                  type="number"
                  min={1}
                  step={1}
                  required
                  value={formState.link_table_warning_threshold}
                  onChange={(event) => setField("link_table_warning_threshold", event.target.value)}
                  disabled={isSaving}
                />
              </label>
            </div>
          </section>

          <section className="card stack-md">
            <div>
              <h2>Processing</h2>
              <p className="helper-text">Gap thresholds used while segmenting and recording measurement streams.</p>
            </div>

            <div className="grid grid-2">
              <label>
                Segment gap seconds
                <input
                  type="number"
                  min={60}
                  step={1}
                  required
                  value={formState.segment_gap_seconds}
                  onChange={(event) => setField("segment_gap_seconds", event.target.value)}
                  disabled={isSaving}
                />
              </label>

              <label>
                Recording period gap seconds
                <input
                  type="number"
                  min={60}
                  step={1}
                  required
                  value={formState.recording_period_gap_seconds}
                  onChange={(event) => setField("recording_period_gap_seconds", event.target.value)}
                  disabled={isSaving}
                />
              </label>
            </div>
          </section>

          <section className="card stack-md">
            <div>
              <h2>Logging</h2>
              <p className="helper-text">Choose the runtime log level stored for this local installation.</p>
            </div>
            <HelpTip {...helpTips.telemetrySettings} />

            <label>
              Log level
              <select
                value={formState.log_level}
                onChange={(event) => setField("log_level", event.target.value as AppSettings["log_level"])}
                disabled={isSaving}
              >
                <option value="DEBUG">DEBUG</option>
                <option value="INFO">INFO</option>
                <option value="WARNING">WARNING</option>
                <option value="ERROR">ERROR</option>
              </select>
            </label>

            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={formState.usage_reporting_enabled}
                onChange={(event) => setField("usage_reporting_enabled", event.target.checked)}
                disabled={isSaving}
              />
              Enable anonymized usage reporting
            </label>
          </section>

          <section className="card stack-md">
            <div className="row-between">
              <div>
                <h2>Database Health</h2>
                <p className="helper-text">Read-only SQLite size and row-count diagnostics for local scale monitoring.</p>
              </div>
              <button type="button" className="button-muted" onClick={() => void loadDiagnostics()} disabled={isDiagnosticsLoading}>
                {isDiagnosticsLoading ? "Refreshing..." : "Refresh"}
              </button>
            </div>

            {diagnosticsError ? <div className="error">{diagnosticsError}</div> : null}

            {diagnostics ? (
              <div className="grid grid-2">
                <div>
                  <strong>Database</strong>
                  <div className="helper-text">{diagnostics.database_kind}</div>
                </div>
                <div>
                  <strong>SQLite file size</strong>
                  <div className="helper-text">{formatBytes(diagnostics.sqlite_file_size_bytes)}</div>
                </div>
                <div>
                  <strong>Measurements</strong>
                  <div className="helper-text">{diagnostics.measurement_count.toLocaleString()}</div>
                </div>
                <div>
                  <strong>Measurement links</strong>
                  <div className="helper-text">
                    {diagnostics.upload_measurement_link_count.toLocaleString()}
                    {diagnostics.upload_measurement_links_over_threshold ? " Warning" : ""}
                  </div>
                </div>
                <div>
                  <strong>NIBP event links</strong>
                  <div className="helper-text">
                    {diagnostics.upload_nibp_event_link_count.toLocaleString()}
                    {diagnostics.upload_nibp_event_links_over_threshold ? " Warning" : ""}
                  </div>
                </div>
              </div>
            ) : !isDiagnosticsLoading && !diagnosticsError ? (
              <p className="helper-text">No diagnostics available.</p>
            ) : null}
          </section>

          <section className="card stack-md">
            <div className="row-between">
              <div>
                <h2>Database Stats</h2>
                <p className="helper-text">Monitor live clinical row counts and archive storage growth.</p>
              </div>
              <button type="button" className="button-muted" onClick={() => void loadDatabaseStats()} disabled={isDatabaseStatsLoading}>
                {isDatabaseStatsLoading ? "Refreshing..." : "Refresh"}
              </button>
            </div>

            {databaseStatsError ? <div className="error">{databaseStatsError}</div> : null}

            {databaseStats ? (
              <div className="grid grid-2">
                <div>
                  <strong>Live measurements</strong>
                  <div className="helper-text">{databaseStats.live_measurement_count.toLocaleString()}</div>
                </div>
                <div>
                  <strong>Live NIBP events</strong>
                  <div className="helper-text">{databaseStats.live_nibp_event_count.toLocaleString()}</div>
                </div>
                <div>
                  <strong>Archived uploads</strong>
                  <div className="helper-text">{databaseStats.archived_upload_count.toLocaleString()}</div>
                </div>
                <div>
                  <strong>Archive files</strong>
                  <div className="helper-text">{databaseStats.archive_file_count.toLocaleString()}</div>
                </div>
                <div>
                  <strong>Archive storage</strong>
                  <div className="helper-text">{formatBytes(databaseStats.archive_total_size_bytes)}</div>
                </div>
                <div>
                  <strong>Oldest archive</strong>
                  <div className="helper-text">{databaseStats.oldest_archive_at ? formatDateTime(databaseStats.oldest_archive_at) : "-"}</div>
                </div>
                <div>
                  <strong>Newest archive</strong>
                  <div className="helper-text">{databaseStats.newest_archive_at ? formatDateTime(databaseStats.newest_archive_at) : "-"}</div>
                </div>
              </div>
            ) : !isDatabaseStatsLoading && !databaseStatsError ? (
              <p className="helper-text">No database stats available.</p>
            ) : null}
          </section>

          <section className="card stack-md">
            <div className="row-between">
              <div>
                <h2>Vital Alert Thresholds</h2>
                <p className="helper-text">Configure species-specific chart overlays for out-of-range vital signs.</p>
              </div>
              <div className="settings-species-add">
                <input
                  value={newSpeciesName}
                  onChange={(event) => setNewSpeciesName(event.target.value)}
                  placeholder="Add species"
                  disabled={isSaving}
                />
                <button type="button" className="button-muted" onClick={addSpeciesThreshold} disabled={isSaving}>
                  Add
                </button>
              </div>
            </div>

            {sortedSpecies.length === 0 ? (
              <p className="helper-text">No species thresholds configured yet.</p>
            ) : (
              <div className="stack-md">
                {sortedSpecies.map((species) => (
                  <div key={species} className="settings-threshold-card">
                    <div className="row-between">
                      <h3>{species}</h3>
                      <button type="button" className="text-button text-button-danger" onClick={() => removeSpeciesThreshold(species)}>
                        Remove
                      </button>
                    </div>

                    <div className="grid grid-2">
                      {thresholdMetrics.map((metric) => (
                        <div key={metric.key} className="settings-threshold-metric">
                          <strong>{metric.label}</strong>
                          <div className="grid grid-2">
                            <label>
                              Low
                              <input
                                type="number"
                                min={0}
                                step="any"
                                value={formState.vital_thresholds[species][metric.key].low ?? ""}
                                onChange={(event) => setThresholdValue(species, metric.key, "low", event.target.value)}
                                disabled={isSaving}
                              />
                            </label>
                            <label>
                              High
                              <input
                                type="number"
                                min={0}
                                step="any"
                                value={formState.vital_thresholds[species][metric.key].high ?? ""}
                                onChange={(event) => setThresholdValue(species, metric.key, "high", event.target.value)}
                                disabled={isSaving}
                              />
                            </label>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="card stack-md">
            <div className="row-between">
              <div>
                <h2>Telemetry Queue</h2>
                <p className="helper-text">View the local anonymized telemetry queue and export it for support review.</p>
              </div>
              <div className="backup-actions">
                <button type="button" className="button-muted" onClick={() => void loadTelemetryStatus()} disabled={isTelemetryLoading}>
                  {isTelemetryLoading ? "Refreshing..." : "Refresh"}
                </button>
                <button type="button" onClick={() => void handleExportTelemetry()} disabled={isTelemetryExporting}>
                  {isTelemetryExporting ? "Exporting..." : "Export telemetry"}
                </button>
              </div>
            </div>

            {telemetryError ? <div className="error">{telemetryError}</div> : null}

            {telemetryStatus ? (
              <div className="grid grid-2">
                <div>
                  <strong>Usage reporting</strong>
                  <div className="helper-text">{telemetryStatus.usage_reporting_enabled ? "Enabled" : "Disabled"}</div>
                </div>
                <div>
                  <strong>Queued usage events</strong>
                  <div className="helper-text">
                    {telemetryStatus.queued_event_count.toLocaleString()} events ({formatBytes(telemetryStatus.queued_size_bytes)})
                  </div>
                </div>
                <div>
                  <strong>Crash reports</strong>
                  <div className="helper-text">
                    {telemetryStatus.crash_event_count.toLocaleString()} events ({formatBytes(telemetryStatus.crash_size_bytes)})
                  </div>
                </div>
              </div>
            ) : !isTelemetryLoading && !telemetryError ? (
              <p className="helper-text">No telemetry status available.</p>
            ) : null}
          </section>

          <div className="stack-sm">
            {saveError ? <div className="error">{saveError}</div> : null}
            {saveMessage ? <div className="helper-text">{saveMessage}</div> : null}
            <button type="submit" disabled={isSaving || !hasChanges}>
              {isSaving ? "Saving..." : "Save changes"}
            </button>
          </div>
        </form>
      )}

      <section className="card stack-md">
        <div className="row-between">
          <div>
            <h2>Archives</h2>
            <p className="helper-text">Archive eligible uploads into ZIP exports while keeping encounter metadata available.</p>
          </div>
          <div className="backup-actions">
            <button type="button" className="button-muted" onClick={() => void handleRunArchival()} disabled={isRunningArchival}>
              {isRunningArchival ? "Archiving..." : "Archive now"}
            </button>
          </div>
        </div>
        <HelpTip {...helpTips.patientArchive} />

        {archiveError ? <div className="error">{archiveError}</div> : null}
        {archiveMessage ? <div className="helper-text">{archiveMessage}</div> : null}

        <div className="advanced-details stack-sm">
          <div className="row-between">
            <div>
              <h3>Archives</h3>
              <p className="helper-text">Archived uploads keep metadata live while the clinical rows move into ZIP exports.</p>
            </div>
            <button type="button" className="button-muted" onClick={() => void loadArchiveList()} disabled={isArchiveLoading}>
              {isArchiveLoading ? "Refreshing..." : "Refresh"}
            </button>
          </div>

          {isArchiveLoading ? (
            <p className="helper-text">Loading archives...</p>
          ) : archives.length === 0 ? (
            <p className="helper-text">No archives have been created yet.</p>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Archive</th>
                  <th>Created</th>
                  <th>Upload</th>
                  <th>Counts</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {archives.map((archive) => (
                  <tr key={archive.id}>
                    <td>{archive.filename}</td>
                    <td>{formatDateTime(archive.created_at)}</td>
                    <td>Upload #{archive.upload_id}</td>
                    <td>
                      {archive.measurement_count.toLocaleString()} M / {archive.nibp_event_count.toLocaleString()} N
                    </td>
                    <td>
                      <button
                        type="button"
                        className="chip"
                        onClick={() => void handleDownloadArchive(archive.id)}
                        disabled={downloadingArchiveId === archive.id}
                      >
                        {downloadingArchiveId === archive.id ? "Downloading..." : "Download"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>
    </div>
  );
}
