// @vitest-environment jsdom

import { act } from "react";
import { createRoot, Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import { PatientHistory } from "./PatientHistory";
import type { PatientUploadHistoryItem } from "../../types/api";

let container: HTMLDivElement;
let root: Root;

function buildUpload(overrides: Partial<PatientUploadHistoryItem> = {}): PatientUploadHistoryItem {
  return {
    id: 14,
    upload_time: "2026-03-16T03:00:00Z",
    latest_recorded_at: "2026-03-16T04:00:00Z",
    status: "completed",
    trend_frames: 100,
    nibp_frames: 20,
    measurements_new: 0,
    measurements_reused: 90,
    nibp_new: 0,
    nibp_reused: 20,
    archived_at: null,
    archive_id: null,
    ...overrides,
  };
}

beforeEach(() => {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div");
  document.body.innerHTML = "";
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
});

describe("PatientHistory", () => {
  it("explains canonical-only storage and shows exact overlap reuse", async () => {
    await act(async () => {
      root.render(
        <MemoryRouter>
          <PatientHistory
            uploads={[buildUpload()]}
            page={1}
            totalPages={1}
            totalCount={1}
            onPageChange={vi.fn()}
            onDeleteUpload={vi.fn()}
            deletingUploadId={null}
          />
        </MemoryRouter>,
      );
    });

    expect(container.textContent).toContain("Original export files are temporary.");
    expect(container.textContent).toContain("Exact overlap: reused 115 rows");
  });

  it("shows mixed new and reused counts when an upload adds new canonical rows", async () => {
    await act(async () => {
      root.render(
        <MemoryRouter>
          <PatientHistory
            uploads={[
              buildUpload({
                measurements_new: 12,
                nibp_new: 3,
                measurements_reused: 50,
                nibp_reused: 10,
              }),
            ]}
            page={1}
            totalPages={1}
            totalCount={1}
            onPageChange={vi.fn()}
            onDeleteUpload={vi.fn()}
            deletingUploadId={null}
          />
        </MemoryRouter>,
      );
    });

    expect(container.textContent).toContain("New 15 | Reused 60");
  });
});
