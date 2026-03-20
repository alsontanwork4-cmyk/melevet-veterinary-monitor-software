// @vitest-environment jsdom

import { act } from "react";
import { createRoot, Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ReportPage } from "./ReportPage";
import type { Channel, Encounter, EncounterMeasurementsResponse, NibpEvent, Patient } from "../types/api";
import {
  getEncounter,
  getEncounterChannels,
  getEncounterMeasurements,
  getEncounterNibpEvents,
  getPatient,
} from "../api/endpoints";

vi.mock("../api/endpoints", () => ({
  getEncounter: vi.fn(),
  getEncounterChannels: vi.fn(),
  getEncounterMeasurements: vi.fn(),
  getEncounterNibpEvents: vi.fn(),
  getPatient: vi.fn(),
}));

const { summaryTrendChartMock } = vi.hoisted(() => ({
  summaryTrendChartMock: vi.fn(() => <div data-testid="summary-trend-chart">Mock Chart</div>),
}));

vi.mock("../components/report/SummaryTrendChart", () => ({
  SummaryTrendChart: summaryTrendChartMock,
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    Link: ({ children, to }: { children: React.ReactNode; to: string }) => <a href={to}>{children}</a>,
    useParams: () => ({ encounterId: "7" }),
  };
});

const mockedGetEncounter = vi.mocked(getEncounter);
const mockedGetPatient = vi.mocked(getPatient);
const mockedGetEncounterChannels = vi.mocked(getEncounterChannels);
const mockedGetEncounterMeasurements = vi.mocked(getEncounterMeasurements);
const mockedGetEncounterNibpEvents = vi.mocked(getEncounterNibpEvents);

let container: HTMLDivElement;
let root: Root;

function buildEncounter(): Encounter {
  return {
    id: 7,
    patient_id: 12,
    upload_id: 30,
    encounter_date_local: "2026-02-06",
    timezone: "Asia/Singapore",
    label: "Encounter 2026-02-06",
    notes: null,
    trend_frames: 5,
    nibp_frames: 0,
    archived_at: null,
    archive_id: null,
    day_start_utc: "2026-02-05T16:00:00.000Z",
    day_end_utc: "2026-02-06T15:59:59.999Z",
    created_at: "2026-02-06T00:00:00.000Z",
    updated_at: "2026-02-06T00:00:00.000Z",
  };
}

function buildChannels(): Channel[] {
  return [
    {
      id: 101,
      upload_id: 30,
      source_type: "trend",
      channel_index: 1,
      name: "SpO2",
      unit: "%",
      valid_count: 5,
    },
  ];
}

function buildMeasurements(): EncounterMeasurementsResponse {
  return {
    encounter_id: 7,
    points: [
      {
        timestamp: "2026-02-06T05:00:00.000Z",
        channel_id: 101,
        channel_name: "SpO2",
        value: 99,
      },
    ],
  };
}

async function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  await act(async () => {
    root.render(
      <QueryClientProvider client={queryClient}>
        <ReportPage />
      </QueryClientProvider>,
    );
  });
}

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

  mockedGetEncounter.mockResolvedValue(buildEncounter());
  mockedGetEncounterChannels.mockResolvedValue(buildChannels());
  mockedGetEncounterMeasurements.mockResolvedValue(buildMeasurements());
  mockedGetEncounterNibpEvents.mockResolvedValue([] as NibpEvent[]);
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
});

describe("ReportPage patient details header", () => {
  it("renders patient details above the charts and strips structured note lines from the notes body", async () => {
    mockedGetPatient.mockResolvedValue({
      id: 12,
      patient_id_code: "PT-12",
      name: "awd",
      species: "Rabbit",
      age: "4 years",
      breed: null,
      weight_kg: null,
      owner_name: "Alice Tan",
      notes: "Gender: Female\nTel: 91234567\nMonitor during recovery.",
      preferred_encounter_id: null,
      created_at: "2026-02-01T00:00:00.000Z",
      updated_at: "2026-02-01T00:00:00.000Z",
    } satisfies Patient);

    await renderPage();

    await waitFor(() => {
      expect(container.textContent).toContain("Patient Details");
      expect(container.textContent).toContain("Mock Chart");
    });

    expect(container.textContent).toContain("PT-12");
    expect(container.textContent).toContain("Alice Tan");
    expect(container.textContent).toContain("awd");
    expect(container.textContent).toContain("Rabbit");
    expect(container.textContent).toContain("Female");
    expect(container.textContent).toContain("4 years");
    expect(container.textContent).toContain("91234567");
    expect(container.textContent).toContain("Monitor during recovery.");
    expect(container.textContent).not.toContain("Gender: Female");
    expect(container.textContent).not.toContain("Tel: 91234567");

    const patientDetailsHeading = Array.from(container.querySelectorAll("h2")).find(
      (element) => element.textContent === "Patient Details",
    );
    const chart = container.querySelector('[data-testid="summary-trend-chart"]');

    expect(patientDetailsHeading).not.toBeNull();
    expect(chart).not.toBeNull();
    expect(
      patientDetailsHeading!.compareDocumentPosition(chart!) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).not.toBe(0);
  });

  it("shows fallback values when patient metadata is missing", async () => {
    mockedGetPatient.mockResolvedValue({
      id: 12,
      patient_id_code: "",
      name: "Buddy",
      species: "Dog",
      age: null,
      breed: null,
      weight_kg: null,
      owner_name: null,
      notes: "",
      preferred_encounter_id: null,
      created_at: "2026-02-01T00:00:00.000Z",
      updated_at: "2026-02-01T00:00:00.000Z",
    } satisfies Patient);

    await renderPage();

    await waitFor(() => {
      expect(container.textContent).toContain("Patient Details");
    });

    const detailValues = Array.from(container.querySelectorAll(".patient-detail-value, .patient-detail-notes-body")).map(
      (element) => element.textContent?.trim(),
    );

    expect(detailValues).toContain("-");
    expect(container.textContent).toContain("Buddy");
    expect(container.textContent).toContain("Dog");
    expect(container.textContent).toContain("Mock Chart");
  });

  it("does not pass the encounter timezone into the summary trend chart", async () => {
    mockedGetPatient.mockResolvedValue({
      id: 12,
      patient_id_code: "PT-12",
      name: "awd",
      species: "Rabbit",
      age: "4 years",
      breed: null,
      weight_kg: null,
      owner_name: "Alice Tan",
      notes: "",
      preferred_encounter_id: null,
      created_at: "2026-02-01T00:00:00.000Z",
      updated_at: "2026-02-01T00:00:00.000Z",
    } satisfies Patient);

    await renderPage();

    await waitFor(() => {
      expect(summaryTrendChartMock).toHaveBeenCalled();
    });

    const sawTimezoneProp = summaryTrendChartMock.mock.calls.some((call: any[]) => "timezone" in (call[0] ?? {}));
    expect(sawTimezoneProp).toBe(false);
  });
});







