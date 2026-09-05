'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const panelSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'firstlook',
  'FirstLookSummaryPanel.tsx',
);
const copyPath = path.resolve(__dirname, '..', 'webview', 'src', 'lib', 'i18n', 'copy.ts');

test('first look summary panel supports a compact coach context', () => {
  const source = fs.readFileSync(panelSourcePath, 'utf8');

  assert.match(source, /compact\?: boolean;/);
  assert.match(source, /compact = false/);
  assert.match(source, /compact \? "firstlook-panel--compact" : null/);
  assert.match(source, /!\s*compact \?\s*\(/);
  assert.match(source, /compact \? <span className="firstlook-panel__context">\{t\("firstLookBadge"\)\}<\/span> : null/);
});

test('first look turns internal classifier values into localized reader-facing labels', () => {
  const source = fs.readFileSync(panelSourcePath, 'utf8');

  assert.match(source, /const FIRST_LOOK_LABELS: Record<ComposerLanguage, FirstLookLabels> = \{/);
  for (const language of ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    assert.match(source, new RegExp(`"${language}": \\{`));
  }
  for (const classifierValue of [
    'empty_new_project',
    'existing_engineering',
    'mixed_uncertain',
    'web_app',
    'api_service',
    'desktop_app',
    'config_dotfiles',
    'unknown',
  ]) {
    assert.match(source, new RegExp(`${classifierValue}:`));
  }
  assert.match(source, /humanizeUnknownClassification\(summary\.projectTypeGuess, unknownProjectType\)/);
  assert.match(source, /humanizeUnknownClassification\(summary\.folderRole, unknownProjectType\)/);
  assert.match(source, /\{folderRoleText\}<\/span>/);
  assert.doesNotMatch(source, /\{summary\.folderRole\}<\/span>/);
  assert.doesNotMatch(source, /summary\.projectTypeGuess \|\|/);
});

test('first look keeps Chinese, Japanese, and Korean labels readable', () => {
  const source = fs.readFileSync(panelSourcePath, 'utf8');
  const labelsStart = source.indexOf('const FIRST_LOOK_LABELS');
  const labelsEnd = source.indexOf('\nfunction humanizeUnknownClassification', labelsStart);

  assert.ok(labelsStart >= 0 && labelsEnd > labelsStart, 'expected first-look label table');
  const labels = source.slice(labelsStart, labelsEnd);
  assert.match(labels, /empty_new_project: "\u65b0\u5efa\u9879\u76ee"/);
  assert.match(labels, /empty_new_project: "\u65b0\u3057\u3044\u30d7\u30ed\u30b8\u30a7\u30af\u30c8"/);
  assert.match(labels, /empty_new_project: "\uc0c8 \ud504\ub85c\uc81d\ud2b8"/);
  assert.match(labels, /unknown: "\u672a\u786e\u8ba4"/);
  assert.match(labels, /unknown: "\u4e0d\u660e"/);
  assert.match(labels, /unknown: "\uc54c \uc218 \uc5c6\uc74c"/);
  assert.doesNotMatch(labels, /\u93c9|\u979b|\u9774/);
});

test('first look keeps its recommended next step visible before optional details', () => {
  const source = fs.readFileSync(panelSourcePath, 'utf8');
  const nextStep = source.indexOf('className="firstlook-panel__next-step"');
  const header = source.indexOf('className="firstlook-panel__header firstlook-panel__header--actionable"');
  const details = source.indexOf('{expanded && hasBodyData ?');

  assert.ok(nextStep >= 0, 'expected an always-visible next-step row');
  assert.ok(nextStep < header, 'expected the next step before the disclosure control');
  assert.ok(header < details, 'expected details to remain secondary');
  assert.match(source, /\{summary\.recommendedNextStep\}/);
});

test('first look uses plain-language labels in every supported locale', () => {
  const source = fs.readFileSync(copyPath, 'utf8');

  for (const label of [
    '项目概览',
    'Project overview',
    'Resumen del proyecto',
    'Aperçu du projet',
    'Projektüberblick',
    'プロジェクト概要',
    '프로젝트 개요',
    'Visão geral do projeto',
  ]) {
    assert.match(source, new RegExp(`firstLookBadge: "${label}"`));
  }
  assert.match(source, /firstLookDirectoryAnchors: "重点位置"/);
  assert.match(source, /firstLookDirectoryAnchors: "Key locations"/);
});
