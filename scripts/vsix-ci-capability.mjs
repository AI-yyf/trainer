import { spawnSync } from "node:child_process";
import fs from "node:fs";
import process from "node:process";
import { fileURLToPath } from "node:url";

function commandResult(command, args, { env = process.env } = {}) {
  return spawnSync(command, args, {
    encoding: "utf8",
    env,
    timeout: 10000,
  });
}

function quoteWindowsCommand(command) {
  return `"${String(command).replace(/"/g, '\\"')}"`;
}

function canRunCodeCli(command, { platform, env, runCommand }) {
  const result =
    platform === "win32" && command.toLowerCase().endsWith(".cmd")
      ? runCommand(env.ComSpec ?? "cmd.exe", ["/d", "/c", `call ${quoteWindowsCommand(command)} --version`], {
          env,
        })
      : runCommand(command, ["--version"], { env });
  return !result.error && result.status === 0;
}

function describeAttempt(command) {
  return command.includes(" ") ? `"${command}"` : command;
}

export function resolveVsCodeCli({
  platform = process.platform,
  env = process.env,
  existsSync = fs.existsSync,
  runCommand = commandResult,
} = {}) {
  const candidates = [];
  const explicit = String(env.CODE_CLI_PATH ?? "").trim();
  if (explicit) {
    if (existsSync(explicit)) {
      candidates.push(explicit);
    } else {
      return {
        codeCli: null,
        reason: "CODE_CLI_PATH is set but does not point to a file.",
        attempted: [explicit],
      };
    }
  }

  if (platform === "darwin") {
    const macFallback = "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code";
    if (existsSync(macFallback)) {
      candidates.push(macFallback);
    }
  }

  if (platform === "win32") {
    candidates.push("code.cmd", "code");
  } else {
    candidates.push("code");
  }

  const attempted = [];
  for (const candidate of [...new Set(candidates)]) {
    attempted.push(candidate);
    if (canRunCodeCli(candidate, { platform, env, runCommand })) {
      return { codeCli: candidate, reason: null, attempted };
    }
  }

  return {
    codeCli: null,
    reason: `No runnable VS Code CLI was found (tried ${attempted.map(describeAttempt).join(", ")}).`,
    attempted,
  };
}

function commandAvailable(command, { env, runCommand }) {
  const result = runCommand(command, ["--help"], { env });
  return !result.error && result.status === 0;
}

export function detectVsixCiCapability(options = {}) {
  const platform = options.platform ?? process.platform;
  const env = options.env ?? process.env;
  const runCommand = options.runCommand ?? commandResult;
  const cli = resolveVsCodeCli({ ...options, platform, env, runCommand });
  const installAvailable = Boolean(cli.codeCli);
  const hasDisplay = Boolean(String(env.DISPLAY ?? "").trim() || String(env.WAYLAND_DISPLAY ?? "").trim());
  const canUseXvfb =
    installAvailable && platform === "linux" && !hasDisplay
      ? commandAvailable("xvfb-run", { env, runCommand })
      : false;
  const hostE2EAvailable =
    installAvailable && (platform !== "linux" || hasDisplay || canUseXvfb);

  let hostReason = null;
  if (!installAvailable) {
    hostReason = cli.reason;
  } else if (platform === "linux" && !hasDisplay && !canUseXvfb) {
    hostReason = "Linux has no DISPLAY/WAYLAND_DISPLAY and no runnable xvfb-run.";
  }

  return {
    platform,
    codeCli: cli.codeCli,
    installAvailable,
    hostE2EAvailable,
    linuxUseXvfb: platform === "linux" && !hasDisplay && canUseXvfb,
    reason: hostReason,
    attempted: cli.attempted,
  };
}

export function formatVsixCiGate(capability, scope) {
  const detail = capability.reason ?? "the runner did not advertise a supported host capability";
  if (scope === "install") {
    return [
      "Native VSIX install smoke was not run.",
      detail,
      "Packaging is not installation evidence; rerun on a native runner with a usable VS Code CLI.",
    ].join(" ");
  }
  return [
    "Installed VSIX host E2E was not run.",
    detail,
    "This remains a manual release gate; dispatch this workflow with run_vsix_host_e2e=true on a runner with VS Code and a display server.",
  ].join(" ");
}

function writeGitHubOutputs(capability, env = process.env) {
  const outputPath = String(env.GITHUB_OUTPUT ?? "").trim();
  if (!outputPath) {
    return;
  }
  const values = {
    install_available: capability.installAvailable,
    host_e2e_available: capability.hostE2EAvailable,
    linux_use_xvfb: capability.linuxUseXvfb,
    code_cli: capability.codeCli ?? "",
    reason: capability.reason ?? "",
  };
  const lines = Object.entries(values).map(([key, value]) => {
    const normalized = String(value).replace(/[\r\n]/g, " ");
    return `${key}=${normalized}`;
  });
  fs.appendFileSync(outputPath, `${lines.join("\n")}\n`, "utf8");
}

function appendGitHubSummary(message, env = process.env) {
  const summaryPath = String(env.GITHUB_STEP_SUMMARY ?? "").trim();
  if (!summaryPath) {
    return;
  }
  fs.appendFileSync(summaryPath, `${message}\n`, "utf8");
}

function reportGate(capability, scope, { required = false } = {}) {
  const message = formatVsixCiGate(capability, scope);
  const title = scope === "install" ? "Native VSIX install gate" : "Installed VSIX host E2E gate";
  appendGitHubSummary(`### ${title}\n\n${message}\n`);
  if (required) {
    console.error(`${title}: ${message}`);
    process.exitCode = 1;
    return;
  }
  console.warn(`::warning title=${title}::${message}`);
}

function main() {
  const flags = new Set(process.argv.slice(2));
  const capability = detectVsixCiCapability();
  writeGitHubOutputs(capability);
  console.log(JSON.stringify(capability, null, 2));

  if (flags.has("--manual-install-gate")) {
    reportGate(capability, "install");
  }
  if (flags.has("--manual-host-e2e-gate")) {
    reportGate(capability, "host");
  }
  if (flags.has("--require-host-e2e") && !capability.hostE2EAvailable) {
    reportGate(capability, "host", { required: true });
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  main();
}
