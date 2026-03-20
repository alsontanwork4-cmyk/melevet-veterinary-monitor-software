export interface VitalStats {
  min: number;
  max: number;
  mean: number;
  stdDev: number;
  count: number;
}

export function computeVitalStats(values: number[]): VitalStats | null {
  const finiteValues = values.filter((value) => Number.isFinite(value));
  if (finiteValues.length === 0) {
    return null;
  }

  let min = finiteValues[0];
  let max = finiteValues[0];
  let sum = 0;

  for (const value of finiteValues) {
    if (value < min) {
      min = value;
    }
    if (value > max) {
      max = value;
    }
    sum += value;
  }

  const count = finiteValues.length;
  const mean = sum / count;
  const variance = finiteValues.reduce((accumulator, value) => accumulator + ((value - mean) ** 2), 0) / count;

  return {
    min,
    max,
    mean,
    stdDev: Math.sqrt(variance),
    count,
  };
}
