interface NibpOverlayProps {
  count: number;
}

export function NibpOverlay({ count }: NibpOverlayProps) {
  return <span className="badge">NIBP (Blood Pressure) Events: {count}</span>;
}
