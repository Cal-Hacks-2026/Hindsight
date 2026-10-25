import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router";
import { api } from "../lib/api";
import { APP_NAME } from "../lib/config";
import { CAMPUS_SHORT, currentTerm, majorsLine } from "../lib/format";
import { loadSession } from "../lib/session";

const HEALTH_RETRIES = 4;
const HEALTH_RETRY_MS = 8000;

const NAV = [
  { to: "/degree", label: "Degree" },
  { to: "/radar", label: "Opportunities" },
  { to: "/counselor", label: "Counselor" },
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
          if (h.storage === false) setDegraded("Profiles can't be saved right now, so setup won't work yet.");
          else if (h.claude === false) setDegraded("The counselor and transcript reading are offline right now.");
          else setDegraded(null);
        },
        () => {
          if (!live) return;
          if (attempt < HEALTH_RETRIES) timer = setTimeout(() => check(attempt + 1), HEALTH_RETRY_MS);
          else setDegraded("The server isn't reachable right now.");
        },
      );
    check(0);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, []);

  return (
    <>
      <header className="app-header">
        <Link to="/" className="brand" aria-label={`${APP_NAME}, home`}>
          <img src="/brand/janus-ink.svg" alt="" width={34} height={38} />
          <span className="brand-text">
            <span className="wordmark">{APP_NAME.toUpperCase()}</span>
            <span className="subline">Plan Your Four-Year Journey</span>
          </span>
        </Link>
        <nav className="nav" aria-label="Main">
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} end>
              {item.label}
            </NavLink>
          ))}
        </nav>
        {profile ? (
          <span className="header-meta">
            {[CAMPUS_SHORT[profile.campus], majorsLine(profile.majors), currentTerm()].filter(Boolean).join(" · ")}
          </span>
        ) : pathname === "/onboarding" ? null : (
          <Link to="/onboarding" className="header-meta">
            Set Up Your Profile
          </Link>
        )}
      </header>
      <div className="hairline" />
      {degraded && (
        <p className="status-banner" role="status">
          {degraded}
        </p>
      )}
      <main>
        <Outlet />
      </main>
      <div className="hairline" />
      <footer className="app-footer">
        <span>Confirm decisions with your advisor.</span>
        <Link to="/agent">How listings stay fresh</Link>
      </footer>
    </>
  );
}
