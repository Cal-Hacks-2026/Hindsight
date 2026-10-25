// General Education on the Credits page: one card per Cal-GETC or IGETC area, from
// GET /profiles/{id}/ge (the college's ASSIST lists for the year each course was taken).
// The Credits page (routes/Degree.tsx) owns the filters; this file draws the areas and the notes.
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
import { StatusMark, type StatusTone } from "./Paper";
import { loadGePattern, saveGePattern, useGe } from "../lib/ge";
import "../styles/ge.css";

const OPTIONS_SHOWN = 3;
const PATTERNS: [GePattern, string][] = [
  ["calgetc", "Cal-GETC"],
  ["igetc", "IGETC"],
];

/** "To Take" (still needed, in progress), "Met", or everything. */
export type GeFilter = "todo" | "met" | "all";

function status(area: GeArea): { tone: StatusTone; label: string } {
  if (!area.required) return { tone: "neutral", label: "Not required" };
  switch (area.status) {
    case "done":
      return { tone: "ok", label: "Met" };
    case "in_progress":
      return { tone: "check", label: "In progress" };
    case "missing":
      return { tone: "missing", label: "Still needed" };
  }
}

/** "ENGL C1000" never breaks across lines. */
const nb = (code: string) => code.replace(/ /g, "\u00a0");

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

/** "MATH 10, Fall 2023" for a counted course; in progress says so. */
const taken = (c: GeCourse) =>
  `${nb(c.code)}, ${c.grade === "IP" ? `in progress ${c.term}` : c.term}`;

/** The student's Cal-GETC / IGETC choice (remembered per profile) and the GE progress for it. */
export function useGeProgress(profileId: string, courses?: Course[]) {
  const [pattern, setPattern] = useState<GePattern | undefined>(() => loadGePattern(profileId));
  const state = useGe(profileId, pattern, courses);
  const ge = state.status === "ready" ? state.ge : undefined;
  function choose(next: GePattern) {
    // Back to the default: forget the pick so a later transcript can change it.
    const pick = ge && next === ge.default_pattern ? undefined : next;
    saveGePattern(profileId, pick);
    setPattern(pick);
  }
  return { state, ge, choose };
}

/** "Take one: ARTS 1A, ARTS 1B, ARTS 2A +41 more"; the button opens the whole list with titles. */
function Options({ area }: { area: GeArea }) {
  const [all, setAll] = useState(false);
  const options = area.options ?? [];
  if (!options.length) return null;
  const lead = area.still_needed > 1 ? `Take ${area.still_needed}:` : "Take one:";
  const more = options.length - OPTIONS_SHOWN;
  const listId = `ge-options-${area.code}`;
  return (
    <div className="credits-what">
      <p>
        <strong>{lead}</strong>{" "}
        {!all && options.slice(0, OPTIONS_SHOWN).map((o) => nb(o.code)).join(", ")}
        {!all && more > 0 && " "}
        {more > 0 && (
          <button
            type="button"
            className="ge-more"
            aria-expanded={all}
            aria-controls={listId}
            onClick={() => setAll((a) => !a)}
          >
            {all ? "Show fewer" : `+${more} more`}
          </button>
        )}
      </p>
      {all && (
        <ul id={listId} className="ge-option-list">
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

/** One area, with the same lines as a requirement card: title, status and plan, what to take, source. */
function AreaCard({
  area,
  ge,
  planned,
}: {
  area: GeArea;
  ge: GeResponse;
  planned?: string;
}) {
  const mark = status(area);
  const college = ge.institution ?? "your college";
  const unitWord = ge.term_system === "quarter" ? "quarter units" : "units";
  const open = area.required && area.status !== "done";
  const when = [
    area.courses.map(taken).join(" + "),
    open && planned && `planned ${planned}`,
  ].filter(Boolean);
  const notes = [
    open ? area.note : units(area, unitWord),
    ...area.courses.flatMap((c) => c.flags.flatMap((f) => flagNote(f, college) ?? [])),
    ...(area.not_counted ?? []).map(
      (c) => `${nb(c.code)} (${c.grade}, ${c.term}) doesn't count here: it needs a C or better.`,
    ),
  ].filter(Boolean);
  return (
    <li className="credits-card" id={`ge-area-${area.code}`}>
      <h3 className="credits-title">
        {area.code} · {area.title}
      </h3>
      <p className="credits-status">
        <StatusMark tone={mark.tone}>{mark.label}</StatusMark>
        {when.length > 0 && <span>{when.join(" · ")}</span>}
      </p>
      {open && <Options area={area} />}
      {notes.length > 0 && <p className="credits-note">{notes.join(" ")}</p>}
      <p className="credits-foot">
        <Source citation={area.citation}>Standards</Source>
        {[...new Map(area.courses.map((c) => [c.citation.url, c.citation])).values()].map((c) => (
          <Source key={c.url} citation={c}>
            {listName(c)}
          </Source>
        ))}
      </p>
    </li>
  );
}

/** The areas for one status filter. Under "All", met and not-required areas fold into one row. */
export function GeAreaCards({
  ge,
  filter,
  plannedFor,
}: {
  ge: GeResponse;
  filter: GeFilter;
  /** The planned term for an area code ("3A"), when the plan has one. */
  plannedFor: (code: string) => string | undefined;
}) {
  const [showDone, setShowDone] = useState(false);
  const settled = ge.areas.filter((a) => !a.required || a.status === "done");
  const open = ge.areas.filter((a) => a.required && a.status !== "done");
  const card = (area: GeArea) => (
    <AreaCard key={area.code} area={area} ge={ge} planned={plannedFor(area.code)} />
  );
  if (filter === "met") {
    const met = settled.filter((a) => a.required);
    return met.length ? (
      <ol className="credits-cards">{met.map(card)}</ol>
    ) : (
      <p className="credits-empty">No {ge.pattern_name} areas met yet.</p>
    );
  }
  if (filter === "todo")
    return open.length ? (
      <ol className="credits-cards">{open.map(card)}</ol>
    ) : (
      <p className="credits-empty">Every {ge.pattern_name} area is met.</p>
    );
  const met = settled.filter((a) => a.required).map((a) => a.code);
  const notRequired = settled.filter((a) => !a.required).map((a) => a.code);
  return (
    <>
      {settled.length > 0 && (
        <div className="fold credits-fold">
          <button
            type="button"
            className="fold-toggle"
            aria-expanded={showDone}
            aria-controls="ge-done"
            onClick={() => setShowDone((o) => !o)}
          >
            <StatusMark tone="ok">Met</StatusMark>
            <span className="fold-meta">
              {[met.join(" · "), notRequired.length > 0 && `Not required: ${notRequired.join(" · ")}`]
                .filter(Boolean)
                .join(" · ")}
            </span>
            <Icon name="chevron" size={20} />
          </button>
          <ol id="ge-done" className="credits-cards" hidden={!showDone}>
            {settled.map(card)}
          </ol>
        </div>
      )}
      {open.length > 0 && <ol className="credits-cards">{open.map(card)}</ol>}
    </>
  );
}

/** For "How We Counted This": why this pattern (with the switch), course lists, grades, options. */
export function GeNotes({
  ge,
  onChoose,
}: {
  ge: GeResponse;
  onChoose: (pattern: GePattern) => void;
}) {
  const find = (re: RegExp) => ge.citations.find((c) => re.test(c.label));
  const college = ge.institution ?? "your college";
  const year = ge.options_year.replace("-", "–");
  return (
    <>
      <p>
        <strong>Why {ge.pattern_name}.</strong> {ge.rule}{" "}
        <Source citation={ge.rule_citation}>{ge.rule_citation.label.split(" · ")[0]!}</Source>
      </p>
      <div className="credit-filters credits-pattern" role="group" aria-label="General education pattern">
        {PATTERNS.map(([value, label]) => (
          <button
            type="button"
            key={value}
            aria-pressed={ge.pattern === value}
            onClick={() => onChoose(value)}
          >
            {label}
          </button>
        ))}
      </div>
      <p>
        <strong>Course lists.</strong> Each course is checked against {college}'s{" "}
        {ge.pattern_name} list for the year it was taken. A course counts in one area only; labs
        count with their science course.{" "}
        <Source citation={find(/Application Rights/)}>Standards</Source>
      </p>
      <p>
        <strong>GE grades.</strong> A C or better counts; a C- doesn't.{" "}
        <Source citation={find(/Grades/)}>Standards</Source>
      </p>
      <p>
        <strong>Options.</strong> Approved at {college} for {year}.{" "}
        <Source
          citation={ge.citations.find((c) => c.source === "assist" && c.label.endsWith(`(${year})`))}
        >
          ASSIST
        </Source>
      </p>
    </>
  );
}
