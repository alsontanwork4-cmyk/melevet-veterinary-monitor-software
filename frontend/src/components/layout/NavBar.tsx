import { useEffect, useRef, useState } from "react";
import { Link, NavLink } from "react-router-dom";

type NavBarProps = {
  isOpen: boolean;
  isSigningOut?: boolean;
  onLogout?: () => void;
  onToggle: () => void;
  userDisplayName?: string;
};

export function NavBar({ isOpen, isSigningOut = false, onLogout, onToggle, userDisplayName }: NavBarProps) {
  const [isUtilityMenuOpen, setIsUtilityMenuOpen] = useState(false);
  const utilityMenuRef = useRef<HTMLDivElement | null>(null);
  const utilityTriggerRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!isOpen) {
      setIsUtilityMenuOpen(false);
    }
  }, [isOpen]);

  useEffect(() => {
    if (!isUtilityMenuOpen) {
      return;
    }

    function closeMenu() {
      setIsUtilityMenuOpen(false);
    }

    function handlePointerDown(event: MouseEvent) {
      if (!(event.target instanceof Node)) {
        return;
      }
      if (utilityTriggerRef.current?.contains(event.target)) {
        return;
      }
      if (utilityMenuRef.current?.contains(event.target)) {
        return;
      }
      closeMenu();
    }

    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        closeMenu();
      }
    }

    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleEscape);
    window.addEventListener("resize", closeMenu);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleEscape);
      window.removeEventListener("resize", closeMenu);
    };
  }, [isUtilityMenuOpen]);

  const navClass = ({ isActive }: { isActive: boolean }) =>
    isActive ? "nav-link nav-link-active" : "nav-link";

  return (
    <aside className={`sidebar${isOpen ? "" : " sidebar-hidden"}`}>
      <div className="sidebar-inner">
        <div className="sidebar-header">
          {isOpen ? (
            <Link to="/" className="brand">
              Melevet<span className="brand-tag">Monitor</span>
            </Link>
          ) : null}
          <button
            type="button"
            className="sidebar-toggle"
            onClick={onToggle}
            aria-label={isOpen ? "Hide left sidebar" : "Open left sidebar"}
            aria-expanded={isOpen}
          >
            {isOpen ? "Hide menu" : "Open menu"}
          </button>
        </div>
        {isOpen ? (
          <>
            <nav className="nav">
              <NavLink to="/" end className={navClass}>
                Homepage
              </NavLink>
              <NavLink to="/decode" className={navClass}>
                Decoding
              </NavLink>
              <NavLink to="/activity" className={navClass}>
                Logs
              </NavLink>
            </nav>
            <div className="sidebar-footer">
              {userDisplayName ? (
                <div className="sidebar-user-card">
                  <span className="sidebar-user-label">Signed in</span>
                  <strong className="sidebar-user-name">{userDisplayName}</strong>
                </div>
              ) : null}
              {onLogout ? (
                <button
                  type="button"
                  className="button-muted sidebar-logout-button"
                  onClick={onLogout}
                  disabled={isSigningOut}
                >
                  {isSigningOut ? "Signing out…" : "Sign out"}
                </button>
              ) : null}
              <div className="sidebar-utility-menu-shell">
                <button
                  ref={utilityTriggerRef}
                  type="button"
                  className="button-muted sidebar-utility-trigger"
                  aria-haspopup="menu"
                  aria-expanded={isUtilityMenuOpen}
                  aria-label="Open settings and help menu"
                  onClick={() => setIsUtilityMenuOpen((current) => !current)}
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" className="sidebar-utility-icon">
                    <path
                      d="M19.14 12.94a7.43 7.43 0 0 0 .05-.94 7.43 7.43 0 0 0-.05-.94l2.03-1.58a.5.5 0 0 0 .12-.64l-1.92-3.32a.5.5 0 0 0-.6-.22l-2.39.96a7.28 7.28 0 0 0-1.63-.94l-.36-2.54a.5.5 0 0 0-.49-.42h-3.84a.5.5 0 0 0-.49.42l-.36 2.54c-.58.22-1.12.53-1.63.94l-2.39-.96a.5.5 0 0 0-.6.22L2.71 8.84a.5.5 0 0 0 .12.64l2.03 1.58a7.43 7.43 0 0 0-.05.94c0 .32.02.63.05.94l-2.03 1.58a.5.5 0 0 0-.12.64l1.92 3.32a.5.5 0 0 0 .6.22l2.39-.96c.5.41 1.05.72 1.63.94l.36 2.54a.5.5 0 0 0 .49.42h3.84a.5.5 0 0 0 .49-.42l.36-2.54c.58-.22 1.12-.53 1.63-.94l2.39.96a.5.5 0 0 0 .6-.22l1.92-3.32a.5.5 0 0 0-.12-.64l-2.03-1.58ZM12 15.5A3.5 3.5 0 1 1 12 8.5a3.5 3.5 0 0 1 0 7Z"
                      fill="currentColor"
                    />
                  </svg>
                  <span>More</span>
                </button>
                {isUtilityMenuOpen ? (
                  <div ref={utilityMenuRef} className="sidebar-utility-menu" role="menu" aria-label="Settings and help">
                    <NavLink
                      to="/settings"
                      className={({ isActive }) =>
                        isActive ? "sidebar-utility-menu-item sidebar-utility-menu-item-active" : "sidebar-utility-menu-item"
                      }
                      role="menuitem"
                      onClick={() => setIsUtilityMenuOpen(false)}
                    >
                      <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" className="sidebar-utility-menu-icon">
                        <path
                          d="M19.14 12.94a7.43 7.43 0 0 0 .05-.94 7.43 7.43 0 0 0-.05-.94l2.03-1.58a.5.5 0 0 0 .12-.64l-1.92-3.32a.5.5 0 0 0-.6-.22l-2.39.96a7.28 7.28 0 0 0-1.63-.94l-.36-2.54a.5.5 0 0 0-.49-.42h-3.84a.5.5 0 0 0-.49.42l-.36 2.54c-.58.22-1.12.53-1.63.94l-2.39-.96a.5.5 0 0 0-.6.22L2.71 8.84a.5.5 0 0 0 .12.64l2.03 1.58a7.43 7.43 0 0 0-.05.94c0 .32.02.63.05.94l-2.03 1.58a.5.5 0 0 0-.12.64l1.92 3.32a.5.5 0 0 0 .6.22l2.39-.96c.5.41 1.05.72 1.63.94l.36 2.54a.5.5 0 0 0 .49.42h3.84a.5.5 0 0 0 .49-.42l.36-2.54c.58-.22 1.12-.53 1.63-.94l2.39.96a.5.5 0 0 0 .6-.22l1.92-3.32a.5.5 0 0 0-.12-.64l-2.03-1.58ZM12 15.5A3.5 3.5 0 1 1 12 8.5a3.5 3.5 0 0 1 0 7Z"
                          fill="currentColor"
                        />
                      </svg>
                      <span>Settings</span>
                    </NavLink>
                    <NavLink
                      to="/help"
                      className={({ isActive }) =>
                        isActive ? "sidebar-utility-menu-item sidebar-utility-menu-item-active" : "sidebar-utility-menu-item"
                      }
                      role="menuitem"
                      onClick={() => setIsUtilityMenuOpen(false)}
                    >
                      <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" className="sidebar-utility-menu-icon">
                        <path
                          d="M12 2.75a9.25 9.25 0 1 0 0 18.5 9.25 9.25 0 0 0 0-18.5Zm0 16.5a7.25 7.25 0 1 1 0-14.5 7.25 7.25 0 0 1 0 14.5Zm-.02-4.2a1.08 1.08 0 1 0 0 2.16 1.08 1.08 0 0 0 0-2.16Zm1.58-7.17c-.44-.38-1.02-.58-1.72-.58-.79 0-1.43.23-1.92.7-.48.45-.75 1.04-.81 1.75a.75.75 0 0 0 1.49.13c.03-.35.15-.62.38-.83.21-.2.49-.3.86-.3.33 0 .58.08.76.23.17.15.25.35.25.63 0 .22-.07.42-.22.59-.09.1-.3.26-.66.48-.47.29-.84.59-1.08.93-.25.34-.37.74-.37 1.23v.32a.75.75 0 0 0 1.5 0v-.23c0-.21.05-.39.15-.54.1-.15.29-.31.59-.49.45-.28.79-.57 1-.87.24-.35.36-.75.36-1.19 0-.69-.25-1.25-.76-1.68Z"
                          fill="currentColor"
                        />
                      </svg>
                      <span>Help</span>
                    </NavLink>
                  </div>
                ) : null}
              </div>
              <small className="sidebar-version">Version {__APP_VERSION__}</small>
            </div>
          </>
        ) : null}
      </div>
    </aside>
  );
}
