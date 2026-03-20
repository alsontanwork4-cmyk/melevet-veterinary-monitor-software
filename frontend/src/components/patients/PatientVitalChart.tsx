import ReactECharts from "echarts-for-react";
import { buildChartTooltipFormatter, formatChartAxisTime, formatChartZoomLabel } from "../../utils/chartTime";

interface VitalSeries {
  name: string;
  color: string;
  data: Array<[string, number]>;
  presentation?: "line" | "connected-points";
}

interface ChartThresholdOverlay {
  label: string;
  low?: number | null;
  high?: number | null;
  color?: string;
}

interface PatientVitalChartProps {
  yAxisLabel: string;
  series: VitalSeries[];
  thresholds?: ChartThresholdOverlay[];
  height?: number;
}

function buildThresholdAnnotation(
  thresholds: ChartThresholdOverlay[] | undefined,
  series: VitalSeries[],
): { markLine?: Record<string, unknown>; markArea?: Record<string, unknown> } | undefined {
  const activeThresholds = (thresholds ?? []).filter((item) => item.low !== null || item.high !== null);
  if (activeThresholds.length === 0) {
    return undefined;
  }

  const seriesValues = series.flatMap((item) => item.data.map(([, value]) => value).filter((value) => Number.isFinite(value)));
  const seriesMin = seriesValues.length > 0 ? Math.min(...seriesValues, 0) : 0;
  const seriesMax = seriesValues.length > 0 ? Math.max(...seriesValues) : 0;

  const markLineData: Array<Record<string, unknown>> = [];
  const markAreaData: Array<[Record<string, unknown>, Record<string, unknown>]> = [];

  for (const threshold of activeThresholds) {
    const color = threshold.color ?? "rgba(217, 119, 6, 0.8)";
    if (threshold.low !== null && threshold.low !== undefined) {
      markLineData.push({
        name: `${threshold.label} low`,
        yAxis: threshold.low,
        lineStyle: { color, type: "dashed", width: 1.5 },
        label: { formatter: `${threshold.label} low`, color },
      });
      markAreaData.push([
        { yAxis: Math.min(seriesMin, threshold.low, 0), itemStyle: { color: "rgba(245, 158, 11, 0.08)" } },
        { yAxis: threshold.low },
      ]);
    }
    if (threshold.high !== null && threshold.high !== undefined) {
      markLineData.push({
        name: `${threshold.label} high`,
        yAxis: threshold.high,
        lineStyle: { color, type: "dashed", width: 1.5 },
        label: { formatter: `${threshold.label} high`, color },
      });
      markAreaData.push([
        { yAxis: threshold.high, itemStyle: { color: "rgba(220, 38, 38, 0.06)" } },
        { yAxis: Math.max(seriesMax, threshold.high) + 1 },
      ]);
    }
  }

  return {
    markLine: markLineData.length > 0 ? { silent: true, symbol: "none", data: markLineData } : undefined,
    markArea: markAreaData.length > 0 ? { silent: true, data: markAreaData } : undefined,
  };
}

export function buildPatientVitalChartOption({
  yAxisLabel,
  series,
  thresholds,
}: Omit<PatientVitalChartProps, "height">): Record<string, unknown> {
  const fontFamily = "DM Sans, system-ui, sans-serif";
  const thresholdAnnotation = buildThresholdAnnotation(thresholds, series);
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
      show: series.length > 1,
      type: "scroll",
      textStyle: { fontFamily, color: "#5A6B7F", fontSize: 11 },
    },
    grid: { top: series.length > 1 ? 44 : 28, left: 48, right: 20, bottom: 56 },
    xAxis: {
      type: "time",
      axisLine: { lineStyle: { color: "#E2E8F0" } },
      splitNumber: 4,
      axisLabel: {
        fontFamily,
        color: "#5A6B7F",
        fontSize: 11,
        hideOverlap: true,
        formatter: (value: string | number | Date) => formatChartAxisTime(value),
      },
      splitLine: { lineStyle: { color: "#EEF2F6" } },
    },
    yAxis: {
      type: "value",
      name: yAxisLabel,
      nameTextStyle: { fontFamily, color: "#5A6B7F", fontSize: 11 },
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
    series: series.map((item, index) => ({
      name: item.name,
      type: "line",
      showSymbol: item.presentation === "connected-points",
      symbol: item.presentation === "connected-points" ? "circle" : undefined,
      symbolSize: item.presentation === "connected-points" ? 8 : undefined,
      connectNulls: false,
      smooth: false,
      itemStyle: { color: item.color },
      lineStyle: { color: item.color, width: 2 },
      data: item.data,
      markArea: index === 0 ? thresholdAnnotation?.markArea : undefined,
      markLine: index === 0 ? thresholdAnnotation?.markLine : undefined,
    })),
  };
}

export function PatientVitalChart({ yAxisLabel, series, thresholds, height = 230 }: PatientVitalChartProps) {
  const option = buildPatientVitalChartOption({ yAxisLabel, series, thresholds });
  return <ReactECharts option={option} style={{ height: `${height}px`, width: "100%" }} notMerge lazyUpdate />;
}
