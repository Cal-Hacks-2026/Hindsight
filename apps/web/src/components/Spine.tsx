// A book spine (DESIGN.md §7). Solid = on the shelf; outline = planned; dashed = still needed;
// dotted = must be taken at the university.
import type { CSSProperties, ReactNode } from "react";
import { isLight } from "../lib/shelf";

export type SpineKind = "solid" | "outline" | "dashed" | "dotted";

export function Spine({
  label,
  sub,
  color,
  kind,
  width,
  height,
  href,
  title,
  textSize,
}: {
  label: string;
  sub?: string;
  color: string;
  kind: SpineKind;
  width: number;
  height: number;
  href?: string;
  /** Full description: tooltip and accessible name. */
  title: string;
  textSize?: number;
}) {
  const style: CSSProperties =
    kind === "solid"
      ? { width, height, background: color, color: isLight(color) ? "var(--ink)" : "var(--paper)" }
      : { width, height, color };
  const body = (
    <>
      <span className="spine-code" style={textSize ? { fontSize: textSize, letterSpacing: "0.1em" } : undefined}>
        {label}
      </span>
      {sub && <span className="spine-sub">{sub}</span>}
    </>
  );
  const className = `spine ${kind}`;
  if (href) {
    return (
      <a className={className} style={style} href={href} target="_blank" rel="noreferrer" title={title} aria-label={title}>
        {body}
      </a>
    );
  }
  return (
    <div className={className} style={style} title={title} role="img" aria-label={title}>
      {body}
    </div>
  );
}

/** Spines standing on a shelf board. `wide` keeps a minimum width and scrolls on phones. */
export function Shelf({ children, wide, label }: { children: ReactNode; wide?: boolean; label: string }) {
  return (
    <div className={wide ? "shelf-scroll" : undefined}>
      <div className={`shelf${wide ? " wide" : ""}`} role="group" aria-label={label}>
        {children}
      </div>
      <div className="shelf-base" aria-hidden="true" />
    </div>
  );
}
