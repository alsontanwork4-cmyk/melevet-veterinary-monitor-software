import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";

import { createStagedUpload, createUpload } from "../../api/endpoints";
import { Patient } from "../../types/api";
import { HelpTip } from "../help/HelpTip";
import { PatientAutocomplete } from "../patients/PatientAutocomplete";
import { helpTips } from "../../content/helpContent";

interface FileBundle {
  trendData: File | null;
  trendIndex: File | null;
  nibpData: File | null;
  nibpIndex: File | null;
}

const initialFiles: FileBundle = {
  trendData: null,
  trendIndex: null,
  nibpData: null,
  nibpIndex: null,
};

interface UploadFormProps {
  preSelectedPatient?: Patient | null;
}

interface BulkUploadBundle extends FileBundle {
  id: string;
  label: string;
  validationError: string | null;
}

interface BulkUploadResult {
  id: string;
  label: string;
  status: "queued" | "uploading" | "completed" | "error";
  uploadId?: number;
  error?: string;
}

function resolveBundleValidation(files: FileBundle): string | null {
  if (!files.trendData) {
    return "Missing TrendChartRecord.data";
  }
  const hasNibpData = Boolean(files.nibpData);
  const hasNibpIndex = Boolean(files.nibpIndex);
  if (hasNibpData !== hasNibpIndex) {
    return "NIBP files must be provided together.";
  }
  return null;
}

function buildBulkBundles(files: FileList): BulkUploadBundle[] {
  const groups = new Map<string, FileBundle>();
  const fileEntries = Array.from(files);

  for (const file of fileEntries) {
    const relativePath = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name;
    const pathParts = relativePath.split("/");
    const filename = pathParts[pathParts.length - 1].toLowerCase();
    const groupKey = pathParts.length > 1 ? pathParts.slice(0, -1).join("/") : "Selected files";
    const existing = groups.get(groupKey) ?? { ...initialFiles };

    if (filename === "trendchartrecord.data") existing.trendData = file;
    if (filename === "trendchartrecord.index") existing.trendIndex = file;
    if (filename === "nibprecord.data") existing.nibpData = file;
    if (filename === "nibprecord.index") existing.nibpIndex = file;

    groups.set(groupKey, existing);
  }

  return Array.from(groups.entries())
    .map(([label, bundle], index) => ({
      id: `${label}-${index}`,
      label,
      ...bundle,
      validationError: resolveBundleValidation(bundle),
    }))
    .filter((bundle) => Object.values(bundle).some((value) => value instanceof File))
    .sort((left, right) => left.label.localeCompare(right.label));
}

export function UploadForm({ preSelectedPatient }: UploadFormProps) {
  const navigate = useNavigate();
  const directoryInputRef = useRef<HTMLInputElement>(null);
  const [selectedPatient, setSelectedPatient] = useState<Patient | null>(preSelectedPatient ?? null);
  const [patientIdCode, setPatientIdCode] = useState("");
  const [patientName, setPatientName] = useState("");
  const [patientSpecies, setPatientSpecies] = useState("");
  const [files, setFiles] = useState<FileBundle>(initialFiles);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bulkBundles, setBulkBundles] = useState<BulkUploadBundle[]>([]);
  const [bulkResults, setBulkResults] = useState<BulkUploadResult[]>([]);
  const [bulkError, setBulkError] = useState<string | null>(null);
  const [isBulkSubmitting, setIsBulkSubmitting] = useState(false);

  const hasPreSelected = Boolean(preSelectedPatient);
  const effectivePatient = hasPreSelected ? preSelectedPatient : selectedPatient;

  useEffect(() => {
    directoryInputRef.current?.setAttribute("webkitdirectory", "");
    directoryInputRef.current?.setAttribute("directory", "");
  }, []);

  const fileValidationError = useMemo(() => {
    const validation = resolveBundleValidation(files);
    if (validation === "NIBP files must be provided together.") {
      return "NIBP upload needs both files: NibpRecord.data and NibpRecord.Index.";
    }
    return validation === "Missing TrendChartRecord.data" ? null : validation;
  }, [files]);

  const canSubmit = useMemo(() => {
    const hasTrendData = Boolean(files.trendData);
    if (!hasTrendData) {
      return false;
    }
    if (fileValidationError) {
      return false;
    }
    if (effectivePatient) {
      return true;
    }
    return Boolean(patientIdCode && patientName && patientSpecies);
  }, [files.trendData, fileValidationError, effectivePatient, patientIdCode, patientName, patientSpecies]);

  const canBulkSubmit = useMemo(() => {
    if (bulkBundles.length === 0 || bulkBundles.some((bundle) => bundle.validationError)) {
      return false;
    }
    if (effectivePatient) {
      return true;
    }
    return Boolean(patientIdCode && patientName && patientSpecies);
  }, [bulkBundles, effectivePatient, patientIdCode, patientName, patientSpecies]);

  function setFile(key: keyof FileBundle, file: File | null) {
    setFiles((current) => ({ ...current, [key]: file }));
  }

  function appendPatientFields(form: FormData) {
    if (effectivePatient) {
      form.append("patient_id", String(effectivePatient.id));
      return;
    }
    form.append("patient_id_code", patientIdCode);
    form.append("patient_name", patientName);
    form.append("patient_species", patientSpecies);
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!canSubmit) {
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      if (!files.trendData) {
        setError("Trend Chart upload needs file: TrendChartRecord.data.");
        return;
      }

      const form = new FormData();
      form.append("trend_data", files.trendData);
      if (files.trendIndex) {
        form.append("trend_index", files.trendIndex);
      }

      if (files.nibpData && files.nibpIndex) {
        form.append("nibp_data", files.nibpData);
        form.append("nibp_index", files.nibpIndex);
      }

      if (effectivePatient) {
        form.append("patient_id", String(effectivePatient.id));
      } else {
        appendPatientFields(form);
      }

      const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
      form.append("timezone", timezone);

      const response = await createStagedUpload(form);
      navigate(`/staged-uploads/${response.stage_id}/discovery`);
    } catch (submitError) {
      if (axios.isAxiosError(submitError)) {
        const detail = submitError.response?.data?.detail;
        if (typeof detail === "string" && detail.trim().length > 0) {
          setError(detail);
          return;
        }
      }
      setError(submitError instanceof Error ? submitError.message : "Upload failed");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleBulkSubmit(event: FormEvent) {
    event.preventDefault();
    if (!canBulkSubmit) {
      return;
    }

    setIsBulkSubmitting(true);
    setBulkError(null);
    const initialResults = bulkBundles.map((bundle) => ({ id: bundle.id, label: bundle.label, status: "queued" as const }));
    setBulkResults(initialResults);

    try {
      const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
      for (const bundle of bulkBundles) {
        setBulkResults((current) => current.map((result) => (
          result.id === bundle.id ? { ...result, status: "uploading" } : result
        )));

        const form = new FormData();
        if (!bundle.trendData) {
          throw new Error(`Missing TrendChartRecord.data for ${bundle.label}`);
        }
        form.append("trend_data", bundle.trendData);
        if (bundle.trendIndex) form.append("trend_index", bundle.trendIndex);
        if (bundle.nibpData && bundle.nibpIndex) {
          form.append("nibp_data", bundle.nibpData);
          form.append("nibp_index", bundle.nibpIndex);
        }
        appendPatientFields(form);
        form.append("timezone", timezone);

        try {
          const response = await createUpload(form);
          setBulkResults((current) => current.map((result) => (
            result.id === bundle.id
              ? { ...result, status: "completed", uploadId: response.upload.id }
              : result
          )));
        } catch (submitError) {
          const resolvedError = resolveSettingsLikeError(submitError, "Bulk upload failed");
          setBulkResults((current) => current.map((result) => (
            result.id === bundle.id
              ? { ...result, status: "error", error: resolvedError }
              : result
          )));
        }
      }
    } finally {
      setIsBulkSubmitting(false);
    }
  }

  function resolveSettingsLikeError(submitError: unknown, fallbackMessage: string): string {
    if (axios.isAxiosError(submitError)) {
      const detail = submitError.response?.data?.detail;
      if (typeof detail === "string" && detail.trim().length > 0) {
        return detail;
      }
    }
    return submitError instanceof Error ? submitError.message : fallbackMessage;
  }

  return (
    <div className="stack-lg">
      {!hasPreSelected && (
        <>
          <PatientAutocomplete onSelect={setSelectedPatient} />
          {selectedPatient && (
            <div className="card success-card">
              Reusing patient: <strong>{selectedPatient.patient_id_code}</strong> - {selectedPatient.name}
              <button type="button" className="text-button" onClick={() => setSelectedPatient(null)}>
                Use new patient instead
              </button>
            </div>
          )}
        </>
      )}

      <form className="card stack-md" onSubmit={onSubmit}>
        <h2>Upload Monitor Export</h2>
        <HelpTip {...helpTips.uploadRequirements} />
        <div>
          Required: Trend Chart data file. Optional: Trend Chart index file and NIBP file pair.
        </div>
        <div className="helper-text">
          Uploaded export files are staged temporarily for parsing. After import, Melevet keeps canonical decoded data and import history instead of preserving the raw export package.
        </div>
        {!effectivePatient && (
          <div className="grid grid-2">
            <label>
              Patient ID
              <input value={patientIdCode} onChange={(event) => setPatientIdCode(event.target.value)} required />
            </label>
            <label>
              Name
              <input value={patientName} onChange={(event) => setPatientName(event.target.value)} required />
            </label>
            <label>
              Species
              <input value={patientSpecies} onChange={(event) => setPatientSpecies(event.target.value)} required />
            </label>
          </div>
        )}

        <div className="grid grid-2">
          <label>
            Trend Chart Data File (TrendChartRecord.data)
            <input type="file" onChange={(event) => setFile("trendData", event.target.files?.[0] ?? null)} required />
          </label>
          <label>
            Trend Chart Index File (TrendChartRecord.Index)
            <input type="file" onChange={(event) => setFile("trendIndex", event.target.files?.[0] ?? null)} />
          </label>

          <label>
            NIBP Data File (NibpRecord.data)
            <input type="file" onChange={(event) => setFile("nibpData", event.target.files?.[0] ?? null)} />
          </label>
          <label>
            NIBP Index File (NibpRecord.Index)
            <input type="file" onChange={(event) => setFile("nibpIndex", event.target.files?.[0] ?? null)} />
          </label>
        </div>

        <button type="submit" disabled={!canSubmit || isSubmitting}>
          {isSubmitting ? "Staging files..." : "Stage Files and Analyze"}
        </button>

        {isSubmitting && <div className="spinner">Uploading raw files to temporary staging. Discovery starts after staging finishes.</div>}
        {fileValidationError && <div className="error">{fileValidationError}</div>}
        {error && <div className="error">{error}</div>}
      </form>

      <form className="card stack-md" onSubmit={handleBulkSubmit}>
        <h2>Bulk Import Folder</h2>
        <HelpTip {...helpTips.bulkImport} />
        <div className="helper-text">
          Select a folder containing one or more complete monitor export sets. Each set is queued and uploaded sequentially.
        </div>
        <label>
          Folder or grouped export files
          <input
            ref={directoryInputRef}
            type="file"
            multiple
            onChange={(event) => {
              const nextBundles = event.target.files ? buildBulkBundles(event.target.files) : [];
              setBulkBundles(nextBundles);
              setBulkResults([]);
              setBulkError(nextBundles.length === 0 ? "No complete record sets were found in the selected folder." : null);
            }}
          />
        </label>

        {bulkBundles.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th>Bundle</th>
                <th>Trend</th>
                <th>NIBP</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {bulkBundles.map((bundle) => {
                const result = bulkResults.find((entry) => entry.id === bundle.id);
                return (
                  <tr key={bundle.id}>
                    <td>{bundle.label}</td>
                    <td>{bundle.trendData ? "Ready" : "Missing"}</td>
                    <td>{bundle.nibpData && bundle.nibpIndex ? "Ready" : (bundle.nibpData || bundle.nibpIndex ? "Partial" : "Optional")}</td>
                    <td>
                      {bundle.validationError
                        ? bundle.validationError
                        : result?.status === "completed"
                          ? `Created upload #${result.uploadId}`
                          : result?.status === "error"
                            ? result.error
                            : result?.status ?? "Queued"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}

        <button type="submit" disabled={!canBulkSubmit || isBulkSubmitting}>
          {isBulkSubmitting ? "Processing queue..." : "Start Bulk Import"}
        </button>

        {bulkError && <div className="error">{bulkError}</div>}
      </form>
    </div>
  );
}
