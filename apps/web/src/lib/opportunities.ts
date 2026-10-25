// Ranked opportunities for a profile, used by the Opportunities page.
// The first unfiltered request per profile can take ~14 s while Claude writes reasons (DECISIONS.md D-005),
// so one in-flight request per (profile, filters) is shared across mounts (and StrictMode's double
// effect) and the result is kept for the rest of the page session. Filtered requests never wait on Claude.
import { useCallback, useEffect, useState } from "react";
import type {
  OpportunitiesQuery,
  OpportunitiesResponse,
  OpportunityCategory,
  RankedOpportunity,
} from "@hindsight/contracts";
import { api } from "./api";

export type OpportunitiesState =
  | { status: "loading"; startedAt: number }
  | { status: "error"; error: unknown }
  | { status: "ready"; items: RankedOpportunity[]; categories: OpportunityCategory[] };

type Ready = Extract<OpportunitiesState, { status: "ready" }>;

const resolved = new Map<string, Ready>();
const inflight = new Map<string, { promise: Promise<Ready>; startedAt: number }>();

const keyOf = (profileId: string, query: OpportunitiesQuery) =>
  `${profileId}?${new URLSearchParams(
    Object.entries(query).filter((e): e is [string, string] => !!e[1]).sort(),
  )}`;

function load(profileId: string, query: OpportunitiesQuery, key: string) {
  let entry = inflight.get(key);
  if (!entry) {
    const promise = api
      .opportunities(profileId, query)
      .then((res: OpportunitiesResponse) => {
        const ready: Ready = { status: "ready", items: res.items, categories: res.categories ?? [] };
        resolved.set(key, ready);
        return ready;
      })
      .finally(() => inflight.delete(key));
    entry = { promise, startedAt: Date.now() };
    inflight.set(key, entry);
  }
  return entry;
}

function initial(key: string | undefined): OpportunitiesState {
  const ready = key ? resolved.get(key) : undefined;
  if (ready) return ready;
  const pending = key ? inflight.get(key) : undefined;
  return { status: "loading", startedAt: pending?.startedAt ?? Date.now() };
}

export function useOpportunities(profileId: string | undefined, query: OpportunitiesQuery = {}) {
  const key = profileId ? keyOf(profileId, query) : undefined;
  const [state, setState] = useState<OpportunitiesState>(() => initial(key));
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!profileId || !key) return;
    const ready = resolved.get(key);
    if (ready) {
      setState(ready);
      return;
    }
    let live = true;
    const { promise, startedAt } = load(profileId, query, key);
    setState({ status: "loading", startedAt });
    promise.then(
      (ready) => live && setState(ready),
      (error: unknown) => live && setState({ status: "error", error }),
    );
    return () => {
      live = false;
    };
    // `key` covers every field of `query`.
  }, [key, attempt]);

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
