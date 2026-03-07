export interface SegmentWindowQueryOptions {
  segmentId?: number;
  fromTs?: string;
  toTs?: string;
}

export function buildSegmentWindowQuery(
  segmentId: number | null,
  fromTs?: string,
  toTs?: string,
): SegmentWindowQueryOptions {
  return {
    segmentId: segmentId ?? undefined,
    fromTs,
    toTs,
  };
}
