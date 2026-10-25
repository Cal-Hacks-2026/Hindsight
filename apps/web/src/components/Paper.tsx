import { useId, type ReactNode } from "react";
import { Icon, StudySketch, type IconName } from "./Icons";

export function Masthead({
  kicker,
  children,
  byline,
  sketch = "books",
}: {
  kicker?: ReactNode;
  children: ReactNode;
  byline?: ReactNode;
  sketch?: "books" | "cap" | "pencil" | "compass";
}) {
  return (
    <header className="masthead">
      <div className="masthead-copy">
        {kicker && <div className="kicker">{kicker}</div>}
        <h1>{children}</h1>
        {byline && <div className="byline">{byline}</div>}
      </div>
      <StudySketch variant={sketch} />
    </header>
  );
}

const sectionIcons: Record<string, IconName> = {
  Credits: "book",
  Plan: "calendar",
  Ask: "chat",
  Summary: "cap",
  "Your goal": "compass",
  "Heads up": "pencil",
  "This week": "calendar",
  Ranked: "compass",
  "About you": "user",
  "About You": "user",
  Transcript: "upload",
  "Confirm courses": "check",
  "Confirm Courses": "check",
};

export function Section({
  label,
  title,
  notes,
  last,
  children,
  id,
}: {
  num?: number;
  label: string;
  title?: ReactNode;
  notes?: ReactNode;
  notesFlush?: boolean;
  last?: boolean;
  children: ReactNode;
  id?: string;
}) {
  const generated = useId();
  const headingId = `${id ?? generated}-label`;
  return (
    <section
      className={`section${last ? " last" : ""}`}
      id={id}
      aria-labelledby={headingId}
    >
      <div className="section-head">
        <Icon name={sectionIcons[label] ?? "book"} size={19} />
        <h2 id={headingId}>{title ?? label}</h2>
      </div>
      <div className="section-main">{children}</div>
      {notes && (
        <aside className="notes" aria-label={`${label} notes`}>
          {notes}
        </aside>
      )}
    </section>
  );
}

/** The page's numbered sources, closed by default under "Sources (N)". A citation link
 *  (#source-n) opens it on the way there (Layout's openCitedSource). */
export function SourceList({
  count,
  children,
}: {
  count: number;
  children: ReactNode;
}) {
  return (
    <section
      className="section sources"
      id="sources"
      aria-labelledby="sources-label"
    >
      <details className="sources-details">
        <summary className="section-head">
          <Icon name="book" size={19} />
          <h2 id="sources-label">Sources ({count})</h2>
          <Icon name="chevron" size={20} />
        </summary>
        <div className="source-list">{children}</div>
      </details>
    </section>
  );
}

export function Note({
  lead,
  children,
  id,
}: {
  lead?: ReactNode;
  children: ReactNode;
  id?: string;
}) {
  return (
    <p id={id}>
      {lead && <strong>{lead}</strong>} {children}
    </p>
  );
}

export function Ref({ n }: { n: number | undefined }) {
  return n === undefined ? null : (
    <sup className="ref">
      <a href={`#source-${n}`} aria-label={`Source ${n}`}>
        {n}
      </a>
    </sup>
  );
}

export type StatusTone = "ok" | "check" | "missing" | "neutral";
export function StatusMark({
  tone,
  children,
}: {
  tone: StatusTone;
  children: ReactNode;
}) {
  return (
    <span className={`status ${tone}`}>
      {tone === "ok" && <Icon name="check" size={12} />}
      {children}
    </span>
  );
}
