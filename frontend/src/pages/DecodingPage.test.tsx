// @vitest-environment jsdom

import { act } from "react";
import { createRoot, Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DecodingPage } from "./DecodingPage";
import { createDecodeJob, downloadDecodeJob, getDecodeJob } from "../api/endpoints";


vi.mock("../api/endpoints", () => ({
  createDecodeJob: vi.fn(),
  getDecodeJob: vi.fn(),
  downloadDecodeJob: vi.fn(),
}));


const mockedCreateDecodeJob = vi.mocked(createDecodeJob);
const mockedGetDecodeJob = vi.mocked(getDecodeJob);
const mockedDownloadDecodeJob = vi.mocked(downloadDecodeJob);

let container: HTMLDivElement;
let root: Root;
let anchorClickSpy: ReturnType<typeof vi.fn>;
let createObjectUrlSpy: ReturnType<typeof vi.fn>;
let revokeObjectUrlSpy: ReturnType<typeof vi.fn>;

function setInputFiles(input: HTMLInputElement, files: File[]) {
  const fileList = {
    0: files[0],
    length: files.length,
    item: (index: number) => files[index] ?? null,
    [Symbol.iterator]: function* iterator() {
      for (const file of files) {
        yield file;
      }
    },
  } as unknown as FileList;

  Object.defineProperty(input, "files", {
    configurable: true,
    value: fileList,
  });
}

async function flushAsyncWork() {
  await act(async () => {
    await new Promise((resolve) => window.setTimeout(resolve, 0));
  });
}

async function waitFor(assertion: () => void) {
  const startedAt = Date.now();
  while (true) {
    try {
      assertion();
      return;
    } catch (error) {
      if (Date.now() - startedAt > 3000) {
        throw error;
      }
      await flushAsyncWork();
    }
  }
}

beforeEach(() => {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div");
  document.body.innerHTML = "";
  document.body.appendChild(container);
  root = createRoot(container);

  mockedCreateDecodeJob.mockReset();
  mockedGetDecodeJob.mockReset();
  mockedDownloadDecodeJob.mockReset();
  anchorClickSpy = vi.fn();
  createObjectUrlSpy = vi.fn(() => "blob:decoded-export");
  revokeObjectUrlSpy = vi.fn();

  HTMLAnchorElement.prototype.click = anchorClickSpy;
  window.URL.createObjectURL = createObjectUrlSpy;
  window.URL.revokeObjectURL = revokeObjectUrlSpy;
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  vi.useRealTimers();
});

describe("DecodingPage", () => {
  it("blocks submit when a pair is incomplete", async () => {
    await act(async () => {
      root.render(<DecodingPage />);
    });

    const fileInputs = Array.from(container.querySelectorAll('input[type="file"]')) as HTMLInputElement[];
    expect(fileInputs).toHaveLength(6);

    const trendDataInput = fileInputs[0];
    setInputFiles(trendDataInput, [new File(["trend"], "TrendChartRecord.data")]);
    await act(async () => {
      trendDataInput.dispatchEvent(new Event("change", { bubbles: true }));
    });

    const submitButton = Array.from(container.querySelectorAll("button")).find((button) =>
      button.textContent?.includes("Decode and Download Excel"),
    );
    expect(submitButton).not.toBeNull();

    await act(async () => {
      submitButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    await waitFor(() => {
      expect(container.textContent).toContain("Trend Chart requires both the .data and .Index files.");
      expect(mockedCreateDecodeJob).not.toHaveBeenCalled();
    });
  });

  it("shows progress and downloads the archive after the decode job completes", async () => {
    vi.useFakeTimers();

    mockedCreateDecodeJob.mockResolvedValue({
      id: "job-1",
      status: "processing",
      progress_percent: 12,
      phase: "Starting decode",
      detail: "Preparing selected record families",
      filename: "decoded-records.zip",
      error_message: null,
      selected_families: ["Trend Chart"],
      created_at: "2026-03-07T00:00:00Z",
      updated_at: "2026-03-07T00:00:00Z",
    });
    mockedGetDecodeJob.mockResolvedValue({
      id: "job-1",
      status: "completed",
      progress_percent: 100,
      phase: "Ready to download",
      detail: "Decoded workbooks are ready",
      filename: "decoded-records.zip",
      error_message: null,
      selected_families: ["Trend Chart"],
      created_at: "2026-03-07T00:00:00Z",
      updated_at: "2026-03-07T00:00:02Z",
    });
    mockedDownloadDecodeJob.mockResolvedValue({
      blob: new Blob(["zip-content"], { type: "application/zip" }),
      filename: "decoded-records.zip",
    });

    await act(async () => {
      root.render(<DecodingPage />);
    });

    const fileInputs = Array.from(container.querySelectorAll('input[type="file"]')) as HTMLInputElement[];
    const trendDataInput = fileInputs[0];
    const trendIndexInput = fileInputs[1];

    setInputFiles(trendDataInput, [new File(["trend"], "TrendChartRecord.data")]);
    setInputFiles(trendIndexInput, [new File(["index"], "TrendChartRecord.Index")]);

    await act(async () => {
      trendDataInput.dispatchEvent(new Event("change", { bubbles: true }));
      trendIndexInput.dispatchEvent(new Event("change", { bubbles: true }));
    });

    const submitButton = Array.from(container.querySelectorAll("button")).find((button) =>
      button.textContent?.includes("Decode and Download Excel"),
    );
    expect(submitButton).not.toBeNull();

    await act(async () => {
      submitButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    await waitFor(() => {
      expect(mockedCreateDecodeJob).toHaveBeenCalledTimes(1);
      expect(container.textContent).toContain("Starting decode");
      expect(container.textContent).toContain("12%");
    });

    await act(async () => {
      vi.advanceTimersByTime(900);
    });

    await waitFor(() => {
      expect(mockedGetDecodeJob).toHaveBeenCalledTimes(1);
      expect(mockedDownloadDecodeJob).toHaveBeenCalledWith("job-1");
      expect(createObjectUrlSpy).toHaveBeenCalledTimes(1);
      expect(anchorClickSpy).toHaveBeenCalledTimes(1);
      expect(revokeObjectUrlSpy).toHaveBeenCalledTimes(1);
      expect(container.textContent).toContain("Downloaded decoded-records.zip");
    });
  });
});
