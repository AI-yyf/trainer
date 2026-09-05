const fs = require('fs');
let content = fs.readFileSync('copy.ts', 'utf8');

// Extract CopyKey union type
const keyMatch = content.match(/export type CopyKey =\s*([\s\S]*?);/);
if (!keyMatch) { console.error('No CopyKey found'); process.exit(1); }
const keyBlock = keyMatch[1];
const keys = Array.from(keyBlock.matchAll(/"([^"]+)"/g)).map(m => m[1]);
console.log('Total CopyKey entries:', keys.length);

// Extract existing keys in zh-CN table
const zhMatch = content.match(/"zh-CN":\s*\{([\s\S]*?)\n  \},?\n  "en-US"/);
if (!zhMatch) { console.error('No zh-CN block found'); process.exit(1); }
const zhBlock = zhMatch[1];
const existingZh = new Set(Array.from(zhBlock.matchAll(/"([^"]+)":/g)).map(m => m[1]));

const missing = keys.filter(k => !existingZh.has(k));
console.log('Missing keys in zh-CN:', missing.length);

// Extract existing keys in en-US table
const enMatch = content.match(/"en-US":\s*\{([\s\S]*?)\n  \}/);
if (!enMatch) { console.error('No en-US block found'); process.exit(1); }
const enBlock = enMatch[1];
const existingEn = new Set(Array.from(enBlock.matchAll(/"([^"]+)":/g)).map(m => m[1]));
const missingEn = keys.filter(k => !existingEn.has(k));
console.log('Missing keys in en-US:', missingEn.length);

if (missing.length === 0 && missingEn.length === 0) {
  console.log('All keys present');
  process.exit(0);
}

// A helper to insert missing keys into a block
function patchBlock(content, blockName, missingKeys) {
  const pattern = new RegExp(`("${blockName}":\\s*\\{)([\\s\\S]*?)(\\n  \\})`);
  const match = content.match(pattern);
  if (!match) { console.error('No', blockName, 'block'); return content; }
  const lines = match[2].split('\n');
  const insertionIndex = lines.length; // append before last brace
  for (const key of missingKeys) {
    lines.splice(insertionIndex, 0, `    "${key}": "",`);
  }
  const newBlock = lines.join('\n');
  return content.replace(pattern, `$1${newBlock}$3`);
}

content = patchBlock(content, 'zh-CN', missing);
content = patchBlock(content, 'en-US', missingEn);

fs.writeFileSync('copy.ts', content);
console.log('Patched');
