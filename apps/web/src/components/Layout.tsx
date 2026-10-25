import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router";
import { api } from "../lib/api";
import { APP_NAME } from "../lib/config";
import { CAMPUS_SHORT, currentTerm } from "../lib/format";
import { loadSession } from "../lib/session";
import { Icon, type IconName } from "./Icons";

const HEALTH_RETRIES = 4;
const HEALTH_RETRY_MS = 8000;

const NAV: { to: string; label: string; icon: IconName }[] = [
  { to: "/degree", label: "My degree", icon: "book" },
  { to: "/radar", label: "Opportunities", icon: "compass" },
  { to: "/counselor", label: "Counselor", icon: "chat" },
  { to: "/agent", label: "Droid activity", icon: "activity" },
];

export function Layout() {
  const { pathname } = useLocation(); // also re-reads the session on navigation (onboarding writes it)
  const { profile } = loadSession();
  const [degraded, setDegraded] = useState<string | null>(null);

  // The API host sleeps when idle and takes a while to wake, so retry before calling it unreachable.
  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout>;
    const check = (attempt: number) =>
      api.health().then(
        (h) => {
          if (!live) return;
          if (h.storage === false)
            setDegraded(
              "Profiles can't be saved right now, so setup won't work yet.",
            );
          else if (h.claude === false)
            setDegraded(
              "The counselor and transcript reading are offline right now.",
            );
          else setDegraded(null);
        },
        () => {
          if (!live) return;
          if (attempt < HEALTH_RETRIES)
            timer = setTimeout(() => check(attempt + 1), HEALTH_RETRY_MS);
          else setDegraded("The server isn't reachable right now.");
        },
      );
    check(0);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, []);

  const page = NAV.find((item) => item.to === pathname)?.label ?? "Get started";

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <aside className="sidebar">
        <Link to="/" className="brand" aria-label={`${APP_NAME}, home`}>
          <span className="brand-symbol">
            <Icon name="book" size={23} />
          </span>
          <span className="wordmark">
            {APP_NAME.toLowerCase()}
            <span className="brand-period">.</span>
          </span>
        </Link>
        <nav className="nav" aria-label="Main">
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} end>
              <Icon name={item.icon} size={19} />
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="campus-label">
            <Icon name="school" size={18} />
            <span>
              De Anza <span aria-hidden="true">→</span> SJSU
            </span>
          </div>
          <Link
            to="/onboarding"
            className="profile-link"
            aria-label={
              profile ? `${profile.name}, profile setup` : "Set up your profile"
            }
          >
            <span className="avatar">
              {profile?.name.trim().charAt(0).toUpperCase() || (
                <Icon name="user" size={17} />
              )}
            </span>
            <span>
              <strong>{profile?.name || "Your profile"}</strong>
              <small>
                {profile ? CAMPUS_SHORT[profile.campus] : "Get started"}
              </small>
            </span>
            <Icon name="chevron" size={15} />
          </Link>
        </div>
      </aside>
      <div className="workspace">
        <header className="workspace-bar">
          <span>
            My workspace <span className="breadcrumb-divider">/</span>{" "}
            <strong>{page}</strong>
          </span>
          <span className="term-meta">
            <Icon name="calendar" size={15} />
            {currentTerm()}
          </span>
        </header>
        {degraded && (
          <p className="status-banner" role="status">
            {degraded}
          </p>
        )}
        <main id="main-content" tabIndex={-1}>
          <Outlet />
        </main>
        <footer className="app-footer">
          <span>{APP_NAME}</span>
          <span>Confirm academic decisions with your advisor.</span>
        </footer>
      </div>
    </div>
  );
}
