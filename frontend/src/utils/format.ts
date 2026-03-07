export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export function formatDate(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }

  const dateOnlyMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (dateOnlyMatch) {
    const [, year, month, day] = dateOnlyMatch;
    return new Date(Date.UTC(Number(year), Number(month) - 1, Number(day))).toLocaleDateString();
  }

  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString();
}

export function formatNumber(value: number | null | undefined, fractionDigits = 2): string {
  if (value === null || value === undefined) {
    return "-";
  }
  return value.toLocaleString(undefined, { maximumFractionDigits: fractionDigits });
}
