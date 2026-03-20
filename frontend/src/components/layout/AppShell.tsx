import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Navigate, Outlet, useLocation } from "react-router-dom";

import { getUpdateStatus } from "../../api/endpoints";
import { useAuth } from "../../auth/AuthProvider";
import { isLocalAppMode } from "../../runtime";
import { hasCompletedOnboarding, markOnboardingCompleted, subscribeOnboardingReplay } from "../../utils/onboarding";
import { NavBar } from "./NavBar";
import { OnboardingModal } from "./OnboardingModal";
import "../../styles/app.css";

export function AppShell() {
  const { isAuthenticated, isSubmitting, user, logout } = useAuth();
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [isOnboardingOpen, setIsOnboardingOpen] = useState(false);
  const location = useLocation();
  const updateStatusQuery = useQuery({
    queryKey: ["update-status"],
    queryFn: () => getUpdateStatus(),
    enabled: isLocalAppMode || (isAuthenticated && user !== null),
    refetchInterval: 1000 * 60 * 60,
  });

  useEffect(() => {
    if (!hasCompletedOnboarding()) {
      setIsOnboardingOpen(true);
    }
    return subscribeOnboardingReplay(() => setIsOnboardingOpen(true));
  }, []);

  function closeOnboarding() {
    markOnboardingCompleted();
    setIsOnboardingOpen(false);
  }

  if (!isLocalAppMode && (!isAuthenticated || user === null)) {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search + location.hash }} />;
  }

  return (
    <>
      <div className={`app-shell${isSidebarOpen ? "" : " app-shell-sidebar-hidden"}`}>
        <NavBar
          isOpen={isSidebarOpen}
          isSigningOut={isSubmitting}
          onToggle={() => setIsSidebarOpen((current) => !current)}
          onLogout={isLocalAppMode ? undefined : () => void logout()}
          userDisplayName={user?.username}
        />
        <div className="app-shell-content">
          <main className="page-container">
            {updateStatusQuery.data?.is_update_available && (
              <div className="app-update-banner">
                <span>Version {updateStatusQuery.data.latest_version} is available.</span>
                {updateStatusQuery.data.download_url ? (
                  <a href={updateStatusQuery.data.download_url} target="_blank" rel="noreferrer">
                    Download update
                  </a>
                ) : null}
              </div>
            )}
            <Outlet />
          </main>
        </div>
      </div>
      <OnboardingModal isOpen={isOnboardingOpen} onClose={closeOnboarding} />
    </>
  );
}
