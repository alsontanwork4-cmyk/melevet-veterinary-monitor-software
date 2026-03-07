import { useEffect, useState } from "react";

import { searchPatients } from "../../api/endpoints";
import { Patient } from "../../types/api";

interface PatientAutocompleteProps {
  onSelect: (patient: Patient) => void;
}

export function PatientAutocomplete({ onSelect }: PatientAutocompleteProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Patient[]>([]);

  useEffect(() => {
    if (query.trim().length < 2) {
      setResults([]);
      return;
    }

    const controller = new AbortController();
    const run = async () => {
      const items = await searchPatients(query.trim());
      if (!controller.signal.aborted) {
        setResults(items);
      }
    };

    run().catch(() => setResults([]));
    return () => controller.abort();
  }, [query]);

  return (
    <div className="card">
      <h3>Find Existing Patient</h3>
      <input
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Search by patient ID or name"
      />
      {results.length > 0 && (
        <ul className="list-simple">
          {results.map((patient) => (
            <li key={patient.id}>
              <button type="button" className="text-button" onClick={() => onSelect(patient)}>
                {patient.patient_id_code} - {patient.name} ({patient.species})
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}