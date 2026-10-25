// Plans for Degree: the chosen majors together, plus each major alone when there are several
// (the "earliest finish" note compares them). Each is a two-phase roadmap: community-college
// terms before transfer, university terms after. Cached per page session like the Radar feed.
import { useEffect, useState } from "react";
import type { PlanResponse, Semester } from "@hindsight/contracts";
import { api } from "./api";
import { loadGePattern } from "./ge";

export type Plans = { combined: Semester[]; single: Record<string, Semester[]>; response: PlanResponse };

export type PlansState =
  | { status: "loading" }
  | { status: "error"; error: unknown }
  | { status: "ready"; plans: Plans };

const cache = new Map<string, Promise<Plans>>();

/** The student's picks ("Fall 2028", "Winter 2027"); undefined = the planner's default. */
export type TermPicks = { transfer?: string; start?: string };

function load(profileId: string, majors: string[], terms: TermPicks): Promise<Plans> {
  // GE areas are planned too, in the pattern picked on the Credits page (or the default).
  const ge = { pattern: loadGePattern(profileId) };
  const key = JSON.stringify([profileId, majors, terms.transfer ?? null, terms.start ?? null, ge.pattern ?? null]);
  let promise = cache.get(key);
  if (!promise) {
    // One major alone is optional context: a failure there only drops the comparison.
    const singles = majors.length > 1 ? majors : [];
    promise = Promise.all([
      api.plan(profileId, majors, terms, ge),
      ...singles.map((m) => api.plan(profileId, [m], terms, ge).catch(() => null)),
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

export function usePlans(profileId: string | undefined, majors: string[], terms: TermPicks = {}): PlansState {
  const [state, setState] = useState<PlansState>({ status: "loading" });
  // Labels contain commas ("Data Science, B.S."), so the dependency key is JSON.
  const key = JSON.stringify(majors);
  const { transfer, start } = terms;

  useEffect(() => {
    const chosen = JSON.parse(key) as string[];
    if (!profileId || chosen.length === 0) return;
    let live = true;
    setState({ status: "loading" });
    load(profileId, chosen, { transfer, start }).then(
      (plans) => live && setState({ status: "ready", plans }),
      (error: unknown) => live && setState({ status: "error", error }),
    );
    return () => {
      live = false;
    };
  }, [profileId, key, transfer, start]);

  return state;
}

export const lastTerm = (semesters: Semester[]) => semesters.at(-1)?.term;
export const termUnits = (s: Semester) => s.courses.reduce((n, c) => n + c.units, 0);
export const beforeTransfer = (semesters: Semester[]) => semesters.filter((s) => s.phase === "before_transfer");
export const afterTransfer = (semesters: Semester[]) => semesters.filter((s) => s.phase !== "before_transfer");

// ---- The student's start and transfer terms, remembered per profile in this browser ----

const TERM_KEYS: Record<keyof TermPicks, string> = {
  transfer: "hindsight.transferTerm.v1",
  start: "hindsight.startTerm.v1",
};

export function loadTerm(which: keyof TermPicks, profileId: string): string | undefined {
  try {
    const all = JSON.parse(localStorage.getItem(TERM_KEYS[which]) ?? "{}") as Record<string, string>;
    return all[profileId] || undefined;
  } catch {
    return undefined;
  }
}

export function saveTerm(which: keyof TermPicks, profileId: string, term: string | undefined): void {
  try {
    const all = JSON.parse(localStorage.getItem(TERM_KEYS[which]) ?? "{}") as Record<string, string>;
    if (term) all[profileId] = term;
    else delete all[profileId];
    localStorage.setItem(TERM_KEYS[which], JSON.stringify(all));
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
