import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import type { AssistMajor, Course, Profile } from "@hindsight/contracts";
import { Icon } from "../components/Icons";
import { Masthead, Note, Section } from "../components/Paper";
import { api } from "../lib/api";
import {
  ASSIST_YEAR_2026_27,
  DE_ANZA_ID,
  DE_ANZA_NAME,
  SJSU_ID,
  SJSU_NAME,
} from "../lib/config";
import { saveSession } from "../lib/session";

type Step = "profile" | "upload" | "confirm";
type Row = { key: number; course: Course };

const STEPS: {
  id: Step;
  label: string;
  title: string;
  note: { lead: string; body: string };
}[] = [
  {
    id: "profile",
    label: "About you",
    title: "A little about you",
    note: {
      lead: "Why we ask.",
      body: "Majors shape your degree plan. Goals and interests help us find opportunities for you.",
    },
  },
  {
    id: "upload",
    label: "Transcript",
    title: "Add your transcript",
    note: {
      lead: "What happens next.",
      body: "Your file isn't stored. Only the courses you review and confirm are saved.",
    },
  },
  {
    id: "confirm",
    label: "Confirm courses",
    title: "Review your courses",
    note: {
      lead: "Only what you confirm counts.",
      body: "Check course names, grades and terms before matching your credits.",
    },
  },
];

const GOALS_MIN = 8;

const errorText = (e: unknown) =>
  e instanceof Error ? e.message : "Something went wrong";

export function Onboarding() {
  const [step, setStep] = useState<Step>("profile");
  const [profile, setProfile] = useState<Profile | null>(null);
  const [rows, setRows] = useState<Row[]>([]);

  const index = STEPS.findIndex((s) => s.id === step);
  const current = STEPS[index]!;

  return (
    <div className="intake">
      <Masthead
        kicker="YOUR NEXT CHAPTER"
        byline={`${DE_ANZA_NAME} → ${SJSU_NAME}`}
        sketch={
          step === "upload" ? "pencil" : step === "confirm" ? "cap" : "books"
        }
      >
        {step === "profile" ? (
          <>
            A clearer path
            <br />
            starts here.
          </>
        ) : step === "upload" ? (
          <>
            Bring what
            <br />
            you’ve learned.
          </>
        ) : (
          <>
            Make every
            <br />
            course count.
          </>
        )}
      </Masthead>
      <Section
        num={index + 1}
        label={current.label}
        title={current.title}
        last
        notes={
          step !== "profile" ? (
            <Note lead={current.note.lead}>{current.note.body}</Note>
          ) : undefined
        }
      >
        <ol className="steps" aria-label="Steps">
          {STEPS.map((s, i) => (
            <li
              key={s.id}
              aria-current={s.id === step ? "step" : undefined}
              className={i < index ? "done" : undefined}
            >
              <span className="step-number">
                {i < index ? <Icon name="check" size={12} /> : i + 1}
              </span>
              {s.label}
            </li>
          ))}
        </ol>

        {step === "profile" && (
          <ProfileStep
            onDone={(p) => {
              setProfile(p);
              saveSession({
                profile: p,
                courses: undefined,
                matches: undefined,
              });
              setStep("upload");
            }}
          />
        )}
        {step === "upload" && profile && (
          <UploadStep
            profile={profile}
            onDone={(courses) => {
              setRows(courses.map((course, i) => ({ key: i, course })));
              setStep("confirm");
            }}
          />
        )}
        {step === "confirm" && profile && (
          <ConfirmStep profile={profile} rows={rows} setRows={setRows} />
        )}
      </Section>
    </div>
  );
}

/**
 * Saves the confirmed courses (none is fine), matches every major, and opens Degree.
 * With no courses every requirement comes back Missing, which is the honest picture for a freshman.
 */
function useMatchAndOpenDegree(profile: Profile) {
  const navigate = useNavigate();
  return async (courses: Course[]) => {
    await api.confirmCourses(profile.id, courses);
    const matches = await Promise.all(
      profile.majors.map((m) => api.match(profile.id, m)),
    );
    saveSession({ profile, courses, matches });
    navigate("/degree", { state: { matches } });
  };
}

function ProfileStep({ onDone }: { onDone: (p: Profile) => void }) {
  const [name, setName] = useState("");
  const [majors, setMajors] = useState<string[]>([]);
  const [goals, setGoals] = useState("");
  const [interests, setInterests] = useState("");
  const [options, setOptions] = useState<AssistMajor[]>([]);
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .assistMajors(DE_ANZA_ID, SJSU_ID, ASSIST_YEAR_2026_27)
      .then((r) =>
        setOptions(
          [...r.majors].sort((a, b) => a.label.localeCompare(b.label)),
        ),
      )
      .catch((e) => setError(`Couldn't load majors: ${errorText(e)}`));
  }, []);

  // ASSIST lists ~180 majors: keep them alphabetical and narrow as you type; picks show as chips.
  const needle = filter.trim().toLowerCase();
  const shown = options.filter((m) => m.label.toLowerCase().includes(needle));

  const toggleMajor = (label: string) =>
    setMajors((m) =>
      m.includes(label) ? m.filter((x) => x !== label) : [...m, label],
    );

  const goalsTooShort =
    goals.trim().length > 0 && goals.trim().length < GOALS_MIN;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (goalsTooShort) return;
    setBusy(true);
    setError(null);
    try {
      const { profile } = await api.createProfile({
        name: name.trim(),
        campus: "sjsu",
        sending_institution_id: DE_ANZA_ID,
        receiving_institution_id: SJSU_ID,
        majors,
        goals: goals.trim(),
        interests: interests
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      });
      onDone(profile);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="form" onSubmit={submit}>
      <label className="field">
        <span className="label">Name</span>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoComplete="name"
          placeholder="Your name"
          required
        />
      </label>
      <fieldset className="field">
        <legend>Majors</legend>
        <input
          type="search"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Search majors"
          aria-label="Filter majors"
        />
        {majors.length > 0 && (
          <div className="chips" aria-label="Selected majors">
            {majors.map((label) => (
              <button
                type="button"
                key={label}
                className="chip"
                aria-label={`Remove ${label}`}
                onClick={() => toggleMajor(label)}
              >
                {label} <span aria-hidden>×</span>
              </button>
            ))}
          </div>
        )}
        <div className="choices scroll">
          {options.length === 0 && !error && (
            <span className="muted">Loading majors…</span>
          )}
          {options.length > 0 && shown.length === 0 && (
            <span className="muted">No major matches “{filter}”.</span>
          )}
          {shown.map((m) => (
            <label key={m.key} className="choice">
              <input
                type="checkbox"
                checked={majors.includes(m.label)}
                onChange={() => toggleMajor(m.label)}
              />
              {m.label}
            </label>
          ))}
        </div>
      </fieldset>
      <label className="field">
        <span className="label">Goals (optional)</span>
        <textarea
          rows={2}
          value={goals}
          onChange={(e) => setGoals(e.target.value)}
          placeholder="Graduate by Spring 2028, find an internship…"
        />
        {goalsTooShort && (
          <span className="field-hint">
            Say a bit more, or leave this blank.
          </span>
        )}
      </label>
      <label className="field">
        <span className="label">Interests</span>
        <input
          value={interests}
          onChange={(e) => setInterests(e.target.value)}
          placeholder="Design, hackathons, finance"
        />
        <span className="field-hint">Separate with commas.</span>
      </label>
      {error && <p className="error">{error}</p>}
      <div className="actions">
        <button
          className="primary"
          type="submit"
          disabled={
            busy || !name.trim() || majors.length === 0 || goalsTooShort
          }
        >
          {busy ? (
            "Saving…"
          ) : (
            <>
              Continue <Icon name="arrow" size={16} />
            </>
          )}
        </button>
      </div>
    </form>
  );
}

function UploadStep({
  profile,
  onDone,
}: {
  profile: Profile;
  onDone: (courses: Course[]) => void;
}) {
  const matchAndOpenDegree = useMatchAndOpenDegree(profile);
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState<"reading" | "matching" | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The file parsed but held no courses (blank page, a resume…).
  const [empty, setEmpty] = useState(false);

  async function upload(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy("reading");
    setError(null);
    try {
      const { courses } = await api.uploadTranscript(profile.id, file);
      if (courses.length) onDone(courses);
      else setEmpty(true);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(null);
    }
  }

  async function continueWithoutCourses() {
    setBusy("matching");
    setError(null);
    try {
      await matchAndOpenDegree([]);
    } catch (e) {
      setError(errorText(e));
      setBusy(null);
    }
  }

  // Opens the file picker; picking a file brings back the Upload button.
  function tryAnother() {
    setFile(null);
    if (fileInput.current) {
      fileInput.current.value = "";
      fileInput.current.click();
    }
  }

  return (
    <form className="form" onSubmit={upload}>
      <p className="lede">
        Upload a PDF or photo. You’ll review the courses before we match your
        credits.
      </p>
      {empty && (
        <div className="state" role="alert">
          <h3>We didn't find any courses in this file.</h3>
          <p>
            It may be blank, unreadable, or not a transcript. Try another file,
            or continue without courses and every requirement will show as
            missing.
          </p>
        </div>
      )}
      <label className="field">
        <span className="upload-symbol">
          <Icon name="upload" size={28} />
        </span>
        <span className="label">Transcript · PDF or image</span>
        <input
          ref={fileInput}
          type="file"
          accept="application/pdf,image/*"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            setEmpty(false);
          }}
        />
      </label>
      {error && <p className="error">{error}</p>}
      <div className="actions">
        {empty ? (
          <>
            <button
              className="primary"
              type="button"
              onClick={tryAnother}
              disabled={!!busy}
            >
              Try another file
            </button>
            <button
              type="button"
              onClick={() => void continueWithoutCourses()}
              disabled={!!busy}
            >
              {busy === "matching" ? "Matching…" : "Continue without courses"}
            </button>
          </>
        ) : (
          <>
            <button
              className="primary"
              type="submit"
              disabled={!file || !!busy}
            >
              {busy === "reading" ? "Reading transcript…" : "Upload"}
            </button>
            <button
              className="text"
              type="button"
              onClick={() => void continueWithoutCourses()}
              disabled={!!busy}
            >
              {busy === "matching"
                ? "Matching…"
                : "I haven’t taken college courses yet"}
            </button>
          </>
        )}
      </div>
    </form>
  );
}

const EMPTY_COURSE: Course = {
  prefix: "",
  number: "",
  title: "",
  units: 0,
  grade: "",
  term: "",
  confirmed: false,
};

function ConfirmStep({
  profile,
  rows,
  setRows,
}: {
  profile: Profile;
  rows: Row[];
  setRows: (fn: (rows: Row[]) => Row[]) => void;
}) {
  const matchAndOpenDegree = useMatchAndOpenDegree(profile);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const update = (key: number, patch: Partial<Course>) =>
    setRows((rs) =>
      rs.map((r) =>
        r.key === key ? { ...r, course: { ...r.course, ...patch } } : r,
      ),
    );
  const remove = (key: number) =>
    setRows((rs) => rs.filter((r) => r.key !== key));
  const add = () =>
    setRows((rs) => [
      ...rs,
      {
        key: Math.max(-1, ...rs.map((r) => r.key)) + 1,
        course: { ...EMPTY_COURSE },
      },
    ]);

  async function confirmAndMatch() {
    setBusy(true);
    setError(null);
    try {
      await matchAndOpenDegree(rows.map((r) => r.course));
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  }

  const text = (key: number, field: keyof Course, value: string) =>
    update(key, { [field]: value });

  return (
    <div className="form">
      <div className="table-scroll">
        <table className="paper confirm">
          <caption>Courses from your transcript</caption>
          <thead>
            <tr>
              <th className="w-xs">Prefix</th>
              <th className="w-xs">Number</th>
              <th>Title</th>
              <th className="w-xs">Units</th>
              <th className="w-xs">Grade</th>
              <th className="w-sm">Term</th>
              <th aria-label="Remove" />
            </tr>
          </thead>
          <tbody>
            {rows.map(({ key, course: c }) => (
              <tr key={key}>
                <td data-label="Prefix">
                  <input
                    aria-label="Prefix"
                    value={c.prefix}
                    onChange={(e) => text(key, "prefix", e.target.value)}
                  />
                </td>
                <td data-label="Number">
                  <input
                    aria-label="Number"
                    value={c.number}
                    onChange={(e) => text(key, "number", e.target.value)}
                  />
                </td>
                <td data-label="Title">
                  <textarea
                    aria-label="Title"
                    rows={1}
                    value={c.title}
                    onChange={(e) =>
                      text(
                        key,
                        "title",
                        e.target.value.replace(/\s*\n\s*/g, " "),
                      )
                    }
                  />
                </td>
                <td data-label="Units">
                  <input
                    aria-label="Units"
                    type="number"
                    min={0}
                    step={0.5}
                    value={c.units}
                    onChange={(e) =>
                      update(key, { units: Number(e.target.value) || 0 })
                    }
                  />
                </td>
                <td data-label="Grade">
                  <input
                    aria-label="Grade"
                    value={c.grade}
                    onChange={(e) => text(key, "grade", e.target.value)}
                  />
                </td>
                <td data-label="Term">
                  <input
                    aria-label="Term"
                    value={c.term}
                    onChange={(e) => text(key, "term", e.target.value)}
                  />
                </td>
                <td>
                  <button
                    type="button"
                    onClick={() => remove(key)}
                    aria-label={`Remove ${c.prefix} ${c.number}`}
                  >
                    ✕
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="actions">
        <button type="button" onClick={add}>
          + Add course
        </button>
        <button
          className="primary"
          type="button"
          onClick={confirmAndMatch}
          disabled={busy || rows.length === 0}
        >
          {busy ? "Matching…" : "Confirm & match credits"}
        </button>
      </div>
    </div>
  );
}
