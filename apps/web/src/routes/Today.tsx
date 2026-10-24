import { Link } from "react-router";
import { TAGLINE } from "../lib/config";
import { loadSession } from "../lib/session";

export function Today() {
  const { profile } = loadSession();
  return (
    <section>
      <h1>{profile ? `Hi, ${profile.name}` : "Today"}</h1>
      <p className="muted">{TAGLINE}</p>
      <div className="card stack">
        <p className="muted">Top alerts, deadlines, and this week's picks land here in Phase 2.</p>
        {!profile && (
          <p>
            <Link to="/onboarding">Start onboarding →</Link>
          </p>
        )}
      </div>
    </section>
  );
}
