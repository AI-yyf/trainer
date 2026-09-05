import fs from 'fs';

function escapeRegExp(string) {
  return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

const replacements = [
  ['language === "zh-CN" ? "出错了" : "Error"', 't("errorTitle")'],
  ['language === "zh-CN" ? "为什么现在刷这张" : "Why this card now"', 't("whyThisCardNow")'],
  ['language === "zh-CN" ? "上下文" : "Context"', 't("contextLabel")'],
  ['language === "zh-CN" ? "评分规则" : "Rubric"', 't("rubricLabel")'],
  ['language === "zh-CN" ? "常见错误" : "Common mistakes"', 't("commonMistakesLabel")'],
  ['language === "zh-CN" ? "答对" : "Correct"', 't("correctLabel")'],
  ['language === "zh-CN" ? "待加强" : "Needs work"', 't("needsWorkLabel")'],
  ['language === "zh-CN" ? "输入你的答案" : "Type your answer"', 't("typeYourAnswer")'],
  ['language === "zh-CN" ? "现在生成一组" : "Generate now"', 't("generateNow")'],
  ['language === "zh-CN" ? "回到实战" : "Back to practice"', 't("backToPracticeShort")'],
  ['language === "zh-CN" ? "回到工程里练" : "Practice in coach"', 't("practiceInCoach")'],
  ['language === "zh-CN" ? "回到教练对话" : "Open coach"', 't("backToCoachShort")'],
  ['language === "zh-CN" ? "去教练里按这题继续" : "Continue in coach"', 't("continueInCoach")'],
  ['language === "zh-CN" ? "依赖掌握" : "Dependency mastery"', 't("dependencyMasteryLabel")'],
  ['language === "zh-CN" ? "优先补齐的依赖主线" : "Dependency lanes to strengthen"', 't("dependencyLanesToStrengthen")'],
  ['language === "zh-CN" ? "最近反馈" : "Recent feedback"', 't("recentFeedback")'],
  ['language === "zh-CN" ? "用答题结果反推训练" : "Use answers to steer training"', 't("useAnswersToSteerTraining")'],
  ['language === "zh-CN" ? "需要继续用真实场景巩固。" : "Needs more reinforcement in real scenarios."', 't("needsMoreReinforcement")'],
  ['language === "zh-CN" ? "再给一个提示" : "Show next hint"', 't("showNextHint")'],
  ['language === "zh-CN" ? "等待生成卡片" : "Waiting for cards"', 't("waitingForCards")'],
  ['language === "zh-CN" ? "把理论、API 和记忆点压成一张一张卡" : "Turn theory, APIs, and memory gaps into cards"', 't("flashHeroTitle")'],
];

const viewPath = '../../components/flash/CoachFlashView.tsx';
let content = fs.readFileSync(viewPath, 'utf8');

let total = 0;
for (const [search, replace] of replacements) {
  const regex = new RegExp(escapeRegExp(search), 'g');
  const count = (content.match(regex) || []).length;
  if (count > 0) {
    content = content.replace(regex, replace);
    total += count;
    console.log(`Replaced ${count}x: ${search.slice(0, 60)}...`);
  }
}

// Handle template literal patterns
// Pattern: language === "zh-CN" ? `参考答案：${x}` : `Reference: ${x}`
content = content.replace(
  /language === "zh-CN" \? `参考答案：(\$\{[^}]+\})` : `Reference: (\$\{[^}]+\})`/g,
  '`${t("referencePrefix")}$1`'
);

content = content.replace(
  /language === "zh-CN" \? `你的回答：(\$\{[^}]+\})` : `Your answer: (\$\{[^}]+\})`/g,
  '`${t("yourAnswerPrefix")}$1`'
);

content = content.replace(
  /language === "zh-CN" \? `提示 (\$\{[^}]+\})：` : `Hint (\$\{[^}]+\}): `/g,
  '`${t("hintPrefix")}$1: `'
);

fs.writeFileSync(viewPath, content);
console.log(`Total simple replacements: ${total}`);

// Now add new keys to copy.ts if they don't exist
let copyContent = fs.readFileSync('copy.ts', 'utf8');

const keyMatch = copyContent.match(/export type CopyKey =\s*([\s\S]*?);/);
const existingKeys = new Set(Array.from(keyMatch[1].matchAll(/"([^"]+)"/g)).map(m => m[1]));

const newPairs = [
  ["errorTitle", "出错了", "Error"],
  ["whyThisCardNow", "为什么现在刷这张", "Why this card now"],
  ["contextLabel", "上下文", "Context"],
  ["rubricLabel", "评分规则", "Rubric"],
  ["commonMistakesLabel", "常见错误", "Common mistakes"],
  ["correctLabel", "答对", "Correct"],
  ["needsWorkLabel", "待加强", "Needs work"],
  ["typeYourAnswer", "输入你的答案", "Type your answer"],
  ["generateNow", "现在生成一组", "Generate now"],
  ["practiceInCoach", "回到工程里练", "Practice in coach"],
  ["continueInCoach", "去教练里按这题继续", "Continue in coach"],
  ["dependencyMasteryLabel", "依赖掌握", "Dependency mastery"],
  ["dependencyLanesToStrengthen", "优先补齐的依赖主线", "Dependency lanes to strengthen"],
  ["needsMoreReinforcement", "需要继续用真实场景巩固。", "Needs more reinforcement in real scenarios."],
  ["showNextHint", "再给一个提示", "Show next hint"],
  ["flashHeroTitle", "把理论、API 和记忆点压成一张一张卡", "Turn theory, APIs, and memory gaps into cards"],
  ["referencePrefix", "参考答案：", "Reference: "],
  ["yourAnswerPrefix", "你的回答：", "Your answer: "],
  ["hintPrefix", "提示 ", "Hint "],
];

const trulyNew = newPairs.filter(([k]) => !existingKeys.has(k));
console.log('New keys to add:', trulyNew.length);

if (trulyNew.length > 0) {
  // Add to CopyKey type
  const typeEnd = copyContent.indexOf(';', copyContent.indexOf('export type CopyKey'));
  const insertions = trulyNew.map(([k]) => `  | "${k}"`).join('\n');
  copyContent = copyContent.slice(0, typeEnd) + '\n' + insertions + copyContent.slice(typeEnd);

  // Add to zh-CN
  const zhBlock = copyContent.match(/"zh-CN":\s*\{([\s\S]*?)\n  \},\n  "en-US"/);
  const zhInsertions = trulyNew.map(([k, zh]) => `    ${k}: "${zh}",`).join('\n');
  copyContent = copyContent.replace(
    /("zh-CN":\s*\{[\s\S]*?)\n  \},\n  "en-US"/,
    `$1\n${zhInsertions}\n  },\n  "en-US"`
  );

  // Add to en-US
  const enInsertions = trulyNew.map(([k, , en]) => `    ${k}: "${en}",`).join('\n');
  copyContent = copyContent.replace(
    /("en-US":\s*\{[\s\S]*?)\n  \},\n\};/,
    `$1\n${enInsertions}\n  },\n};`
  );

  fs.writeFileSync('copy.ts', copyContent);
  console.log('Added new keys to copy.ts');
}
