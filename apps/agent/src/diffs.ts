// Snapshots of extractors/ so every change Droid makes is recorded as a unified diff.
import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';

import { createTwoFilesPatch } from 'diff';

export type Snapshot = Map<string, string>;

export interface FileDiff {
  file: string;
  diff: string;
  added: number;
  removed: number;
}

export async function snapshot(dir: string): Promise<Snapshot> {
  const out: Snapshot = new Map();
  for (const name of (await readdir(dir)).sort()) {
    if (/\.(py|js)$/.test(name)) out.set(name, await readFile(path.join(dir, name), 'utf8'));
  }
  return out;
}

/** Diffs from `before` to the folder as it is now; updates `before` to now. */
export async function changesSince(before: Snapshot, dir: string): Promise<FileDiff[]> {
  const now = await snapshot(dir);
  const out: FileDiff[] = [];
  for (const name of new Set([...before.keys(), ...now.keys()])) {
    const a = before.get(name) ?? '';
    const b = now.get(name) ?? '';
    if (a === b) continue;
    const diff = createTwoFilesPatch(`a/${name}`, `b/${name}`, a, b, '', '', { context: 3 });
    const lines = diff.split('\n').slice(2);
    out.push({
      file: name,
      diff,
      added: lines.filter((l) => l.startsWith('+') && !l.startsWith('+++')).length,
      removed: lines.filter((l) => l.startsWith('-') && !l.startsWith('---')).length,
    });
  }
  before.clear();
  for (const [k, v] of now) before.set(k, v);
  return out;
}
