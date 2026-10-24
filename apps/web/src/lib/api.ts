// Typed client for every endpoint in PROJECT.md §10.
import type {
  AgentEventsResponse,
  AgentRunRequest,
  AgentRunResponse,
  AssistMajorsResponse,
  CounselorRequest,
  CounselorResponse,
  Course,
  CoursesResponse,
  CreateProfileRequest,
  HealthResponse,
  MatchResult,
  OpportunitiesResponse,
  PlanResponse,
  ProfileResponse,
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
    throw new ApiError(res.status, detail);
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

  assistMajors: (sending: number, receiving: number, year: number) =>
    request<AssistMajorsResponse>(
      `/assist/majors?${new URLSearchParams({ sending: String(sending), receiving: String(receiving), year: String(year) })}`,
    ),

  match: (id: string, major_label: string) =>
    request<MatchResult>(`/profiles/${enc(id)}/match`, { method: "POST", body: json({ major_label }) }),

  plan: (id: string, majors: string[]) =>
    request<PlanResponse>(`/profiles/${enc(id)}/plan?${new URLSearchParams({ majors: majors.join(",") })}`),

  opportunities: (id: string) => request<OpportunitiesResponse>(`/profiles/${enc(id)}/opportunities`),

  counselor: (id: string, body: CounselorRequest) =>
    request<CounselorResponse>(`/profiles/${enc(id)}/counselor`, { method: "POST", body: json(body) }),

  runAgent: (body: AgentRunRequest) =>
    request<AgentRunResponse>("/agent/run", { method: "POST", body: json(body) }),

  agentEvents: (runId: string) =>
    request<AgentEventsResponse>(`/agent/events?${new URLSearchParams({ run_id: runId })}`),

  // Called by Apify, not the web app; here so the client covers the whole contract.
  apifyWebhook: (payload: unknown) =>
    request<WebhookResponse>("/webhooks/apify", { method: "POST", body: json(payload) }),
};
