'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'app',
  'App.tsx',
);
const browserSidecarSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'browserSidecar.ts',
);
const coachSettingsViewSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'settings',
  'CoachSettingsView.tsx',
);

function readAppSource() {
  return fs.readFileSync(appSourcePath, 'utf8');
}

function readBrowserSidecarSource() {
  return fs.readFileSync(browserSidecarSourcePath, 'utf8');
}

function readCoachSettingsViewSource() {
  return fs.readFileSync(coachSettingsViewSourcePath, 'utf8');
}

test('host-message subscription requests the bootstrap once, outside applyHostMessage identity churn', () => {
  const source = readAppSource();

  // The subscription effect must dispatch through a ref and run once: keying it
  // on `applyHostMessage` re-ran `requestBootstrapOnce` on every layout/settings
  // state change and re-posted `request/bootstrap`, which the live browser
  // preview answered with a repeating POST /memory/settings + GET /memory/summary
  // round trip (the observed save/poll loop).
  assert.match(
    source,
    /const applyHostMessageRef = useRef\(applyHostMessage\);\s*useEffect\(\(\) => \{\s*applyHostMessageRef\.current = applyHostMessage;\s*\}, \[applyHostMessage\]\);\s*useEffect\(\(\) => \{\s*const unsubscribe = subscribeToHostMessages\(\(message\) => \{\s*applyHostMessageRef\.current\(message\);\s*\}\);\s*requestBootstrapOnce\(\);\s*return unsubscribe;\s*\}, \[\]\);/,
  );

  // The ref keeps the latest dispatcher; nothing else may re-run the request.
  assert.match(source, /applyHostMessageRef\.current = applyHostMessage;/);
  assert.doesNotMatch(source, /subscribeToHostMessages\(\(message\) => \{\s*applyHostMessage\(message\);\s*\}\);\s*requestBootstrapOnce\(\);\s*return unsubscribe;\s*\}, \[applyHostMessage\]\)/);
});

test('bootstrap request guard re-arms only on the false -> true host-state transition', () => {
  const source = readAppSource();

  // In browser preview `hasReceivedHostState` starts true; an unconditional
  // reset disarmed `bootstrapRequestSent` on mount so every later
  // `requestBootstrapOnce` call re-posted the request.
  assert.match(
    source,
    /const hostStateReceivedOnceRef = useRef\(hasReceivedHostState\);\s*useEffect\(\(\) => \{\s*if \(!hasReceivedHostState\) \{\s*return;\s*\}\s*if \(hostStateReceivedOnceRef\.current\) \{\s*return;\s*\}\s*hostStateReceivedOnceRef\.current = true;\s*bootstrapRequestSent = false;\s*\}, \[hasReceivedHostState\]\);/,
  );
});

test('live browser preview bootstrap runs once per mount with ref-stable callbacks', () => {
  const source = readAppSource();

  const effectStart = source.indexOf('browserPreviewBootstrapDepsRef = useRef(');
  assert.ok(effectStart > 0, 'expected the browser preview bootstrap deps ref');

  const effectDeps = source.indexOf('}, [isBrowserPreview]);', effectStart);
  assert.ok(effectDeps > effectStart, 'expected the bootstrap effect to be keyed on isBrowserPreview only');

  const effectSource = source.slice(effectStart, effectDeps);
  assert.match(effectSource, /fetchBrowserPreviewBootstrap\(bootstrapSessionId\)/);
  assert.match(effectSource, /dispatchHostMessage\(message\)/);
  assert.match(effectSource, /hostMessageSequenceRef\.current !== requestSequence/);
  assert.doesNotMatch(
    effectSource,
    /\}, \[\s*applyBrowserPreviewLocationOverrides,\s*applyHostMessage,\s*isBrowserPreview,\s*previewSessionId,\s*setOperationMessage,\s*\]\)/,
  );
});

test('live bootstrap fetches collapse concurrent requests into one sidecar round trip', () => {
  const source = readBrowserSidecarSource();

  assert.match(source, /let inFlightLiveBootstrap: Promise<\{ sessionId: string; message: HostMessage \}> \| null = null;/);
  assert.match(source, /if \(inFlightLiveBootstrap && inFlightLiveBootstrapKey === dedupeKey\) \{\s*return inFlightLiveBootstrap;\s*\}/);
  assert.match(source, /inFlightLiveBootstrap = request;/);
  assert.match(
    source,
    /finally \{\s*if \(inFlightLiveBootstrapKey === dedupeKey\) \{\s*inFlightLiveBootstrap = null;\s*inFlightLiveBootstrapKey = "";\s*\}\s*\}/,
  );
});

test('persistCoachSettings skips the save when the payload already matches the saved snapshot', () => {
  const source = readAppSource();

  // The equality baseline must be the last server-applied snapshot
  // (`data.memory.workspace`), never the optimistic layout state, which already
  // reflects pending user changes and would suppress real saves.
  const persistStart = source.indexOf('const persistCoachSettings = useCallback(');
  assert.ok(persistStart > 0, 'expected persistCoachSettings');
  const persistEnd = source.indexOf('const handleSuggestedAction', persistStart);
  assert.ok(persistEnd > persistStart, 'expected persistCoachSettings body bounds');

  const persistSource = source.slice(persistStart, persistEnd);
  assert.match(persistSource, /const savedWorkspaceSettings = data\.memory\.workspace;/);
  assert.match(persistSource, /const matchesSavedSettings = Boolean\(/);
  assert.match(persistSource, /matchesSavedCoachDefaults\(payload\.coachDefaults, savedWorkspaceSettings\.coachDefaults\)/);
  assert.match(persistSource, /if \(matchesSavedSettings\) \{\s*return;\s*\}/);
  assert.match(persistSource, /postMessage\(\{\s*type: "settings\/saveCoach",\s*payload,\s*\}\);/);
  assert.match(persistSource, /saveBrowserPreviewCoachSettings\(payload, previewSessionId\)/);

  // Sparse snapshots never block an explicit save: undefined snapshot fields
  // count as matching, missing coach defaults always force the write.
  assert.match(
    source,
    /function matchesSavedCoachDefaults\(\s*next: CoachDefaults,\s*saved:\s*\|?\s*\(Partial<CoachDefaults>[^\n]*\)\s*\| undefined,\s*\): boolean \{\s*if \(!saved\) \{\s*return false;\s*\}/,
  );
});

test('settings save handlers stay user-intent only with no persisting effects', () => {
  const settingsSource = readCoachSettingsViewSource();
  const appSource = readAppSource();

  // Every useEffect body in CoachSettingsView must avoid invoking the save or
  // onChange persistence handlers: persistence happens in click handlers only.
  const effectBodies = [];
  const effectPattern = /useEffect\(\(\) => \{([\s\S]*?)\}, \[[^\]]*\]\);/g;
  let match = effectPattern.exec(settingsSource);
  while (match) {
    effectBodies.push(match[1]);
    match = effectPattern.exec(settingsSource);
  }
  assert.ok(effectBodies.length > 0, 'expected useEffect hooks in CoachSettingsView');
  for (const body of effectBodies) {
    assert.doesNotMatch(body, /onSaveCoachSettings|persistCoachSettings|saveBrowserPreviewCoachSettings/);
  }

  // App must not persist coach settings from an effect either.
  assert.doesNotMatch(appSource, /useEffect\(\(\) => \{[^}]*persistCoachSettings\(/);
});
