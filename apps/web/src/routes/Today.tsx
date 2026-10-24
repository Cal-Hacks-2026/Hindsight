import { Link } from "react-router";
import type { RankedOpportunity } from "@hindsight/contracts";
import { OpportunityCard } from "../components/OpportunityCard";
import { NoProfile, RadarEmpty, RadarError, RadarLoading } from "../components/RadarStates";
import { TAGLINE } from "../lib/config";
import { nearestDeadline, useOpportunities } from "../lib/opportunities";
import { loadSession } from "../lib/session";
import { useNow } from "../lib/time";

const TOP_PICKS = 3;

export function Today() {
  const { profile } = loadSession();
  const { state, retry } = useOpportunities(profile?.id);
  const now = useNow(60_000);

  return (
    <section>
      <h1>{profile ? `Hi, ${profile.name}` : "Today"}</h1>
      <p className="muted">{TAGLINE}</p>

      {!profile ? (
        <NoProfile />
      ) : state.status === "loading" ? (
        <RadarLoading startedAt={state.startedAt} />
      ) : state.status === "error" ? (
        <RadarError error={state.error} onRetry={retry} />
      ) : state.items.length === 0 ? (
        <RadarEmpty campus={profile.campus} />
      ) : (
        <TodayFeed items={state.items} now={now} />
      )}
    </section>
  );
}

function TodayFeed({ items, now }: { items: RankedOpportunity[]; now: number }) {
  const alert = nearestDeadline(items, now);
  const picks = items.slice(0, TOP_PICKS);
  return (
    <>
      <h2>Nearest deadline</h2>
      {alert ? (
        <div className="alert">
          <OpportunityCard item={alert} now={now} as="article" />
        </div>
      ) : (
        <p className="card muted">No upcoming deadlines on your Radar right now.</p>
      )}

      <h2>Top picks for you</h2>
      <ol className="opportunities">
        {picks.map((item, i) => (
          <OpportunityCard key={item.id} item={item} now={now} rank={i + 1} />
        ))}
      </ol>
      {items.length > picks.length && (
        <p className="see-all">
          <Link to="/radar">See all {items.length} on Radar →</Link>
        </p>
      )}
    </>
  );
}
