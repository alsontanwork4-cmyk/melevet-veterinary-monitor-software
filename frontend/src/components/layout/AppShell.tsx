import { Outlet } from "react-router-dom";

import { NavBar } from "./NavBar";
import "../../styles/app.css";

export function AppShell() {
  return (
    <div className="app-shell">
      <NavBar />
      <div className="app-shell-content">
        <main className="page-container">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
