'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const repoRoot = path.resolve(__dirname, '..', '..');

const {
  DEFAULT_SMART_CONTEXT_WINDOW_TOKENS,
  DEFAULT_SMART_MAX_OUTPUT_TOKENS,
  SMART_CONTEXT_WINDOW_PRESETS,
  SMART_MAX_OUTPUT_PRESETS,
  formatCompactTokenLimit,
  inferModelDefaultTokenLimits,
  resolveEffectiveTokenBudgetProfile,
} = require(path.resolve(repoRoot, 'extension', 'dist', 'shared', 'src', 'smartTokenBudget.js'));

const { trainerSkillCatalog } = require(
  path.resolve(repoRoot, 'extension', 'dist', 'shared', 'src', 'skillCatalog.js'),
);

test('smartTokenBudget defaults modern models to 1M context without 977K glitch', () => {
  assert.equal(DEFAULT_SMART_CONTEXT_WINDOW_TOKENS, 1_000_000);
  assert.equal(DEFAULT_SMART_MAX_OUTPUT_TOKENS, 65_536);

  assert.equal(formatCompactTokenLimit(1_000_000), '1M');
  assert.equal(formatCompactTokenLimit(1_048_576), '1M');
  assert.equal(formatCompactTokenLimit(2_000_000), '2M');
  assert.equal(formatCompactTokenLimit(131_072), '128K');
  assert.equal(formatCompactTokenLimit(65_536), '64K');
  assert.equal(formatCompactTokenLimit(undefined), '');

  assert.ok(SMART_CONTEXT_WINDOW_PRESETS.includes(1_000_000));
  assert.ok(SMART_MAX_OUTPUT_PRESETS.includes(65_536));

  const minimaxLimits = inferModelDefaultTokenLimits({ model: 'MiniMax-M3.1-Flash' });
  assert.equal(minimaxLimits.contextWindowTokens, 1_000_000);
  assert.equal(minimaxLimits.maxOutputTokens, 131_072);

  const genericLimits = inferModelDefaultTokenLimits({ model: '' });
  assert.equal(genericLimits.contextWindowTokens, 1_000_000);
  assert.equal(genericLimits.maxOutputTokens, 65_536);
});

test('smart thinking budget coordinates safely below effectiveMaxOutputTokens', () => {
  const highCapProfile = resolveEffectiveTokenBudgetProfile({
    model: 'MiniMax-M3.1-Flash',
    configuredContextWindowTokens: 1_000_000,
    configuredMaxOutputTokens: 131_072,
  });
  assert.equal(highCapProfile.effectiveContextWindowTokens, 1_000_000);
  assert.ok(highCapProfile.thinkingBudget.max < highCapProfile.effectiveMaxOutputTokens);
  assert.ok(highCapProfile.thinkingBudget.high <= highCapProfile.thinkingBudget.max);
  assert.ok(highCapProfile.thinkingBudget.recommendedCustom <= highCapProfile.thinkingBudget.max);
  assert.ok(highCapProfile.thinkingBudget.presets.every((v) => v <= highCapProfile.thinkingBudget.max));

  const cappedProfile = resolveEffectiveTokenBudgetProfile({
    model: 'custom-8k-model',
    configuredContextWindowTokens: 64_000,
    configuredMaxOutputTokens: 8_192,
  });
  assert.ok(cappedProfile.thinkingBudget.max < 8_192);
  assert.ok(cappedProfile.thinkingBudget.high <= cappedProfile.thinkingBudget.max);
  assert.ok(cappedProfile.thinkingBudget.presets.every((v) => v <= cappedProfile.thinkingBudget.max));
});

test('skillCatalog exposes $image and $organize skills and webview CSP allows inline visuals', () => {
  const triggers = new Set(trainerSkillCatalog.map((item) => item.trigger));
  assert.ok(triggers.has('$image'));
  assert.ok(triggers.has('$organize'));

  const webviewContentSource = fs.readFileSync(
    path.join(repoRoot, 'extension', 'src', 'core', 'webviewContent.ts'),
    'utf8',
  );
  assert.match(webviewContentSource, /img-src[\s\S]*http:\/\/127\.0\.0\.1:\*/);
  assert.match(webviewContentSource, /img-src[\s\S]*http:\/\/localhost:\*/);
  assert.match(webviewContentSource, /img-src[\s\S]*data:\s*blob:/);

  const richContentSource = fs.readFileSync(
    path.join(repoRoot, 'extension', 'webview', 'src', 'components', 'coach', 'MessageRichContent.tsx'),
    'utf8',
  );
  assert.match(richContentSource, /export function markdownUrlTransform/);
  assert.match(richContentSource, /SAFE_IMAGE_DATA_URL_RE/);
  assert.match(richContentSource, /export function MessageImageGallery/);
  assert.match(richContentSource, /urlTransform=\{markdownUrlTransform\}/);

  const settingsSource = fs.readFileSync(
    path.join(repoRoot, 'extension', 'webview', 'src', 'components', 'settings', 'CoachSettingsView.tsx'),
    'utf8',
  );
  assert.doesNotMatch(settingsSource, /Math\.round\([^)]*\/\s*1024\)/);
  assert.match(settingsSource, /SMART_CONTEXT_WINDOW_PRESETS/);
  assert.match(settingsSource, /SMART_MAX_OUTPUT_PRESETS/);
});
