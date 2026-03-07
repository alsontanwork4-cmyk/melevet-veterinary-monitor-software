import { describe, expect, it } from "vitest";

import { Channel } from "../types/api";
import { resolveReportMetrics } from "./reportMetrics";

function makeChannel(
  id: number,
  sourceType: "trend" | "nibp",
  channelIndex: number,
  name: string,
  validCount = 100,
): Channel {
  return {
    id,
    upload_id: 1,
    source_type: sourceType,
    channel_index: channelIndex,
    name,
    unit: sourceType === "nibp" ? "mmHg" : null,
    valid_count: validCount,
  };
}

describe("resolveReportMetrics", () => {
  it("matches underscore-delimited trend channel names", () => {
    const channels: Channel[] = [
      makeChannel(1, "trend", 16, "heart_rate_be_u16"),
      makeChannel(2, "trend", 14, "spo2_be_u16"),
    ];

    const resolved = resolveReportMetrics(channels);

    expect(resolved.coreTrendByMetric.heart_rate?.name).toBe("heart_rate_be_u16");
    expect(resolved.coreTrendByMetric.spo2?.name).toBe("spo2_be_u16");
    expect(resolved.defaultTrendChannelIds).toEqual([1, 2]);
    expect(resolved.usedTrendFallback).toBe(false);
  });

  it("does not fall back to raw trend offsets when core trend metrics are absent", () => {
    const channels: Channel[] = [
      makeChannel(10, "trend", 0, "trend_raw_be_u16_o00"),
      makeChannel(11, "trend", 1, "trend_raw_be_u16_o02"),
    ];

    const resolved = resolveReportMetrics(channels);

    expect(resolved.coreTrendByMetric.heart_rate).toBeUndefined();
    expect(resolved.coreTrendByMetric.spo2).toBeUndefined();
    expect(resolved.defaultTrendChannelIds).toEqual([]);
    expect(resolved.usedTrendFallback).toBe(false);
  });

  it("maps NIBP keys to inferred storage fields", () => {
    const channels: Channel[] = [
      makeChannel(20, "nibp", 14, "bp_systolic_inferred"),
      makeChannel(21, "nibp", 15, "bp_mean_inferred"),
      makeChannel(22, "nibp", 16, "bp_diastolic_inferred"),
    ];

    const resolved = resolveReportMetrics(channels);

    expect(resolved.nibpValueKeys.systolic).toBe("bp_systolic_inferred");
    expect(resolved.nibpValueKeys.map).toBe("bp_mean_inferred");
    expect(resolved.nibpValueKeys.diastolic).toBe("bp_diastolic_inferred");
  });
});
