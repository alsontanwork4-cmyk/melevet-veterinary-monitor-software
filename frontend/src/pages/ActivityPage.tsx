import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { listAuditLog } from "../api/endpoints";
import { formatDateTime } from "../utils/format";

const PAGE_SIZE = 50;

function formatAuditDetails(details: Record<string, unknown>): string {
  const entries = Object.entries(details);
  if (entries.length === 0) {
    return "-";
  }
  return entries
    .slice(0, 4)
    .map(([key, value]) => `${key}: ${typeof value === "string" ? value : JSON.stringify(value)}`)
    .join(" | ");
}

export function ActivityPage() {
  const [page, setPage] = useState(1);
  const [entityType, setEntityType] = useState("");

  const queryParams = useMemo(() => ({
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
    entityType: entityType || undefined,
  }), [entityType, page]);

  const auditQuery = useQuery({
    queryKey: ["audit-log", queryParams],
    queryFn: () => listAuditLog(queryParams),
    placeholderData: (previousData) => previousData,
  });

  const totalCount = auditQuery.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE) || 1);

  return (
    <div className="stack-lg">
      <div className="page-header">
        <div>
          <h1>Logs</h1>
          <p className="helper-text">Review changes to patients, uploads, encounters, and related admin logs.</p>
        </div>
        <label className="activity-filter">
          Entity
          <select
            value={entityType}
            onChange={(event) => {
              setEntityType(event.target.value);
              setPage(1);
            }}
          >
            <option value="">All</option>
            <option value="patient">Patients</option>
            <option value="upload">Uploads</option>
            <option value="encounter">Encounters</option>
          </select>
        </label>
      </div>

      {auditQuery.isLoading ? (
        <div className="card">Loading logs...</div>
      ) : auditQuery.isError ? (
        <div className="card error">Unable to load logs.</div>
      ) : (
        <div className="card stack-sm">
          <table className="table">
            <thead>
              <tr>
                <th>When</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Entity</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {(auditQuery.data?.items ?? []).map((entry) => (
                <tr key={entry.id}>
                  <td>{formatDateTime(entry.timestamp)}</td>
                  <td>{entry.actor}</td>
                  <td>{entry.action}</td>
                  <td>{entry.entity_type} #{entry.entity_id}</td>
                  <td>{formatAuditDetails(entry.details_json)}</td>
                </tr>
              ))}
              {(auditQuery.data?.items.length ?? 0) === 0 && (
                <tr>
                  <td colSpan={5} className="helper-text">No logs yet.</td>
                </tr>
              )}
            </tbody>
          </table>

          <div className="row-between">
            <span className="helper-text">Page {page} of {totalPages}</span>
            <div className="chips">
              <button type="button" className="chip" disabled={page <= 1} onClick={() => setPage((current) => current - 1)}>
                Previous
              </button>
              <button type="button" className="chip" disabled={page >= totalPages} onClick={() => setPage((current) => current + 1)}>
                Next
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
