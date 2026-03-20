// @vitest-environment jsdom

import { act } from "react";
import { createRoot, Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import { SettingsPage } from "./SettingsPage";
import {
  exportTelemetry,
  getDatabaseStats,
  getDatabaseDiagnostics,
  getSettings,
  getTelemetryStatus,
  listArchives,
  runArchival,
  updateSettings,
} from "../api/endpoints";

vi.mock("../api/endpoints", () => ({
  exportTelemetry: vi.fn(),
  getDatabaseStats: vi.fn(),
  getDatabaseDiagnostics: vi.fn(),
  getSettings: vi.fn(),
  getTelemetryStatus: vi.fn(),
  listArchives: vi.fn(),
  runArchival: vi.fn(),
  updateSettings: vi.fn(),
}));

const mockedExportTelemetry = vi.mocked(exportTelemetry);
const mockedGetDatabaseStats = vi.mocked(getDatabaseStats);
const mockedGetDatabaseDiagnostics = vi.mocked(getDatabaseDiagnostics);
const mockedGetSettings = vi.mocked(getSettings);
const mockedGetTelemetryStatus = vi.mocked(getTelemetryStatus);
const mockedListArchives = vi.mocked(listArchives);
const mockedRunArchival = vi.mocked(runArchival);
const mockedUpdateSettings = vi.mocked(updateSettings);

let container: HTMLDivElement;
let root: Root;

async function flushAsyncWork() {
  await act(async () => {
    await new Promise((resolve) => window.setTimeout(resolve, 0));
  });
}

async function waitFor(assertion: () => void) {
  const startedAt = Date.now();
  while (true) {
    try {
      assertion();
      return;
    } catch (error) {
      if (Date.now() - startedAt > 3000) {
        throw error;
      }
      await flushAsyncWork();
    }
  }
}

beforeEach(() => {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div");
  document.body.innerHTML = "";
  document.body.appendChild(container);
  root = createRoot(container);

  vi.clearAllMocks();
  mockedGetSettings.mockResolvedValue({
    archive_retention_days: null,
    link_table_warning_threshold: 1000000,
    log_level: "INFO",
    orphan_upload_retention_days: 7,
    segment_gap_seconds: 600,
    recording_period_gap_seconds: 86400,
    usage_reporting_enabled: false,
    vital_thresholds: {},
  });
  mockedGetDatabaseStats.mockResolvedValue({
    database_kind: "sqlite",
    sqlite_file_size_bytes: 4096,
    live_measurement_count: 12,
    live_nibp_event_count: 5,
    archived_upload_count: 0,
    archive_file_count: 0,
    archive_total_size_bytes: 0,
    oldest_archive_at: null,
    newest_archive_at: null,
  });
  mockedGetDatabaseDiagnostics.mockResolvedValue({
    database_kind: "sqlite",
    sqlite_file_size_bytes: 4096,
    measurement_count: 12,
    upload_measurement_link_count: 34,
    upload_nibp_event_link_count: 5,
    link_table_warning_threshold: 1000000,
    upload_measurement_links_over_threshold: false,
    upload_nibp_event_links_over_threshold: false,
  });
  mockedGetTelemetryStatus.mockResolvedValue({
    usage_reporting_enabled: false,
    queued_event_count: 0,
    queued_size_bytes: 0,
    crash_event_count: 0,
    crash_size_bytes: 0,
  });
  mockedListArchives.mockResolvedValue([]);
  mockedRunArchival.mockResolvedValue({ archived_upload_count: 0, archives: [] });
  mockedExportTelemetry.mockResolvedValue({ blob: new Blob(["events"]), filename: "events.ndjson" });
  mockedUpdateSettings.mockImplementation(async (payload) => ({
    archive_retention_days: payload.archive_retention_days ?? null,
    link_table_warning_threshold: payload.link_table_warning_threshold ?? 1000000,
    log_level: payload.log_level ?? "INFO",
    orphan_upload_retention_days: payload.orphan_upload_retention_days ?? 7,
    segment_gap_seconds: payload.segment_gap_seconds ?? 600,
    recording_period_gap_seconds: payload.recording_period_gap_seconds ?? 86400,
    usage_reporting_enabled: payload.usage_reporting_enabled ?? false,
    vital_thresholds: payload.vital_thresholds ?? {},
  }));
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
});

describe("SettingsPage", () => {
  it("renders database diagnostics and the warning threshold setting", async () => {
    await act(async () => {
      root.render(
        <MemoryRouter>
          <SettingsPage />
        </MemoryRouter>,
      );
    });

    await waitFor(() => {
      expect(container.textContent).toContain("Database Health");
      expect(container.textContent).toContain("SQLite file size");
      expect(container.textContent).toContain("Measurements");
      expect(container.textContent).toContain("Measurement links");
      expect(container.textContent).toContain("Link table warning threshold");
      expect(container.textContent).toContain("4.0 KB");
    });
  });
});
