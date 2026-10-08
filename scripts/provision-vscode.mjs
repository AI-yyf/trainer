import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import { pathToFileURL } from "node:url";

// Use the same released version on each native runner. The Microsoft update
// service supplies its platform-specific SHA-256 and source commit.
export const VSCODE_ACCEPTANCE_VERSION = "1.127.0";

export function resolveVsCodeArchiveTarget(platform = process.platform, arch = process.arch) {
  const targets = {
    "linux-x64": { updatePlatform: "linux-x64", cli: "bin/code", archive: "code.tar.gz" },
    "linux-arm64": { updatePlatform: "linux-arm64", cli: "bin/code", archive: "code.tar.gz" },
    "darwin-x64": { updatePlatform: "darwin", cli: "Visual Studio Code.app/Contents/Resources/app/bin/code", archive: "code.zip" },
    "darwin-arm64": { updatePlatform: "darwin-arm64", cli: "Visual Studio Code.app/Contents/Resources/app/bin/code", archive: "code.zip" },
    "win32-x64": { updatePlatform: "win32-x64-archive", cli: "bin/code.cmd", archive: "code.zip" },
    "win32-arm64": { updatePlatform: "win32-arm64-archive", cli: "bin/code.cmd", archive: "code.zip" },
  };
  const target = targets[`${platform}-${arch}`];
  if (!target) throw new Error(`Unsupported native VS Code acceptance target: ${platform}-${arch}`);
  return target;
}

export function verifyVsCodeMetadata(metadata, version = VSCODE_ACCEPTANCE_VERSION) {
  if (metadata.productVersion !== version || !/^[a-f0-9]{40}$/i.test(metadata.version ?? "")) {
    throw new Error(`Microsoft update metadata does not identify VS Code ${version}.`);
  }
  if (!/^[a-f0-9]{64}$/i.test(metadata.sha256hash ?? "")) {
    throw new Error("Microsoft update metadata is missing the required SHA-256.");
  }
  const url = new URL(metadata.url);
  if (url.protocol !== "https:" || url.hostname !== "vscode.download.prss.microsoft.com") {
    throw new Error(`Unexpected Microsoft VS Code archive URL: ${url.origin}`);
  }
  return metadata;
}

export async function verifyArchiveSha256(archivePath, expectedSha256) {
  const hash = createHash("sha256");
  for await (const chunk of fs.createReadStream(archivePath)) hash.update(chunk);
  const actual = hash.digest("hex");
  if (actual !== expectedSha256.toLowerCase()) {
    throw new Error(`VS Code archive SHA-256 mismatch: expected ${expectedSha256}, received ${actual}.`);
  }
  return actual;
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, { encoding: "utf8", timeout: 180000, ...options });
  if (result.error || result.status !== 0) {
    throw new Error(`${command} failed: ${result.error?.message ?? result.stderr ?? result.status}`);
  }
  return result.stdout;
}

export async function provisionVsCode({
  platform = process.platform,
  arch = process.arch,
  version = VSCODE_ACCEPTANCE_VERSION,
  baseDir = process.env.RUNNER_TEMP ?? os.tmpdir(),
  fetchImpl = fetch,
  runCommand = run,
} = {}) {
  const target = resolveVsCodeArchiveTarget(platform, arch);
  const metadataUrl = `https://update.code.visualstudio.com/api/versions/${version}/${target.updatePlatform}/stable`;
  const metadataResponse = await fetchImpl(metadataUrl, { signal: AbortSignal.timeout(30000) });
  if (!metadataResponse.ok) throw new Error(`VS Code metadata request failed: HTTP ${metadataResponse.status}`);
  const metadata = verifyVsCodeMetadata(await metadataResponse.json(), version);
  fs.mkdirSync(baseDir, { recursive: true });
  const root = fs.mkdtempSync(path.join(baseDir, "trainer-vscode-acceptance-"));
  const archivePath = path.join(root, target.archive);
  const installDir = path.join(root, "application");
  fs.mkdirSync(installDir);
  const archiveResponse = await fetchImpl(metadata.url, { signal: AbortSignal.timeout(300000) });
  if (!archiveResponse.ok || !archiveResponse.body) {
    throw new Error(`VS Code archive request failed: HTTP ${archiveResponse.status}`);
  }
  await pipeline(Readable.fromWeb(archiveResponse.body), fs.createWriteStream(archivePath, { flags: "wx" }));
  const sha256 = await verifyArchiveSha256(archivePath, metadata.sha256hash);
  // Extraction happens only after checksum verification. These archives never
  // install into the runner's or developer's existing VS Code application.
  if (platform === "linux") {
    runCommand("tar", ["-xzf", archivePath, "--strip-components=1", "-C", installDir]);
  } else if (platform === "darwin") {
    runCommand("/usr/bin/ditto", ["-x", "-k", archivePath, installDir]);
  } else {
    runCommand("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command",
      "Expand-Archive -LiteralPath $env:TRAINER_CODE_ARCHIVE -DestinationPath $env:TRAINER_CODE_INSTALL -Force"], {
      env: { ...process.env, TRAINER_CODE_ARCHIVE: archivePath, TRAINER_CODE_INSTALL: installDir },
    });
  }
  const codeCli = path.join(installDir, target.cli);
  if (!fs.existsSync(codeCli)) throw new Error(`Verified VS Code archive has no CLI at ${codeCli}`);
  const output = platform === "win32"
    ? runCommand(process.env.ComSpec ?? "cmd.exe", ["/d", "/c", `call "${codeCli}" --version`], { windowsVerbatimArguments: true })
    : runCommand(codeCli, ["--version"]);
  const [installedVersion, installedCommit] = output.trim().split(/\r?\n/);
  if (installedVersion !== version || installedCommit !== metadata.version) {
    throw new Error(`Downloaded VS Code CLI identity differs from verified metadata: ${output}`);
  }
  fs.unlinkSync(archivePath);
  return { version, commit: installedCommit, platform: target.updatePlatform, sha256, metadataUrl, downloadUrl: metadata.url, codeCli };
}

async function main() {
  const report = await provisionVsCode();
  const reportPath = path.resolve("output/maturity/ci-installed/vscode-provision.json");
  fs.mkdirSync(path.dirname(reportPath), { recursive: true });
  fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`);
  if (process.env.GITHUB_ENV) fs.appendFileSync(process.env.GITHUB_ENV, `CODE_CLI_PATH=${report.codeCli}\n`);
  console.log(JSON.stringify(report, null, 2));
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main().catch((error) => { console.error(error); process.exitCode = 1; });
}
