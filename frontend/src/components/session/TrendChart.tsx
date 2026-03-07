import ReactECharts from "echarts-for-react";

import { AlarmEvent, MeasurementPoint, NibpEvent } from "../../types/api";
import { alarmColorMap } from "../../utils/alarmColors";
import { parseNibpReading } from "../../utils/vitals";

interface TrendChartProps {
  groupedData: Record<string, MeasurementPoint[]>;
  nibpEvents: NibpEvent[];
  alarms: AlarmEvent[];
  seriesLabelByChannel?: Record<string, string>;
}

export function TrendChart({ groupedData, nibpEvents, alarms, seriesLabelByChannel = {} }: TrendChartProps) {
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

  const alarmLines = alarms.map((alarm) => ({
    xAxis: alarm.timestamp,
    lineStyle: {
      color: alarmColorMap[alarm.alarm_category],
      width: 1,
      opacity: 0.7,
    },
    label: {
      show: false,
    },
  }));

  const markLine = {
    silent: true,
    symbol: "none",
    data: alarmLines,
  };

  if (trendSeries.length > 0) {
    trendSeries[0].markLine = markLine;
  } else {
    trendSeries.push({
      name: "Trend",
      type: "line",
      data: [],
      markLine,
    });
  }

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
      type: "scroll",
      textStyle: { fontFamily, color: "#5A6B7F", fontSize: 12 },
    },
    grid: { top: 48, left: 48, right: 48, bottom: 70 },
    xAxis: {
      type: "time",
      axisLine: { lineStyle: { color: "#E2E8F0" } },
      axisLabel: { fontFamily, color: "#5A6B7F", fontSize: 11 },
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
      },
    ],
    series: [...trendSeries, nibpSeries],
  };

  return <ReactECharts option={option} style={{ height: "520px", width: "100%" }} notMerge lazyUpdate />;
}
