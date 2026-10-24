// Client for the API's /internal/agent/* endpoints (apps/api/app/routers/internal_agent.py).
import type { Campus } from './config.ts';

export type EventKind = 'plan' | 'step' | 'diff' | 'result' | 'error';
export type SourceStatus = 'ok' | 'empty' | 'extractor_error' | 'fetch_failed' | 'missing';

export interface SourceReport {
  source_id: string;
  kind: string;
  extractor: string;
  status: SourceStatus;
  parsed: number;
  kept: number;
  error?: string | null;
}

export interface ScanReport {
  apify_run_id: string;
  stored: number;
  skipped: Record<string, number>;
  sources: SourceReport[];
}

export interface AlertsReport {
  alerts: { opportunity_id: string; title: string; url: string; when: string; new: boolean }[];
  new: number;
  rule: string;
}

export interface RankReport {
  profiles: { ranked: number; top: unknown[] }[]; // no profile ids: this reaches the public log
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
  }
}

const SCAN_TIMEOUT_MS = 12 * 60_000; // an Apify run is capped at 10 minutes
const DEFAULT_TIMEOUT_MS = 3 * 60_000; // ranking may ask Claude for reasons

export class HindsightApi {
  constructor(
    private readonly baseUrl: string,
    private readonly secret: string,
    private readonly fetchImpl: typeof fetch = fetch,
  ) {}

  private async call<T>(method: 'GET' | 'POST', path: string, body?: unknown, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<T> {
    let res: Response;
    try {
      res = await this.fetchImpl(`${this.baseUrl}${path}`, {
        method,
        headers: { 'content-type': 'application/json', 'x-agent-secret': this.secret },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: AbortSignal.timeout(timeoutMs),
      });
    } catch (e) {
      throw new ApiError(`API unreachable: ${(e as Error).message}`);
    }
    const text = await res.text();
    if (!res.ok) {
      let detail = text.slice(0, 300);
      try {
        detail = JSON.parse(text).detail ?? detail;
      } catch {
        // not JSON; keep the text
      }
      throw new ApiError(`${method} ${path} → ${res.status}: ${detail}`, res.status);
    }
    return JSON.parse(text) as T;
  }

  scan(campus: Campus): Promise<ScanReport> {
    return this.call('POST', '/internal/agent/scan', { campus }, SCAN_TIMEOUT_MS);
  }

  rescan(campus: Campus, apifyRunId: string): Promise<ScanReport> {
    return this.call('POST', '/internal/agent/rescan', { campus, apify_run_id: apifyRunId });
  }

  raw(apifyRunId: string, sourceId: string): Promise<unknown> {
    const q = new URLSearchParams({ apify_run_id: apifyRunId, source_id: sourceId });
    return this.call('GET', `/internal/agent/raw?${q}`);
  }

  rank(campus: Campus, profileId?: string): Promise<RankReport> {
    return this.call('POST', '/internal/agent/rank', { campus, profile_id: profileId ?? null });
  }

  alerts(campus: Campus, profileId?: string): Promise<AlertsReport> {
    return this.call('POST', '/internal/agent/alerts', { campus, profile_id: profileId ?? null });
  }

  event(runId: string, kind: EventKind, message: string, payload?: unknown): Promise<{ ok: true }> {
    return this.call('POST', '/internal/agent/events', { run_id: runId, kind, message, payload });
  }
}
