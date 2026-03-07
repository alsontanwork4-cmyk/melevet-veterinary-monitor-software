interface AlarmMarkersProps {
  count: number;
}

export function AlarmMarkers({ count }: AlarmMarkersProps) {
  return <span className="badge">Alarm Events: {count}</span>;
}
