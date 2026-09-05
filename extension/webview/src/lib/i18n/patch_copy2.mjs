import fs from 'fs';
const content = fs.readFileSync('copy.ts', 'utf8');

// Extract all CopyKey values
const keyMatch = content.match(/export type CopyKey =\s*([\s\S]*?);/);
if (!keyMatch) { console.error('No CopyKey'); process.exit(1); }
const keys = Array.from(keyMatch[1].matchAll(/"([^"]+)"/g)).map(m => m[1]);

// Extract keys from zh-CN block
const zhStart = content.indexOf('"zh-CN": {');
const zhEnd = content.indexOf('"en-US": {', zhStart);
const zhBlock = content.slice(zhStart, zhEnd);
const zhKeys = new Set(Array.from(zhBlock.matchAll(/(\w+):/g)).map(m => m[1]));
const missingZh = keys.filter(k => !zhKeys.has(k));

// Extract keys from en-US block
const enStart = zhEnd;
const enEnd = content.lastIndexOf('};');
const enBlock = content.slice(enStart, enEnd);
const enKeys = new Set(Array.from(enBlock.matchAll(/(\w+):/g)).map(m => m[1]));
const missingEn = keys.filter(k => !enKeys.has(k));

console.log('Missing zh-CN:', missingZh.length, 'en-US:', missingEn.length);

let out = content;

// Append missing zh-CN keys before the closing of zh-CN block
const zhCloseIdx = out.indexOf('\n  },\n  "en-US"');
if (zhCloseIdx > 0) {
  const zhInserts = missingZh.map(k => `    ${k}: "",`).join('\n');
  out = out.slice(0, zhCloseIdx) + '\n' + zhInserts + out.slice(zhCloseIdx);
}

// Append missing en-US keys before the closing of en-US block
const enCloseIdx = out.lastIndexOf('\n  },\n};');
if (enCloseIdx > 0) {
  const enInserts = missingEn.map(k => `    ${k}: "",`).join('\n');
  out = out.slice(0, enCloseIdx) + '\n' + enInserts + out.slice(enCloseIdx);
}

fs.writeFileSync('copy.ts', out);
console.log('Done');
