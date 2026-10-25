import { useEffect, useState } from "react";
import { Link, NavLink, Outlet } from "react-router";
import { api } from "../lib/api";
import { APP_NAME, TAGLINE } from "../lib/config";
import { loadSession } from "../lib/session";
import { Icon, type IconName } from "./Icons";

const HEALTH_RETRIES = 4;
const HEALTH_RETRY_MS = 8000;

const NAV: { to: string; label: string; icon: IconName }[] = [
  { to: "/plan", label: "My plan", icon: "calendar" },
  { to: "/credits", label: "My credits", icon: "book" },
  { to: "/radar", label: "Opportunities", icon: "compass" },
  { to: "/counselor", label: "Ask Hindsight", icon: "chat" },
];

export function Layout() {
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

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <aside className="sidebar">
        <Link to="/" className="brand" aria-label={`${APP_NAME}, home`}>
          <img
            className="brand-logo"
            src="/brand/janus-ink.svg"
            alt=""
            width={54}
            height={62}
          />
          <span className="brand-text">
            <span className="wordmark">{APP_NAME}</span>
            <span className="brand-tagline">{TAGLINE}</span>
          </span>
        </Link>
        <nav className="nav" aria-label="Main">
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} end>
              <Icon name={item.icon} size={24} />
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <Link
            to="/onboarding"
            className="profile-link"
            aria-label={
              profile ? `${profile.name}, profile setup` : "Set up your profile"
            }
          >
            <span className="avatar">
              {profile?.name.trim().charAt(0).toUpperCase() || (
                <Icon name="user" size={24} />
              )}
            </span>
            <span>
              <strong>{profile?.name || "Your profile"}</strong>
            </span>
            <Icon name="chevron" size={15} />
          </Link>
        </div>
      </aside>
      <div className="workspace">
        {degraded && (
          <p className="status-banner" role="status">
            {degraded}
          </p>
        )}
        <main id="main-content" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
