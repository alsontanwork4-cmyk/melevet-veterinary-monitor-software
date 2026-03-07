import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { getMeasurements, MeasurementQuery } from "../api/endpoints";
import { MeasurementPoint } from "../types/api";

export function useChartData(segmentId: number | null, query: MeasurementQuery) {
  const channels = query.channels ?? [];
  const hasChannelFilter = Array.isArray(query.channels);
  const hasSelectedChannels = !hasChannelFilter || channels.length > 0;

  const result = useQuery({
    queryKey: ["measurements", segmentId, query],
    queryFn: () => getMeasurements(segmentId as number, query),
    enabled: segmentId !== null && hasSelectedChannels,
  });

  const byChannel = useMemo(() => {
    const grouped: Record<string, MeasurementPoint[]> = {};
    if (!result.data) {
      return grouped;
    }

    for (const point of result.data.points) {
      if (!grouped[point.channel_name]) {
        grouped[point.channel_name] = [];
      }
      grouped[point.channel_name].push(point);
    }
    return grouped;
  }, [result.data]);

  return { ...result, byChannel };
}
