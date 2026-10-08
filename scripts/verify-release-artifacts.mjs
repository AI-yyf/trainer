import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { verifyVsixTargetArtifact } from "../extension/scripts/package-vsix.mjs";
import { readZipEntries, readZipEntry } from "../extension/scripts/vsix-archive.mjs";

const filename = fileURLToPath(import.meta.url);
export const RELEASE_TARGETS = ["darwin-arm64", "linux-x64", "win32-x64"];

export function verifyReleaseArtifacts({ directory, ref, commit }) {
  if (!/^refs\/tags\/v\d+\.\d+\.\d+(?:-[\w.-]+)?$/.test(ref ?? "")) {
    throw new Error("Formal release requires a product version tag.");
  }
  if (!/^[a-f0-9]{40}$/.test(commit ?? "")) throw new Error("Formal release requires the exact source commit.");
  const version = ref.slice("refs/tags/v".length);
  const vsixFiles = fs.readdirSync(directory).filter((name) => name.endsWith(".vsix"));
  if (vsixFiles.length !== RELEASE_TARGETS.length) throw new Error("Formal release requires exactly three target artifacts.");
  const seen = new Set();
  const verified = [];
  for (const file of vsixFiles) {
    const vsixPath = path.join(directory, file);
    const metadata = JSON.parse(fs.readFileSync(`${vsixPath}.build.json`, "utf8"));
    const archive = fs.readFileSync(vsixPath);
    const hash = crypto.createHash("sha256").update(archive).digest("hex");
    if (metadata.schemaVersion !== 1 || metadata.productVersion !== version ||
        metadata.sourceCommit !== commit || metadata.sourceDirty !== false ||
        metadata.vsix?.sha256 !== hash || metadata.vsix?.file !== file ||
        metadata.vsix?.bytes !== archive.length) {
      throw new Error(`Release artifact provenance/version/hash gate failed: ${file}.`);
    }
    const target = metadata.targetPlatform;
    if (!RELEASE_TARGETS.includes(target) || seen.has(target)) throw new Error(`Missing or duplicated release target: ${target}.`);
    seen.add(target);
    const targetReport = verifyVsixTargetArtifact({ vsixPath, targetPlatform: target });
    if (targetReport.errors.length) throw new Error(targetReport.errors.join("\n"));
    const entries = readZipEntries(archive);
    const packaged = JSON.parse(readZipEntry(archive, entries.get("extension/package.json")).toString("utf8"));
    const sidecar = JSON.parse(readZipEntry(archive, entries.get(`extension/bundled/bin/${target}/trainer-sidecar-manifest.json`)).toString("utf8"));
    if (packaged.version !== version || sidecar.platform !== target ||
        sidecar.sourceSnapshot?.sha256 !== metadata.sourceSnapshot?.sha256 ||
        !sidecar.buildEnvironment?.python || !sidecar.buildEnvironment?.dependencies?.pyinstaller) {
      throw new Error(`Release packaged runtime/version gate failed: ${file}.`);
    }
    verified.push({ file, target, sha256: hash });
  }
  return { version, commit, artifacts: verified };
}

if (process.argv[1] && path.resolve(process.argv[1]) === filename) {
  const args = process.argv.slice(2);
  const get = (name) => args[args.indexOf(name) + 1];
  const report = verifyReleaseArtifacts({ directory: get("--dir"), ref: get("--ref"), commit: get("--commit") });
  console.log(JSON.stringify(report, null, 2));
}
