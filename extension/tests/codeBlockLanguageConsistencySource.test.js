'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const coachDirectory = path.resolve(__dirname, '..', 'webview', 'src', 'components', 'coach');
const copyPath = path.join(coachDirectory, 'codeBlockCopy.ts');
const richCodeBlockPath = path.join(coachDirectory, 'RichCodeBlock.tsx');
const richContentPath = path.join(coachDirectory, 'MessageRichContent.tsx');
const messageBubblePath = path.join(coachDirectory, 'CoachMessageBubble.tsx');
const messagePartsPath = path.join(coachDirectory, 'CoachMessageParts.tsx');
const artifactBlockPath = path.join(coachDirectory, 'CoachArtifactBlock.tsx');
const languages = ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR'];

test('code block copy feedback is complete across all supported languages', () => {
  const copySource = fs.readFileSync(copyPath, 'utf8');
  const richCodeBlockSource = fs.readFileSync(richCodeBlockPath, 'utf8');
  const richContentSource = fs.readFileSync(richContentPath, 'utf8');

  assert.match(copySource, /const codeBlockCopy: Record<ComposerLanguage, CodeBlockCopy> = \{/);
  for (const [index, language] of languages.entries()) {
    const start = copySource.indexOf(`"${language}": {`);
    const nextLanguage = languages[index + 1];
    const end = nextLanguage ? copySource.indexOf(`"${nextLanguage}": {`, start + 1) : copySource.length;

    assert.ok(start >= 0 && end > start, `expected ${language} code block copy`);
    const localeCopy = copySource.slice(start, end);
    for (const key of ['code', 'copy', 'copied']) {
      assert.match(localeCopy, new RegExp(`${key}:`), `expected ${language}.${key}`);
    }
  }

  assert.match(copySource, /export function resolveCodeBlockCopy\(language: ComposerLanguage\)/);
  assert.match(richCodeBlockSource, /import \{ resolveCodeBlockCopy \} from "\.\/codeBlockCopy";/);
  assert.match(richCodeBlockSource, /const copy = resolveCodeBlockCopy\(language\);/);
  assert.match(richContentSource, /import \{ resolveCodeBlockCopy \} from "\.\/codeBlockCopy";/);
  assert.match(richContentSource, /const codeBlockCopy = resolveCodeBlockCopy\(language\);/);
});

test('coach message paths keep the selected language all the way to code renderers', () => {
  const bubbleSource = fs.readFileSync(messageBubblePath, 'utf8');
  const partsSource = fs.readFileSync(messagePartsPath, 'utf8');
  const artifactSource = fs.readFileSync(artifactBlockPath, 'utf8');

  assert.doesNotMatch(bubbleSource, /narrowLanguage/);
  assert.match(bubbleSource, /<MessageRichContent[\s\S]*?language=\{language\}/);
  assert.match(bubbleSource, /<CoachMessageParts parts=\{visibleParts \?\? \[\]\} language=\{language\}/);
  assert.match(bubbleSource, /<CoachArtifactBlock[\s\S]*?language=\{language\}/);
  assert.match(partsSource, /language\?: ComposerLanguage;/);
  assert.match(artifactSource, /language\?: ComposerLanguage;/);
  assert.match(partsSource, /<RichCodeBlock[\s\S]*?language=\{language\}/);
  assert.match(artifactSource, /<MessageRichContent body=\{artifact\.summary\} language=\{language\}/);
});
