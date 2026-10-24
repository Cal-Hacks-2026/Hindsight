import assert from 'node:assert/strict';
import { mkdtempSync, realpathSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test } from 'node:test';

import { ToolConfirmationOutcome as O, ToolConfirmationType as T } from '@factory/droid-sdk/node';

import { EditScope, type PermissionRequest } from '../src/policy.ts';

// Real files: the scope refuses targets that aren't regular files (symlinks included).
const DIR = realpathSync(mkdtempSync(path.join(tmpdir(), 'extractors-')));
for (const name of ['localist.py', 'devpost.py', 'x.py', 'page_function.js']) writeFileSync(path.join(DIR, name), '');
const OPTIONS = [O.ProceedOnce, O.ProceedAlways, O.Cancel].map((value) => ({ value, label: value }));

function request(...details: unknown[]): PermissionRequest {
  return { options: OPTIONS, toolUses: details.map((d) => ({ details: d })) } as unknown as PermissionRequest;
}

const patch = (file: string, op = 'Update') => ({
  type: T.ApplyPatch,
  filePath: file,
  fileName: file,
  patchContent: `*** Begin Patch\n*** ${op} File: ${file}\n@@\n-a\n+b\n*** End Patch`,
  files: [{ filePath: file, operation: op.toLowerCase() }], // the CLI's own parse
});

function scope(): EditScope {
  const s = new EditScope(DIR, 2);
  s.allow(['localist.py']);
  return s;
}

test('allows our own MCP tools and nothing else by default', () => {
  const s = new EditScope(DIR, 2);
  assert.equal(s.decide(request({ type: T.McpTool, toolName: 'scan_campus', serverName: 'hindsight' })).outcome, O.ProceedOnce);
  assert.equal(s.decide(request({ type: T.McpTool, toolName: 'x', serverName: 'other' })).outcome, O.Cancel);
  assert.equal(s.decide(request({ type: T.Execute, command: 'ls', fullCommand: 'ls' })).outcome, O.Cancel);
  assert.equal(s.decide(request(patch(`${DIR}/localist.py`))).outcome, O.Cancel, 'nothing editable before a scan reports failures');
});

test('allows in-place patches to a failing extractor only', () => {
  const s = scope();
  const ok = s.decide(request(patch(`${DIR}/localist.py`)));
  assert.equal(ok.outcome, O.ProceedOnce);
  assert.deepEqual(ok.edits, [`${DIR}/localist.py`]);
  assert.equal(s.decide(request(patch('localist.py'))).outcome, O.ProceedOnce, 'relative to the extractors folder');
});

test('refuses edits outside the scope', () => {
  const cases = [
    patch(`${DIR}/devpost.py`), // not failing in this run
    patch(`${DIR}/page_function.js`),
    patch(`${DIR}/../normalize.py`),
    patch('/srv/app/.env'),
    patch(`${DIR}/localist.py`, 'Add'),
    patch(`${DIR}/localist.py`, 'Delete'),
    { ...patch(`${DIR}/localist.py`), patchContent: `*** Update File: ${DIR}/localist.py\n*** Move to: ${DIR}/x.py\n` },
    { ...patch(`${DIR}/localist.py`), patchContent: `*** Update File: ${DIR}/localist.py\n*** Update File: /srv/app/apps/api/app/main.py\n` },
    { ...patch(`${DIR}/localist.py`), files: [{ filePath: `${DIR}/localist.py`, fileName: 'localist.py', operation: 'delete' }] },
    { type: T.Create, filePath: `${DIR}/new.py`, fileName: 'new.py', content: '' },
    { type: T.Edit, filePath: '/etc/hosts', fileName: 'hosts' },
  ];
  for (const details of cases) {
    const d = scope().decide(request(details));
    assert.equal(d.outcome, O.Cancel, JSON.stringify(details));
    assert.ok(d.denied.length > 0);
  }
});

test('a script batch is allowed only if every call is', () => {
  const script = (...calls: unknown[]) => ({ type: T.Script, calls: calls.map((confirmation) => ({ confirmation })) });
  assert.equal(scope().decide(request(script(patch(`${DIR}/localist.py`)))).outcome, O.ProceedOnce);
  assert.equal(
    scope().decide(request(script(patch(`${DIR}/localist.py`), { type: T.Execute, command: 'curl', fullCommand: 'curl x' }))).outcome,
    O.Cancel,
  );
});

test('enforces the per-run patch budget', () => {
  const s = scope();
  assert.equal(s.decide(request(patch('localist.py'))).outcome, O.ProceedOnce);
  assert.equal(s.decide(request(patch('localist.py'))).outcome, O.ProceedOnce);
  const third = s.decide(request(patch('localist.py')));
  assert.equal(third.outcome, O.Cancel);
  assert.match(third.denied[0], /budget/);
  assert.equal(s.decide(request({ type: T.McpTool, toolName: 'rescan', serverName: 'hindsight' })).outcome, O.ProceedOnce);
});

test('only plain extractor basenames can be opened', () => {
  const s = new EditScope(DIR, 2);
  s.allow(['../main.py', 'page_function.js', 'devpost.py']);
  assert.deepEqual(s.allowedFiles(), ['devpost.py']);
});

test('cancels when ProceedOnce is not offered', () => {
  const req = { ...request(patch('localist.py')), options: [{ value: O.Cancel, label: 'no' }] } as PermissionRequest;
  assert.equal(scope().decide(req).outcome, O.Cancel);
});

test('refuses to patch a symlink, even under an allowed name', () => {
  const s = new EditScope(DIR, 2);
  symlinkSync(path.join(DIR, 'x.py'), path.join(DIR, 'linked.py'));
  s.allow(['linked.py']);
  assert.equal(s.decide(request(patch(`${DIR}/linked.py`))).outcome, O.Cancel);
});

test('patch text is parsed strictly, and must agree with what the CLI reports', () => {
  const ok = patch(`${DIR}/localist.py`);
  const withText = (patchContent: string) => ({ ...ok, patchContent });
  const denied = (d: unknown) => scope().decide(request(d)).outcome === O.Cancel;
  assert.equal(denied(withText(ok.patchContent.replaceAll('\n', '\r\n'))), false, 'CRLF is fine');
  for (const sneaky of [
    `*** Begin Patch\n*** Update File: ${DIR}/localist.py\n@@\n-a\n+b\n  *** Add File: ${DIR}/new.py\n+x\n*** End Patch`,
    `*** Begin Patch\n***Update File: ${DIR}/../normalize.py\n@@\n-a\n+b\n*** End Patch`,
    `*** Begin Patch\n*** Update File: ${DIR}/localist.py\n*** Move to: ${DIR}/x.py\n*** End Patch`,
    `*** Begin Patch\n@@\n-a\n+b\n*** End Patch`,
    // Prefixes \s doesn't cover but another parser's trim might: NEL, zero-width space, BOM, a control char.
    ...['\u0085', '\u200b', '\ufeff', '\u0001'].map(
      (p) => `*** Begin Patch\n*** Update File: ${DIR}/localist.py\n@@\n-a\n+b\n${p}*** Add File: ${DIR}/new.py\n*** End Patch`,
    ),
    // A context line's single leading space doesn't hide a header from a parser that trims.
    `*** Begin Patch\n*** Update File: ${DIR}/localist.py\n@@\n-a\n+b\n *** Add File: ${DIR}/new.py\n*** End Patch`,
  ]) {
    assert.ok(denied(withText(sneaky)), sneaky);
  }
  assert.ok(denied({ ...ok, files: [{ filePath: `${DIR}/x.py`, operation: 'update' }] }), 'files[] names another file');
  assert.ok(denied({ ...ok, filePath: `${DIR}/x.py` }), 'filePath names another file');
  assert.ok(denied({ ...ok, files: undefined }), 'no files[] from the CLI');
  assert.ok(denied({ ...ok, files: [] }), 'empty files[] from the CLI');
  assert.ok(denied({ ...ok, filePath: undefined }), 'no filePath from the CLI');
  assert.equal(denied({ ...ok, files: [{ filePath: `${DIR}/localist.py`, operation: 'update' }] }), false);
  // Hunk lines that start with `*` after the prefix are code, not headers.
  const starred = `*** Begin Patch\n*** Update File: ${DIR}/localist.py\n@@\n def f(\n **kwargs,\n     *args,\n-    *rest,\n+    **extra,\n )\n*** End Patch`;
  assert.equal(denied(withText(starred)), false, 'context and changed lines with * or ** are fine');
});
