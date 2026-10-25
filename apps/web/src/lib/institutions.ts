// ASSIST's college and university lists for the onboarding pickers. Each list is fetched once per
// page session (the API caches them for a day too) and filtered in the browser as the student types,
// so typing never calls ASSIST.
//
// When the live list can't load, a committed snapshot (src/data/institutions-snapshot.json, from
// apps/api/scripts/snapshot_institutions.py) stands in, and `savedOn` says so. It's only a list to
// pick from: nothing is preselected either way. A saved list isn't kept, so the next load tries live.
import type { AssistInstitution } from "@hindsight/contracts";
import { api } from "./api";
import { SJSU_ID } from "./config";

/** `savedOn`: the snapshot's date ("2026-10-25"), set only when the live list failed. */
export type InstitutionList = { institutions: AssistInstitution[]; savedOn?: string };

let colleges: Promise<InstitutionList> | undefined;
const universities = new Map<number, Promise<InstitutionList>>();

type Snapshot = {
  saved_on: string;
  colleges: AssistInstitution[];
  universities: Record<string, { name: string; full_plan?: boolean }>;
  /** College id → [university id, ASSIST year id] for each university it has agreements with. */
  agreements: Record<string, [number, number][]>;
};

// Loaded only on a failure, as its own chunk.
const snapshot = () =>
  import("../data/institutions-snapshot.json").then((m) => m.default as unknown as Snapshot);

/** The snapshot's list, or the live call's own error when the snapshot can't help. */
function fromSnapshot(
  liveError: unknown,
  pick: (s: Snapshot) => AssistInstitution[] | undefined,
): Promise<InstitutionList> {
  return snapshot().then(
    (s) => {
      const institutions = pick(s);
      if (!institutions?.length) throw liveError;
      return { institutions, savedOn: s.saved_on };
    },
    () => {
      throw liveError;
    },
  );
}

export function loadColleges(): Promise<InstitutionList> {
  if (!colleges) {
    const found = api.assistColleges().then(
      (r): InstitutionList => ({ institutions: r.institutions }),
      (e) => fromSnapshot(e, (s) => s.colleges),
    );
    colleges = found;
    found.then((l) => l.savedOn && (colleges = undefined), () => (colleges = undefined));
  }
  return colleges;
}

export function loadUniversities(collegeId: number): Promise<InstitutionList> {
  let found = universities.get(collegeId);
  if (!found) {
    found = api.assistUniversities(collegeId).then(
      (r): InstitutionList => ({ institutions: r.institutions }),
      (e) =>
        fromSnapshot(e, (s) =>
          s.agreements[collegeId]?.map(([id, year_id]) => ({ id, year_id, ...s.universities[id]! })),
        ),
    );
    found.then(
      (l) => l.savedOn && universities.delete(collegeId),
      () => universities.delete(collegeId),
    );
    universities.set(collegeId, found);
  }
  return found;
}

/** "2026-10-25" → "October 25, 2026" */
export const savedOnLabel = (savedOn: string) =>
  new Date(`${savedOn}T00:00:00Z`).toLocaleDateString("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });

/** The profile campus the API will assign (apps/api/app/config.py campus_for). */
export const campusFor = (universityId: number) =>
  universityId === SJSU_ID ? "sjsu" : universityId === 79 ? "berkeley" : "other";
