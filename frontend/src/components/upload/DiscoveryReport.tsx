import { Link } from "react-router-dom";

import { DiscoveryResponse } from "../../types/api";

interface DiscoveryReportProps {
  data: DiscoveryResponse;
}

export function DiscoveryReport({ data }: DiscoveryReportProps) {
  return (
    <div className="stack-md">
      <div className="card">
        <h2>Channel Discovery Report</h2>
        <p>
          Trend Chart Records: <strong>{data.trend_frames}</strong> | NIBP Records: <strong>{data.nibp_frames}</strong> | Alarm Events: <strong>{data.alarm_frames}</strong>
        </p>
        <p>
          Recording Periods: <strong>{data.periods}</strong> | Segments: <strong>{data.segments}</strong>
        </p>
        <Link to={`/uploads/${data.upload_id}/report`} className="button-link">
          View Report
        </Link>
      </div>
    </div>
  );
}
