import fs from 'fs';

let content = fs.readFileSync('copy.ts', 'utf8');

// 1. Ensure these keys are in CopyKey type
const requiredKeys = [
  'useAnswersToSteerTraining', 'errorTitle', 'rubricLabel', 'commonMistakesLabel',
  'correctLabel', 'needsWorkLabel', 'typeYourAnswer', 'dependencyMasteryLabel',
  'needsMoreReinforcement', 'referencePrefix', 'yourAnswerPrefix', 'hintPrefix',
  'submissionLoading'
];

// Check existing keys
const keyMatch = content.match(/export type CopyKey =([\s\S]*?);/);
const existingKeys = new Set(Array.from(keyMatch[1].matchAll(/"([^"]+)"/g)).map(m => m[1]));
const missingKeys = requiredKeys.filter(k => !existingKeys.has(k));
console.log('Missing CopyKey entries:', missingKeys.length);

if (missingKeys.length > 0) {
  const typeEnd = content.indexOf(';', content.indexOf('export type CopyKey'));
  const insertions = missingKeys.map(k => `  | "${k}"`).join('\n');
  content = content.slice(0, typeEnd) + '\n' + insertions + content.slice(typeEnd);
}

// 2. Ensure these keys are in zh-CN block
const zhPairs = missingKeys.map(k => {
  const defaults: Record<string, [string, string]> = {
    useAnswersToSteerTraining: ['Use answers to steer training', 'Use answers to steer training'],
    errorTitle: ['出错了', 'Error'],
    rubricLabel: ['评分规则', 'Rubric'],
    commonMistakesLabel: ['常见错误', 'Common mistakes'],
    correctLabel: ['答对', 'Correct'],
    needsWorkLabel: ['待加强', 'Needs work'],
    typeYourAnswer: ['输入你的答案', 'Type your answer'],
    dependencyMasteryLabel: ['依赖掌握', 'Dependency mastery'],
    needsMoreReinforcement: ['需要继续用真实场景巩固。', 'Needs more reinforcement in real scenarios.'],
    referencePrefix: ['参考答案：', 'Reference: '],
    yourAnswerPrefix: ['你的回答：', 'Your answer: '],
    hintPrefix: ['提示 ', 'Hint '],
    submissionLoading: ['提交中…', 'Submitting…'],
  };
  return defaults[k] || [k, k];
});

if (zhPairs.length > 0) {
  const zhInsertions = zhPairs.map(([zh]) => `    ${zhPairs.map(([zh]) => zh).join('\n')}`).join('\n');
  // This logic is broken, let's do it properly
}

// Proper approach: find zh-CN block and append missing keys
const zhBlockMatch = content.match(/"zh-CN":\s*\{([\s\S]*?)\n  \},\n  "en-US"/);
if (zhBlockMatch) {
  const zhLines = zhBlockMatch[1].split('\n');
  const existingZhKeys = new Set(zhLines.map(l => (l.match(/(\w+):/) || [])[1]).filter(Boolean));
  const zhMissing = zhPairs.filter(([_, __, k]) => !existingZhKeys.has(k));
  
  if (zhMissing.length > 0) {
    const zhInsertLines = zhMissing.map(([zh, _en, key]) => `    ${key}: "${zh}",`).join('\n');
    content = content.replace(
      /("zh-CN":\s*\{[\s\S]*?)\n  \},\n  "en-US"/,
      `$1\n${zhInsertLines}\n  },\n  "en-US"`
    );
  }
}

// 3. Ensure keys are in en-US block
const enBlockMatch = content.match(/"en-US":\s*\{([\s\S]*?)\n  \},\n\};/);
if (enBlockMatch) {
  const enLines = enBlockMatch[1].split('\n');
  const existingEnKeys = new Set(enLines.map(l => (l.match(/(\w+):/) || [])[1]).filter(Boolean));
  const enMissing = zhPairs.filter(([_, __, k]) => !existingEnKeys.has(k));
  
  if (enMissing.length > 0) {
    const enInsertLines = enMissing.map(([_zh, en, key]) => `    ${key}: "${en}",`).join('\n');
    content = content.replace(
      /("en-US":\s*\{[\s\S]*?)\n  \},\n\};/,
      `$1\n${enInsertLines}\n  },\n};`
    );
  }
}

fs.writeFileSync('copy.ts', content);
console.log('Added missing keys to copy.ts');
