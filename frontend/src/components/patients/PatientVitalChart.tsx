import ReactECharts from "echarts-for-react";

interface VitalSeries {
  name: string;
  color: string;
  data: Array<[string, number]>;
  presentation?: "line" | "connected-points";
}

interface PatientVitalChartProps {
  yAxisLabel: string;
  series: VitalSeries[];
  height?: number;
}

export function PatientVitalChart({ yAxisLabel, series, height = 230 }: PatientVitalChartProps) {
  const fontFamily = "DM Sans, system-ui, sans-serif";
  const option: Record<string, unknown> = {
    tooltip: {
      trigger: "axis",
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
        formatter: "{HH}:{mm}",
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
    series: series.map((item) => ({
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
    })),
  };

  return <ReactECharts option={option} style={{ height: `${height}px`, width: "100%" }} notMerge lazyUpdate />;
}
