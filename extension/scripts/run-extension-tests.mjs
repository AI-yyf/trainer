import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const extensionDir = path.resolve(__dirname, "..");
const testsDir = path.join(extensionDir, "tests");

function isRunnableTest(entry) {
  return (
    entry.isFile() &&
    entry.name.endsWith(".test.js") &&
    !entry.name.startsWith("._") &&
    entry.name !== ".DS_Store"
  );
}

if (!fs.existsSync(testsDir)) {
  console.error(`Extension tests directory is missing: ${testsDir}`);
  process.exit(1);
}

const testFiles = fs
  .readdirSync(testsDir, { withFileTypes: true })
  .filter(isRunnableTest)
  .map((entry) => path.join(testsDir, entry.name))
  .sort((left, right) => left.localeCompare(right));

if (testFiles.length === 0) {
  console.error("No runnable extension tests found.");
  process.exit(1);
}

const result = spawnSync(process.execPath, ["--test", ...testFiles], {
  cwd: path.resolve(extensionDir, ".."),
  stdio: "inherit",
});

process.exit(result.status ?? 1);
