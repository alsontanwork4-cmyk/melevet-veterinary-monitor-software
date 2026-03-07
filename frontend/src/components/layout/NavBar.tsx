import { Link, NavLink } from "react-router-dom";

export function NavBar() {
  const navClass = ({ isActive }: { isActive: boolean }) =>
    isActive ? "nav-link nav-link-active" : "nav-link";

  return (
    <aside className="sidebar">
      <div className="sidebar-inner">
        <Link to="/" className="brand">
          Melevet<span className="brand-tag">Monitor</span>
        </Link>
        <nav className="nav">
          <NavLink to="/" end className={navClass}>
            Homepage
          </NavLink>
          <NavLink to="/decode" className={navClass}>
            Decoding
          </NavLink>
        </nav>
      </div>
    </aside>
  );
}
