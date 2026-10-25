import type { RankedOpportunity } from "@hindsight/contracts";
import { Listing, NewLabel, safeUrl, typeLabel } from "../components/Listing";
import { Masthead, Section } from "../components/Paper";
import {
  NoProfile,
  RadarEmpty,
  RadarError,
  RadarLoading,
  RadarUnwatched,
} from "../components/RadarStates";
import { plural, shortUniversity, universityName } from "../lib/format";
import { useOpportunities } from "../lib/opportunities";
import { loadSession } from "../lib/session";
import { closeAt, formatWhen, useNow } from "../lib/time";

const SHOWN = 10;
const WEEK = 7 * 24 * 60 * 60 * 1000;

type Upcoming = {
  item: RankedOpportunity;
  at: number;
  iso: string;
  verb: string;
};

/** "Closes" for a deadline; a hackathon's scraped deadline is when its run ends (lib/time closeAt). */
function dates(item: RankedOpportunity, now: number): Omit<Upcoming, "item">[] {
  const due = closeAt(item, now);
  return [
    {
      iso: due === item.starts_at ? "" : (due ?? ""),
      verb: item.type === "hackathon" ? "Ends" : "Closes",
    },
    { iso: item.starts_at ?? "", verb: "Starts" },
  ]
    .map((d) => ({ ...d, at: Date.parse(d.iso) }))
    .filter((d) => !Number.isNaN(d.at) && d.at >= now);
}

/** Listings that start or close within 7 days: Droid's alerts first, then soonest first. */
function thisWeek(items: RankedOpportunity[], now: number): Upcoming[] {
  const out: Upcoming[] = [];
  for (const item of items) {
    const first = dates(item, now)
      .filter((d) => d.at - now <= WEEK)
      .sort((a, b) => a.at - b.at)[0];
    if (first) out.push({ item, ...first });
  }
  return out.sort(
    (a, b) => Number(b.item.notified) - Number(a.item.notified) || a.at - b.at,
  );
}

/** The soonest dated listing past this week, for the empty strip's "Next up". */
function nextUp(
  items: RankedOpportunity[],
  now: number,
): { title: string; at: number } | undefined {
  const dated = items.flatMap((item) =>
    dates(item, now).map((d) => ({ title: item.title, at: d.at })),
  );
  return dated.sort((a, b) => a.at - b.at)[0];
}

const monthOf = (at: number) =>
  new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Los_Angeles",
    month: "long",
  }).format(new Date(at));

export function Radar() {
  const { profile } = loadSession();
  // "other": a university with no Radar sources. Nothing to fetch; another campus's feed would mislead.
  const unwatched = profile?.campus === "other";
  const campus = profile ? shortUniversity(universityName(profile)) : undefined;
  const { state, retry } = useOpportunities(
    unwatched ? undefined : profile?.id,
  );
  const now = useNow(60_000);
  const ready =
    state.status === "ready" ? state.items.slice(0, SHOWN) : undefined;
  const week =
    !unwatched && state.status === "ready" && state.items.length
      ? thisWeek(state.items, now)
      : undefined;
  const next =
    week?.length === 0 && state.status === "ready"
      ? nextUp(state.items, now)
      : undefined;

  return (
    <>
      <Masthead sketch="compass">Opportunities</Masthead>
      {week && (
        <Section
          num={1}
          label="This week"
          title={week.length ? "This week" : undefined}
        >
          {week.length ? (
            <ol className="week">
              {week.map((w) => (
                <WeekRow key={w.item.id} {...w} />
              ))}
            </ol>
          ) : (
            <p className="lede">
              Nothing starts or closes this week.
              {next ? ` Next up: ${next.title}, in ${monthOf(next.at)}.` : ""}
            </p>
          )}
        </Section>
      )}
      <Section
        num={week ? 2 : 1}
        label="Ranked"
        title={
          ready?.length
            ? `${ready.length} ${plural(ready.length, "opportunity", "opportunities")} for you`
            : undefined
        }
        last
      >
        {!profile ? (
          <NoProfile />
        ) : unwatched ? (
          <RadarUnwatched university={campus!} />
        ) : state.status === "loading" ? (
          <RadarLoading startedAt={state.startedAt} skeletons={4} />
        ) : state.status === "error" ? (
          <RadarError error={state.error} onRetry={retry} />
        ) : !ready?.length ? (
          <RadarEmpty campus={campus!} />
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

function WeekRow({ item, iso, verb }: Upcoming) {
  const link = safeUrl(item.url);
  const when = formatWhen(iso);
  return (
    <li>
      <span className="week-when">
        {verb} {when}
      </span>
      <div className="week-body">
        {link ? (
          <a
            className="week-title"
            href={link.href}
            target="_blank"
            rel="noreferrer"
          >
            {item.title}
          </a>
        ) : (
          <span className="week-title">{item.title}</span>
        )}
        {item.notified && <NewLabel />}
        <div className="meta">
          {[typeLabel(item.type), item.org].filter(Boolean).join(" · ")}
        </div>
      </div>
    </li>
  );
}
