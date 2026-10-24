// Shared API contract — PROJECT.md §10. Frozen after Phase 0.
// Mirrored by Pydantic models in apps/api/app/models/contracts.py.
// Any shape change needs integrator (Atishay) sign-off.

export type Campus = "sjsu" | "berkeley";

// Not spelled out in §10; fields mirror the `profiles` table in §9.
export type Profile = {
  id: string;
  name: string;
  campus: Campus;
  sending_institution_id: number;
  receiving_institution_id: number;
  majors: string[];
  goals: string;
  interests: string[];
  created_at: string;
};

export type Course = {
  prefix: string;
  number: string;
  title: string;
  units: number;
  grade: string;
  term: string;
  academic_year_id?: number;
  confirmed: boolean;
};

export type Citation = {
  source: "assist" | "catalog" | "web";
  label: string;
  url: string;
  ref?: string;
};

export type Requirement = {
  id: string;
  group_title: string;
  rule: "all" | "n_of";
  n?: number;
  receiving_course: string;
  status: "satisfied" | "partial" | "missing" | "at_university";
  satisfied_by: string[];
  flags: string[]; // e.g. "sequence_rule", "min_grade_C"
  citation: Citation;
  confidence: "high" | "medium" | "low";
};

export type MatchResult = {
  major_label: string;
  agreement_key: string;
  requirements: Requirement[];
  summary: { satisfied: number; partial: number; missing: number; at_university: number };
};

export type SemesterCourse = {
  code: string;
  title: string;
  units: number;
  reason: string;
  prereqs: string[];
};

export type Semester = { term: string; courses: SemesterCourse[] };

export type RankedOpportunity = {
  id: string;
  title: string;
  type: string;
  org: string;
  url: string;
  starts_at?: string;
  deadline?: string;
  score: number;
  reason: string;
  /** Droid alerted on it (profile_opportunities.notified). */
  notified: boolean;
};

export type AgentEvent = {
  run_id: string;
  kind: "plan" | "step" | "diff" | "result" | "error";
  message: string;
  payload?: unknown;
  created_at: string;
};

export type ChatMessage = { role: "user" | "assistant"; content: string };

export type AssistMajor = { label: string; key: string };

// ---- Request / response envelopes ----

export type CreateProfileRequest = Omit<Profile, "id" | "created_at">;
export type ProfileResponse = { profile: Profile };
export type CoursesResponse = { courses: Course[] };
export type UpdateCoursesRequest = { courses: Course[] };
export type AssistMajorsResponse = { majors: AssistMajor[] };
export type MatchRequest = { major_label: string };
/** uncurated_majors: chosen majors left out of the plan because they have no curated requirements yet. */
export type PlanResponse = { semesters: Semester[]; uncurated_majors?: string[] };
export type OpportunitiesResponse = { items: RankedOpportunity[] };
export type CounselorRequest = { message: string; history: ChatMessage[] };
export type CounselorResponse = { reply: string; citations: Citation[] };
export type AgentRunRequest = { campus: Campus };
export type AgentRunResponse = { run_id: string };
export type AgentEventsResponse = { events: AgentEvent[] };
export type AgentLatestRunResponse = { run_id: string | null };
export type WebhookResponse = { ok: true };
export type HealthResponse = { status: "ok"; app: string; storage?: boolean; claude?: boolean };
