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
const commandsRegistryConfigPath = path.resolve(
  __dirname,
  '..',
  'src',
  'commands',
  'registry.config.ts',
);
const extensionSrcRoot = path.resolve(__dirname, '..', 'src');

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

test('only previewResourceCommand posts /sandbox/preview and opts invent via conversation', () => {
  const source = fs.readFileSync(resourceCommandsPath, 'utf8');
  const registryConfigSource = fs.readFileSync(commandsRegistryConfigPath, 'utf8');

  const previewPosts = source.match(/\/sandbox\/preview/g) ?? [];
  assert.equal(previewPosts.length, 1, 'expected a single /sandbox/preview host call site');

  assert.match(source, /export async function previewResourceCommand\(/);
  assert.match(
    source,
    /attachPreviewAssetUris\(\s*\{\s*\/\/ Pass conversation[\s\S]*?conversation:\s*current\.conversation/,
  );

  const attachCalls = [...source.matchAll(/attachPreviewAssetUris\(/g)];
  assert.equal(attachCalls.length, 7, 'expected seven attachPreviewAssetUris call sites');

  // Two live preview paths opt into inventing a conversation file_preview:
  // the sandbox preview and the canonical Markdown digest of a library
  // document. Both live inside previewResourceCommand; no other command may
  // pass conversation.
  const previewStart = source.indexOf('export async function previewResourceCommand');
  assert.ok(previewStart >= 0, 'missing previewResourceCommand');
  const previewEnd = source.indexOf('\nexport ', previewStart + 1);
  const previewSlice = source.slice(previewStart, previewEnd > previewStart ? previewEnd : source.length);
  assert.equal(
    (previewSlice.match(/conversation:\s*current\.conversation/g) ?? []).length,
    2,
    'only the live preview path may pass conversation to invent',
  );

  assert.match(
    registryConfigSource,
    /COMMAND_IDS\.previewSandbox,\s*register:\s*\(ctx,\s*payload\)\s*=>\s*previewResourceCommand\(ctx,\s*payload\)/,
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

test('no other extension/src file posts /sandbox/preview or calls attachPreviewAssetUris', () => {
  const files = collectTsFiles(extensionSrcRoot);
  const previewCallers = [];
  const attachCallers = [];

  for (const file of files) {
    const text = fs.readFileSync(file, 'utf8');
    if (text.includes('/sandbox/preview')) {
      previewCallers.push(path.relative(extensionSrcRoot, file));
    }
    if (text.includes('attachPreviewAssetUris(') || text.includes('attachPreviewAssetUris,')) {
      // Definition + import + call sites are allowed only in these two files.
      attachCallers.push(path.relative(extensionSrcRoot, file));
    }
  }

  assert.deepEqual(previewCallers, [path.join('commands', 'resourceCommands.ts')]);
  assert.deepEqual(
    attachCallers.sort(),
    [path.join('commands', 'resourceCommands.ts'), path.join('core', 'previewAssetUris.ts')].sort(),
  );
});
