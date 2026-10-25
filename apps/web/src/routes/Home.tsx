// Home, in order: the path at a glance, next term's courses, what's dated in the next 7 days (listings
// and transfer deadlines, as Opportunities' compact cards), deadlines further out, and this week's
// classes. Everything comes from the same endpoints as Plan, Credits, Schedule and Opportunities.
import { Fragment, useEffect, useState } from "react";
import { Link } from "react-router";
import type {
  MatchResult,
  OpportunityCategory,
  Profile,
  RankedOpportunity,
  ScheduledClass,
  ScheduleTerm,
  SemesterCourse,
  Weekday,
} from "@hindsight/contracts";
import { Icon } from "../components/Icons";
import { hostOf, Listing, safeUrl } from "../components/Listing";
import { Masthead, Section, SourceList } from "../components/Paper";
import { api } from "../lib/api";
import { campusLabel, watched as readsAFeed } from "../lib/campuses";
import { catalogMajor, yearSpan } from "../lib/catalog";
import {
  plural,
  shortUniversity,
  universityName,
  withPeriod,
} from "../lib/format";
import { loadGePattern, useGe, type GeState } from "../lib/ge";
import { upcomingMilestones, type Milestone } from "../lib/milestones";
import { fitFor, nextSevenDays, useFreeWeek, type FreeWeek } from "../lib/fits";
import { useOpportunities } from "../lib/opportunities";
import {
  beforeTransfer,
  lastTerm,
  loadPicks,
  planMajors,
  usePlans,
  type PlansState,
} from "../lib/plans";
import { courseKey } from "../lib/schedule";
import { loadSession } from "../lib/session";
import { closeAt, useNow } from "../lib/time";
import { Landing } from "./Landing";
import "../styles/opportunities.css";
import "../styles/home.css";

const DAY = 24 * 60 * 60 * 1000;
const WEEK = 7 * DAY;
const LISTINGS_SHOWN = 4;
// Phones show fewer (home.css); the link to Opportunities has the rest.
const LISTINGS_SHOWN_NARROW = 2;
const NEXT_CLASSES = 3;

const DAYS: Weekday[] = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const DAY_NAME: Record<Weekday, string> = {
  Mon: "Monday",
  Tue: "Tuesday",
  Wed: "Wednesday",
  Thu: "Thursday",
  Fri: "Friday",
  Sat: "Saturday",
  Sun: "Sunday",
};

// ---- Sources: every claim gets a numbered footnote, as on Plan ----

type Source = { n: number; text: string; url: string };

class Sources {
  readonly list: Source[] = [];
  add(url: string | undefined, text: string): number[] {
    const link = url && safeUrl(url);
    if (!link) return [];
    const found = this.list.find((s) => s.url === link.href);
    if (found) return [found.n];
    const n = this.list.length + 1;
    this.list.push({ n, text, url: link.href });
    return [n];
  }
}

function Refs({ ns }: { ns: number[] }) {
  const sorted = [...new Set(ns)].sort((a, b) => a - b);
  if (!sorted.length) return null;
  return (
    <sup className="ref">
      {sorted.map((n, i) => (
        <Fragment key={n}>
          {i > 0 && ","}
          <a href={`#source-${n}`} aria-label={`Source ${n}`}>
            {n}
          </a>
        </Fragment>
      ))}
    </sup>
  );
}

// ---- Dates and times ----

const PACIFIC = "America/Los_Angeles";
const pacificDay = new Intl.DateTimeFormat("en-CA", {
  timeZone: PACIFIC,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});
const longDay = new Intl.DateTimeFormat("en-US", {
  weekday: "long",
  month: "long",
  day: "numeric",
});

/** Local calendar date, "YYYY-MM-DD" (schedules are in the college's own time, like the Schedule page). */
const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const addDays = (d: Date, n: number) =>
  new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
const weekdayOf = (d: Date) => DAYS[(d.getDay() + 6) % 7]!;
const minutes = (hhmm: string) => {
  const [h, m] = hhmm.split(":").map(Number);
  return h! * 60 + m!;
};

/** "14:00" → "2", "15:20" → "3:20"; with the period: "2 PM". */
function clock(hhmm: string, meridiem = true): string {
  const m = minutes(hhmm);
  const h = Math.floor(m / 60) % 24;
  const text = `${h % 12 || 12}${m % 60 ? `:${String(m % 60).padStart(2, "0")}` : ""}`;
  return meridiem ? `${text} ${h < 12 ? "AM" : "PM"}` : text;
}
/** "2–5 PM", "11 AM–1:20 PM" */
function span(start: string, end: string): string {
  const same = minutes(start) < 720 === minutes(end) < 720;
  return `${clock(start, !same)}–${clock(end)}`;
}

const meets = (c: ScheduledClass, day: Date) =>
  c.mode !== "asynchronous" &&
  !!c.start_time &&
  !!c.end_time &&
  c.days.includes(weekdayOf(day)) &&
  (!c.start_date || iso(day) >= c.start_date) &&
  (!c.end_date || iso(day) <= c.end_date);

/** The term that's running today, else the next to start, else the latest (as on Schedule). */
function currentTerm(
  rows: ScheduledClass[],
  terms: ScheduleTerm[],
  today: string,
): string | undefined {
  const dated = (t: string) =>
    rows.filter((r) => r.term === t && r.start_date && r.end_date);
  const running = terms.find((t) =>
    dated(t.term).some((r) => r.start_date! <= today && today <= r.end_date!),
  );
  if (running) return running.term;
  const next = terms.find((t) =>
    dated(t.term).some((r) => r.start_date! > today),
  );
  return next?.term ?? terms.at(-1)?.term;
}

// ---- Data ----

type ScheduleState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; rows: ScheduledClass[]; terms: ScheduleTerm[] };

function useSavedSchedule(profileId: string): ScheduleState {
  const [state, setState] = useState<ScheduleState>({ status: "loading" });
  useEffect(() => {
    let live = true;
    api.schedule(profileId).then(
      (res) =>
        live &&
        setState({
          status: "ready",
          rows: res.rows,
          terms: res.terms ?? [],
        }),
      () => live && setState({ status: "error" }),
    );
    return () => {
      live = false;
    };
  }, [profileId]);
  return state;
}

// ---- Next term: what the plan has the student register for next ----

type NextTerm = { term: string; courses: string[]; geSlots: number };

/** The first planned term with a course not already on the saved schedule (those are registered for). */
function nextTerm(plans: PlansState, scheduled: Set<string>): NextTerm | undefined {
  if (plans.status !== "ready") return undefined;
  const open = (c: SemesterCourse) => !scheduled.has(courseKey(c.code));
  const s = plans.plans.combined.find((s) => s.courses.some(open));
  if (!s) return undefined;
  const left = s.courses.filter(open);
  return {
    term: s.term,
    courses: left.filter((c) => !c.ge_options).map((c) => c.code),
    geSlots: left.filter((c) => c.ge_options).length,
  };
}

/** "CIS 22C, CIS 40 + 1 GE slot" */
function termLine({ courses, geSlots }: NextTerm): string {
  const ge = geSlots ? `${geSlots} GE ${plural(geSlots, "slot")}` : "";
  return courses.length ? [courses.join(", "), ge].filter(Boolean).join(" + ") : ge;
}

// ---- This week: only what's dated in the next 7 days ----

type WeekPick = { item: RankedOpportunity; at: number; fit?: string };

/** Listings that start or close in the next 7 days, best-ranked first; with a schedule, ones that fit the
 *  student's free time come first (Opportunities' Fits Your Week rule). */
function weekListings(items: RankedOpportunity[], free: FreeWeek, now: number): WeekPick[] {
  const picks = items.flatMap((item) => {
    const at = [item.starts_at, closeAt(item, now)]
      .map((d) => Date.parse(d ?? ""))
      .filter((t) => t >= now && t - now <= WEEK)
      .sort((a, b) => a - b)[0];
    if (at === undefined) return [];
    const fit = free.status === "ready" ? fitFor(item, free.days, now) : undefined;
    return [{ item, at, fit }];
  });
  picks.sort(
    (a, b) =>
      Number(!!b.fit) - Number(!!a.fit) ||
      Number(b.item.notified) - Number(a.item.notified) ||
      b.item.score - a.item.score ||
      a.at - b.at,
  );
  // The same event can be listed twice (two sources); show it once.
  const seen = new Set<string>();
  return picks.filter(({ item }) => {
    const key = item.title.toLowerCase();
    return !seen.has(key) && !!seen.add(key);
  });
}

/** Opportunities' name for a listing's kind: its subcategory ("Workshops"), else its category. */
function kindLabels(categories: OpportunityCategory[]) {
  const label = new Map(
    categories.flatMap((c) => [
      [c.id, c.label] as const,
      ...c.subcategories.map((sub) => [`${c.id}/${sub.id}`, sub.label] as const),
    ]),
  );
  return (item: RankedOpportunity) =>
    (item.category &&
      (label.get(`${item.category}/${item.subcategory}`) ?? label.get(item.category))) ||
    undefined;
}

/** "YYYY-MM-DD" → "Mar 2", with the year when it isn't this one: "Mar 2, 2027". */
function dayLabel(day: string, today: string): string {
  const at = new Date(`${day}T12:00:00Z`);
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    ...(day.slice(0, 4) !== today.slice(0, 4) ? { year: "numeric" } : {}),
    timeZone: "UTC",
  }).format(at);
}

/** A milestone that opens or closes this week, as the same compact card as an opportunity. */
function MilestoneCard({ m, today }: { m: Milestone; today: string }) {
  const link = safeUrl(m.url);
  const opening = m.opens > today;
  return (
    <li className="opp-card">
      <h3 className="opp-title">
        {link ? (
          <a href={link.href} target="_blank" rel="noreferrer">
            {m.title}
          </a>
        ) : (
          m.title
        )}
      </h3>
      <p className="opp-when">
        {opening ? `Opens ${dayLabel(m.opens, today)}` : `Closes ${dayLabel(m.closes, today)}`}
      </p>
      <p className="opp-reason" title={m.why}>
        {withPeriod(m.why)}
      </p>
      <p className="opp-foot">
        Transfer Deadline · {m.source}
        {link && (
          <>
            {" · "}
            <a href={link.href} target="_blank" rel="noreferrer" aria-label={`Source: ${hostOf(link)}`}>
              {hostOf(link)} ↗
            </a>
          </>
        )}
      </p>
    </li>
  );
}

// ---- Page ----

export function Home() {
  const { profile, matches, courses } = loadSession();
  if (!profile) return <Landing />;
  return <HomePage profile={profile} matches={matches} courses={courses} />;
}

function HomePage({
  profile,
  matches,
  courses,
}: {
  profile: Profile;
  matches?: MatchResult[];
  courses?: ReturnType<typeof loadSession>["courses"];
}) {
  const now = useNow(60_000);
  const today = new Date(now);
  const todayIso = iso(today);
  const university = shortUniversity(universityName(profile), profile.receiving_institution_id);

  // The same plan as the Plan page: chosen majors, picked terms, GE included.
  const { planned, fullPlan, query } = planMajors(profile, matches);
  const [picks] = useState(() => loadPicks(profile.id));
  const plans = usePlans(profile.id, query, picks);
  const planState: PlansState | { status: "none" } = planned.length
    ? plans
    : { status: "none" };
  const ge = useGe(profile.id, loadGePattern(profile.id), courses);
  const schedule = useSavedSchedule(profile.id);
  const rows = schedule.status === "ready" ? schedule.rows : [];
  const term =
    schedule.status === "ready"
      ? currentTerm(rows, schedule.terms, todayIso)
      : undefined;
  const watched = readsAFeed(profile);
  // The next 7 days only, as Opportunities' Fits Your Week asks for them (no wait on new reasons).
  const { state: opps } = useOpportunities(
    watched ? profile.id : undefined,
    nextSevenDays(now),
  );
  const free = useFreeWeek(
    watched ? profile.id : undefined,
    rows.length > 0,
    now,
  );

  const sources = new Sources();
  const next =
    planState.status === "ready"
      ? nextTerm(planState, new Set(rows.map((r) => courseKey(r.course))))
      : undefined;

  // Milestones depend on the transfer term, so wait for the plan. This week: opening or closing in the
  // next 7 days; the rest are Coming Up.
  const transfer =
    plans.status === "ready" ? plans.plans.response.transfer_term : picks.transfer;
  const pacificToday = pacificDay.format(today);
  const weekEnd = pacificDay.format(new Date(now + WEEK));
  const thisWeek = (m: Milestone) =>
    m.closes <= weekEnd || (m.opens > pacificToday && m.opens <= weekEnd);
  const milestones =
    planState.status !== "loading"
      ? upcomingMilestones(
          universityName(profile),
          profile.receiving_institution_id,
          transfer,
          pacificToday,
        )
      : undefined;
  const dueThisWeek = milestones?.filter(thisWeek) ?? [];
  const comingUp = milestones?.filter((m) => !thisWeek(m)) ?? [];

  // With a saved schedule, wait for its free time so the order doesn't jump.
  const freeSettled = !rows.length || free.status !== "loading";
  const listingsReady =
    watched && opps.status === "ready" && schedule.status !== "loading" && freeSettled;
  const listings = listingsReady ? weekListings(opps.items, free, now) : [];
  const kindOf = kindLabels(opps.status === "ready" ? opps.categories : []);
  const weekPending = !milestones || (watched && opps.status !== "error" && !listingsReady);
  const weekCount = dueThisWeek.length + listings.length;

  return (
    <>
      <Masthead sketch="books" byline={longDay.format(today)}>
        Home
      </Masthead>
      <div className="home-grid">
        <PathSummary
          matches={matches}
          plans={planState}
          ge={ge}
          fullPlan={fullPlan}
          university={university}
          catalogRefs={planned.flatMap((label) => {
            const c = catalogMajor(label, profile.receiving_institution_id);
            return c
              ? sources.add(
                  c.source_url,
                  `${university} Catalog ${yearSpan(c.catalog_year)} · ${c.major_label}`,
                )
              : [];
          })}
        />
        <Section label="Plan" title="Next Term">
          {!matches?.length ? (
            <>
              <p className="home-empty">Add your courses to see what to take next term.</p>
              <Link className="inline-link" to="/onboarding">
                Add Your Courses <Icon name="arrow" size={20} />
              </Link>
            </>
          ) : planState.status === "loading" ? (
            <div role="status" aria-live="polite">
              <div className="loading-bar" aria-hidden="true" />
              <p className="sr-only">Loading your plan.</p>
            </div>
          ) : (
            <>
              {next ? (
                <p className="home-next">
                  <strong>{next.term}:</strong> {termLine(next)}
                </p>
              ) : (
                <p className="home-empty">
                  {planState.status === "error"
                    ? "Your plan didn't load."
                    : planState.status === "none"
                      ? `None of your majors has a full plan at ${university} yet.`
                      : "Nothing left to plan before transfer."}
                </p>
              )}
              <Link className="inline-link" to="/plan">
                See Your Plan <Icon name="arrow" size={20} />
              </Link>
            </>
          )}
        </Section>
        <Section label="This week" title="This Week" id="this-week">
          {weekCount > 0 && (
            <ol className="opp-cards">
              {dueThisWeek.map((m) => (
                <MilestoneCard key={m.id} m={m} today={pacificToday} />
              ))}
              {listings.slice(0, LISTINGS_SHOWN).map(({ item, fit }) => (
                <Listing
                  key={item.id}
                  item={item}
                  now={now}
                  kind={kindOf(item)}
                  fit={fit}
                  campus={campusLabel(item.campus_id, profile)}
                />
              ))}
            </ol>
          )}
          {weekPending ? (
            <div className="home-pending" role="status" aria-live="polite">
              <div className="loading-bar" aria-hidden="true" />
              <p>Loading this week.</p>
            </div>
          ) : (
            weekCount === 0 && (
              <p className="home-empty">Nothing is dated in the next 7 days.</p>
            )
          )}
          {opps.status === "error" ? (
            <p className="plan-note">
              Opportunities didn't load. <Link to="/radar">Try the Opportunities page</Link>
            </p>
          ) : (
            watched &&
            listingsReady && (
              <p className="plan-note">
                {rows.length > 0 ? (
                  <Link to="/radar?fits=1">See everything that fits your week</Link>
                ) : listings.length > LISTINGS_SHOWN_NARROW ? (
                  <Link to="/radar?week=1">
                    See all {listings.length} this week on Opportunities
                  </Link>
                ) : (
                  <Link to="/radar">See all opportunities</Link>
                )}
              </p>
            )
          )}
        </Section>
        <Section label="Heads up" title="Coming Up">
          {!milestones ? (
            <div role="status" aria-live="polite">
              <div className="loading-bar" aria-hidden="true" />
              <p className="sr-only">Loading deadlines.</p>
            </div>
          ) : comingUp.length ? (
            <ul className="home-coming">
              {comingUp.map((m) => {
                const link = safeUrl(m.url);
                return (
                  <li key={m.id}>
                    <span className="home-coming-date">
                      {m.opens > pacificToday
                        ? `Opens ${dayLabel(m.opens, pacificToday)}`
                        : dayLabel(m.closes, pacificToday)}
                    </span>
                    {link ? (
                      <a href={link.href} target="_blank" rel="noreferrer">
                        {m.title}
                      </a>
                    ) : (
                      <span>{m.title}</span>
                    )}
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="home-empty">No other deadlines ahead.</p>
          )}
        </Section>
        <YourWeek state={schedule} term={term} today={today} now={now} />
      </div>
      {sources.list.length > 0 && (
        <SourceList count={sources.list.length}>
          {sources.list.map((s) => (
            <p key={s.n} id={`source-${s.n}`}>
              <strong>{s.n}.</strong>{" "}
              <a href={s.url} target="_blank" rel="noreferrer">
                {s.text}
              </a>
            </p>
          ))}
        </SourceList>
      )}
    </>
  );
}

// ---- Right column ----

function PathSummary({
  matches,
  plans,
  ge,
  fullPlan,
  university,
  catalogRefs,
}: {
  matches?: MatchResult[];
  plans: PlansState | { status: "none" };
  ge: GeState;
  fullPlan: boolean;
  university: string;
  catalogRefs: number[];
}) {
  if (!matches?.length)
    return (
      <Section label="Summary" title="Your Path">
        <p className="home-empty">Add your courses to see your path.</p>
      </Section>
    );
  // One row per university requirement, across majors (a shared course counts once).
  const reqs = new Map<string, boolean>();
  for (const m of matches)
    for (const r of m.requirements)
      reqs.set(
        r.receiving_course,
        (reqs.get(r.receiving_course) ?? false) || r.status === "satisfied",
      );
  const met = [...reqs.values()].filter(Boolean).length;
  const ready = plans.status === "ready" ? plans.plans : undefined;
  const before = ready ? beforeTransfer(ready.combined) : undefined;
  const geSummary = ge.status === "ready" ? ge.ge.summary : undefined;
  const geTotal = geSummary
    ? geSummary.done + geSummary.in_progress + geSummary.missing
    : 0;
  return (
    <Section label="Summary" title="Your Path">
      <dl className="home-path">
        <div>
          <dt>Requirements met</dt>
          <dd>
            {met} of {reqs.size}
          </dd>
        </div>
        <div>
          <dt>
            {ge.status === "ready" ? `${ge.ge.pattern_name} areas done` : "GE areas done"}
          </dt>
          <dd>
            {geSummary ? `${geSummary.done} of ${geTotal}` : ge.status === "error" ? "—" : "…"}
          </dd>
        </div>
        <div>
          <dt>Terms before transfer</dt>
          <dd>{before ? before.length : plans.status === "loading" ? "…" : "—"}</dd>
        </div>
        <div>
          <dt>Transfer term</dt>
          <dd>{ready?.response.transfer_term ?? (plans.status === "loading" ? "…" : "—")}</dd>
        </div>
        {fullPlan && (
          <div>
            <dt>
              Estimated finish
              <Refs ns={catalogRefs} />
            </dt>
            <dd>{ready ? (lastTerm(ready.combined) ?? "—") : plans.status === "loading" ? "…" : "—"}</dd>
          </div>
        )}
      </dl>
      {!fullPlan && (
        <p className="plan-note">
          Courses after transfer aren't planned for {university} yet.
        </p>
      )}
      {plans.status === "none" && (
        <p className="plan-note">
          None of your majors has a full plan at {university} yet.
        </p>
      )}
      <Link className="inline-link" to="/plan">
        See Your Plan <Icon name="arrow" size={20} />
      </Link>
    </Section>
  );
}

type Meeting = { cls: ScheduledClass; day: Date };

function YourWeek({
  state,
  term,
  today,
  now,
}: {
  state: ScheduleState;
  term: string | undefined;
  today: Date;
  now: number;
}) {
  if (state.status === "loading")
    return (
      <Section label="Your week" title="Your Week">
        <div role="status" aria-live="polite">
          <div className="loading-bar" aria-hidden="true" />
          <p className="sr-only">Loading your schedule.</p>
        </div>
      </Section>
    );
  if (state.status === "error" || !state.rows.length)
    return (
      <Section label="Your week" title="Your Week">
        <p className="home-empty">
          {state.status === "error"
            ? "Your schedule didn't load."
            : "No class schedule yet."}
        </p>
        <Link className="inline-link" to="/schedule">
          {state.status === "error" ? "Open Your Schedule" : "Add Your Class Schedule"}{" "}
          <Icon name="arrow" size={20} />
        </Link>
      </Section>
    );

  const classes = state.rows.filter((r) => r.term === term);
  const at = (m: Meeting) => {
    const [h, min] = m.cls.start_time!.split(":").map(Number);
    return new Date(m.day.getFullYear(), m.day.getMonth(), m.day.getDate(), h, min).getTime();
  };
  const byStart = (a: Meeting, b: Meeting) => at(a) - at(b);
  const todays = classes
    .filter((c) => meets(c, today))
    .map((cls) => ({ cls, day: today }))
    .sort(byStart);
  const upcoming: Meeting[] = [];
  for (let i = 1; i <= 7 && upcoming.length < NEXT_CLASSES; i++) {
    const day = addDays(today, i);
    upcoming.push(
      ...classes
        .filter((c) => meets(c, day))
        .map((cls) => ({ cls, day }))
        .sort(byStart),
    );
  }
  const later = todays.filter((m) => at(m) > now);
  const next = [...later, ...upcoming].slice(0, NEXT_CLASSES);
  const unscheduled = classes.filter(
    (c) => c.mode === "asynchronous" || !c.start_time,
  );

  return (
    <Section label="Your week" title="Your Week">
      <h3 className="home-day">Today</h3>
      {todays.length ? (
        <ul className="home-classes">
          {todays.map((m) => (
            <ClassRow key={`${m.cls.course}-${m.cls.start_time}`} m={m} />
          ))}
        </ul>
      ) : (
        <p className="home-empty">No classes today.</p>
      )}
      <h3 className="home-day">Next</h3>
      {next.length ? (
        <ul className="home-classes">
          {next.map((m) => (
            <ClassRow
              key={`${iso(m.day)}-${m.cls.course}-${m.cls.start_time}`}
              m={m}
              withDay={iso(m.day) !== iso(today)}
            />
          ))}
        </ul>
      ) : (
        <p className="home-empty">
          No more classes in the next 7 days{term ? ` for ${term}` : ""}.
        </p>
      )}
      {unscheduled.length > 0 && (
        <p className="plan-note">
          No set meeting time:{" "}
          {unscheduled.map((c) => c.course).join(", ")}.
        </p>
      )}
      <Link className="inline-link" to="/schedule">
        Open Your Schedule <Icon name="arrow" size={20} />
      </Link>
    </Section>
  );
}

function ClassRow({ m, withDay }: { m: Meeting; withDay?: boolean }) {
  const { cls } = m;
  const where = cls.mode === "online" ? "Online" : cls.location;
  return (
    <li>
      <span className="home-class-time">
        {withDay && `${DAY_NAME[weekdayOf(m.day)].slice(0, 3)} `}
        {span(cls.start_time!, cls.end_time!)}
      </span>
      <span>
        <strong>{cls.course}</strong>
        {cls.title && ` ${cls.title}`}
        {where && <span className="home-class-meta"> · {where}</span>}
      </span>
    </li>
  );
}

