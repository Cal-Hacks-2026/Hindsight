// The plan as term tables, like a student's own class audit: planned terms (before transfer, then
// after), then completed terms from the transcript. Also the printable ed plan ("Download Ed Plan").
import {
  Fragment,
  useEffect,
  useState,
  type ChangeEvent,
  type CSSProperties,
  type ReactNode,
} from "react";
import type {
  Course,
  Requirement,
  Semester,
  SemesterCourse,
} from "@hindsight/contracts";
import { catalogMajor, yearSpan } from "../lib/catalog";
import { formatLongDate, listing, plural, shortMajor } from "../lib/format";
import { termIndex } from "../lib/goal";
import { parseReceiving } from "../lib/shelf";
import {
  afterTransfer,
  beforeTransfer,
  transferChoices,
  type Plans,
  type TermPicks,
} from "../lib/plans";
import {
  scheduledFor,
  timeRange,
  useSchedule,
  type Schedule,
  type ScheduledClass,
} from "../lib/schedule";
import "../styles/plan.css";

// The planner's default caps (apps/api/app/services/planner.py DEFAULT_UNIT_CAP, DEFAULT_CC_UNIT_CAP).
const UNIT_CAP = 15;
const CC_UNIT_CAP = 15;
/** Completed terms shown before "Show N earlier terms". */
const RECENT_TERMS = 2;
const PLACEHOLDER_PREFIX = "PLACEHOLDER · ";

/** A requirement from the student's match, with its numbered sources. `code`: "MATH 30", or "Elective". */
export type PlanRow = {
  req: Requirement;
  refs: number[];
  majors: string[];
  code: string;
  /** The ASSIST agreement year the requirement comes from: "2026–27". */
  agreement?: string;
};

/** Institution names: "De Anza" / "De Anza College", "SJSU" / "San José State University". */
export type PlanNames = {
  college: string;
  collegeLong: string;
  campus: string;
  campusLong: string;
  profileCampus: string;
};

/** What every table needs to say what a course counts toward and cite it. */
export type PlanContext = {
  plans?: Plans;
  rows: PlanRow[];
  courses?: Course[];
  names: PlanNames;
  majors: string[];
  /** Catalog source number per curated major label. */
  catalogRefs: Record<string, number>;
  profileId: string;
};

// ---- Shared pieces ----

export function Cite({ ns }: { ns: number[] }) {
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

const norm = (code: string) => code.replace(/\s+/g, " ").trim().toUpperCase();
const subjectOf = (code: string) => norm(code).split(" ")[0] ?? "";
const fmtUnits = (n: number) =>
  Number.isInteger(n) ? String(n) : n.toFixed(1);

/** One tint per subject, in the order subjects first appear. Hues step by the golden angle, so
 *  neighbors differ and any number of subjects stay distinct; every fill is light enough for ink
 *  text (12:1 or better). */
function subjectTints(ctx: PlanContext): (code: string) => number {
  const order: string[] = [];
  const codes = [
    ...(ctx.plans?.combined.flatMap((s) => s.courses.map((c) => c.code)) ?? []),
    ...(ctx.courses?.map((c) => `${c.prefix} ${c.number}`) ?? []),
  ];
  for (const code of codes) {
    const subject = subjectOf(code);
    if (!order.includes(subject)) order.push(subject);
  }
  return (code) =>
    (215 + Math.max(0, order.indexOf(subjectOf(code))) * 137.5) % 360;
}

function SubjectTag({
  code,
  title,
  tint,
}: {
  code: string;
  title: string;
  tint: number;
}) {
  const style = {
    "--tag-fill": `hsl(${tint} 42% 91%)`,
    "--tag-edge": `hsl(${tint} 32% 42%)`,
  } as CSSProperties;
  return (
    <span className="subject-tag" style={style}>
      <strong>{code}</strong>
      {title && <span>{title}</span>}
    </span>
  );
}

// ---- Counts Toward ----

type Count = { key: string; text: ReactNode; refs: number[]; note?: string };

function CountsList({ counts, grade }: { counts: Count[]; grade?: string }) {
  if (grade && NO_CREDIT.test(grade.trim().toUpperCase()))
    return <span className="plan-muted">No credit with this grade</span>;
  if (!counts.length)
    return (
      <span className="plan-muted">Not matched to a major requirement</span>
    );
  return (
    <ul className="plan-counts">
      {counts.map((c) => (
        <li key={c.key}>
          {c.text}
          <Cite ns={c.refs} />
          {c.note && <span className="plan-count-note">{c.note}</span>}
        </li>
      ))}
    </ul>
  );
}

/** Requirement rows merged by receiving course: the same requirement can appear once per major. */
function requirementCounts(
  hits: PlanRow[],
  ctx: PlanContext,
  note: (row: PlanRow) => string | undefined = () => undefined,
): Count[] {
  const merged = new Map<string, Count & { majors: string[] }>();
  for (const row of hits) {
    const key = row.req.receiving_course;
    const found = merged.get(key);
    if (found) {
      found.refs.push(...row.refs);
      found.majors.push(...row.majors);
      continue;
    }
    merged.set(key, {
      key,
      // A choose-from requirement reads by its group: "SJSU Major Electives".
      text: `${ctx.names.campus} ${row.code === "Elective" ? titleCase(row.req.group_title) : row.code}`,
      refs: [...row.refs],
      note: note(row),
      majors: [...row.majors],
    });
  }
  return [...merged.values()].map(({ majors, ...c }) => ({
    ...c,
    note:
      [c.note, ctx.majors.length > 1 && majorsNote(majors)]
        .filter(Boolean)
        .join(" · ") || undefined,
  }));
}

/** ASSIST's "MAJOR ELECTIVES" → "Major Electives" */
const titleCase = (text: string) =>
  text
    .toLowerCase()
    .replace(/\b(?!(?:and|or|of|for|the|to|in)\b)[a-z]/g, (c) =>
      c.toUpperCase(),
    );

const majorsNote = (majors: string[]) =>
  [...new Set(majors)].map(shortMajor).join(" and ");

/** Grades that earn no credit, so the attempt counts toward nothing. */
const NO_CREDIT = /^(F|W|FW|WF|NP|NC|I|U)$/;

/** The requirements ASSIST credits a taken course toward. */
const creditedBy = (course: Course, ctx: PlanContext) => {
  if (NO_CREDIT.test(course.grade.trim().toUpperCase())) return [];
  const code = norm(`${course.prefix} ${course.number}`);
  return ctx.rows.filter((r) =>
    r.req.satisfied_by.some((s) => norm(s) === code),
  );
};

function completedCounts(hits: PlanRow[], ctx: PlanContext): Count[] {
  return requirementCounts(hits, ctx, ({ req }) =>
    req.status === "partial"
      ? "partly complete"
      : req.status === "in_progress"
        ? "in progress"
        : req.confidence !== "high"
          ? "match needs review"
          : undefined,
  );
}

const GE_CHOICES_SHOWN = 4;

/** "Take one of ARTS 1A, ARTS 1B, ARTS 2A, ARTS 2B or 40 more". */
function geChoices(options: string[]): string {
  const shown = options.slice(0, GE_CHOICES_SHOWN).join(", ");
  const more = options.length - GE_CHOICES_SHOWN;
  if (more > 0) return `Take one of ${shown} or ${more} more`;
  return options.length > 1
    ? `Take one of ${options.slice(0, -1).join(", ")} or ${options.at(-1)}`
    : `Take ${options[0] ?? "an approved course"}`;
}

/** A planned course: the requirement the planner chose it for, from its reason. */
function plannedCounts(
  course: SemesterCourse,
  semester: Semester,
  ctx: PlanContext,
): Count[] {
  const reason = course.reason.replace(PLACEHOLDER_PREFIX, "");
  // A GE slot: any course on the area's approved list (/plan?ge=true).
  if (course.ge_options)
    return [
      {
        key: "ge",
        text: `${course.ge_area}: ${course.title}`,
        refs: [],
        note: geChoices(course.ge_options),
      },
    ];
  // A major course that also counts for a GE area.
  const ge: Count[] = course.ge_area
    ? [{ key: "ge", text: `Also ${course.ge_area}`, refs: [] }]
    : [];
  if (semester.phase === "before_transfer") {
    // "For MATH 30 - Calculus I (Data Science, B.S.); ASSIST option: MATH 1A"
    const hits = ctx.rows.filter((r) =>
      reason.includes(`For ${r.req.receiving_course} (`),
    );
    if (hits.length) return [...requirementCounts(hits, ctx), ...ge];
    // The saved match predates this plan: name the requirement from the reason, uncited.
    return [
      ...[...reason.matchAll(/(?:^|; )For (.+?) \(/g)].map((m, i) => ({
        key: `${i}`,
        text: `${ctx.names.campus} ${parseReceiving(m[1]!).code}`,
        refs: [],
      })),
      ...ge,
    ];
  }
  // "Core Courses (Economics, B.S.)", "Major Electives: pick 1 of 2 still needed toward 15 units
  // (Data Science, B.S.); any listed elective works", "Prerequisite for CS 146"
  const all = Object.values(ctx.catalogRefs);
  const parts = reason
    .split("; ")
    .filter((part) => part && part !== "any listed elective works");
  // Every "Prerequisite for X" becomes one line: "Prerequisite for CS 156, CS 171 and CS 133".
  const unlocks = parts.flatMap(
    (part) => /^Prerequisite for (.+)$/.exec(part)?.[1] ?? [],
  );
  const counts = parts
    .filter((part) => !part.startsWith("Prerequisite for "))
    .map((part, i): Count => {
      const group =
        /^(.+?)(: pick \d+ of \d+ still needed toward .+?)? \(([^()]+)\)$/.exec(
          part,
        );
      if (!group) return { key: `${i}`, text: part, refs: all };
      const [, title, pick, major] = group;
      const ref = ctx.catalogRefs[major!];
      return {
        key: `${i}`,
        text: `${ctx.names.campus} ${title}`,
        refs: ref ? [ref] : all,
        note:
          [pick && "elective", ctx.majors.length > 1 && shortMajor(major!)]
            .filter(Boolean)
            .join(" · ") || undefined,
      };
    });
  if (unlocks.length)
    counts.push({
      key: "prereq",
      text: `Prerequisite for ${listing(unlocks)}`,
      refs: all,
    });
  return counts;
}

// ---- Section cell (from the Schedule feature) ----

const MODE: Record<NonNullable<ScheduledClass["mode"]>, string> = {
  in_person: "In person",
  online: "Online",
  hybrid: "Hybrid",
  asynchronous: "Asynchronous",
};

function SectionCell({ slot }: { slot?: ScheduledClass }) {
  if (!slot) return <span className="plan-muted">Pick a Section</span>;
  const days = slot.days?.length ? slot.days.join(", ") : undefined;
  const time = timeRange(slot.start_time, slot.end_time);
  return (
    <span className="plan-section">
      <strong>{slot.section ? `Section ${slot.section}` : "Section"}</strong>
      {slot.crn && <span className="plan-muted">CRN {slot.crn}</span>}
      {slot.professor && <span>{slot.professor}</span>}
      {days && <span>{days}</span>}
      {time && <span className="nowrap">{time}</span>}
      {slot.mode && slot.mode !== "in_person" && !days && (
        <span>{MODE[slot.mode]}</span>
      )}
    </span>
  );
}

// ---- Term tables ----

type TableRow = {
  key: string;
  code: string;
  title: string;
  units: number;
  counts: Count[];
  prereqs?: string[];
  grade?: string;
  agreement?: string;
  slot?: ScheduledClass;
};

const GRADE: Record<string, string> = { IP: "In progress" };

function TermTable({
  id,
  term,
  status,
  institution,
  kind,
  rows,
  unitLabel,
  tint,
  className,
}: {
  id: string;
  term: string;
  status: string;
  institution: string;
  kind: "planned" | "completed";
  rows: TableRow[];
  unitLabel: string;
  tint: (code: string) => number;
  className?: string;
}) {
  const total = rows.reduce((n, r) => n + r.units, 0);
  const headingId = `${id}-heading`;
  const columns = kind === "planned" ? 4 : 5;
  return (
    <div className={`plan-term${className ? ` ${className}` : ""}`}>
      <h4 className="plan-term-head" id={headingId}>
        {term}
        <span>
          <span className="plan-term-sep"> · </span>
          {status} · {institution}
        </span>
      </h4>
      <div
        className="plan-table-scroll"
        role="region"
        aria-labelledby={headingId}
        tabIndex={0}
      >
        <table className={`plan-table ${kind}`} aria-labelledby={headingId}>
          <thead>
            <tr>
              <th scope="col">Course</th>
              <th scope="col">Counts Toward</th>
              <th scope="col" className="num">
                Units
              </th>
              {kind === "planned" ? (
                <th scope="col">Section</th>
              ) : (
                <>
                  <th scope="col">Grade</th>
                  <th scope="col">Agreement Year</th>
                </>
              )}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key}>
                <td>
                  <SubjectTag
                    code={r.code}
                    title={r.title}
                    tint={tint(r.code)}
                  />
                  {r.prereqs && r.prereqs.length > 0 && (
                    <span className="plan-prereqs">
                      Prerequisites: {r.prereqs.join(", ")}
                    </span>
                  )}
                </td>
                <td>
                  <CountsList counts={r.counts} grade={r.grade} />
                </td>
                <td className="num">{fmtUnits(r.units)}</td>
                {kind === "planned" ? (
                  <td>
                    <SectionCell slot={r.slot} />
                  </td>
                ) : (
                  <>
                    <td className="nowrap">
                      {GRADE[r.grade ?? ""] ?? (r.grade || "—")}
                    </td>
                    <td>{r.agreement ?? "—"}</td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row" colSpan={2}>
                Term total
              </th>
              <td className="num">{fmtUnits(total)}</td>
              <td colSpan={columns - 3}>{unitLabel}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}

const unitLabelOf = (s?: Semester) =>
  s?.term_system === "quarter" ? "quarter units" : "units";

function PlannedTerm({
  semester,
  ctx,
  schedule,
  tint,
}: {
  semester: Semester;
  ctx: PlanContext;
  schedule: Schedule;
  tint: (code: string) => number;
}) {
  const before = semester.phase === "before_transfer";
  return (
    <TermTable
      id={`plan-${semester.term.replace(/\s+/g, "-").toLowerCase()}`}
      term={semester.term}
      status="Planned"
      institution={
        semester.institution ??
        (before ? ctx.names.collegeLong : ctx.names.campusLong)
      }
      kind="planned"
      unitLabel={unitLabelOf(semester)}
      tint={tint}
      rows={semester.courses.map((c, i) => ({
        // GE slots repeat a code ("Cal-GETC 4" twice).
        key: c.ge_options ? `${c.code}-${i}` : c.code,
        code: c.code,
        title: c.title,
        units: c.units,
        counts: plannedCounts(c, semester, ctx),
        prereqs: c.prereqs,
        slot: scheduledFor(schedule, semester.term, c.code),
      }))}
    />
  );
}

/** The next term with courses, for "Take Next". */
export function NextTermTable({ ctx }: { ctx: PlanContext }) {
  const schedule = useSchedule(ctx.profileId);
  const next = ctx.plans?.combined.find((s) => s.courses.length > 0);
  if (!next) return null;
  return (
    <PlannedTerm
      semester={next}
      ctx={ctx}
      schedule={schedule}
      tint={subjectTints(ctx)}
    />
  );
}

/** Transcript courses by term, newest first; an undated course goes last. */
function transcriptTerms(courses: Course[]) {
  const byTerm = new Map<string, Course[]>();
  for (const c of courses) {
    const term = c.term.trim() || "Term not listed";
    byTerm.set(term, [...(byTerm.get(term) ?? []), c]);
  }
  return [...byTerm]
    .map(([term, list]) => ({ term, courses: list, at: termIndex(term) ?? -1 }))
    .sort((a, b) => b.at - a.at);
}

// ---- The whole course plan ----

export function PlanTables({
  ctx,
  student,
  picks,
  onPick,
  fullPlan,
  loading,
}: {
  ctx: PlanContext;
  student: string;
  /** The planner is still running: printing now would leave out the planned terms. */
  loading: boolean;
  picks: TermPicks;
  onPick: (which: keyof TermPicks, term: string | undefined) => void;
  fullPlan: boolean;
}) {
  const { plans, names, majors } = ctx;
  const schedule = useSchedule(ctx.profileId);
  const tint = subjectTints(ctx);
  const before = plans ? beforeTransfer(plans.combined) : [];
  const after = plans ? afterTransfer(plans.combined) : [];
  const response = plans?.response;
  const transfer = response?.transfer_term;
  const earliest = response?.earliest_transfer_term;
  const late = response?.not_before_transfer;
  const geLate = response?.ge_not_before_transfer;
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
  const allCatalogRefs = Object.values(ctx.catalogRefs);

  const [showEarlier, setShowEarlier] = useState(false);
  const taken = ctx.courses?.length ? transcriptTerms(ctx.courses) : [];
  const earlier = taken.length - RECENT_TERMS;

  const pathway = `${majors.map(shortMajor).join(" + ")} · ${names.collegeLong} to ${names.campusLong}`;

  return (
    <div className="ed-plan">
      <header className="ed-plan-print-head">
        <h1>Education Plan</h1>
        <p className="ed-plan-pathway">{majors.join(" + ")}</p>
        <p>
          {names.collegeLong} → {names.campusLong}
        </p>
        <dl>
          <div>
            <dt>Student</dt>
            <dd>{student}</dd>
          </div>
          {response?.start_term && (
            <div>
              <dt>Start</dt>
              <dd>{response.start_term}</dd>
            </div>
          )}
          {transfer && (
            <div>
              <dt>Transfer</dt>
              <dd>{transfer}</dd>
            </div>
          )}
          <div>
            <dt>Prepared</dt>
            <dd>{formatLongDate()}</dd>
          </div>
        </dl>
      </header>

      <div className="plan-actions">
        <PrintButton title={`Ed Plan · ${pathway}`} disabled={loading} />
      </div>

      {plans && (
        <>
          <p className="plan-caveat">
            Course offerings aren’t confirmed. Check {names.college} and{" "}
            {names.campus} schedules before registering.
          </p>
          <div className="term-picks">
            {response?.default_start_term && response.start_term_choices && (
              <TermSelect
                id="start-term"
                label={`Starting at ${names.college} in`}
                value={picks.start}
                defaultTerm={response.default_start_term}
                defaultNote="default"
                choices={response.start_term_choices}
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
          {geLate && geLate.length > 0 && (
            <p className="plan-warning" role="status">
              {transfer} is too early to finish {listing(geLate)} at{" "}
              {names.college}.
              {earliest &&
                ` Transferring in ${earliest} leaves time for all of them.`}
            </p>
          )}
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
              <span className="phase-kicker">Before Transfer</span> at {college}
            </h3>
            {before.length ? (
              <div className="plan-terms">
                {before.map((s) => (
                  <PlannedTerm
                    key={s.term}
                    semester={s}
                    ctx={ctx}
                    schedule={schedule}
                    tint={tint}
                  />
                ))}
              </div>
            ) : (
              <p className="lede">
                Nothing left to take at {names.college} for{" "}
                {majors.map(shortMajor).join(" + ")}.
              </p>
            )}
            <p className="phase-note">
              Up to {CC_UNIT_CAP} {quarters ? "quarter" : "semester"} units per
              term. Courses follow ASSIST sequences; check {names.college}{" "}
              prerequisites.{" "}
              {response?.ge_pattern
                ? `${response.ge_pattern === "igetc" ? "IGETC" : "Cal-GETC"} general education comes after the major courses; pick each course from the area's list on the Credits page.`
                : "General education isn't included."}
            </p>
          </div>

          <div className="phase">
            <h3 className="phase-head">
              <span className="phase-kicker">After Transfer</span> at {campus}
            </h3>
            {!fullPlan ? (
              <p className="lede">
                {names.campus}'s full degree requirements aren't available yet,
                so upper-division courses aren't planned. Check with{" "}
                {names.campus}'s advisors.
              </p>
            ) : after.length ? (
              <>
                <div className="plan-terms">
                  {after.map((s) => (
                    <PlannedTerm
                      key={s.term}
                      semester={s}
                      ctx={ctx}
                      schedule={schedule}
                      tint={tint}
                    />
                  ))}
                </div>
                <p className="phase-note">
                  Up to {UNIT_CAP} units per term, following prerequisites in
                  the {names.campus} Catalog {listing(years)}.
                  <Cite ns={allCatalogRefs} />
                </p>
              </>
            ) : (
              <p className="lede">
                Nothing left to schedule at {names.campus}: every listed
                requirement is done or planned before transfer.
              </p>
            )}
          </div>
        </>
      )}

      {taken.length > 0 && (
        <div className="phase">
          <h3 className="phase-head">
            <span className="phase-kicker">Completed</span> from your transcript
          </h3>
          <div className="plan-terms">
            {taken.map((t, i) => (
              <TermTable
                key={t.term}
                id={`taken-${i}`}
                className={
                  i >= RECENT_TERMS && !showEarlier ? "is-collapsed" : undefined
                }
                term={t.term}
                status={
                  t.courses.some((c) => c.grade.toUpperCase() === "IP")
                    ? "In Progress"
                    : "Completed"
                }
                institution={names.collegeLong}
                kind="completed"
                unitLabel={quarters ? "quarter units" : "units"}
                tint={tint}
                rows={t.courses.map((c, j) => {
                  const hits = creditedBy(c, ctx);
                  const agreements = [
                    ...new Set(hits.flatMap((r) => r.agreement ?? [])),
                  ];
                  return {
                    key: `${c.prefix} ${c.number} ${j}`,
                    code: `${c.prefix} ${c.number}`,
                    title: c.title,
                    units: c.units,
                    counts: completedCounts(hits, ctx),
                    grade: c.grade,
                    agreement: agreements.length
                      ? agreements.join(", ")
                      : undefined,
                  };
                })}
              />
            ))}
          </div>
          {earlier > 0 && (
            <button
              type="button"
              className="text plan-earlier"
              aria-expanded={showEarlier}
              onClick={() => setShowEarlier((s) => !s)}
            >
              {showEarlier
                ? "Hide earlier terms"
                : `Show ${earlier} earlier ${plural(earlier, "term")}`}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/** "Download Ed Plan": the browser's print dialog, which also saves a PDF, named for the pathway. */
function PrintButton({
  title,
  disabled,
}: {
  title: string;
  disabled: boolean;
}) {
  const [printing, setPrinting] = useState(false);
  useEffect(() => {
    if (!printing) return;
    const previous = document.title;
    document.title = title;
    const done = () => setPrinting(false);
    window.addEventListener("afterprint", done);
    window.print();
    return () => {
      window.removeEventListener("afterprint", done);
      document.title = previous;
    };
  }, [printing, title]);
  return (
    <button type="button" disabled={disabled} onClick={() => setPrinting(true)}>
      {/* Icons.tsx's stroke style; drawn here so the shared icon set stays untouched. */}
      <svg
        width={22}
        height={22}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M12 3v13m-5-5 5 5 5-5M4 15v5h16v-5" />
      </svg>
      Download Ed Plan
    </button>
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

/** Placeholder term tables while the planner runs. */
export function PlanTablesLoading() {
  return (
    <div role="status" aria-live="polite" className="plan-terms">
      <span className="sr-only">Building your plan…</span>
      {[0, 1].map((i) => (
        <div className="plan-term" key={i} aria-hidden="true">
          <span className="skeleton-line" style={{ width: 280, height: 22 }} />
          <div className="plan-table-scroll plan-skeleton">
            {[0, 1, 2].map((j) => (
              <span key={j} className="skeleton-line" />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
