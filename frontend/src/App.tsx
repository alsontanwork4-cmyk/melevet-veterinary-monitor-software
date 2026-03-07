import { Navigate, createBrowserRouter } from "react-router-dom";

import { AppShell } from "./components/layout/AppShell";
import { DecodingPage } from "./pages/DecodingPage";
import { DiscoveryPage } from "./pages/DiscoveryPage";
import { PatientsPage } from "./pages/PatientsPage";
import { ReportPage } from "./pages/ReportPage";
import { UploadPage } from "./pages/UploadPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <PatientsPage /> },
      { path: "patients", element: <Navigate to="/" replace /> },
      { path: "patients/:patientId", element: <Navigate to="/" replace /> },
      { path: "patients/:patientId/upload", element: <UploadPage /> },
      { path: "upload", element: <Navigate to="/" replace /> },
      { path: "decode", element: <DecodingPage /> },
      { path: "uploads/:uploadId/discovery", element: <DiscoveryPage /> },
      { path: "uploads/:uploadId/report", element: <Navigate to="../discovery" replace relative="path" /> },
      { path: "uploads/:uploadId/session", element: <Navigate to="../discovery" replace relative="path" /> },
      { path: "encounters/:encounterId/report", element: <ReportPage /> },
    ],
  },
]);
