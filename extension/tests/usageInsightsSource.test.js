'use strict';

// P1 #12 UI half source guards: the Settings → Preferences usage-insights
// disclosure is wired as a read-only webview → sidecar round trip. These
// guards pin the bridge pieces so the round trip cannot silently drop a
// message type, skip the command registration, or ship copy in fewer than
// eight languages.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

function read(...segments) {
  return fs.readFileSync(path.resolve(__dirname, '..', ...segments), 'utf8');
}

const viewSource = read('webview', 'src', 'components', 'settings', 'CoachSettingsView.tsx');
const settingsTextSource = read('webview', 'src', 'components', 'settings', 'settingsText.ts');
const vscodeLibSource = read('webview', 'src', 'lib', 'vscode.ts');
const typesSource = read('webview', 'src', 'lib', 'types.ts');
const registrySource = read('src', 'commands', 'registry.config.ts');
const insightsCommandSource = read('src', 'commands', 'insightsCommands.ts');
const constantsSource = read('src', 'core', 'constants.ts');
const sharedCommandsSource = read('..', 'shared', 'src', 'commands.ts');

// Every user-visible string the disclosure renders must resolve through
// settingsText, which means an eight-language entry in SETTINGS_TEXT (zh-CN
// resolves inline). Guards pin both halves per phrase.
const USAGE_INSIGHTS_PHRASES = [
  ['使用洞察', 'Usage insights'],
  ['只汇总本机事件账本，只读、不联网。', 'Local ledger, read-only. Nothing leaves this machine.'],
  ['近 7 天', 'Last 7 days'],
  ['近 30 天', 'Last 30 days'],
  ['统计区间', 'Window'],
  ['刷新', 'Refresh'],
  ['读取中…', 'Loading…'],
  ['卡片', 'Cards'],
  ['计划', 'Plans'],
  ['证据', 'Evidence'],
  ['练习提交', 'Practice submissions'],
  ['资源', 'Resources'],
  ['反思', 'Reflections'],
  ['教学资产', 'Teaching assets'],
  ['活跃天数', 'Active days'],
  ['连续活跃', 'Day streak'],
  ['每日活跃', 'Daily activity'],
  ['这个区间还没有任何记录。', 'No activity recorded in this window yet.'],
];

const EIGHT_LOCALES = ['en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR'];

test('usage insights: every rendered phrase resolves through settingsText', () => {
  for (const [zh, en] of USAGE_INSIGHTS_PHRASES) {
    assert.match(
      viewSource,
      new RegExp(`settingsText\\(language,\\s*"${zh.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}",`),
      `view must render "${zh}" through settingsText`,
    );
  }
});

test('usage insights: SETTINGS_TEXT carries all seven non-zh locales per phrase', () => {
  for (const [zh, en] of USAGE_INSIGHTS_PHRASES) {
    const key = `${zh}\\u0000${en}`;
    const pattern = new RegExp(`"${key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}":\\s*{([^}]*)}`);
    const match = settingsTextSource.match(pattern);
    assert.ok(match, `SETTINGS_TEXT missing entry for "${zh}"`);
    for (const locale of EIGHT_LOCALES) {
      assert.match(match[1], new RegExp(`"${locale}":`), `"${zh}" missing ${locale}`);
    }
  }
});

test('usage insights: result message survives the host-message schema', () => {
  assert.match(vscodeLibSource, /z\.literal\("insights\/localUsageResult"\)/);
  assert.match(typesSource, /\{ type: "insights\/localUsageResult"; payload: \{ requestId: string; ok: boolean; insights\?: LocalUsageInsights; message\?: string \} \}/);
  // The request helper posts the internal bridge command.
  assert.match(vscodeLibSource, /commandId: trainerCommands\.refreshLocalUsage, payload: \{ requestId, windowDays \}/);
});

test('usage insights: command id is declared once and registered last', () => {
  assert.match(sharedCommandsSource, /refreshLocalUsage: "trainer\.insights\.refreshLocalUsage"/);
  assert.match(constantsSource, /refreshLocalUsage: trainerCommands\.refreshLocalUsage/);
  assert.match(registrySource, /import \{ refreshLocalUsageCommand \} from '\.\/insightsCommands'/);
  assert.match(
    registrySource,
    /\{ commandId: COMMAND_IDS\.refreshLocalUsage, register: \(ctx, payload\) => refreshLocalUsageCommand\(ctx, payload\) \},\s*\];/,
    'registration must stay the last entry so historical order is preserved',
  );
});

test('usage insights: host command is read-only against the local endpoint', () => {
  assert.match(insightsCommandSource, /getJson<unknown>\(\s*status\.port,\s*`\/insights\/local-usage\?window_days=\$\{windowDays\}`/);
  assert.doesNotMatch(insightsCommandSource, /postJson|ensureTrusted/);
  assert.match(insightsCommandSource, /type: 'insights\/localUsageResult'/);
});

test('usage insights: view exposes stable hooks for E2E', () => {
  assert.match(viewSource, /data-settings-subsection="usage-insights"/);
  assert.match(viewSource, /persistenceKey="settings-usage-insights"/);
  assert.match(viewSource, /data-usage-insights-refresh="true"/);
  assert.match(viewSource, /data-usage-insights-error="true"/);
});
