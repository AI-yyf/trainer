import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { ensureCurrentVsix } from "./prepare-current-vsix.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const extensionDir = path.resolve(__dirname, "..");

const { vsixPath } = ensureCurrentVsix({
  reason: "Installing a stale VSIX would break packaged-state truth for Trainer.",
});
const fallbackCodeCli = "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code";

const codeCli =
  process.env.CODE_CLI_PATH && fs.existsSync(process.env.CODE_CLI_PATH)
    ? process.env.CODE_CLI_PATH
    : fs.existsSync(fallbackCodeCli)
      ? fallbackCodeCli
      : process.platform === "win32"
        ? "code.cmd"
        : "code";

const installArgs = ["--install-extension", vsixPath, "--force"];
const install =
  process.platform === "win32" && codeCli.toLowerCase().endsWith(".cmd")
    ? spawnSync(
        process.env.ComSpec ?? "cmd.exe",
        ["/d", "/c", buildWindowsCmd(codeCli, installArgs)],
        {
          cwd: extensionDir,
          stdio: "inherit",
          windowsVerbatimArguments: true,
        },
      )
    : spawnSync(codeCli, installArgs, {
        cwd: extensionDir,
        stdio: "inherit",
      });

if (install.status !== 0) {
  console.error("Trainer install failed. VS Code CLI returned a non-zero exit code.");
  process.exit(install.status ?? 1);
}

console.log(`Trainer installed from ${vsixPath}`);

function buildWindowsCmd(command, args) {
  return ["call", quoteWindowsCmdArg(command), ...args.map(quoteWindowsCmdArg)].join(" ");
}

function quoteWindowsCmdArg(value) {
  return `"${String(value).replace(/"/g, '\\"')}"`;
}
