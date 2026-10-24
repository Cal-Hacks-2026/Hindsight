// What Droid may do (DECISIONS.md D-003, D-006). The session runs at autonomy Off, so
// every tool call with a side effect asks this handler first: file edits, shell commands,
// web fetch/search, MCP tools, including those made inside a Script or by a Task
// subagent (all verified against droid 0.249). Deny by default:
// - our own MCP tools (server "hindsight") are allowed;
// - file edits are allowed only for extractor files under extractors/ that this run's
//   scan reported as failing, only as in-place updates (no create / delete / move),
//   and only up to a per-run patch budget;
// - everything else (shell, web, other files, other MCP servers) is cancelled.
// Reads, TodoWrite, ToolSearch, Script, and Task run without asking. Droid's environment
// holds no secrets (config.ts scrubEnv) and the repo is public, so reads are harmless.
// We don't also use disabledToolIds: in droid 0.249 any disabled tool hides ApplyPatch.
import { lstatSync } from 'node:fs';
import path from 'node:path';

import { ToolConfirmationOutcome, ToolConfirmationType } from '@factory/droid-sdk/node';
import type { CreateSessionOptions } from '@factory/droid-sdk/node';

export type PermissionRequest = Parameters<NonNullable<CreateSessionOptions['permissionHandler']>>[0];
type ToolUse = PermissionRequest['toolUses'][number];
type Details = ToolUse['details'];

export const MCP_SERVER = 'hindsight';

// Patch text is parsed strictly, so our reading and the CLI's can't disagree about which
// files a patch touches: every line that could be a control line (a `*` after any
// whitespace, control, or invisible format characters, however another parser trims)
// must be exactly one of these, with nothing before it and no Add/Delete/Move.
const PATCH_CONTROL = /^[\s\p{Cc}\p{Cf}\p{Z}]*\*/u;
const PATCH_FRAME = /^\*\*\* (Begin Patch|End Patch|End of File)$/;
const PATCH_UPDATE = /^\*\*\* Update File: (.+)$/;

/** Files a patch's text updates, or why it is refused. */
export function patchTargets(content: string): string[] | { denied: string } {
  const files: string[] = [];
  for (const line of content.split(/\r\n|[\n\r\u2028\u2029]/)) {
    if (!PATCH_CONTROL.test(line) || PATCH_FRAME.test(line)) continue;
    const update = PATCH_UPDATE.exec(line);
    if (!update) return { denied: `patches may only update files in place (${line.trim().slice(0, 80)})` };
    files.push(update[1]);
  }
  return files.length ? files : { denied: 'patch names no file' };
}

export interface Decision {
  outcome: ToolConfirmationOutcome.ProceedOnce | ToolConfirmationOutcome.Cancel;
  denied: string[]; // why, one line per refused call
  edits: string[]; // files an approved request will change
}

export class EditScope {
  private readonly allowed = new Set<string>();
  private approvals = 0;

  constructor(
    readonly dir: string,
    readonly maxPatches: number,
  ) {}

  /** Open these extractor files (basenames from a scan report) for editing. */
  allow(files: string[]): void {
    for (const file of files) {
      if (/^[a-z0-9_]+\.py$/.test(file)) this.allowed.add(path.join(this.dir, file));
    }
  }

  allowedFiles(): string[] {
    return [...this.allowed].map((f) => path.basename(f)).sort();
  }

  private target(filePath: string): string | null {
    const abs = path.resolve(this.dir, filePath);
    return this.allowed.has(abs) && isRegularFile(abs) ? abs : null;
  }

  /** Files this confirmation would change, or a reason it is refused. */
  private check(details: Details): { files: string[] } | { denied: string } {
    switch (details.type) {
      case ToolConfirmationType.McpTool:
        return details.serverName === MCP_SERVER
          ? { files: [] }
          : { denied: `MCP tool ${details.toolName} is not ours` };
      case ToolConfirmationType.Edit: {
        const file = this.target(details.filePath);
        return file ? { files: [file] } : { denied: `edit outside the allowed extractors: ${details.filePath}` };
      }
      case ToolConfirmationType.ApplyPatch: {
        const named = patchTargets(details.patchContent);
        if (!Array.isArray(named)) return named;
        for (const f of details.files ?? []) {
          if (f.operation !== 'update' || f.moveTo !== undefined) {
            return { denied: `patches may only update files in place (${f.filePath})` };
          }
        }
        // The text, the CLI's own parse (files[]), and filePath must all name the same files;
        // a patch the CLI reports no files for is refused.
        const resolve = (f: string) => path.resolve(this.dir, f);
        const fromText = new Set(named.map(resolve));
        const fromCli = new Set((details.files ?? []).map((f) => resolve(f.filePath)));
        const sameFiles = fromCli.size === fromText.size && [...fromCli].every((f) => fromText.has(f));
        if (!sameFiles || !fromText.has(resolve(details.filePath))) {
          return { denied: 'patch text and the files it reports disagree' };
        }
        const outside = named.filter((f) => this.target(f) === null);
        return outside.length
          ? { denied: `patch outside the allowed extractors: ${outside.join(', ')}` }
          : { files: [...fromText] };
      }
      default:
        return { denied: `${details.type} is not allowed` };
    }
  }

  decide(request: PermissionRequest): Decision {
    const confirmations = request.toolUses.flatMap((use) =>
      use.details.type === ToolConfirmationType.Script
        ? use.details.calls.map((call) => call.confirmation as Details)
        : [use.details],
    );
    const denied: string[] = [];
    const edits: string[] = [];
    for (const details of confirmations) {
      const verdict = this.check(details);
      if ('denied' in verdict) denied.push(verdict.denied);
      else edits.push(...verdict.files);
    }
    if (confirmations.length === 0) denied.push('empty permission request');
    if (!denied.length && edits.length && this.approvals >= this.maxPatches) {
      denied.push(`patch budget for this run (${this.maxPatches}) is used up`);
    }
    const offered = request.options.some((o) => o.value === ToolConfirmationOutcome.ProceedOnce);
    if (!denied.length && !offered) denied.push('ProceedOnce was not offered');
    if (denied.length) return { outcome: ToolConfirmationOutcome.Cancel, denied, edits: [] };
    if (edits.length) this.approvals += 1;
    return { outcome: ToolConfirmationOutcome.ProceedOnce, denied, edits };
  }
}

/** Not a symlink (or anything else): the API refuses those too (extract.read_regular). */
function isRegularFile(file: string): boolean {
  try {
    return lstatSync(file).isFile();
  } catch {
    return false;
  }
}
