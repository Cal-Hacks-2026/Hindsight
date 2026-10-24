import { NavLink, Outlet } from "react-router";
import { APP_NAME } from "../lib/config";

const NAV = [
  { to: "/", label: "Today" },
  { to: "/degree", label: "Degree" },
  { to: "/radar", label: "Radar" },
  { to: "/counselor", label: "Counselor" },
  { to: "/agent", label: "Agent" },
  { to: "/onboarding", label: "Onboarding" },
];

export function Layout() {
  return (
    <>
      <header className="app-header">
        <NavLink to="/" className="brand">
          {APP_NAME}
        </NavLink>
        <nav className="nav">
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} end>
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main>
        <Outlet />
      </main>
    </>
  );
}
