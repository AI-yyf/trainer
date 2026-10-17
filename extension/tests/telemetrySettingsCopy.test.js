'use strict';

/**
 * P2 #18: the telemetry consent surface's copy contract.
 *
 * All six strings exist in all eight languages, and no non-Chinese locale
 * silently falls back to the zh source (a missing translation would ship
 * Chinese into a foreign locale's Settings sheet).
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const Module = require('node:module');

const webviewRoot = path.resolve(__dirname, '..', 'webview', 'src');
const esbuild = require('../webview/node_modules/esbuild');

function compileAndLoad(entryPoint) {
  const compiled = esbuild.buildSync({
    entryPoints: [entryPoint], bundle: true, platform: 'node', format: 'cjs', write: false,
  });
  const mod = new Module(entryPoint, module);
  mod.filename = entryPoint;
  mod.paths = Module._nodeModulePaths(path.dirname(entryPoint));
  mod._compile(compiled.outputFiles[0].text, entryPoint);
  return mod.exports;
}

const copyModule = compileAndLoad(path.join(webviewRoot, 'components', 'settings', 'telemetrySettingsCopy.ts'));

const LANGUAGES = ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR'];
const KEYS = ['title', 'detail', 'rowLabel', 'stateOn', 'stateOff', 'stateUnknown'];

test('telemetry consent copy is complete in all eight languages', () => {
  for (const language of LANGUAGES) {
    const copy = copyModule.telemetrySettingsCopy(language);
    for (const key of KEYS) {
      assert.equal(typeof copy[key], 'string', `${language}:${key} missing`);
      assert.ok(copy[key].length >= 6, `${language}:${key} too short`);
    }
  }
});

test('non-Chinese locales are actually translated (no zh fallback)', () => {
  for (const language of LANGUAGES) {
    if (language === 'zh-CN') continue;
    const copy = copyModule.telemetrySettingsCopy(language);
    const zhCopy = copyModule.telemetrySettingsCopy('zh-CN');
    for (const key of KEYS) {
      assert.notEqual(copy[key], zhCopy[key], `${language}:${key} fell back to the zh string`);
    }
  }
});

test('zh-CN uses the source strings', () => {
  const copy = copyModule.telemetrySettingsCopy('zh-CN');
  assert.equal(copy.title, '匿名遥测（可选）');
  assert.equal(copy.stateOff, '已关闭 · 不收集任何数据');
});
