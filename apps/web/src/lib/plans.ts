// Plans for Degree: the chosen majors together, plus each major alone when there are several
// (the "earliest finish" note compares them). Each is a two-phase roadmap: community-college
// terms before transfer, university terms after. Cached per page session like the Radar feed.
import { useEffect, useState } from "react";
import type { PlanResponse, Semester } from "@hindsight/contracts";
import { api } from "./api";

export type Plans = { combined: Semester[]; single: Record<string, Semester[]>; response: PlanResponse };

export type PlansState =
  | { status: "loading" }
  | { status: "error"; error: unknown }
  | { status: "ready"; plans: Plans };

const cache = new Map<string, Promise<Plans>>();

function load(profileId: string, majors: string[], transferTerm?: string): Promise<Plans> {
  const key = JSON.stringify([profileId, majors, transferTerm ?? null]);
  let promise = cache.get(key);
  if (!promise) {
    // One major alone is optional context: a failure there only drops the comparison.
    const singles = majors.length > 1 ? majors : [];
    promise = Promise.all([
      api.plan(profileId, majors, transferTerm),
      ...singles.map((m) => api.plan(profileId, [m], transferTerm).catch(() => null)),
    ]).then(([combined, ...rest]) => ({
      combined: combined!.semesters,
      response: combined!,
      single: Object.fromEntries(
        singles.flatMap((m, i) => (rest[i] ? [[m, rest[i]!.semesters] as const] : [])),
      ),
    }));
    promise.catch(() => cache.delete(key));
    cache.set(key, promise);
  }
  return promise;
}

/** `transferTerm`: the student's pick ("Fall 2028"); undefined = the planner's default. */
export function usePlans(profileId: string | undefined, majors: string[], transferTerm?: string): PlansState {
  const [state, setState] = useState<PlansState>({ status: "loading" });
  // Labels contain commas ("Data Science, B.S."), so the dependency key is JSON.
  const key = JSON.stringify(majors);

  useEffect(() => {
    const chosen = JSON.parse(key) as string[];
    if (!profileId || chosen.length === 0) return;
    let live = true;
    setState({ status: "loading" });
    load(profileId, chosen, transferTerm).then(
      (plans) => live && setState({ status: "ready", plans }),
      (error: unknown) => live && setState({ status: "error", error }),
    );
    return () => {
      live = false;
    };
  }, [profileId, key, transferTerm]);

  return state;
}

export const lastTerm = (semesters: Semester[]) => semesters.at(-1)?.term;
export const termUnits = (s: Semester) => s.courses.reduce((n, c) => n + c.units, 0);
export const beforeTransfer = (semesters: Semester[]) => semesters.filter((s) => s.phase === "before_transfer");
export const afterTransfer = (semesters: Semester[]) => semesters.filter((s) => s.phase !== "before_transfer");

// ---- The student's transfer term, remembered per profile in this browser ----

const TRANSFER_KEY = "hindsight.transferTerm.v1";

export function loadTransferTerm(profileId: string): string | undefined {
  try {
    const all = JSON.parse(localStorage.getItem(TRANSFER_KEY) ?? "{}") as Record<string, string>;
    return all[profileId] || undefined;
  } catch {
    return undefined;
  }
}

export function saveTransferTerm(profileId: string, term: string | undefined): void {
  try {
    const all = JSON.parse(localStorage.getItem(TRANSFER_KEY) ?? "{}") as Record<string, string>;
    if (term) all[profileId] = term;
    else delete all[profileId];
    localStorage.setItem(TRANSFER_KEY, JSON.stringify(all));
  } catch {
    // storage unavailable: the pick lasts for this page only
  }
}

/** Transfer terms a student can pick: Fall and Spring from the next university term, six years out.
 *  Mirrors apps/api/app/services/planner.py next_term. */
export function transferChoices(d: Date = new Date()): string[] {
  let season = d.getMonth() <= 6 ? "Fall" : "Spring";
  let year = d.getMonth() <= 6 ? d.getFullYear() : d.getFullYear() + 1;
  const out: string[] = [];
  for (let i = 0; i < 12; i++) {
    out.push(`${season} ${year}`);
    [season, year] = season === "Spring" ? ["Fall", year] : ["Spring", year + 1];
  }
  return out;
}
