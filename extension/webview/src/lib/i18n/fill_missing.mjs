import fs from 'fs';

let content = fs.readFileSync('copy.ts', 'utf8');
const missing = JSON.parse(fs.readFileSync('missing_keys.json', 'utf8'));

function camelToWords(s) {
  return s.replace(/([A-Z])/g, ' $1').replace(/^./, (c) => c.toUpperCase()).trim();
}

// Insert missing keys into zh-CN block with English fallback (to be translated later)
const zhStart = content.indexOf('"zh-CN": {');
const zhEnd = content.indexOf('"en-US": {');
const zhBlock = content.slice(zhStart, zhEnd);
const zhLines = zhBlock.split('\n');
const zhLastBraceIdx = zhLines.findIndex((l) => l.trim() === '},');
const zhInsertIdx = zhLastBraceIdx >= 0 ? zhLastBraceIdx : zhLines.length;
for (const key of missing) {
  zhLines.splice(zhInsertIdx, 0, `    ${key}: "${camelToWords(key)}",`);
}
const newZhBlock = zhLines.join('\n');
content = content.slice(0, zhStart) + newZhBlock + content.slice(zhEnd);

// Insert missing keys into en-US block
const enStart = content.indexOf('"en-US": {');
const enBlock = content.slice(enStart);
const enLines = enBlock.split('\n');
const enLastBraceIdx = enLines.findIndex((l) => l.trim() === '},');
const enInsertIdx = enLastBraceIdx >= 0 ? enLastBraceIdx : enLines.length;
for (const key of missing) {
  enLines.splice(enInsertIdx, 0, `    ${key}: "${camelToWords(key)}",`);
}
const newEnBlock = enLines.join('\n');
content = content.slice(0, enStart) + newEnBlock;

// Change as Record<...> to satisfies Record<...>
content = content.replace(
  /as Record<ComposerLanguage, Record<CopyKey, string>>/,
  'satisfies Record<ComposerLanguage, Record<CopyKey, string>>'
);

fs.writeFileSync('copy.ts', content);
console.log('Patched', missing.length, 'missing keys with default English labels');
console.log('Changed as Record to satisfies Record');
