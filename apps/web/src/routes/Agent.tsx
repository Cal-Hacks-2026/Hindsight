// Agent log: start a Droid run and follow its plan → steps → diffs → result (PROJECT.md §10).
// Events are polled from /agent/events; the run id lives in ?run= so a run can be linked and reloaded.
// Without ?run=, the page opens on the campus's latest run (/agent/runs/latest).
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import type { AgentEvent } from "@hindsight/contracts";
import { Masthead } from "../components/Paper";
import { api, ApiError } from "../lib/api";
import { loadSession } from "../lib/session";
import { useNow } from "../lib/time";
import "../styles/counselor.css";

const POLL_MS = 2000;
// apps/agent stops a run after 20 minutes by default; keep polling a little past that.
const MAX_POLL_MS = 25 * 60_000;

type Poll = { events: AgentEvent[]; done: boolean; gaveUp: boolean; fetchError?: unknown };

const EMPTY: Poll = { events: [], done: false, gaveUp: false };

export function Agent() {
  const { profile } = loadSession();
  const campus = profile?.campus ?? "sjsu";
  const [params, setParams] = useSearchParams();
  const runId = params.get("run") ?? undefined;
  const [poll, setPoll] = useState<Poll>(EMPTY);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<unknown>();
  const [latest, setLatest] = useState<"loading" | "none" | "error">();

  useEffect(() => {
    if (runId) return;
    let live = true;
    setLatest("loading");
    api.latestAgentRun(campus).then(
      ({ run_id }) => {
        if (!live) return;
        if (run_id) setParams({ run: run_id }, { replace: true });
        else setLatest("none");
      },
      () => live && setLatest("error"),
    );
    return () => {
      live = false;
    };
  }, [runId, campus, setParams]);

  useEffect(() => {
    if (!runId) return;
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const since = Date.now();
    setPoll(EMPTY);

    async function tick() {
      try {
        const { events } = await api.agentEvents(runId!);
        if (!live) return;
        const done = finished(events);
        // A run older than the agent's timeout that never logged an end won't finish now.
        const stale = !done && events.length > 0 && Date.now() - Date.parse(events[0]!.created_at) > MAX_POLL_MS;
        setPoll({ events, done, gaveUp: stale });
        if (done || stale) return;
      } catch (fetchError) {
        if (!live) return;
        setPoll((p) => ({ ...p, fetchError }));
      }
      if (Date.now() - since > MAX_POLL_MS) {
        setPoll((p) => ({ ...p, gaveUp: true }));
        return;
      }
      timer = setTimeout(() => void tick(), POLL_MS);
    }

    void tick();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [runId]);

  async function runNow() {
    setStarting(true);
    setStartError(undefined);
    try {
      const { run_id } = await api.runAgent({ campus });
      setParams({ run: run_id });
    } catch (error) {
      setStartError(error);
    } finally {
      setStarting(false);
    }
  }

  const running = Boolean(runId) && !poll.done && !poll.gaveUp;

  return (
    <div className="cs">
      <Masthead>How Listings Stay Fresh</Masthead>

      <section className="cs-row">
        <div className="cs-label cs-row-label">Run</div>
        <div className="cs-main">
          <p className="cs-para">
            Droid scans {campus === "sjsu" ? "SJSU" : "UC Berkeley"} event sources, ranks what it finds, and repairs an
            extractor when a site changes. Every plan, step, and patch it makes is logged below.
          </p>
          <div className="cs-actions">
            <button type="button" className="cs-btn cs-btn-solid" onClick={() => void runNow()} disabled={starting || running}>
              {starting ? "Starting…" : running ? "Running…" : "Run Now"}
            </button>
          </div>
          {!runId && latest === "loading" && (
            <p className="cs-muted" role="status">
              Loading the latest run…
            </p>
          )}
          {!runId && latest === "none" && <p className="cs-muted">No runs logged yet. Start one to see it here.</p>}
          {!runId && latest === "error" && <p className="cs-muted">Couldn't load the latest run.</p>}
          {startError !== undefined && (
            <p className="ag-alert" role="alert">
              {startErrorMessage(startError)}
            </p>
          )}
        </div>
        <div className="cs-margin">{runId && <RunMeta runId={runId} poll={poll} />}</div>
      </section>

      {runId && (
        <section className="cs-row">
          <div className="cs-label cs-row-label">Timeline</div>
          <div className="cs-main">
            {poll.events.length === 0 ? (
              <p className="cs-muted" role="status">
                {poll.gaveUp
                  ? "No events were recorded for this run."
                  : "Queued. Waiting for Droid to pick up the run…"}
              </p>
            ) : (
              <ol className="ag-timeline" aria-live="polite">
                {poll.events.map((event, i) => (
                  <EventRow key={i} event={event} />
                ))}
              </ol>
            )}
            {poll.fetchError !== undefined && !poll.done && (
              <p className="cs-muted">Couldn't refresh the log just now; retrying.</p>
            )}
          </div>
          <div className="cs-margin" />
        </section>
      )}
    </div>
  );
}

function RunMeta({ runId, poll }: { runId: string; poll: Poll }) {
  const now = useNow(1000);
  const first = poll.events[0] ? Date.parse(poll.events[0].created_at) : undefined;
  const last = poll.events.at(-1) ? Date.parse(poll.events.at(-1)!.created_at) : undefined;
  const end = poll.done || poll.gaveUp ? last : now;
  const elapsed = first !== undefined && end !== undefined ? Math.max(0, end - first) : undefined;
  const outcome = [...poll.events].reverse().find((e) => e.kind === "result" || isTerminalError(e));
  const status = poll.done
    ? outcome?.kind === "result"
      ? "Finished"
      : "Failed"
    : poll.gaveUp
      ? "No longer polling"
      : poll.events.length
        ? "Running"
        : "Queued";

  return (
    <dl className="ag-meta">
      <div>
        <dt className="cs-label">Status</dt>
        <dd className={poll.done ? (outcome?.kind === "result" ? "ag-ok" : "ag-bad") : poll.gaveUp ? undefined : "ag-live"}>
          {status}
        </dd>
      </div>
      <div>
        <dt className="cs-label">Run</dt>
        <dd className="cs-num" title={runId}>
          {runId.slice(0, 8)}
        </dd>
      </div>
      <div>
        <dt className="cs-label">Events</dt>
        <dd className="cs-num">{poll.events.length}</dd>
      </div>
      {elapsed !== undefined && (
        <div>
          <dt className="cs-label">Elapsed</dt>
          <dd className="cs-num">{duration(elapsed)}</dd>
        </div>
      )}
    </dl>
  );
}

const KIND_LABEL: Record<AgentEvent["kind"], string> = {
  plan: "Plan",
  step: "Step",
  diff: "Diff",
  result: "Result",
  error: "Error",
};

function EventRow({ event }: { event: AgentEvent }) {
  return (
    <li className={`ag-event ag-k-${event.kind}`}>
      <time className="cs-num ag-time" dateTime={event.created_at}>
        {clock(event.created_at)}
      </time>
      <span className="cs-label ag-kind">{KIND_LABEL[event.kind] ?? event.kind}</span>
      <div className="ag-body">
        {event.kind === "plan" ? (
          <ol className="ag-plan">
            {event.message
              .split("\n")
              .filter((line) => line.trim())
              .map((line, i) => {
                const { status, text } = planLine(line);
                return (
                  <li key={i}>
                    {status && <span className="cs-label ag-status">{STATUS_LABEL[status] ?? status}</span>}
                    {text}
                  </li>
                );
              })}
          </ol>
        ) : (
          <p className="ag-message">{event.message}</p>
        )}
        {event.kind === "diff" && <DiffBlock payload={event.payload} />}
        {event.kind === "result" && <ResultMeta payload={event.payload} />}
      </div>
    </li>
  );
}

function DiffBlock({ payload }: { payload: unknown }) {
  const p = record(payload);
  const text = typeof p?.diff === "string" ? p.diff : typeof p?.preview === "string" ? p.preview : undefined;
  if (!text) return null;
  const lines = text.split("\n").filter((line) => !/^=+$/.test(line));
  return (
    <pre className="ag-diff" aria-label={typeof p?.file === "string" ? `Diff of ${p.file}` : "Diff"}>
      <code>
        {lines.map((line, i) => (
          <span key={i} className={diffClass(line)}>
            {line}
            {"\n"}
          </span>
        ))}
      </code>
      {p?.truncated === true && <span className="ag-truncated">Diff truncated.</span>}
    </pre>
  );
}

function ResultMeta({ payload }: { payload: unknown }) {
  const p = record(payload);
  if (!p) return null;
  const patched = Array.isArray(p.patched) ? p.patched.filter((f): f is string => typeof f === "string") : [];
  const items: [string, string][] = [];
  if (typeof p.alerts_new === "number") items.push(["New alerts", String(p.alerts_new)]);
  items.push(["Patched", patched.length ? patched.join(", ") : "none"]);
  if (typeof p.duration_ms === "number") items.push(["Duration", duration(p.duration_ms)]);
  return (
    <dl className="ag-result">
      {items.map(([k, v]) => (
        <div key={k}>
          <dt className="cs-label">{k}</dt>
          <dd className="cs-num">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

// ---- helpers ----

const STATUS_LABEL: Record<string, string> = { completed: "Done", in_progress: "Doing", pending: "To Do" };

// Droid's TodoWrite lines arrive as "1. [completed] Scan sources"; the <ol> already numbers them.
function planLine(line: string): { status?: string; text: string } {
  const m = /^\s*(?:\d+[.)]\s*)?(?:\[([a-z_ ]+)\]\s*)?(.*)$/i.exec(line)!;
  return { status: m[1]?.trim().toLowerCase().replace(/ /g, "_"), text: m[2]!.trim() };
}

// apps/agent/src/job.ts ends every run with one result, or an error that starts "Run ".
function isTerminalError(e: AgentEvent): boolean {
  return e.kind === "error" && /^Run (ended|stopped|failed)\b/.test(e.message);
}

function finished(events: AgentEvent[]): boolean {
  return events.some((e) => e.kind === "result" || isTerminalError(e));
}

function record(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined;
}

function diffClass(line: string): string | undefined {
  if (line.startsWith("+++") || line.startsWith("---")) return "ag-d-file";
  if (line.startsWith("@@")) return "ag-d-hunk";
  if (line.startsWith("+")) return "ag-d-add";
  if (line.startsWith("-")) return "ag-d-del";
  return undefined;
}

const clockFmt = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });

function clock(iso: string): string {
  const at = new Date(iso);
  return Number.isNaN(at.getTime()) ? "" : clockFmt.format(at);
}

function duration(ms: number): string {
  const s = Math.round(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function startErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return "We couldn't reach the Hindsight server. Check your connection and try again.";
  if (error.status === 429) return "Too many runs in a short time. Wait a minute, then try again.";
  return error.message || "Couldn't start a run. Try again in a moment.";
}
