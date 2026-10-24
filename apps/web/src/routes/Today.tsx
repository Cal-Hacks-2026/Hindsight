import { Link } from "react-router";
import type { Profile, RankedOpportunity } from "@hindsight/contracts";
import { Listing, hostOf, safeUrl, typeLabel } from "../components/Listing";
import { Masthead, Note, Ref, Section } from "../components/Paper";
import { NoProfile, RadarEmpty, RadarError, RadarLoading } from "../components/RadarStates";
import { Shelf, Spine } from "../components/Spine";
import { CAMPUS_SHORT, countWord, formatDateline, listing, plural } from "../lib/format";
import { useOpportunities } from "../lib/opportunities";
import { loadSession } from "../lib/session";
import { LISTING_LEGEND, listingColor, spineHeight } from "../lib/shelf";
import { useNow } from "../lib/time";

const PICKS = 3;
const SHELF = 10;
const WEEK = 7 * 24 * 60 * 60 * 1000;

export function Today() {
  const { profile } = loadSession();
  const { state, retry } = useOpportunities(profile?.id);
  const now = useNow(60_000);

  const masthead = (
    <Masthead kicker={formatDateline(new Date(now))}>
      What you'd <em>wish</em> you knew,
      <br />
      this week.
    </Masthead>
  );

  if (!profile || state.status !== "ready" || state.items.length === 0) {
    return (
      <>
        {masthead}
        <Section num={1} label="Before it closes" last>
          {!profile ? (
            <NoProfile />
          ) : state.status === "loading" ? (
            <RadarLoading startedAt={state.startedAt} />
          ) : state.status === "error" ? (
            <RadarError error={state.error} onRetry={retry} />
          ) : (
            <RadarEmpty campus={profile.campus} />
          )}
        </Section>
      </>
    );
  }

  return (
    <>
      {masthead}
      <Edition profile={profile} items={state.items} now={now} />
    </>
  );
}

function Edition({ profile, items, now }: { profile: Profile; items: RankedOpportunity[]; now: number }) {
  const upcoming = (i: RankedOpportunity) => {
    const at = i.deadline ? Date.parse(i.deadline) : NaN;
    return !Number.isNaN(at) && at > now;
  };
  // Items stay in rank order; the lead section is the best-ranked ones that still have a deadline ahead.
  const closing = items.filter(upcoming).slice(0, PICKS);
  const byDeadline = closing.length > 0;
  const picks = byDeadline ? closing : items.slice(0, PICKS);
  const rest = items.filter((i) => !picks.includes(i)).slice(0, SHELF);
  const thisWeek = items.filter((i) => upcoming(i) && Date.parse(i.deadline!) - now < WEEK).length;
  const hosts = [...new Set(items.flatMap((i) => {
    const u = safeUrl(i.url);
    return u ? [hostOf(u)] : [];
  }))];
  const campus = CAMPUS_SHORT[profile.campus];

  return (
    <>
      <Section
        label="Abstract"
        notesFlush
        notes={
          <p id="source-1">
            <strong>1</strong>&nbsp; {hosts.length ? `${listing(hosts)}. ` : ""}Every item links to its original page.
          </p>
        }
      >
        <p className="lede">
          Hindsight ranked {items.length} {campus} {plural(items.length, "listing")} against your majors, goals and
          interests.
          <Ref n={1} /> {thisWeek ? `${countWord(thisWeek, true)} ${thisWeek === 1 ? "closes" : "close"} within a week.` : "Nothing closes within a week."}
        </p>
      </Section>

      <Section
        num={1}
        label={byDeadline ? "Before it closes" : "Top picks"}
        notes={
          <Note lead={`Why ${picks.length === 1 ? "this one" : `these ${countWord(picks.length)}`}.`}>
            {byDeadline
              ? "The best-ranked listings that still have a deadline ahead, scored on your majors, goals and interests plus how soon they close."
              : "Scored on your majors, goals and interests plus how soon they close."}{" "}
            The italic line is Claude's reason; the dates come only from the source page.
          </Note>
        }
      >
        <ol className="entries">
          {picks.map((item, i) => (
            <Listing key={item.id} item={item} now={now} rank={byDeadline ? undefined : i + 1} />
          ))}
        </ol>
      </Section>

      {rest.length > 0 && (
        <Section num={2} label="On your radar" title="Further reading, shelved by kind.">
          <figure>
            <Shelf wide label="More listings, as shelved books">
              {rest.map((item) => {
                const link = safeUrl(item.url);
                return (
                  <Spine
                    key={item.id}
                    label={typeLabel(item.type).toUpperCase()}
                    color={listingColor(item.type)}
                    kind="solid"
                    width={spineHeight(`${item.id}w`, 36, 50)}
                    height={spineHeight(item.id, 158, 196)}
                    href={link?.href}
                    title={[item.title, item.org].filter(Boolean).join(" · ")}
                    textSize={11}
                  />
                );
              })}
            </Shelf>
            <figcaption className="legend">
              <span>
                <em className="fig">Fig. 1.</em> The next {countWord(rest.length)} listings ranked for you. Select a
                spine to open it.
              </span>
              {LISTING_LEGEND.filter((l) => rest.some((i) => listingColor(i.type) === l.color)).map((l) => (
                <span key={l.label} style={{ color: l.color }}>
                  ■ {l.label}
                </span>
              ))}
            </figcaption>
          </figure>
          <p style={{ margin: "28px 0 0" }}>
            <Link to="/radar">See all {items.length} on Radar →</Link>
          </p>
        </Section>
      )}

      <Section
        num={rest.length > 0 ? 3 : 2}
        label="Methods"
        title="How this edition was made."
        last
        notes={
          <Note lead="Run by Droid.">
            The agent rescans campus sources on a schedule. When a site changes and a reader breaks, it repairs only
            that reader. <Link to="/agent">See the latest run →</Link>
          </Note>
        }
      >
        <ol className="methods">
          <li>
            <span className="meta">Plan</span>
            <span>Collect upcoming {campus} events and opportunities, then rank them against your profile.</span>
          </li>
          <li>
            <span className="meta">Step</span>
            <span>Listings come from {hosts.length} {plural(hosts.length, "site")}; every one keeps the link to its page.</span>
          </li>
          <li>
            <span className="meta">Step</span>
            <span>Ranked by majors, goals, interests and deadline. Claude wrote one reason per listing.</span>
          </li>
          <li>
            <span className="meta result">Result</span>
            <span>
              {items.length} {plural(items.length, "listing")} ranked; {thisWeek} {thisWeek === 1 ? "closes" : "close"} within 7 days.
            </span>
          </li>
        </ol>
      </Section>
    </>
  );
}
