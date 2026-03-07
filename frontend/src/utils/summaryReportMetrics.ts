import { Channel, NibpEvent } from "../types/api";
import { nibpValueKeyFromChannelIndex } from "./reportMetrics";

export type SummaryMetricId = "spo2" | "heart_rate" | "nibp";

export interface SummaryMetricDefinition {
  id: SummaryMetricId;
  label: string;
}

export const summaryMetricDefinitions: SummaryMetricDefinition[] = [
  { id: "spo2", label: "SpO2" },
  { id: "heart_rate", label: "Heart Rate" },
  { id: "nibp", label: "NIBP (Blood Pressure)" },
];

interface TrendRule {
  metric: Exclude<SummaryMetricId, "nibp">;
  patterns: RegExp[];
}

interface NibpRule {
  key: "systolic" | "map" | "diastolic";
  patterns: RegExp[];
  fallbackChannelIndex: number;
}

const trendRules: TrendRule[] = [
  { metric: "spo2", patterns: [/spo2/, /oxygen[_\s-]*(sat|saturation)/] },
  { metric: "heart_rate", patterns: [/heart[_\s-]*rate/, /pulse[_\s-]*rate/, /(^|[_\s-])hr([_\s-]|$)/, /pulse/] },
];

const nibpRules: NibpRule[] = [
  { key: "systolic", patterns: [/systolic/], fallbackChannelIndex: 14 },
  { key: "map", patterns: [/\bmap\b/, /mean[_\s-]*arterial/, /mean/], fallbackChannelIndex: 15 },
  { key: "diastolic", patterns: [/diastolic/], fallbackChannelIndex: 16 },
];

export interface ResolvedSummaryMetrics {
  trendByMetric: Partial<Record<Exclude<SummaryMetricId, "nibp">, Channel>>;
  nibpChannels: Partial<Record<"systolic" | "map" | "diastolic", Channel>>;
  nibpValueKeys: {
    systolic?: string;
    map?: string;
    diastolic?: string;
  };
}

interface SummaryInferredNibpReading {
  systolic: number | null;
  mean: number | null;
  diastolic: number | null;
}

function isBetterCandidate(next: Channel, current: Channel | null): boolean {
  if (current === null) {
    return true;
  }
  if (next.valid_count !== current.valid_count) {
    return next.valid_count > current.valid_count;
  }
  return next.channel_index < current.channel_index;
}

function pickByPatterns(channels: Channel[], patterns: RegExp[], excludedIds = new Set<number>()): Channel | null {
  let best: Channel | null = null;
  for (const channel of channels) {
    if (excludedIds.has(channel.id)) {
      continue;
    }

    const name = channel.name.toLowerCase();
    if (!patterns.some((pattern) => pattern.test(name))) {
      continue;
    }
    if (isBetterCandidate(channel, best)) {
      best = channel;
    }
  }
  return best;
}

export function resolveSummaryMetrics(channels: Channel[]): ResolvedSummaryMetrics {
  const trendChannels = channels.filter((channel) => channel.source_type === "trend" && channel.valid_count > 0);
  const nibpChannels = channels.filter((channel) => channel.source_type === "nibp" && channel.valid_count > 0);

  const trendByMetric: Partial<Record<Exclude<SummaryMetricId, "nibp">, Channel>> = {};
  const usedTrendIds = new Set<number>();

  for (const rule of trendRules) {
    const match = pickByPatterns(trendChannels, rule.patterns, usedTrendIds);
    if (!match) {
      continue;
    }
    trendByMetric[rule.metric] = match;
    usedTrendIds.add(match.id);
  }

  const resolvedNibpChannels: ResolvedSummaryMetrics["nibpChannels"] = {};
  const nibpValueKeys: ResolvedSummaryMetrics["nibpValueKeys"] = {};
  const usedNibpIds = new Set<number>();

  for (const rule of nibpRules) {
    let channel = pickByPatterns(nibpChannels, rule.patterns, usedNibpIds);
    if (!channel) {
      channel = nibpChannels.find((candidate) => candidate.channel_index === rule.fallbackChannelIndex) ?? null;
    }
    if (!channel) {
      continue;
    }

    usedNibpIds.add(channel.id);
    resolvedNibpChannels[rule.key] = channel;
    const valueKey = nibpValueKeyFromChannelIndex(channel.channel_index);
    if (valueKey) {
      nibpValueKeys[rule.key] = valueKey;
    }
  }

  return { trendByMetric, nibpChannels: resolvedNibpChannels, nibpValueKeys };
}

export function resolveSummaryNibpValue(
  channelValues: Record<string, number | null>,
  channel: Channel | undefined,
): number | null {
  if (!channel) {
    return null;
  }

  const namedValue = channelValues[channel.name];
  if (typeof namedValue === "number") {
    return namedValue;
  }

  const valueKey = nibpValueKeyFromChannelIndex(channel.channel_index);
  if (!valueKey) {
    return null;
  }

  const inferredValue = channelValues[valueKey];
  return typeof inferredValue === "number" ? inferredValue : null;
}

function resolvePositiveNumber(channelValues: Record<string, number | null>, keys: string[]): number | null {
  for (const key of keys) {
    const value = channelValues[key];
    if (typeof value === "number" && Number.isFinite(value) && value > 0) {
      return value;
    }
  }
  return null;
}

export function resolveSummaryInferredNibpReading(
  channelValues: Record<string, number | null>,
  channels: ResolvedSummaryMetrics["nibpChannels"],
): SummaryInferredNibpReading {
  const systolic = resolvePositiveNumber(channelValues, ["bp_systolic_inferred"])
    ?? resolveSummaryNibpValue(channelValues, channels.systolic);
  const diastolic = resolvePositiveNumber(channelValues, ["bp_diastolic_inferred"])
    ?? resolveSummaryNibpValue(channelValues, channels.diastolic);
  const rawMean = resolvePositiveNumber(channelValues, ["bp_mean_inferred", "bp_map_inferred"])
    ?? resolveSummaryNibpValue(channelValues, channels.map);

  const validSystolic = typeof systolic === "number" && Number.isFinite(systolic) && systolic > 0 ? systolic : null;
  const validDiastolic = typeof diastolic === "number" && Number.isFinite(diastolic) && diastolic > 0 ? diastolic : null;
  const validMean = typeof rawMean === "number" && Number.isFinite(rawMean) && rawMean > 0 ? rawMean : null;

  return {
    systolic: validSystolic,
    mean: validMean ?? (
      validSystolic !== null && validDiastolic !== null && validSystolic >= validDiastolic
        ? Math.round(validDiastolic + (validSystolic - validDiastolic) / 3)
        : null
    ),
    diastolic: validDiastolic,
  };
}

export function buildSummaryNibpSeries(
  events: NibpEvent[],
  channels: ResolvedSummaryMetrics["nibpChannels"],
): Array<{
  name: string;
  data: Array<[string, number]>;
  color: string;
  presentation: "connected-points";
}> {
  const systolicData: Array<[string, number]> = [];
  const meanData: Array<[string, number]> = [];
  const diastolicData: Array<[string, number]> = [];

  for (const event of events) {
    const reading = resolveSummaryInferredNibpReading(event.channel_values, channels);
    const systolicValue = reading.systolic;
    const diastolicValue = reading.diastolic;
    if (systolicValue === null || diastolicValue === null) {
      continue;
    }
    if (systolicValue < diastolicValue) {
      continue;
    }

    systolicData.push([event.timestamp, systolicValue]);
    if (reading.mean !== null) {
      meanData.push([event.timestamp, reading.mean]);
    }
    diastolicData.push([event.timestamp, diastolicValue]);
  }

  const series: Array<{
    name: string;
    data: Array<[string, number]>;
    color: string;
    presentation: "connected-points";
  }> = [
    { name: "Systolic Pressure", data: systolicData, color: "#1D4ED8", presentation: "connected-points" },
    { name: "Mean Pressure", data: meanData, color: "#2563EB", presentation: "connected-points" },
    { name: "Diastolic Pressure", data: diastolicData, color: "#3B82F6", presentation: "connected-points" },
  ];

  return series.filter((entry) => entry.data.length > 0);
}
