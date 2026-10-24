// Per-browser memory of the current profile and its last match results.
// Phase 0 convenience only; Supabase becomes the source of truth in Phase 1.
import type { Course, MatchResult, Profile } from "@hindsight/contracts";

const KEY = "hindsight.session.v1";

// `courses` is what the student confirmed; Degree uses it to show when each credit was taken.
export type Session = { profile?: Profile; courses?: Course[]; matches?: MatchResult[] };

export function loadSession(): Session {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Session) : {};
  } catch {
    return {};
  }
}

export function saveSession(patch: Session): void {
  try {
    localStorage.setItem(KEY, JSON.stringify({ ...loadSession(), ...patch }));
  } catch {
    // storage unavailable (private mode etc.) — the slice still works within the page
  }
}
