import { Link } from "react-router-dom";

import { PatientUploadHistoryItem } from "../../types/api";
import { formatDateTime } from "../../utils/format";

interface PatientHistoryProps {
  uploads: PatientUploadHistoryItem[];
  onDeleteUpload: (uploadId: number) => void;
  deletingUploadId: number | null;
}

const statusLabels: Record<string, string> = {
  completed: "Completed",
  processing: "Processing",
  error: "Error",
};

export function PatientHistory({ uploads, onDeleteUpload, deletingUploadId }: PatientHistoryProps) {
  return (
    <div className="card">
      <h3>Upload History</h3>
      <table className="table">
        <thead>
          <tr>
            <th>Upload ID</th>
            <th>Uploaded At</th>
            <th>Status</th>
            <th>Trend Chart Records</th>
            <th>NIBP Records</th>
            <th>Alarm Events</th>
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
              <td>{statusLabels[upload.status] ?? upload.status}</td>
              <td>{upload.trend_frames}</td>
              <td>{upload.nibp_frames}</td>
              <td>{upload.alarm_frames}</td>
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
