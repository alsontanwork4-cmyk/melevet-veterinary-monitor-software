import { describe, expect, it } from "vitest";

import { Encounter, PatientWithUploadCount } from "../types/api";
import { getPatientReportDate, resolvePreferredEncounter, sortPatientsByCreatedAt } from "./patientReports";

function buildPatient(overrides: Partial<PatientWithUploadCount>): PatientWithUploadCount {
  return {
    id: 1,
    patient_id_code: "PT-001",
    name: "Kitty",
    species: "cat",
    owner_name: null,
    notes: null,
    preferred_encounter_id: null,
    created_at: "2026-02-01T00:00:00.000Z",
    upload_count: 1,
    last_upload_time: null,
    latest_report_date: null,
    report_date: null,
    ...overrides,
  };
}

function buildEncounter(id: number, encounterDateLocal: string): Encounter {
  return {
    id,
    patient_id: 1,
    upload_id: 1,
    encounter_date_local: encounterDateLocal,
    timezone: "UTC",
    label: null,
    notes: null,
    trend_frames: 0,
    nibp_frames: 0,
    archived_at: null,
    archive_id: null,
    day_start_utc: encounterDateLocal + "T00:00:00.000Z",
    day_end_utc: encounterDateLocal + "T23:59:59.999Z",
    created_at: encounterDateLocal + "T00:00:00.000Z",
    updated_at: encounterDateLocal + "T00:00:00.000Z",
  };
}

describe("getPatientReportDate", () => {
  it("falls back to latest_report_date when report_date is null", () => {
    const patient = buildPatient({ latest_report_date: "2026-02-25", report_date: null });
    expect(getPatientReportDate(patient)).toBe("2026-02-25");
  });
});

describe("sortPatientsByCreatedAt", () => {
  it("sorts by patient creation time and leaves missing timestamps last", () => {
    const patients = [
      buildPatient({ id: 1, name: "Alpha", created_at: "2026-02-24T00:00:00.000Z" }),
      buildPatient({ id: 2, name: "Bravo", created_at: "2026-02-26T00:00:00.000Z" }),
      buildPatient({ id: 3, name: "Charlie", created_at: "" }),
    ];

    expect(sortPatientsByCreatedAt(patients, "desc").map((patient) => patient.id)).toEqual([2, 1, 3]);
    expect(sortPatientsByCreatedAt(patients, "asc").map((patient) => patient.id)).toEqual([1, 2, 3]);
  });
});

describe("resolvePreferredEncounter", () => {
  it("returns the preferred encounter when it exists", () => {
    const encounters = [buildEncounter(11, "2026-02-25"), buildEncounter(10, "2026-02-24")];
    expect(resolvePreferredEncounter(encounters, 10)?.id).toBe(10);
  });

  it("falls back to the newest encounter when the preferred id is missing", () => {
    const encounters = [buildEncounter(11, "2026-02-25"), buildEncounter(10, "2026-02-24")];
    expect(resolvePreferredEncounter(encounters, 999)?.id).toBe(11);
  });
});
