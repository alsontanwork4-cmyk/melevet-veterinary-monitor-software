import { SummaryMetricId } from "./summaryReportMetrics";

type MetricSeries = Record<SummaryMetricId, Array<{ data: Array<[string, number]> }>>;

export function buildSummaryMetricAvailability(metricSeries: MetricSeries): Record<SummaryMetricId, boolean> {
  return {
    spo2: metricSeries.spo2.some((series) => series.data.length > 0),
    heart_rate: metricSeries.heart_rate.some((series) => series.data.length > 0),
    nibp: metricSeries.nibp.some((series) => series.data.length > 0),
  };
}
