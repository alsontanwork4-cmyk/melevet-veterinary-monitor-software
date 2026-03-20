import { Navigate, createBrowserRouter } from "react-router-dom";

import { AppShell } from "./components/layout/AppShell";
import { ActivityPage } from "./pages/ActivityPage";
import { DecodingPage } from "./pages/DecodingPage";
import { DiscoveryPage } from "./pages/DiscoveryPage";
import { LoginPage } from "./pages/LoginPage";
import { PatientsPage } from "./pages/PatientsPage";
import { ReportPage } from "./pages/ReportPage";
import { SessionPage } from "./pages/SessionPage";
import { SettingsPage } from "./pages/SettingsPage";
import { UploadPage } from "./pages/UploadPage";
import { HelpPage } from "./pages/HelpPage";
import { isLocalAppMode } from "./runtime";

export const router = createBrowserRouter([
  ...(
    isLocalAppMode
      ? []
      : [
          {
            path: "/login",
            element: <LoginPage />,
          },
        ]
  ),
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
      { path: "staged-uploads/:stageId/discovery", element: <DiscoveryPage /> },
      { path: "uploads/:uploadId/discovery", element: <DiscoveryPage /> },
      { path: "uploads/:uploadId/report", element: <Navigate to="../discovery" replace relative="path" /> },
      { path: "uploads/:uploadId/session", element: <SessionPage /> },
      { path: "activity", element: <ActivityPage /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "help", element: <HelpPage /> },
      { path: "encounters/:encounterId/report", element: <ReportPage /> },
    ],
  },
]);
