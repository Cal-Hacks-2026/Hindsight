import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import type { AssistMajor, Course, Profile } from "@hindsight/contracts";
import { Masthead, Note, Section } from "../components/Paper";
import { api } from "../lib/api";
import { ASSIST_YEAR_2026_27, DE_ANZA_ID, DE_ANZA_NAME, SJSU_ID, SJSU_NAME } from "../lib/config";
import { saveSession } from "../lib/session";

type Step = "profile" | "upload" | "confirm";
type Row = { key: number; course: Course };

const STEPS: { id: Step; label: string; title: string; note: { lead: string; body: string } }[] = [
  {
    id: "profile",
    label: "About you",
    title: "Who this report is for.",
    note: {
      lead: "Why we ask.",
      body: "Your majors decide which ASSIST agreements and catalog requirements are checked. Goals and interests rank your Radar.",
    },
  },
  {
    id: "upload",
    label: "Transcript",
    title: "Your transcript, as you have it.",
    note: {
      lead: "What happens next.",
      body: "Claude reads the courses off the page. Nothing is matched until you've checked every row.",
    },
  },
  {
    id: "confirm",
    label: "Confirm courses",
    title: "Check every row against your transcript.",
    note: {
      lead: "Only what you confirm counts.",
      body: "Matching against ASSIST is deterministic and uses exactly these rows. Fix anything we misread.",
    },
  },
];

const GOALS_MIN = 8;

const errorText = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");

export function Onboarding() {
  const [step, setStep] = useState<Step>("profile");
  const [profile, setProfile] = useState<Profile | null>(null);
  const [rows, setRows] = useState<Row[]>([]);

  const index = STEPS.findIndex((s) => s.id === step);
  const current = STEPS[index]!;

  return (
    <>
      <Masthead kicker="Intake · Three steps" byline={`${DE_ANZA_NAME} → ${SJSU_NAME}`}>
        Begin with your
        <br />
        <em>transcript</em>.
      </Masthead>
      <Section
        num={index + 1}
        label={current.label}
        title={current.title}
        last
        notes={<Note lead={current.note.lead}>{current.note.body}</Note>}
      >
        <ol className="steps" aria-label="Steps">
          {STEPS.map((s, i) => (
            <li key={s.id} aria-current={s.id === step ? "step" : undefined} className={i < index ? "done" : undefined}>
              {String(i + 1).padStart(2, "0")} · {s.label}
            </li>
          ))}
        </ol>

        {step === "profile" && (
          <ProfileStep
            onDone={(p) => {
              setProfile(p);
              saveSession({ profile: p, courses: undefined, matches: undefined });
              setStep("upload");
            }}
          />
        )}
        {step === "upload" && profile && (
          <UploadStep
            profileId={profile.id}
            onDone={(courses) => {
              setRows(courses.map((course, i) => ({ key: i, course })));
              setStep("confirm");
            }}
          />
        )}
        {step === "confirm" && profile && <ConfirmStep profile={profile} rows={rows} setRows={setRows} />}
      </Section>
    </>
  );
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
      .then((r) => setOptions([...r.majors].sort((a, b) => a.label.localeCompare(b.label))))
      .catch((e) => setError(`Couldn't load majors: ${errorText(e)}`));
  }, []);

  // ASSIST lists ~180 majors: keep them alphabetical and narrow as you type; picks show as chips.
  const needle = filter.trim().toLowerCase();
  const shown = options.filter((m) => m.label.toLowerCase().includes(needle));

  const toggleMajor = (label: string) =>
    setMajors((m) => (m.includes(label) ? m.filter((x) => x !== label) : [...m, label]));

  const goalsTooShort = goals.trim().length > 0 && goals.trim().length < GOALS_MIN;

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
        interests: interests.split(",").map((s) => s.trim()).filter(Boolean),
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
        <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" required />
      </label>
      <p className="route-line">
        <span className="label">Transfer path</span>
        {DE_ANZA_NAME} → {SJSU_NAME}
      </p>
      <fieldset className="field">
        <legend>Majors</legend>
        <input
          type="search"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter majors, e.g. data science"
          aria-label="Filter majors"
        />
        {majors.length > 0 && (
          <div className="chips" aria-label="Selected majors">
            {majors.map((label) => (
              <button type="button" key={label} className="chip" onClick={() => toggleMajor(label)}>
                {label} <span aria-hidden>×</span>
              </button>
            ))}
          </div>
        )}
        <div className="choices scroll">
          {options.length === 0 && !error && <span className="muted">Loading majors…</span>}
          {options.length > 0 && shown.length === 0 && <span className="muted">No major matches “{filter}”.</span>}
          {shown.map((m) => (
            <label key={m.key} className="choice">
              <input type="checkbox" checked={majors.includes(m.label)} onChange={() => toggleMajor(m.label)} />
              {m.label}
            </label>
          ))}
        </div>
      </fieldset>
      <label className="field">
        <span className="label">Goals (optional)</span>
        <textarea rows={2} value={goals} onChange={(e) => setGoals(e.target.value)} placeholder="e.g. Graduate by Spring 2028, land an ML internship" />
        {goalsTooShort && <span className="field-hint">Say a bit more, or leave this blank.</span>}
      </label>
      <label className="field">
        <span className="label">Interests</span>
        <input value={interests} onChange={(e) => setInterests(e.target.value)} placeholder="ai, hackathons, finance" />
        <span className="field-hint">Separate with commas.</span>
      </label>
      {error && <p className="error">{error}</p>}
      <div className="actions">
        <button className="primary" type="submit" disabled={busy || !name.trim() || majors.length === 0 || goalsTooShort}>
          {busy ? "Saving…" : "Continue"}
        </button>
      </div>
    </form>
  );
}

function UploadStep({ profileId, onDone }: { profileId: string; onDone: (courses: Course[]) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function upload(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const { courses } = await api.uploadTranscript(profileId, file);
      onDone(courses);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="form" onSubmit={upload}>
      <p className="lede">
        Upload your community-college transcript, as a PDF or a photo. We'll read the courses, then you check them
        before anything is matched.
      </p>
      <label className="field">
        <span className="label">Transcript</span>
        <input type="file" accept="application/pdf,image/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </label>
      {error && <p className="error">{error}</p>}
      <div className="actions">
        <button className="primary" type="submit" disabled={!file || busy}>
          {busy ? "Reading transcript…" : "Upload"}
        </button>
      </div>
    </form>
  );
}

const EMPTY_COURSE: Course = { prefix: "", number: "", title: "", units: 0, grade: "", term: "", confirmed: false };

function ConfirmStep({
  profile,
  rows,
  setRows,
}: {
  profile: Profile;
  rows: Row[];
  setRows: (fn: (rows: Row[]) => Row[]) => void;
}) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const update = (key: number, patch: Partial<Course>) =>
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, course: { ...r.course, ...patch } } : r)));
  const remove = (key: number) => setRows((rs) => rs.filter((r) => r.key !== key));
  const add = () =>
    setRows((rs) => [...rs, { key: Math.max(-1, ...rs.map((r) => r.key)) + 1, course: { ...EMPTY_COURSE } }]);

  async function confirmAndMatch() {
    setBusy(true);
    setError(null);
    try {
      await api.confirmCourses(profile.id, rows.map((r) => r.course));
      const matches = await Promise.all(profile.majors.map((m) => api.match(profile.id, m)));
      saveSession({ profile, courses: rows.map((r) => r.course), matches });
      navigate("/degree", { state: { matches } });
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  }

  const text = (key: number, field: keyof Course, value: string) => update(key, { [field]: value });

  return (
    <div className="form">
      <div className="table-scroll">
        <table className="paper confirm">
          <caption>Table 1. Courses read from your transcript.</caption>
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
                <td><input aria-label="Prefix" value={c.prefix} onChange={(e) => text(key, "prefix", e.target.value)} /></td>
                <td><input aria-label="Number" value={c.number} onChange={(e) => text(key, "number", e.target.value)} /></td>
                <td>
                  <textarea
                    aria-label="Title"
                    rows={1}
                    value={c.title}
                    onChange={(e) => text(key, "title", e.target.value.replace(/\s*\n\s*/g, " "))}
                  />
                </td>
                <td>
                  <input
                    aria-label="Units"
                    type="number"
                    min={0}
                    step={0.5}
                    value={c.units}
                    onChange={(e) => update(key, { units: Number(e.target.value) || 0 })}
                  />
                </td>
                <td><input aria-label="Grade" value={c.grade} onChange={(e) => text(key, "grade", e.target.value)} /></td>
                <td><input aria-label="Term" value={c.term} onChange={(e) => text(key, "term", e.target.value)} /></td>
                <td>
                  <button type="button" onClick={() => remove(key)} aria-label={`Remove ${c.prefix} ${c.number}`}>
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
        <button className="primary" type="button" onClick={confirmAndMatch} disabled={busy || rows.length === 0}>
          {busy ? "Matching…" : "These are right — match my credits"}
        </button>
      </div>
    </div>
  );
}
