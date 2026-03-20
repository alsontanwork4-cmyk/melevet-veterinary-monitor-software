import ReactECharts from "echarts-for-react";

import { MeasurementPoint, NibpEvent } from "../../types/api";

interface ReportVitalsChartProps {
  groupedData: Record<string, MeasurementPoint[]>;
  nibpEvents: NibpEvent[];
  nibpValueKeys: {
    systolic?: string;
    map?: string;
    diastolic?: string;
  };
}

function toNibpSeriesData(events: NibpEvent[], key: string): Array<[string, number]> {
  const data: Array<[string, number]> = [];

  for (const event of events) {
    const value = event.channel_values[key];
    if (typeof value === "number") {
      data.push([event.timestamp, value]);
    }
  }

  return data;
}

export function ReportVitalsChart({
  groupedData,
  nibpEvents,
  nibpValueKeys,
}: ReportVitalsChartProps) {
  const trendSeries: Array<Record<string, unknown>> = Object.entries(groupedData).map(([name, points]) => ({
    name,
    type: "line",
    showSymbol: false,
    connectNulls: false,
    smooth: false,
    yAxisIndex: 0,
    data: points.map((point) => [point.timestamp, point.value]),
  }));

  const nibpSeriesDefs: Array<{
    metric: "systolic" | "map" | "diastolic";
    label: string;
    color: string;
  }> = [
    { metric: "systolic", label: "NIBP Systolic", color: "#1D4ED8" },
    { metric: "map", label: "NIBP MAP", color: "#2563EB" },
    { metric: "diastolic", label: "NIBP Diastolic", color: "#3B82F6" },
  ];

  const nibpSeries: Array<Record<string, unknown>> = [];
  for (const seriesDef of nibpSeriesDefs) {
    const valueKey = nibpValueKeys[seriesDef.metric];
    if (!valueKey) {
      continue;
    }

    const data = toNibpSeriesData(nibpEvents, valueKey);
    if (data.length === 0) {
      continue;
    }

    nibpSeries.push({
      name: seriesDef.label,
      type: "scatter",
      symbol: "diamond",
      symbolSize: 9,
      yAxisIndex: 1,
      itemStyle: { color: seriesDef.color },
      data,
    });
  }

  const allSeries = [...trendSeries, ...nibpSeries];
  if (allSeries.length === 0) {
    allSeries.push({
      name: "Vitals",
      type: "line",
      data: [],
      yAxisIndex: 0,
    });
  }

  const fontFamily = "DM Sans, system-ui, sans-serif";

  const option: Record<string, unknown> = {
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "cross" },
      backgroundColor: "#FFFFFF",
      borderColor: "#E2E8F0",
      borderWidth: 1,
      textStyle: { fontFamily, color: "#1A2332", fontSize: 12 },
    },
    legend: {
      type: "scroll",
      textStyle: { fontFamily, color: "#5A6B7F", fontSize: 12 },
    },
    grid: { top: 52, left: 56, right: 56, bottom: 72 },
    xAxis: {
      type: "time",
      axisLine: { lineStyle: { color: "#E2E8F0" } },
      axisLabel: { fontFamily, color: "#5A6B7F", fontSize: 11 },
      splitLine: { lineStyle: { color: "#EEF2F6" } },
    },
    yAxis: [
      {
        type: "value",
        name: "Vitals",
        nameTextStyle: { fontFamily, color: "#5A6B7F" },
        axisLine: { lineStyle: { color: "#E2E8F0" } },
        axisLabel: { fontFamily, color: "#5A6B7F", fontSize: 11 },
        splitLine: { lineStyle: { color: "#EEF2F6" } },
      },
      {
        type: "value",
        name: "NIBP (mmHg)",
        nameTextStyle: { fontFamily, color: "#5A6B7F" },
        axisLine: { lineStyle: { color: "#E2E8F0" } },
        axisLabel: { fontFamily, color: "#5A6B7F", fontSize: 11 },
        splitLine: { show: false },
      },
    ],
    dataZoom: [
      { type: "inside" },
      {
        type: "slider",
        borderColor: "#E2E8F0",
        fillerColor: "rgba(43, 110, 99, 0.08)",
        handleStyle: { color: "#2B6E63" },
      },
    ],
    series: allSeries,
  };

  return <ReactECharts option={option} style={{ height: "540px", width: "100%" }} notMerge lazyUpdate />;
}
