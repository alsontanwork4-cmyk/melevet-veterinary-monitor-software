import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { PatientWithUploadCount } from "../../types/api";
import { formatDate } from "../../utils/format";
import { getAgeFromNotes, getGenderFromNotes } from "../../utils/patientNotes";
import { getPatientReportDate } from "../../utils/patientReports";

interface PatientListProps {
  patients: PatientWithUploadCount[];
  page: number;
  totalPages: number;
  totalCount: number;
  selectedPatientId: number | null;
  onSelectPatient: (patientId: number) => void;
  onUploadPatient: (patientId: number) => void;
  onEditPatient: (patientId: number) => void;
  onDeletePatient: (patientId: number) => void;
  onPageChange: (page: number) => void;
}

export function PatientList({
  patients,
  page,
  totalPages,
  totalCount,
  selectedPatientId,
  onSelectPatient,
  onUploadPatient,
  onEditPatient,
  onDeletePatient,
  onPageChange,
}: PatientListProps) {
  const [openMenuPatientId, setOpenMenuPatientId] = useState<number | null>(null);
  const [openMenuPosition, setOpenMenuPosition] = useState<{ top: number; left: number } | null>(null);
  const openMenuRef = useRef<HTMLDivElement | null>(null);
  const openTriggerRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (openMenuPatientId === null) {
      return;
    }

    function closeOpenMenu() {
      setOpenMenuPatientId(null);
      setOpenMenuPosition(null);
    }

    function handlePointerDown(event: MouseEvent) {
      if (!(event.target instanceof Node)) {
        return;
      }
      if (openTriggerRef.current?.contains(event.target)) {
        return;
      }
      if (openMenuRef.current?.contains(event.target)) {
        return;
      }
      closeOpenMenu();
    }

    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        closeOpenMenu();
      }
    }

    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleEscape);
    window.addEventListener("resize", closeOpenMenu);
    window.addEventListener("scroll", closeOpenMenu, true);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleEscape);
      window.removeEventListener("resize", closeOpenMenu);
      window.removeEventListener("scroll", closeOpenMenu, true);
    };
  }, [openMenuPatientId]);

  function closeMenu() {
    setOpenMenuPatientId(null);
    setOpenMenuPosition(null);
  }

  function toggleMenu(patientId: number, trigger: HTMLButtonElement) {
    if (openMenuPatientId === patientId) {
      closeMenu();
      return;
    }

    const rect = trigger.getBoundingClientRect();
    const viewportPadding = 12;
    const menuWidth = 132;
    const menuHeight = 126;
    const left = Math.max(
      viewportPadding,
      Math.min(rect.right - menuWidth, window.innerWidth - menuWidth - viewportPadding),
    );
    const opensUpward = rect.bottom + 6 + menuHeight > window.innerHeight - viewportPadding;
    const top = opensUpward ? Math.max(viewportPadding, rect.top - menuHeight - 6) : rect.bottom + 6;

    openTriggerRef.current = trigger;
    setOpenMenuPatientId(patientId);
    setOpenMenuPosition({ top, left });
  }

  const activePatient = openMenuPatientId === null ? null : patients.find((patient) => patient.id === openMenuPatientId) ?? null;

  return (
    <div className="card patient-list-card">
      <div className="patient-list-table-shell">
        <table className="table patient-list-table">
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
              <th className="patient-actions-column-header">Actions</th>
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
                  <div className="patient-actions-menu-shell">
                    <button
                      type="button"
                      className="patient-actions-trigger"
                      onClick={(event) => {
                        event.stopPropagation();
                        toggleMenu(patient.id, event.currentTarget);
                      }}
                      aria-haspopup="menu"
                      aria-expanded={openMenuPatientId === patient.id}
                      aria-label={`Open actions for ${patient.name}`}
                    >
                      ...
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="patient-list-pagination">
        <div className="patient-list-summary">
          Showing {patients.length} of {totalCount} patients
        </div>
        <div className="patient-list-pagination-info">Page {page} of {totalPages}</div>
        <div className="patient-list-pagination-actions">
          <button type="button" className="button-muted" onClick={() => onPageChange(page - 1)} disabled={page <= 1}>
            Previous
          </button>
          <button
            type="button"
            className="button-muted"
            onClick={() => onPageChange(page + 1)}
            disabled={page >= totalPages}
          >
            Next
          </button>
        </div>
      </div>
      {activePatient && openMenuPosition
        ? createPortal(
            <div
              ref={openMenuRef}
              className="patient-actions-menu"
              role="menu"
              aria-label={`Actions for ${activePatient.name}`}
              style={{
                position: "fixed",
                top: `${openMenuPosition.top}px`,
                left: `${openMenuPosition.left}px`,
              }}
            >
              <button
                type="button"
                className="patient-actions-menu-item"
                onClick={(event) => {
                  event.stopPropagation();
                  closeMenu();
                  onUploadPatient(activePatient.id);
                }}
                aria-label={`Upload ${activePatient.name}`}
              >
                Upload
              </button>
              <button
                type="button"
                className="patient-actions-menu-item"
                onClick={(event) => {
                  event.stopPropagation();
                  closeMenu();
                  onEditPatient(activePatient.id);
                }}
                aria-label={`Edit ${activePatient.name}`}
              >
                Edit
              </button>
              <button
                type="button"
                className="patient-actions-menu-item patient-actions-menu-item-danger"
                onClick={(event) => {
                  event.stopPropagation();
                  closeMenu();
                  onDeletePatient(activePatient.id);
                }}
                aria-label={`Delete ${activePatient.name}`}
              >
                Delete
              </button>
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
