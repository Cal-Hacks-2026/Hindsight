import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import type {
  AssistInstitution,
  AssistMajor,
  Course,
  Profile,
  ProfileStage,
} from "@hindsight/contracts";
import { Icon } from "../components/Icons";
import { InstitutionPicker } from "../components/InstitutionPicker";
import { Masthead, Note, Section } from "../components/Paper";
import { api } from "../lib/api";
import { ASSIST_YEAR_2026_27, assistYear } from "../lib/config";
import { shortUniversity } from "../lib/format";
import { campusFor, loadColleges, loadUniversities } from "../lib/institutions";
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
    title: "Your Profile",
    note: {
      lead: "Why we ask.",
      body: "Majors shape your degree plan. Goals and interests help us find opportunities for you.",
    },
  },
  {
    id: "upload",
    label: "Transcript",
    title: "Upload a File",
    note: {
      lead: "What happens next.",
      body: "Your file isn't stored. Only the courses you review and confirm are saved.",
    },
  },
  {
    id: "confirm",
    label: "Confirm courses",
    title: "Course Details",
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
        sketch={
          step === "upload" ? "pencil" : step === "confirm" ? "cap" : "books"
        }
      >
        {step === "profile" ? (
          <>
            Start With
            <br />
            Your Path.
          </>
        ) : step === "upload" ? (
          <>
            Your
            <br />
            Transcript.
          </>
        ) : (
          <>
            Review Your
            <br />
            Courses.
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
              <span className="step-label">{s.label}</span>
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
    navigate("/plan", { state: { matches } });
  };
}

// The stage question, asked before the pathway.
const STAGES: { id: ProfileStage; label: string }[] = [
  { id: "high_school", label: "In High School" },
  { id: "community_college", label: "At a Community College" },
  { id: "transferred", label: "Already Transferred" },
  { id: "returning", label: "Returning to School" },
];

// ASSIST's academic years, current first. Only the current one has agreements we read.
const ACADEMIC_YEARS = [ASSIST_YEAR_2026_27];

function ProfileStep({ onDone }: { onDone: (p: Profile) => void }) {
  const [name, setName] = useState("");
  const [stage, setStage] = useState<ProfileStage>();
  const [yearId, setYearId] = useState(ASSIST_YEAR_2026_27);
  const [majors, setMajors] = useState<string[]>([]);
  const [minor, setMinor] = useState("");
  const [goals, setGoals] = useState("");
  const [interests, setInterests] = useState("");
  const [colleges, setColleges] = useState<AssistInstitution[]>();
  const [college, setCollege] = useState<AssistInstitution>();
  const [universities, setUniversities] = useState<AssistInstitution[]>();
  const [university, setUniversity] = useState<AssistInstitution>();
  const [listError, setListError] = useState<string | null>(null);
  const [options, setOptions] = useState<AssistMajor[]>();
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Colleges once. Nothing is picked until the student chooses (assist.org's order: year, college,
  // university, major).
  useEffect(() => {
    loadColleges().then(setColleges, (e) => {
      setListError(`Couldn't load ASSIST's college list: ${errorText(e)}. Reload to try again.`);
      setColleges([]);
    });
  }, []);

  // The universities this college has agreements with; keep the pick if it's still there.
  useEffect(() => {
    if (!college) return;
    let live = true;
    setUniversities(undefined);
    setListError(null);
    loadUniversities(college.id).then(
      (list) => {
        if (!live) return;
        setUniversities(list);
        setUniversity((u) => list.find((x) => x.id === u?.id));
      },
      (e) => {
        if (!live) return;
        setListError(`Couldn't load the universities for ${college.name}: ${errorText(e)}`);
        setUniversities([]);
        setUniversity(undefined);
      },
    );
    return () => {
      live = false;
    };
  }, [college]);

  // Majors for the pair, from the year ASSIST has agreements for. Picks not offered for the new pair drop.
  useEffect(() => {
    if (!college || !university) {
      setOptions(undefined);
      return;
    }
    let live = true;
    setOptions(undefined);
    setError(null);
    api.assistMajors(college.id, university.id, university.year_id ?? yearId).then(
      (r) => {
        if (!live) return;
        const sorted = [...r.majors].sort((a, b) => a.label.localeCompare(b.label));
        setOptions(sorted);
        setMajors((m) => m.filter((label) => sorted.some((o) => o.label === label)));
      },
      (e) => live && setError(`Couldn't load majors: ${errorText(e)}`),
    );
    return () => {
      live = false;
    };
  }, [college, university, yearId]);

  // ASSIST lists ~180 majors: keep them alphabetical and narrow as you type; picks show as chips.
  const needle = filter.trim().toLowerCase();
  const shown = (options ?? []).filter((m) => m.label.toLowerCase().includes(needle));
  const year = university?.year_id;
  const voidsAdt = majors.length > 1 || minor.trim().length > 0;

  const toggleMajor = (label: string) =>
    setMajors((m) =>
      m.includes(label) ? m.filter((x) => x !== label) : [...m, label],
    );

  const goalsTooShort =
    goals.trim().length > 0 && goals.trim().length < GOALS_MIN;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (goalsTooShort || !stage || !college || !university) return;
    setBusy(true);
    setError(null);
    try {
      const { profile } = await api.createProfile({
        name: name.trim(),
        stage,
        campus: campusFor(university.id),
        sending_institution_id: college.id,
        receiving_institution_id: university.id,
        majors,
        minor: minor.trim() || undefined,
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
        <legend>Where Are You Now?</legend>
        <div className="choices stage-choices">
          {STAGES.map((s) => (
            <label key={s.id} className="choice">
              <input
                type="radio"
                name="stage"
                checked={stage === s.id}
                onChange={() => setStage(s.id)}
                required
              />
              {s.label}
            </label>
          ))}
        </div>
      </fieldset>
      <label className="field">
        <span className="label">Academic Year</span>
        <select value={yearId} onChange={(e) => setYearId(Number(e.target.value))}>
          {ACADEMIC_YEARS.map((id) => (
            <option key={id} value={id}>
              {assistYear(id)}
              {id === ASSIST_YEAR_2026_27 ? " (Current)" : ""}
            </option>
          ))}
        </select>
      </label>
      <InstitutionPicker
        id="from"
        label="Community College"
        noun="community college"
        nouns="community colleges"
        example="Foothill"
        value={college}
        options={colleges}
        onChange={setCollege}
        hint={
          college?.term_system &&
          `${college.term_system === "quarter" ? "Quarter" : "Semester"} system.`
        }
      />
      <InstitutionPicker
        id="to"
        label="University"
        noun="university"
        nouns="universities"
        example="UCLA"
        value={university}
        options={universities}
        onChange={setUniversity}
        locked={college ? undefined : "Pick a community college first."}
        badge={(u) => (u.full_plan ? "Full Plan" : undefined)}
        hint={
          university ? (
            <UniversityHint university={university} />
          ) : (
            college &&
            universities?.length !== 0 &&
            `Universities with ASSIST agreements from ${college.name}.`
          )
        }
      />
      {listError && <p className="error">{listError}</p>}
      <fieldset className="field" disabled={!university}>
        <legend>Majors</legend>
        <input
          type="search"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder={university ? "Search majors" : "Pick a university first."}
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
        {university && (
          <div className="choices scroll">
            {!options && !error && (
              <span className="muted">Loading majors…</span>
            )}
            {options?.length === 0 && (
              <span className="muted">
                ASSIST lists no major agreements from {college?.name} to{" "}
                {university.name}
                {year ? ` for ${assistYear(year)}` : ""}.
              </span>
            )}
            {!!options?.length && shown.length === 0 && (
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
        )}
        {year !== undefined && !!options?.length && (
          <span className="field-hint">From ASSIST's {assistYear(year)} agreements.</span>
        )}
      </fieldset>
      <label className="field">
        <span className="label">Minor (optional)</span>
        <input
          value={minor}
          onChange={(e) => setMinor(e.target.value)}
          placeholder={university ? "Business" : "Pick a university first."}
          disabled={!university}
        />
      </label>
      {voidsAdt && (
        <p className="plan-warning adt-warning" role="status">
          Adding a minor or second major voids the ADT guarantee at CSU
          campuses. Talk to your advisor before you commit.
        </p>
      )}
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
            busy ||
            !name.trim() ||
            !stage ||
            !college ||
            !university ||
            majors.length === 0 ||
            goalsTooShort
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

/** What the plan covers for this university, and which ASSIST year its agreements come from. */
function UniversityHint({ university }: { university: AssistInstitution }) {
  const short = shortUniversity(university.name);
  const year = university.year_id;
  return (
    <>
      {university.full_plan
        ? `Full plan: credits, community college terms and ${short} semesters.`
        : `Credits and community college terms only. ${short}'s full degree requirements aren't available yet.`}
      {year !== undefined && year < ASSIST_YEAR_2026_27 && (
        <>
          {" "}
          ASSIST has no {assistYear(ASSIST_YEAR_2026_27)} agreements for this
          pair yet, so {assistYear(year)} is used.
        </>
      )}
    </>
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
        Upload your{" "}
        {profile.sending_institution_name ?? "community college"} transcript as
        a PDF or photo. You’ll review the courses before your credits are
        matched.
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
