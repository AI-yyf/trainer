import fs from 'fs';

const viewPath = '../../components/flash/CoachFlashView.tsx';
let viewContent = fs.readFileSync(viewPath, 'utf8');

// Define translations that should be in copyTable
// Each entry: [chinese, english, suggestedKey]
const translations = [
  ['把理论、API 和记忆点压成一张一张卡', 'Turn theory, APIs, and memory gaps into cards', 'flashHeroTitle'],
  ['等待生成卡片', 'Waiting for cards', 'waitingForCards'],
  ['出错了', 'Error', 'errorTitle'],
  ['为什么现在刷这张', 'Why this card now', 'whyThisCardNow'],
  ['上下文', 'Context', 'contextLabel'],
  ['评分规则', 'Rubric', 'rubricLabel'],
  ['常见错误', 'Common mistakes', 'commonMistakesLabel'],
  ['答对', 'Correct', 'correctLabel'],
  ['待加强', 'Needs work', 'needsWorkLabel'],
  ['输入你的答案', 'Type your answer', 'typeYourAnswer'],
  ['现在生成一组', 'Generate now', 'generateNow'],
  ['回到实战', 'Back to practice', 'backToPracticeShort'],
  ['回到教练对话', 'Open coach', 'backToCoachShort'],
  ['去教练里按这题继续', 'Continue in coach', 'continueInCoach'],
  ['依赖掌握', 'Dependency mastery', 'dependencyMasteryLabel'],
  ['优先补齐的依赖主线', 'Dependency lanes to strengthen', 'dependencyLanesToStrengthen'],
  ['需要继续用真实场景巩固。', 'Needs more reinforcement in real scenarios.', 'needsMoreReinforcement'],
  ['最近反馈', 'Recent feedback', 'recentFeedback'],
  ['用答题结果反推训练', 'Use answers to steer training', 'useAnswersToSteerTraining'],
  ['你的回答：', 'Your answer: ', 'yourAnswerPrefix'],
  ['提示 ', 'Hint ', 'hintPrefix'],
  ['再给一个提示', 'Show next hint', 'showNextHint'],
  ['回到工程里练', 'Practice in coach', 'practiceInCoach'],
  ['参考答案：', 'Reference: ', 'referencePrefix'],
];

// Replace simple ternary patterns (no template literals with variables inside)
for (const [zh, en, key] of translations) {
  // Escape special regex chars
  const escapedZh = zh.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const escapedEn = en.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

  // Pattern: language === "zh-CN" ? "中文字符串" : "英文字符串"
  const pattern1 = new RegExp(
    `language === "zh-CN" \\? "${escapedZh}" : "${escapedEn}"`,
    'g'
  );
  viewContent = viewContent.replace(pattern1, `t("${key}")`);

  // Pattern: language === "zh-CN" ? `中文字符串${...}` : `英文字符串${...}`
  // These need manual handling, skip for now
}

// Also fix cases where the ternary has template literals with variables
// Pattern: {language === "zh-CN" ? `参考答案：${currentCard.expectedAnswer}` : `Reference: ${currentCard.expectedAnswer}`}
viewContent = viewContent.replace(
  /\{language === "zh-CN" \? `中文字符串（\$\{[^}]+\})` : `英文字符串（\$\{[^}]+\})`\}/g,
  (match) => {
    // Extract the Chinese and English parts
    const zhMatch = match.match(/zh-CN" \? `([^`]+)`/);
    const enMatch = match.match(/: `([^`]+)`/);
    if (!zhMatch || !enMatch) return match;
    // Build using template literal with t() for static parts
    const zhPart = zhMatch[1].replace(/\$\{([^}]+)\}/g, '${$1}');
    return `{\`\${t("referencePrefix")}${zhPart.replace(/^[^$]+/, '')}\`}`;
  }
);

// Simpler approach: handle the reference prefix case manually
viewContent = viewContent.replace(
  /\{language === "zh-CN" \? `参考答案：(\$\{[^}]+\})` : `Reference: (\$\{[^}]+\})`\}/g,
  '{`${t("referencePrefix")}$1`}'
);

viewContent = viewContent.replace(
  /\{language === "zh-CN" \? `提示 (\$\{[^}]+\})：` : `Hint (\$\{[^}]+\}): `/g,
  '{`${t("hintPrefix")}$1: `}'
);

viewContent = viewContent.replace(
  /\{language === "zh-CN" \? `你的回答：(\$\{[^}]+\})` : `Your answer: (\$\{[^}]+\})`\}/g,
  '{`${t("yourAnswerPrefix")}$1`}'
);

fs.writeFileSync(viewPath, viewContent);
console.log('Replaced CoachFlashView inline translations');

// Now add new keys to copy.ts
let copyContent = fs.readFileSync('copy.ts', 'utf8');

// Extract existing CopyKey keys
const keyMatch = copyContent.match(/export type CopyKey =\s*([\s\S]*?);/);
const existingKeys = new Set(Array.from(keyMatch[1].matchAll(/"([^"]+)"/g)).map(m => m[1]));

let addedCount = 0;
const newKeys = [];
for (const [, , key] of translations) {
  if (!existingKeys.has(key)) {
    newKeys.push(key);
    addedCount++;
  }
}

if (addedCount > 0) {
  // Add new keys to CopyKey type
  const typeEndPos = copyContent.indexOf(';', copyContent.indexOf('export type CopyKey'));
  const keyInsertions = newKeys.map(k => `  | "${k}"`).join('\n');
  copyContent = copyContent.slice(0, typeEndPos) + '\n' + keyInsertions + copyContent.slice(typeEndPos);

  // Add new keys to zh-CN block
  const zhBlock = copyContent.match(/"zh-CN":\s*\{([\s\S]*?)\n  \},\n  "en-US"/);
  if (zhBlock) {
    const zhInsertions = newKeys.map(k => {
      const t = translations.find(t => t[2] === k);
      return `    ${k}: "${t[0]}",`;
    }).join('\n');
    copyContent = copyContent.replace(
      /("zh-CN":\s*\{[\s\S]*?)\n  \},\n  "en-US"/,
      `$1\n${zhInsertions}\n  },\n  "en-US"`
    );
  }

  // Add new keys to en-US block
  const enBlock = copyContent.match(/"en-US":\s*\{([\s\S]*?)\n  \},?\n\};?/);
  if (enBlock) {
    const enInsertions = newKeys.map(k => {
      const t = translations.find(t => t[2] === k);
      return `    ${k}: "${t[1]}",`;
    }).join('\n');
    copyContent = copyContent.replace(
      /("en-US":\s*\{[\s\S]*?)\n  \},\n\};/,
      `$1\n${enInsertions}\n  },\n};`
    );
  }

  fs.writeFileSync('copy.ts', copyContent);
  console.log('Added', addedCount, 'new keys to copy.ts');
}
