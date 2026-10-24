import { Listing } from "../components/Listing";
import { Masthead, Note, Section } from "../components/Paper";
import { NoProfile, RadarEmpty, RadarError, RadarLoading } from "../components/RadarStates";
import { CAMPUS_SHORT, plural } from "../lib/format";
import { useOpportunities } from "../lib/opportunities";
import { loadSession } from "../lib/session";
import { useNow } from "../lib/time";

const SHOWN = 10;

export function Radar() {
  const { profile } = loadSession();
  const { state, retry } = useOpportunities(profile?.id);
  const now = useNow(60_000);
  const ready = state.status === "ready" ? state.items.slice(0, SHOWN) : undefined;

  return (
    <>
      <Masthead kicker={`Campus opportunities${profile ? ` · ${CAMPUS_SHORT[profile.campus]}` : ""}`}>
        Opportunities,
        <br />
        <em>ranked</em> for you.
      </Masthead>
      <Section
        num={1}
        label="Ranked"
        title={ready?.length ? `${ready.length} ${plural(ready.length, "listing")}, best fit first.` : undefined}
        last
        notes={
          ready?.length ? (
            <>
              <Note lead="How it's ranked.">
                How well each one matches your majors, goals and interests, plus how soon it closes. The italic line
                is Claude's reason; dates come only from the source page.
              </Note>
              <Note lead="Time left.">Red closes within two days, amber within a week.</Note>
            </>
          ) : undefined
        }
      >
        {!profile ? (
          <NoProfile />
        ) : state.status === "loading" ? (
          <RadarLoading startedAt={state.startedAt} skeletons={4} />
        ) : state.status === "error" ? (
          <RadarError error={state.error} onRetry={retry} />
        ) : !ready?.length ? (
          <RadarEmpty campus={profile.campus} />
        ) : (
          <ol className="entries">
            {ready.map((item, i) => (
              <Listing key={item.id} item={item} now={now} rank={i + 1} />
            ))}
          </ol>
        )}
      </Section>
    </>
  );
}
