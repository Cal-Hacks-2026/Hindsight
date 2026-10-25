// Shared API contract — PROJECT.md §10. Frozen after Phase 0.
// Mirrored by Pydantic models in apps/api/app/models/contracts.py.
// Any shape change needs integrator (Atishay) sign-off.

export type Campus = "sjsu" | "berkeley"; // campuses with Radar sources
// The API sets a profile's campus from receiving_institution_id; "other" is any ASSIST
// university without Radar sources or curated requirements.
export type ProfileCampus = Campus | "other";

// ---- SKELETON: where the student is now, asked before the pathway ----
export type ProfileStage = "high_school" | "community_college" | "transferred" | "returning";

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
  // SKELETON: optional so older profiles still load.
  stage?: ProfileStage;
  minor?: string;
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

// ---- University guide (UNIVERSITY) ----
// "What to Expect" at the student's university: short sections written only from official or
// institutional pages, every item citing them (GET /universities/{id}/guide).

export type GuideSectionId =
  | "transfer_services"
  | "academics"
  | "getting_around"
  | "housing"
  | "student_life"
  | "first_semester";

export type GuideSource = {
  id: string;
  title: string;
  publisher: string; // e.g. "SJSU University Housing Services", "Associated Students, SJSU"
  url: string;
  retrieved_on: string; // YYYY-MM-DD the page was read
};

export type GuideItem = {
  text: string;
  source_ids: string[]; // ids in UniversityGuide.sources; never empty
};

export type GuideSection = {
  id: GuideSectionId;
  title: string;
  items: GuideItem[];
  // Opportunities categories (RankedOpportunity.type) worth linking from this section.
  opportunity_types?: string[];
};

export type UniversityGuide = {
  university_id: number; // ASSIST institution id (39 = SJSU)
  university_name: string;
  last_updated: string; // YYYY-MM-DD the sources were last read
  sections: GuideSection[];
  sources: GuideSource[]; // cited sources, in footnote order
};

export type UniversityGuideResponse = {
  university_id: number;
  available: boolean; // false: no guide for this university yet
  university_name?: string;
  guide?: UniversityGuide;
};

// ---- Class schedule (SCHEDULE) ----

export type ClassMode = "in_person" | "online" | "hybrid" | "asynchronous";
export type Weekday = "Mon" | "Tue" | "Wed" | "Thu" | "Fri" | "Sat" | "Sun";

/** One meeting pattern of a class; a lecture plus a lab is two rows with the same CRN. */
export type ScheduledClass = {
  term: string;
  course: string; // as printed, e.g. "MATH 1B" or "MATH D001B"
  title: string;
  crn?: string;
  section?: string;
  professor?: string;
  units?: number;
  location?: string;
  mode: ClassMode;
  days: Weekday[]; // empty for asynchronous or TBA
  start_time?: string; // "HH:MM", 24-hour
  end_time?: string;
  start_date?: string; // "YYYY-MM-DD", when the schedule prints class dates
  end_date?: string;
  // Upload only, for the confirm table: why a row needs a second look (never stored).
  flags?: string[];
  confirmed: boolean;
};

/** units: each class counted once, however many meeting rows it has. */
export type ScheduleTerm = { term: string; units: number; classes: number };
export type ScheduleResponse = { rows: ScheduledClass[]; terms?: ScheduleTerm[] }; // terms: saved schedules only
export type UpdateScheduleRequest = { rows: ScheduledClass[] };
export type FreeBlock = { start: string; end: string; minutes: number };
export type FreeDay = { day: Weekday; date: string; blocks: FreeBlock[] };
export type FreeBlocksResponse = {
  week: string; // the Monday, "YYYY-MM-DD"
  day_start: string; // "07:00"
  day_end: string; // "22:00"
  days: FreeDay[]; // Mon–Sun
};
export type ScheduledPlanCourse = { code: string; planned_term: string; scheduled_term: string; crn?: string };
/** Planned courses that are on the saved schedule. */
export type ScheduledPlanResponse = { courses: ScheduledPlanCourse[] };
