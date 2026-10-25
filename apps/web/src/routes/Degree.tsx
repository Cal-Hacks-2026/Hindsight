import {
  Fragment,
  useEffect,
  useState,
  type ChangeEvent,
  type FormEvent,
  type ReactNode,
} from "react";
import { Link, useLocation, useNavigate } from "react-router";
import type {
  Course,
  MatchResult,
  Profile,
  Requirement,
  Semester,
} from "@hindsight/contracts";
import {
  Masthead,
  Note,
  Section,
  StatusMark,
  type StatusTone,
} from "../components/Paper";
import { Icon } from "../components/Icons";
import { ApiError } from "../lib/api";
import { catalogMajor, hasFullPlan, yearSpan } from "../lib/catalog";
import {
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
import { mentionsGraduation, parseGoalTerm, termIndex } from "../lib/goal";
import {
  afterTransfer,
  beforeTransfer,
  lastTerm,
  loadTerm,
  saveTerm,
  termUnits,
  transferChoices,
  usePlans,
  type Plans,
  type TermPicks,
} from "../lib/plans";
import { loadSession } from "../lib/session";
import { parseReceiving, type ParsedCourse } from "../lib/shelf";

// The planner's default cap (apps/api/app/services/planner.py DEFAULT_UNIT_CAP).
const UNIT_CAP = 15;
const TERMS_SHOWN = 3;
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

// "De Anza College → San Jose State University · Data Science, B.S. (2026–2027)"
const AGREEMENT_RE = /^(.+?) → (.+?) · (.+) \((\d{4})[–-](\d{4})\)$/;

/** `college`: the sending college's short name, e.g. "De Anza", "Foothill"; `from`/`to`: full names. */
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
      return { tone: "sjsu", label: "No published match" };
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
        {view === "credits" ? "My credits" : "My plan"}
      </Masthead>
      <Section label="Summary" last>
        <p className="lede">
          Add your transcript to see which credits count and what comes next.
        </p>
        <p className="actions" style={{ marginTop: 28 }}>
          <Link className="button primary" to="/onboarding">
            {hasProfile ? "Upload your transcript" : "Set up your profile"}
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
  const majors = matches.map((m) => m.major_label);
  // With the university's requirements (SJSU), the planner plans curated majors only; the rest get
  // the ASSIST rows and no plan. Without them (any other university), every major gets its
  // community-college terms and the after-transfer block says what's missing.
  const fullPlan = hasFullPlan(profile.campus);
  const planned = fullPlan
    ? majors.filter((m) => catalogMajor(m, profile.campus))
    : majors;
  const uncurated = fullPlan
    ? majors.filter((m) => !catalogMajor(m, profile.campus))
    : [];
  // The student's start and transfer terms, if they picked them; otherwise the planner's defaults.
  const [picks, setPicks] = useState<TermPicks>(() => {
    const transfer = loadTerm("transfer", profile.id);
    return {
      transfer:
        transfer && transferChoices().includes(transfer) ? transfer : undefined,
      start: loadTerm("start", profile.id),
    };
  });
  const plans = usePlans(
    profile.id,
    view === "plan" && planned.length ? majors : [],
    picks,
  );
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
  // Names as the ASSIST agreement gives them, so a Foothill report never says De Anza.
  const agreement = matches
    .flatMap((m) => m.requirements.map((r) => agreementOf(r.citation.label)))
    .find(Boolean);
  const campusLong = agreement?.to ?? universityName(profile);
  const campus = shortUniversity(campusLong);
  const catalogRefs = majors.flatMap((label) => {
    const c = catalogMajor(label, profile.campus);
    return c
      ? [
          sources.add(
            c.source_url,
            `${campus} Catalog ${yearSpan(c.catalog_year)} · ${label}${label.endsWith(".") ? "" : "."} Not yet checked against the current catalog.`,
            `Catalog ${yearSpan(c.catalog_year)}`,
          ),
        ]
      : [];
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
    profileCampus: profile.campus,
  };
  const missed = rows.filter((r) => r.req.status === "satisfied" && r.older);

  const ready = plans.status === "ready" ? plans.plans : undefined;
  const citations = (
    <Section label="Sources" title="Sources">
      <div className="source-list">
        {sources.list.map((source) => (
          <p key={source.n} id={`source-${source.n}`}>
            <strong>{source.n}.</strong>{" "}
            <a href={source.url} target="_blank" rel="noreferrer">
              {source.text}
            </a>
          </p>
        ))}
      </div>
    </Section>
  );

  return (
    <>
      <Masthead
        byline={majorsLine(majors)}
        sketch={view === "credits" ? "books" : "cap"}
      >
        {view === "credits" ? "My credits" : "My plan"}
      </Masthead>
      {view === "credits" ? (
        <>
          <Credits
            rows={rows}
            courses={courses}
            majors={majors}
            campus={campus}
          />
          {missed.length > 0 && <Missed rows={missed} courses={courses} />}
        </>
      ) : (
        <>
          {ready && (
            <NextTerm plans={ready} catalogRefs={catalogRefs} rows={rows} />
          )}
          {planned.length > 0 && plans.status === "loading" && (
            <Section label="Plan" title="Building your plan">
              <PlanLoading />
            </Section>
          )}
          {plans.status === "error" && (
            <Section label="Plan" title="Your plan">
              <PlanError error={plans.error} />
            </Section>
          )}
          <Attention rows={rows} />
          <Section label="Summary" title="Your progress">
            <Abstract
              rows={rows}
              majors={planned}
              plans={ready}
              catalogRefs={catalogRefs}
              names={names}
              fullPlan={fullPlan}
            />
          </Section>
          {/* Without the university's requirements there's no finish term to check a goal against. */}
          {fullPlan && ready && (
            <GoalCheck goals={profile.goals} majors={planned} plans={ready} />
          )}
          <Section
            id="course-plan"
            label="Plan"
            title="Your course plan"
            notes={
              <PlanNotes
                majors={planned}
                plans={ready}
                names={names}
                fullPlan={fullPlan}
              />
            }
          >
            <NotPlanned majors={uncurated} campus={campus} />
            {ready && (
              <Roadmap
                plans={ready}
                majors={planned}
                catalogRefs={catalogRefs}
                names={names}
                picks={picks}
                onPick={pick}
                fullPlan={fullPlan}
              />
            )}
          </Section>
          <Ask names={names} fullPlan={fullPlan} />
        </>
      )}
      {citations}
    </>
  );
}

/** Institution names for copy, from the agreement: "De Anza" / "De Anza College", "SJSU" / "San Jose State University". */
type Names = {
  college: string;
  collegeLong: string;
  campus: string;
  campusLong: string;
  profileCampus: string;
};

// ---- Abstract ----

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

function Abstract({
  rows,
  majors,
  plans,
  catalogRefs,
  names,
  fullPlan,
}: {
  rows: Row[];
  majors: string[];
  plans?: Plans;
  catalogRefs: number[];
  names: Names;
  fullPlan: boolean;
}) {
  const { campus, college } = names;
  const done = rows.filter((r) => r.req.status === "satisfied");
  const partial = rows.filter((r) => r.req.status === "partial");
  const inProgress = rows.filter((r) => r.req.status === "in_progress");
  const open = rows.filter(
    (r) => r.req.status === "missing" || r.req.status === "at_university",
  );
  const combined = plans && lastTerm(plans.combined);
  const before = plans && beforeTransfer(plans.combined);
  return (
    <>
      <dl className="progress-stats">
        <div>
          <dt>Requirements met</dt>
          <dd>{done.length}</dd>
        </div>
        <div>
          <dt>In progress</dt>
          <dd>{inProgress.length}</dd>
        </div>
        <div>
          <dt>Partly complete</dt>
          <dd>{partial.length}</dd>
        </div>
        <div>
          <dt>Still to take</dt>
          <dd>{open.length}</dd>
        </div>
      </dl>
      {combined && plans && (
        <>
          <dl className="milestones">
            {plans.response.transfer_term && (
              <div>
                <dt>Planned transfer to {campus}</dt>
                <dd>{plans.response.transfer_term}</dd>
              </div>
            )}
            {/* Without the university's requirements the last planned term is a community-college one, not a finish. */}
            {fullPlan && (
              <div>
                <dt>
                  Estimated major completion
                  <Refs ns={catalogRefs} />
                </dt>
                <dd>{combined}</dd>
              </div>
            )}
          </dl>
          {before && before.length > 0 && (
            <p className="plan-note">
              {countWord(before.length, true)} {plural(before.length, "term")}{" "}
              at {college} before transfer.
            </p>
          )}
          {fullPlan && majors.length > 1 && (
            <div className="major-comparison">
              {majors.map((major) => {
                const term =
                  plans.single[major] && lastTerm(plans.single[major]!);
                return term ? (
                  <p key={major}>
                    {shortMajor(major)} alone: <strong>{term}</strong>
                    <Refs ns={catalogRefs} />
                  </p>
                ) : null;
              })}
            </div>
          )}
        </>
      )}
      <p className="plan-note">
        Major requirements only. General education and other graduation
        requirements aren’t included.
      </p>
      <Link className="inline-link" to="/credits">
        Review my credits <Icon name="arrow" size={20} />
      </Link>
    </>
  );
}

function NextTerm({
  plans,
  catalogRefs,
  rows,
}: {
  plans: Plans;
  catalogRefs: number[];
  rows: Row[];
}) {
  const next = plans.combined.find((semester) => semester.courses.length > 0);
  if (!next) return null;
  const unitLabel = next.term_system === "quarter" ? "quarter units" : "units";
  const refs =
    next.phase === "before_transfer"
      ? [...new Set(rows.flatMap((row) => row.refs))]
      : catalogRefs;
  return (
    <Section label="Plan" title="Take next">
      <div className="next-term-heading">
        <h3>{next.term}</h3>
        <span>
          {termUnits(next)} {unitLabel}
        </span>
      </div>
      {next.institution && (
        <p className="next-institution">At {next.institution}</p>
      )}
      <CourseCards semester={next} unitLabel={unitLabel} />
      <p className="plan-note">
        Proposed courses. Check availability and prerequisites before
        registering.
        <Refs ns={refs} />
      </p>
      <a className="inline-link" href="#course-plan">
        See the full plan <Icon name="arrow" size={20} />
      </a>
    </Section>
  );
}

function Attention({ rows }: { rows: Row[] }) {
  const review = rows.filter(
    ({ req }) =>
      req.status === "partial" ||
      req.confidence !== "high" ||
      (req.status === "satisfied" &&
        req.flags.some((flag) =>
          ["course_year_mismatch", "pass_no_pass"].includes(flag),
        )),
  );
  if (!review.length) return null;
  return (
    <Section label="Heads up" title="Needs attention">
      <ul className="attention-list">
        {review.slice(0, 3).map((row) => (
          <li key={row.key}>
            <div>
              <strong>{rowCode(row)}</strong>
              <p>
                {row.req.status === "partial"
                  ? row.req.flags.includes("sequence_rule")
                    ? "Complete the remaining sequence before this requirement counts."
                    : "Complete the remaining courses for this requirement."
                  : "Check this course’s match before relying on it."}
                <Refs ns={row.refs} />
              </p>
            </div>
            <Link
              className="inline-link"
              to={`/counselor?${new URLSearchParams({ q: `What should I do next for ${row.req.receiving_course}?` })}`}
            >
              Get next steps <Icon name="arrow" size={20} />
            </Link>
          </li>
        ))}
      </ul>
      <Link className="inline-link" to="/credits">
        Review all credits <Icon name="arrow" size={20} />
      </Link>
    </Section>
  );
}

function CourseCards({
  semester,
  unitLabel,
}: {
  semester: Semester;
  unitLabel: string;
}) {
  return (
    <div className="course-list">
      {semester.courses.map((course) => (
        <details className="course-card" key={course.code}>
          <summary>
            <strong>{course.code}</strong>
            <span>
              {course.units} {unitLabel}
            </span>
            <span className="course-title">{course.title}</span>
          </summary>
          <p>{course.reason.replace(PLACEHOLDER_PREFIX, "")}</p>
          {course.prereqs.length > 0 && (
            <p>Prerequisites: {course.prereqs.join(", ")}</p>
          )}
        </details>
      ))}
    </div>
  );
}

// ---- Goal check ----

function GoalCheck({
  goals,
  majors,
  plans,
}: {
  goals: string;
  majors: string[];
  plans: Plans;
}) {
  const text = goals.trim();
  if (!text) return null;
  const goal = parseGoalTerm(text);
  const finish = lastTerm(plans.combined);
  const finishAt = finish ? termIndex(finish) : undefined;

  if (!goal) {
    if (!mentionsGraduation(text)) return null;
    return (
      <Section label="Your goal">
        <p className="goal">
          You wrote "{text}", but we couldn't read a target term from it. Add
          one like "Spring 2028" so we can check it against your plan.{" "}
          <Link to="/onboarding">Edit your goals</Link>
        </p>
      </Section>
    );
  }
  if (!finish || finishAt === undefined) return null;

  if (finishAt <= goal.index) {
    return (
      <Section label="Your goal">
        <p className="goal ok">
          Your major plan finishes {finish}, within your {goal.label} target.
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
    <Section label="Your goal">
      <p className="goal late">
        Your current major plan finishes {finish}, after your {goal.label} goal.
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

// ---- 01 Credits ----

function Credits({
  rows,
  courses,
  majors,
  campus,
}: {
  rows: Row[];
  courses?: Course[];
  majors: string[];
  campus: string;
}) {
  const [filter, setFilter] = useState<"all" | "met" | "review">("all");
  const done = rows.filter((row) => row.req.status === "satisfied").length;
  const shown = rows.filter(
    ({ req }) =>
      filter === "all" ||
      (filter === "met"
        ? req.status === "satisfied"
        : req.status !== "satisfied" || req.confidence !== "high"),
  );
  return (
    <Section
      label="Credits"
      title="What counts toward your major"
      notes={<CreditNotes rows={rows} />}
    >
      <div
        className="progress-track"
        role="progressbar"
        aria-label="Requirements satisfied"
        aria-valuemin={0}
        aria-valuemax={rows.length || 1}
        aria-valuenow={done}
      >
        <span
          style={{ width: `${rows.length ? (done / rows.length) * 100 : 0}%` }}
        />
      </div>
      <p className="progress-caption">
        {done} of {rows.length} requirements met
      </p>
      <div className="credit-filters" aria-label="Filter credits">
        {(
          [
            ["all", "All"],
            ["met", "Met"],
            ["review", "To resolve"],
          ] as const
        ).map(([value, label]) => (
          <button
            type="button"
            key={value}
            aria-pressed={filter === value}
            onClick={() => setFilter(value)}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="credit-list" aria-live="polite">
        {shown.map((row) => (
          <RequirementRow
            key={row.key}
            row={row}
            courses={courses}
            majors={majors}
            campus={campus}
          />
        ))}
        {!shown.length && <p className="lede">No requirements in this view.</p>}
      </div>
    </Section>
  );
}

function Missed({ rows, courses }: { rows: Row[]; courses?: Course[] }) {
  return (
    <Section label="Heads up" notesFlush>
      <div className="missed">
        <h2>Credits worth a second look</h2>
        <ul>
          {rows.map((r) => {
            const via = r.req.satisfied_by
              .map((code) => {
                const term = findCourse(courses, code)?.term;
                return term ? `${code} (${term})` : code;
              })
              .join(" + ");
            return (
              <li key={r.key}>
                <strong>{rowCode(r)}</strong> counts through {via} only under
                the {r.older} agreement. The current one rates it lower or
                doesn't count it.{" "}
                <a href={r.req.citation.url} target="_blank" rel="noreferrer">
                  ASSIST {r.older}
                </a>
              </li>
            );
          })}
        </ul>
      </div>
    </Section>
  );
}

/** For a credit that counts with doubt, the question to take to an advisor. */
function advisorQuestion(row: Row): string | null {
  const { req, parsed } = row;
  if (req.status !== "satisfied" || req.confidence === "high") return null;
  const via = req.satisfied_by.join(" + ") || "my course";
  return `Ask your advisor: "Does ${via} satisfy ${parsed.code} for ${row.majors.map(shortMajor).join(" and ")}?"`;
}

function RequirementRow({
  row,
  courses,
  majors,
  campus,
}: {
  row: Row;
  courses?: Course[];
  majors: string[];
  campus: string;
}) {
  const { req, parsed } = row;
  const status = tone(req);
  const via = req.satisfied_by.map((code) => {
    const course = findCourse(courses, code);
    return `${code}${course?.term ? ` · ${course.term}` : ""}`;
  });
  const takeAt = takeAtLead(req);
  const question = advisorQuestion(row);
  const college = agreementOf(req.citation.label)?.college ?? "your college";
  const evaluationQuestion = `There is no published course match for ${req.receiving_course}. What should I submit to request an evaluation?`;
  return (
    <article className="credit-card">
      <header className="credit-heading">
        <div>
          <p className="credit-context">{campus} requirement</p>
          <h3>{parsed.choose ? "Choose an elective" : parsed.code}</h3>
          {parsed.title && <p className="credit-title">{parsed.title}</p>}
        </div>
        <StatusMark tone={status.tone}>{status.label}</StatusMark>
      </header>
      <dl className="credit-details">
        {via.length > 0 && (
          <div>
            <dt>Your coursework</dt>
            <dd>
              {via.map((course) => (
                <span key={course}>{course}</span>
              ))}
            </dd>
          </div>
        )}
        <div>
          <dt>Applies to</dt>
          <dd>
            {req.group_title.charAt(0) + req.group_title.slice(1).toLowerCase()}
            {majors.length > 1 && (
              <span>{row.majors.map(shortMajor).join(" · ")}</span>
            )}
          </dd>
        </div>
      </dl>
      {parsed.alternatives.length > 0 && (
        <details className="credit-options">
          <summary>
            {parsed.choose
              ? parsed.choose.charAt(0).toUpperCase() + parsed.choose.slice(1)
              : "Accepted alternatives"}
          </summary>
          <p>{parsed.alternatives.join(" · ")}</p>
        </details>
      )}
      {takeAt && (
        <p className="credit-next">
          <strong>{takeAt}</strong> {req.options!.map(keepCodes).join(" · ")}
        </p>
      )}
      {req.status === "missing" && !takeAt && (
        <p className="credit-next">Not matched to your confirmed coursework.</p>
      )}
      {req.status === "at_university" && (
        <p className="credit-next">
          No published equivalent at {college}. Request an evaluation to check
          whether prior coursework can apply.
        </p>
      )}
      {question && <p className="credit-next">{question}</p>}
      <div className="credit-actions">
        <a href={req.citation.url} target="_blank" rel="noreferrer">
          {agreementOf(req.citation.label)?.short ?? "View agreement"} ↗
        </a>
        <Refs ns={row.refs} />
        {(question || req.status === "at_university") && (
          <Link
            className="inline-link"
            to={`/counselor?${new URLSearchParams({ q: question ?? evaluationQuestion })}`}
          >
            {question ? "Review this match" : "Ask about an evaluation"}
            <Icon name="arrow" size={20} />
          </Link>
        )}
      </div>
    </article>
  );
}

/** "MATH 1A" never breaks across lines. */
const keepCodes = (text: string) =>
  text.replace(/\b([A-Z][A-Z0-9]{1,5}) (?=C?\d)/g, "$1\u00a0");

/** "Take at De Anza:" for rows still open, with how many of the listed options it takes. */
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
        <Note lead="Grades.">
          Published minimums include{" "}
          {listing([...grades].map((grade) => `${grade} or better`))}. Check
          each agreement for the course-specific rule.
        </Note>
      )}
    </>
  );
}

// ---- 02 Plan ----

// The planner's default caps (apps/api/app/services/planner.py DEFAULT_UNIT_CAP, DEFAULT_CC_UNIT_CAP).
const CC_UNIT_CAP = 15;

function Roadmap({
  plans,
  majors,
  catalogRefs,
  names,
  picks,
  onPick,
  fullPlan,
}: {
  plans: Plans;
  majors: string[];
  catalogRefs: number[];
  names: Names;
  picks: TermPicks;
  onPick: (which: keyof TermPicks, term: string | undefined) => void;
  fullPlan: boolean;
}) {
  const before = beforeTransfer(plans.combined);
  const after = afterTransfer(plans.combined);
  const {
    transfer_term: transfer,
    earliest_transfer_term: earliest,
    not_before_transfer: late,
    default_start_term: defaultStart,
    start_term_choices: startChoices,
  } = plans.response;
  const college = before[0]?.institution ?? names.collegeLong;
  const campus = after[0]?.institution ?? names.campusLong;
  const quarters = (before[0]?.term_system ?? "quarter") === "quarter";
  const years = [
    ...new Set(
      majors.flatMap(
        (m) => catalogMajor(m, names.profileCampus)?.catalog_year ?? [],
      ),
    ),
  ].map(yearSpan);
  return (
    <>
      <p className="plan-caveat">
        Course offerings aren’t confirmed. Check {names.college} and{" "}
        {names.campus} schedules before registering.
      </p>

      <div className="term-picks">
        {defaultStart && startChoices && (
          <TermSelect
            id="start-term"
            label={`Starting at ${names.college} in`}
            value={picks.start}
            defaultTerm={defaultStart}
            defaultNote="default"
            choices={startChoices}
            onPick={(t) => onPick("start", t)}
          />
        )}
        {transfer && (
          <TermSelect
            id="transfer-term"
            label={`Transfer to ${names.campus} in`}
            value={picks.transfer}
            defaultTerm={earliest ?? transfer}
            defaultNote="earliest"
            choices={transferChoices()}
            onPick={(t) => onPick("transfer", t)}
          />
        )}
      </div>
      {late && late.length > 0 && (
        <p className="plan-warning" role="status">
          {transfer} is too early for {listing(late)} at {names.college}, so{" "}
          {late.length === 1 ? "its" : "their"} {names.campus}{" "}
          {late.length === 1 ? "equivalent is" : "equivalents are"} planned
          after transfer instead.
          {earliest &&
            ` Transferring in ${earliest} leaves time for all of them.`}
        </p>
      )}

      <div className="phase">
        <h3 className="phase-head">
          <span className="phase-kicker">Before transfer</span> at {college}
        </h3>
        {before.length ? (
          <PlanShelves
            semesters={before}
            unitLabel={quarters ? "qtr units" : "units"}
            caption={
              <>
                Up to {CC_UNIT_CAP} {quarters ? "quarter" : "semester"} units
                per term. Courses follow ASSIST sequences; check {names.college}{" "}
                prerequisites.
              </>
            }
          />
        ) : (
          <p className="lede">
            Nothing left to take at {names.college} for {majorsLine(majors)}.
          </p>
        )}
        <p className="phase-note">GE (Cal-GETC) isn't included yet.</p>
      </div>

      <div className="phase">
        <h3 className="phase-head">
          <span className="phase-kicker">After transfer</span> at {campus}
        </h3>
        {!fullPlan ? (
          <p className="lede">
            {names.campus}'s full degree requirements aren't available yet, so
            upper-division courses aren't planned. Check with {names.campus}'s
            advisors.
          </p>
        ) : after.length ? (
          <PlanShelves
            semesters={after}
            unitLabel="units"
            caption={
              <>
                Up to {UNIT_CAP} units per term, following prerequisites in the{" "}
                {names.campus} Catalog {listing(years)}.
                <Refs ns={catalogRefs} />
              </>
            }
          />
        ) : (
          <p className="lede">
            Nothing left to schedule at {names.campus}: every listed requirement
            is done or planned before transfer.
          </p>
        )}
      </div>
    </>
  );
}

/** A term picker whose empty value means the planner's default ("Fall 2028 (earliest)"). */
function TermSelect({
  id,
  label,
  value,
  defaultTerm,
  defaultNote,
  choices,
  onPick,
}: {
  id: string;
  label: string;
  value?: string;
  defaultTerm: string;
  defaultNote: string;
  choices: string[];
  onPick: (term: string | undefined) => void;
}) {
  function change(e: ChangeEvent<HTMLSelectElement>) {
    onPick(e.target.value || undefined);
  }
  return (
    <div className="term-pick">
      <label htmlFor={id}>{label}</label>
      <select id={id} value={value ?? ""} onChange={change}>
        <option value="">
          {defaultTerm} ({defaultNote})
        </option>
        {choices
          .filter((t) => t !== defaultTerm)
          .map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
      </select>
    </div>
  );
}

function PlanShelves({
  semesters,
  caption,
  unitLabel,
}: {
  semesters: Semester[];
  caption: ReactNode;
  unitLabel: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? semesters : semesters.slice(0, TERMS_SHOWN);
  const hidden = semesters.slice(TERMS_SHOWN);

  return (
    <figure className="terms">
      {shown.map((s) => (
        <div className="term" key={s.term}>
          <div className="term-label">
            {s.term}
            <br />
            <span>
              {termUnits(s)} {unitLabel}
            </span>
          </div>
          <div className="term-shelf">
            <CourseCards semester={s} unitLabel={unitLabel} />
          </div>
        </div>
      ))}
      {hidden.length > 0 && (
        <div className="term more">
          <div className="term-label">
            {expanded ? "Through" : `${hidden[0]!.term} →`}
            <br />
            <span>
              {expanded
                ? lastTerm(semesters)
                : `${hidden.length} more ${plural(hidden.length, "term")}`}
            </span>
          </div>
          <div className="term-shelf">
            <button
              type="button"
              className="text"
              onClick={() => setExpanded((e) => !e)}
              aria-expanded={expanded}
            >
              {expanded
                ? "Show fewer terms"
                : `Show every term to ${lastTerm(semesters)}`}
            </button>
          </div>
        </div>
      )}
      <figcaption style={{ maxWidth: 640 }}>{caption}</figcaption>
    </figure>
  );
}

function PlanNotes({
  majors,
  plans,
  names,
  fullPlan,
}: {
  majors: string[];
  plans?: Plans;
  names: Names;
  fullPlan: boolean;
}) {
  const combined = plans && lastTerm(plans.combined);
  const transfer = plans?.response.transfer_term;
  const singles = plans
    ? majors.flatMap((m) =>
        plans.single[m]?.length
          ? [[m, lastTerm(plans.single[m]!)!] as const]
          : [],
      )
    : [];
  const unscheduled = majors.flatMap((m) =>
    (catalogMajor(m, names.profileCampus)?.unscheduled ?? []).map(
      (g) => `${g.units} units of ${shortMajor(m)} ${g.title}`,
    ),
  );
  const placeholder = plans?.combined.some((s) =>
    s.courses.some((c) => c.reason.startsWith(PLACEHOLDER_PREFIX)),
  );
  return (
    <>
      {transfer && (
        <Note lead="Transfer.">
          {plans?.response.earliest_transfer_term === transfer
            ? `${transfer}, the first Fall after your ${names.college} courses. You can pick another term above the plan.`
            : `${transfer}, as you picked. The earliest that fits every ${names.college} course is ${plans?.response.earliest_transfer_term}.`}
        </Note>
      )}
      {combined && fullPlan && (
        <Note lead="Earliest finish.">
          {singles.length && majors.length > 1
            ? `${singles.map(([m, t]) => `${t} with ${shortMajor(m)} alone`).join("; ")}. Together, ${combined}.`
            : `${combined}, at up to ${UNIT_CAP} units per ${names.campus} term.`}
        </Note>
      )}
      {unscheduled.length > 0 && (
        <Note lead="Not yet scheduled.">
          {listing(unscheduled)}: the catalog lists no courses for{" "}
          {unscheduled.length === 1 ? "it" : "them"}, so the planner can't place{" "}
          {unscheduled.length === 1 ? "it" : "them"} and the finish term doesn't
          include {unscheduled.length === 1 ? "it" : "them"}.
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

function PlanLoading() {
  return (
    <div role="status" aria-live="polite" className="terms">
      <span className="sr-only">Building your plan…</span>
      {[0, 1, 2].map((i) => (
        <div className="term" key={i} aria-hidden="true">
          <div className="term-label">
            <span
              className="skeleton-line w-60"
              style={{ width: 80, height: 12 }}
            />
          </div>
          <div className="term-shelf">
            <div className="skeleton-shelf">
              {[132, 140, 126, 136].map((h, j) => (
                <span key={j} style={{ height: h - i * 4 }} />
              ))}
            </div>
          </div>
        </div>
      ))}
    </div>
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
      <h3>Couldn't build a plan.</h3>
      <p>{detail}</p>
    </div>
  );
}

// ---- 03 Ask ----

function Ask({ names, fullPlan }: { names: Names; fullPlan: boolean }) {
  const navigate = useNavigate();
  const [question, setQuestion] = useState("");
  function submit(e: FormEvent) {
    e.preventDefault();
    const q = question.trim();
    navigate(q ? `/counselor?${new URLSearchParams({ q })}` : "/counselor", {
      state: q ? { question: q } : undefined,
    });
  }
  return (
    <Section num={3} label="Ask" last>
      <form className="ask" onSubmit={submit}>
        <label htmlFor="ask-q">Questions about your plan?</label>
        <div className="ask-row">
          <input
            id="ask-q"
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Can I graduate by Spring 2028 if I add a major?"
          />
          <button className="primary" type="submit">
            Ask the counselor
          </button>
        </div>
        <p>
          Answers grounded in your transcript
          {fullPlan ? `, ASSIST and the ${names.campus} catalog.` : " and ASSIST."}
        </p>
      </form>
    </Section>
  );
}
