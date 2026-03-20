export type HelpSection = {
  id: string;
  title: string;
  summary: string;
  bullets: string[];
};

export const helpSections: HelpSection[] = [
  {
    id: "getting-started",
    title: "Getting Started",
    summary: "Use the Patients page as the daily home screen for saved encounters, uploads, and reports.",
    bullets: [
      "Open a patient to review saved upload history and encounter reports.",
      "Use Settings for retention, telemetry, and diagnostic health checks.",
      "Use Logs to review operational history across patients, uploads, and encounters.",
    ],
  },
  {
    id: "uploading",
    title: "Uploading Monitor Files",
    summary: "Uploads require TrendChart files and optionally support a matching NIBP file pair.",
    bullets: [
      "Single upload uses staged discovery before saving an encounter date.",
      "Bulk import processes each folder bundle sequentially through the backend write lock.",
      "Missing paired NIBP index files will block the affected bundle.",
    ],
  },
  {
    id: "reports",
    title: "Reading Reports",
    summary: "Reports summarize the saved encounter day with trend charts, NIBP values, and print support.",
    bullets: [
      "If an upload has been archived, charts are replaced with a metadata notice and archive download link.",
      "Use Print Report for a print-friendly patient summary.",
      "Threshold overlays come from the species settings configured in Settings.",
    ],
  },
  {
    id: "retention",
    title: "Archival and Retention",
    summary: "Archival exports old clinical rows into ZIP files and keeps encounter metadata live.",
    bullets: [
      "Archives are stored inside the app data root for the current runtime.",
      "Archiving removes live measurements and NIBP events for eligible uploads after export.",
      "Database stats show live row counts and archive storage size for monitoring.",
    ],
  },
  {
    id: "telemetry",
    title: "Telemetry and Privacy",
    summary: "Usage reporting is opt-in and stores anonymized events locally unless exported manually.",
    bullets: [
      "Crash reports can still be captured even when usage reporting is turned off.",
      "Telemetry excludes patient names, notes, file contents, and other clinical free text.",
      "Telemetry export downloads the local NDJSON queue for external support review.",
    ],
  },
  {
    id: "troubleshooting",
    title: "Troubleshooting",
    summary: "Use the built-in diagnostics surfaces first before escalating to support.",
    bullets: [
      "Check database diagnostics and database stats from Settings.",
      "Review Logs for recent create, update, delete, and archive operations.",
      "If the frontend crashes, reopen the app or open Help from the crash screen.",
    ],
  },
];

export const helpTips = {
  uploadRequirements: {
    title: "Upload file requirements",
    body: "TrendChartRecord.data is required. NIBP files must be provided as a complete data/index pair.",
    sectionId: "uploading",
  },
  bulkImport: {
    title: "Bulk import behavior",
    body: "Bulk import queues each folder bundle sequentially. A failed bundle does not stop later bundles from attempting upload.",
    sectionId: "uploading",
  },
  archivedReport: {
    title: "Archived report data",
    body: "Archived uploads keep encounter metadata visible, but chart/event rows must be downloaded from the archive ZIP for external review.",
    sectionId: "retention",
  },
  retentionSettings: {
    title: "Retention settings",
    body: "Archive retention controls when completed uploads are exported and removed from live clinical storage. Blank leaves archival disabled.",
    sectionId: "retention",
  },
  telemetrySettings: {
    title: "Telemetry privacy",
    body: "Usage reporting is opt-in. The queue is stored locally and can be exported manually for support workflows.",
    sectionId: "telemetry",
  },
  patientArchive: {
    title: "Archived uploads in patient history",
    body: "Archived uploads still appear in patient history so encounter timelines stay intact.",
    sectionId: "retention",
  },
} as const;
