import { describe, expect, it } from "vitest";

import { buildTrendChartOption } from "./TrendChart";

describe("buildTrendChartOption", () => {
  it("formats the session chart timeline in UTC", () => {
    const option = buildTrendChartOption({
      groupedData: {
        heart_rate_be_u16: [
          {
            timestamp: "2026-01-19T12:20:00.000Z",
            channel_id: 1,
            channel_name: "heart_rate_be_u16",
            value: 99,
          },
        ],
      },
      nibpEvents: [],
      seriesLabelByChannel: { heart_rate_be_u16: "Heart Rate" },
    });

    const xAxis = option.xAxis as { axisLabel: { formatter: (value: string) => string } };
    const tooltip = option.tooltip as { formatter: (params: unknown) => string };
    const sliderZoom = (option.dataZoom as Array<{ type: string; labelFormatter?: (value: string) => string }>).find(
      (item) => item.type === "slider",
    );

    expect(option.useUTC).toBe(true);
    expect(xAxis.axisLabel.formatter("2026-01-19T12:20:00.000Z")).toBe("12:20");
    expect(
      tooltip.formatter([
        {
          axisValue: "2026-01-19T12:20:00.000Z",
          marker: "",
          seriesName: "Heart Rate",
          value: ["2026-01-19T12:20:00.000Z", 99],
        },
      ]),
    ).toContain("2026-01-19 12:20:00 UTC");
    expect(sliderZoom?.labelFormatter?.("2026-01-19T12:20:00.000Z")).toBe("01-19 12:20");
  });
});
