import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const filename = fileURLToPath(import.meta.url);
const root = path.resolve(path.dirname(filename), "..");

export function verifyProductVersion({ repoRoot = root, ref = process.env.GITHUB_REF ?? "" } = {}) {
  const product = JSON.parse(fs.readFileSync(path.join(repoRoot, "extension/package.json"), "utf8"));
  const errors = [];
  if (!/^\d+\.\d+\.\d+(?:-[\w.-]+)?$/.test(product.version)) {
    errors.push("Extension product version is not a valid release version.");
  }
  for (const name of ["package.json", "package-lock.json", "extension/package-lock.json"]) {
    const manifest = JSON.parse(fs.readFileSync(path.join(repoRoot, name), "utf8"));
    if (manifest.version !== product.version) errors.push(`${name} version differs from extension/package.json.`);
    if (manifest.packages?.[""] && manifest.packages[""].version !== product.version) {
      errors.push(`${name} root package version differs from extension/package.json.`);
    }
  }
  for (const name of fs.readdirSync(repoRoot).filter((name) => /^README(?:_[\w-]+)?\.md$/.test(name))) {
    const text = fs.readFileSync(path.join(repoRoot, name), "utf8");
    if (!text.includes(`badge/source-v${product.version}-`)) {
      errors.push(`${name} source badge differs from the product version.`);
    }
  }
  if (ref.startsWith("refs/tags/") && ref !== `refs/tags/v${product.version}`) {
    errors.push(`Tag ${ref.slice("refs/tags/".length)} differs from product v${product.version}.`);
  }
  if (errors.length) throw new Error(`Product version gate failed:\n${errors.map((error) => `- ${error}`).join("\n")}`);
  return { version: product.version, source: "extension/package.json", ref };
}

if (process.argv[1] && path.resolve(process.argv[1]) === filename) {
  const report = verifyProductVersion();
  console.log(`Product version verified: ${report.version} (${report.source}).`);
}
