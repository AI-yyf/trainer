import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

const extensionDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const companionVsix = path.resolve(extensionDir, '../remote-extension/trainer-workspace-companion.vsix');
const outputDir = path.join(extensionDir, 'bundled', 'remote');
const outputPath = path.join(outputDir, 'trainer-workspace-companion.vsix');

if (!fs.existsSync(companionVsix)) {
  throw new Error(`Remote companion VSIX was not produced: ${companionVsix}`);
}
fs.mkdirSync(outputDir, { recursive: true });
fs.copyFileSync(companionVsix, outputPath);
console.log(`Bundled Remote Workspace Companion -> ${path.relative(extensionDir, outputPath)}`);
