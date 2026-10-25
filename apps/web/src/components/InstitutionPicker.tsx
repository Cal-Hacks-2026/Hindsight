// A searchable pick from one of ASSIST's institution lists. Nothing is picked by default: with no
// choice yet it shows the filter box and the list. Once picked, it reads like the old transfer-path
// line (label over the chosen name) and "Change" opens the box again. `locked` (with the reason as
// its text) keeps it closed until an earlier choice is made.
import { useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import type { AssistInstitution } from "@hindsight/contracts";
import { shortUniversity } from "../lib/format";

/** Case- and accent-insensitive: "jose" finds "José". */
const fold = (s: string) => s.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();

/** What a search matches: the name, plus its short form (the registry's, or "UC <Campus>", "CSU <Campus>"). */
const haystack = (i: AssistInstitution) => fold(`${i.name} ${shortUniversity(i.name, i.id)}`);

export function InstitutionPicker({
  id,
  label,
  noun,
  nouns,
  value,
  options,
  onChange,
  badge,
  hint,
  locked,
}: {
  id: string;
  label: string;
  /** "community college" / "community colleges": for the placeholder and empty states. */
  noun: string;
  nouns: string;
  value?: AssistInstitution;
  /** undefined while loading. */
  options?: AssistInstitution[];
  onChange: (i: AssistInstitution) => void;
  badge?: (i: AssistInstitution) => string | undefined;
  hint?: ReactNode;
  /** Why it can't be used yet: "Pick a community college first." */
  locked?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const change = useRef<HTMLButtonElement>(null);
  const words = fold(query).split(/[\s,]+/).filter(Boolean);
  const shown = (options ?? []).filter((o) => words.every((w) => haystack(o).includes(w)));

  function pick(o: AssistInstitution) {
    onChange(o);
    setOpen(false);
    setQuery("");
    // The list it was picked from is gone; keep focus on this field rather than the page.
    requestAnimationFrame(() => change.current?.focus());
  }

  function key(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") {
      setOpen(false);
      setQuery("");
    } else if (e.key === "Enter") {
      e.preventDefault(); // not the form's submit
      if (shown[0]) pick(shown[0]);
    }
  }

  const tag = value && badge?.(value);
  const searching = !locked && (open || (!value && !!options?.length));
  return (
    <div className="field picker">
      <span className="label" id={`${id}-label`}>
        {label}
      </span>
      {locked ? (
        <input type="search" disabled placeholder={locked} aria-labelledby={`${id}-label`} />
      ) : searching ? (
        <>
          <input
            type="search"
            autoFocus={open}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={key}
            placeholder={`Search ${options?.length ?? 0} ${nouns} by name`}
            aria-labelledby={`${id}-label`}
            aria-controls={`${id}-list`}
          />
          <ul className="choices scroll picker-list" id={`${id}-list`} role="listbox" aria-labelledby={`${id}-label`}>
            {shown.map((o) => {
              const b = badge?.(o);
              return (
                <li key={o.id} role="option" aria-selected={o.id === value?.id}>
                  <button type="button" className="picker-option" onClick={() => pick(o)}>
                    <span>{o.name}</span>
                    {b && <span className="picker-tag">{b}</span>}
                  </button>
                </li>
              );
            })}
            {shown.length === 0 && (
              <li className="muted picker-empty">
                No {noun} matches “{query}”.
              </li>
            )}
          </ul>
          {value && (
            <button type="button" className="text picker-cancel" onClick={() => setOpen(false)}>
              Keep {value.name}
            </button>
          )}
        </>
      ) : (
        <div className="picker-current">
          <span className="picker-name" aria-live="polite">
            {value?.name ?? (options ? `No ${nouns} to choose from` : `Loading ${nouns}…`)}
          </span>
          {tag && <span className="picker-tag">{tag}</span>}
          {value && (
            <button
              ref={change}
              type="button"
              className="text"
              onClick={() => setOpen(true)}
              disabled={!options?.length}
              aria-label={`Change ${label.toLowerCase()}`}
            >
              Change
            </button>
          )}
        </div>
      )}
      {hint && <span className="field-hint">{hint}</span>}
    </div>
  );
}
