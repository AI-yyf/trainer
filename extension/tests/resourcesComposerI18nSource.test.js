const assert = require('node:assert/strict');
const test = require('node:test');
const { load, read } = require('./templateAssertions');

test('Resources uses the localized shared composer, including all eight languages', () => {
  const { unifiedComposerCopy } = load('lib/i18n/unifiedComposerCopy.ts');
  assert.equal(Object.keys(unifiedComposerCopy).length, 8);
  for (const copy of Object.values(unifiedComposerCopy)) assert.ok(copy.resourcePrompt.trim());
  const app = read('app/App.tsx');
  assert.match(app, /appUiCopy\(layout\.composerLanguage, "找资料"\)/);
  assert.match(app, /submittedSearchQuery=\{resourcesViewSearchQuery\}/);
  assert.doesNotMatch(app, /setResourcesComposerMode/);
});
