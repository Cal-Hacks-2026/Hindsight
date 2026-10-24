// apps/agent: Hindsight's Droid service (README › "Where Droid runs", DECISIONS.md D-006).
// Triggers: a schedule (AGENT_INTERVAL_MINUTES, default 120) and HTTP from the API
// (POST /agent/run → manual; POST /profiles → profile_created).
import { randomUUID } from 'node:crypto';

import { HindsightApi } from './api.ts';
import { loadConfig, scrubEnv } from './config.ts';
import { RunLog } from './events.ts';
import { runDirect, runJob } from './job.ts';
import { HourlyBudget, QueueFull, RunQueue } from './queue.ts';
import { createAgentServer } from './server.ts';

const config = loadConfig();
const removed = scrubEnv(); // Droid inherits process.env; it gets no secrets but its own API key (passed explicitly)
const api = new HindsightApi(config.apiUrl, config.agentSecret);
const secrets = [config.agentSecret]; // redacted from the public run log (the Factory key always is)
const profileRuns = new HourlyBudget(config.profileRunsPerHour);

const queue = new RunQueue(
  (job) =>
    job.trigger === 'profile_created' && !profileRuns.take()
      ? runDirect(job, { api, secrets })
      : runJob(job, { config, api, secrets }),
  config.queueLimit,
  (job, position) => {
    if (position > 0) void new RunLog(api, job.runId).step(`Queued behind ${position - 1 ? `${position - 1} other run(s) and ` : ''}the current run`);
  },
  config.manualCooldownMs,
);

const server = createAgentServer(queue, config.agentSecret);
server.listen(config.port, config.host, () => {
  console.log(`agent: listening on http://${config.host}:${config.port}; API ${config.apiUrl}; extractors ${config.extractorsDir}`);
  console.log(`agent: removed ${removed.length} variables from Droid's environment`);
});

if (config.intervalMinutes > 0) {
  console.log(`agent: scheduled scans of ${config.campuses.join(', ')} every ${config.intervalMinutes} min`);
  setInterval(() => {
    for (const campus of config.campuses) {
      try {
        queue.enqueue({ runId: randomUUID(), campus, trigger: 'schedule' });
      } catch (e) {
        if (!(e instanceof QueueFull)) throw e;
        console.warn(`agent: skipped scheduled ${campus} scan: ${e.message}`);
      }
    }
  }, config.intervalMinutes * 60_000);
} else {
  console.log('agent: schedule off (AGENT_INTERVAL_MINUTES=0); runs only on demand');
}

for (const signal of ['SIGINT', 'SIGTERM'] as const) {
  process.on(signal, () => {
    server.close();
    process.exit(0);
  });
}
