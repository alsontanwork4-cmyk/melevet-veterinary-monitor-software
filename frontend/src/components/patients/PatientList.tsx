import { CSSProperties, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { PatientWithUploadCount } from "../../types/api";
import { formatDate } from "../../utils/format";
import { getPatientReportDate } from "../../utils/patientReports";
import { getAgeFromNotes, getGenderFromNotes } from "../../utils/patientNotes";

interface PatientListProps {
  patients: PatientWithUploadCount[];
  selectedPatientId: number | null;
  onSelectPatient: (patientId: number) => void;
  onUploadPatient: (patientId: number) => void;
  onEditPatient: (patientId: number) => void;
  onDeletePatient: (patientId: number) => void;
  deletingPatientId?: number | null;
}

export function PatientList({
  patients,
  selectedPatientId,
  onSelectPatient,
  onUploadPatient,
  onEditPatient,
  onDeletePatient,
  deletingPatientId = null,
}: PatientListProps) {
  const [openMenuPatientId, setOpenMenuPatientId] = useState<number | null>(null);
  const [menuStyle, setMenuStyle] = useState<CSSProperties>({});
  const listRef = useRef<HTMLDivElement>(null);
  const triggerRefs = useRef(new Map<number, HTMLButtonElement>());
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (openMenuPatientId === null) {
      setMenuStyle({});
      return;
    }

    function updateMenuPosition() {
      if (openMenuPatientId === null) {
        return;
      }

      const trigger = triggerRefs.current.get(openMenuPatientId);
      const menu = menuRef.current;
      if (!trigger || !menu) {
        return;
      }

      const triggerRect = trigger.getBoundingClientRect();
      const menuRect = menu.getBoundingClientRect();
      const viewportWidth = window.innerWidth;
      const viewportHeight = window.innerHeight;
      const gap = 6;

      let top = triggerRect.bottom + gap;
      let left = triggerRect.right - menuRect.width;

      if (left < 8) {
        left = 8;
      } else if (left + menuRect.width > viewportWidth - 8) {
        left = viewportWidth - menuRect.width - 8;
      }

      if (top + menuRect.height > viewportHeight - 8) {
        top = triggerRect.top - menuRect.height - gap;
      }

      if (top < 8) {
        top = 8;
      }

      setMenuStyle({
        position: "fixed",
        top,
        left,
      });
    }

    const frameId = window.requestAnimationFrame(updateMenuPosition);
    window.addEventListener("resize", updateMenuPosition);
    window.addEventListener("scroll", updateMenuPosition, true);
    return () => {
      window.cancelAnimationFrame(frameId);
      window.removeEventListener("resize", updateMenuPosition);
      window.removeEventListener("scroll", updateMenuPosition, true);
    };
  }, [openMenuPatientId]);

  useEffect(() => {
    function onDocumentMouseDown(event: MouseEvent) {
      if (!(event.target instanceof Node)) {
        return;
      }

      if (menuRef.current?.contains(event.target)) {
        return;
      }

      const trigger = openMenuPatientId !== null ? triggerRefs.current.get(openMenuPatientId) : null;
      if (trigger?.contains(event.target)) {
        return;
      }

      setOpenMenuPatientId(null);
    }

    document.addEventListener("mousedown", onDocumentMouseDown);
    return () => {
      document.removeEventListener("mousedown", onDocumentMouseDown);
    };
  }, []);

  const openMenuPatient = openMenuPatientId !== null ? patients.find((patient) => patient.id === openMenuPatientId) ?? null : null;

  return (
    <>
      <div className="card patient-list-card" ref={listRef}>
        <table className="table">
          <thead>
            <tr>
              <th>Patient ID</th>
              <th>Patient Name</th>
              <th>Species</th>
              <th>Age</th>
              <th>Gender</th>
              <th>Client Name</th>
              <th>Created Date</th>
              <th>Report Date</th>
              <th className="patient-actions-column-header">
                <span className="visually-hidden">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {patients.map((patient) => (
              <tr
                key={patient.id}
                className={selectedPatientId === patient.id ? "row-clickable row-selected" : "row-clickable"}
                onClick={() => onSelectPatient(patient.id)}
              >
                <td className="patient-row-link">{patient.patient_id_code}</td>
                <td className="patient-row-link">{patient.name}</td>
                <td>{patient.species}</td>
                <td>{patient.age?.trim() || getAgeFromNotes(patient.notes) || "-"}</td>
                <td>{getGenderFromNotes(patient.notes) || "-"}</td>
                <td>{patient.owner_name?.trim() || "-"}</td>
                <td>{formatDate(patient.created_at)}</td>
                <td>{formatDate(getPatientReportDate(patient))}</td>
                <td className="patient-actions-cell">
                  <div className="patient-actions-wrapper">
                    <button
                      type="button"
                      className="patient-actions-trigger"
                      aria-label={`Open actions for ${patient.name}`}
                      ref={(element) => {
                        if (element) {
                          triggerRefs.current.set(patient.id, element);
                        } else {
                          triggerRefs.current.delete(patient.id);
                        }
                      }}
                      onClick={(event) => {
                        event.stopPropagation();
                        setOpenMenuPatientId((current) => (current === patient.id ? null : patient.id));
                      }}
                    >
                      ⋯
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {openMenuPatient &&
        createPortal(
          <div
            ref={menuRef}
            className="patient-actions-menu"
            style={menuStyle}
            role="menu"
            aria-label={`Actions for ${openMenuPatient.name}`}
          >
            <button
              type="button"
              className="patient-actions-item"
              role="menuitem"
              onClick={() => {
                setOpenMenuPatientId(null);
                onUploadPatient(openMenuPatient.id);
              }}
            >
              Upload files
            </button>
            <button
              type="button"
              className="patient-actions-item"
              role="menuitem"
              onClick={() => {
                setOpenMenuPatientId(null);
                onEditPatient(openMenuPatient.id);
              }}
            >
              Edit details
            </button>
            <button
              type="button"
              className="patient-actions-item patient-actions-item-danger"
              role="menuitem"
              onClick={() => {
                setOpenMenuPatientId(null);
                onDeletePatient(openMenuPatient.id);
              }}
              disabled={deletingPatientId === openMenuPatient.id}
            >
              {deletingPatientId === openMenuPatient.id ? "Deleting..." : "Delete patient data"}
            </button>
          </div>,
          document.body,
        )}
    </>
  );
}
