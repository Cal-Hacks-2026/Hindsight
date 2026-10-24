import { Fragment, useState, type FormEvent, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import type { Course, MatchResult, Profile, Requirement, Semester } from "@hindsight/contracts";
import { Masthead, Note, Section, StatusMark, type StatusTone } from "../components/Paper";
import { Shelf, Spine, type SpineKind } from "../components/Spine";
import { ApiError } from "../lib/api";
import { catalogMajor, yearSpan } from "../lib/catalog";
import {
  CAMPUS_LONG,
  CAMPUS_SHORT,
  SENDING_LONG,
  bylineName,
  countWord,
  formatLongDate,
  listing,
  majorsLine,
  plural,
  shortMajor,
} from "../lib/format";
import { mentionsGraduation, parseGoalTerm, termIndex } from "../lib/goal";
import { lastTerm, termUnits, usePlans, type Plans } from "../lib/plans";
import { loadSession } from "../lib/session";
import { departmentColor, parseReceiving, spineHeight, spineWidth, type ParsedCourse } from "../lib/shelf";

// The planner's default cap (apps/api/app/services/planner.py DEFAULT_UNIT_CAP).
const UNIT_CAP = 15;
const TERMS_SHOWN = 3;
const PLACEHOLDER_PREFIX = "PLACEHOLDER · ";

// Human copy for gotcha flags; unknown flags fall through as-is.
const FLAG_NOTE: Record<string, { lead: (codes: string) => string; body: string }> = {
  course_year_mismatch: {
    lead: (c) => `Why ${c} ${c.includes(" and ") ? "are" : "is"} amber.`,
    body: "ASSIST lists the De Anza course for a different range of terms than the one on your transcript. It still matches, but confirm the term with your advisor.",
  },
  sequence_rule: {
    lead: (c) => `Why ${c} ${c.includes(" and ") ? "are" : "is"} partial.`,
    body: "ASSIST wants the whole De Anza sequence finished at one college before transfer. A partly finished sequence earns nothing yet.",
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
    body: "Taken pass/no pass. Check whether SJSU needs a letter grade.",
  },
  no_current_articulation: {
    lead: (c) => `${c}.`,
    body: "No De Anza course articulates to this one right now, so it has to be taken at SJSU.",
  },
};
const QUIET_FLAGS = /^(min_grade_|below_min_grade$|n_units$|sequence_grouping_inferred$|denied_course$)/;

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
const SHORT_NAMES: Record<string, string> = {
  "De Anza College": "De Anza",
  "San Jose State University": "SJSU",
  "San José State University": "SJSU",
};

type Agreement = { start: number; span: string; text: string; short: string };

function agreementOf(label: string): Agreement | undefined {
  const m = AGREEMENT_RE.exec(label);
  if (!m) return undefined;
  const [, from, to, major, start, end] = m;
  const span = `${start}–${end!.slice(2)}`;
  const name = (s: string) => SHORT_NAMES[s] ?? s;
  return { start: Number(start), span, text: `ASSIST · ${name(from!)} → ${name(to!)} · ${major} · ${span} agreement`, short: `ASSIST ${span}` };
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

const STATUS_ORDER: Requirement["status"][] = ["satisfied", "partial", "missing", "at_university"];

function buildRows(matches: MatchResult[], courses: Course[] | undefined, sources: Sources): Row[] {
  const rows = new Map<string, Row>();
  for (const m of matches) {
    const years = m.requirements.map((r) => agreementOf(r.citation.label)?.start ?? 0);
    const current = Math.max(0, ...years);
    for (const req of m.requirements) {
      const ag = agreementOf(req.citation.label);
      const n = sources.add(req.citation.url, ag?.text ?? req.citation.label, ag?.short ?? "ASSIST");
      const key = [req.receiving_course, req.status, req.satisfied_by.join("+")].join("|");
      let row = rows.get(key);
      if (!row) {
        const units = req.satisfied_by.reduce((sum, code) => sum + (findCourse(courses, code)?.units ?? 0), 0);
        row = { key, req, parsed: parseReceiving(req.receiving_course), majors: [], refs: [], units: units || undefined };
        rows.set(key, row);
      }
      if (!row.majors.includes(m.major_label)) row.majors.push(m.major_label);
      if (!row.refs.includes(n)) row.refs.push(n);
      if (req.status === "satisfied" && ag && ag.start < current) row.older = ag.span;
    }
  }
  return [...rows.values()].sort((a, b) => STATUS_ORDER.indexOf(a.req.status) - STATUS_ORDER.indexOf(b.req.status));
}

function findCourse(courses: Course[] | undefined, code: string): Course | undefined {
  const norm = (s: string) => s.replace(/\s+/g, " ").trim().toUpperCase();
  return courses?.find((c) => norm(`${c.prefix} ${c.number}`) === norm(code));
}

function tone(req: Requirement): { tone: StatusTone; label: string } {
  switch (req.status) {
    case "satisfied":
      return req.confidence === "high" ? { tone: "ok", label: "Counts" } : { tone: "check", label: "Counts · confirm" };
    case "partial":
      return { tone: "check", label: "Partial" };
    case "missing":
      return { tone: "missing", label: "Missing" };
    case "at_university":
      return { tone: "sjsu", label: "Take at SJSU" };
  }
}

/** "CIS 36A", "CIS 36B", "CS 46A" → "CIS 36A +2": spines are short; the Credits table lists them all. */
function shortCodes(codes: string[]): string {
  return codes.length > 1 ? `${codes[0]} +${codes.length - 1}` : (codes[0] ?? "");
}

const rowCode = (r: Row) => (r.parsed.choose ? "Elective" : r.parsed.code);

// ---- Page ----

export function Degree() {
  const location = useLocation();
  const session = loadSession();
  const matches: MatchResult[] | undefined =
    (location.state as { matches?: MatchResult[] } | null)?.matches ?? session.matches;
  const profile = session.profile;

  if (!profile || !matches?.length) return <NoResults hasProfile={!!profile} />;
  return <Report profile={profile} matches={matches} courses={session.courses} />;
}

function NoResults({ hasProfile }: { hasProfile: boolean }) {
  return (
    <>
      <Masthead kicker="Report No. 01 · Credit articulation & degree plan">
        Your degree,
        <br />
        in <em>hindsight</em>.
      </Masthead>
      <Section label="Summary" last>
        <p className="lede">
          No results yet. Upload your {SENDING_LONG} transcript and confirm your courses; this report then shows what
          already counts, what's missing, and a plan term by term.
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

function Report({ profile, matches, courses }: { profile: Profile; matches: MatchResult[]; courses?: Course[] }) {
  const majors = matches.map((m) => m.major_label);
  // The planner only knows curated majors; the rest get the ASSIST rows above and no plan.
  const planned = majors.filter((m) => catalogMajor(m));
  const uncurated = majors.filter((m) => !catalogMajor(m));
  const plans = usePlans(profile.id, planned.length ? majors : []);

  // Number the sources in reading order: agreements as the rows cite them, then the catalog.
  const sources = new Sources();
  const rows = buildRows(matches, courses, sources);
  const catalogRefs = majors.flatMap((label) => {
    const c = catalogMajor(label);
    return c
      ? [sources.add(c.source_url, `SJSU Catalog ${yearSpan(c.catalog_year)} · ${label}${label.endsWith(".") ? "" : "."} Not yet checked against the current catalog.`, `Catalog ${yearSpan(c.catalog_year)}`)]
      : [];
  });

  const campus = CAMPUS_SHORT[profile.campus];
  const today = formatLongDate();
  const missed = rows.filter((r) => r.req.status === "satisfied" && r.older);

  return (
    <>
      <Masthead
        kicker="Report No. 01 · Credit articulation & degree plan"
        byline={`${profile.name.trim() ? `Prepared for ${bylineName(profile.name)} · ` : ""}${SENDING_LONG} → ${CAMPUS_LONG[profile.campus]} · ${today}`}
      >
        Your degree,
        <br />
        in <em>hindsight</em>.
      </Masthead>

      {missed.length > 0 && <Missed rows={missed} courses={courses} />}

      <Section
        label="Summary"
        notesFlush
        notes={sources.list.map((s) => (
          <p key={s.n} id={`source-${s.n}`}>
            <strong>{s.n}</strong>&nbsp; <a href={s.url} target="_blank" rel="noreferrer">{s.text}</a>
          </p>
        ))}
      >
        <Abstract rows={rows} majors={planned} plans={plans.status === "ready" ? plans.plans : undefined} catalogRefs={catalogRefs} campus={campus} />
      </Section>

      {plans.status === "ready" && <GoalCheck goals={profile.goals} majors={planned} plans={plans.plans} />}

      <Credits rows={rows} courses={courses} majors={majors} campus={campus} plans={plans.status === "ready" ? plans.plans : undefined} />

      <Section num={2} label="Plan" title="The books still to collect, term by term." notes={<PlanNotes majors={planned} plans={plans.status === "ready" ? plans.plans : undefined} />}>
        <NotPlanned majors={uncurated} campus={campus} />
        {!planned.length ? null : plans.status === "loading" ? (
          <PlanLoading />
        ) : plans.status === "error" ? (
          <PlanError error={plans.error} />
        ) : (
          <>
            <p className="plan-caveat">
              Planned terms are proposals: we haven't confirmed which terms SJSU offers each course, so check the
              schedule before you register.
            </p>
            <PlanShelves semesters={plans.plans.combined} majors={planned} catalogRefs={catalogRefs} />
          </>
        )}
      </Section>

      <Ask />
    </>
  );
}

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
  campus,
}: {
  rows: Row[];
  majors: string[];
  plans?: Plans;
  catalogRefs: number[];
  campus: string;
}) {
  const done = rows.filter((r) => r.req.status === "satisfied");
  const partial = rows.filter((r) => r.req.status === "partial");
  const open = rows.filter((r) => r.req.status === "missing" || r.req.status === "at_university");
  const counted = new Set(done.flatMap((r) => r.req.satisfied_by));
  const older = done.filter((r) => r.older);

  const counts: ReactNode[] = [];
  if (done.length) {
    counts.push(
      <Fragment key="done">
        {countWord(counted.size, true)} of your De Anza courses already satisfy {countWord(done.length)} {campus}{" "}
        {plural(done.length, "requirement")}
        {older.length > 0 &&
          `, ${older.length === done.length ? "all" : countWord(older.length)} of them through an older agreement`}
        .{" "}
      </Fragment>,
    );
  } else {
    counts.push(<Fragment key="done">None of your De Anza courses satisfy a {campus} requirement yet. </Fragment>);
  }
  if (open.length) {
    const codes = open.map(rowCode);
    counts.push(
      <Fragment key="open">
        {countWord(open.length, true)} {plural(open.length, "requirement")} still {open.length === 1 ? "needs" : "need"} a
        course{codes.length <= 5 ? `: ${listing(codes)}` : ""}.{" "}
      </Fragment>,
    );
  }
  if (partial.length) {
    counts.push(
      <Fragment key="partial">
        {countWord(partial.length, true)} more {partial.length === 1 ? "is" : "are"} partly done.
      </Fragment>,
    );
  }

  const combined = plans && lastTerm(plans.combined);
  let finish: ReactNode = null;
  if (combined) {
    const [first, ...others] = majors;
    const alone = first ? plans.single[first] && lastTerm(plans.single[first]!) : undefined;
    finish = (
      <p className="lede">
        {alone && others.length
          ? `You can finish in ${alone} with ${shortMajor(first!)} only, or ${combined} with ${majorsLine(others)} added.`
          : `Your earliest finish is ${combined}.`}
        <Refs ns={catalogRefs} />
      </p>
    );
  }
  return (
    <>
      {finish}
      <p className={finish ? "lede-sub" : "lede"}>{counts}</p>
    </>
  );
}

// ---- Goal check ----

function GoalCheck({ goals, majors, plans }: { goals: string; majors: string[]; plans: Plans }) {
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
          You wrote "{text}", but we couldn't read a target term from it. Add one like "Spring 2028" so we can check
          it against your plan.{" "}
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
          On track. Your plan finishes {finish}, in time for your goal of graduating by {goal.label}.
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
        {goal.label} isn't reachable with {majorsLine(majors)}: the plan finishes {finish}.
      </p>
      <ul className="goal-levers">
        {levers.map((l) => (
          <li key={l}>{l}</li>
        ))}
        <li>A heavier term load or summer courses could close some of the gap. Ask your advisor what's allowed.</li>
      </ul>
    </Section>
  );
}

// ---- 01 Credits ----

function spineFor(row: Row, campus: string): { kind: SpineKind; color: string; sub: string } {
  const via = row.req.satisfied_by;
  switch (row.req.status) {
    case "satisfied":
      return { kind: "solid", color: departmentColor(via[0] && row.parsed.choose ? via[0] : row.parsed.code), sub: via.length ? `via ${shortCodes(via)}` : "" };
    case "partial":
      return { kind: "dashed", color: "var(--check)", sub: "partly done" };
    case "missing":
      return { kind: "dashed", color: "var(--missing)", sub: "still needed" };
    case "at_university":
      return { kind: "dotted", color: "var(--sjsu)", sub: `at ${campus}` };
  }
}

function Credits({ rows, courses, majors, campus, plans }: { rows: Row[]; courses?: Course[]; majors: string[]; campus: string; plans?: Plans }) {
  const planned = plannedTerms(plans);
  const onShelf = rows.filter((r) => r.req.status === "satisfied");
  const gaps = rows.filter((r) => r.req.status !== "satisfied");
  const present = new Set(rows.map((r) => r.req.status));

  const spine = (r: Row) => {
    const s = spineFor(r, campus);
    const label = rowCode(r);
    return (
      <Spine
        key={r.key}
        label={label}
        sub={s.sub}
        color={s.color}
        kind={s.kind}
        width={r.units ? spineWidth(r.units) : spineHeight(`${r.key}w`, 40, 48)}
        height={spineHeight(r.key, 160, 196)}
        title={`${label}: ${tone(r.req).label}. ${r.req.citation.ref ?? r.req.citation.label}`}
      />
    );
  };

  return (
    <Section num={1} label="Credits" title="What is already on your shelf." notes={<CreditNotes rows={rows} />}>
      <figure>
        <Shelf wide label="Requirements, as shelved books">
          {onShelf.map(spine)}
          {onShelf.length > 0 && gaps.length > 0 && <div className="shelf-gap" aria-hidden="true" />}
          {gaps.map(spine)}
        </Shelf>
        <figcaption className="legend">
          <span>
            <em className="fig">Fig. 1.</em> Your lower-division preparation, as {campus} sees it.
          </span>
          <span>▮ Solid — counts</span>
          {present.has("partial") && <span style={{ color: "var(--check)" }}>┆ Dashed — partly done</span>}
          {present.has("missing") && <span style={{ color: "var(--missing)" }}>┆ Dashed — still needed</span>}
          {present.has("at_university") && <span style={{ color: "var(--sjsu)" }}>⋮ Dotted — must be taken at {campus}</span>}
        </figcaption>
      </figure>

      <div className="table-scroll req-table">
        <table className="paper">
          <caption>Table 1. Requirement by requirement.</caption>
          <thead>
            <tr>
              <th scope="col">{campus} requirement</th>
              <th scope="col">Satisfied by</th>
              <th scope="col">Status</th>
              <th scope="col">Source</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              // A row only for majors the planner doesn't cover can't be "not in your plan yet".
              <RequirementRow key={r.key} row={r} courses={courses} majors={majors} planned={planned} plansReady={!!plans && r.majors.some((m) => !!catalogMajor(m))} />
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  );
}

function Missed({ rows, courses }: { rows: Row[]; courses?: Course[] }) {
  return (
    <Section label="Heads up" notesFlush>
      <div className="missed">
        <h2>Things your counselor missed.</h2>
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
                <strong>{rowCode(r)}</strong> counts through {via} only under the {r.older} agreement. The current one
                rates it lower or doesn't count it.{" "}
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

/** Where each planned course lands, by normalized code. */
function plannedTerms(plans?: Plans): Map<string, string> {
  const out = new Map<string, string>();
  for (const sem of plans?.combined ?? []) {
    for (const c of sem.courses) out.set(c.code.replace(/\s+/g, " ").trim().toUpperCase(), sem.term);
  }
  return out;
}

/** One line on what to do about a row that isn't plainly done; null when nothing is needed. */
function nextStep(row: Row, via: string[], planned: Map<string, string>, plansReady: boolean): string | null {
  const { req, parsed } = row;
  const term = planned.get(parsed.code.replace(/\s+/g, " ").trim().toUpperCase());
  const where = term ? ` Your plan puts it in ${term}.` : plansReady ? " It isn't in your plan yet; ask your advisor." : "";
  switch (req.status) {
    case "missing":
      return parsed.choose
        ? `Take one of: ${parsed.alternatives.join(", ")}.`
        : `Take ${parsed.code} before or after transferring.${where}`;
    case "at_university":
      return `Take ${parsed.code} at SJSU; no De Anza course counts for it.${where}`;
    case "partial":
      return req.flags.includes("sequence_rule")
        ? "Finish the whole De Anza sequence before you transfer, or none of it counts."
        : "Take one more course from this list to finish it.";
    case "satisfied":
      return req.confidence === "high"
        ? null
        : `Ask your advisor: "Does ${via.join(" + ") || "my course"} satisfy ${parsed.code} for ${row.majors.map(shortMajor).join(" and ")}?"`;
  }
}

function RequirementRow({ row, courses, majors, planned, plansReady }: { row: Row; courses?: Course[]; majors: string[]; planned: Map<string, string>; plansReady: boolean }) {
  const { req, parsed } = row;
  const t = tone(req);
  const via = req.satisfied_by.map((code) => {
    const term = findCourse(courses, code)?.term;
    return term ? `${code} · ${term}` : code;
  });
  const onlySome = majors.length > 1 && row.majors.length < majors.length;
  const next = nextStep(row, req.satisfied_by, planned, plansReady);
  return (
    <tr>
      <td>
        {parsed.choose ? (
          <>
            <strong>Elective</strong> · choose from {parsed.alternatives.join(", ")}
          </>
        ) : (
          <>
            <strong>{parsed.code}</strong>
            {parsed.title && ` · ${parsed.title}`}
            {parsed.alternatives.length > 0 && <span className="req-sub">or {parsed.alternatives.join(", ")}</span>}
          </>
        )}
        {onlySome && <span className="req-sub">{row.majors.map(shortMajor).join(", ")}</span>}
      </td>
      <td className={via.length ? undefined : "muted"}>
        {via.length ? via.join(", ") : req.status === "at_university" ? "No current articulation" : "—"}
      </td>
      <td>
        <StatusMark tone={t.tone}>{t.label}</StatusMark>
        {next && <span className="req-sub next-step">{next}</span>}
      </td>
      <td className="muted nowrap">
        <a href={req.citation.url} target="_blank" rel="noreferrer" title={req.citation.ref} style={{ color: "inherit", textDecoration: "none" }}>
          {agreementOf(req.citation.label)?.short ?? "ASSIST"}
        </a>
        <Refs ns={row.refs} />
      </td>
    </tr>
  );
}

function CreditNotes({ rows }: { rows: Row[] }) {
  const byFlag = new Map<string, string[]>();
  const grades = new Set<string>();
  for (const r of rows) {
    for (const f of r.req.flags) {
      const grade = /^min_grade_(.+)$/.exec(f)?.[1];
      if (grade) grades.add(grade);
      if (QUIET_FLAGS.test(f)) continue;
      // Shown only where it changes the reading: the amber note for credits that count, the rest anywhere.
      if (f === "course_year_mismatch" && r.req.status !== "satisfied") continue;
      const codes = byFlag.get(f) ?? [];
      if (!codes.includes(rowCode(r))) codes.push(rowCode(r));
      byFlag.set(f, codes);
    }
  }
  return (
    <>
      <Note lead="Reading the shelf.">
        Every solid spine is a {SENDING_LONG} course already accepted for a requirement. Hover any spine for its ASSIST
        row.
      </Note>
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
          Every credit shown meets the minimum grade ASSIST sets for it ({listing([...grades].map((g) => `${g} or better`))}).
        </Note>
      )}
    </>
  );
}

// ---- 02 Plan ----

function PlanShelves({ semesters, majors, catalogRefs }: { semesters: Semester[]; majors: string[]; catalogRefs: number[] }) {
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? semesters : semesters.slice(0, TERMS_SHOWN);
  const hidden = semesters.slice(TERMS_SHOWN);
  const years = [...new Set(majors.flatMap((m) => catalogMajor(m)?.catalog_year ?? []))].map(yearSpan);

  if (!semesters.length) {
    return <p className="lede">Nothing left to schedule: every listed requirement is already done.</p>;
  }

  return (
    <figure className="terms">
      {shown.map((s) => (
        <div className="term" key={s.term}>
          <div className="term-label">
            {s.term}
            <br />
            <span>{termUnits(s)} units</span>
          </div>
          <div className="term-shelf">
            <Shelf label={`${s.term} courses`}>
              {s.courses.map((c) => (
                <Spine
                  key={c.code}
                  label={c.code}
                  color={departmentColor(c.code)}
                  kind="outline"
                  width={spineWidth(c.units)}
                  height={spineHeight(c.code, 124, 142)}
                  title={`${c.code} · ${c.title} · ${c.units} units. ${c.reason.replace(PLACEHOLDER_PREFIX, "")}${
                    c.prereqs.length ? `. Needs ${c.prereqs.join(", ")}` : ""
                  }`}
                />
              ))}
            </Shelf>
          </div>
        </div>
      ))}
      {hidden.length > 0 && (
        <div className="term more">
          <div className="term-label">
            {expanded ? "Through" : `${hidden[0]!.term} →`}
            <br />
            <span>{expanded ? lastTerm(semesters) : `${hidden.length} more ${plural(hidden.length, "term")}`}</span>
          </div>
          <div className="term-shelf">
            <button type="button" className="text" onClick={() => setExpanded((e) => !e)} aria-expanded={expanded}>
              {expanded ? "Show the next three terms only" : `Show the full path to ${lastTerm(semesters)}`}
            </button>
          </div>
        </div>
      )}
      <figcaption style={{ maxWidth: 640 }}>
        <em className="fig">Fig. 2.</em> Proposed sequence for {majorsLine(majors)} at up to {UNIT_CAP} units per term.
        Order respects prerequisites in the SJSU Catalog {listing(years)}.<Refs ns={catalogRefs} /> Term-by-term course
        offerings are not yet confirmed. Hover a spine for why it's there.
      </figcaption>
    </figure>
  );
}

function PlanNotes({ majors, plans }: { majors: string[]; plans?: Plans }) {
  const combined = plans && lastTerm(plans.combined);
  const singles = plans ? majors.flatMap((m) => (plans.single[m]?.length ? [[m, lastTerm(plans.single[m]!)!] as const] : [])) : [];
  const unscheduled = majors.flatMap((m) =>
    (catalogMajor(m)?.unscheduled ?? []).map((g) => `${g.units} units of ${shortMajor(m)} ${g.title}`),
  );
  const placeholder = plans?.combined.some((s) => s.courses.some((c) => c.reason.startsWith(PLACEHOLDER_PREFIX)));
  return (
    <>
      {combined && (
        <Note lead="Earliest finish.">
          {singles.length && majors.length > 1
            ? `${singles.map(([m, t]) => `${t} with ${shortMajor(m)} alone`).join("; ")}. Together, ${combined}.`
            : `${combined}, at up to ${UNIT_CAP} units per term.`}
        </Note>
      )}
      {unscheduled.length > 0 && (
        <Note lead="Not yet scheduled.">
          {listing(unscheduled)}: the catalog lists no courses for {unscheduled.length === 1 ? "it" : "them"}, so the
          planner can't place {unscheduled.length === 1 ? "it" : "them"} and the finish term doesn't include{" "}
          {unscheduled.length === 1 ? "it" : "them"}.
        </Note>
      )}
      {placeholder && <Note lead="Sample data.">This major's requirements are placeholders until they're curated.</Note>}
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
            <span className="skeleton-line w-60" style={{ width: 80, height: 12 }} />
          </div>
          <div className="term-shelf">
            <div className="skeleton-shelf">
              {[132, 140, 126, 136].map((h, j) => (
                <span key={j} style={{ height: h - i * 4 }} />
              ))}
            </div>
            <div className="shelf-base" style={{ height: 2 }} />
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
      We don't have {campus}'s {listing(majors.map(shortMajor))} requirements yet, so lower-division only (from ASSIST).
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

function Ask() {
  const navigate = useNavigate();
  const [question, setQuestion] = useState("");
  function submit(e: FormEvent) {
    e.preventDefault();
    const q = question.trim();
    navigate(q ? `/counselor?${new URLSearchParams({ q })}` : "/counselor", { state: q ? { question: q } : undefined });
  }
  return (
    <Section num={3} label="Ask" last>
      <form className="ask" onSubmit={submit}>
        <label htmlFor="ask-q">What would you like to know about this plan?</label>
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
        <p>Answers cite ASSIST and the SJSU catalog. Hindsight never decides whether a credit counts; it explains the computed result.</p>
      </form>
    </Section>
  );
}
