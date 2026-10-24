// Ranked Radar feed for a profile, used by Radar.
// The first request per profile can take ~14 s while Claude writes reasons (DECISIONS.md D-005),
// so one in-flight request is shared across mounts (and StrictMode's double effect) and the
// result is kept for the rest of the page session.
import { useCallback, useEffect, useState } from "react";
import type { RankedOpportunity } from "@hindsight/contracts";
import { api } from "./api";

export type OpportunitiesState =
  | { status: "loading"; startedAt: number }
  | { status: "error"; error: unknown }
  | { status: "ready"; items: RankedOpportunity[] };

const resolved = new Map<string, RankedOpportunity[]>();
const inflight = new Map<string, { promise: Promise<RankedOpportunity[]>; startedAt: number }>();

function load(profileId: string) {
  let entry = inflight.get(profileId);
  if (!entry) {
    const promise = api
      .opportunities(profileId)
      .then((res) => {
        resolved.set(profileId, res.items);
        return res.items;
      })
      .finally(() => inflight.delete(profileId));
    entry = { promise, startedAt: Date.now() };
    inflight.set(profileId, entry);
  }
  return entry;
}

function initial(profileId: string | undefined): OpportunitiesState {
  const items = profileId ? resolved.get(profileId) : undefined;
  if (items) return { status: "ready", items };
  const pending = profileId ? inflight.get(profileId) : undefined;
  return { status: "loading", startedAt: pending?.startedAt ?? Date.now() };
}

export function useOpportunities(profileId: string | undefined) {
  const [state, setState] = useState<OpportunitiesState>(() => initial(profileId));
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!profileId) return;
    const items = resolved.get(profileId);
    if (items) {
      setState({ status: "ready", items });
      return;
    }
    let live = true;
    const { promise, startedAt } = load(profileId);
    setState({ status: "loading", startedAt });
    promise.then(
      (items) => live && setState({ status: "ready", items }),
      (error: unknown) => live && setState({ status: "error", error }),
    );
    return () => {
      live = false;
    };
  }, [profileId, attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { state, retry };
}

/** The item whose deadline comes soonest and hasn't passed. */
export function nearestDeadline(items: RankedOpportunity[], now: number): RankedOpportunity | undefined {
  let best: { item: RankedOpportunity; at: number } | undefined;
  for (const item of items) {
    if (!item.deadline) continue;
    const at = Date.parse(item.deadline);
    if (Number.isNaN(at) || at < now) continue;
    if (!best || at < best.at) best = { item, at };
  }
  return best?.item;
}
