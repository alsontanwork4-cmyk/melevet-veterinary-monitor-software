export function toUtcDayKey(value: string): string | null {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }

  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  const day = String(date.getUTCDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function parseUtcDayKey(dayKey: string): Date | null {
  const match = dayKey.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) {
    return null;
  }

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const timestamp = Date.UTC(year, month - 1, day, 0, 0, 0, 0);
  const date = new Date(timestamp);
  if (
    Number.isNaN(date.getTime()) ||
    date.getUTCFullYear() !== year ||
    date.getUTCMonth() !== month - 1 ||
    date.getUTCDate() !== day
  ) {
    return null;
  }

  return date;
}

export function toUtcDayRange(dayKey: string): { fromTs: string; toTs: string; dayStartIso: string; dayEndIso: string } | null {
  const start = parseUtcDayKey(dayKey);
  if (!start) {
    return null;
  }

  const end = new Date(Date.UTC(
    start.getUTCFullYear(),
    start.getUTCMonth(),
    start.getUTCDate(),
    23,
    59,
    59,
    999,
  ));

  return {
    fromTs: start.toISOString(),
    toTs: end.toISOString(),
    dayStartIso: start.toISOString(),
    dayEndIso: end.toISOString(),
  };
}

export function formatUtcDayLabel(dayKey: string): string {
  const date = parseUtcDayKey(dayKey);
  return date
    ? date.toLocaleDateString(undefined, { timeZone: "UTC" })
    : dayKey;
}
