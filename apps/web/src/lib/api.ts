// Typed client for every endpoint in PROJECT.md §10.
import type {
  AgentEventsResponse,
  AgentLatestRunResponse,
  AgentRunRequest,
  AgentRunResponse,
  AssistInstitutionsResponse,
  AssistMajorsResponse,
  Campus,
  CounselorRequest,
  CounselorResponse,
  Course,
  CoursesResponse,
  CreateProfileRequest,
  FreeBlocksResponse,
  GePattern,
  GeResponse,
  HealthResponse,
  MatchResult,
  OpportunitiesQuery,
  OpportunitiesResponse,
  PlanResponse,
  ProfileResponse,
  ScheduledClass,
  ScheduledPlanResponse,
  ScheduleResponse,
  UniversityGuideResponse,
  WebhookResponse,
} from "@hindsight/contracts";
import { API_URL } from "./config";

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// Server-side setup problems are not something a student can act on; say so plainly.
function friendlyDetail(detail: string): string {
  if (detail.startsWith("Storage is")) return "We couldn't save your profile. Try again in a minute.";
  return detail;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const isForm = init.body instanceof FormData;
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: isForm ? init.headers : { "Content-Type": "application/json", ...init.headers },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // non-JSON error body
    }
    throw new ApiError(res.status, friendlyDetail(detail));
  }
  return res.json() as Promise<T>;
}

const json = (body: unknown) => JSON.stringify(body);
const enc = encodeURIComponent;

export const api = {
  health: () => request<HealthResponse>("/health"),

  createProfile: (body: CreateProfileRequest) =>
    request<ProfileResponse>("/profiles", { method: "POST", body: json(body) }),

  getProfile: (id: string) => request<ProfileResponse>(`/profiles/${enc(id)}`),

  uploadTranscript: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<CoursesResponse>(`/profiles/${enc(id)}/transcript`, { method: "POST", body: form });
  },

  confirmCourses: (id: string, courses: Course[]) =>
    request<CoursesResponse>(`/profiles/${enc(id)}/courses`, { method: "PUT", body: json({ courses }) }),

  assistColleges: () => request<AssistInstitutionsResponse>("/assist/colleges"),

  assistUniversities: (sending: number) =>
    request<AssistInstitutionsResponse>(`/assist/universities?${new URLSearchParams({ sending: String(sending) })}`),

  assistMajors: (sending: number, receiving: number, year: number) =>
    request<AssistMajorsResponse>(
      `/assist/majors?${new URLSearchParams({ sending: String(sending), receiving: String(receiving), year: String(year) })}`,
    ),

  match: (id: string, major_label: string) =>
    request<MatchResult>(`/profiles/${enc(id)}/match`, { method: "POST", body: json({ major_label }) }),

  // `ge`: also plan the missing GE areas before transfer, in the pattern given (or the default).
  plan: (
    id: string,
    majors: string[],
    terms: { transfer?: string; start?: string } = {},
    ge?: { pattern?: GePattern },
  ) =>
    request<PlanResponse>(
      `/profiles/${enc(id)}/plan?${new URLSearchParams({
        majors: majors.join(","),
        ...(terms.transfer ? { transfer_term: terms.transfer } : {}),
        ...(terms.start ? { start_term: terms.start } : {}),
        ...(ge ? { ge: "true", ...(ge.pattern ? { ge_pattern: ge.pattern } : {}) } : {}),
      })}`,
    ),

  // Class schedule (SCHEDULE): upload → confirm → save, like transcripts.
  uploadSchedule: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<ScheduleResponse>(`/profiles/${enc(id)}/schedule`, { method: "POST", body: form });
  },

  saveSchedule: (id: string, rows: ScheduledClass[]) =>
    request<ScheduleResponse>(`/profiles/${enc(id)}/schedule`, { method: "PUT", body: json({ rows }) }),

  schedule: (id: string) => request<ScheduleResponse>(`/profiles/${enc(id)}/schedule`),

  freeBlocks: (id: string, week: string, term?: string) =>
    request<FreeBlocksResponse>(
      `/profiles/${enc(id)}/schedule/free-blocks?${new URLSearchParams({ week, ...(term ? { term } : {}) })}`,
    ),

  scheduledPlan: (id: string) => request<ScheduledPlanResponse>(`/profiles/${enc(id)}/schedule/planned`),

  ge: (id: string, pattern?: GePattern) =>
    request<GeResponse>(
      `/profiles/${enc(id)}/ge${pattern ? `?${new URLSearchParams({ pattern })}` : ""}`,
    ),

  opportunities: (id: string, query: OpportunitiesQuery = {}) => {
    const qs = new URLSearchParams(Object.entries(query).filter((e): e is [string, string] => !!e[1])).toString();
    return request<OpportunitiesResponse>(`/profiles/${enc(id)}/opportunities${qs ? `?${qs}` : ""}`);
  },

  counselor: (id: string, body: CounselorRequest) =>
    request<CounselorResponse>(`/profiles/${enc(id)}/counselor`, { method: "POST", body: json(body) }),

  runAgent: (body: AgentRunRequest) =>
    request<AgentRunResponse>("/agent/run", { method: "POST", body: json(body) }),

  latestAgentRun: (campus: Campus) =>
    request<AgentLatestRunResponse>(`/agent/runs/latest?${new URLSearchParams({ campus })}`),

  universityGuide: (universityId: number) =>
    request<UniversityGuideResponse>(`/universities/${enc(String(universityId))}/guide`),

  agentEvents: (runId: string) =>
    request<AgentEventsResponse>(`/agent/events?${new URLSearchParams({ run_id: runId })}`),

  // Called by Apify, not the web app; here so the client covers the whole contract.
  apifyWebhook: (payload: unknown) =>
    request<WebhookResponse>("/webhooks/apify", { method: "POST", body: json(payload) }),
};
