import { Segment } from "../../types/api";

interface SegmentSelectorProps {
  segments: Segment[];
  selectedSegmentId: number | null;
  onChange: (segmentId: number) => void;
}

export function SegmentSelector({ segments, selectedSegmentId, onChange }: SegmentSelectorProps) {
  return (
    <div className="card compact-card">
      <h4>Continuous Segment</h4>
      <p className="helper-text">
        Segments split a period into continuous blocks when an internal gap is longer than 10 minutes.
      </p>
      <select
        value={selectedSegmentId ?? ""}
        onChange={(event) => onChange(Number(event.target.value))}
      >
        {segments.map((segment) => (
          <option key={segment.id} value={segment.id}>
            Segment {segment.segment_index + 1} ({segment.frame_count} frames)
          </option>
        ))}
      </select>
    </div>
  );
}
