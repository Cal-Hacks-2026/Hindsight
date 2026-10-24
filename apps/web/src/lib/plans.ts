// Semester plans for Degree: the chosen majors together, plus each major alone when there are
// several (the "earliest finish" note compares them). Cached per page session like the Radar feed.
import { useEffect, useState } from "react";
import type { Semester } from "@hindsight/contracts";
import { api } from "./api";

export type Plans = { combined: Semester[]; single: Record<string, Semester[]> };

export type PlansState =
  | { status: "loading" }
  | { status: "error"; error: unknown }
  | { status: "ready"; plans: Plans };

const cache = new Map<string, Promise<Plans>>();

function load(profileId: string, majors: string[]): Promise<Plans> {
  const key = JSON.stringify([profileId, majors]);
  let promise = cache.get(key);
  if (!promise) {
    // One major alone is optional context: a failure there only drops the comparison.
    const singles = majors.length > 1 ? majors : [];
    promise = Promise.all([
      api.plan(profileId, majors),
      ...singles.map((m) => api.plan(profileId, [m]).catch(() => null)),
    ]).then(([combined, ...rest]) => ({
      combined: combined!.semesters,
      single: Object.fromEntries(
        singles.flatMap((m, i) => (rest[i] ? [[m, rest[i]!.semesters] as const] : [])),
      ),
    }));
    promise.catch(() => cache.delete(key));
    cache.set(key, promise);
  }
  return promise;
}

export function usePlans(profileId: string | undefined, majors: string[]): PlansState {
  const [state, setState] = useState<PlansState>({ status: "loading" });
  // Labels contain commas ("Data Science, B.S."), so the dependency key is JSON.
  const key = JSON.stringify(majors);

  useEffect(() => {
    const chosen = JSON.parse(key) as string[];
    if (!profileId || chosen.length === 0) return;
    let live = true;
    setState({ status: "loading" });
    load(profileId, chosen).then(
      (plans) => live && setState({ status: "ready", plans }),
      (error: unknown) => live && setState({ status: "error", error }),
    );
    return () => {
      live = false;
    };
  }, [profileId, key]);

  return state;
}

export const lastTerm = (semesters: Semester[]) => semesters.at(-1)?.term;
export const termUnits = (s: Semester) => s.courses.reduce((n, c) => n + c.units, 0);
