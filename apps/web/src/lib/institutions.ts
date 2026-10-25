// ASSIST's college and university lists for the onboarding pickers. Each list is fetched once per
// page session (the API caches them for a day too) and filtered in the browser as the student types,
// so typing never calls ASSIST.
import type { AssistInstitution } from "@hindsight/contracts";
import { api } from "./api";
import { ASSIST_YEAR_2026_27, DE_ANZA_ID, DE_ANZA_NAME, SJSU_ID, SJSU_NAME } from "./config";

let colleges: Promise<AssistInstitution[]> | undefined;
const universities = new Map<number, Promise<AssistInstitution[]>>();

export function loadColleges(): Promise<AssistInstitution[]> {
  if (!colleges) {
    colleges = api.assistColleges().then((r) => r.institutions);
    colleges.catch(() => (colleges = undefined));
  }
  return colleges;
}

export function loadUniversities(collegeId: number): Promise<AssistInstitution[]> {
  let found = universities.get(collegeId);
  if (!found) {
    found = api.assistUniversities(collegeId).then((r) => r.institutions);
    found.catch(() => universities.delete(collegeId));
    universities.set(collegeId, found);
  }
  return found;
}

// The defaults, for when ASSIST's lists can't be loaded: the demo path still works.
export const DE_ANZA: AssistInstitution = { id: DE_ANZA_ID, name: DE_ANZA_NAME, term_system: "quarter" };
export const SJSU: AssistInstitution = { id: SJSU_ID, name: SJSU_NAME, year_id: ASSIST_YEAR_2026_27, full_plan: true };

/** The profile campus the API will assign (apps/api/app/config.py campus_for). */
export const campusFor = (universityId: number) =>
  universityId === SJSU_ID ? "sjsu" : universityId === 79 ? "berkeley" : "other";
