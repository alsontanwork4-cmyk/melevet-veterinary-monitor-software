import { describe, expect, it } from "vitest";

import { formatUtcDayLabel, parseUtcDayKey, toUtcDayKey, toUtcDayRange } from "./reportDay";

describe("reportDay", () => {
  it("builds day keys using UTC date parts", () => {
    expect(toUtcDayKey("2026-02-25T23:55:20Z")).toBe("2026-02-25");
    expect(toUtcDayKey("2026-02-26T00:05:00+08:00")).toBe("2026-02-25");
  });

  it("creates UTC day ranges from the selected key", () => {
    expect(toUtcDayRange("2026-02-25")).toEqual({
      fromTs: "2026-02-25T00:00:00.000Z",
      toTs: "2026-02-25T23:59:59.999Z",
      dayStartIso: "2026-02-25T00:00:00.000Z",
      dayEndIso: "2026-02-25T23:59:59.999Z",
    });
  });

  it("parses and formats UTC day labels safely", () => {
    expect(parseUtcDayKey("2026-02-25")?.toISOString()).toBe("2026-02-25T00:00:00.000Z");
    expect(formatUtcDayLabel("2026-02-25")).toBe(new Date("2026-02-25T00:00:00.000Z").toLocaleDateString(undefined, { timeZone: "UTC" }));
  });
});
