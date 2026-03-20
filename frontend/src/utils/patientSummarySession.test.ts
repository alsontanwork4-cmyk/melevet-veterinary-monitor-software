import { describe, expect, it } from "vitest";

import {
  buildSummaryPreviewWindow,
  collectDuplicateReportDayKeys,
  formatPatientSummaryUploadLabel,
  getLatestReportDayKey,
  selectLatestPeriod,
  selectLatestSegment,
  sortCompletedUploads,
} from "./patientSummarySession";

describe("patientSummarySession", () => {
  it("sorts completed uploads by latest recorded time before upload time", () => {
    const uploads = sortCompletedUploads([
      {
        id: 11,
        upload_time: "2026-03-06T07:25:20Z",
        latest_recorded_at: "2026-02-01T08:00:00Z",
        status: "completed",
        trend_frames: 1,
        nibp_frames: 0,
        measurements_new: 0,
        measurements_reused: 0,
        nibp_new: 0,
        nibp_reused: 0,
        archived_at: null,
        archive_id: null,
      },
      {
        id: 12,
        upload_time: "2026-03-05T07:25:20Z",
        latest_recorded_at: "2026-03-02T13:51:52Z",
        status: "completed",
        trend_frames: 1,
        nibp_frames: 0,
        measurements_new: 0,
        measurements_reused: 0,
        nibp_new: 0,
        nibp_reused: 0,
        archived_at: null,
        archive_id: null,
      },
      {
        id: 13,
        upload_time: "2026-03-07T07:25:20Z",
        latest_recorded_at: null,
        status: "processing",
        trend_frames: 1,
        nibp_frames: 0,
        measurements_new: 0,
        measurements_reused: 0,
        nibp_new: 0,
        nibp_reused: 0,
        archived_at: null,
        archive_id: null,
      },
    ]);

    expect(uploads.map((upload) => upload.id)).toEqual([12, 11]);
  });

  it("derives the latest report day using the same UTC day model as the detailed report", () => {
    const latestDay = getLatestReportDayKey([
      {
        id: 1,
        upload_id: 1,
        period_index: 0,
        start_time: "2026-02-25T23:55:20Z",
        end_time: "2026-02-26T00:05:00Z",
        frame_count: 10,
        label: "Period 1",
      },
      {
        id: 2,
        upload_id: 1,
        period_index: 1,
        start_time: "2026-03-02T11:23:44Z",
        end_time: "2026-03-02T13:51:52Z",
        frame_count: 10,
        label: "Period 2",
      },
    ]);

    expect(latestDay).toBe("2026-03-02");
  });

  it("prefers the latest period and segment by end time instead of frame count", () => {
    const period = selectLatestPeriod([
      {
        id: 1,
        upload_id: 1,
        period_index: 0,
        start_time: "2026-02-25T11:50:09Z",
        end_time: "2026-02-26T13:37:45Z",
        frame_count: 14627,
        label: "Period 1",
      },
      {
        id: 2,
        upload_id: 1,
        period_index: 1,
        start_time: "2026-03-02T11:23:44Z",
        end_time: "2026-03-02T13:51:52Z",
        frame_count: 8889,
        label: "Period 2",
      },
    ]);
    const segment = selectLatestSegment([
      {
        id: 10,
        period_id: 2,
        upload_id: 1,
        segment_index: 0,
        start_time: "2026-03-02T11:23:44Z",
        end_time: "2026-03-02T13:10:00Z",
        frame_count: 9000,
        duration_seconds: 6376,
      },
      {
        id: 11,
        period_id: 2,
        upload_id: 1,
        segment_index: 1,
        start_time: "2026-03-02T13:15:00Z",
        end_time: "2026-03-02T13:51:52Z",
        frame_count: 100,
        duration_seconds: 2212,
      },
    ]);

    expect(period?.id).toBe(2);
    expect(segment?.id).toBe(11);
  });

  it("clamps the homepage preview window to the selected UTC day", () => {
    const window = buildSummaryPreviewWindow(
      {
        start_time: "2026-03-01T23:50:00Z",
        end_time: "2026-03-02T00:10:00Z",
      },
      "2026-03-02",
    );

    expect(window).toEqual({
      fromTs: "2026-03-02T00:00:00.000Z",
      toTs: "2026-03-02T00:10:00.000Z",
    });
  });

  it("formats selector labels from report day and disambiguates duplicates", () => {
    const duplicateDayKeys = collectDuplicateReportDayKeys([
      {
        latest_recorded_at: "2026-03-02T13:51:52Z",
      },
      {
        latest_recorded_at: "2026-03-02T10:00:00Z",
      },
    ]);

    expect(
      formatPatientSummaryUploadLabel(
        {
          id: 14,
          upload_time: "2026-03-06T07:25:20Z",
          latest_recorded_at: "2026-03-02T13:51:52Z",
        },
        duplicateDayKeys,
      ),
    ).toBe(`${new Date("2026-03-02T00:00:00.000Z").toLocaleDateString(undefined, { timeZone: "UTC" })} (Session #14)`);
  });

  it("falls back to upload time when no parsed report day exists", () => {
    expect(
      formatPatientSummaryUploadLabel(
        {
          id: 15,
          upload_time: "2026-03-06T07:25:20Z",
          latest_recorded_at: null,
        },
        new Set(),
      ),
    ).toBe("2026-03-06 07:25:20 UTC");
  });
});
