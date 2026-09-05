'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const viewPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'resources',
  'ResourcesWorkbenchView.tsx',
);

test('Resources view renders snapshot-backed orientation instead of inferred readiness', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const viewSource = fs.readFileSync(viewPath, 'utf8');
  const viewStart = source.indexOf('const renderResourcesView = () =>');
  const viewEnd = source.indexOf('const renderTrainingView', viewStart);
  assert.ok(viewStart >= 0 && viewEnd > viewStart, 'expected Resources view render');
  const view = source.slice(viewStart, viewEnd);

  assert.match(source, /deriveResourcesOrientation/);
  assert.match(source, /resolveResourcesBindingIds/);
  assert.match(view, /orientation=\{/);
  assert.match(view, /leftoverResourceLibraryListNotLive && resourcesOrientation/);
  assert.match(view, /primaryAction: "open_coach"/);
  assert.match(view, /primaryActionLabel: t\.openCoach/);
  assert.match(view, /leftoverNote=\{leftoverResourceLibraryListNotLive \? t\.leftoverNotLive : undefined\}/);
  assert.match(view, /onOrientationAction=\{handleResourcesOrientationAction\}/);
  assert.doesNotMatch(view, /<CoachOrientationRail/);
  assert.doesNotMatch(
    source.slice(source.indexOf('const resourcesOrientation = useMemo'), viewEnd),
    /canInjectTrainingCard/,
  );

  assert.match(viewSource, /resources-knowledge__current/);
  assert.match(viewSource, /selectedResource\.title/);
  assert.match(viewSource, /resources-knowledge__add-resource/);
  assert.match(viewSource, /resources-knowledge__search/);
  assert.doesNotMatch(viewSource, /className="resources-knowledge__more"/);
  assert.match(viewSource, /resources-library-tree__trash/);
  assert.doesNotMatch(viewSource, /CoachOrientationRail/);
  assert.doesNotMatch(viewSource, /coach-thread-strip--orientation/);
});
