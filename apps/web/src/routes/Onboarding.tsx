import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import type { AssistMajor, Campus, Course, Profile } from "@hindsight/contracts";
import { api } from "../lib/api";
import { ASSIST_YEAR_2026_27, DE_ANZA_ID, SJSU_ID } from "../lib/config";
import { saveSession } from "../lib/session";

type Step = "profile" | "upload" | "confirm";
type Row = { key: number; course: Course };

const STEPS: { id: Step; label: string }[] = [
  { id: "profile", label: "1. About you" },
  { id: "upload", label: "2. Transcript" },
  { id: "confirm", label: "3. Confirm courses" },
];

const errorText = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");

export function Onboarding() {
  const [step, setStep] = useState<Step>("profile");
  const [profile, setProfile] = useState<Profile | null>(null);
  const [rows, setRows] = useState<Row[]>([]);

  return (
    <section>
      <h1>Get started</h1>
      <ol className="steps">
        {STEPS.map((s) => (
          <li key={s.id} className={s.id === step ? "current" : undefined}>
            {s.label}
          </li>
        ))}
      </ol>

      {step === "profile" && (
        <ProfileStep
          onDone={(p) => {
            setProfile(p);
            saveSession({ profile: p, matches: undefined });
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
    </section>
  );
}

function ProfileStep({ onDone }: { onDone: (p: Profile) => void }) {
  const [name, setName] = useState("");
  const [campus, setCampus] = useState<Campus>("sjsu");
  const [majors, setMajors] = useState<string[]>([]);
  const [goals, setGoals] = useState("");
  const [interests, setInterests] = useState("");
  const [options, setOptions] = useState<AssistMajor[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .assistMajors(DE_ANZA_ID, SJSU_ID, ASSIST_YEAR_2026_27)
      .then((r) => setOptions(r.majors))
      .catch((e) => setError(`Couldn't load majors: ${errorText(e)}`));
  }, []);

  const toggleMajor = (label: string) =>
    setMajors((m) => (m.includes(label) ? m.filter((x) => x !== label) : [...m, label]));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { profile } = await api.createProfile({
        name: name.trim(),
        campus,
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
    <form className="card stack" onSubmit={submit}>
      <label>
        Name
        <input value={name} onChange={(e) => setName(e.target.value)} required />
      </label>
      <label>
        Transferring from
        <select disabled value="deanza">
          <option value="deanza">De Anza College</option>
        </select>
      </label>
      <label>
        Transferring to
        <select value={campus} onChange={(e) => setCampus(e.target.value as Campus)}>
          <option value="sjsu">San José State University</option>
          <option value="berkeley" disabled>
            UC Berkeley (coming soon)
          </option>
        </select>
      </label>
      <fieldset className="choices">
        <legend>Majors</legend>
        {options.length === 0 && !error && <span className="muted">Loading majors…</span>}
        {options.map((m) => (
          <label key={m.key} className="inline">
            <input type="checkbox" checked={majors.includes(m.label)} onChange={() => toggleMajor(m.label)} />
            {m.label}
          </label>
        ))}
      </fieldset>
      <label>
        Goals
        <textarea rows={2} value={goals} onChange={(e) => setGoals(e.target.value)} placeholder="e.g. Graduate by Spring 2028, land an ML internship" />
      </label>
      <label>
        Interests <span className="muted">(comma-separated)</span>
        <input value={interests} onChange={(e) => setInterests(e.target.value)} placeholder="ai, hackathons, finance" />
      </label>
      {error && <p className="error">{error}</p>}
      <div>
        <button className="primary" type="submit" disabled={busy || !name.trim() || majors.length === 0}>
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
    <form className="card stack" onSubmit={upload}>
      <p className="muted">
        Upload your community-college transcript (PDF or photo). We'll read the courses, then you check them before
        anything is matched.
      </p>
      <label>
        Transcript
        <input type="file" accept="application/pdf,image/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </label>
      {error && <p className="error">{error}</p>}
      <div>
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
      saveSession({ profile, matches });
      navigate("/degree", { state: { matches } });
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  }

  const text = (key: number, field: keyof Course, value: string) => update(key, { [field]: value });

  return (
    <div className="card stack">
      <p className="muted">
        Check every row against your transcript. Fix anything we misread — matching only uses what you confirm here.
      </p>
      <div className="table-scroll">
        <table className="courses">
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
                <td><input aria-label="Title" value={c.title} onChange={(e) => text(key, "title", e.target.value)} /></td>
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
      <div className="row">
        <button type="button" onClick={add}>
          + Add course
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      <div>
        <button className="primary" type="button" onClick={confirmAndMatch} disabled={busy || rows.length === 0}>
          {busy ? "Matching…" : "These are right — match my credits"}
        </button>
      </div>
    </div>
  );
}
