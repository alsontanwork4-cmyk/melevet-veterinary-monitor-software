import { FormEvent, RefObject, useEffect, useRef, useState } from "react";
import axios from "axios";

import { DecodeJob, createDecodeJob, downloadDecodeJob, getDecodeJob } from "../api/endpoints";

interface DecodeFiles {
  trendData: File | null;
  trendIndex: File | null;
  nibpData: File | null;
  nibpIndex: File | null;
}

const initialFiles: DecodeFiles = {
  trendData: null,
  trendIndex: null,
  nibpData: null,
  nibpIndex: null,
};

function decodePairError(label: string, dataFile: File | null, indexFile: File | null): string | null {
  if (!dataFile && !indexFile) {
    return null;
  }
  if (!dataFile || !indexFile) {
    return `${label} requires both the .data and .Index files.`;
  }
  return null;
}

async function resolveDecodeError(error: unknown): Promise<string> {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data;
    if (detail instanceof Blob) {
      const text = await detail.text();
      if (text) {
        try {
          const parsed = JSON.parse(text) as { detail?: string };
          if (typeof parsed.detail === "string" && parsed.detail.trim().length > 0) {
            return parsed.detail;
          }
          return text;
        } catch {
          return text;
        }
      }
    }
  }

  if (error instanceof Error && error.message.trim().length > 0) {
    return error.message;
  }

  return "Decoding failed.";
}

export function DecodingPage() {
  const [files, setFiles] = useState<DecodeFiles>(initialFiles);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [activeJob, setActiveJob] = useState<DecodeJob | null>(null);
  const downloadedJobIdRef = useRef<string | null>(null);

  const trendDataRef = useRef<HTMLInputElement>(null);
  const trendIndexRef = useRef<HTMLInputElement>(null);
  const nibpDataRef = useRef<HTMLInputElement>(null);
  const nibpIndexRef = useRef<HTMLInputElement>(null);
  const inputRefs: Record<keyof DecodeFiles, RefObject<HTMLInputElement | null>> = {
    trendData: trendDataRef,
    trendIndex: trendIndexRef,
    nibpData: nibpDataRef,
    nibpIndex: nibpIndexRef,
  };

  const validationErrors = [
    decodePairError("Trend Chart", files.trendData, files.trendIndex),
    decodePairError("NIBP", files.nibpData, files.nibpIndex),
  ].filter((value): value is string => value !== null);

  let selectedPairCount = 0;
  if (files.trendData && files.trendIndex) {
    selectedPairCount += 1;
  }
  if (files.nibpData && files.nibpIndex) {
    selectedPairCount += 1;
  }

  let formError: string | null = null;
  if (validationErrors.length > 0) {
    formError = validationErrors[0];
  } else if (selectedPairCount === 0) {
    formError = "Upload at least one complete record pair to decode.";
  }

  const isBusy = isSubmitting || activeJob !== null || isDownloading;
  const progressPercent = activeJob ? activeJob.progress_percent : uploadProgress;
  const progressPhase = activeJob
    ? activeJob.phase
    : isSubmitting
      ? "Uploading files"
      : isDownloading
        ? "Downloading archive"
        : null;
  const progressDetail = activeJob
    ? activeJob.detail
    : isSubmitting
      ? "Sending selected files to the decode worker"
      : isDownloading
        ? "Saving the ZIP archive to your device"
        : null;

  useEffect(() => {
    if (!activeJob || (activeJob.status !== "processing" && activeJob.status !== "queued")) {
      return;
    }

    const timer = window.setTimeout(async () => {
      try {
        const nextJob = await getDecodeJob(activeJob.id);
        setActiveJob(nextJob);
      } catch (pollError) {
        setError(await resolveDecodeError(pollError));
        setActiveJob(null);
        setIsSubmitting(false);
      }
    }, 800);

    return () => window.clearTimeout(timer);
  }, [activeJob]);

  useEffect(() => {
    async function downloadCompletedJob(job: DecodeJob) {
      if (downloadedJobIdRef.current === job.id) {
        return;
      }
      downloadedJobIdRef.current = job.id;
      setIsDownloading(true);

      try {
        const result = await downloadDecodeJob(job.id);
        const filename = result.filename ?? "decoded-records.zip";
        const url = window.URL.createObjectURL(result.blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        window.URL.revokeObjectURL(url);

        setSuccessMessage(`Downloaded ${filename}`);
      } catch (downloadError) {
        setError(await resolveDecodeError(downloadError));
      } finally {
        setIsDownloading(false);
        setIsSubmitting(false);
        setActiveJob(null);
        setUploadProgress(0);
      }
    }

    if (!activeJob) {
      return;
    }

    if (activeJob.status === "completed") {
      void downloadCompletedJob(activeJob);
      return;
    }

    if (activeJob.status === "error") {
      setError(activeJob.error_message ?? "Decoding failed.");
      setIsDownloading(false);
      setIsSubmitting(false);
      setActiveJob(null);
      setUploadProgress(0);
    }
  }, [activeJob]);

  function setFile(key: keyof DecodeFiles, file: File | null) {
    setError(null);
    setSuccessMessage(null);
    setFiles((current) => ({ ...current, [key]: file }));
  }

  function clearFile(key: keyof DecodeFiles) {
    const ref = inputRefs[key];
    if (ref.current) {
      ref.current.value = "";
    }
    setFile(key, null);
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (formError) {
      setError(formError);
      return;
    }

    setIsSubmitting(true);
    setError(null);
    setSuccessMessage(null);
    setUploadProgress(0);
    setActiveJob(null);
    downloadedJobIdRef.current = null;

    try {
      const form = new FormData();
      if (files.trendData && files.trendIndex) {
        form.append("trend_data", files.trendData);
        form.append("trend_index", files.trendIndex);
      }
      if (files.nibpData && files.nibpIndex) {
        form.append("nibp_data", files.nibpData);
        form.append("nibp_index", files.nibpIndex);
      }
      form.append("timezone", Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC");

      const job = await createDecodeJob(form, (progress) => {
        setUploadProgress(progress);
      });
      setActiveJob(job);
    } catch (submitError) {
      setError(await resolveDecodeError(submitError));
      setUploadProgress(0);
      setIsSubmitting(false);
    }
  }

  return (
    <div className="decode-page stack-lg">
      <div className="page-header">
        <div className="stack-md">
          <h1>Decoding</h1>
          <p className="helper-text decode-subtitle">
            Upload any complete monitor record pair to decode it into Excel workbooks. Files are processed only for this download and are not stored in the patient database.
          </p>
        </div>
      </div>

      <form className="card stack-lg" onSubmit={handleSubmit}>
        <div className="decode-pair-grid">
          <div className="decode-pair-card stack-md">
            <h3>Trend Chart</h3>
            <label>
              TrendChartRecord.data
              <div className="file-input-row">
                <input ref={trendDataRef} type="file" onChange={(event) => setFile("trendData", event.target.files?.[0] ?? null)} disabled={isBusy} />
                {files.trendData && (
                  <button type="button" className="file-remove-btn" onClick={() => clearFile("trendData")} disabled={isBusy} aria-label="Remove TrendChartRecord.data">X</button>
                )}
              </div>
            </label>
            <label>
              TrendChartRecord.Index
              <div className="file-input-row">
                <input ref={trendIndexRef} type="file" onChange={(event) => setFile("trendIndex", event.target.files?.[0] ?? null)} disabled={isBusy} />
                {files.trendIndex && (
                  <button type="button" className="file-remove-btn" onClick={() => clearFile("trendIndex")} disabled={isBusy} aria-label="Remove TrendChartRecord.Index">X</button>
                )}
              </div>
            </label>
          </div>

          <div className="decode-pair-card stack-md">
            <h3>NIBP</h3>
            <label>
              NibpRecord.data
              <div className="file-input-row">
                <input ref={nibpDataRef} type="file" onChange={(event) => setFile("nibpData", event.target.files?.[0] ?? null)} disabled={isBusy} />
                {files.nibpData && (
                  <button type="button" className="file-remove-btn" onClick={() => clearFile("nibpData")} disabled={isBusy} aria-label="Remove NibpRecord.data">X</button>
                )}
              </div>
            </label>
            <label>
              NibpRecord.Index
              <div className="file-input-row">
                <input ref={nibpIndexRef} type="file" onChange={(event) => setFile("nibpIndex", event.target.files?.[0] ?? null)} disabled={isBusy} />
                {files.nibpIndex && (
                  <button type="button" className="file-remove-btn" onClick={() => clearFile("nibpIndex")} disabled={isBusy} aria-label="Remove NibpRecord.Index">X</button>
                )}
              </div>
            </label>
          </div>

        </div>

        <div className="decode-summary card compact-card">
          <strong>{selectedPairCount}</strong> complete pair{selectedPairCount === 1 ? "" : "s"} ready for export.
        </div>

        {(isSubmitting || activeJob || isDownloading) && (
          <div className="card compact-card decode-progress-card stack-md">
            <div className="row-between">
              <strong>{progressPhase ?? "Preparing decode job"}</strong>
              <span className="decode-progress-percent">{progressPercent}%</span>
            </div>
            <div className="progress-track" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progressPercent}>
              <div className="progress-fill" style={{ width: `${progressPercent}%` }} />
            </div>
            {progressDetail && <div className="helper-text">{progressDetail}</div>}
          </div>
        )}

        <div className="row-between decode-actions">
          <button type="submit" disabled={validationErrors.length > 0 || selectedPairCount === 0 || isBusy}>
            {isBusy ? "Decoding..." : "Decode and Download Excel"}
          </button>
          <span className="helper-text">The download is a single ZIP containing one XLSX workbook per decoded record family.</span>
        </div>

        {validationErrors.length > 0 && <div className="error">{formError}</div>}
        {error && <div className="error">{error}</div>}
        {successMessage && <div className="helper-text">{successMessage}</div>}
      </form>
    </div>
  );
}
