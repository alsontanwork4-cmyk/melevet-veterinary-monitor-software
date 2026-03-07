import { AlarmCategory } from "../../types/api";
import { alarmColorMap } from "../../utils/alarmColors";

interface AlarmBadgeProps {
  category: AlarmCategory;
}

export function AlarmBadge({ category }: AlarmBadgeProps) {
  return (
    <span className="pill" style={{ backgroundColor: alarmColorMap[category] }}>
      {category}
    </span>
  );
}