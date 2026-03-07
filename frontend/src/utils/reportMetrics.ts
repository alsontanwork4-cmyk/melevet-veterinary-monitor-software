import { Channel } from "../types/api";

export type CoreTrendMetric = "heart_rate" | "spo2";
export type CoreNibpMetric = "systolic" | "map" | "diastolic";

interface TrendMetricRule {
  key: CoreTrendMetric;
  label: string;
  patterns: RegExp[];
}

interface NibpMetricRule {
  key: CoreNibpMetric;
  patterns: RegExp[];
  fallbackChannelIndex: number;
  valueKey: string;
}

const trendMetricRules: TrendMetricRule[] = [
  {
    key: "heart_rate",
    label: "Heart rate / pulse",
    patterns: [/heart[_\s-]*rate/, /pulse[_\s-]*rate/, /pulse/, /(^|[_\s-])hr([_\s-]|$)/],
  },
  {
    key: "spo2",
    label: "SpO2",
    patterns: [/spo2/, /oxygen[_\s-]*(sat|saturation)/],
  },
];

const nibpMetricRules: NibpMetricRule[] = [
  {
    key: "systolic",
    patterns: [/systolic/],
    fallbackChannelIndex: 14,
    valueKey: "bp_systolic_inferred",
  },
  {
    key: "map",
    patterns: [/(^|[_\s-])map([_\s-]|$)/, /mean[_\s-]*arterial/, /mean/],
    fallbackChannelIndex: 15,
    valueKey: "bp_mean_inferred",
  },
  {
    key: "diastolic",
    patterns: [/diastolic/],
    fallbackChannelIndex: 16,
    valueKey: "bp_diastolic_inferred",
  },
];

export interface ResolvedReportMetrics {
  defaultTrendChannelIds: number[];
  coreTrendChannels: Channel[];
  coreTrendByMetric: Partial<Record<CoreTrendMetric, Channel>>;
  missingTrendMetricLabels: string[];
  usedTrendFallback: boolean;
  nibpChannels: Partial<Record<CoreNibpMetric, Channel>>;
  nibpValueKeys: Partial<Record<CoreNibpMetric, string>>;
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

function pickBestMatch(
  channels: Channel[],
  patterns: RegExp[],
  excludedIds: Set<number> = new Set<number>(),
): Channel | null {
  let best: Channel | null = null;

  for (const channel of channels) {
    if (excludedIds.has(channel.id)) {
      continue;
    }
    const normalizedName = channel.name.toLowerCase();
    if (!patterns.some((pattern) => pattern.test(normalizedName))) {
      continue;
    }
    if (isBetterCandidate(channel, best)) {
      best = channel;
    }
  }

  return best;
}

export function nibpValueKeyFromChannelIndex(channelIndex: number): string | null {
  switch (channelIndex) {
    case 14:
      return "bp_systolic_inferred";
    case 15:
      return "bp_mean_inferred";
    case 16:
      return "bp_diastolic_inferred";
    default:
      return null;
  }
}

export const nibpRawKeyFromChannelIndex = nibpValueKeyFromChannelIndex;

export function resolveReportMetrics(channels: Channel[]): ResolvedReportMetrics {
  const trendChannels = channels.filter((channel) => channel.source_type === "trend" && channel.valid_count > 0);
  const nibpChannels = channels.filter((channel) => channel.source_type === "nibp" && channel.valid_count > 0);

  const usedTrendChannelIds = new Set<number>();
  const coreTrendChannels: Channel[] = [];
  const coreTrendByMetric: Partial<Record<CoreTrendMetric, Channel>> = {};
  const missingTrendMetricLabels: string[] = [];

  for (const metric of trendMetricRules) {
    const match = pickBestMatch(trendChannels, metric.patterns, usedTrendChannelIds);
    if (match) {
      coreTrendChannels.push(match);
      coreTrendByMetric[metric.key] = match;
      usedTrendChannelIds.add(match.id);
      continue;
    }
    missingTrendMetricLabels.push(metric.label);
  }

  const nibpChannelsByMetric: Partial<Record<CoreNibpMetric, Channel>> = {};
  const nibpValueKeys: Partial<Record<CoreNibpMetric, string>> = {};
  const usedNibpChannelIds = new Set<number>();

  for (const metric of nibpMetricRules) {
    let channel = pickBestMatch(nibpChannels, metric.patterns, usedNibpChannelIds);
    if (channel === null) {
      channel = nibpChannels.find((candidate) => candidate.channel_index === metric.fallbackChannelIndex) ?? null;
    }
    if (channel === null) {
      continue;
    }

    nibpChannelsByMetric[metric.key] = channel;
    nibpValueKeys[metric.key] = metric.valueKey;
    usedNibpChannelIds.add(channel.id);
  }

  return {
    defaultTrendChannelIds: coreTrendChannels.map((channel) => channel.id),
    coreTrendChannels,
    coreTrendByMetric,
    missingTrendMetricLabels,
    usedTrendFallback: false,
    nibpChannels: nibpChannelsByMetric,
    nibpValueKeys,
  };
}
