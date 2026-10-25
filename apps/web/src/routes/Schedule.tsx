// Class schedule: upload → confirm → a week grid with free time, and a list by term.
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router";
import type {
  ClassMode,
  FreeBlocksResponse,
  Profile,
  ScheduledClass,
  ScheduledPlanCourse,
  ScheduleTerm,
  Weekday,
} from "@hindsight/contracts";
import { api, ApiError } from "../lib/api";
import { loadSession } from "../lib/session";
import { plural } from "../lib/format";
import { Icon } from "../components/Icons";
import { Masthead, Section, StatusMark } from "../components/Paper";
import "../styles/schedule.css";

const DAYS: Weekday[] = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const DAY_LETTER: Record<Weekday, string> = {
  Mon: "M",
  Tue: "T",
  Wed: "W",
  Thu: "Th",
  Fri: "F",
  Sat: "Sa",
  Sun: "Su",
};
const DAY_NAME: Record<Weekday, string> = {
  Mon: "Monday",
  Tue: "Tuesday",
  Wed: "Wednesday",
  Thu: "Thursday",
  Fri: "Friday",
  Sat: "Saturday",
  Sun: "Sunday",
};
const MODES: [ClassMode, string][] = [
  ["in_person", "In person"],
  ["online", "Online"],
  ["hybrid", "Hybrid"],
  ["asynchronous", "Asynchronous"],
];
const MODE_LABEL = Object.fromEntries(MODES) as Record<ClassMode, string>;

// Why a parsed row needs a second look, in the student's words.
const FLAG_TEXT: Record<string, string> = {
  unclear_scan: "Hard to read. Check every field.",
  term_unparsed: "Term not recognized.",
  days_unparsed: "Days not recognized.",
  time_unparsed: "Times not recognized.",
  time_assumed: "AM or PM wasn't printed. Check the times.",
  dates_unparsed: "Class dates not recognized.",
  no_meeting_time: "No meeting time printed, so it won't show on the week grid.",
};

// The week grid runs 7 AM–10 PM, as the free-time API does.
const GRID_START = 7 * 60;
const GRID_END = 22 * 60;
const HOUR_PX = 64;

const errorText = (e: unknown, saving = false) => {
  if (e instanceof ApiError && e.status >= 502)
    return saving
      ? "We couldn't save your schedule. Try again in a minute."
      : "Your schedule isn't available right now. Try again in a minute.";
  return e instanceof Error ? e.message : "Something went wrong";
};

// ---- Dates and times ----

const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const fromIso = (s: string) => {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y!, m! - 1, d!);
};
const addDays = (d: Date, n: number) =>
  new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
const mondayOf = (d: Date) => addDays(d, -((d.getDay() + 6) % 7));
const minutes = (hhmm: string) => {
  const [h, m] = hhmm.split(":").map(Number);
  return h! * 60 + m!;
};
function clock(hhmm: string, meridiem = true): string {
  const m = minutes(hhmm);
  const h = Math.floor(m / 60);
  const text = `${h % 12 || 12}:${String(m % 60).padStart(2, "0")}`;
  return meridiem ? `${text} ${h < 12 ? "AM" : "PM"}` : text;
}
// "9:30–11:20 AM", or "11:30 AM–1:20 PM" when the halves differ.
function span(start: string, end: string): string {
  const same = minutes(start) < 720 === minutes(end) < 720;
  return `${clock(start, !same)}–${clock(end)}`;
}
function duration(mins: number): string {
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return [h && `${h} hr`, m && `${m} min`].filter(Boolean).join(" ");
}
const monthDay = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
});
const longDay = new Intl.DateTimeFormat("en-US", {
  weekday: "long",
  month: "long",
  day: "numeric",
});

const meets = (c: ScheduledClass, day: Date) =>
  c.mode !== "asynchronous" &&
  !!c.start_time &&
  !!c.end_time &&
  c.days.includes(DAYS[(day.getDay() + 6) % 7]!) &&
  (!c.start_date || iso(day) >= c.start_date) &&
  (!c.end_date || iso(day) <= c.end_date);

const onGrid = (c: ScheduledClass) =>
  c.mode !== "asynchronous" && !!c.start_time && c.days.length > 0;

function daysText(days: Weekday[]): string {
  return days.map((d) => DAY_LETTER[d]).join("");
}

// The term that's running this week, else the next to start, else the latest.
function defaultTerm(rows: ScheduledClass[], terms: ScheduleTerm[], today: string): string | undefined {
  const dated = (t: string) =>
    rows.filter((r) => r.term === t && r.start_date && r.end_date);
  const running = terms.find((t) =>
    dated(t.term).some((r) => r.start_date! <= today && today <= r.end_date!),
  );
  if (running) return running.term;
  const next = terms.find((t) => dated(t.term).some((r) => r.start_date! > today));
  return next?.term ?? terms[terms.length - 1]?.term;
}

// This week if the term is running, else the term's first week.
function defaultWeek(rows: ScheduledClass[], term: string | undefined, today: Date): Date {
  const starts = rows
    .filter((r) => r.term === term && r.start_date && r.end_date)
    .map((r) => [r.start_date!, r.end_date!] as const);
  const now = iso(today);
  if (starts.length && !starts.some(([s, e]) => s <= now && now <= e)) {
    const first = starts.map(([s]) => s).sort()[0]!;
    if (first > now) return mondayOf(fromIso(first));
  }
  return mondayOf(today);
}

// ---- Page ----

type Mode = "loading" | "upload" | "confirm" | "saved";
type Row = { key: number; cls: ScheduledClass };

export function Schedule() {
  const { profile } = loadSession();
  if (!profile)
    return (
      <>
        <Masthead sketch="pencil">Schedule</Masthead>
        <Section label="Transcript" title="Add Your Classes" last>
          <p className="lede">Set up your profile to add your class schedule.</p>
          <p className="actions schedule-gap">
            <Link className="button primary" to="/onboarding">
              Set up your profile
            </Link>
          </p>
        </Section>
      </>
    );
  return <SchedulePage profile={profile} />;
}

function SchedulePage({ profile }: { profile: Profile }) {
  const [mode, setMode] = useState<Mode>("loading");
  const [saved, setSaved] = useState<ScheduledClass[]>([]);
  const [terms, setTerms] = useState<ScheduleTerm[]>([]);
  const [draft, setDraft] = useState<Row[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api.schedule(profile.id).then(
      (res) => {
        if (!live) return;
        setSaved(res.rows);
        setTerms(res.terms ?? []);
        setMode(res.rows.length ? "saved" : "upload");
      },
      (e) => {
        if (!live) return;
        setLoadError(errorText(e));
        setMode("upload");
      },
    );
    return () => {
      live = false;
    };
  }, [profile.id]);

  const first = useRef(true);
  useEffect(() => {
    if (mode === "loading") return;
    if (first.current) {
      first.current = false;
      return;
    }
    const main = document.getElementById("main-content");
    main?.focus({ preventScroll: true });
    window.scrollTo({ top: 0 });
  }, [mode]);

  const edit = (rows: ScheduledClass[]) => {
    setDraft(rows.map((cls, key) => ({ key, cls })));
    setMode("confirm");
  };

  return (
    <div className="schedule">
      <Masthead sketch="pencil">Schedule</Masthead>
      {mode === "loading" && (
        <Section label="This week" title="This Week" last>
          <p className="lede" role="status">
            Loading your schedule…
          </p>
        </Section>
      )}
      {mode === "upload" && (
        <UploadStep
          profile={profile}
          loadError={loadError}
          onParsed={edit}
          onCancel={saved.length ? () => setMode("saved") : undefined}
        />
      )}
      {mode === "confirm" && (
        <ConfirmStep
          profile={profile}
          rows={draft}
          setRows={setDraft}
          onSaved={(rows, t) => {
            setSaved(rows);
            setTerms(t);
            setMode("saved");
          }}
          onCancel={() => setMode(saved.length ? "saved" : "upload")}
        />
      )}
      {mode === "saved" && (
        <SavedSchedule
          profile={profile}
          rows={saved}
          terms={terms}
          onUpload={() => setMode("upload")}
          onEdit={() => edit(saved)}
        />
      )}
    </div>
  );
}

// ---- Upload ----

function UploadStep({
  profile,
  loadError,
  onParsed,
  onCancel,
}: {
  profile: Profile;
  loadError: string | null;
  onParsed: (rows: ScheduledClass[]) => void;
  onCancel?: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function upload(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const { rows } = await api.uploadSchedule(profile.id, file);
      onParsed(rows);
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  }

  return (
    <Section label="Transcript" title="Upload Your Schedule" last>
      <form className="form" onSubmit={upload}>
        <p className="lede">
          Upload your {profile.sending_institution_name ?? "college"} class
          schedule as a PDF or screenshot. You’ll check each class before it’s
          saved.
        </p>
        {loadError && <p className="error">{loadError}</p>}
        <label className="field">
          <span className="upload-symbol">
            <Icon name="upload" size={28} />
          </span>
          <span className="label">Class schedule · PDF or image</span>
          <input
            type="file"
            accept="application/pdf,image/png,image/jpeg,image/webp"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>
        {error && <p className="error">{error}</p>}
        <div className="actions">
          <button className="primary" type="submit" disabled={!file || busy}>
            {busy ? "Reading schedule…" : "Upload"}
          </button>
          {onCancel && (
            <button className="text" type="button" onClick={onCancel} disabled={busy}>
              Keep my saved schedule
            </button>
          )}
        </div>
      </form>
    </Section>
  );
}

// ---- Confirm ----

const EMPTY_CLASS: ScheduledClass = {
  term: "",
  course: "",
  title: "",
  mode: "in_person",
  days: [],
  confirmed: false,
};

function ConfirmStep({
  profile,
  rows,
  setRows,
  onSaved,
  onCancel,
}: {
  profile: Profile;
  rows: Row[];
  setRows: (fn: (rows: Row[]) => Row[]) => void;
  onSaved: (rows: ScheduledClass[], terms: ScheduleTerm[]) => void;
  onCancel: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const update = (key: number, patch: Partial<ScheduledClass>) =>
    setRows((rs) =>
      rs.map((r) => (r.key === key ? { ...r, cls: { ...r.cls, ...patch } } : r)),
    );
  const remove = (key: number) => setRows((rs) => rs.filter((r) => r.key !== key));
  const add = () =>
    setRows((rs) => [
      ...rs,
      {
        key: Math.max(-1, ...rs.map((r) => r.key)) + 1,
        cls: { ...EMPTY_CLASS, term: rs[rs.length - 1]?.cls.term ?? "" },
      },
    ]);
  // Empty inputs are omitted, not sent as "".
  const optional = (value: string) => value.trim() || undefined;
  const toggleDay = (key: number, days: Weekday[], day: Weekday) =>
    update(key, {
      days: DAYS.filter((d) => (d === day ? !days.includes(d) : days.includes(d))),
    });

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const res = await api.saveSchedule(
        profile.id,
        rows.map((r) => r.cls),
      );
      onSaved(res.rows, res.terms ?? []);
    } catch (e) {
      setError(errorText(e, true));
      setBusy(false);
    }
  }

  const flagged = rows.filter((r) => r.cls.flags?.length).length;

  return (
    <Section label="Confirm courses" title="Confirm Your Classes" last>
      <div className="form">
        {flagged > 0 && (
          <p className="lede-sub schedule-flag-summary">
            {flagged} {plural(flagged, "class", "classes")} need a second look.
          </p>
        )}
        <div className="table-scroll">
          <table className="paper confirm schedule-confirm">
            <caption>Classes from your schedule</caption>
            <thead>
              <tr>
                <th>Course</th>
                <th>Title</th>
                <th>Term</th>
                <th>Days</th>
                <th>Start</th>
                <th>End</th>
                <th>Mode</th>
                <th>Location</th>
                <th>Units</th>
                <th>Section</th>
                <th>Professor</th>
                <th>CRN</th>
                <th aria-label="Remove" />
              </tr>
            </thead>
            <tbody>
              {rows.map(({ key, cls: c }) => {
                const timed = c.mode !== "asynchronous";
                return (
                  <tr key={key} className={c.flags?.length ? "flagged" : undefined}>
                    <td data-label="Course">
                      <input
                        aria-label="Course"
                        value={c.course}
                        onChange={(e) => update(key, { course: e.target.value })}
                      />
                      {c.flags?.map((f) => (
                        <span className="schedule-flag" key={f}>
                          {FLAG_TEXT[f] ?? "Check this row."}
                        </span>
                      ))}
                    </td>
                    <td data-label="Title">
                      <textarea
                        aria-label="Title"
                        rows={1}
                        value={c.title}
                        onChange={(e) =>
                          update(key, { title: e.target.value.replace(/\s*\n\s*/g, " ") })
                        }
                      />
                    </td>
                    <td data-label="Term">
                      <input
                        aria-label="Term"
                        value={c.term}
                        onChange={(e) => update(key, { term: e.target.value })}
                      />
                    </td>
                    <td data-label="Days">
                      <div className="day-toggles" role="group" aria-label={`Days for ${c.course || "this class"}`}>
                        {DAYS.map((d) => (
                          <button
                            key={d}
                            type="button"
                            aria-pressed={c.days.includes(d)}
                            aria-label={DAY_NAME[d]}
                            disabled={!timed}
                            onClick={() => toggleDay(key, c.days, d)}
                          >
                            {DAY_LETTER[d]}
                          </button>
                        ))}
                      </div>
                    </td>
                    <td data-label="Start">
                      <input
                        aria-label="Start time"
                        type="time"
                        disabled={!timed}
                        value={c.start_time ?? ""}
                        onChange={(e) => update(key, { start_time: optional(e.target.value) })}
                      />
                    </td>
                    <td data-label="End">
                      <input
                        aria-label="End time"
                        type="time"
                        disabled={!timed}
                        value={c.end_time ?? ""}
                        onChange={(e) => update(key, { end_time: optional(e.target.value) })}
                      />
                    </td>
                    <td data-label="Mode">
                      <select
                        aria-label="Mode"
                        value={c.mode}
                        onChange={(e) => update(key, { mode: e.target.value as ClassMode })}
                      >
                        {MODES.map(([value, label]) => (
                          <option key={value} value={value}>
                            {label}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td data-label="Location">
                      <input
                        aria-label="Location"
                        value={c.location ?? ""}
                        onChange={(e) => update(key, { location: optional(e.target.value) })}
                      />
                    </td>
                    <td data-label="Units">
                      <input
                        aria-label="Units"
                        type="number"
                        min={0}
                        step={0.5}
                        value={c.units ?? ""}
                        onChange={(e) =>
                          update(key, {
                            units: e.target.value === "" ? undefined : Number(e.target.value),
                          })
                        }
                      />
                    </td>
                    <td data-label="Section">
                      <input
                        aria-label="Section"
                        value={c.section ?? ""}
                        onChange={(e) => update(key, { section: optional(e.target.value) })}
                      />
                    </td>
                    <td data-label="Professor">
                      <input
                        aria-label="Professor"
                        value={c.professor ?? ""}
                        onChange={(e) => update(key, { professor: optional(e.target.value) })}
                      />
                    </td>
                    <td data-label="CRN">
                      <input
                        aria-label="CRN"
                        value={c.crn ?? ""}
                        onChange={(e) => update(key, { crn: optional(e.target.value) })}
                      />
                    </td>
                    <td>
                      <button
                        type="button"
                        onClick={() => remove(key)}
                        aria-label={`Remove ${c.course || "this class"}`}
                      >
                        ✕
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {error && <p className="error">{error}</p>}
        <div className="actions">
          <button type="button" onClick={add}>
            + Add class
          </button>
          <button
            className="primary"
            type="button"
            onClick={() => void save()}
            disabled={busy || rows.length === 0}
          >
            {busy ? "Saving…" : "Confirm & save schedule"}
          </button>
          <button className="text" type="button" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
        </div>
      </div>
    </Section>
  );
}

// ---- Saved: week grid and list ----

function SavedSchedule({
  profile,
  rows,
  terms,
  onUpload,
  onEdit,
}: {
  profile: Profile;
  rows: ScheduledClass[];
  terms: ScheduleTerm[];
  onUpload: () => void;
  onEdit: () => void;
}) {
  const today = useMemo(() => new Date(), []);
  const [view, setView] = useState<"week" | "list">("week");
  const [term, setTerm] = useState(() => defaultTerm(rows, terms, iso(today)));
  const [week, setWeek] = useState(() => defaultWeek(rows, term, today));
  const [planned, setPlanned] = useState<ScheduledPlanCourse[]>([]);

  // Which saved classes are on the plan; the marks are extra, so a failure just leaves them off.
  useEffect(() => {
    let live = true;
    api.scheduledPlan(profile.id).then(
      (res) => live && setPlanned(res.courses),
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, [profile.id, rows]);

  const chooseTerm = (t: string) => {
    setTerm(t);
    setWeek(defaultWeek(rows, t, today));
  };

  return (
    <>
      <Section label="This week" title={view === "week" ? "Your Week" : "Classes by Term"}>
        <div className="schedule-toolbar">
          <div className="credit-filters" role="group" aria-label="View">
            {(
              [
                ["week", "Week"],
                ["list", "List"],
              ] as const
            ).map(([value, label]) => (
              <button
                type="button"
                key={value}
                aria-pressed={view === value}
                onClick={() => setView(value)}
              >
                {label}
              </button>
            ))}
          </div>
          {view === "week" && terms.length > 1 && (
            <label className="schedule-term">
              <span className="schedule-sr">Term</span>
              <select value={term} onChange={(e) => chooseTerm(e.target.value)}>
                {terms.map((t) => (
                  <option key={t.term} value={t.term}>
                    {t.term}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
        {view === "week" ? (
          <WeekView
            profile={profile}
            rows={rows.filter((r) => !term || r.term === term)}
            term={term}
            week={week}
            setWeek={setWeek}
          />
        ) : (
          <ListView rows={rows} terms={terms} planned={planned} />
        )}
      </Section>
      <Section label="Transcript" title="Update Your Schedule" last>
        <div className="actions">
          <button type="button" onClick={onEdit}>
            Edit classes
          </button>
          <button type="button" onClick={onUpload}>
            Upload a new schedule
          </button>
        </div>
        <p className="schedule-source">
          From the class schedule you uploaded and confirmed.
          {planned.length > 0 && (
            <>
              {" "}
              Plan marks compare it with <Link to="/plan">your plan</Link>.
            </>
          )}
        </p>
      </Section>
    </>
  );
}

function WeekView({
  profile,
  rows,
  term,
  week,
  setWeek,
}: {
  profile: Profile;
  rows: ScheduledClass[];
  term: string | undefined;
  week: Date;
  setWeek: (d: Date) => void;
}) {
  const [free, setFree] = useState<FreeBlocksResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const weekIso = iso(week);
  const request = useRef(0);

  useEffect(() => {
    const id = ++request.current;
    setError(null);
    api.freeBlocks(profile.id, weekIso, term).then(
      (res) => id === request.current && setFree(res),
      (e) => {
        if (id !== request.current) return;
        setFree(null);
        setError(errorText(e));
      },
    );
  }, [profile.id, weekIso, term]);

  const days = DAYS.map((d, i) => {
    const date = addDays(week, i);
    const classes = rows
      .filter((c) => meets(c, date))
      .sort((a, b) => minutes(a.start_time!) - minutes(b.start_time!));
    const blocks = free?.week === weekIso ? (free.days[i]?.blocks ?? []) : [];
    return { day: d, date, classes, blocks };
  });
  const offGrid = rows.filter((c) => !onGrid(c));
  const weekLabel = `Week of ${monthDay.format(week)}`;

  return (
    <div className="sched-week">
      <div className="sched-week-nav">
        <button type="button" onClick={() => setWeek(addDays(week, -7))} aria-label="Previous week">
          <span aria-hidden="true">←</span>
        </button>
        <h3 aria-live="polite">{weekLabel}</h3>
        <button type="button" onClick={() => setWeek(addDays(week, 7))} aria-label="Next week">
          <span aria-hidden="true">→</span>
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="sched-week-grid" role="group" aria-label={weekLabel}>
        <div className="sched-week-hours" aria-hidden="true">
          {Array.from({ length: (GRID_END - GRID_START) / 60 + 1 }, (_, i) => {
            const h = GRID_START / 60 + i;
            return (
              <span key={h} style={{ top: i * HOUR_PX }}>
                {h % 12 || 12} {h < 12 ? "AM" : "PM"}
              </span>
            );
          })}
        </div>
        {days.map(({ day, date, classes, blocks }) => (
          <div className="sched-week-day" key={day} role="group" aria-label={longDay.format(date)}>
            <div className="sched-week-day-head" aria-hidden="true">
              <strong>{day}</strong> {date.getDate()}
            </div>
            <div className="sched-week-day-body" style={{ height: ((GRID_END - GRID_START) / 60) * HOUR_PX }}>
              {blocks.map((b) => (
                <div
                  key={b.start}
                  className="sched-week-free"
                  style={place(b.start, b.end)}
                  title={`Free ${span(b.start, b.end)} (${duration(b.minutes)})`}
                  aria-label={`Free ${span(b.start, b.end)}`}
                >
                  {b.minutes >= 45 && <span>Free</span>}
                </div>
              ))}
              {lanes(classes).map(({ cls, lane, of }) => (
                <div
                  key={`${cls.course}-${cls.crn}-${cls.start_time}`}
                  className={`sched-week-class ${cls.mode}${
                    minutes(cls.end_time!) - minutes(cls.start_time!) < 75 ? " short" : ""
                  }`}
                  style={{
                    ...place(cls.start_time!, cls.end_time!),
                    left: `calc(${(lane / of) * 100}% + 2px)`,
                    width: `calc(${100 / of}% - 4px)`,
                  }}
                >
                  <strong>{cls.course}</strong>
                  <span>{span(cls.start_time!, cls.end_time!)}</span>
                  {cls.location && <span>{cls.location}</span>}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
      <ol className="sched-week-agenda" aria-label={weekLabel}>
        {days.map(({ day, date, classes, blocks }) => (
          <li key={day}>
            <h4>{longDay.format(date)}</h4>
            <ul>
              {agenda(classes, blocks).map((item) =>
                item.kind === "class" ? (
                  <li key={`c-${item.cls.course}-${item.cls.start_time}`} className="agenda-class">
                    <strong>{item.cls.course}</strong>
                    <span>
                      {span(item.cls.start_time!, item.cls.end_time!)}
                      {item.cls.location && ` · ${item.cls.location}`}
                    </span>
                  </li>
                ) : (
                  <li key={`f-${item.start}`} className="agenda-free">
                    Free {span(item.start, item.end)}
                  </li>
                ),
              )}
              {!classes.length && !blocks.length && <li className="agenda-free">No classes</li>}
            </ul>
          </li>
        ))}
      </ol>
      {rows.some((c) => onGrid(c) && !c.start_date) && (
        <p className="sched-week-offgrid">
          Your schedule doesn’t list class dates, so these classes show in every week.
        </p>
      )}
      {offGrid.length > 0 && (
        <p className="sched-week-offgrid">
          <strong>Not on the grid:</strong>{" "}
          {offGrid
            .map((c) => `${c.course} (${c.mode === "asynchronous" ? "asynchronous" : "no meeting time"})`)
            .join(", ")}
        </p>
      )}
    </div>
  );
}

function place(start: string, end: string) {
  const s = Math.max(minutes(start), GRID_START);
  const e = Math.min(minutes(end), GRID_END);
  return {
    top: ((s - GRID_START) / 60) * HOUR_PX,
    height: Math.max(((e - s) / 60) * HOUR_PX, 18),
  };
}

// Overlapping classes share the column side by side.
function lanes(classes: ScheduledClass[]) {
  const placed: { cls: ScheduledClass; lane: number; of: number }[] = [];
  let group: typeof placed = [];
  let groupEnd = -1;
  const close = () => {
    const of = Math.max(1, ...group.map((p) => p.lane + 1));
    group.forEach((p) => (p.of = of));
    group = [];
  };
  for (const cls of classes) {
    const s = minutes(cls.start_time!);
    if (s >= groupEnd) close();
    const busy = new Set(group.filter((p) => minutes(p.cls.end_time!) > s).map((p) => p.lane));
    let lane = 0;
    while (busy.has(lane)) lane++;
    const item = { cls, lane, of: 1 };
    group.push(item);
    placed.push(item);
    groupEnd = Math.max(groupEnd, minutes(cls.end_time!));
  }
  close();
  return placed;
}

type AgendaItem =
  | { kind: "class"; cls: ScheduledClass; at: number }
  | { kind: "free"; start: string; end: string; at: number };

function agenda(classes: ScheduledClass[], blocks: { start: string; end: string }[]): AgendaItem[] {
  return [
    ...classes.map((cls) => ({ kind: "class" as const, cls, at: minutes(cls.start_time!) })),
    ...blocks.map((b) => ({ kind: "free" as const, ...b, at: minutes(b.start) })),
  ].sort((a, b) => a.at - b.at);
}

// A class with a lecture and a lab is two rows; the list shows it once with both meetings.
function grouped(rows: ScheduledClass[]) {
  const classes = new Map<string, ScheduledClass[]>();
  for (const r of rows) {
    const id = r.crn ? `${r.term}|${r.crn}` : `${r.term}|${r.course}|${r.section ?? ""}`;
    classes.set(id, [...(classes.get(id) ?? []), r]);
  }
  return [...classes.values()];
}

function meetingText(c: ScheduledClass): string {
  if (c.mode === "asynchronous") return "Asynchronous";
  if (!c.start_time || !c.end_time || !c.days.length) return "No meeting time";
  return `${daysText(c.days)} ${span(c.start_time, c.end_time)}`;
}

const courseKey = (code: string) => {
  const m = /^\s*([A-Za-z&]+)[\s\-_.]*(.+?)\s*$/.exec(code);
  if (!m) return code.toUpperCase().replace(/[^A-Z0-9]/g, "");
  const number = m[2]!.toUpperCase().replace(/[^A-Z0-9]/g, "").replace(/^[A-Z]?0+(\d)/, "$1");
  return m[1]!.toUpperCase() + number;
};

function ListView({
  rows,
  terms,
  planned,
}: {
  rows: ScheduledClass[];
  terms: ScheduleTerm[];
  planned: ScheduledPlanCourse[];
}) {
  const plannedBy = new Map(planned.map((p) => [courseKey(p.code), p]));
  return (
    <div className="terms">
      {terms.map((t) => (
        <div className="term" key={t.term}>
          <h3 className="term-label">
            {t.term}
            <span>
              {t.units} {plural(t.units, "unit")} · {t.classes} {plural(t.classes, "class", "classes")}
            </span>
          </h3>
          <table className="paper schedule-list">
            <caption className="schedule-sr">Classes in {t.term}</caption>
            <thead>
              <tr>
                <th>Course</th>
                <th>Meets</th>
                <th>Location</th>
                <th>Professor</th>
                <th className="num">Units</th>
              </tr>
            </thead>
            <tbody>
              {grouped(rows.filter((r) => r.term === t.term)).map((meetings) => {
                const c = meetings[0]!;
                const plan = plannedBy.get(courseKey(c.course));
                return (
                  <tr key={`${c.crn}-${c.course}-${c.section}`}>
                    <td data-label="Course">
                      <strong>{c.course}</strong>
                      {c.section && <span className="schedule-muted"> · {c.section}</span>}
                      <span className="schedule-title">{c.title}</span>
                      {plan && (
                        <StatusMark tone="ok">
                          On your plan{plan.planned_term !== c.term ? ` for ${plan.planned_term}` : ""}
                        </StatusMark>
                      )}
                    </td>
                    <td data-label="Meets">
                      {meetings.map((m, i) => (
                        <span className="schedule-line" key={i}>
                          {meetingText(m)}
                        </span>
                      ))}
                      {c.mode !== "asynchronous" && (
                        <span className="schedule-muted">{MODE_LABEL[c.mode]}</span>
                      )}
                    </td>
                    <td data-label="Location">
                      {meetings.map((m, i) => (
                        <span className="schedule-line" key={i}>
                          {m.location ?? "—"}
                        </span>
                      ))}
                    </td>
                    <td data-label="Professor">{c.professor ?? "—"}</td>
                    <td data-label="Units" className="num">
                      {c.units ?? "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr>
                <th scope="row" colSpan={4}>
                  Total
                </th>
                <td className="num">{t.units}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      ))}
    </div>
  );
}
