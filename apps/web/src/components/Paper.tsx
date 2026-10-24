// The scientific-paper layout (DESIGN.md §6): a masthead, numbered sections on hairlines,
// and sidenotes in the margin for sources and asides.
import type { ReactNode } from "react";

export function Masthead({ kicker, children, byline }: { kicker: ReactNode; children: ReactNode; byline?: ReactNode }) {
  return (
    <div className="masthead">
      <div className="kicker">{kicker}</div>
      <h1>{children}</h1>
      {byline && <div className="byline">{byline}</div>}
    </div>
  );
}

/**
 * One row of the paper: label column (a light numeral over a tiny label, or the label alone),
 * the main column, and an optional margin of sidenotes.
 */
export function Section({
  num,
  label,
  title,
  notes,
  notesFlush,
  last,
  children,
  id,
}: {
  num?: number;
  label: string;
  title?: ReactNode;
  notes?: ReactNode;
  /** Sidenotes start level with the text instead of below the heading. */
  notesFlush?: boolean;
  last?: boolean;
  children: ReactNode;
  id?: string;
}) {
  const headingId = id ? `${id}-label` : undefined;
  return (
    <section className={`section${last ? " last" : ""}`} id={id} aria-labelledby={headingId}>
      <div className={`section-head${num === undefined ? " plain" : ""}`}>
        {num !== undefined && (
          <div className="numeral" aria-hidden="true">
            {String(num).padStart(2, "0")}
          </div>
        )}
        <div className="label" id={headingId}>
          {label}
        </div>
      </div>
      <div className="section-main">
        {title && <h2>{title}</h2>}
        {children}
      </div>
      {notes ? (
        <aside className={`notes${notesFlush ? " flush" : ""}`} aria-label="Notes">
          {notes}
        </aside>
      ) : (
        <div className="notes" aria-hidden="true" />
      )}
    </section>
  );
}

/** A sidenote: an optional bold lead-in, then the note. */
export function Note({ lead, children, id }: { lead?: ReactNode; children: ReactNode; id?: string }) {
  return (
    <p id={id}>
      {lead && <strong>{lead}</strong>} {children}
    </p>
  );
}

/** Superscript citation pointing at a numbered sidenote. */
export function Ref({ n }: { n: number | undefined }) {
  if (n === undefined) return null;
  return (
    <sup className="ref">
      <a href={`#source-${n}`} aria-label={`Source ${n}`}>
        {n}
      </a>
    </sup>
  );
}

export type StatusTone = "ok" | "check" | "missing" | "sjsu";

export function StatusMark({ tone, children }: { tone: StatusTone; children: ReactNode }) {
  return <span className={`status ${tone}`}>{children}</span>;
}
