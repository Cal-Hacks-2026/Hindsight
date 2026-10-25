// Home: this week's moves (next course, a missing GE area, the next transfer milestone,
// opportunities that fit the student's free time), the path at a glance, and this week's classes.
// Everything comes from the same endpoints as Plan, Credits, Schedule and Opportunities.
import { Fragment, useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router";
import type {
  GeResponse,
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
import { safeUrl } from "../components/Listing";
import { Masthead, Section } from "../components/Paper";
import { api } from "../lib/api";
import { watched as readsAFeed } from "../lib/campuses";
import { catalogMajor, hasFullPlan, yearSpan } from "../lib/catalog";
import {
  collapse,
  shortMajor,
  shortUniversity,
  universityName,
} from "../lib/format";
import { loadGePattern, useGe, type GeState } from "../lib/ge";
import { nextMilestone } from "../lib/milestones";
import { fitFor, nextSevenDays, useFreeWeek, type FreeWeek } from "../lib/fits";
import { useOpportunities } from "../lib/opportunities";
import {
  beforeTransfer,
  lastTerm,
  loadTerm,
  transferChoices,
  usePlans,
  type PlansState,
} from "../lib/plans";
import { courseKey } from "../lib/schedule";
import { loadSession } from "../lib/session";
import { closeAt, formatWhen, useNow } from "../lib/time";
import { Landing } from "./Landing";
import "../styles/home.css";

const DAY = 24 * 60 * 60 * 1000;
const WEEK = 7 * DAY;
const ROOMS_SHOWN = 2;
const OPTIONS_SHOWN = 4;
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

// ---- This week's moves ----

type Kind = "Courses" | "Deadline" | "Rooms" | "Schedule";
type Move = {
  key: string;
  kind: Kind;
  title: string;
  why: ReactNode;
  refs: number[];
  action: { label: string; to?: string; href?: string };
  /** The GE area code a GE-slot course fills ("1A"), so the GE move picks another. */
  geArea?: string;
};

const areaCode = (geArea: string) => geArea.split(" ").at(-1) ?? geArea;

/** "Data Science, B.S." → "Data Science"; ASSIST's UC labels too: "Business Economics/B.A." → "Business Economics". */
const majorName = (label: string) =>
  shortMajor(label).replace(/\/\s*B\.[AS]\.?$/i, "");

/** The ASSIST agreement or catalog page behind a planned course, and what it counts toward. */
function courseWhy(
  c: SemesterCourse,
  matches: MatchResult[],
  profile: Profile,
  university: string,
  sources: Sources,
  ge: GeResponse | undefined,
): { text: string; refs: number[] } {
  if (c.ge_area && c.ge_options) {
    const area = ge?.areas.find((a) => a.code === areaCode(c.ge_area!));
    return {
      text: `Fills ${c.ge_area} (${c.title}). Take one of: ${collapse(c.ge_options, ", ", OPTIONS_SHOWN)}.`,
      refs: area ? sources.add(area.citation.url, area.citation.label) : [],
    };
  }
  // Community-college course: "For CS 46A - Introduction to Programming (Data Science, B.S.); ASSIST option: …"
  const cc = /^For (.+) \(([^()]+)\); ASSIST option:/.exec(c.reason);
  if (cc) {
    const [, receiving, major] = cc;
    const req = matches
      .flatMap((m) => m.requirements)
      .find((r) => r.receiving_course === receiving);
    const choose = receiving!.startsWith("Choose from:")
      ? receiving!
          .slice("Choose from:".length)
          .split(";")
          .map((s) => s.trim().split(" - ")[0]!)
      : undefined;
    const target = choose
      ? `one of ${university}'s ${collapse(choose, ", ", 3)}`
      : `${university}'s ${receiving!.replace(" - ", " ")}`;
    return {
      text: `Counts toward ${target} for ${majorName(major!)}.${c.ge_area ? ` Also fills ${c.ge_area}.` : ""}`,
      refs: req ? sources.add(req.citation.url, `ASSIST · ${req.citation.label}`) : [],
    };
  }
  // University course: "Major Requirements: Upper Division (Data Science, B.S.); Prerequisite for …"
  const group = /^(.+?) \(([^()]+)\)/.exec(c.reason.split(";")[0] ?? "");
  const major = group ? catalogMajor(group[2]!, profile.receiving_institution_id) : undefined;
  return {
    text: group
      ? `Counts toward ${majorName(group[2]!)} ${group[1]}.`
      : c.reason,
    refs: major
      ? sources.add(
          major.source_url,
          `${university} Catalog ${yearSpan(major.catalog_year)} · ${major.major_label}`,
        )
      : [],
  };
}

function courseMove(
  plans: PlansState,
  matches: MatchResult[],
  profile: Profile,
  university: string,
  sources: Sources,
  ge: GeResponse | undefined,
  scheduled: Set<string>,
): Move | undefined {
  if (plans.status !== "ready") return undefined;
  // Courses already on the saved schedule are registered for, so the next one to register for comes after.
  const open = (c: SemesterCourse) => !scheduled.has(courseKey(c.code));
  const next = plans.plans.combined.find((s) => s.courses.some(open));
  // A major course first: GE gets its own move.
  const course =
    next?.courses.find((c) => open(c) && !c.ge_options) ??
    next?.courses.find(open);
  if (!next || !course) return undefined;
  const why = courseWhy(course, matches, profile, university, sources, ge);
  return {
    key: `course-${course.code}`,
    kind: "Courses",
    title: course.ge_options
      ? `Pick a ${course.ge_area} Course for ${next.term}`
      : `Take ${course.code} in ${next.term}`,
    why: why.text,
    refs: why.refs,
    action: { label: "See your plan", to: "/plan" },
    geArea: course.ge_options && course.ge_area ? areaCode(course.ge_area) : undefined,
  };
}

/** The missing GE area the plan schedules first (or the first in the pattern), with its options. */
function geMove(
  state: GeState,
  plans: PlansState,
  skip: string | undefined,
  sources: Sources,
  schedule: ScheduledClass[],
): Move | undefined {
  if (state.status !== "ready") return undefined;
  const ge = state.ge;
  const planned = new Map<string, string>();
  if (plans.status === "ready")
    for (const s of plans.plans.combined)
      for (const c of s.courses)
        if (c.ge_area && c.ge_options && !planned.has(areaCode(c.ge_area)))
          planned.set(areaCode(c.ge_area), s.term);
  const order = [...planned.keys()];
  const rank = (code: string) =>
    order.includes(code) ? order.indexOf(code) : order.length;
  const area = ge.areas
    .filter((a) => a.required && a.status === "missing" && a.code !== skip)
    .map((a, i) => ({ a, i }))
    .sort((x, y) => rank(x.a.code) - rank(y.a.code) || x.i - y.i)[0]?.a;
  if (!area) return undefined;
  const options = (area.options ?? []).map((o) => o.code);
  const term = planned.get(area.code);
  // An option already on the saved schedule isn't on the confirmed transcript, so it isn't counted yet.
  const taking = schedule.find((r) =>
    options.some((o) => courseKey(o) === courseKey(r.course)),
  );
  const dash = (s: string) => s.replace(/[–-]/g, "-");
  const list = ge.citations.find(
    (c) => c.source === "assist" && dash(c.label).includes(dash(ge.options_year)),
  );
  return {
    key: `ge-${area.code}`,
    kind: "Courses",
    title: `${ge.pattern_name} Area ${area.code}: ${area.title}`,
    why: taking ? (
      <>
        {taking.course} is on your {taking.term} schedule and counts here, but
        it isn't on your confirmed courses yet, so this area still shows as
        needed.
      </>
    ) : (
      <>
        {area.still_needed > 1
          ? `${area.still_needed} courses still needed`
          : "Still needed"}
        {term ? `, planned for ${term}` : ""}.
        {options.length > 0 &&
          ` Take one of: ${collapse(options, ", ", OPTIONS_SHOWN)}.`}
      </>
    ),
    refs: [
      ...sources.add(area.citation.url, area.citation.label),
      ...(options.length && list ? sources.add(list.url, list.label) : []),
    ],
    action: { label: "See GE progress", to: "/credits#general-education" },
  };
}

function deadlineMove(
  university: string,
  universityId: number,
  transfer: string | undefined,
  today: string,
  sources: Sources,
): Move | undefined {
  const m = nextMilestone(university, universityId, transfer, today);
  if (!m) return undefined;
  return {
    key: m.id,
    kind: "Deadline",
    title: m.title,
    why: `${m.dates}. ${m.why}`,
    refs: sources.add(m.url, m.source),
    action: { label: m.action, href: m.url },
  };
}

/** Up to two listings that start or close in the next 7 days, best-ranked first; with a schedule, ones
 *  that fit the student's free time come first (Opportunities' Fits Your Week rule). */
function roomMoves(
  items: RankedOpportunity[],
  categories: OpportunityCategory[],
  free: FreeWeek,
  now: number,
  sources: Sources,
): Move[] {
  const label = new Map(
    categories.flatMap((c) => [
      [c.id, c.label] as const,
      ...c.subcategories.map((sub) => [`${c.id}/${sub.id}`, sub.label] as const),
    ]),
  );
  const kindOf = (item: RankedOpportunity) =>
    (item.category &&
      (label.get(`${item.category}/${item.subcategory}`) ?? label.get(item.category))) ||
    undefined;
  const picks = items.flatMap((item) => {
    const dates = [
      { iso: item.starts_at, verb: "Starts" },
      {
        iso: closeAt(item, now),
        verb: item.type === "hackathon" ? "Ends" : "Closes",
      },
    ]
      .map((d) => ({ ...d, at: Date.parse(d.iso ?? "") }))
      .filter((d) => d.at >= now && d.at - now <= WEEK)
      .sort((a, b) => a.at - b.at);
    const first = dates[0];
    if (!first) return [];
    const fit = free.status === "ready" ? fitFor(item, free.days, now) : undefined;
    return [{ item, first, fit }];
  });
  picks.sort(
    (a, b) =>
      Number(!!b.fit) - Number(!!a.fit) ||
      Number(b.item.notified) - Number(a.item.notified) ||
      b.item.score - a.item.score ||
      a.first.at - b.first.at,
  );
  // The same event can be listed twice (two sources); show it once.
  const seen = new Set<string>();
  const unique = picks.filter(({ item }) => {
    const key = item.title.toLowerCase();
    return !seen.has(key) && !!seen.add(key);
  });
  return unique.slice(0, ROOMS_SHOWN).map(({ item, first, fit }) => {
    const when = `${first.verb} ${formatWhen(first.iso!)}.`;
    const kind = kindOf(item);
    const link = safeUrl(item.url);
    return {
      key: `room-${item.id}`,
      kind: "Rooms",
      title: item.title,
      why: [kind && `${kind}.`, fit && `${fit}.`, when, !fit && item.reason]
        .filter(Boolean)
        .join(" "),
      refs: sources.add(
        item.url,
        [item.org, item.title].filter(Boolean).join(" · "),
      ),
      action: link
        ? { label: "Open the listing", href: link.href }
        : { label: "See opportunities", to: "/radar" },
    };
  });
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
  const majors = matches?.map((m) => m.major_label) ?? [];
  const fullPlan = hasFullPlan(profile.receiving_institution_id);
  const planned = fullPlan
    ? majors.filter((m) => catalogMajor(m, profile.receiving_institution_id))
    : majors;
  const [picks] = useState(() => {
    const transfer = loadTerm("transfer", profile.id);
    return {
      transfer:
        transfer && transferChoices().includes(transfer) ? transfer : undefined,
      start: loadTerm("start", profile.id),
    };
  });
  const plans = usePlans(profile.id, planned.length ? majors : [], picks);
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

  // Footnotes in reading order: moves first, then the path summary.
  const sources = new Sources();
  const geReady = ge.status === "ready" ? ge.ge : undefined;
  const moves: Move[] = [];
  if (!matches?.length)
    moves.push({
      key: "courses-setup",
      kind: "Courses",
      title: "Add Your Courses",
      why: "Upload a transcript, or continue with no courses, to see what to take next.",
      refs: [],
      action: { label: "Add your courses", to: "/onboarding" },
    });
  const course = matches?.length
    ? courseMove(
        plans,
        matches,
        profile,
        university,
        sources,
        geReady,
        new Set(rows.map((r) => courseKey(r.course))),
      )
    : undefined;
  if (course) moves.push(course);
  // Without confirmed courses (none is fine) there's nothing to measure GE against yet.
  const geNext = matches?.length
    ? geMove(ge, plans, course?.geArea, sources, rows)
    : undefined;
  if (geNext) moves.push(geNext);
  // The application milestone depends on the transfer term, so wait for the plan.
  const planSettled = planState.status !== "loading";
  const transfer =
    plans.status === "ready"
      ? plans.plans.response.transfer_term
      : picks.transfer;
  const deadline = planSettled
    ? deadlineMove(
        universityName(profile),
        profile.receiving_institution_id,
        transfer,
        pacificDay.format(new Date(now)),
        sources,
      )
    : undefined;
  if (deadline) moves.push(deadline);
  // With a saved schedule, wait for its free time so the order doesn't jump.
  const freeSettled = !rows.length || free.status !== "loading";
  const rooms =
    watched && opps.status === "ready" && schedule.status !== "loading" && freeSettled
      ? roomMoves(opps.items, opps.categories, free, now, sources)
      : [];
  moves.push(...rooms);
  if (schedule.status === "ready" && !rows.length)
    moves.push({
      key: "schedule",
      kind: "Schedule",
      title: "Add Your Class Schedule",
      why: "With your classes saved, Home shows your week and which opportunities fit your free time.",
      refs: [],
      action: { label: "Add your class schedule", to: "/schedule" },
    });

  const pending = [
    !!matches?.length && planState.status === "loading" && "your plan",
    !!matches?.length && ge.status === "loading" && "your GE progress",
    watched && opps.status === "loading" && "this week's opportunities",
  ].filter((x): x is string => !!x);

  return (
    <>
      <Masthead sketch="books" byline={longDay.format(today)}>
        Home
      </Masthead>
      <div className="home-grid">
        <div className="home-main">
          <Section label="This week" title="This Week">
            {moves.length > 0 && (
              <ol className="moves">
                {moves.map((m) => (
                  <MoveRow key={m.key} move={m} />
                ))}
              </ol>
            )}
            {pending.length > 0 ? (
              <div className="home-pending" role="status" aria-live="polite">
                <div className="loading-bar" aria-hidden="true" />
                <p>Loading {pending.join(", ")}.</p>
              </div>
            ) : (
              moves.length === 0 &&
              !!matches?.length && (
                <p className="lede">Nothing needs your attention this week.</p>
              )
            )}
            {watched &&
              opps.status === "ready" &&
              schedule.status !== "loading" &&
              freeSettled &&
              rooms.length === 0 && (
                <p className="plan-note">
                  No opportunities start or close in the next 7 days.{" "}
                  <Link to="/radar">See all opportunities</Link>
                </p>
              )}
            {rooms.length > 0 && rows.length > 0 && (
              <p className="plan-note">
                <Link to="/radar?fits=1">See everything that fits your week</Link>
              </p>
              )}
            {opps.status === "error" && (
              <p className="plan-note">
                Opportunities didn't load.{" "}
                <Link to="/radar">Try the Opportunities page</Link>
              </p>
            )}
            {planState.status === "error" && (
              <p className="plan-note">
                Your plan didn't load. <Link to="/plan">Open your plan</Link>
              </p>
            )}
          </Section>
        </div>
        <div className="home-side">
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
          <YourWeek state={schedule} term={term} today={today} now={now} />
        </div>
      </div>
      {sources.list.length > 0 && (
        <Section id="sources" label="Sources" title="Sources" last>
          <div className="source-list">
            {sources.list.map((s) => (
              <p key={s.n} id={`source-${s.n}`}>
                <strong>{s.n}.</strong>{" "}
                <a href={s.url} target="_blank" rel="noreferrer">
                  {s.text}
                </a>
              </p>
            ))}
          </div>
        </Section>
      )}
    </>
  );
}

function MoveRow({ move }: { move: Move }) {
  const { kind, title, why, refs, action } = move;
  return (
    <li className="move">
      <span className="move-kind">{kind}</span>
      <h3 className="move-title">{title}</h3>
      <p className="move-why">
        {why}
        <Refs ns={refs} />
      </p>
      {action.href ? (
        <a
          className="inline-link"
          href={action.href}
          target="_blank"
          rel="noreferrer"
        >
          {action.label} <Icon name="arrow" size={20} />
        </a>
      ) : (
        <Link className="inline-link" to={action.to!}>
          {action.label} <Icon name="arrow" size={20} />
        </Link>
      )}
    </li>
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
        See your plan <Icon name="arrow" size={20} />
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
          {state.status === "error" ? "Open your schedule" : "Add your class schedule"}{" "}
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
        Open your schedule <Icon name="arrow" size={20} />
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

