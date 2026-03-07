import { AlarmCategory } from "../types/api";

export const alarmColorMap: Record<AlarmCategory, string> = {
  technical: "#D97706",
  physiological_warning: "#CA8A04",
  physiological_critical: "#EF4444",
  technical_critical: "#DC2626",
  system: "#3B82F6",
  informational: "#6B7280",
};