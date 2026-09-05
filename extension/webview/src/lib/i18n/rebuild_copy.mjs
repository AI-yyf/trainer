import fs from 'fs';

// Read App.tsx to extract the original copy object
const appContent = fs.readFileSync('../../app/App.tsx', 'utf8');
const copyMatch = appContent.match(/const copy: Record<ComposerLanguage, Record<CopyKey, string>> = \{([\s\S]*?)\n\};/);
if (!copyMatch) {
  console.error('Could not find copy object in App.tsx');
  process.exit(1);
}

const copyBlock = copyMatch[0];

// Read current copy.ts
let copyContent = fs.readFileSync('copy.ts', 'utf8');

// Extract current CopyKey type and zh-CN block
const keyMatch = copyContent.match(/(export type CopyKey =[\s\S]*?);/);
const copyTableMatch = copyContent.match(/(export const copyTable = \{[\s\S]*?)\n\} as Record<ComposerLanguage, Record<CopyKey, string>>;/);

if (!keyMatch || !copyTableMatch) {
  console.error('Could not find CopyKey or copyTable in copy.ts');
  process.exit(1);
}

// Reconstruct: CopyKey + zh-CN/en-US from App.tsx copy object
// But we need to preserve any new keys added to CopyKey that aren't in App.tsx copy
const newContent = `${keyMatch[1]};\n\n${copyBlock.replace('const copy:', 'export const copyTable:').replace(/Record<CopyKey, string>/, 'Record<CopyKey, string>').replace(/\n\};/, '\n} as Record<ComposerLanguage, Record<CopyKey, string>>;')}\n`;

fs.writeFileSync('copy.ts', newContent);
console.log('Reconstructed copy.ts from App.tsx copy object');
