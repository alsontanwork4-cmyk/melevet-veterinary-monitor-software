import { describe, expect, it } from "vitest";

import { Channel, NibpEvent } from "../types/api";
import {
  buildSummaryNibpSeries,
  resolveSummaryInferredNibpReading,
  resolveSummaryMetrics,
  resolveSummaryNibpValue,
} from "./summaryReportMetrics";

function makeTrendChannel(
  id: number,
  channelIndex: number,
  name: string,
  validCount = 100,
): Channel {
  return {
    id,
    upload_id: 1,
    source_type: "trend",
    channel_index: channelIndex,
    name,
    unit: null,
    valid_count: validCount,
  };
}

function makeNibpChannel(
  id: number,
  channelIndex: number,
  name: string,
  validCount = 100,
): Channel {
  return {
    id,
    upload_id: 1,
    source_type: "nibp",
    channel_index: channelIndex,
    name,
    unit: "mmHg",
    valid_count: validCount,
  };
}

function makeNibpEvent(
  timestamp: string,
  channelValues: Record<string, number | null>,
): NibpEvent {
  return {
    id: 1,
    upload_id: 1,
    segment_id: 1,
    timestamp,
    channel_values: channelValues,
    has_measurement: true,
  };
}

describe("resolveSummaryMetrics", () => {
  it("matches heart_rate_be_u16 and spo2_be_u16 channel names", () => {
    const channels: Channel[] = [
      makeTrendChannel(10, 16, "heart_rate_be_u16"),
      makeTrendChannel(11, 14, "spo2_be_u16"),
    ];

    const resolved = resolveSummaryMetrics(channels);

    expect(resolved.trendByMetric.heart_rate?.name).toBe("heart_rate_be_u16");
    expect(resolved.trendByMetric.spo2?.name).toBe("spo2_be_u16");
  });

  it("still matches existing pulse and oxygen naming variants", () => {
    const channels: Channel[] = [
      makeTrendChannel(20, 4, "pulse_rate_raw"),
      makeTrendChannel(21, 5, "oxygen_saturation"),
    ];

    const resolved = resolveSummaryMetrics(channels);

    expect(resolved.trendByMetric.heart_rate?.name).toBe("pulse_rate_raw");
    expect(resolved.trendByMetric.spo2?.name).toBe("oxygen_saturation");
  });

  it("resolves inferred NIBP keys", () => {
    const channels: Channel[] = [
      makeNibpChannel(40, 14, "bp_systolic_inferred"),
      makeNibpChannel(41, 15, "bp_mean_inferred"),
      makeNibpChannel(42, 16, "bp_diastolic_inferred"),
    ];

    const resolved = resolveSummaryMetrics(channels);

    expect(resolved.nibpChannels.systolic?.name).toBe("bp_systolic_inferred");
    expect(resolved.nibpChannels.diastolic?.name).toBe("bp_diastolic_inferred");
    expect(resolved.nibpValueKeys.systolic).toBe("bp_systolic_inferred");
    expect(resolved.nibpValueKeys.map).toBe("bp_mean_inferred");
    expect(resolved.nibpValueKeys.diastolic).toBe("bp_diastolic_inferred");
  });

  it("reads explicit inferred NIBP channel names from compact payloads", () => {
    const channel = makeNibpChannel(40, 14, "bp_systolic_inferred");

    expect(resolveSummaryNibpValue({ bp_systolic_inferred: 112 }, channel)).toBe(112);
  });

  it("builds sparse NIBP point series from valid systolic and diastolic pairs only", () => {
    const channels = {
      systolic: makeNibpChannel(40, 14, "bp_systolic_inferred"),
      map: makeNibpChannel(41, 15, "bp_mean_inferred"),
      diastolic: makeNibpChannel(42, 16, "bp_diastolic_inferred"),
    };

    const series = buildSummaryNibpSeries([
      makeNibpEvent("2026-02-25T20:10:00.000Z", {
        bp_systolic_inferred: 120,
        bp_diastolic_inferred: 80,
      }),
      makeNibpEvent("2026-02-25T20:12:00.000Z", {
        bp_systolic_inferred: 110,
        bp_diastolic_inferred: 75,
      }),
      makeNibpEvent("2026-02-25T20:13:00.000Z", {
        bp_systolic_inferred: 118,
      }),
    ], channels);

    expect(series).toEqual([
      {
        name: "Systolic Pressure",
        data: [
          ["2026-02-25T20:10:00.000Z", 120],
          ["2026-02-25T20:12:00.000Z", 110],
        ],
        color: "#1D4ED8",
        presentation: "connected-points",
      },
      {
        name: "Mean Pressure",
        data: [
          ["2026-02-25T20:10:00.000Z", 93],
          ["2026-02-25T20:12:00.000Z", 87],
        ],
        color: "#2563EB",
        presentation: "connected-points",
      },
      {
        name: "Diastolic Pressure",
        data: [
          ["2026-02-25T20:10:00.000Z", 80],
          ["2026-02-25T20:12:00.000Z", 75],
        ],
        color: "#3B82F6",
        presentation: "connected-points",
      },
    ]);
  });

  it("builds validated NIBP series from inferred fields even without resolved channels", () => {
    const series = buildSummaryNibpSeries([
      makeNibpEvent("2026-02-25T20:10:00.000Z", {
        bp_systolic_inferred: 120,
        bp_diastolic_inferred: 80,
      }),
      makeNibpEvent("2026-02-25T20:12:00.000Z", {
        bp_systolic_inferred: 78,
        bp_diastolic_inferred: 92,
      }),
    ], {});

    expect(series).toEqual([
      {
        name: "Systolic Pressure",
        data: [["2026-02-25T20:10:00.000Z", 120]],
        color: "#1D4ED8",
        presentation: "connected-points",
      },
      {
        name: "Mean Pressure",
        data: [["2026-02-25T20:10:00.000Z", 93]],
        color: "#2563EB",
        presentation: "connected-points",
      },
      {
        name: "Diastolic Pressure",
        data: [["2026-02-25T20:10:00.000Z", 80]],
        color: "#3B82F6",
        presentation: "connected-points",
      },
    ]);
  });

  it("drops inverted NIBP pairs where systolic is lower than diastolic", () => {
    const channels = {
      systolic: makeNibpChannel(40, 14, "bp_systolic_inferred"),
      diastolic: makeNibpChannel(42, 16, "bp_diastolic_inferred"),
    };

    const series = buildSummaryNibpSeries([
      makeNibpEvent("2026-02-25T20:10:00.000Z", {
        bp_systolic_inferred: 82,
        bp_diastolic_inferred: 96,
      }),
    ], channels);

    expect(series).toEqual([]);
  });

  it("prefers inferred BP field names from linked NIBP decode output", () => {
    const reading = resolveSummaryInferredNibpReading({
      bp_systolic_inferred: 119,
      bp_mean_inferred: 92,
      bp_diastolic_inferred: 79,
    }, {
      systolic: makeNibpChannel(40, 14, "bp_systolic_inferred"),
      map: makeNibpChannel(41, 15, "bp_mean_inferred"),
      diastolic: makeNibpChannel(42, 16, "bp_diastolic_inferred"),
    });

    expect(reading).toEqual({
      systolic: 119,
      mean: 92,
      diastolic: 79,
    });
  });

  it("does not falsely map raw trend offset channels as vital metrics", () => {
    const channels: Channel[] = [
      makeTrendChannel(30, 0, "trend_raw_be_u16_o00"),
      makeTrendChannel(31, 1, "trend_raw_be_u16_o02"),
      makeTrendChannel(32, 2, "trend_raw_be_u16_o04"),
    ];

    const resolved = resolveSummaryMetrics(channels);

    expect(resolved.trendByMetric.heart_rate).toBeUndefined();
    expect(resolved.trendByMetric.spo2).toBeUndefined();
  });
});
