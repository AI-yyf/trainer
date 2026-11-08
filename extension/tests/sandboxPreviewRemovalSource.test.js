'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const resourceCommandsPath = path.resolve(
  __dirname,
  '..',
  'src',
  'commands',
  'resourceCommands.ts',
);
const extensionSrcRoot = path.resolve(__dirname, '..', 'src');
const sharedCommandsPath = path.resolve(__dirname, '..', '..', 'shared', 'src', 'commands.ts');

function collectTsFiles(dir, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      collectTsFiles(full, out);
      continue;
    }
    if (entry.name.endsWith('.ts')) {
      out.push(full);
    }
  }
  return out;
}

test('the extension exposes no Trainer-owned resource preview lane', () => {
  const files = collectTsFiles(extensionSrcRoot);
  const previewCallers = files.filter((file) => fs.readFileSync(file, 'utf8').includes('/sandbox/preview'));
  const previewSymbols = files.filter((file) => {
    const text = fs.readFileSync(file, 'utf8');
    return text.includes('previewResourceCommand') || text.includes('previewSandbox');
  });

  assert.deepEqual(previewCallers, [], 'no extension file may call /sandbox/preview');
  assert.deepEqual(previewSymbols, [], 'no extension file may register a preview command');
  assert.doesNotMatch(
    fs.readFileSync(sharedCommandsPath, 'utf8'),
    /previewSandbox/,
    'the shared command catalog must not expose trainer.sandbox.preview',
  );
});

test('mkdir refresh delete leftover dumps call attachPreviewAssetUris without conversation', () => {
  const source = fs.readFileSync(resourceCommandsPath, 'utf8');

  const failClosedFns = [
    'createSandboxDirectoryCommand',
    'deleteSandboxPathCommand',
    'refreshSandboxCommand',
    'refreshSandboxSelectionFromPreview',
    'applySandboxRootChange',
  ];

  for (const fn of failClosedFns) {
    const start = source.indexOf(`function ${fn}`);
    assert.ok(start >= 0, `missing ${fn}`);
    const nextExport = source.indexOf('\nexport ', start + 1);
    const nextAsync = source.indexOf('\nasync function ', start + 1);
    const candidates = [nextExport, nextAsync].filter((value) => value > start);
    const end = candidates.length > 0 ? Math.min(...candidates) : source.length;
    const slice = source.slice(start, end);
    assert.match(slice, /attachPreviewAssetUris\(/, `${fn} must call attachPreviewAssetUris`);
    assert.doesNotMatch(
      slice,
      /conversation:\s*current\.conversation/,
      `${fn} must omit conversation (fail-closed invent)`,
    );
  }
});
