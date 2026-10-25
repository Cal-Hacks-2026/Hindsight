// A searchable pick from one of ASSIST's institution lists. Closed, it reads like the old
// transfer-path line (label over the chosen name); "Change" opens a filter box and the list.
import { useState, type KeyboardEvent, type ReactNode } from "react";
import type { AssistInstitution } from "@hindsight/contracts";
import { shortUniversity } from "../lib/format";

/** Case- and accent-insensitive: "san jose" finds "San José State University". */
const fold = (s: string) => s.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();

/** What a search matches: the name, plus its short form ("UCLA", "SJSU", "CSU East Bay"). */
const haystack = (i: AssistInstitution) => fold(`${i.name} ${shortUniversity(i.name)}`);

export function InstitutionPicker({
  id,
  label,
  noun,
  nouns,
  example,
  value,
  options,
  onChange,
  badge,
  hint,
}: {
  id: string;
  label: string;
  /** "community college" / "community colleges": for the placeholder and empty states. */
  noun: string;
  nouns: string;
  /** For the placeholder: "Foothill". */
  example: string;
  value?: AssistInstitution;
  /** undefined while loading. */
  options?: AssistInstitution[];
  onChange: (i: AssistInstitution) => void;
  badge?: (i: AssistInstitution) => string | undefined;
  hint?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const words = fold(query).split(/[\s,]+/).filter(Boolean);
  const shown = (options ?? []).filter((o) => words.every((w) => haystack(o).includes(w)));

  function pick(o: AssistInstitution) {
    onChange(o);
    setOpen(false);
    setQuery("");
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
  return (
    <div className="field picker">
      <span className="label" id={`${id}-label`}>
        {label}
      </span>
      {open ? (
        <>
          <input
            type="search"
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={key}
            placeholder={`Search ${options?.length ?? 0} ${nouns}, e.g. ${example}`}
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
          <button type="button" className="text picker-cancel" onClick={() => setOpen(false)}>
            Keep {value ? value.name : "the current choice"}
          </button>
        </>
      ) : (
        <div className="picker-current">
          <span className="picker-name" aria-live="polite">
            {value?.name ?? (options ? `Choose a ${noun}` : `Loading ${nouns}…`)}
          </span>
          {tag && <span className="picker-tag">{tag}</span>}
          <button
            type="button"
            className="text"
            onClick={() => setOpen(true)}
            disabled={!options?.length}
            aria-label={`Change ${label.toLowerCase()}`}
          >
            Change
          </button>
        </div>
      )}
      {hint && <span className="field-hint">{hint}</span>}
    </div>
  );
}
