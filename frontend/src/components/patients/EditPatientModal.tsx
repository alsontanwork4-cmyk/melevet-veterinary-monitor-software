import { FormEvent, useEffect, useState } from "react";
import axios from "axios";

import { createEncounterFromUpload, deleteEncounter, updatePatient } from "../../api/endpoints";
import { PatientAvailableReportDate, PatientUpdatePayload, PatientWithUploadCount } from "../../types/api";
import { sanitizeDigits, shouldAllowNumericKey } from "../../utils/numericInput";
import { formatEncounterDateLabel } from "../../utils/encounters";
import { getAgeFromNotes, getGenderFromNotes, removeAgeFromNotes, setGenderInNotes } from "../../utils/patientNotes";
import { ModalCard } from "../layout/ModalCard";

interface EditPatientModalProps {
  open: boolean;
  patient: PatientWithUploadCount | null;
  reportDateOptions: PatientAvailableReportDate[];
  onClose: () => void;
  onUpdated: () => Promise<void> | void;
}

interface EditPatientFormState {
  patientIdCode: string;
  name: string;
  species: string;
  age: string;
  gender: string;
  clientName: string;
  selectedReportDate: string;
}

const initialState: EditPatientFormState = {
  patientIdCode: "",
  name: "",
  species: "",
  age: "",
  gender: "",
  clientName: "",
  selectedReportDate: "",
};

function resolveInitialSelectedReportDate(
  patient: PatientWithUploadCount,
  reportDateOptions: PatientAvailableReportDate[],
): string {
  if (patient.preferred_encounter_id !== null) {
    const preferredOption = reportDateOptions.find((option) => option.encounter_id === patient.preferred_encounter_id);
    if (preferredOption) {
      return preferredOption.encounter_date_local;
    }
  }

  const currentReportDate = patient.report_date ?? patient.latest_report_date ?? null;
  if (currentReportDate) {
    const matchingOption = reportDateOptions.find((option) => option.encounter_date_local === currentReportDate);
    if (matchingOption) {
      return matchingOption.encounter_date_local;
    }
  }

  return reportDateOptions[0]?.encounter_date_local ?? "";
}

function resolveAttachedEncounterId(
  patient: PatientWithUploadCount,
  reportDateOptions: PatientAvailableReportDate[],
): number | null {
  if (patient.preferred_encounter_id !== null) {
    return patient.preferred_encounter_id;
  }

  const currentReportDate = patient.report_date ?? null;
  if (!currentReportDate) {
    return null;
  }

  const matchingOption = reportDateOptions.find(
    (option) => option.encounter_date_local === currentReportDate && option.encounter_id !== null,
  );
  return matchingOption?.encounter_id ?? null;
}

export function EditPatientModal({ open, patient, reportDateOptions, onClose, onUpdated }: EditPatientModalProps) {
  const [form, setForm] = useState<EditPatientFormState>(initialState);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (!open || !patient) {
      return;
    }

    setForm({
      patientIdCode: patient.patient_id_code,
      name: patient.name,
      species: patient.species,
      age: patient.age ?? getAgeFromNotes(patient.notes),
      gender: getGenderFromNotes(patient.notes),
      clientName: patient.owner_name ?? "",
      selectedReportDate: resolveInitialSelectedReportDate(patient, reportDateOptions),
    });
    setError(null);
    setIsSubmitting(false);
  }, [open, patient, reportDateOptions]);

  function setField<K extends keyof EditPatientFormState>(key: K, value: EditPatientFormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function onNumericKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (!shouldAllowNumericKey(event)) {
      event.preventDefault();
    }
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!patient || isSubmitting) {
      return;
    }

    const patientIdCode = form.patientIdCode.trim();
    const name = form.name.trim();
    const species = form.species.trim();
    const age = form.age.trim();
    const gender = form.gender.trim();
    const clientName = form.clientName.trim();
    if (!patientIdCode || !name || !species || !gender || !clientName) {
      setError("Patient ID, patient name, species, gender, and client name are required.");
      return;
    }

    const selectedReportDate = form.selectedReportDate.trim();
    const selectedReportDateOption = reportDateOptions.find((option) => option.encounter_date_local === selectedReportDate);
    if (!selectedReportDateOption) {
      setError("Selected report date is invalid.");
      return;
    }

    const basePayload: PatientUpdatePayload = {
      patient_id_code: patientIdCode,
      name,
      species,
      age: age || null,
      owner_name: clientName,
      notes: setGenderInNotes(removeAgeFromNotes(patient.notes), gender),
    };

    setIsSubmitting(true);
    setError(null);
    try {
      const previousEncounterId = resolveAttachedEncounterId(patient, reportDateOptions);
      let preferredEncounterId = selectedReportDateOption.encounter_id;
      if (preferredEncounterId === null) {
        await updatePatient(patient.id, basePayload);
        const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
        const createdEncounter = await createEncounterFromUpload(selectedReportDateOption.upload_id, {
          patient_id: patient.id,
          encounter_date_local: selectedReportDateOption.encounter_date_local,
          timezone,
        });
        preferredEncounterId = createdEncounter.id;
        await updatePatient(patient.id, { preferred_encounter_id: preferredEncounterId });
      } else {
        await updatePatient(patient.id, {
          ...basePayload,
          preferred_encounter_id: preferredEncounterId,
        });
      }
      if (previousEncounterId !== null && previousEncounterId !== preferredEncounterId) {
        await deleteEncounter(previousEncounterId);
      }
      await onUpdated();
      onClose();
    } catch (submitError) {
      if (axios.isAxiosError(submitError)) {
        const detail = submitError.response?.data?.detail;
        if (typeof detail === "string" && detail.trim().length > 0) {
          setError(detail);
        } else {
          setError("Unable to update patient.");
        }
      } else {
        setError(submitError instanceof Error ? submitError.message : "Unable to update patient.");
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  const title = patient ? "Edit Patient " + patient.patient_id_code : "Edit Patient";

  return (
    <ModalCard open={open} title={title} onClose={onClose} closeDisabled={isSubmitting}>
      <form className="stack-md" onSubmit={onSubmit}>
        <div className="grid grid-2">
          <label>
            Patient ID
            <input
              autoFocus
              value={form.patientIdCode}
              onChange={(event) => setField("patientIdCode", event.target.value)}
              required
              disabled={isSubmitting}
            />
          </label>
          <label>
            Patient Name
            <input
              value={form.name}
              onChange={(event) => setField("name", event.target.value)}
              required
              disabled={isSubmitting}
            />
          </label>
          <label>
            Species
            <input value={form.species} onChange={(event) => setField("species", event.target.value)} required disabled={isSubmitting} />
          </label>
          <label>
            Age
            <input
              value={form.age}
              onChange={(event) => setField("age", sanitizeDigits(event.target.value))}
              onKeyDown={onNumericKeyDown}
              inputMode="numeric"
              pattern="[0-9]*"
              disabled={isSubmitting}
            />
          </label>
          <label>
            Gender
            <input value={form.gender} onChange={(event) => setField("gender", event.target.value)} required disabled={isSubmitting} />
          </label>
          <label>
            Client Name
            <input value={form.clientName} onChange={(event) => setField("clientName", event.target.value)} required disabled={isSubmitting} />
          </label>
          <label>
            Report Date
            <select
              value={form.selectedReportDate}
              onChange={(event) => setField("selectedReportDate", event.target.value)}
              disabled={isSubmitting || reportDateOptions.length === 0}
            >
              {reportDateOptions.map((option) => (
                <option key={`${option.upload_id}-${option.encounter_date_local}`} value={option.encounter_date_local}>
                  {formatEncounterDateLabel(option.encounter_date_local)}
                  {option.is_saved ? "" : " (detected)"}
                </option>
              ))}
            </select>
          </label>
        </div>
        {reportDateOptions.length === 0 && <div className="helper-text">No detected report date is available for this patient yet.</div>}
        <div className="modal-actions">
          <button type="button" className="button-muted" onClick={onClose} disabled={isSubmitting}>
            Cancel
          </button>
          <button type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Saving..." : "Save Changes"}
          </button>
        </div>
        {error && <div className="error">{error}</div>}
      </form>
    </ModalCard>
  );
}
