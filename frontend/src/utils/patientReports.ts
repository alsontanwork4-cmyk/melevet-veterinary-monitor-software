import { Encounter, PatientWithUploadCount } from "../types/api";

export function getPatientReportDate(patient: Pick<PatientWithUploadCount, "report_date" | "latest_report_date">): string | null {
  return patient.report_date ?? patient.latest_report_date ?? null;
}

export function sortPatientsByCreatedAt(
  patients: PatientWithUploadCount[],
  order: "asc" | "desc",
): PatientWithUploadCount[] {
  return [...patients].sort((left, right) => {
    const leftTime = Date.parse(left.created_at);
    const rightTime = Date.parse(right.created_at);
    const leftMissing = Number.isNaN(leftTime);
    const rightMissing = Number.isNaN(rightTime);

    if (leftMissing && rightMissing) {
      return left.name.localeCompare(right.name);
    }
    if (leftMissing) {
      return 1;
    }
    if (rightMissing) {
      return -1;
    }

    return order === "asc" ? leftTime - rightTime : rightTime - leftTime;
  });
}

export function resolvePreferredEncounter(
  encounters: Encounter[] | null | undefined,
  preferredEncounterId: number | null,
): Encounter | null {
  if (!encounters || encounters.length === 0) {
    return null;
  }

  if (preferredEncounterId !== null) {
    const preferred = encounters.find((encounter) => encounter.id === preferredEncounterId);
    if (preferred) {
      return preferred;
    }
  }

  return encounters[0] ?? null;
}
