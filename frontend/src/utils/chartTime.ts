type DateLike = string | number | Date;

type ChartTooltipParam = {
  axisValue?: DateLike;
  marker?: string;
  seriesName?: string;
  value?: unknown;
};

function resolveDate(value: DateLike): Date | null {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }

  return date;
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

function getDateParts(value: DateLike, includeSeconds: boolean): Record<string, string> | null {
  const date = resolveDate(value);
  if (!date) {
    return null;
  }

  return {
    year: String(date.getUTCFullYear()),
    month: pad(date.getUTCMonth() + 1),
    day: pad(date.getUTCDate()),
    hour: pad(date.getUTCHours()),
    minute: pad(date.getUTCMinutes()),
    second: includeSeconds ? pad(date.getUTCSeconds()) : "",
  };
}

function extractSeriesValue(value: unknown): string {
  if (Array.isArray(value)) {
    const detailValue = value[2];
    if (typeof detailValue === "string" && detailValue.trim().length > 0) {
      return detailValue;
    }
    const seriesValue = value[1];
    return seriesValue === null || seriesValue === undefined ? "-" : String(seriesValue);
  }

  return value === null || value === undefined ? "-" : String(value);
}

export function formatChartAxisTime(value: DateLike): string {
  const parts = getDateParts(value, false);
  if (!parts) {
    return "";
  }

  return `${parts.hour}:${parts.minute}`;
}

export function formatChartTooltipTimestamp(value: DateLike): string {
  const parts = getDateParts(value, true);
  if (!parts) {
    return "";
  }

  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second} UTC`;
}

export function formatChartZoomLabel(value: DateLike): string {
  const parts = getDateParts(value, false);
  if (!parts) {
    return "";
  }

  return `${parts.month}-${parts.day} ${parts.hour}:${parts.minute}`;
}

export function buildChartTooltipFormatter() {
  return (params: ChartTooltipParam | ChartTooltipParam[]): string => {
    const items = Array.isArray(params) ? params : [params];
    if (items.length === 0) {
      return "";
    }

    const title = formatChartTooltipTimestamp(items[0].axisValue ?? "");
    const seriesLines = items.map((item) => `${item.marker ?? ""}${item.seriesName ?? "Value"}: ${extractSeriesValue(item.value)}`);
    return [title, ...seriesLines].join("<br/>");
  };
}
