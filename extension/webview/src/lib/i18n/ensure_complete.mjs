import fs from 'fs';

let copyContent = fs.readFileSync('copy.ts', 'utf8');

// Extract all CopyKey values
const keyMatch = copyContent.match(/export type CopyKey =\s*([\s\S]*?);/);
const keys = Array.from(keyMatch[1].matchAll(/"([^"]+)"/g)).map(m => m[1]);

// Extract existing keys in zh-CN block value area (between { and })
const zhTableMatch = copyContent.match(/"zh-CN":\s*\{([\s\S]*?)\},\n  "en-US"/);
const zhTableKeys = new Set(Array.from(zhTableMatch[1].matchAll(/(\w+):/g)).map(m => m[1]));

const enTableMatch = copyContent.match(/"en-US":\s*\{([\s\S]*?)\},\n\};/);
const enTableKeys = new Set(Array.from(enTableMatch[1].matchAll(/(\w+):/g)).map(m => m[1]));

function camelToWords(s) {
  return s.replace(/([A-Z])/g, ' $1').replace(/^./, c => c.toUpperCase()).trim();
}

const missingZh = keys.filter(k => !zhTableKeys.has(k));
const missingEn = keys.filter(k => !enTableKeys.has(k));

console.log('Missing zh-CN keys:', missingZh.length);
console.log('Missing en-US keys:', missingEn.length);

if (missingZh.length === 0 && missingEn.length === 0) {
  console.log('All keys present');
  process.exit(0);
}

// Add missing to zh-CN
if (missingZh.length > 0) {
  const zhInsertions = missingZh.map(k => `    ${k}: "${camelToWords(k)}",`).join('\n');
  copyContent = copyContent.replace(
    /("zh-CN":\s*\{[\s\S]*?)\n  \},\n  "en-US"/,
    `$1\n${zhInsertions}\n  },\n  "en-US"`
  );
}

// Add missing to en-US
if (missingEn.length > 0) {
  const enInsertions = missingEn.map(k => `    ${k}: "${camelToWords(k)}",`).join('\n');
  copyContent = copyContent.replace(
    /("en-US":\s*\{[\s\S]*?)\n  \},\n\};/,
    `$1\n${enInsertions}\n  },\n};`
  );
}

fs.writeFileSync('copy.ts', copyContent);
console.log('Patched all missing keys with default English labels');
