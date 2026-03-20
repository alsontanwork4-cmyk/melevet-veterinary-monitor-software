// @vitest-environment jsdom

import { act } from "react";
import { createRoot, Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { PatientsPage } from "./PatientsPage";
import type { Encounter, PaginatedPatientList, PatientWithUploadCount } from "../types/api";
import {
  deleteUpload,
  deletePatient,
  getEncounterChannels,
  getEncounterMeasurements,
  getEncounterNibpEvents,
  listPatientAvailableReportDates,
  listPatientEncounters,
  listPatientSpecies,
  listPatientUploads,
  listPatients,
} from "../api/endpoints";

vi.mock("../api/endpoints", () => ({
  deleteUpload: vi.fn(),
  deletePatient: vi.fn(),
  getEncounterChannels: vi.fn(),
  getEncounterMeasurements: vi.fn(),
  getEncounterNibpEvents: vi.fn(),
  listPatientAvailableReportDates: vi.fn(),
  listPatientEncounters: vi.fn(),
  listPatientSpecies: vi.fn(),
  listPatientUploads: vi.fn(),
  listPatients: vi.fn(),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => vi.fn(),
  };
});

vi.mock("../components/patients/PatientList", () => ({
  PatientList: ({
    patients,
    page,
    totalPages,
    totalCount,
    selectedPatientId,
    onDeletePatient,
    onPageChange,
  }: {
    patients: PatientWithUploadCount[];
    page: number;
    totalPages: number;
    totalCount: number;
    selectedPatientId: number | null;
    onDeletePatient: (patientId: number) => void;
    onPageChange: (page: number) => void;
  }) => (
    <div>
      <div data-testid="selected-patient">{selectedPatientId ?? "none"}</div>
      <div data-testid="page-info">{`Page ${page} of ${totalPages}`}</div>
      <div data-testid="patient-summary">{`Showing ${patients.length} of ${totalCount} patients`}</div>
      <button type="button" onClick={() => onPageChange(page - 1)} disabled={page <= 1}>
        Previous
      </button>
      <button type="button" onClick={() => onPageChange(page + 1)} disabled={page >= totalPages}>
        Next
      </button>
      {patients.map((patient) => (
        <div key={patient.id}>
          <span>{patient.name}</span>
          <button type="button" onClick={() => onDeletePatient(patient.id)}>
            Delete {patient.name}
          </button>
        </div>
      ))}
    </div>
  ),
}));

vi.mock("../components/patients/NewPatientModal", () => ({
  NewPatientModal: () => null,
}));

vi.mock("../components/patients/EditPatientModal", () => ({
  EditPatientModal: () => null,
}));

const { patientVitalChartMock } = vi.hoisted(() => ({
  patientVitalChartMock: vi.fn(() => null),
}));

vi.mock("../components/patients/PatientVitalChart", () => ({
  PatientVitalChart: patientVitalChartMock,
}));

const mockedListPatients = vi.mocked(listPatients);
const mockedDeleteUpload = vi.mocked(deleteUpload);
const mockedDeletePatient = vi.mocked(deletePatient);
const mockedListPatientEncounters = vi.mocked(listPatientEncounters);
const mockedListPatientUploads = vi.mocked(listPatientUploads);
const mockedListPatientSpecies = vi.mocked(listPatientSpecies);
const mockedGetEncounterChannels = vi.mocked(getEncounterChannels);
const mockedGetEncounterMeasurements = vi.mocked(getEncounterMeasurements);
const mockedGetEncounterNibpEvents = vi.mocked(getEncounterNibpEvents);
const mockedListPatientAvailableReportDates = vi.mocked(listPatientAvailableReportDates);

let container: HTMLDivElement;
let root: Root;

function buildPatient(id: number, name: string, overrides: Partial<PatientWithUploadCount> = {}): PatientWithUploadCount {
  return {
    id,
    patient_id_code: `PT-${id}`,
    name,
    species: "Dog",
    age: "2",
    owner_name: "Tan",
    notes: "Gender: Male",
    preferred_encounter_id: null,
    created_at: "2026-03-07T00:00:00Z",
    upload_count: 1,
    last_upload_time: "2026-03-07T00:00:00Z",
    latest_report_date: "2026-03-07",
    report_date: "2026-03-07",
    ...overrides,
  };
}

function buildPaginated(items: PatientWithUploadCount[], total = items.length): PaginatedPatientList {
  return {
    items,
    total,
  };
}

async function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
      mutations: {
        retry: false,
      },
    },
  });

  await act(async () => {
    root.render(
      <QueryClientProvider client={queryClient}>
        <PatientsPage />
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

function getButton(label: string) {
  return Array.from(container.querySelectorAll("button")).find((button) => button.textContent?.trim() === label) ?? null;
}

function setInputValue(input: HTMLInputElement, value: string) {
  const valueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  valueSetter?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

beforeEach(() => {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div");
  document.body.innerHTML = "";
  document.body.appendChild(container);
  root = createRoot(container);

  vi.clearAllMocks();
  vi.stubGlobal("confirm", vi.fn(() => true));

  mockedListPatients.mockResolvedValue(buildPaginated([]));
  mockedListPatientSpecies.mockResolvedValue([]);
  mockedListPatientEncounters.mockResolvedValue([]);
  mockedListPatientUploads.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
  mockedGetEncounterChannels.mockResolvedValue([]);
  mockedGetEncounterMeasurements.mockResolvedValue({ encounter_id: 1, points: [] });
  mockedGetEncounterNibpEvents.mockResolvedValue([]);
  mockedListPatientAvailableReportDates.mockResolvedValue([]);
  mockedDeleteUpload.mockResolvedValue({ deleted: true, upload_id: 1 });
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  vi.unstubAllGlobals();
});

describe("PatientsPage delete flow", () => {
  it("removes the deleted patient and clears the selection after a successful delete", async () => {
    const patient = buildPatient(1, "Ruyee");
    mockedListPatients.mockResolvedValueOnce(buildPaginated([patient], 1)).mockResolvedValue(buildPaginated([], 0));
    mockedDeletePatient.mockResolvedValue({ deleted: true, patient_id: patient.id });

    await renderPage();

    await waitFor(() => {
      expect(container.textContent).toContain("Ruyee");
      expect(container.textContent).toContain("Showing 1 of 1 patients");
    });

    const deleteButton = getButton("Delete Ruyee");
    expect(deleteButton).not.toBeNull();

    await act(async () => {
      deleteButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    await waitFor(() => {
      expect(mockedDeletePatient).toHaveBeenCalledWith(patient.id);
      expect(container.textContent).not.toContain("Ruyee");
      expect(container.textContent).toContain("No patients yet");
      expect(container.textContent).toContain("Select a patient from the left panel");
    });
  });

  it("shows backend error detail when delete fails", async () => {
    const patient = buildPatient(2, "Kitty");
    mockedListPatients.mockResolvedValue(buildPaginated([patient], 1));
    mockedDeletePatient.mockRejectedValue({
      isAxiosError: true,
      response: {
        data: {
          detail: "Patient delete failed on server",
        },
      },
    });

    await renderPage();

    await waitFor(() => {
      expect(container.textContent).toContain("Kitty");
    });

    const deleteButton = getButton("Delete Kitty");
    expect(deleteButton).not.toBeNull();

    await act(async () => {
      deleteButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    await waitFor(() => {
      expect(mockedDeletePatient).toHaveBeenCalledWith(patient.id);
      expect(container.textContent).toContain("Patient delete failed on server");
      expect(container.textContent).toContain("Kitty");
    });
  });
});

describe("PatientsPage server-side filters and pagination", () => {
  it("loads species options into the filter panel", async () => {
    mockedListPatients.mockResolvedValue(buildPaginated([buildPatient(1, "Ruyee")], 1));
    mockedListPatientSpecies.mockResolvedValue(["Cat", "Dog"]);

    await renderPage();

    const filterButton = getButton("Filter");
    expect(filterButton).not.toBeNull();

    await act(async () => {
      filterButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    await waitFor(() => {
      expect(container.textContent).toContain("Cat");
      expect(container.textContent).toContain("Dog");
    });
  });

  it("applies filters through the backend query params", async () => {
    mockedListPatients
      .mockResolvedValueOnce(
        buildPaginated([
          buildPatient(1, "Alpha", { species: "Dog", owner_name: "Lee", notes: "Gender: Male", age: "12" }),
          buildPatient(2, "Bella", { species: "Rabbit", owner_name: "Tan", notes: "Gender: Female", age: "2" }),
        ], 2),
      )
      .mockResolvedValue(buildPaginated([buildPatient(2, "Bella", { species: "Rabbit", owner_name: "Tan", notes: "Gender: Female", age: "2", created_at: "2026-03-08T00:00:00Z" })], 1));
    mockedListPatientSpecies.mockResolvedValue(["Dog", "Rabbit"]);

    await renderPage();

    await waitFor(() => {
      expect(container.textContent).toContain("Alpha");
      expect(container.textContent).toContain("Bella");
    });

    const filterButton = getButton("Filter");
    expect(filterButton).not.toBeNull();

    await act(async () => {
      filterButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const selects = Array.from(container.querySelectorAll("select"));
    const inputs = Array.from(container.querySelectorAll("input"));
    const startDateInput = inputs.find((input) => input.getAttribute("type") === "date" && input.parentElement?.textContent?.includes("Start Date"));
    const endDateInput = inputs.find((input) => input.getAttribute("type") === "date" && input.parentElement?.textContent?.includes("End Date"));
    const speciesSelect = selects.find((select) => select.parentElement?.textContent?.includes("Species"));
    const genderSelect = selects.find((select) => select.parentElement?.textContent?.includes("Gender"));
    const clientNameInput = inputs.find((input) => input.getAttribute("placeholder") === "Filter client name");
    const patientNameInput = inputs.find((input) => input.getAttribute("placeholder") === "Filter patient name");
    const ageInput = inputs.find((input) => input.getAttribute("placeholder") === "Filter age");

    expect(startDateInput).not.toBeNull();
    expect(endDateInput).not.toBeNull();
    expect(speciesSelect).not.toBeNull();
    expect(genderSelect).not.toBeNull();
    expect(clientNameInput).not.toBeNull();
    expect(patientNameInput).not.toBeNull();
    expect(ageInput).not.toBeNull();

    await act(async () => {
      speciesSelect!.value = "Rabbit";
      speciesSelect!.dispatchEvent(new Event("change", { bubbles: true }));
      genderSelect!.value = "Female";
      genderSelect!.dispatchEvent(new Event("change", { bubbles: true }));
      setInputValue(clientNameInput as HTMLInputElement, "tan");
      setInputValue(patientNameInput as HTMLInputElement, "bell");
      setInputValue(ageInput as HTMLInputElement, "2");
      setInputValue(startDateInput as HTMLInputElement, "2026-03-08");
      setInputValue(endDateInput as HTMLInputElement, "2026-03-08");
    });

    const applyButton = getButton("Apply");
    expect(applyButton).not.toBeNull();

    await act(async () => {
      applyButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    await waitFor(() => {
      expect(mockedListPatients).toHaveBeenLastCalledWith(
        expect.objectContaining({
          limit: 50,
          offset: 0,
          species: "Rabbit",
          owner_name: "tan",
          patient_name: "bell",
          gender: "Female",
          age: "2",
          created_from: "2026-03-08",
          created_to: "2026-03-08",
        }),
      );
      expect(container.textContent).toContain("Bella");
      expect(container.textContent).not.toContain("Alpha");
    });
  });

  it("moves to the next page using backend pagination params", async () => {
    mockedListPatients
      .mockResolvedValueOnce(buildPaginated([buildPatient(1, "Alpha")], 60))
      .mockResolvedValue(buildPaginated([buildPatient(2, "Bella")], 60));

    await renderPage();

    await waitFor(() => {
      expect(container.querySelector("[data-testid='page-info']")?.textContent).toBe("Page 1 of 2");
      expect(container.textContent).toContain("Alpha");
    });

    const nextButton = getButton("Next");
    expect(nextButton).not.toBeNull();

    await act(async () => {
      nextButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    await waitFor(() => {
      expect(mockedListPatients).toHaveBeenLastCalledWith(expect.objectContaining({ limit: 50, offset: 50 }));
      expect(container.querySelector("[data-testid='page-info']")?.textContent).toBe("Page 2 of 2");
      expect(container.textContent).toContain("Bella");
    });
  });

  it("resets pagination back to page one when filters change", async () => {
    mockedListPatients
      .mockResolvedValueOnce(buildPaginated([buildPatient(1, "Alpha")], 60))
      .mockResolvedValueOnce(buildPaginated([buildPatient(2, "Bravo")], 60))
      .mockResolvedValue(buildPaginated([buildPatient(3, "Coco", { species: "Rabbit" })], 1));
    mockedListPatientSpecies.mockResolvedValue(["Dog", "Rabbit"]);

    await renderPage();

    await waitFor(() => {
      expect(container.querySelector("[data-testid='page-info']")?.textContent).toBe("Page 1 of 2");
    });

    await act(async () => {
      getButton("Next")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    await waitFor(() => {
      expect(container.querySelector("[data-testid='page-info']")?.textContent).toBe("Page 2 of 2");
      expect(container.textContent).toContain("Bravo");
    });

    await act(async () => {
      getButton("Filter")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const speciesSelect = Array.from(container.querySelectorAll("select")).find((select) => select.parentElement?.textContent?.includes("Species"));
    expect(speciesSelect).not.toBeNull();

    await act(async () => {
      speciesSelect!.value = "Rabbit";
      speciesSelect!.dispatchEvent(new Event("change", { bubbles: true }));
      getButton("Apply")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    await waitFor(() => {
      expect(mockedListPatients).toHaveBeenLastCalledWith(
        expect.objectContaining({
          limit: 50,
          offset: 0,
          species: "Rabbit",
        }),
      );
      expect(container.querySelector("[data-testid='page-info']")?.textContent).toBe("Page 1 of 1");
      expect(container.textContent).toContain("Coco");
    });
  });
});

function buildEncounter(id = 41): Encounter {
  return {
    id,
    patient_id: 1,
    upload_id: 91,
    encounter_date_local: "2026-03-07",
    timezone: "Asia/Singapore",
    label: "Saved encounter",
    notes: null,
    trend_frames: 4,
    nibp_frames: 0,
    archived_at: null,
    archive_id: null,
    day_start_utc: "2026-03-06T16:00:00.000Z",
    day_end_utc: "2026-03-07T15:59:59.999Z",
    created_at: "2026-03-07T00:00:00.000Z",
    updated_at: "2026-03-07T00:00:00.000Z",
  };
}

describe("PatientsPage UTC chart wiring", () => {
  it("does not pass the selected encounter timezone into patient summary charts", async () => {
    mockedListPatients.mockResolvedValue(buildPaginated([buildPatient(1, "Ruyee")], 1));
    mockedListPatientEncounters.mockResolvedValue([buildEncounter()]);
    mockedGetEncounterChannels.mockResolvedValue([
      {
        id: 101,
        upload_id: 91,
        source_type: "trend",
        channel_index: 1,
        name: "Heart Rate",
        unit: "bpm",
        valid_count: 4,
      },
    ]);
    mockedGetEncounterMeasurements.mockResolvedValue({
      encounter_id: 41,
      points: [
        {
          timestamp: "2026-03-07T04:20:00.000Z",
          channel_id: 101,
          channel_name: "Heart Rate",
          value: 122,
        },
      ],
    });

    await renderPage();

    await waitFor(() => {
      expect(patientVitalChartMock).toHaveBeenCalled();
    });

    const sawTimezoneProp = patientVitalChartMock.mock.calls.some((call: any[]) => "timezone" in (call[0] ?? {}));
    expect(sawTimezoneProp).toBe(false);
  });
});
