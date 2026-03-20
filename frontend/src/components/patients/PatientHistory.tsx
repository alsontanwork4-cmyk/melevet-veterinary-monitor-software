import { Link } from "react-router-dom";

import { PatientUploadHistoryItem } from "../../types/api";
import { formatDateTime } from "../../utils/format";

interface PatientHistoryProps {
  uploads: PatientUploadHistoryItem[];
  page?: number;
  totalPages?: number;
  totalCount?: number;
  onPageChange?: (page: number) => void;
  onDeleteUpload: (uploadId: number) => void;
  deletingUploadId: number | null;
}

const statusLabels: Record<string, string> = {
  completed: "Completed",
  processing: "Processing",
  error: "Error",
};

function formatCanonicalSummary(upload: PatientUploadHistoryItem): string {
  const newTotal = upload.measurements_new + upload.nibp_new;
  const reusedTotal = upload.measurements_reused + upload.nibp_reused;

  if (newTotal === 0 && reusedTotal === 0) {
    return upload.status === "completed" ? "No canonical rows written" : "Pending";
  }

  if (newTotal === 0 && reusedTotal > 0) {
    return `Exact overlap: reused ${reusedTotal.toLocaleString()} rows`;
  }

  return `New ${newTotal.toLocaleString()} | Reused ${reusedTotal.toLocaleString()}`;
}

export function PatientHistory({
  uploads,
  page = 1,
  totalPages = 1,
  totalCount = uploads.length,
  onPageChange,
  onDeleteUpload,
  deletingUploadId,
}: PatientHistoryProps) {
  return (
    <div className="card stack-sm">
      <div className="row-between">
        <div>
          <h3>Upload History</h3>
          <p className="helper-text">
            Showing {uploads.length} of {totalCount} uploads.
          </p>
        </div>
        {totalPages > 1 && onPageChange ? (
          <div className="row gap-sm">
            <button type="button" className="button-muted" onClick={() => onPageChange(page - 1)} disabled={page <= 1}>
              Previous
            </button>
            <span className="helper-text">
              Page {page} of {totalPages}
            </span>
            <button
              type="button"
              className="button-muted"
              onClick={() => onPageChange(page + 1)}
              disabled={page >= totalPages}
            >
              Next
            </button>
          </div>
        ) : null}
      </div>
      <p className="helper-text">
        Original export files are temporary. Melevet keeps canonical decoded rows and lightweight import history only.
      </p>
      <table className="table">
        <thead>
          <tr>
            <th>Upload ID</th>
            <th>Uploaded At</th>
            <th>Latest Recorded At</th>
            <th>Status</th>
            <th>Canonical Storage</th>
            <th>Trend Chart Records</th>
            <th>NIBP Records</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {uploads.map((upload) => (
            <tr key={upload.id}>
              <td>
                <Link to={`/uploads/${upload.id}/report`}>#{upload.id}</Link>
              </td>
              <td>{formatDateTime(upload.upload_time)}</td>
              <td>{formatDateTime(upload.latest_recorded_at)}</td>
              <td>{statusLabels[upload.status] ?? upload.status}</td>
              <td>{formatCanonicalSummary(upload)}</td>
              <td>{upload.trend_frames}</td>
              <td>{upload.nibp_frames}</td>
              <td>
                <button
                  type="button"
                  className="text-button text-button-danger"
                  onClick={() => onDeleteUpload(upload.id)}
                  disabled={deletingUploadId === upload.id}
                >
                  {deletingUploadId === upload.id ? "Deleting..." : "Delete"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
