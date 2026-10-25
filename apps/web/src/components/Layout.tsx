import { useCallback, useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router";
import { api } from "../lib/api";
import { APP_NAME, TAGLINE } from "../lib/config";
import { loadSession } from "../lib/session";
import { ASK_PANEL_ID, AskPanel } from "./AskPanel";
import { Icon, type IconName } from "./Icons";
import "../styles/shell.css";

/** Sources and other answers sit in closed <details>: open the one holding a citation's target
 *  (and any around it) so following "#source-3" lands on visible text. */
function openCitedSource(hash: string) {
  if (hash.length < 2) return;
  let details = document
    .getElementById(decodeURIComponent(hash.slice(1)))
    ?.closest("details");
  while (details) {
    details.open = true;
    details = details.parentElement?.closest("details");
  }
}

const HEALTH_RETRIES = 4;
const HEALTH_RETRY_MS = 8000;

// Ask isn't a page in the nav: it opens as a panel over any page (/counselor still works for links).
const NAV: { to: string; label: string; icon: IconName }[] = [
  { to: "/", label: "Home", icon: "home" },
  { to: "/plan", label: "Plan", icon: "calendar" },
  { to: "/credits", label: "Credits", icon: "book" },
  { to: "/schedule", label: "Schedule", icon: "clock" },
  { to: "/radar", label: "Opportunities", icon: "compass" },
  { to: "/university", label: "University", icon: "school" },
];

export function Layout() {
  const { profile } = loadSession();
  const [degraded, setDegraded] = useState<string | null>(null);
  const { pathname } = useLocation();
  const [askOpen, setAskOpen] = useState(false);
  const [askMounted, setAskMounted] = useState(false);
  const closeAsk = useCallback(() => setAskOpen(false), []);
  const toggleAsk = () => {
    setAskMounted(true);
    setAskOpen((o) => !o);
  };
  // The Counselor page is Ask already; a second copy in the panel would just repeat it.
  const askHere = pathname !== "/counselor";
  useEffect(() => {
    if (!askHere) setAskOpen(false);
  }, [askHere]);
  const askButton = (className: string) =>
    askHere && (
      <button
        type="button"
        className={`ask-open ${className}`}
        aria-expanded={askOpen}
        aria-controls={ASK_PANEL_ID}
        aria-label="Ask Hindsight"
        onClick={toggleAsk}
      >
        <Icon name="chat" size={24} />
        <span>Ask Hindsight</span>
      </button>
    );

  useEffect(() => {
    // Capture phase: open the details before the browser follows the link and scrolls.
    const onClick = (e: MouseEvent) => {
      const link = (e.target as Element | null)?.closest?.('a[href^="#"]');
      if (link) openCitedSource(link.getAttribute("href")!);
    };
    const onHash = () => openCitedSource(window.location.hash);
    // A printed ed plan lists its sources in full.
    const onPrint = () =>
      document
        .querySelectorAll<HTMLDetailsElement>("details.sources-details")
        .forEach((d) => (d.open = true));
    document.addEventListener("click", onClick, true);
    window.addEventListener("hashchange", onHash);
    window.addEventListener("beforeprint", onPrint);
    return () => {
      document.removeEventListener("click", onClick, true);
      window.removeEventListener("hashchange", onHash);
      window.removeEventListener("beforeprint", onPrint);
    };
  }, []);

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
        Skip to Content
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
        {askButton("ask-open-compact")}
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
          {/* Floats beside the page header, so it takes no height of its own. */}
          {askHere && (
            <div className="topbar">{askButton("ask-open-wide")}</div>
          )}
          <Outlet />
        </main>
      </div>
      {askHere && (
        <AskPanel
          open={askOpen}
          mounted={askMounted}
          pathname={pathname}
          onClose={closeAsk}
        />
      )}
    </div>
  );
}
