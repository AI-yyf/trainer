import fs from 'fs';
const content = fs.readFileSync('copy.ts', 'utf8');

// Extract CopyKey union type
const keyMatch = content.match(/export type CopyKey =\s*([\s\S]*?);/);
const keys = Array.from(keyMatch[1].matchAll(/"([^"]+)"/g)).map(m => m[1]);

// Extract keys from zh-CN block
const zhStart = content.indexOf('"zh-CN": {');
const zhEnd = content.indexOf('"en-US": {');
const zhBlock = content.slice(zhStart, zhEnd);
const zhKeys = new Set(Array.from(zhBlock.matchAll(/(\w+):/g)).map(m => m[1]));

const missing = keys.filter(k => !zhKeys.has(k));
console.log('Total CopyKey:', keys.length);
console.log('Present in zh-CN:', zhKeys.size);
console.log('Missing:', missing.length);
fs.writeFileSync('missing_keys.json', JSON.stringify(missing, null, 2));
