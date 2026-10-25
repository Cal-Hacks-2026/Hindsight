// General Education on the Credits page: one row per Cal-GETC or IGETC area, from
// GET /profiles/{id}/ge (the college's ASSIST lists for the year each course was taken).
import { useState } from "react";
import type {
  Citation,
  Course,
  GeArea,
  GeCourse,
  GePattern,
  GeResponse,
} from "@hindsight/contracts";
import { Icon } from "./Icons";
import { Note, Section, StatusMark, type StatusTone } from "./Paper";
import { loadGePattern, saveGePattern, useGe } from "../lib/ge";
import "../styles/ge.css";

const OPTIONS_SHOWN = 4;
const PATTERNS: [GePattern, string][] = [
  ["calgetc", "Cal-GETC"],
  ["igetc", "IGETC"],
];

function status(area: GeArea): { tone: StatusTone; label: string } {
  if (!area.required) return { tone: "neutral", label: "Not required" };
  switch (area.status) {
    case "done":
      return { tone: "ok", label: "Done" };
    case "in_progress":
      return { tone: "check", label: "In progress" };
    case "missing":
      return { tone: "missing", label: "Still needed" };
  }
}

/** "ENGL C1000" never breaks across lines. */
const nb = (code: string) => code.replace(/ /g, " ");

/** "ASSIST · <College> · IGETC (2023–2024)" → "IGETC 2023–2024". */
const listName = (c: Citation) =>
  /· ([^·]+) \((\d{4}[–-]\d{4})\)$/.exec(c.label)?.slice(1).join(" ") ??
  "ASSIST list";

function Source({ citation, children }: { citation?: Citation; children: string }) {
  return citation ? (
    <a href={citation.url} target="_blank" rel="noreferrer">
      {children} ↗
    </a>
  ) : null;
}

function flagNote(flag: string, college: string): string | null {
  switch (flag) {
    case "pass_no_pass":
      return `Pass counts if ${college} treats it as a C or better.`;
    case "igetc_course":
      return "IGETC course from before Fall 2025, used in the same Cal-GETC area. Your college decides this exception.";
    case "calgetc_course":
      return "Cal-GETC course used in the same IGETC area. Your college decides this exception.";
    default:
      return null;
  }
}

function CourseLine({ course, college }: { course: GeCourse; college: string }) {
  const notes = course.flags.flatMap((f) => flagNote(f, college) ?? []);
  return (
    <li>
      <strong>{nb(course.code)}</strong> {course.title && `${course.title} · `}
      <span className="ge-meta">
        {course.term} · {course.grade === "IP" ? "In progress" : course.grade}
      </span>{" "}
      <Source citation={course.citation}>{listName(course.citation)}</Source>
      {notes.map((n) => (
        <span key={n} className="ge-flag">
          {n}
        </span>
      ))}
    </li>
  );
}

/** The first few approved courses; "+N more" opens the whole list with titles. */
function Options({ area }: { area: GeArea }) {
  const [all, setAll] = useState(false);
  const options = area.options ?? [];
  if (!options.length) return null;
  const lead = area.still_needed > 1 ? `Take ${area.still_needed} of:` : "Take one of:";
  const more = options.length - OPTIONS_SHOWN;
  const listId = `ge-options-${area.code}`;
  return (
    <div className="ge-take">
      <p>
        <strong>{lead}</strong>{" "}
        {!all && options.slice(0, OPTIONS_SHOWN).map((o) => nb(o.code)).join(" · ")}
        {!all && more > 0 && " "}
        {more > 0 && (
          <button
            type="button"
            className="ge-more"
            aria-expanded={all}
            aria-controls={listId}
            onClick={() => setAll((a) => !a)}
          >
            {all ? "Show Fewer" : `+${more} More`}
          </button>
        )}
      </p>
      {all && (
        <ul id={listId}>
          {options.map((o) => (
            <li key={o.code}>
              <strong>{nb(o.code)}</strong> {o.title}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** "9 quarter units." when met, "4 of 8 quarter units." on the way, nothing before any course counts. */
function units(area: GeArea, unitWord: string): string | null {
  if (!area.courses.length || area.units_required <= 0) return null;
  return area.units >= area.units_required
    ? `${area.units} ${unitWord}.`
    : `${area.units} of ${area.units_required} ${unitWord}.`;
}

function AreaRow({ area, ge }: { area: GeArea; ge: GeResponse }) {
  const mark = status(area);
  const college = ge.institution ?? "your college";
  const unitWord = ge.term_system === "quarter" ? "quarter units" : "units";
  return (
    <article className="ge-row">
      <p className="ge-code">{area.code}</p>
      <div className="ge-body">
        <h3 className="ge-title">{area.title}</h3>
        {area.courses.length > 0 && (
          <ul className="ge-courses">
            {area.courses.map((c) => (
              <CourseLine key={c.code} course={c} college={college} />
            ))}
          </ul>
        )}
        {area.not_counted?.map((c) => (
          <p key={c.code} className="ge-note">
            {nb(c.code)} ({c.grade}, {c.term}) doesn't count here: it needs a C
            or better.
          </p>
        ))}
        {area.required && area.status !== "done" && <Options area={area} />}
        <p className="ge-note">
          {[area.note, units(area, unitWord)].filter(Boolean).join(" ")}{" "}
          <Source citation={area.citation}>Standards</Source>
        </p>
      </div>
      <div className="ge-status">
        <StatusMark tone={mark.tone}>{mark.label}</StatusMark>
      </div>
    </article>
  );
}

function GeNotes({ ge }: { ge: GeResponse }) {
  const find = (re: RegExp) => ge.citations.find((c) => re.test(c.label));
  const college = ge.institution ?? "your college";
  return (
    <>
      <Note lead={`Why ${ge.pattern_name}.`}>
        {ge.rule}{" "}
        <Source citation={ge.rule_citation}>
          {ge.rule_citation.label.split(" · ")[0]!}
        </Source>
      </Note>
      <Note lead="Course lists.">
        Each course is checked against {college}'s {ge.pattern_name} list for
        the year it was taken. A course counts in one area only; labs count
        with their science course.{" "}
        <Source citation={find(/Application Rights/)}>Standards</Source>
      </Note>
      <Note lead="Grades.">
        A C or better counts; a C- doesn't.{" "}
        <Source citation={find(/Grades/)}>Standards</Source>
      </Note>
      <Note lead="Options.">
        Approved at {college} for {ge.options_year.replace("-", "–")}.{" "}
        <Source citation={ge.citations.find((c) => c.source === "assist" && c.label.endsWith(`(${ge.options_year.replace("-", "–")})`))}>
          ASSIST
        </Source>
      </Note>
    </>
  );
}

export function GeProgress({ profileId, courses }: { profileId: string; courses?: Course[] }) {
  const [pattern, setPattern] = useState<GePattern | undefined>(() => loadGePattern(profileId));
  const state = useGe(profileId, pattern, courses);
  const ge = state.status === "ready" ? state.ge : undefined;

  function choose(next: GePattern) {
    // Back to the default: forget the pick so a later transcript can change it.
    const pick = ge && next === ge.default_pattern ? undefined : next;
    saveGePattern(profileId, pick);
    setPattern(pick);
  }

  const [showDone, setShowDone] = useState(false);
  const required = ge?.areas.filter((a) => a.required) ?? [];
  const done = ge?.summary.done ?? 0;
  // Areas done (and ones the student's university doesn't require) fold into one row.
  const settled = ge?.areas.filter((a) => !a.required || a.status === "done") ?? [];
  const open = ge?.areas.filter((a) => a.required && a.status !== "done") ?? [];
  const notRequired = settled.filter((a) => !a.required).length;
  return (
    <Section
      id="general-education"
      label="Credits"
      title="General Education"
      notes={ge && <GeNotes ge={ge} />}
    >
      {state.status === "loading" && (
        <div role="status" aria-live="polite">
          <span className="sr-only">Checking general education…</span>
          {[0, 1, 2].map((i) => (
            <span key={i} className="skeleton-line ge-skeleton" aria-hidden="true" />
          ))}
        </div>
      )}
      {state.status === "error" && (
        <p className="lede">
          General education progress isn't available right now. Try again in a
          minute.
        </p>
      )}
      {ge && (
        <>
          <div
            className="progress-track"
            role="progressbar"
            aria-label="General education areas done"
            aria-valuemin={0}
            aria-valuemax={required.length || 1}
            aria-valuenow={done}
          >
            <span style={{ width: `${required.length ? (done / required.length) * 100 : 0}%` }} />
          </div>
          <p className="progress-caption">
            {done} of {required.length} {ge.pattern_name} areas done
            {ge.summary.in_progress > 0 && ` · ${ge.summary.in_progress} in progress`}
          </p>
          <div className="credit-filters" role="group" aria-label="General education pattern">
            {PATTERNS.map(([value, label]) => (
              <button
                type="button"
                key={value}
                aria-pressed={ge.pattern === value}
                onClick={() => choose(value)}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="ge-list" aria-live="polite">
            {settled.length > 0 && (
              <div className="fold ge-fold">
                <button
                  type="button"
                  className="fold-toggle"
                  aria-expanded={showDone}
                  aria-controls="ge-done"
                  onClick={() => setShowDone((o) => !o)}
                >
                  <StatusMark tone="ok">
                    {settled.length - notRequired} {settled.length - notRequired === 1 ? "area" : "areas"} done
                  </StatusMark>
                  <span className="fold-meta">
                    {settled
                      .filter((a) => a.required)
                      .map((a) => a.code)
                      .join(" · ")}
                    {notRequired > 0 && ` · ${notRequired} not required`}
                  </span>
                  <Icon name="chevron" size={20} />
                </button>
                <div id="ge-done" hidden={!showDone}>
                  {settled.map((area) => (
                    <AreaRow key={area.code} area={area} ge={ge} />
                  ))}
                </div>
              </div>
            )}
            {open.map((area) => (
              <AreaRow key={area.code} area={area} ge={ge} />
            ))}
          </div>
        </>
      )}
    </Section>
  );
}
