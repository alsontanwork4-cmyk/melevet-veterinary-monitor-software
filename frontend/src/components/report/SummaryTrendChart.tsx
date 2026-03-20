import { forwardRef, useImperativeHandle, useRef } from "react";
import ReactECharts from "echarts-for-react";
import type { EChartsType } from "echarts";
import { buildSeriesBounds, buildWindowBounds, TrendSeriesInput } from "./summaryTrendWindow";
import { buildChartTooltipFormatter, formatChartAxisTime, formatChartZoomLabel } from "../../utils/chartTime";

export interface SummaryTrendChartHandle {
  getEchartsInstance: () => EChartsType | null;
}

export interface ChartThresholdOverlay {
  label: string;
  low?: number | null;
  high?: number | null;
  color?: string;
}

interface SummaryTrendChartProps {
  series: TrendSeriesInput[];
  yAxisLabel: string;
  windowMinutes: number;
  dayStartIso: string;
  dayEndIso: string;
  thresholds?: ChartThresholdOverlay[];
  height?: number;
}

function buildThresholdAnnotation(
  thresholds: ChartThresholdOverlay[] | undefined,
  series: TrendSeriesInput[],
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
        {
          name: `${threshold.label} low zone`,
          yAxis: Math.min(seriesMin, threshold.low, 0),
          itemStyle: { color: "rgba(245, 158, 11, 0.08)" },
        },
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
        {
          name: `${threshold.label} high zone`,
          yAxis: threshold.high,
          itemStyle: { color: "rgba(220, 38, 38, 0.06)" },
        },
        { yAxis: Math.max(seriesMax, threshold.high) + 1 },
      ]);
    }
  }

  return {
    markLine: markLineData.length > 0 ? { silent: true, symbol: "none", data: markLineData } : undefined,
    markArea: markAreaData.length > 0 ? { silent: true, data: markAreaData } : undefined,
  };
}

export function buildSummaryTrendChartOption({
  series,
  yAxisLabel,
  windowMinutes,
  dayStartIso,
  dayEndIso,
  thresholds,
}: Omit<SummaryTrendChartProps, "height">): Record<string, unknown> {
  const { start: axisStart, end: axisEnd } = buildSeriesBounds(dayStartIso, dayEndIso, series);
  const { start: zoomStart, end: zoomEnd } = buildWindowBounds(dayStartIso, dayEndIso, windowMinutes, series);
  const fontFamily = "DM Sans, system-ui, sans-serif";

  const thresholdAnnotation = buildThresholdAnnotation(thresholds, series);
  const resolvedSeries = series.length > 0
    ? series.map((item, index) => {
      const thresholdDecorations = index === 0 ? thresholdAnnotation : undefined;
      if (item.presentation === "connected-points") {
        return {
          name: item.name,
          type: "line",
          symbol: "circle",
          symbolSize: 8,
          showSymbol: true,
          connectNulls: false,
          smooth: false,
          itemStyle: item.color ? { color: item.color } : undefined,
          lineStyle: item.color ? { color: item.color, width: 2 } : { width: 2 },
          data: item.data,
          markArea: thresholdDecorations?.markArea,
          markLine: thresholdDecorations?.markLine,
        };
      }

      return {
        name: item.name,
        type: "line",
        showSymbol: false,
        connectNulls: false,
        smooth: false,
        itemStyle: item.color ? { color: item.color } : undefined,
        lineStyle: item.color ? { color: item.color, width: 2 } : { width: 2 },
        data: item.data,
        markArea: thresholdDecorations?.markArea,
        markLine: thresholdDecorations?.markLine,
      };
    })
    : [{
      name: "No Data",
      type: "line",
      showSymbol: false,
      data: [],
    }];

  return {
    useUTC: true,
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "cross" },
      formatter: buildChartTooltipFormatter(),
      backgroundColor: "#FFFFFF",
      borderColor: "#E2E8F0",
      borderWidth: 1,
      textStyle: { fontFamily, color: "#1A2332", fontSize: 13 },
    },
    legend: {
      type: "scroll",
      orient: "horizontal",
      top: 8,
      left: 0,
      icon: "circle",
      itemWidth: 12,
      itemHeight: 12,
      textStyle: { fontFamily, color: "#5A6B7F", fontSize: 13 },
    },
    grid: { top: 52, left: 64, right: 28, bottom: 82 },
    xAxis: {
      type: "time",
      min: axisStart,
      max: axisEnd,
      axisLine: { lineStyle: { color: "#E2E8F0" } },
      axisLabel: {
        fontFamily,
        color: "#5A6B7F",
        fontSize: 12,
        hideOverlap: true,
        formatter: (value: string | number | Date) => formatChartAxisTime(value),
      },
      splitLine: { lineStyle: { color: "#EEF2F6" } },
    },
    yAxis: {
      type: "value",
      scale: true,
      name: yAxisLabel,
      nameGap: 18,
      nameTextStyle: { fontFamily, color: "#5A6B7F", fontSize: 12 },
      axisLine: { lineStyle: { color: "#E2E8F0" } },
      axisLabel: { fontFamily, color: "#5A6B7F", fontSize: 12 },
      splitLine: { lineStyle: { color: "#EEF2F6" } },
    },
    dataZoom: [
      { type: "inside", startValue: zoomStart, endValue: zoomEnd },
      {
        type: "slider",
        height: 26,
        borderColor: "#E2E8F0",
        fillerColor: "rgba(43, 110, 99, 0.08)",
        handleStyle: { color: "#2B6E63" },
        textStyle: { fontFamily, color: "#5A6B7F", fontSize: 11 },
        startValue: zoomStart,
        endValue: zoomEnd,
        labelFormatter: (value: string | number | Date) => formatChartZoomLabel(value),
      },
    ],
    series: resolvedSeries,
  };
}

export const SummaryTrendChart = forwardRef<SummaryTrendChartHandle, SummaryTrendChartProps>(function SummaryTrendChart(
{
  series,
  yAxisLabel,
  windowMinutes,
  dayStartIso,
  dayEndIso,
  thresholds,
  height = 340,
}: SummaryTrendChartProps,
ref,
) {
  const chartRef = useRef<InstanceType<typeof ReactECharts> | null>(null);
  const option = buildSummaryTrendChartOption({
    series,
    yAxisLabel,
    windowMinutes,
    dayStartIso,
    dayEndIso,
    thresholds,
  });

  useImperativeHandle(ref, () => ({
    getEchartsInstance: () => chartRef.current?.getEchartsInstance() ?? null,
  }));

  return <ReactECharts ref={chartRef} option={option} style={{ width: "100%", height: `${height}px` }} notMerge lazyUpdate />;
});
