import type { RankedOpportunity } from "@hindsight/contracts";
import { Link, useSearchParams } from "react-router";
import { Listing, NewLabel, safeUrl, typeLabel } from "../components/Listing";
import { Masthead, Section } from "../components/Paper";
import {
  NoProfile,
  RadarEmpty,
  RadarError,
  RadarLoading,
  RadarUnwatched,
} from "../components/RadarStates";
import { campusLabel, watched } from "../lib/campuses";
import { plural, shortUniversity, universityName } from "../lib/format";
import { fitFor, nextSevenDays, useFreeWeek, type FreeWeek } from "../lib/fits";
import { useOpportunities } from "../lib/opportunities";
import { loadSession } from "../lib/session";
import "../styles/opportunities.css";
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
  // Neither school has Radar sources in the registry. Nothing to fetch; another campus's feed would mislead.
  const unwatched = !!profile && !watched(profile);
  const campus = profile
    ? shortUniversity(universityName(profile), profile.receiving_institution_id)
    : undefined;
  const profileId = unwatched ? undefined : profile?.id;
  const [params, setParams] = useSearchParams();
  const category = params.get("category") ?? undefined;
  const subcategory = category ? (params.get("subcategory") ?? undefined) : undefined;
  const fits = params.get("fits") === "1";
  const type = params.get("type") ?? undefined; // University links: /radar?type=workshop
  const now = useNow(60_000);

  // The default feed: "This week", the category list and its counts, and the ranked list when unfiltered.
  const { state: base, retry: retryBase } = useOpportunities(profileId);
  const filtered = !!category || fits;
  const { state: picked, retry: retryPicked } = useOpportunities(
    filtered ? profileId : undefined,
    { category, subcategory, ...(fits ? nextSevenDays(now) : {}) },
  );
  const free = useFreeWeek(profileId, fits, now);
  const state = filtered ? picked : base;
  const retry = filtered ? retryPicked : retryBase;

  const categories = base.status === "ready" ? base.categories : [];
  const current = categories.find((c) => c.id === category);
  const subLabel = new Map(
    categories.flatMap((c) => c.subcategories.map((s) => [`${c.id}/${s.id}`, s.label] as const)),
  );
  const kindOf = (item: RankedOpportunity) =>
    item.category && item.subcategory
      ? subLabel.get(`${item.category}/${item.subcategory}`)
      : undefined;

  const set = (next: Record<string, string | undefined>) =>
    setParams(
      (prev) => {
        const out = new URLSearchParams(prev);
        for (const [k, v] of Object.entries(next)) {
          if (v) out.set(k, v);
          else out.delete(k);
        }
        return out;
      },
      { replace: true },
    );

  let shown: { item: RankedOpportunity; fit?: string }[] | undefined;
  if (state.status === "ready") {
    const items = state.items.filter((i) => !type || i.type === type);
    if (fits && free.status === "ready") {
      const seen = new Set<string>();
      shown = items.flatMap((item) => {
        const fit = fitFor(item, free.days, now);
        const key = item.title.toLowerCase();
        if (!fit || seen.has(key)) return [];
        seen.add(key);
        return [{ item, fit }];
      });
    } else if (!fits) {
      shown = (filtered ? items : items.slice(0, SHOWN)).map((item) => ({ item }));
    }
  }

  const week =
    !unwatched && base.status === "ready" && base.items.length
      ? thisWeek(base.items, now)
      : undefined;
  const next =
    week?.length === 0 && base.status === "ready"
      ? nextUp(base.items, now)
      : undefined;
  const scope = current
    ? (current.subcategories.find((s) => s.id === subcategory)?.label ?? current.label)
    : undefined;

  return (
    <>
      <Masthead sketch="compass">Opportunities</Masthead>
      {week && (
        <Section
          num={1}
          label="This week"
          title={week.length ? "This Week" : undefined}
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
          shown?.length
            ? `${shown.length} ${plural(shown.length, "opportunity", "opportunities")}${
                fits ? " that fit your week" : scope ? ` in ${scope}` : " for you"
              }`
            : undefined
        }
        last
      >
        {profileId && categories.length > 0 && (
          <div className="opp-controls">
            <div className="credit-filters" role="group" aria-label="Category">
              <button
                type="button"
                aria-pressed={!category}
                onClick={() => set({ category: undefined, subcategory: undefined })}
              >
                All
              </button>
              {categories
                .filter((c) => c.count > 0 || c.id === category)
                .map((c) => (
                  <button
                    type="button"
                    key={c.id}
                    aria-pressed={c.id === category}
                    onClick={() => set({ category: c.id, subcategory: undefined })}
                  >
                    {c.label}
                    {!fits && <span className="opp-count">{c.count}</span>}
                  </button>
                ))}
            </div>
            {current && current.subcategories.filter((s) => s.count > 0).length > 1 && (
              <div className="credit-filters opp-subfilters" role="group" aria-label={`${current.label} type`}>
                <button
                  type="button"
                  aria-pressed={!subcategory}
                  onClick={() => set({ subcategory: undefined })}
                >
                  All {current.label}
                </button>
                {current.subcategories
                  .filter((s) => s.count > 0 || s.id === subcategory)
                  .map((s) => (
                    <button
                      type="button"
                      key={s.id}
                      aria-pressed={s.id === subcategory}
                      onClick={() => set({ subcategory: s.id })}
                    >
                      {s.label}
                      {!fits && <span className="opp-count">{s.count}</span>}
                    </button>
                  ))}
              </div>
            )}
            <div className="opp-fits">
              <button
                type="button"
                className="opp-fits-toggle"
                aria-pressed={fits}
                onClick={() => set({ fits: fits ? undefined : "1" })}
              >
                <span className="opp-switch" aria-hidden="true" />
                Fits Your Week
              </button>
              {fits && <FitsNote free={free} />}
            </div>
            {type && (
              <p className="opp-type">
                Only {typeLabel(type)} listings.{" "}
                <button type="button" className="inline-link" onClick={() => set({ type: undefined })}>
                  Show All Types
                </button>
              </p>
            )}
          </div>
        )}
        {!profile ? (
          <NoProfile />
        ) : unwatched ? (
          <RadarUnwatched university={campus!} />
        ) : state.status === "loading" || (fits && free.status === "loading") ? (
          <RadarLoading
            startedAt={state.status === "loading" ? state.startedAt : now}
            skeletons={4}
            quick={filtered}
          />
        ) : state.status === "error" ? (
          <RadarError error={state.error} onRetry={retry} />
        ) : fits && free.status === "error" ? (
          <RadarError error={free.error} onRetry={() => set({ fits: undefined })} />
        ) : fits && free.status === "no-schedule" ? null : !shown?.length ? (
          filtered || type ? (
            <div className="state">
              <h3>{fits ? "Nothing Fits Your Week Yet" : "Nothing Here Right Now"}</h3>
              <p>
                {fits
                  ? `No ${scope ? `${scope} ` : ""}listings in the next 7 days start and end inside your free time.`
                  : `No current ${campus} listings${scope ? ` in ${scope}` : ""}. Check back after the next campus scan.`}
              </p>
            </div>
          ) : (
            <RadarEmpty campus={campus!} />
          )
        ) : (
          <ol className="entries">
            {shown.map(({ item, fit }, i) => (
              <Listing
                key={item.id}
                item={item}
                now={now}
                rank={i + 1}
                kind={kindOf(item)}
                fit={fit}
                campus={campusLabel(item.campus_id, profile)}
              />
            ))}
          </ol>
        )}
      </Section>
    </>
  );
}

/** What the toggle is checking against, or why it can't. */
function FitsNote({ free }: { free: FreeWeek }) {
  if (free.status === "no-schedule")
    return (
      <p className="opp-fits-note">
        Add your class schedule to see what fits around your classes.{" "}
        <Link to="/schedule">Go to Schedule</Link>
      </p>
    );
  if (free.status !== "ready") return null;
  return (
    <p className="opp-fits-note">
      Listings in the next 7 days that start and end inside your free time
      {free.term ? `, around your ${free.term} classes` : ""}. Free time is 7 AM–10 PM outside class.{" "}
      <Link to="/schedule">See Your Week</Link>
    </p>
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
