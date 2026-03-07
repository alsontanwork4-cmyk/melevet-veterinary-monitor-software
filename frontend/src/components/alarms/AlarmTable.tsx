import { AlarmEvent } from "../../types/api";
import { alarmColorMap } from "../../utils/alarmColors";
import { formatDateTime } from "../../utils/format";

interface AlarmTableProps {
  alarms: AlarmEvent[];
  onSelectAlarm?: (alarm: AlarmEvent) => void;
  selectedAlarmId?: number | null;
}

export function AlarmTable({ alarms, onSelectAlarm, selectedAlarmId = null }: AlarmTableProps) {
  return (
    <div className="card">
      <h3>Alarm Events</h3>
      <table className="table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Category</th>
            <th>Flags</th>
            <th>Message</th>
          </tr>
        </thead>
        <tbody>
          {alarms.map((alarm) => (
            <tr
              key={alarm.id}
              className={`${onSelectAlarm ? "row-clickable" : ""} ${selectedAlarmId === alarm.id ? "row-selected" : ""}`.trim()}
              onClick={onSelectAlarm ? () => onSelectAlarm(alarm) : undefined}
            >
              <td>{formatDateTime(alarm.timestamp)}</td>
              <td>
                <span className="pill" style={{ backgroundColor: alarmColorMap[alarm.alarm_category] }}>
                  {alarm.alarm_category}
                </span>
              </td>
              <td>
                hi={alarm.flag_hi} lo={alarm.flag_lo}
              </td>
              <td>{alarm.message}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
