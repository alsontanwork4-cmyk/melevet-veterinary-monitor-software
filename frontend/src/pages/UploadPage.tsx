import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { getPatient } from "../api/endpoints";
import { Breadcrumb } from "../components/layout/Breadcrumb";
import { UploadForm } from "../components/upload/UploadForm";

export function UploadPage() {
  const { patientId } = useParams();
  const parsedPatientId = patientId ? Number(patientId) : null;

  const patientQuery = useQuery({
    queryKey: ["patient", parsedPatientId],
    queryFn: () => getPatient(parsedPatientId as number),
    enabled: parsedPatientId !== null && Number.isFinite(parsedPatientId),
  });

  const patient = patientQuery.data ?? null;
  const isExistingPatient = parsedPatientId !== null;

  if (isExistingPatient && patientQuery.isLoading) {
    return <div className="card">Loading patient...</div>;
  }

  if (isExistingPatient && patientQuery.isError) {
    return <div className="card error">Unable to load patient details.</div>;
  }

  return (
    <div className="stack-md">
      {patient ? (
        <Breadcrumb
          items={[
            { label: "Patients", to: "/patients" },
            { label: `${patient.name} (${patient.species})` },
            { label: "Upload Data" },
          ]}
        />
      ) : (
        <Breadcrumb
          items={[
            { label: "Patients", to: "/patients" },
            { label: "New Patient" },
          ]}
        />
      )}

      <h1>{patient ? `Upload Data for ${patient.name}` : "New Patient Upload"}</h1>
      <UploadForm preSelectedPatient={patient} />
    </div>
  );
}
