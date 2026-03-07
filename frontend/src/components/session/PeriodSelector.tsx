import { RecordingPeriod } from "../../types/api";

interface PeriodSelectorProps {
  periods: RecordingPeriod[];
  selectedPeriodId: number | null;
  onChange: (periodId: number) => void;
}

export function PeriodSelector({ periods, selectedPeriodId, onChange }: PeriodSelectorProps) {
  return (
    <div className="card compact-card">
      <h4>Recording Period</h4>
      <p className="helper-text">
        A new period starts when timestamps jump backward or when the gap is longer than 24 hours.
      </p>
      <div className="chips">
        {periods.map((period) => (
          <button
            key={period.id}
            type="button"
            className={selectedPeriodId === period.id ? "chip chip-active" : "chip"}
            onClick={() => onChange(period.id)}
          >
            {period.label}
          </button>
        ))}
      </div>
    </div>
  );
}
