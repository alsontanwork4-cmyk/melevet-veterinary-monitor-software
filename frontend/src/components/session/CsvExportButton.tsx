import { exportCsvUrl } from "../../api/endpoints";

interface CsvExportButtonProps {
  uploadId: number;
  segmentId: number;
  channelIds: number[];
  fromTs?: string;
  toTs?: string;
}

export function CsvExportButton({ uploadId, segmentId, channelIds, fromTs, toTs }: CsvExportButtonProps) {
  const href = exportCsvUrl(uploadId, segmentId, channelIds, fromTs, toTs);

  return (
    <a className="button-link" href={href} target="_blank" rel="noreferrer">
      Export CSV
    </a>
  );
}