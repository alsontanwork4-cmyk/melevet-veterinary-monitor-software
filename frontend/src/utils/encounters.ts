import { Encounter } from "../types/api";

function parseEncounterDate(value: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) {
    return null;
  }

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (!Number.isFinite(year) || !Number.isFinite(month) || !Number.isFinite(day)) {
    return null;
  }

  return new Date(Date.UTC(year, month - 1, day));
}

export function formatEncounterDateLabel(value: string): string {
  const date = parseEncounterDate(value);
  if (date === null || Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleDateString(undefined, { timeZone: "UTC" });
}

export function encounterDisplayLabel(encounter: Pick<Encounter, "encounter_date_local" | "label">): string {
  const label = encounter.label?.trim();
  return label && label.length > 0 ? label : formatEncounterDateLabel(encounter.encounter_date_local);
}
