import { describe, expect, it } from "vitest";

import { buildSegmentWindowQuery } from "./sessionWindowQuery";

describe("buildSegmentWindowQuery", () => {
  it("includes segment and window bounds when provided", () => {
    const query = buildSegmentWindowQuery(48, "2026-01-19T14:14:24.000Z", "2026-01-19T14:19:24.000Z");

    expect(query).toEqual({
      segmentId: 48,
      fromTs: "2026-01-19T14:14:24.000Z",
      toTs: "2026-01-19T14:19:24.000Z",
    });
  });

  it("omits segmentId when segment is not selected", () => {
    const query = buildSegmentWindowQuery(null, "2026-01-19T14:14:24.000Z", "2026-01-19T14:19:24.000Z");

    expect(query).toEqual({
      segmentId: undefined,
      fromTs: "2026-01-19T14:14:24.000Z",
      toTs: "2026-01-19T14:19:24.000Z",
    });
  });
});
