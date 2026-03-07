// @vitest-environment jsdom

import { act } from "react";
import { createRoot, Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { PatientsPage } from "./PatientsPage";
import type { PatientWithUploadCount } from "../types/api";
import {
  deletePatient,
  getEncounterChannels,
  getEncounterMeasurements,
  getEncounterNibpEvents,
  listPatientAvailableReportDates,
  listPatientEncounters,
  listPatients,
} from "../api/endpoints";


vi.mock("../api/endpoints", () => ({
  deletePatient: vi.fn(),
  getEncounterChannels: vi.fn(),
  getEncounterMeasurements: vi.fn(),
  getEncounterNibpEvents: vi.fn(),
  listPatientAvailableReportDates: vi.fn(),
  listPatientEncounters: vi.fn(),
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
    selectedPatientId,
    onDeletePatient,
    deletingPatientId,
  }: {
    patients: PatientWithUploadCount[];
    selectedPatientId: number | null;
    onDeletePatient: (patientId: number) => void;
    deletingPatientId?: number | null;
  }) => (
    <div>
      <div data-testid="selected-patient">{selectedPatientId ?? "none"}</div>
      {patients.map((patient) => (
        <div key={patient.id}>
          <span>{patient.name}</span>
          <button
            type="button"
            onClick={() => onDeletePatient(patient.id)}
            disabled={deletingPatientId === patient.id}
          >
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

vi.mock("../components/patients/PatientVitalChart", () => ({
  PatientVitalChart: () => null,
}));


const mockedListPatients = vi.mocked(listPatients);
const mockedDeletePatient = vi.mocked(deletePatient);
const mockedListPatientEncounters = vi.mocked(listPatientEncounters);
const mockedGetEncounterChannels = vi.mocked(getEncounterChannels);
const mockedGetEncounterMeasurements = vi.mocked(getEncounterMeasurements);
const mockedGetEncounterNibpEvents = vi.mocked(getEncounterNibpEvents);
const mockedListPatientAvailableReportDates = vi.mocked(listPatientAvailableReportDates);

let container: HTMLDivElement;
let root: Root;

function buildPatient(id: number, name: string): PatientWithUploadCount {
  return {
    id,
    patient_id_code: `PT-${id}`,
    name,
    species: "Dog",
    owner_name: "Tan",
    notes: "Gender: Male",
    preferred_encounter_id: null,
    created_at: "2026-03-07T00:00:00Z",
    upload_count: 1,
    last_upload_time: "2026-03-07T00:00:00Z",
    latest_report_date: "2026-03-07",
    report_date: "2026-03-07",
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

beforeEach(() => {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div");
  document.body.innerHTML = "";
  document.body.appendChild(container);
  root = createRoot(container);

  vi.clearAllMocks();
  vi.stubGlobal("confirm", vi.fn(() => true));

  mockedListPatientEncounters.mockResolvedValue([]);
  mockedGetEncounterChannels.mockResolvedValue([]);
  mockedGetEncounterMeasurements.mockResolvedValue({ encounter_id: 1, points: [] });
  mockedGetEncounterNibpEvents.mockResolvedValue([]);
  mockedListPatientAvailableReportDates.mockResolvedValue([]);
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  vi.unstubAllGlobals();
});

function getDeleteButton(patientName: string) {
  const buttons = Array.from(container.querySelectorAll("button"));
  return buttons.find((button) => button.textContent?.trim() === `Delete ${patientName}`) ?? null;
}

describe("PatientsPage delete flow", () => {
  it("removes the deleted patient and clears the selection after a successful delete", async () => {
    const patient = buildPatient(1, "Ruyee");
    mockedListPatients.mockResolvedValueOnce([patient]).mockResolvedValue([]);
    mockedDeletePatient.mockResolvedValue({ deleted: true, patient_id: patient.id });

    await renderPage();

    await waitFor(() => {
      expect(container.textContent).toContain("Ruyee");
      expect(container.textContent).toContain("1");
    });

    const deleteButton = getDeleteButton("Ruyee");
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
    mockedListPatients.mockResolvedValue([patient]);
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

    const deleteButton = getDeleteButton("Kitty");
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
