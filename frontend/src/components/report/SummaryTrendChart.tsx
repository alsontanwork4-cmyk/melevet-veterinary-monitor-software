import ReactECharts from "echarts-for-react";
import { buildSeriesBounds, buildWindowBounds, TrendSeriesInput } from "./summaryTrendWindow";

interface SummaryTrendChartProps {
  series: TrendSeriesInput[];
  yAxisLabel: string;
  windowMinutes: number;
  dayStartIso: string;
  dayEndIso: string;
  height?: number;
}

export function buildSummaryTrendChartOption({
  series,
  yAxisLabel,
  windowMinutes,
  dayStartIso,
  dayEndIso,
}: Omit<SummaryTrendChartProps, "height">): Record<string, unknown> {
  const { start: axisStart, end: axisEnd } = buildSeriesBounds(dayStartIso, dayEndIso, series);
  const { start: zoomStart, end: zoomEnd } = buildWindowBounds(dayStartIso, dayEndIso, windowMinutes, series);
  const fontFamily = "DM Sans, system-ui, sans-serif";

  const resolvedSeries = series.length > 0
    ? series.map((item) => {
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
      axisLabel: { fontFamily, color: "#5A6B7F", fontSize: 12, hideOverlap: true },
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
      },
    ],
    series: resolvedSeries,
  };
}

export function SummaryTrendChart({
  series,
  yAxisLabel,
  windowMinutes,
  dayStartIso,
  dayEndIso,
  height = 340,
}: SummaryTrendChartProps) {
  const option = buildSummaryTrendChartOption({
    series,
    yAxisLabel,
    windowMinutes,
    dayStartIso,
    dayEndIso,
  });

  return <ReactECharts option={option} style={{ width: "100%", height: `${height}px` }} notMerge lazyUpdate />;
}
