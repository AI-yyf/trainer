import fs from 'fs';

let content = fs.readFileSync('copy.ts', 'utf8');

// Extract keys from CopyKey type
const keyMatch = content.match(/export type CopyKey =([\s\S]*?);/);
const keys = Array.from(keyMatch[1].matchAll(/"([^"]+)"/g)).map(m => m[1]);

function camelToWords(s) {
  return s.replace(/([A-Z])/g, ' $1').replace(/^./, c => c.toUpperCase()).trim();
}

// Extract existing keys from zh-CN block
const zhStartIdx = content.indexOf('"zh-CN": {');
const zhMidIdx = content.indexOf('"en-US": {');
const zhBlock = content.slice(zhStartIdx, zhMidIdx);
const zhExisting = new Set(Array.from(zhBlock.matchAll(/(\w+):/g)).map(m => m[1]));

const zhMissing = keys.filter(k => !zhExisting.has(k));
console.log('Missing in zh-CN:', zhMissing.length);

// Extract existing keys from en-US block
const enStartIdx = zhMidIdx;
const enBlock = content.slice(enStartIdx);
const enExisting = new Set(Array.from(enBlock.matchAll(/(\w+):/g)).map(m => m[1]));

const enMissing = keys.filter(k => !enExisting.has(k));
console.log('Missing in en-US:', enMissing.length);

if (zhMissing.length === 0 && enMissing.length === 0) {
  console.log('All keys present');
  process.exit(0);
}

// Insert missing keys into zh-CN block (before the closing "},")
const zhCloseIdx = content.indexOf('\n  },\n  "en-US"', zhStartIdx);
if (zhCloseIdx > 0) {
  const zhInserts = zhMissing.map(k => `    ${k}: "${camelToWords(k)}",`).join('\n');
  content = content.slice(0, zhCloseIdx) + '\n' + zhInserts + content.slice(zhCloseIdx);
}

// Insert missing keys into en-US block (before the closing "},\n};" at end)
const enCloseIdx = content.lastIndexOf('\n  },\n};');
if (enCloseIdx > 0) {
  const enInserts = enMissing.map(k => `    ${k}: "${camelToWords(k)}",`).join('\n');
  content = content.slice(0, enCloseIdx) + '\n' + enInserts + content.slice(enCloseIdx);
}

fs.writeFileSync('copy.ts', content);
console.log('Patched', zhMissing.length, 'zh-CN and', enMissing.length, 'en-US missing keys');
