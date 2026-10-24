import { OpportunityCard } from "../components/OpportunityCard";
import { NoProfile, RadarEmpty, RadarError, RadarLoading } from "../components/RadarStates";
import { useOpportunities } from "../lib/opportunities";
import { loadSession } from "../lib/session";
import { useNow } from "../lib/time";

export function Radar() {
  const { profile } = loadSession();
  const { state, retry } = useOpportunities(profile?.id);
  const now = useNow(60_000);

  return (
    <section>
      <h1>Campus Radar</h1>
      <p className="muted">Events and opportunities ranked for you, with why each one fits.</p>

      {!profile ? (
        <NoProfile />
      ) : state.status === "loading" ? (
        <RadarLoading startedAt={state.startedAt} skeletons={4} />
      ) : state.status === "error" ? (
        <RadarError error={state.error} onRetry={retry} />
      ) : state.items.length === 0 ? (
        <RadarEmpty campus={profile.campus} />
      ) : (
        <>
          <p className="muted count">
            {state.items.length} {state.items.length === 1 ? "match" : "matches"}, best first
          </p>
          <ol className="opportunities">
            {state.items.map((item, i) => (
              <OpportunityCard key={item.id} item={item} now={now} rank={i + 1} />
            ))}
          </ol>
        </>
      )}
    </section>
  );
}
