// Loading, empty, error, and no-profile states used by Radar.
import { Link } from "react-router";
import { ApiError } from "../lib/api";
import { useNow } from "../lib/time";

// The first load is one long Claude call (DECISIONS.md D-005); say what's happening as time passes.
function loadingMessage(seconds: number): string {
  if (seconds < 4) return "Finding Your Opportunities…";
  if (seconds < 20) return "Matching Opportunities to Your Interests…";
  return "Still Working…";
}

export function RadarLoading({
  startedAt,
  skeletons = 3,
  quick,
}: {
  startedAt: number;
  skeletons?: number;
  /** A filtered list: it never waits on reasons, so leave out the first-visit note. */
  quick?: boolean;
}) {
  const now = useNow(1000);
  const seconds = Math.max(0, Math.floor((now - startedAt) / 1000));
  return (
    <div role="status" aria-live="polite">
      <div className="state">
        <div className="loading-head">
          <h3>{loadingMessage(seconds)}</h3>
          <span className="muted elapsed" aria-hidden="true">
            {seconds}s
          </span>
        </div>
        <div className="loading-bar" aria-hidden="true" />
        {!quick && (
          <p>
            {seconds >= 20
              ? "The first load sometimes runs a little long."
              : "The first visit can take about 15 seconds."}
          </p>
        )}
      </div>
      <div aria-hidden="true">
        {Array.from({ length: skeletons }, (_, i) => (
          <div key={i} className="skeleton">
            <span className="skeleton-line w-30" />
            <span className="skeleton-line w-60" />
            <span className="skeleton-line w-90" />
            <span className="skeleton-line w-75" />
          </div>
        ))}
      </div>
    </div>
  );
}

export function RadarError({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry: () => void;
}) {
  let title = "Couldn't Load Your Opportunities";
  let detail =
    "We couldn't reach the Hindsight server. Check your connection and try again.";
  let canRetry = true;

  if (error instanceof ApiError) {
    if (error.status === 404) {
      title = "We Couldn't Find Your Profile";
      detail =
        "It may have been reset on the server. Set it up again to get your opportunities back.";
      canRetry = false;
    } else if (error.status === 429) {
      detail =
        "Too many requests in a short time. Wait a minute, then try again.";
    } else {
      detail = `The server returned an error (${error.status}${error.message ? `: ${error.message}` : ""}).`;
    }
  }

  return (
    <div className="state" role="alert">
      <h3>{title}</h3>
      <p>{detail}</p>
      <div className="actions">
        {canRetry ? (
          <button className="primary" onClick={onRetry}>
            Try Again
          </button>
        ) : (
          <Link className="button primary" to="/onboarding">
            Set Up Your Profile
          </Link>
        )}
      </div>
    </div>
  );
}

export function RadarEmpty({ campus }: { campus: string }) {
  return (
    <div className="state">
      <h3>No Opportunities Yet</h3>
      <p>
        No upcoming {campus} listings match your profile yet. Check back after
        the next campus scan.
      </p>
    </div>
  );
}

/** A university with no Radar sources: say so instead of showing an empty or another campus's feed. */
export function RadarUnwatched({ university }: { university: string }) {
  return (
    <div className="state">
      <h3>{university}'s Campus Isn't Covered Yet</h3>
      <p>
        Opportunities are listed only for campuses Hindsight scans, and{" "}
        {university} isn't one of them yet. Your plan and credits work the same.
      </p>
      <div className="actions">
        <Link className="button" to="/plan">
          Open My Plan
        </Link>
      </div>
    </div>
  );
}

export function NoProfile() {
  return (
    <div className="state">
      <h3>Set Up Your Profile First</h3>
      <p>
        Hindsight ranks campus events and opportunities against your majors,
        goals, and interests.
      </p>
      <div className="actions">
        <Link className="button primary" to="/onboarding">
          Create Your Profile
        </Link>
      </div>
    </div>
  );
}
