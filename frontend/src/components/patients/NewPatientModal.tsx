import { FormEvent, useEffect, useState } from "react";
import axios from "axios";

import { createPatient } from "../../api/endpoints";
import { Patient, PatientCreatePayload } from "../../types/api";
import { sanitizeDigits, shouldAllowNumericKey } from "../../utils/numericInput";
import { ModalCard } from "../layout/ModalCard";

interface NewPatientModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: (patient: Patient) => Promise<void> | void;
}

interface NewPatientFormState {
  patientIdCode: string;
  clientName: string;
  tel: string;
  petName: string;
  speciesChoice: "" | "dog" | "cat" | "rabbit" | "other";
  otherSpecies: string;
  gender: "" | "male" | "female" | "other";
  age: string;
  notes: string;
}

const initialState: NewPatientFormState = {
  patientIdCode: "",
  clientName: "",
  tel: "",
  petName: "",
  speciesChoice: "",
  otherSpecies: "",
  gender: "",
  age: "",
  notes: "",
};

function generatePatientIdCode(): string {
  const random = Math.random().toString(36).slice(2, 8).toUpperCase();
  return `AUTO-${Date.now()}-${random}`;
}

export function NewPatientModal({ open, onClose, onCreated }: NewPatientModalProps) {
  const [form, setForm] = useState<NewPatientFormState>(initialState);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (open) {
      setForm(initialState);
      setError(null);
      setIsSubmitting(false);
    }
  }, [open]);

  function setField<K extends keyof NewPatientFormState>(key: K, value: NewPatientFormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function onNumericKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (!shouldAllowNumericKey(event)) {
      event.preventDefault();
    }
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (isSubmitting) {
      return;
    }

    const providedPatientIdCode = form.patientIdCode.trim();
    const patientIdCode = providedPatientIdCode.length > 0 ? providedPatientIdCode : generatePatientIdCode();
    const clientName = form.clientName.trim();
    const petName = form.petName.trim();
    const tel = form.tel.trim();
    const age = form.age.trim();
    const species =
      form.speciesChoice === "other"
        ? form.otherSpecies.trim()
        : form.speciesChoice === "dog"
          ? "Dog"
          : form.speciesChoice === "cat"
            ? "Cat"
            : form.speciesChoice === "rabbit"
              ? "Rabbit"
            : "";
    const gender =
      form.gender === "male"
        ? "Male"
        : form.gender === "female"
          ? "Female"
          : form.gender === "other"
              ? "Other"
              : "";

    if (!clientName || !petName || !species || !gender) {
      setError("Client name, patient name, species, and gender are required.");
      return;
    }

    const noteLines: string[] = [`Gender: ${gender}`];
    if (tel) {
      noteLines.push(`Tel: ${tel}`);
    }
    const userNotes = form.notes.trim();
    if (userNotes) {
      noteLines.push("", userNotes);
    }
    const composedNotes = noteLines.join("\n");

    const payload: PatientCreatePayload = {
      patient_id_code: patientIdCode,
      name: petName,
      species,
      age: age || null,
      owner_name: clientName,
      notes: composedNotes,
    };

    setIsSubmitting(true);
    setError(null);
    try {
      const patient = await createPatient(payload);
      await onCreated(patient);
      onClose();
    } catch (submitError) {
      if (axios.isAxiosError(submitError)) {
        const detail = submitError.response?.data?.detail;
        if (typeof detail === "string" && detail.trim().length > 0) {
          setError(detail);
        } else {
          setError("Unable to create patient.");
        }
      } else {
        setError(submitError instanceof Error ? submitError.message : "Unable to create patient.");
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <ModalCard open={open} title="New Patient" onClose={onClose} closeDisabled={isSubmitting}>
      <form className="stack-md" onSubmit={onSubmit}>
        <div className="grid grid-2">
          <label>
            Patient ID (optional)
            <input
              autoFocus
              value={form.patientIdCode}
              onChange={(event) => setField("patientIdCode", event.target.value)}
              disabled={isSubmitting}
            />
          </label>
          <label>
            Client Name
            <input
              value={form.clientName}
              onChange={(event) => setField("clientName", event.target.value)}
              required
              disabled={isSubmitting}
            />
          </label>
          <label>
            Tel (optional)
            <input
              value={form.tel}
              onChange={(event) => setField("tel", sanitizeDigits(event.target.value))}
              onKeyDown={onNumericKeyDown}
              inputMode="numeric"
              pattern="[0-9]*"
              disabled={isSubmitting}
            />
          </label>
          <label>
            Patient Name
            <input value={form.petName} onChange={(event) => setField("petName", event.target.value)} required disabled={isSubmitting} />
          </label>
          <label>
            Species
            <select
              value={form.speciesChoice}
              onChange={(event) => {
                const speciesChoice = event.target.value as NewPatientFormState["speciesChoice"];
                setForm((current) => ({
                  ...current,
                  speciesChoice,
                  otherSpecies: speciesChoice === "other" ? current.otherSpecies : "",
                }));
              }}
              required
              disabled={isSubmitting}
            >
              <option value="">Select species</option>
              <option value="dog">Dog</option>
              <option value="cat">Cat</option>
              <option value="rabbit">Rabbit</option>
              <option value="other">Other</option>
            </select>
            {form.speciesChoice === "other" && (
              <input
                placeholder="Type other species"
                value={form.otherSpecies}
                onChange={(event) => setField("otherSpecies", event.target.value)}
                disabled={isSubmitting}
                required
              />
            )}
          </label>
          <label>
            Gender
            <select value={form.gender} onChange={(event) => setField("gender", event.target.value as NewPatientFormState["gender"])} required disabled={isSubmitting}>
              <option value="">Select gender</option>
              <option value="male">Male</option>
              <option value="female">Female</option>
              <option value="other">Other</option>
            </select>
          </label>
          <label>
            Age (optional)
            <input
              value={form.age}
              onChange={(event) => setField("age", sanitizeDigits(event.target.value))}
              onKeyDown={onNumericKeyDown}
              inputMode="numeric"
              pattern="[0-9]*"
              disabled={isSubmitting}
            />
          </label>
        </div>

        <label>
          Notes (optional)
          <textarea value={form.notes} onChange={(event) => setField("notes", event.target.value)} rows={3} disabled={isSubmitting} />
        </label>

        <div className="modal-actions">
          <button type="button" className="button-muted" onClick={onClose} disabled={isSubmitting}>
            Cancel
          </button>
          <button type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Creating..." : "Create Patient"}
          </button>
        </div>
        {error && <div className="error">{error}</div>}
      </form>
    </ModalCard>
  );
}
