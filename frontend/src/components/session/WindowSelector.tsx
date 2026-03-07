interface WindowSelectorProps {
  value: number;
  onChange: (minutes: number) => void;
  options?: number[];
}

const defaultOptions = [1, 5, 10, 20];

export function WindowSelector({ value, onChange, options }: WindowSelectorProps) {
  const resolvedOptions = Array.from(new Set(options ?? defaultOptions)).sort((a, b) => a - b);

  return (
    <div className="card compact-card">
      <h4>Time Window</h4>
      <div className="chips">
        {resolvedOptions.map((minutes) => (
          <button
            key={minutes}
            type="button"
            className={value === minutes ? "chip chip-active" : "chip"}
            onClick={() => onChange(minutes)}
          >
            {minutes} min
          </button>
        ))}
      </div>
    </div>
  );
}
