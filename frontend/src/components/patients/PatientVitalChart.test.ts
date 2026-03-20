import { describe, expect, it } from "vitest";

import { buildPatientVitalChartOption } from "./PatientVitalChart";

describe("buildPatientVitalChartOption", () => {
  it("formats the same UTC timestamp identically to the report summary chart in UTC", () => {
    const option = buildPatientVitalChartOption({
      yAxisLabel: "%",
      series: [
        {
          name: "SpO2 (%)",
          color: "#0EA5E9",
          data: [["2026-01-19T12:20:00.000Z", 99]],
        },
      ],
    });

    const xAxis = option.xAxis as { axisLabel: { formatter: (value: string) => string } };
    const tooltip = option.tooltip as { formatter: (params: unknown) => string };
    const sliderZoom = (option.dataZoom as Array<{ type: string; labelFormatter?: (value: string) => string }>).find(
      (item) => item.type === "slider",
    );

    expect(xAxis.axisLabel.formatter("2026-01-19T12:20:00.000Z")).toBe("12:20");
    expect(
      tooltip.formatter([
        {
          axisValue: "2026-01-19T12:20:00.000Z",
          marker: "",
          seriesName: "SpO2 (%)",
          value: ["2026-01-19T12:20:00.000Z", 99],
        },
      ]),
    ).toContain("2026-01-19 12:20:00 UTC");
    expect(sliderZoom?.labelFormatter?.("2026-01-19T12:20:00.000Z")).toBe("01-19 12:20");
  });

  it("keeps UTC display unchanged for UTC timestamps", () => {
    const option = buildPatientVitalChartOption({
      yAxisLabel: "%",
      series: [
        {
          name: "SpO2 (%)",
          color: "#0EA5E9",
          data: [["2026-01-19T12:20:00.000Z", 99]],
        },
      ],
    });

    const xAxis = option.xAxis as { axisLabel: { formatter: (value: string) => string } };
    const tooltip = option.tooltip as { formatter: (params: unknown) => string };

    expect(xAxis.axisLabel.formatter("2026-01-19T12:20:00.000Z")).toBe("12:20");
    expect(
      tooltip.formatter([
        {
          axisValue: "2026-01-19T12:20:00.000Z",
          marker: "",
          seriesName: "SpO2 (%)",
          value: ["2026-01-19T12:20:00.000Z", 99],
        },
      ]),
    ).toContain("2026-01-19 12:20:00 UTC");
  });
});
