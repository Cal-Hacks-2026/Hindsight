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
import path from 'node:path';

import { ToolConfirmationOutcome, ToolConfirmationType } from '@factory/droid-sdk/node';
import type { CreateSessionOptions } from '@factory/droid-sdk/node';

export type PermissionRequest = Parameters<NonNullable<CreateSessionOptions['permissionHandler']>>[0];
type ToolUse = PermissionRequest['toolUses'][number];
type Details = ToolUse['details'];

export const MCP_SERVER = 'hindsight';

const PATCH_HEADER = /^\*\*\* (Add|Delete|Update) File: (.+)$/gm;
const PATCH_MOVE = /^\*\*\* Move to: /m;

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
    return this.allowed.has(abs) ? abs : null;
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
        if (PATCH_MOVE.test(details.patchContent)) return { denied: 'patches may not move files' };
        const files: string[] = [];
        for (const [, op, file] of details.patchContent.matchAll(PATCH_HEADER)) {
          if (op !== 'Update') return { denied: `patches may not ${op.toLowerCase()} files (${file})` };
          files.push(file.trim());
        }
        for (const f of details.files ?? []) {
          if (f.operation !== 'update' || f.moveTo !== undefined) {
            return { denied: `patches may only update files in place (${f.filePath})` };
          }
          files.push(f.filePath);
        }
        if (files.length === 0) files.push(details.filePath);
        const targets = files.map((f) => this.target(f));
        const outside = files.filter((_, i) => targets[i] === null);
        return outside.length
          ? { denied: `patch outside the allowed extractors: ${outside.join(', ')}` }
          : { files: [...new Set(targets as string[])] };
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
