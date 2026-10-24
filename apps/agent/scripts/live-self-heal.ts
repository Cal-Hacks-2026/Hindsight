// Live check of the self-healing loop against the real Droid CLI (uses Factory credits).
//   npm run smoke:live        (needs FACTORY_API_KEY; reads the repo-root .env)
// Copies extractors/ to a temp folder, breaks localist.py the way a site redesign
// would (the feed's "events" key becomes "results"), stubs our API, and runs one job.
// Nothing touches Supabase, Apify, or the real extractors folder.
import { cp, mkdtemp, readFile, realpath, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import type { ScanReport } from '../src/api.ts';
import { runJob } from '../src/job.ts';

const REAL = fileURLToPath(new URL('../../api/app/services/radar/extractors', import.meta.url));
const apiKey = process.env.FACTORY_API_KEY;
if (!apiKey) throw new Error('FACTORY_API_KEY is not set');

const dir = await realpath(await mkdtemp(path.join(tmpdir(), 'hindsight-extractors-')));
await cp(REAL, dir, { recursive: true });
const file = path.join(dir, 'localist.py');
const original = await readFile(file, 'utf8');
const sample = { json: { results: [{ event: { title: 'Intro to PyTorch', status: 'live', localist_url: 'https://events.sjsu.edu/event/intro-to-pytorch', event_instances: [{ event_instance: { start: '2026-11-02T13:00:00-08:00' } }] } }], page: { current: 1, total: 1 } } };

const fixedNow = async () => (await readFile(file, 'utf8')).includes('results');
const report = async (): Promise<ScanReport> => ({
  apify_run_id: 'liveSmoke1', stored: 0, skipped: {},
  sources: [{ source_id: 'sjsu-events-ai-tech', kind: 'localist', extractor: 'localist.py', ...((await fixedNow()) ? { status: 'ok', parsed: 1, kept: 1 } : { status: 'empty', parsed: 0, kept: 0 }) }],
});
const events: { kind: string; message: string; payload?: unknown }[] = [];

try {
  await runJob(
    { runId: '00000000-0000-4000-8000-00000000beef', campus: 'sjsu', trigger: 'manual' },
    {
      config: { factoryApiKey: apiKey, droidPath: fileURLToPath(new URL('../node_modules/.bin/droid', import.meta.url)), extractorsDir: dir, modelId: process.env.DROID_MODEL || undefined, maxPatchesPerRun: 4, runTimeoutMs: 10 * 60_000 },
      api: {
        scan: report,
        rescan: report,
        raw: async (_r, source_id) => ({ source_id, kind: 'localist', extractor: 'localist.py', items: [{ sourceId: source_id, campus: 'sjsu', contentType: 'application/json', ...sample }] }),
        rank: async () => ({ profiles: [] }),
        alerts: async () => ({ alerts: [], new: 0, rule: 'top 5 ranked, deadline or start within 7 days' }),
        event: async (_id, kind, message, payload) => (events.push({ kind, message, payload }), { ok: true }),
      },
    },
  );
  const diffs = events.filter((e) => e.kind === 'diff');
  console.log(`\n${events.length} events; ${diffs.length} diff(s); kinds: ${[...new Set(events.map((e) => e.kind))].join(', ')}`);
  for (const d of diffs) console.log((d.payload as { diff: string }).diff);
  const changed = (await readFile(file, 'utf8')) !== original;
  console.log(`localist.py changed: ${changed}; fixed: ${await fixedNow()}`);
  await writeFile(path.join(tmpdir(), 'hindsight-live-self-heal.json'), JSON.stringify(events, null, 2));
  if (!changed || !diffs.length) process.exitCode = 1;
} finally {
  await rm(dir, { recursive: true, force: true });
}
