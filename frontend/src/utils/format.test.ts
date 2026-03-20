import { describe, expect, it } from "vitest";

import { formatDateTime } from "./format";

describe("formatDateTime", () => {
  it("formats ISO timestamps in UTC", () => {
    expect(formatDateTime("2026-03-06T07:25:20Z")).toBe("2026-03-06 07:25:20 UTC");
  });

  it("returns a placeholder for empty values", () => {
    expect(formatDateTime(null)).toBe("-");
  });
});
