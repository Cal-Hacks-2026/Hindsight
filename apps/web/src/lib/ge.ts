// GE progress for the Credits page, and the student's Cal-GETC / IGETC choice, remembered per
// profile in this browser. Cached per page session like the plans.
import { useEffect, useState } from "react";
import type { Course, GePattern, GeResponse } from "@hindsight/contracts";
import { api } from "./api";

export type GeState =
  | { status: "loading" }
  | { status: "error"; error: unknown }
  | { status: "ready"; ge: GeResponse };

const cache = new Map<string, Promise<GeResponse>>();
const PATTERN_KEY = "hindsight.gePattern.v1";

/** The pattern the student picked; undefined = the one their start term gives. */
export function loadGePattern(profileId: string): GePattern | undefined {
  try {
    const all = JSON.parse(localStorage.getItem(PATTERN_KEY) ?? "{}") as Record<string, GePattern>;
    return all[profileId] === "calgetc" || all[profileId] === "igetc" ? all[profileId] : undefined;
  } catch {
    return undefined;
  }
}

export function saveGePattern(profileId: string, pattern: GePattern | undefined): void {
  try {
    const all = JSON.parse(localStorage.getItem(PATTERN_KEY) ?? "{}") as Record<string, GePattern>;
    if (pattern) all[profileId] = pattern;
    else delete all[profileId];
    localStorage.setItem(PATTERN_KEY, JSON.stringify(all));
  } catch {
    // storage unavailable: the pick lasts for this page only
  }
}

export function useGe(profileId: string, pattern: GePattern | undefined, courses?: Course[]): GeState {
  const [state, setState] = useState<GeState>({ status: "loading" });
  // New courses (a re-upload) mean new progress.
  const coursesKey = (courses ?? []).map((c) => `${c.prefix} ${c.number} ${c.grade} ${c.term}`).join("|");

  useEffect(() => {
    const key = JSON.stringify([profileId, pattern ?? null, coursesKey]);
    let promise = cache.get(key);
    if (!promise) {
      promise = api.ge(profileId, pattern);
      promise.catch(() => cache.delete(key));
      cache.set(key, promise);
    }
    let live = true;
    setState({ status: "loading" });
    promise.then(
      (ge) => live && setState({ status: "ready", ge }),
      (error: unknown) => live && setState({ status: "error", error }),
    );
    return () => {
      live = false;
    };
  }, [profileId, pattern, coursesKey]);

  return state;
}
