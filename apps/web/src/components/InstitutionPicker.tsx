// A searchable pick from one of ASSIST's institution lists, as a combobox: one text field that shows the
// chosen name, and a list that opens on focus or typing and closes again once something is picked.
// Nothing is picked by default. `locked` (with the reason as its text) keeps it disabled until an earlier
// choice is made.
import { useEffect, useState, type KeyboardEvent, type ReactNode } from "react";
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
  const [active, setActive] = useState(0);
  const words = fold(query).split(/[\s,]+/).filter(Boolean);
  const shown = (options ?? []).filter((o) => words.every((w) => haystack(o).includes(w)));
  const listId = `${id}-list`;
  const optionId = (o: AssistInstitution) => `${id}-option-${o.id}`;
  const current = open ? shown[active] : undefined;

  // Keep the highlighted option in view while arrowing through a long list.
  useEffect(() => {
    if (current) document.getElementById(optionId(current))?.scrollIntoView({ block: "nearest" });
  });

  function close() {
    setOpen(false);
    setQuery("");
  }

  function pick(o: AssistInstitution) {
    onChange(o);
    close();
  }

  function key(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!open) setOpen(true);
      else setActive((a) => Math.min(a + 1, shown.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter" && open) {
      e.preventDefault(); // not the form's submit
      if (current) pick(current);
    } else if (e.key === "Escape" && open) {
      e.preventDefault();
      close();
    }
  }

  const tag = value && badge?.(value);
  const placeholder =
    locked ??
    (!options
      ? `Loading ${nouns}…`
      : options.length === 0
        ? `No ${nouns} to choose from`
        : (value?.name ?? "Search by name"));
  return (
    <div className="field picker">
      <span className="picker-head">
        <label className="label" htmlFor={`${id}-input`}>
          {label}
        </label>
        {tag && <span className="picker-tag">{tag}</span>}
      </span>
      <input
        id={`${id}-input`}
        type="text"
        role="combobox"
        autoComplete="off"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={current ? optionId(current) : undefined}
        value={open ? query : (value?.name ?? "")}
        placeholder={placeholder}
        disabled={!!locked || !options?.length}
        onFocus={() => {
          setOpen(true);
          setActive(0);
        }}
        onClick={() => setOpen(true)}
        onBlur={close}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
          setActive(0);
        }}
        onKeyDown={key}
      />
      {open && (
        <ul className="choices scroll picker-list" id={listId} role="listbox" aria-label={label}>
          {shown.map((o) => {
            const b = badge?.(o);
            return (
              <li
                key={o.id}
                id={optionId(o)}
                role="option"
                aria-selected={o.id === value?.id}
                className={o === current ? "active" : undefined}
              >
                {/* mousedown would blur the field and close the list before the click lands */}
                <button
                  type="button"
                  tabIndex={-1}
                  className="picker-option"
                  onMouseDown={(e) => e.preventDefault()}
                  onMouseEnter={() => setActive(shown.indexOf(o))}
                  onClick={() => pick(o)}
                >
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
      )}
      {hint && <span className="field-hint">{hint}</span>}
    </div>
  );
}
