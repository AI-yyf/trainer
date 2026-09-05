import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { ensureCurrentVsix } from "./prepare-current-vsix.mjs";
import {
  SIDECAR_BINARY_MANIFEST_FILE,
} from "./bundle-sidecar-binary.mjs";
import {
  verifyBundledBinaryManifest,
} from "./verify-package.mjs";
import { verifyBundledSidecarRuntime } from "./verify-bundled-sidecar-runtime.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const extensionDir = path.resolve(__dirname, "..");
const { packageJson, vsixPath, rebuilt } = ensureCurrentVsix({
  reason: "VSIX install smoke must verify the current packaged extension, not a stale artifact.",
});
const extensionId = `${packageJson.publisher}.${packageJson.name}`;
const installedDirName = `${packageJson.publisher}.${packageJson.name}-${packageJson.version}`;
const fallbackCodeCli = "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code";

const codeCli = resolveCodeCli();

const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "trainer-vsix-install-smoke-"));
const userDataDir = path.join(tempRoot, "user-data");
const extensionsDir = path.join(tempRoot, "extensions");
fs.mkdirSync(userDataDir, { recursive: true });
fs.mkdirSync(extensionsDir, { recursive: true });

try {
  runCode(["--user-data-dir", userDataDir, "--extensions-dir", extensionsDir, "--install-extension", vsixPath, "--force"]);
  const list = runCode(["--user-data-dir", userDataDir, "--extensions-dir", extensionsDir, "--list-extensions", "--show-versions"]);
  const expectedListEntry = `${extensionId}@${packageJson.version}`;
  if (!list.stdout.split(/\r?\n/).includes(expectedListEntry)) {
    fail(`Installed extension list does not include ${expectedListEntry}.\n${list.stdout}`);
  }

  const installedRoot = path.join(extensionsDir, installedDirName);
  const requiredFiles = [
    "package.json",
    "dist/extension/src/extension.js",
    "webview/dist/index.html",
    "bundled/server/run_sidecar.py",
    `bundled/bin/${process.platform}-${process.arch}/${process.platform === "win32" ? "trainer-sidecar.exe" : "trainer-sidecar"}`,
    `bundled/bin/${process.platform}-${process.arch}/${SIDECAR_BINARY_MANIFEST_FILE}`,
  ];
  const missing = requiredFiles.filter((relativePath) => !fs.existsSync(path.join(installedRoot, relativePath)));
  if (missing.length > 0) {
    fail(`Installed VSIX is missing required runtime files:\n${missing.map((item) => `- ${item}`).join("\n")}`);
  }

  const binaryManifestReport = verifyBundledBinaryManifest({
    extensionDir: installedRoot,
    repoRoot: installedRoot,
    serverDir: path.join(installedRoot, "bundled", "server"),
  });
  if (binaryManifestReport.errors.length > 0) {
    fail(
      `Installed VSIX sidecar binary manifest failed verification:\n${binaryManifestReport.errors
        .map((item) => `- ${item}`)
        .join("\n")}`,
    );
  }

  const metadataJunk = listMetadataJunk(installedRoot);
  if (metadataJunk.length > 0) {
    fail(
      `Installed VSIX contains metadata junk:\n${metadataJunk
        .slice(0, 30)
        .map((item) => `- ${item}`)
        .join("\n")}`,
    );
  }

  const runtimeSmoke = await verifyBundledSidecarRuntime({ extensionDir: installedRoot });

  console.log(
    JSON.stringify(
      {
        ok: true,
        codeCli,
        extensionId,
        version: packageJson.version,
        vsixPath,
        rebuiltCurrentVsix: rebuilt,
        installedRoot,
        listEntry: expectedListEntry,
        requiredFiles,
        binaryManifest: binaryManifestReport.manifest,
        runtimeSmoke: {
          targetPlatform: runtimeSmoke.targetPlatform,
        },
        metadataJunkCount: 0,
      },
      null,
      2,
    ),
  );
} finally {
  if (process.env.TRAINER_KEEP_VSIX_INSTALL_SMOKE !== "1") {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
}

function runCode(args) {
  const result =
    process.platform === "win32" && codeCli.toLowerCase().endsWith(".cmd")
      ? spawnSync(process.env.ComSpec ?? "cmd.exe", ["/d", "/c", buildWindowsCmd(codeCli, args)], {
          cwd: extensionDir,
          encoding: "utf8",
          windowsVerbatimArguments: true,
        })
      : spawnSync(codeCli, args, {
          cwd: extensionDir,
          encoding: "utf8",
        });
  if (result.status !== 0) {
    fail(
      [
        `VS Code CLI failed: ${codeCli} ${args.join(" ")}`,
        result.error ? `${result.error.name}: ${result.error.message}` : "",
        (result.stdout ?? "").trim(),
        (result.stderr ?? "").trim(),
      ]
        .filter(Boolean)
        .join("\n"),
    );
  }
  return result;
}

function buildWindowsCmd(command, args) {
  return ["call", quoteWindowsCmdArg(command), ...args.map(quoteWindowsCmdArg)].join(" ");
}

function quoteWindowsCmdArg(value) {
  return `"${String(value).replace(/"/g, '\\"')}"`;
}

function resolveCodeCli() {
  if (process.env.CODE_CLI_PATH && fs.existsSync(process.env.CODE_CLI_PATH)) {
    return process.env.CODE_CLI_PATH;
  }

  if (fs.existsSync(fallbackCodeCli)) {
    return fallbackCodeCli;
  }

  if (process.platform === "win32") {
    for (const candidate of ["code.cmd", "code"]) {
      const result = spawnSync("where.exe", [candidate], { encoding: "utf8" });
      const firstMatch = (result.stdout ?? "")
        .split(/\r?\n/)
        .map((line) => line.trim())
        .find((line) => line && fs.existsSync(line));
      if (firstMatch) {
        return firstMatch;
      }
    }
    return "code.cmd";
  }

  return "code";
}

function listMetadataJunk(rootPath) {
  const findings = [];
  const pending = [rootPath];
  while (pending.length > 0) {
    const current = pending.pop();
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const entryPath = path.join(current, entry.name);
      if (entry.name === ".DS_Store" || entry.name.startsWith("._")) {
        findings.push(path.relative(rootPath, entryPath));
        continue;
      }
      if (entry.isDirectory()) {
        pending.push(entryPath);
      }
    }
  }
  return findings.sort((left, right) => left.localeCompare(right));
}

function fail(message) {
  console.error(`Trainer VSIX install smoke failed.\n${message}`);
  process.exit(1);
}
