// Shared API contract — PROJECT.md §10. Frozen after Phase 0.
// Mirrored by Pydantic models in apps/api/app/models/contracts.py.
// Any shape change needs integrator (Atishay) sign-off.

export type Campus = "sjsu" | "berkeley"; // campuses with Radar sources
// The API sets a profile's campus from receiving_institution_id; "other" is any ASSIST
// university without Radar sources or curated requirements.
export type ProfileCampus = Campus | "other";

// Not spelled out in §10; fields mirror the `profiles` table in §9.
export type Profile = {
  id: string;
  name: string;
  campus: ProfileCampus;
  sending_institution_id: number;
  receiving_institution_id: number;
  majors: string[];
  goals: string;
  interests: string[];
  created_at: string;
  // ASSIST's names for the two institutions, when the API can give them (not stored).
  sending_institution_name?: string;
  receiving_institution_name?: string;
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
  // "in_progress": the only gap is a course with an IP grade.
  status: "satisfied" | "partial" | "missing" | "at_university" | "in_progress";
  satisfied_by: string[];
  flags: string[]; // e.g. "sequence_rule", "min_grade_C"
  // What to take at the sending college, for rows not yet satisfied:
  // ["MATH 1A or MATH 1AH"], ["CIS 35A", "CIS 22A + CIS 22B"].
  options?: string[];
  citation: Citation;
  confidence: "high" | "medium" | "low";
};

export type MatchResult = {
  major_label: string;
  agreement_key: string;
  requirements: Requirement[];
  summary: { satisfied: number; partial: number; missing: number; at_university: number; in_progress?: number };
};

export type SemesterCourse = {
  code: string;
  title: string;
  units: number;
  reason: string;
  prereqs: string[];
};

export type Semester = {
  term: string;
  courses: SemesterCourse[];
  // Two-phase roadmap (I-03): community-college terms before transfer, university terms after.
  phase?: "before_transfer" | "after_transfer";
  institution?: string; // e.g. "De Anza College"
  term_system?: "quarter" | "semester"; // how `units` are counted
};

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

export type AssistInstitution = {
  id: number;
  name: string;
  term_system?: "quarter" | "semester"; // community colleges
  // Universities, for one community college: the ASSIST year their agreements are read from
  // (2026–27 = 77, or the latest year published before it), and whether we have curated
  // requirements for a full degree plan.
  year_id?: number;
  full_plan?: boolean;
};

// ---- Request / response envelopes ----

export type CreateProfileRequest = Omit<Profile, "id" | "created_at" | "sending_institution_name" | "receiving_institution_name">;
export type ProfileResponse = { profile: Profile };
export type CoursesResponse = { courses: Course[] };
export type UpdateCoursesRequest = { courses: Course[] };
export type AssistMajorsResponse = { majors: AssistMajor[] };
export type AssistInstitutionsResponse = { institutions: AssistInstitution[] };
export type MatchRequest = { major_label: string };
/** uncurated_majors: chosen majors left out of the plan because they have no curated requirements yet. */
export type PlanResponse = {
  semesters: Semester[]; // before-transfer terms first, then after-transfer terms
  uncurated_majors?: string[];
  transfer_term?: string; // when the after-transfer terms start
  earliest_transfer_term?: string; // the first Fall after the before-transfer terms finish
  start_term?: string; // first community-college term
  default_start_term?: string; // next Fall with no courses yet, else the next registrable term
  start_term_choices?: string[]; // community-college terms the student can start in
  // Community-college courses that don't fit before a requested transfer_term; their
  // university equivalents are planned after transfer instead.
  not_before_transfer?: string[];
  // false when we don't have the university's degree requirements: no after-transfer terms.
  full_plan?: boolean;
};
export type OpportunitiesResponse = { items: RankedOpportunity[] };
export type CounselorRequest = { message: string; history: ChatMessage[] };
export type CounselorResponse = { reply: string; citations: Citation[] };
export type AgentRunRequest = { campus: Campus };
export type AgentRunResponse = { run_id: string };
export type AgentEventsResponse = { events: AgentEvent[] };
export type AgentLatestRunResponse = { run_id: string | null };
export type WebhookResponse = { ok: true };
export type HealthResponse = { status: "ok"; app: string; storage?: boolean; claude?: boolean };
