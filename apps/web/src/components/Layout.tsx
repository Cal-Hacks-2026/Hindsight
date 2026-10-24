import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router";
import { api } from "../lib/api";
import { APP_NAME } from "../lib/config";
import { CAMPUS_SHORT, currentTerm, majorsLine } from "../lib/format";
import { loadSession } from "../lib/session";

const NAV = [
  { to: "/degree", label: "Degree" },
  { to: "/radar", label: "Opportunities" },
  { to: "/counselor", label: "Counselor" },
  { to: "/agent", label: "Droid activity" },
];

// The footer's right-hand note, per page (design/mockups).
const FOOTER_NOTE: Record<string, string> = {
  "/radar": "Every listing links to its source",
  "/counselor": "Hindsight explains computed results · It never decides whether a credit counts",
};
const DEFAULT_NOTE = "Every claim is sourced · Confirm decisions with your advisor";

export function Layout() {
  const { pathname } = useLocation(); // also re-reads the session on navigation (onboarding writes it)
  const { profile } = loadSession();
  const [degraded, setDegraded] = useState<string | null>(null);

  useEffect(() => {
    api
      .health()
      .then((h) => {
        if (h.storage === false) setDegraded("Profiles can't be saved right now, so setup won't work yet.");
        else if (h.claude === false) setDegraded("The counselor and transcript reading are offline right now.");
      })
      .catch(() => setDegraded("The server isn't reachable right now."));
  }, []);

  return (
    <>
      <header className="app-header">
        <Link to="/" className="brand" aria-label={`${APP_NAME}, home`}>
          <img src="/brand/janus-ink.svg" alt="" width={34} height={38} />
          <span className="wordmark">{APP_NAME.toUpperCase()}</span>
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
        ) : (
          <Link to="/onboarding" className="header-meta">
            Set up your profile →
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
        <span>
          {APP_NAME} · <em className="motto">Respice · Prospice</em>
        </span>
        <span>{FOOTER_NOTE[pathname] ?? DEFAULT_NOTE}</span>
      </footer>
    </>
  );
}
