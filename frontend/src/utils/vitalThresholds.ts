import type { SpeciesVitalThresholds, VitalThresholdRange } from "../types/api";

export const emptyThresholdRange = (): VitalThresholdRange => ({ low: null, high: null });

export const emptySpeciesThresholds = (): SpeciesVitalThresholds => ({
  spo2: emptyThresholdRange(),
  heart_rate: emptyThresholdRange(),
  nibp_systolic: emptyThresholdRange(),
  nibp_map: emptyThresholdRange(),
  nibp_diastolic: emptyThresholdRange(),
});

export function resolveSpeciesThresholds(
  thresholds: Record<string, SpeciesVitalThresholds>,
  species: string | null | undefined,
): SpeciesVitalThresholds | null {
  const normalizedSpecies = species?.trim().toLowerCase();
  if (!normalizedSpecies) {
    return null;
  }

  const exact = Object.entries(thresholds).find(([key]) => key.trim().toLowerCase() === normalizedSpecies);
  return exact?.[1] ?? null;
}

export function countOutOfRange(values: number[], range: VitalThresholdRange | null | undefined): number {
  if (!range) {
    return 0;
  }
  return values.filter((value) => {
    if (!Number.isFinite(value)) {
      return false;
    }
    if (range.low !== null && value < range.low) {
      return true;
    }
    if (range.high !== null && value > range.high) {
      return true;
    }
    return false;
  }).length;
}
