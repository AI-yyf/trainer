import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const extensionDir = path.resolve(__dirname, "..");

const packagePayloadRoots = [
  path.join(extensionDir, "dist"),
  path.join(extensionDir, "webview", "dist"),
  path.join(extensionDir, "bundled"),
  path.join(extensionDir, "media"),
];

function isMetadataJunk(filePath) {
  const name = path.basename(filePath);
  return name === ".DS_Store" || name.startsWith("._");
}

function cleanMetadataJunk(rootPath) {
  if (!fs.existsSync(rootPath)) {
    return 0;
  }

  let removed = 0;
  const pending = [rootPath];
  while (pending.length > 0) {
    const current = pending.pop();
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const entryPath = path.join(current, entry.name);
      if (isMetadataJunk(entryPath)) {
        fs.rmSync(entryPath, { recursive: entry.isDirectory(), force: true });
        removed += 1;
        continue;
      }
      if (entry.isDirectory()) {
        pending.push(entryPath);
      }
    }
  }
  return removed;
}

const removed = packagePayloadRoots.reduce(
  (count, rootPath) => count + cleanMetadataJunk(rootPath),
  0,
);

console.log(`Removed ${removed} package metadata junk file${removed === 1 ? "" : "s"}.`);
