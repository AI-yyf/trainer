'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const Module = require('node:module');
const path = require('node:path');
const test = require('node:test');

const webviewNodeModules = path.resolve(__dirname, '..', 'webview', 'node_modules');
if (!process.env.NODE_PATH?.split(path.delimiter).includes(webviewNodeModules)) {
  process.env.NODE_PATH = process.env.NODE_PATH
    ? `${webviewNodeModules}${path.delimiter}${process.env.NODE_PATH}`
    : webviewNodeModules;
  Module._initPaths();
}

const typescript = require(path.join(webviewNodeModules, 'typescript'));
const toolCopyPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'coach',
  'coachToolResultCopy.ts',
);
const messagePartsPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'coach',
  'CoachMessageParts.tsx',
);
const activityStripPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'coach',
  'AgentActivityStripSmart.tsx',
);

function loadToolCopy() {
  const previousLoader = Module._extensions['.ts'];
  delete require.cache[toolCopyPath];
  Module._extensions['.ts'] = (loadedModule, filename) => {
    const { outputText } = typescript.transpileModule(fs.readFileSync(filename, 'utf8'), {
      compilerOptions: {
        module: typescript.ModuleKind.CommonJS,
        target: typescript.ScriptTarget.ES2022,
        esModuleInterop: true,
      },
      fileName: filename,
    });
    loadedModule._compile(outputText, filename);
  };

  try {
    return require(toolCopyPath);
  } finally {
    if (previousLoader === undefined) {
      delete Module._extensions['.ts'];
    } else {
      Module._extensions['.ts'] = previousLoader;
    }
    delete require.cache[toolCopyPath];
  }
}

test('generic tool result summaries never reuse HTTP, traceback, or JSON payload prose', () => {
  const { summarizeSafeCoachToolResult } = loadToolCopy();
  const raw = 'HTTP 502: upstream failed\\nTraceback (most recent call last): {"token":"hidden"}';

  assert.equal(
    summarizeSafeCoachToolResult({ summary: raw, note: raw, detail: raw, error: raw }, 'en-US'),
    undefined,
  );
  assert.equal(
    summarizeSafeCoachToolResult({ items: [{ id: 'one' }], summary: raw }, 'en-US'),
    'Found 1 items',
  );
});

test('generic tool result summaries preserve safe summary and note hints', () => {
  const { summarizeSafeCoachToolResult } = loadToolCopy();

  assert.equal(
    summarizeSafeCoachToolResult({ summary: 'Plan anchor found.' }, 'en-US'),
    'Plan anchor found.',
  );
  assert.equal(
    summarizeSafeCoachToolResult({ note: 'Weak spot: recovery truth.' }, 'en-US'),
    'Weak spot: recovery truth.',
  );
});

test('coach tool status UI uses safe summaries and never reads activity error details', () => {
  const partsSource = fs.readFileSync(messagePartsPath, 'utf8');
  const toolResultStart = partsSource.indexOf('case "tool_result": {');
  const toolResultEnd = partsSource.indexOf('    case "reasoning":', toolResultStart);
  const toolResult = partsSource.slice(toolResultStart, toolResultEnd);
  const activitySource = fs.readFileSync(activityStripPath, 'utf8');

  assert.ok(toolResultStart >= 0 && toolResultEnd > toolResultStart, 'expected generic tool result case');
  assert.match(toolResult, /summarizeSafeCoachToolResult\(part\.result, language\)/);
  assert.doesNotMatch(toolResult, /renderJson\(part\.result\)/);
  assert.doesNotMatch(toolResult, /\{part\.error\}/);
  assert.doesNotMatch(toolResult, /\{part\.result\}/);
  assert.doesNotMatch(activitySource, /\.(?:detail|error)\b/);
  assert.match(activitySource, /return copy\.needsRetry;/);
  assert.match(activitySource, /summarizeSafeCoachToolResult\(activity\.result, language\)/);
});
