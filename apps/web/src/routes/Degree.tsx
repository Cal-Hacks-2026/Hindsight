import { Fragment, useEffect, useState, type ReactNode } from "react";
import { Link, useLocation, useSearchParams } from "react-router";
import type {
  Course,
  MatchResult,
  Profile,
  Requirement,
} from "@hindsight/contracts";
import {
  Masthead,
  Note,
  Section,
  SourceList,
  StatusMark,
  type StatusTone,
} from "../components/Paper";
import {
  GeAreaCards,
  GeNotes,
  useGeProgress,
} from "../components/GeProgress";
import { Icon } from "../components/Icons";
import {
  PlanMethodNotes,
  PlanTables,
  PlanTablesLoading,
  type PlanContext,
} from "../components/PlanTables";
import { ApiError } from "../lib/api";
import { catalogMajor, yearSpan } from "../lib/catalog";
import {
  collapse,
  collegeName,
  countWord,
  listing,
  majorsLine,
  plural,
  shortCollege,
  shortMajor,
  shortUniversity,
  universityName,
} from "../lib/format";
import { parseGoalTerm, termIndex } from "../lib/goal";
import {
  beforeTransfer,
  lastTerm,
  loadPicks,
  planMajors,
  saveTerm,
  usePlans,
  type Plans,
  type TermPicks,
} from "../lib/plans";
import { loadSession } from "../lib/session";
import { parseReceiving, type ParsedCourse } from "../lib/shelf";
import "../styles/ge.css";

const PLACEHOLDER_PREFIX = "PLACEHOLDER · ";

// Human copy for gotcha flags; unknown flags fall through as-is.
const FLAG_NOTE: Record<
  string,
  { lead: (codes: string) => string; body: string }
> = {
  course_year_mismatch: {
    lead: (c) => `Check the term for ${c}.`,
    body: "ASSIST lists the course for a different range of terms than the one on your transcript. It still matches, but confirm the term with your advisor.",
  },
  sequence_rule: {
    lead: (c) => `Why ${c} ${c.includes(" and ") ? "are" : "is"} partial.`,
    body: "ASSIST wants the whole sequence finished at one college before transfer. A partly finished sequence earns nothing yet.",
  },
  unspecified_rule: {
    lead: (c) => `${c}.`,
    body: "ASSIST doesn't say how many courses to choose, so this match is low confidence.",
  },
  renumbered_match: {
    lead: (c) => `${c}.`,
    body: "Matched by title and units because the course was renumbered. Low confidence; confirm with your advisor.",
  },
  pass_no_pass: {
    lead: (c) => `${c}.`,
    body: "Taken pass/no pass. Check whether your destination requires a letter grade.",
  },
  no_current_articulation: {
    lead: (c) => `${c}.`,
    body: "No course equivalency is published for this requirement. Ask the destination school for an evaluation.",
  },
};
const QUIET_FLAGS =
  /^(min_grade_|below_min_grade$|n_units$|sequence_grouping_inferred$|denied_course$)/;

// ---- Sources: every claim gets a numbered sidenote ----

type Source = { n: number; text: string; short: string; url: string };

class Sources {
  readonly list: Source[] = [];
  add(url: string, text: string, short: string): number {
    const found = this.list.find((s) => s.url === url);
    if (found) return found.n;
    const n = this.list.length + 1;
    this.list.push({ n, text, short, url });
    return n;
  }
}

// "<College> → <University> · Data Science, B.S. (2026–2027)"
const AGREEMENT_RE = /^(.+?) → (.+?) · (.+) \((\d{4})[–-](\d{4})\)$/;

/** `college`: the sending college's short name ("<Name> College" → "<Name>"); `from`/`to`: full names. */
type Agreement = {
  start: number;
  span: string;
  text: string;
  short: string;
  college: string;
  from: string;
  to: string;
};

function agreementOf(label: string): Agreement | undefined {
  const m = AGREEMENT_RE.exec(label);
  if (!m) return undefined;
  const [, from, to, major, start, end] = m;
  const span = `${start}–${end!.slice(2)}`;
  return {
    start: Number(start),
    span,
    text: `ASSIST · ${shortCollege(from!)} → ${shortUniversity(to!)} · ${major} · ${span} agreement`,
    short: `ASSIST ${span}`,
    college: shortCollege(from!),
    from: from!,
    to: to!,
  };
}

// ---- Requirements, merged across majors ----

type Row = {
  key: string;
  req: Requirement;
  parsed: ParsedCourse;
  majors: string[];
  refs: number[];
  /** Credited under an older agreement than the major's current one. */
  older?: string;
  units?: number;
};

const STATUS_ORDER: Requirement["status"][] = [
  "satisfied",
  "in_progress",
  "partial",
  "missing",
  "at_university",
];

function buildRows(
  matches: MatchResult[],
  courses: Course[] | undefined,
  sources: Sources,
): Row[] {
  const rows = new Map<string, Row>();
  for (const m of matches) {
    const years = m.requirements.map(
      (r) => agreementOf(r.citation.label)?.start ?? 0,
    );
    const current = Math.max(0, ...years);
    for (const req of m.requirements) {
      const ag = agreementOf(req.citation.label);
      const n = sources.add(
        req.citation.url,
        ag?.text ?? req.citation.label,
        ag?.short ?? "ASSIST",
      );
      const key = [
        req.receiving_course,
        req.status,
        req.satisfied_by.join("+"),
      ].join("|");
      let row = rows.get(key);
      if (!row) {
        const units = req.satisfied_by.reduce(
          (sum, code) => sum + (findCourse(courses, code)?.units ?? 0),
          0,
        );
        row = {
          key,
          req,
          parsed: parseReceiving(req.receiving_course),
          majors: [],
          refs: [],
          units: units || undefined,
        };
        rows.set(key, row);
      }
      if (!row.majors.includes(m.major_label)) row.majors.push(m.major_label);
      if (!row.refs.includes(n)) row.refs.push(n);
      if (req.status === "satisfied" && ag && ag.start < current)
        row.older = ag.span;
    }
  }
  return [...rows.values()].sort(
    (a, b) =>
      STATUS_ORDER.indexOf(a.req.status) - STATUS_ORDER.indexOf(b.req.status),
  );
}

function findCourse(
  courses: Course[] | undefined,
  code: string,
): Course | undefined {
  const norm = (s: string) => s.replace(/\s+/g, " ").trim().toUpperCase();
  return courses?.find((c) => norm(`${c.prefix} ${c.number}`) === norm(code));
}

function tone(req: Requirement): { tone: StatusTone; label: string } {
  switch (req.status) {
    case "satisfied":
      return req.confidence === "high"
        ? { tone: "ok", label: "Requirement met" }
        : { tone: "check", label: "Match needs review" };
    case "in_progress":
      return { tone: "check", label: "In progress" };
    case "partial":
      return { tone: "check", label: "Partly complete" };
    case "missing":
      return { tone: "missing", label: "Still needed" };
    case "at_university":
      return { tone: "neutral", label: "No published match" };
  }
}

const rowCode = (r: Row) => (r.parsed.choose ? "Elective" : r.parsed.code);

// ---- Page ----

export function Degree({ view = "plan" }: { view?: "plan" | "credits" }) {
  const location = useLocation();
  const session = loadSession();
  const matches: MatchResult[] | undefined =
    (location.state as { matches?: MatchResult[] } | null)?.matches ??
    session.matches;
  const profile = session.profile;

  if (!profile || !matches?.length)
    return <NoResults hasProfile={!!profile} view={view} />;
  return (
    <Report
      profile={profile}
      matches={matches}
      courses={session.courses}
      view={view}
    />
  );
}

function NoResults({
  hasProfile,
  view,
}: {
  hasProfile: boolean;
  view: "plan" | "credits";
}) {
  return (
    <>
      <Masthead sketch={view === "credits" ? "books" : "cap"}>
        {view === "credits" ? "Credits" : "Plan"}
      </Masthead>
      <Section label="Summary" last>
        <p className="lede">
          Add your transcript to see which credits count and what comes next.
        </p>
        <p className="actions" style={{ marginTop: 28 }}>
          <Link className="button primary" to="/onboarding">
            {hasProfile ? "Upload Your Transcript" : "Set Up Your Profile"}
          </Link>
        </p>
      </Section>
    </>
  );
}

function Report({
  profile,
  matches,
  courses,
  view,
}: {
  profile: Profile;
  matches: MatchResult[];
  courses?: Course[];
  view: "plan" | "credits";
}) {
  // With the university's requirements (a registry entry that lists them), the planner plans curated majors only; the rest get
  // the ASSIST rows and no plan. Without them (any other university), every major gets its
  // community-college terms and the after-transfer block says what's missing.
  const { majors, planned, fullPlan, query } = planMajors(profile, matches);
  const uncurated = majors.filter((m) => !planned.includes(m));
  // The student's start and transfer terms, if they picked them; otherwise the planner's defaults.
  // Credits reads the same plan for "planned Winter 2027".
  const [picks, setPicks] = useState<TermPicks>(() => loadPicks(profile.id));
  const plans = usePlans(profile.id, query, picks);
  function pick(which: keyof TermPicks, term: string | undefined) {
    saveTerm(which, profile.id, term);
    setPicks((p) => ({ ...p, [which]: term }));
  }
  // A saved start term that has since passed is rejected (422): fall back to the default.
  const staleStart =
    plans.status === "error" &&
    plans.error instanceof ApiError &&
    plans.error.status === 422 &&
    !!picks.start;
  useEffect(() => {
    if (staleStart) pick("start", undefined);
  });

  // Number the sources in reading order: agreements as the rows cite them, then the catalog.
  const sources = new Sources();
  const rows = buildRows(matches, courses, sources);
  // Names as the ASSIST agreement gives them, so a report never names another college.
  const agreement = matches
    .flatMap((m) => m.requirements.map((r) => agreementOf(r.citation.label)))
    .find(Boolean);
  const campusLong = agreement?.to ?? universityName(profile);
  const campus = shortUniversity(campusLong, profile.receiving_institution_id);
  const catalogRefByMajor: Record<string, number> = {};
  const catalogRefs = majors.flatMap((label) => {
    const c = catalogMajor(label, profile.receiving_institution_id);
    if (!c) return [];
    const n = sources.add(
      c.source_url,
      `${campus} Catalog ${yearSpan(c.catalog_year)} · ${label}${label.endsWith(".") ? "" : "."} Not yet checked against the current catalog.`,
      `Catalog ${yearSpan(c.catalog_year)}`,
    );
    catalogRefByMajor[label] = n;
    return [n];
  });

  const collegeLong = agreement?.from ?? collegeName(profile);
  const names: Names = {
    college:
      agreement?.college ??
      (profile.sending_institution_name
        ? shortCollege(collegeLong)
        : "your college"),
    collegeLong,
    campus,
    campusLong,
    universityId: profile.receiving_institution_id,
  };

  const ready = plans.status === "ready" ? plans.plans : undefined;
  const planContext: PlanContext = {
    plans: ready,
    rows: rows.map((r) => ({
      req: r.req,
      refs: r.refs,
      majors: r.majors,
      code: rowCode(r),
      agreement: agreementOf(r.req.citation.label)?.span,
    })),
    courses,
    names,
    majors: planned,
    catalogRefs: catalogRefByMajor,
    profileId: profile.id,
  };
  const citations = sources.list.length > 0 && (
    <SourceList count={sources.list.length}>
      {sources.list.map((source) => (
        <p key={source.n} id={`source-${source.n}`}>
          <strong>{source.n}.</strong>{" "}
          <a href={source.url} target="_blank" rel="noreferrer">
            {source.text}
          </a>
        </p>
      ))}
    </SourceList>
  );
  const loading = planned.length > 0 && plans.status === "loading";

  return (
    <>
      <Masthead
        byline={majorsLine(majors)}
        sketch={view === "credits" ? "books" : "cap"}
      >
        {view === "credits" ? "Credits" : "Plan"}
      </Masthead>
      {view === "credits" ? (
        <Credits
          rows={rows}
          courses={courses}
          majors={majors}
          campus={campus}
          plans={ready}
          profileId={profile.id}
        />
      ) : (
        <>
          {plans.status === "error" && (
            <Section label="Plan" title="Your Plan">
              <PlanError error={plans.error} />
            </Section>
          )}
          <Section
            id="course-plan"
            label="Plan"
            title={loading ? "Building Your Plan" : "Your Course Plan"}
          >
            {ready && (
              <PlanGlance
                plans={ready}
                names={names}
                fullPlan={fullPlan}
                catalogRefs={catalogRefs}
              />
            )}
            <NotPlanned majors={uncurated} campus={campus} />
            {loading && <PlanTablesLoading />}
            <PlanTables
              ctx={planContext}
              student={profile.name}
              picks={picks}
              onPick={pick}
              fullPlan={fullPlan}
              loading={loading}
            />
          </Section>
          <Attention rows={rows} />
          {/* Without the university's requirements there's no finish term to check a goal against. */}
          {fullPlan && ready && (
            <GoalCheck goals={profile.goals} majors={planned} plans={ready} />
          )}
          {ready && (
            <HowSection id="plan-how" title="How This Plan Was Built">
              <PlanNotes
                majors={planned}
                plans={ready}
                names={names}
                fullPlan={fullPlan}
              />
              <PlanMethodNotes ctx={planContext} fullPlan={fullPlan} />
            </HowSection>
          )}
        </>
      )}
      {citations}
    </>
  );
}

/** Institution names for copy, from the agreement: short and full, for the college and the university. */
type Names = {
  college: string;
  collegeLong: string;
  campus: string;
  campusLong: string;
  /** The profile's university (ASSIST id). */
  universityId: number;
};

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

/** Notes behind one closed row at the bottom of the page ("How This Plan Was Built"). Styled like
 *  Sources (N), and opened for printing with it. */
function HowSection({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section
      className="section sources how-section"
      id={id}
      aria-labelledby={`${id}-label`}
    >
      <details className="sources-details">
        <summary className="section-head">
          <Icon name="book" size={19} />
          <h2 id={`${id}-label`}>{title}</h2>
          <Icon name="chevron" size={20} />
        </summary>
        <div className="how-notes">{children}</div>
      </details>
    </section>
  );
}

// ---- Plan ----

/** The plan in one line: transfer term, estimated finish, terms left at the college. The only place
 *  these numbers appear on the Plan. */
function PlanGlance({
  plans,
  names,
  fullPlan,
  catalogRefs,
}: {
  plans: Plans;
  names: Names;
  fullPlan: boolean;
  catalogRefs: number[];
}) {
  const finish = lastTerm(plans.combined);
  const before = beforeTransfer(plans.combined).length;
  return (
    <dl className="plan-glance">
      {plans.response.transfer_term && (
        <div>
          <dt>Transfer to {names.campus}</dt>
          <dd>{plans.response.transfer_term}</dd>
        </div>
      )}
      {/* Without the university's requirements the last planned term is a community-college one, not a finish. */}
      {fullPlan && finish && (
        <div>
          <dt>
            Estimated finish
            <Refs ns={catalogRefs} />
          </dt>
          <dd>{finish}</dd>
        </div>
      )}
      {before > 0 && (
        <div>
          <dt>Terms at {names.college} before transfer</dt>
          <dd>{before}</dd>
        </div>
      )}
    </dl>
  );
}

const ATTENTION_SHOWN = 3;

function Attention({ rows }: { rows: Row[] }) {
  const review = rows.filter(
    ({ req }) =>
      req.status === "partial" ||
      // Doubt about a match matters only for a credit that counts.
      (req.status === "satisfied" &&
        (req.confidence !== "high" ||
          req.flags.some((flag) =>
            ["course_year_mismatch", "pass_no_pass"].includes(flag),
          ))),
  );
  if (!review.length) return null;
  return (
    <Section label="Heads up" title="Needs Attention">
      <ul className="plan-attention">
        {review.slice(0, ATTENTION_SHOWN).map((row) => (
          <li key={row.key}>
            <strong>{rowCode(row)}</strong>
            <p>
              {row.req.status === "partial"
                ? row.req.flags.includes("sequence_rule")
                  ? "Finish the sequence before it counts."
                  : "Finish the remaining courses before it counts."
                : "Check this match before relying on it."}
              <Refs ns={row.refs} />
            </p>
            <Link
              className="inline-link"
              to={`/counselor?${new URLSearchParams({ q: `What should I do next for ${row.req.receiving_course}?` })}`}
            >
              Get Next Steps <Icon name="arrow" size={20} />
            </Link>
          </li>
        ))}
      </ul>
      <Link className="inline-link" to="/credits">
        Review All Credits <Icon name="arrow" size={20} />
      </Link>
    </Section>
  );
}

// ---- Goal check ----

/** Goals are free text. Only a target term in them ("by Spring 2028") gets a card. */
function GoalCheck({
  goals,
  majors,
  plans,
}: {
  goals: string;
  majors: string[];
  plans: Plans;
}) {
  const goal = parseGoalTerm(goals);
  const finish = lastTerm(plans.combined);
  const finishAt = finish ? termIndex(finish) : undefined;
  if (!goal || !finish || finishAt === undefined) return null;

  if (finishAt <= goal.index) {
    return (
      <Section label="Your goal" title="Your Goal">
        <p className="goal ok">
          Your major plan finishes within your {goal.label} target.
        </p>
      </Section>
    );
  }

  const levers = majors.flatMap((m) => {
    const alone = plans.single[m] && lastTerm(plans.single[m]!);
    const at = alone ? termIndex(alone) : undefined;
    return alone && at !== undefined && at <= goal.index && majors.length > 1
      ? [`Doing ${shortMajor(m)} alone finishes ${alone}, in time.`]
      : [];
  });
  return (
    <Section label="Your goal" title="Your Goal">
      <p className="goal late">
        Your current major plan finishes after your {goal.label} goal.
      </p>
      <ul className="goal-levers">
        {levers.map((l) => (
          <li key={l}>{l}</li>
        ))}
        <li>
          A heavier term load or summer courses could close some of the gap. Ask
          your advisor what's allowed.
        </li>
      </ul>
    </Section>
  );
}

/** Why the transfer term is what it is, and anything the finish term leaves out. The terms
 *  themselves are in the summary row. */
function PlanNotes({
  majors,
  plans,
  names,
  fullPlan,
}: {
  majors: string[];
  plans: Plans;
  names: Names;
  fullPlan: boolean;
}) {
  const transfer = plans.response.transfer_term;
  const earliest = plans.response.earliest_transfer_term;
  const singles = majors.flatMap((m) =>
    plans.single[m]?.length ? [[m, lastTerm(plans.single[m]!)!] as const] : [],
  );
  const unscheduled = majors.flatMap((m) =>
    (catalogMajor(m, names.universityId)?.unscheduled ?? []).map(
      (g) => `${g.units} units of ${shortMajor(m)} ${g.title}`,
    ),
  );
  const placeholder = plans.combined.some((s) =>
    s.courses.some((c) => c.reason.startsWith(PLACEHOLDER_PREFIX)),
  );
  const it = unscheduled.length === 1 ? "it" : "them";
  return (
    <>
      {transfer && (
        <Note lead="Transfer.">
          {earliest === transfer
            ? `The first Fall after your ${names.college} courses. Pick another term at the top of the plan.`
            : `As you picked. The earliest that fits every ${names.college} course is ${earliest}.`}
        </Note>
      )}
      {fullPlan && singles.length > 0 && majors.length > 1 && (
        <Note lead="One major at a time.">
          {singles.map(([m, t]) => `${shortMajor(m)} alone finishes ${t}`).join("; ")}.
        </Note>
      )}
      {unscheduled.length > 0 && (
        <Note lead="Not yet scheduled.">
          {listing(unscheduled)}: the catalog lists no courses for {it}, so the
          planner can't place {it} and the finish term doesn't include {it}.
        </Note>
      )}
      {placeholder && (
        <Note lead="Sample data.">
          This major's requirements are placeholders until they're curated.
        </Note>
      )}
    </>
  );
}

function NotPlanned({ majors, campus }: { majors: string[]; campus: string }) {
  if (!majors.length) return null;
  return (
    <p className="lede">
      We don't have {campus}'s {listing(majors.map(shortMajor))} requirements
      yet, so lower-division only (from ASSIST).
    </p>
  );
}

function PlanError({ error }: { error: unknown }) {
  // The API's messages are written for students; anything else gets a generic line.
  const detail =
    error instanceof ApiError
      ? error.status === 404 || error.status === 422
        ? error.message
        : "The planner hit an unexpected error. Reload to try again."
      : "We couldn't reach the Hindsight server. Reload to try again.";
  return (
    <div className="state" role="alert">
      <h3>Couldn't Build a Plan</h3>
      <p>{detail}</p>
    </div>
  );
}

// ---- Credits ----

type CreditShow = "major" | "ge";
type CreditFilter = "todo" | "met" | "all";

const SHOW: [CreditShow, string][] = [
  ["major", "Major"],
  ["ge", "General Education"],
];
const FILTERS: [CreditFilter, string][] = [
  ["todo", "To Take"],
  ["met", "Met"],
  ["all", "All"],
];

const norm = (code: string) => code.replace(/\s+/g, " ").trim().toUpperCase();

/** The first planned term that takes a requirement: a college course chosen for it before
 *  transfer, or its university course after. */
function plannedTerm(row: Row, plans?: Plans): string | undefined {
  const { req, parsed } = row;
  for (const s of plans?.combined ?? []) {
    const hit = s.courses.some((c) =>
      s.phase === "before_transfer"
        ? c.reason.includes(`For ${req.receiving_course} (`)
        : !parsed.choose && norm(c.code) === norm(parsed.code),
    );
    if (hit) return s.term;
  }
  return undefined;
}

/** The first planned term with a course for a GE area ("3A"). */
function plannedGeTerm(code: string, plans?: Plans): string | undefined {
  return plans?.combined.find((s) =>
    s.courses.some((c) => c.ge_area?.split(" ").at(-1) === code),
  )?.term;
}

function Credits({
  rows,
  courses,
  majors,
  campus,
  plans,
  profileId,
}: {
  rows: Row[];
  courses?: Course[];
  majors: string[];
  campus: string;
  plans?: Plans;
  profileId: string;
}) {
  const [params, setParams] = useSearchParams();
  const show: CreditShow = params.get("show") === "ge" ? "ge" : "major";
  const filter: CreditFilter =
    (FILTERS.find(([v]) => v === params.get("status"))?.[0]) ?? "todo";
  function set(next: { show?: CreditShow; status?: CreditFilter }) {
    const p = new URLSearchParams(params);
    const s = next.show ?? show;
    const f = next.status ?? filter;
    if (s === "major") p.delete("show");
    else p.set("show", s);
    if (f === "todo") p.delete("status");
    else p.set("status", f);
    setParams(p, { replace: true, preventScrollReset: true });
  }
  const { ge, state: geState, choose } = useGeProgress(profileId, courses);
  // A GE slot on the Plan links to its area here: scroll to it once the areas load.
  const { hash } = useLocation();
  useEffect(() => {
    if (!ge || !hash.startsWith("#ge-area-")) return;
    document.getElementById(decodeURIComponent(hash.slice(1)))?.scrollIntoView();
  }, [ge, hash]);

  const met = rows.filter((r) => r.req.status === "satisfied");
  const missed = met.filter((r) => r.older);
  const geRequired = ge?.areas.filter((a) => a.required) ?? [];
  // The GE plan is only for the pattern shown here.
  const gePlans = plans?.response.ge_pattern === ge?.pattern ? plans : undefined;

  const card = (row: Row) => (
    <RequirementCard
      key={row.key}
      row={row}
      courses={courses}
      majors={majors}
      campus={campus}
      planned={plannedTerm(row, plans)}
    />
  );
  const open = rows.filter((r) => r.req.status !== "satisfied");
  return (
    <>
      <Section label="Credits" title="What Counts">
        <p className="credits-summary">
          <span>
            Major <strong>{met.length} of {rows.length}</strong>
          </span>
          {ge && (
            <span>
              GE <strong>{ge.summary.done} of {geRequired.length}</strong>
            </span>
          )}
          {missed.length > 0 && (
            <span>
              <strong>{missed.length}</strong>{" "}
              {plural(missed.length, "credit")} saved by when you took them
            </span>
          )}
        </p>
        {missed.length > 0 && <Missed rows={missed} />}
        <div className="opp-controls credits-controls">
          <div className="credit-filters" role="group" aria-label="Requirements">
            {SHOW.map(([value, label]) => (
              <button
                type="button"
                key={value}
                aria-pressed={show === value}
                onClick={() => set({ show: value })}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="credit-filters opp-subfilters" role="group" aria-label="Status">
            {FILTERS.map(([value, label]) => (
              <button
                type="button"
                key={value}
                aria-pressed={filter === value}
                onClick={() => set({ status: value })}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <div aria-live="polite">
          {show === "major" ? (
            <MajorCards rows={rows} open={open} met={met} filter={filter} card={card} />
          ) : ge ? (
            <GeAreaCards
              ge={ge}
              filter={filter}
              plannedFor={(code) => plannedGeTerm(code, gePlans)}
            />
          ) : geState.status === "error" ? (
            <p className="credits-empty">
              General education progress isn't available right now. Try again in
              a minute.
            </p>
          ) : (
            <div role="status">
              <span className="sr-only">Checking general education…</span>
              {[0, 1, 2].map((i) => (
                <span key={i} className="skeleton-line ge-skeleton" aria-hidden="true" />
              ))}
            </div>
          )}
        </div>
      </Section>
      <HowSection id="credits-how" title="How We Counted This">
        {ge && <GeNotes ge={ge} onChoose={choose} />}
        <CreditNotes rows={rows} />
      </HowSection>
    </>
  );
}

function MajorCards({
  rows,
  open,
  met,
  filter,
  card,
}: {
  rows: Row[];
  open: Row[];
  met: Row[];
  filter: CreditFilter;
  card: (row: Row) => ReactNode;
}) {
  const [showMet, setShowMet] = useState(false);
  if (!rows.length) return <p className="credits-empty">No requirements listed.</p>;
  if (filter === "met")
    return met.length ? (
      <ol className="credits-cards">{met.map(card)}</ol>
    ) : (
      <p className="credits-empty">Nothing met yet. Your courses show up here once they count.</p>
    );
  if (filter === "todo")
    return open.length ? (
      <ol className="credits-cards">{open.map(card)}</ol>
    ) : (
      <p className="credits-empty">Every major requirement is met.</p>
    );
  return (
    <>
      {met.length > 0 && (
        <div className="fold credits-fold">
          <button
            type="button"
            className="fold-toggle"
            aria-expanded={showMet}
            aria-controls="credits-met"
            onClick={() => setShowMet((o) => !o)}
          >
            <StatusMark tone="ok">Met</StatusMark>
            <span className="fold-meta">{collapse(met.map(rowCode), " · ", 4)}</span>
            <Icon name="chevron" size={20} />
          </button>
          <ol id="credits-met" className="credits-cards" hidden={!showMet}>
            {met.map(card)}
          </ol>
        </div>
      )}
      {open.length > 0 && <ol className="credits-cards">{open.map(card)}</ol>}
    </>
  );
}

/** "2 credits count because of when you took them: MATH 30, MATH 31 count under the 2023–24
 *  agreement, the year you took those courses." Each requirement links to its agreement. */
function Missed({ rows }: { rows: Row[] }) {
  const years = [...new Set(rows.map((r) => r.older!))];
  const one = rows.length === 1;
  return (
    <div className="credits-banner" role="note">
      <p>
        <strong>
          {rows.length} {plural(rows.length, "credit")}{" "}
          {one ? "counts because of when you took it" : "count because of when you took them"}:
        </strong>{" "}
        {years.map((year, i) => {
          const group = rows.filter((r) => r.older === year);
          return (
            <Fragment key={year}>
              {i > 0 && (i === years.length - 1 ? " and " : ", ")}
              {group.map((r, j) => (
                <Fragment key={r.key}>
                  {j > 0 && (j === group.length - 1 ? " and " : ", ")}
                  <a href={r.req.citation.url} target="_blank" rel="noreferrer">
                    {rowCode(r)}
                  </a>
                </Fragment>
              ))}
              {i === 0 ? (group.length === 1 ? " counts" : " count") : ""} under the{" "}
              <span className="nowrap">{year}</span> agreement
            </Fragment>
          );
        })}
        , the {years.length === 1 ? "year" : "years"} you took{" "}
        {one ? "that course" : "those courses"}.
      </p>
    </div>
  );
}

/** For a credit that counts with doubt, the question to take to an advisor. */
function advisorQuestion(row: Row): string | null {
  const { req, parsed } = row;
  if (req.status !== "satisfied" || req.confidence === "high") return null;
  const via = req.satisfied_by.join(" + ") || "my course";
  return `Ask your advisor: "Does ${via} satisfy ${parsed.code} for ${row.majors.map(shortMajor).join(" and ")}?"`;
}

/** ASSIST's "MAJOR ELECTIVES" → "Major Electives" */
const titleCase = (text: string) =>
  text
    .toLowerCase()
    .replace(/\b(?!(?:and|or|of|for|the|to|in)\b)[a-z]/g, (c) =>
      c.toUpperCase(),
    );

/** One requirement, the same lines on every card: title, status and plan, what to take, source. */
function RequirementCard({
  row,
  courses,
  majors,
  campus,
  planned,
}: {
  row: Row;
  courses?: Course[];
  majors: string[];
  campus: string;
  planned?: string;
}) {
  const { req, parsed } = row;
  const status = tone(req);
  const via = req.satisfied_by
    .map((code) => {
      const term = findCourse(courses, code)?.term;
      return term ? `${code}, ${term}` : code;
    })
    .join(" + ");
  const open = req.status !== "satisfied" && req.status !== "in_progress";
  const when = [via, open && planned && `planned ${planned}`].filter(Boolean);
  const takeAt = takeAtLead(req);
  const question = advisorQuestion(row);
  const ag = agreementOf(req.citation.label);
  const college = ag?.college ?? "your college";
  const evaluationQuestion = `There is no published course match for ${req.receiving_course}. What should I submit to request an evaluation?`;
  const title = parsed.choose
    ? titleCase(req.group_title)
    : [parsed.code, parsed.title].filter(Boolean).join(" · ");
  return (
    <li className="credits-card">
      <h3 className="credits-title">
        {campus} {title}
      </h3>
      <p className="credits-status">
        <StatusMark tone={status.tone}>{status.label}</StatusMark>
        {when.length > 0 && <span>{when.join(" · ")}</span>}
      </p>
      <p className="credits-what">
        {takeAt ? (
          <>
            <strong>{takeAt}</strong> {req.options!.map(keepCodes).join(" · ")}
          </>
        ) : req.status === "at_university" ? (
          `No published equivalent at ${college}. Request an evaluation to check whether prior coursework can apply.`
        ) : question ? (
          question
        ) : req.status === "missing" ? (
          "Not matched to your confirmed coursework."
        ) : row.older ? (
          `Counts under the ${row.older} agreement, the year you took it.`
        ) : (
          `Counts toward ${req.group_title.toLowerCase()}.`
        )}
      </p>
      <p className="credits-foot">
        <a href={req.citation.url} target="_blank" rel="noreferrer">
          {ag?.short ?? "ASSIST"} ↗
        </a>
        <Refs ns={row.refs} />
        {majors.length > 1 && (
          <span>{row.majors.map(shortMajor).join(" · ")}</span>
        )}
        {(question || req.status === "at_university") && (
          <Link
            to={`/counselor?${new URLSearchParams({ q: question ?? evaluationQuestion })}`}
          >
            {question ? "Review This Match" : "Ask About an Evaluation"} →
          </Link>
        )}
      </p>
    </li>
  );
}

/** "MATH 1A" never breaks across lines. */
const keepCodes = (text: string) =>
  text.replace(/\b([A-Z][A-Z0-9]{1,5}) (?=C?\d)/g, "$1 ");

/** "Take at <college>:" for rows still open, with how many of the listed options it takes. */
function takeAtLead(req: Requirement): string | undefined {
  if (
    !req.options?.length ||
    (req.status !== "missing" && req.status !== "partial")
  )
    return undefined;
  const college = agreementOf(req.citation.label)?.college ?? "your college";
  if (req.options.length === 1) return `Take at ${college}:`;
  const how =
    req.rule === "n_of" && req.n && req.flags.includes("n_units")
      ? `toward ${req.n} units`
      : req.rule === "n_of" && req.n && req.n > 1
        ? `${countWord(req.n)} of`
        : "one of";
  return `Take at ${college}, ${how}:`;
}

/** ASSIST's flags and grade minimums, for "How We Counted This". */
function CreditNotes({ rows }: { rows: Row[] }) {
  const byFlag = new Map<string, string[]>();
  const grades = new Set<string>();
  for (const r of rows) {
    for (const f of r.req.flags) {
      const grade = /^min_grade_(.+)$/.exec(f)?.[1];
      if (grade) grades.add(grade);
      if (QUIET_FLAGS.test(f)) continue;
      // Term mismatches matter only for courses that count.
      if (f === "course_year_mismatch" && r.req.status !== "satisfied")
        continue;
      const codes = byFlag.get(f) ?? [];
      if (!codes.includes(rowCode(r))) codes.push(rowCode(r));
      byFlag.set(f, codes);
    }
  }
  return (
    <>
      {[...byFlag].map(([flag, codes]) => {
        const copy = FLAG_NOTE[flag];
        const who = listing(codes);
        return copy ? (
          <Note key={flag} lead={copy.lead(who)}>
            {copy.body}
          </Note>
        ) : (
          <Note key={flag} lead={`${who}.`}>
            ASSIST flag: {flag.replace(/_/g, " ")}.
          </Note>
        );
      })}
      {grades.size > 0 && (
        <Note lead="Major grades.">
          Published minimums include{" "}
          {listing([...grades].map((grade) => `${grade} or better`))}. Check
          each agreement for the course-specific rule.
        </Note>
      )}
    </>
  );
}
