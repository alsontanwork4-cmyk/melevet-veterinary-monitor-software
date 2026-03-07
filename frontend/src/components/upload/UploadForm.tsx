import { FormEvent, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";

import { createUpload } from "../../api/endpoints";
import { Patient } from "../../types/api";
import { PatientAutocomplete } from "../patients/PatientAutocomplete";

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

export function UploadForm({ preSelectedPatient }: UploadFormProps) {
  const navigate = useNavigate();
  const [selectedPatient, setSelectedPatient] = useState<Patient | null>(preSelectedPatient ?? null);
  const [patientIdCode, setPatientIdCode] = useState("");
  const [patientName, setPatientName] = useState("");
  const [patientSpecies, setPatientSpecies] = useState("");
  const [files, setFiles] = useState<FileBundle>(initialFiles);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const hasPreSelected = Boolean(preSelectedPatient);
  const effectivePatient = hasPreSelected ? preSelectedPatient : selectedPatient;

  const fileValidationError = useMemo(() => {
    const hasNibpData = Boolean(files.nibpData);
    const hasNibpIndex = Boolean(files.nibpIndex);
    if (hasNibpData !== hasNibpIndex) {
      return "NIBP upload needs both files: NibpRecord.data and NibpRecord.Index.";
    }

    return null;
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

  function setFile(key: keyof FileBundle, file: File | null) {
    setFiles((current) => ({ ...current, [key]: file }));
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
        form.append("patient_id_code", patientIdCode);
        form.append("patient_name", patientName);
        form.append("patient_species", patientSpecies);
      }

      const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
      form.append("timezone", timezone);

      const response = await createUpload(form);
      const query = new URLSearchParams();
      query.set("patientId", String(response.patient_id));
      if (response.reused_existing) {
        query.set("reused", "1");
      }
      if (response.exact_duplicate) {
        query.set("exactDuplicate", "1");
      }
      navigate(`/uploads/${response.upload.id}/discovery?${query.toString()}`);
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
        <div>
          Required: Trend Chart data file. Optional: Trend Chart index file and NIBP file pair.
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
          {isSubmitting ? "Parsing files..." : "Upload and Analyze"}
        </button>

        {isSubmitting && <div className="spinner">Parsing and storing data. Large files can take several minutes. Live progress appears on the discovery page.</div>}
        {fileValidationError && <div className="error">{fileValidationError}</div>}
        {error && <div className="error">{error}</div>}
      </form>
    </div>
  );
}
