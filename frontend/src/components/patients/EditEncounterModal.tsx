import { FormEvent, useEffect, useState } from "react";
import axios from "axios";

import { updateEncounter } from "../../api/endpoints";
import { Encounter, EncounterUpdatePayload } from "../../types/api";
import { encounterDisplayLabel } from "../../utils/encounters";
import { ModalCard } from "../layout/ModalCard";

interface EditEncounterModalProps {
  open: boolean;
  encounter: Encounter | null;
  onClose: () => void;
  onUpdated: (encounter: Encounter) => Promise<void> | void;
}

interface EditEncounterFormState {
  encounterDateLocal: string;
  label: string;
  notes: string;
}

const initialState: EditEncounterFormState = {
  encounterDateLocal: "",
  label: "",
  notes: "",
};

export function EditEncounterModal({ open, encounter, onClose, onUpdated }: EditEncounterModalProps) {
  const [form, setForm] = useState<EditEncounterFormState>(initialState);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (!open || encounter === null) {
      return;
    }

    setForm({
      encounterDateLocal: encounter.encounter_date_local,
      label: encounter.label ?? "",
      notes: encounter.notes ?? "",
    });
    setError(null);
    setIsSubmitting(false);
  }, [encounter, open]);

  function setField<K extends keyof EditEncounterFormState>(key: K, value: EditEncounterFormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (encounter === null || isSubmitting) {
      return;
    }

    const encounterDateLocal = form.encounterDateLocal.trim();
    if (!encounterDateLocal) {
      setError("Encounter date is required.");
      return;
    }

    const payload: EncounterUpdatePayload = {
      encounter_date_local: encounterDateLocal,
      timezone: encounter.timezone,
      label: form.label.trim() || null,
      notes: form.notes.trim() || null,
    };

    setIsSubmitting(true);
    setError(null);
    try {
      const updatedEncounter = await updateEncounter(encounter.id, payload);
      await onUpdated(updatedEncounter);
      onClose();
    } catch (submitError) {
      if (axios.isAxiosError(submitError)) {
        const detail = submitError.response?.data?.detail;
        if (typeof detail === "string" && detail.trim().length > 0) {
          setError(detail);
        } else {
          setError("Unable to update encounter.");
        }
      } else {
        setError(submitError instanceof Error ? submitError.message : "Unable to update encounter.");
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  const title = encounter ? `Edit ${encounterDisplayLabel(encounter)}` : "Edit Encounter";

  return (
    <ModalCard open={open} title={title} onClose={onClose} closeDisabled={isSubmitting}>
      <form className="stack-md" onSubmit={onSubmit}>
        <div className="grid grid-2">
          <label>
            Encounter date
            <input
              autoFocus
              type="date"
              value={form.encounterDateLocal}
              onChange={(event) => setField("encounterDateLocal", event.target.value)}
              required
              disabled={isSubmitting}
            />
          </label>
          <label>
            Label (optional)
            <input
              value={form.label}
              onChange={(event) => setField("label", event.target.value)}
              maxLength={128}
              disabled={isSubmitting}
            />
          </label>
        </div>

        <label>
          Notes (optional)
          <textarea
            value={form.notes}
            onChange={(event) => setField("notes", event.target.value)}
            rows={4}
            disabled={isSubmitting}
          />
        </label>

        <div className="helper-text">Timezone: {encounter?.timezone ?? "-"}</div>

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
