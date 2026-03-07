import { describe, expect, it } from "vitest";

import { buildSummaryTrendChartOption } from "./SummaryTrendChart";
import { buildSeriesBounds, buildWindowBounds } from "./summaryTrendWindow";

describe("buildWindowBounds", () => {
  it("anchors default window to latest data point when series has data", () => {
    const bounds = buildWindowBounds(
      "2026-01-19T00:00:00.000Z",
      "2026-01-19T23:59:59.999Z",
      5,
      [
        {
          name: "SpO2 (%)",
          data: [
            ["2026-01-19T10:31:25.000Z", 98],
            ["2026-01-19T12:58:47.000Z", 97],
          ],
        },
      ],
    );

    expect(bounds.end).toBe("2026-01-19T12:58:47.000Z");
    expect(bounds.start).toBe("2026-01-19T12:53:47.000Z");
  });

  it("falls back to end-of-day window when no data exists", () => {
    const bounds = buildWindowBounds(
      "2026-01-19T00:00:00.000Z",
      "2026-01-19T23:59:59.999Z",
      5,
      [],
    );

    expect(bounds.end).toBe("2026-01-19T23:59:59.999Z");
    expect(bounds.start).toBe("2026-01-19T23:54:59.999Z");
  });

  it("clamps long windows to available data range", () => {
    const bounds = buildWindowBounds(
      "2026-01-19T00:00:00.000Z",
      "2026-01-19T23:59:59.999Z",
      30,
      [
        {
          name: "SpO2 (%)",
          data: [
            ["2026-01-19T21:20:00.000Z", 99],
            ["2026-01-19T21:22:00.000Z", 98],
          ],
        },
      ],
    );

    expect(bounds.start).toBe("2026-01-19T21:20:00.000Z");
    expect(bounds.end).toBe("2026-01-19T21:22:00.000Z");
  });
});

describe("buildSeriesBounds", () => {
  it("uses actual data extent within the selected day", () => {
    const bounds = buildSeriesBounds(
      "2026-01-19T00:00:00.000Z",
      "2026-01-19T23:59:59.999Z",
      [
        {
          name: "SpO2 (%)",
          data: [
            ["2026-01-19T21:20:00.000Z", 99],
            ["2026-01-19T22:40:00.000Z", 97],
          ],
        },
      ],
    );

    expect(bounds.start).toBe("2026-01-19T21:20:00.000Z");
    expect(bounds.end).toBe("2026-01-19T22:40:00.000Z");
  });
});

describe("buildSummaryTrendChartOption", () => {
  it("renders sparse point series as scatter without converting line series", () => {
    const option = buildSummaryTrendChartOption({
      yAxisLabel: "mmHg",
      windowMinutes: 5,
      dayStartIso: "2026-01-19T00:00:00.000Z",
      dayEndIso: "2026-01-19T23:59:59.999Z",
      series: [
        {
          name: "SpO2 (%)",
          data: [["2026-01-19T21:20:00.000Z", 99]],
        },
        {
          name: "Systolic",
          presentation: "connected-points",
          data: [["2026-01-19T21:25:00.000Z", 118]],
        },
      ],
    });

    const renderedSeries = option.series as Array<Record<string, unknown>>;
    expect(renderedSeries[0].type).toBe("line");
    expect(renderedSeries[1].type).toBe("line");
    expect(renderedSeries[1].symbol).toBe("circle");
    expect(option.useUTC).toBe(true);
  });
});
