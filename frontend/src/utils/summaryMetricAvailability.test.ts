import { describe, expect, it } from "vitest";

import { buildSummaryMetricAvailability } from "./summaryMetricAvailability";

describe("buildSummaryMetricAvailability", () => {
  it("marks only metrics with actual series points as available", () => {
    const availability = buildSummaryMetricAvailability({
      spo2: [{ data: [["2026-01-19T10:31:25.000Z", 98]] }],
      heart_rate: [{ data: [["2026-01-19T10:31:25.000Z", 140]] }],
      nibp: [],
    });

    expect(availability).toEqual({
      spo2: true,
      heart_rate: true,
      nibp: false,
    });
  });

  it("treats mapped-but-empty series as unavailable", () => {
    const availability = buildSummaryMetricAvailability({
      spo2: [{ data: [] }],
      heart_rate: [{ data: [] }],
      nibp: [{ data: [] }],
    });

    expect(availability).toEqual({
      spo2: false,
      heart_rate: false,
      nibp: false,
    });
  });
});
