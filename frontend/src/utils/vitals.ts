import { NibpEvent } from "../types/api";

type VitalRule = {
  label: string;
  priority: number;
  patterns: RegExp[];
};

const exactLabelMap: Record<string, string> = {
  spo2_be_u16: "SpO2",
  pulse_rate_be_u16: "Heart Rate",
  heart_rate_be_u16: "Heart Rate",
  bp_systolic_inferred: "NIBP (Blood Pressure) Systolic",
  bp_mean_inferred: "NIBP (Blood Pressure) Mean",
  bp_diastolic_inferred: "NIBP (Blood Pressure) Diastolic",
  nibp_systolic_raw: "NIBP (Blood Pressure) Systolic",
  nibp_map_raw: "NIBP (Blood Pressure) MAP",
  nibp_diastolic_raw: "NIBP (Blood Pressure) Diastolic",
  trend_clock_marker: "Clock Marker",
};

const vitalRules: VitalRule[] = [
  {
    label: "Heart Rate",
    priority: 1,
    patterns: [/heart[_\s-]?rate/i, /pulse[_\s-]?rate/i, /\bhr\b/i],
  },
  {
    label: "SpO2",
    priority: 2,
    patterns: [/spo2/i, /spo[_\s-]?2/i],
  },
  {
    label: "NIBP (Blood Pressure) Systolic",
    priority: 3,
    patterns: [/nibp[_\s-]*systolic/i, /blood[_\s-]?pressure[_\s-]*systolic/i, /systolic/i],
  },
  {
    label: "NIBP (Blood Pressure) MAP",
    priority: 4,
    patterns: [/(^|_)map(_|$)/i, /mean[_\s-]?arterial/i],
  },
  {
    label: "NIBP (Blood Pressure) Diastolic",
    priority: 5,
    patterns: [/diastolic/i],
  },
  {
    label: "Temperature",
    priority: 6,
    patterns: [/temp/i, /temperature/i],
  },
  {
    label: "CO2",
    priority: 7,
    patterns: [/etco2/i, /co2/i],
  },
];

function titleCase(input: string): string {
  return input
    .split(" ")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function normalizeChannelName(rawName: string): string {
  return rawName.trim().toLowerCase();
}

function parseChannelOffset(rawName: string, source: "trend" | "nibp"): string | null {
  const normalized = normalizeChannelName(rawName);
  const regex =
    source === "trend" ? /^trend_raw_be_u16_o(\d+)$/i : /^nibp_raw_be_u16_o(\d+)$/i;
  const match = normalized.match(regex);
  return match ? match[1] : null;
}

function firstMatchingRule(rawName: string): VitalRule | null {
  const normalized = normalizeChannelName(rawName);
  for (const rule of vitalRules) {
    if (rule.patterns.some((pattern) => pattern.test(normalized))) {
      return rule;
    }
  }
  return null;
}

export function friendlyChannelName(rawName: string): string {
  const normalized = normalizeChannelName(rawName);
  const exact = exactLabelMap[normalized];
  if (exact) {
    return exact;
  }

  const rule = firstMatchingRule(rawName);
  if (rule) {
    return rule.label;
  }

  const trendOffset = parseChannelOffset(rawName, "trend");
  if (trendOffset) {
    return `Technical Trend Channel ${trendOffset}`;
  }

  const nibpOffset = parseChannelOffset(rawName, "nibp");
  if (nibpOffset) {
    return `Technical NIBP Channel ${nibpOffset}`;
  }

  const cleaned = normalized
    .replace(/_be_u\d+/gi, "")
    .replace(/_raw/gi, "")
    .replace(/_/g, " ")
    .replace(/\s+/g, " ")
    .trim();

  return cleaned.length > 0 ? titleCase(cleaned) : rawName;
}

export function isKeyVitalChannel(rawName: string): boolean {
  return firstMatchingRule(rawName) !== null;
}

export function keyVitalPriority(rawName: string): number {
  const normalized = normalizeChannelName(rawName);
  const exact = exactLabelMap[normalized];
  if (exact) {
    const exactRule = vitalRules.find((rule) => rule.label === exact);
    return exactRule?.priority ?? 999;
  }

  return firstMatchingRule(rawName)?.priority ?? 999;
}

export function channelDisplayLabel(rawName: string, unit?: string | null): string {
  const label = friendlyChannelName(rawName);
  if (!unit || unit.trim().length === 0) {
    return label;
  }
  return `${label} (${unit})`;
}

function toNumeric(value: number | null): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function firstNumericValue(event: NibpEvent): number | null {
  for (const value of Object.values(event.channel_values)) {
    const numeric = toNumeric(value);
    if (numeric !== null) {
      return numeric;
    }
  }
  return null;
}

export interface ParsedNibpReading {
  systolic: number | null;
  map: number | null;
  diastolic: number | null;
  representative: number | null;
  summary: string;
}

export function parseNibpReading(event: NibpEvent): ParsedNibpReading {
  let systolic: number | null = null;
  let map: number | null = null;
  let diastolic: number | null = null;

  for (const [key, rawValue] of Object.entries(event.channel_values)) {
    const value = toNumeric(rawValue);
    if (value === null) {
      continue;
    }
    const normalized = normalizeChannelName(key);

    if (systolic === null && (/systolic/.test(normalized) || /o28\b/.test(normalized))) {
      systolic = value;
    }
    if (map === null && (/(^|_)map(_|$)/.test(normalized) || /mean/.test(normalized) || /o30\b/.test(normalized))) {
      map = value;
    }
    if (diastolic === null && (/diastolic/.test(normalized) || /o32\b/.test(normalized))) {
      diastolic = value;
    }
  }

  const representative = map ?? systolic ?? diastolic ?? firstNumericValue(event);
  const summaryParts: string[] = [];

  if (systolic !== null || diastolic !== null) {
    const systolicText = systolic !== null ? String(Math.round(systolic)) : "?";
    const diastolicText = diastolic !== null ? String(Math.round(diastolic)) : "?";
    summaryParts.push(`${systolicText}/${diastolicText} mmHg`);
  }
  if (map !== null) {
    summaryParts.push(`MAP ${Math.round(map)} mmHg`);
  }
  if (summaryParts.length === 0 && representative !== null) {
    summaryParts.push(`${Math.round(representative)} mmHg`);
  }
  if (summaryParts.length === 0) {
    summaryParts.push("No reading");
  }

  return {
    systolic,
    map,
    diastolic,
    representative,
    summary: summaryParts.join(" | "),
  };
}
