import ReactECharts from "echarts-for-react";

import { MeasurementPoint, NibpEvent } from "../../types/api";
import { buildChartTooltipFormatter, formatChartAxisTime, formatChartZoomLabel } from "../../utils/chartTime";
import { parseNibpReading } from "../../utils/vitals";

interface TrendChartProps {
  groupedData: Record<string, MeasurementPoint[]>;
  nibpEvents: NibpEvent[];
  seriesLabelByChannel?: Record<string, string>;
}

export function buildTrendChartOption({ groupedData, nibpEvents, seriesLabelByChannel = {} }: TrendChartProps): Record<string, unknown> {
  const trendSeries: Array<Record<string, unknown>> = Object.entries(groupedData).map(([name, points]) => ({
    name: seriesLabelByChannel[name] ?? name,
    type: "line",
    showSymbol: false,
    connectNulls: false,
    data: points.map((point) => [point.timestamp, point.value]),
  }));

  const nibpData: Array<[string, number, string]> = [];
  for (const event of nibpEvents) {
    const reading = parseNibpReading(event);
    if (reading.representative !== null) {
      nibpData.push([event.timestamp, reading.representative, reading.summary]);
    }
  }

  const nibpSeries: Record<string, unknown> = {
    name: "NIBP (Blood Pressure)",
    type: "scatter",
    symbol: "diamond",
    symbolSize: 9,
    itemStyle: { color: "#2563EB" },
    data: nibpData,
    tooltip: {
      formatter: (params: { value: [string, number, string] }) => `NIBP: ${params.value[2]}`,
    },
  };

  if (trendSeries.length === 0) {
    trendSeries.push({
      name: "Trend",
      type: "line",
      data: [],
    });
  }

  const fontFamily = "DM Sans, system-ui, sans-serif";

  return {
    useUTC: true,
    tooltip: {
      trigger: "axis",
      formatter: buildChartTooltipFormatter(),
      backgroundColor: "#FFFFFF",
      borderColor: "#E2E8F0",
      borderWidth: 1,
      textStyle: { fontFamily, color: "#1A2332", fontSize: 12 },
    },
    legend: {
      type: "scroll",
      textStyle: { fontFamily, color: "#5A6B7F", fontSize: 12 },
    },
    grid: { top: 48, left: 48, right: 48, bottom: 70 },
    xAxis: {
      type: "time",
      axisLine: { lineStyle: { color: "#E2E8F0" } },
      axisLabel: {
        fontFamily,
        color: "#5A6B7F",
        fontSize: 11,
        formatter: (value: string | number | Date) => formatChartAxisTime(value),
      },
      splitLine: { lineStyle: { color: "#EEF2F6" } },
    },
    yAxis: {
      type: "value",
      name: "Vital Value",
      nameTextStyle: { fontFamily, color: "#5A6B7F" },
      axisLine: { lineStyle: { color: "#E2E8F0" } },
      axisLabel: { fontFamily, color: "#5A6B7F", fontSize: 11 },
      splitLine: { lineStyle: { color: "#EEF2F6" } },
    },
    dataZoom: [
      { type: "inside" },
      {
        type: "slider",
        borderColor: "#E2E8F0",
        fillerColor: "rgba(43, 110, 99, 0.08)",
        handleStyle: { color: "#2B6E63" },
        labelFormatter: (value: string | number | Date) => formatChartZoomLabel(value),
      },
    ],
    series: [...trendSeries, nibpSeries],
  };
}

export function TrendChart({ groupedData, nibpEvents, seriesLabelByChannel = {} }: TrendChartProps) {
  const option = buildTrendChartOption({ groupedData, nibpEvents, seriesLabelByChannel });
  return <ReactECharts option={option} style={{ height: "520px", width: "100%" }} notMerge lazyUpdate />;
}
