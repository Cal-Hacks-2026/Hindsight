// Loading, empty, error, and no-profile states shared by Today and Radar.
import { Link } from "react-router";
import type { Campus } from "@hindsight/contracts";
import { ApiError } from "../lib/api";
import { useNow } from "../lib/time";

const CAMPUS_LABEL: Record<Campus, string> = { sjsu: "SJSU", berkeley: "UC Berkeley" };

// The first load is one long Claude call (DECISIONS.md D-005); say what's happening as time passes.
function loadingMessage(seconds: number): string {
  if (seconds < 4) return "Pulling this week's campus events and opportunities…";
  if (seconds < 20) return "Claude is writing why each one fits you…";
  return "Still working. The first load sometimes runs a little long.";
}

export function RadarLoading({ startedAt, skeletons = 3 }: { startedAt: number; skeletons?: number }) {
  const now = useNow(1000);
  const seconds = Math.max(0, Math.floor((now - startedAt) / 1000));
  return (
    <div className="radar-loading" role="status" aria-live="polite">
      <div className="card loading-banner">
        <div className="loading-head">
          <span className="spinner" aria-hidden="true" />
          <strong>{loadingMessage(seconds)}</strong>
          <span className="muted elapsed" aria-hidden="true">
            {seconds}s
          </span>
        </div>
        <div className="loading-bar" aria-hidden="true" />
        <p className="muted">
          Your first Radar load takes about 15 seconds while we rank everything for your profile. After that it's
          instant.
        </p>
      </div>
      <ul className="opportunities" aria-hidden="true">
        {Array.from({ length: skeletons }, (_, i) => (
          <li key={i} className="card skeleton">
            <span className="skeleton-line w-60" />
            <span className="skeleton-line w-30" />
            <span className="skeleton-line w-90" />
            <span className="skeleton-line w-75" />
          </li>
        ))}
      </ul>
    </div>
  );
}

export function RadarError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  let title = "Couldn't load your Radar.";
  let detail = "We couldn't reach the Hindsight server. Check your connection and try again.";
  let canRetry = true;

  if (error instanceof ApiError) {
    if (error.status === 404) {
      title = "We couldn't find your profile.";
      detail = "It may have been reset on the server. Set it up again to get your Radar back.";
      canRetry = false;
    } else if (error.status === 429) {
      detail = "Too many requests in a short time. Wait a minute, then try again.";
    } else {
      detail = `The server returned an error (${error.status}${error.message ? `: ${error.message}` : ""}).`;
    }
  }

  return (
    <div className="card stack state-card" role="alert">
      <div>
        <strong>{title}</strong>
        <p className="muted">{detail}</p>
      </div>
      <div className="row">
        {canRetry ? (
          <button className="primary" onClick={onRetry}>
            Try again
          </button>
        ) : (
          <Link to="/onboarding">Set up your profile →</Link>
        )}
      </div>
    </div>
  );
}

export function RadarEmpty({ campus }: { campus: Campus }) {
  return (
    <div className="card stack state-card">
      <div>
        <strong>Nothing on your Radar yet.</strong>
        <p className="muted">
          No upcoming {CAMPUS_LABEL[campus]} events or opportunities matched your profile. Droid rescans campus
          sources on a schedule, so check back after the next run.
        </p>
      </div>
      <div className="row">
        <Link to="/agent">See the latest scan →</Link>
      </div>
    </div>
  );
}

export function NoProfile() {
  return (
    <div className="card stack state-card">
      <div>
        <strong>Set up your profile first.</strong>
        <p className="muted">Radar ranks campus events and opportunities against your majors, goals, and interests.</p>
      </div>
      <div className="row">
        <Link to="/onboarding">Start onboarding →</Link>
      </div>
    </div>
  );
}
