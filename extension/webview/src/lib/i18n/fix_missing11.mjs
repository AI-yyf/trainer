import fs from 'fs';

let content = fs.readFileSync('copy.ts', 'utf8');

const missingPairs = [
  ['errorTitle', '出错了', 'Error'],
  ['rubricLabel', '评分规则', 'Rubric'],
  ['commonMistakesLabel', '常见错误', 'Common mistakes'],
  ['correctLabel', '答对', 'Correct'],
  ['needsWorkLabel', '待加强', 'Needs work'],
  ['typeYourAnswer', '输入你的答案', 'Type your answer'],
  ['dependencyMasteryLabel', '依赖掌握', 'Dependency mastery'],
  ['needsMoreReinforcement', '需要继续用真实场景巩固。', 'Needs more reinforcement in real scenarios.'],
  ['referencePrefix', '参考答案：', 'Reference: '],
  ['yourAnswerPrefix', '你的回答：', 'Your answer: '],
  ['hintPrefix', '提示 ', 'Hint '],
];

// Add to zh-CN block (before the closing "en-US")
const zhInsertions = missingPairs.map(([k, zh]) => `    ${k}: "${zh}",`).join('\n');
content = content.replace(
  /("zh-CN":\s*\{[\s\S]*?)\n  \},\n  "en-US"/,
  `$1\n${zhInsertions}\n  },\n  "en-US"`
);

// Add to en-US block
const enInsertions = missingPairs.map(([k, , en]) => `    ${k}: "${en}",`).join('\n');
content = content.replace(
  /("en-US":\s*\{[\s\S]*?)\n  \},\n\};/,
  `$1\n${enInsertions}\n  },\n};`
);

fs.writeFileSync('copy.ts', content);
console.log('Added 11 keys to both zh-CN and en-US blocks');
