// Environment → config. Read once at startup; main.ts then scrubs secrets from
// process.env, because the Droid SDK passes process.env on to the droid subprocess.
import { readFileSync, realpathSync, rmSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

export const CAMPUSES = ['sjsu', 'berkeley'] as const;
export type Campus = (typeof CAMPUSES)[number];

export interface Config {
  apiUrl: string;
  agentSecret: string;
  factoryApiKey: string;
  host: string;
  port: number;
  intervalMinutes: number; // 0 turns the schedule off
  campuses: Campus[];
  extractorsDir: string;
  droidPath: string;
  modelId?: string;
  maxPatchesPerRun: number;
  runTimeoutMs: number;
  queueLimit: number;
  manualCooldownMs: number;
  profileRunsPerHour: number;
}

const DEFAULT_EXTRACTORS = fileURLToPath(new URL('../../api/app/services/radar/extractors', import.meta.url));
const DEFAULT_DROID = fileURLToPath(new URL('../node_modules/.bin/droid', import.meta.url));

function int(env: NodeJS.ProcessEnv, name: string, fallback: number, min = 0): number {
  const raw = env[name];
  if (raw === undefined || raw === '') return fallback;
  const value = Number(raw);
  if (!Number.isInteger(value) || value < min) throw new Error(`${name} must be an integer ≥ ${min}`);
  return value;
}

function required(env: NodeJS.ProcessEnv, name: string): string {
  const value = env[name]?.trim();
  if (!value) throw new Error(`${name} is not set`);
  return value;
}

/**
 * AGENT_SECRET, or in the container AGENT_SECRET_FILE: read once, then deleted. Droid runs
 * as the agent's OS user and could read /proc/<agent pid>/environ, which keeps the
 * process's original environment even after scrubEnv(); a file passed this way is gone
 * before Droid starts.
 */
function agentSecret(env: NodeJS.ProcessEnv): string {
  const file = env.AGENT_SECRET_FILE;
  if (!file) return required(env, 'AGENT_SECRET');
  const secret = readFileSync(file, 'utf8').trim();
  rmSync(file, { force: true });
  if (!secret) throw new Error('AGENT_SECRET_FILE is empty');
  return secret;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  const campuses = (env.AGENT_CAMPUSES ?? 'sjsu,berkeley')
    .split(',')
    .map((c) => c.trim())
    .filter(Boolean);
  for (const c of campuses) {
    if (!(CAMPUSES as readonly string[]).includes(c)) throw new Error(`AGENT_CAMPUSES: unknown campus ${c}`);
  }
  return {
    apiUrl: (env.AGENT_API_URL ?? 'http://127.0.0.1:8000').replace(/\/+$/, ''),
    agentSecret: agentSecret(env),
    factoryApiKey: required(env, 'FACTORY_API_KEY'),
    host: env.AGENT_HOST ?? '127.0.0.1',
    port: int(env, 'AGENT_PORT', 8787, 1),
    intervalMinutes: int(env, 'AGENT_INTERVAL_MINUTES', 120),
    campuses: campuses as Campus[],
    extractorsDir: realpathSync(env.EXTRACTORS_DIR ?? DEFAULT_EXTRACTORS),
    droidPath: env.DROID_PATH ?? DEFAULT_DROID,
    modelId: env.DROID_MODEL || undefined,
    maxPatchesPerRun: int(env, 'AGENT_MAX_PATCHES', 4),
    runTimeoutMs: int(env, 'AGENT_RUN_TIMEOUT_MINUTES', 20, 1) * 60_000,
    queueLimit: int(env, 'AGENT_QUEUE_LIMIT', 10, 1),
    manualCooldownMs: int(env, 'AGENT_MANUAL_COOLDOWN_MINUTES', 2) * 60_000,
    profileRunsPerHour: int(env, 'AGENT_PROFILE_RUNS_PER_HOUR', 6),
  };
}

// Everything else is removed from process.env before Droid starts (see main.ts).
const SAFE_ENV = new Set(['PATH', 'HOME', 'USER', 'LOGNAME', 'SHELL', 'TERM', 'LANG', 'TZ', 'TMPDIR', 'NODE_ENV']);

export function scrubEnv(env: NodeJS.ProcessEnv = process.env): string[] {
  const removed = Object.keys(env).filter((k) => !SAFE_ENV.has(k) && !k.startsWith('LC_'));
  for (const key of removed) delete env[key];
  return removed;
}
