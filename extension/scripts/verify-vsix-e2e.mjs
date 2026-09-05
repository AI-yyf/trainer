import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath } from "node:url";
import { ensureCurrentVsix } from "./prepare-current-vsix.mjs";
import {
  buildVsixE2EProviderSavePayloadTemplate,
} from "./vsix-e2e-provider-config.mjs";
import {
  resolveVsixE2EProviderRuntime,
  withVsixE2EFixtureLoopbackBypass,
} from "./vsix-e2e-provider-runtime.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const extensionDir = path.resolve(__dirname, "..");
const repoRoot = path.resolve(extensionDir, "..");
const { packageJson, vsixPath, rebuilt } = ensureCurrentVsix({
  reason: "VSIX E2E must validate the current packaged extension and bundled sidecar truth.",
});
const extensionId = `${packageJson.publisher}.${packageJson.name}`;
const fallbackCodeCli = "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code";

const codeCli = resolveCodeCli();
const tempRoot = createVsixE2ETempRoot();
const userDataDir = path.join(tempRoot, "user-data");
const extensionsDir = path.join(tempRoot, "extensions");
const workspaceDir = path.join(tempRoot, "workspace");
const trainerWorkspaceDir = path.join(tempRoot, "trainer-workspace");
const driverDir = path.join(tempRoot, "smoke-driver");
const reportPath = path.join(tempRoot, "trainer-e2e-report.json");
const exportedReportPath = (process.env.TRAINER_E2E_EXPORT_REPORT_PATH || "").trim();
const exportedArtifactsDir = exportedReportPath
  ? path.join(path.dirname(exportedReportPath), "vsix-installed-state")
  : path.join(repoRoot, "output", "playwright", "sidebar-audit", "vsix-installed-state");
const keepArtifacts = process.env.TRAINER_KEEP_VSIX_E2E === "1";
const keepArtifactsOnFailure = process.env.TRAINER_KEEP_VSIX_E2E_ON_FAILURE === "1";

fs.mkdirSync(path.join(userDataDir, "User"), { recursive: true });
fs.mkdirSync(extensionsDir, { recursive: true });
fs.mkdirSync(workspaceDir, { recursive: true });
fs.mkdirSync(driverDir, { recursive: true });
fs.mkdirSync(exportedArtifactsDir, { recursive: true });

let finalResult = null;
let finalError = null;
let providerRuntime = null;
let fixtureProviderStats = null;

try {
  providerRuntime = await resolveVsixE2EProviderRuntime({
    extensionDir,
    requestedProtocol: process.env.TRAINER_E2E_PROVIDER_PROTOCOL,
  });
  const providerConfiguration = providerRuntime.configuration;
  const launchEnvironment =
    providerRuntime.source === "fixture"
      ? withVsixE2EFixtureLoopbackBypass(process.env)
      : process.env;
  writeUserSettings();
  writeWorkspace();
  provisionTemporaryTrainerWorkspace();
  writeDriverExtension(providerConfiguration);

  runCode([
    "--user-data-dir",
    userDataDir,
    "--extensions-dir",
    extensionsDir,
    "--install-extension",
    vsixPath,
    "--force",
  ]);

  const launchArgs = [
    "--user-data-dir",
    userDataDir,
    "--extensions-dir",
    extensionsDir,
    "--skip-welcome",
    "--skip-release-notes",
    "--extensionDevelopmentPath",
    driverDir,
    "--new-window",
    "--wait",
    workspaceDir,
  ];
  const launchOptions = {
    env: {
      ...launchEnvironment,
      TRAINER_E2E_REPORT_PATH: reportPath,
      TRAINER_E2E_TARGET_EXTENSION_ID: extensionId,
      TRAINER_E2E_PROVIDER_BASE_URL: providerRuntime.baseUrl,
      TRAINER_E2E_PROVIDER_API_KEY: providerRuntime.apiKey,
      TRAINER_E2E_PROVIDER_MODEL: providerRuntime.model,
      TRAINER_E2E_PROVIDER_PROTOCOL: providerConfiguration.protocol,
      TRAINER_E2E_PROVIDER_SOURCE: providerRuntime.source,
      TRAINER_E2E_ARTIFACTS_DIR: exportedArtifactsDir,
      TRAINER_E2E_USER_DATA_DIR: userDataDir,
      TRAINER_E2E_WORKSPACE_DIR: workspaceDir,
      TRAINER_E2E_TRAINER_WORKSPACE_DIR: trainerWorkspaceDir,
    },
    timeout: Number.parseInt(process.env.TRAINER_E2E_TIMEOUT_MS ?? "600000", 10),
  };
  const launchResult = runSmokeDriverWithRetry(launchArgs, launchOptions, reportPath, userDataDir);

  if (providerRuntime.source === "fixture") {
    fixtureProviderStats = await providerRuntime.readFixtureStats();
    if (
      !fixtureProviderStats ||
      fixtureProviderStats.modelsRequests < 1 ||
      fixtureProviderStats.chatCompletionRequests < 1
    ) {
      throw new Error(
        "VSIX E2E fixture provider did not receive both model-list and coach-message traffic.",
      );
    }
  }

  if (!fs.existsSync(reportPath)) {
    throw new Error(
      [
        "Smoke driver did not write a report.",
        `VS Code stdout:\n${launchResult.stdout ?? ""}`,
        `VS Code stderr:\n${launchResult.stderr ?? ""}`,
      ].join("\n"),
    );
  }

  const report = JSON.parse(fs.readFileSync(reportPath, "utf8"));
  if (!report.ok) {
    const error = new Error(`VSIX E2E smoke reported failure.\n${JSON.stringify(report, null, 2)}`);
    error.report = report;
    throw error;
  }

  finalResult = {
    ok: true,
    codeCli,
    extensionId,
    version: packageJson.version,
    vsixPath,
    rebuiltCurrentVsix: rebuilt,
    workspaceDir,
    reportPath,
    keptArtifacts: keepArtifacts,
    tempRoot,
    artifactsDir: exportedArtifactsDir,
    provider: summarizeProviderRuntime(providerRuntime, fixtureProviderStats),
    report,
  };
} catch (error) {
  finalError = normalizeError(error);
  finalResult = {
    ok: false,
    codeCli,
    extensionId,
    version: packageJson.version,
    vsixPath,
    rebuiltCurrentVsix: rebuilt,
    workspaceDir,
    reportPath,
    keptArtifacts: keepArtifacts || keepArtifactsOnFailure,
    tempRoot,
    artifactsDir: exportedArtifactsDir,
    provider: summarizeProviderRuntime(providerRuntime, fixtureProviderStats),
    error: finalError,
    report: readJsonIfExists(reportPath) ?? error?.report ?? null,
  };
} finally {
  if (exportedReportPath && finalResult) {
    fs.mkdirSync(path.dirname(exportedReportPath), { recursive: true });
    fs.writeFileSync(exportedReportPath, JSON.stringify(finalResult, null, 2) + "\n", "utf8");
  }

  const shouldKeepArtifacts = keepArtifacts || (Boolean(finalError) && keepArtifactsOnFailure);
  if (finalResult) {
    finalResult.keptArtifacts = shouldKeepArtifacts;
  }

  if (!shouldKeepArtifacts) {
    cleanupVsixE2ETempRoot(tempRoot);
  } else {
    console.error(`Trainer VSIX E2E artifacts kept at: ${tempRoot}`);
  }

  if (providerRuntime) {
    try {
      await providerRuntime.stop();
    } catch (error) {
      console.warn(
        `Trainer VSIX E2E fixture provider cleanup could not finish: ${normalizeError(error).message}`,
      );
    }
  }
}

if (finalError) {
  console.error(`Trainer VSIX E2E smoke failed.\n${finalError.message}`);
  process.exit(1);
}

console.log(JSON.stringify(finalResult, null, 2));

function summarizeProviderRuntime(runtime, fixtureStats) {
  if (!runtime) {
    return null;
  }
  return {
    source: runtime.source,
    protocol: runtime.configuration.protocol,
    model: runtime.model,
    usedPartialExternalOverride: runtime.usedPartialExternalOverride,
    fixtureStats: fixtureStats ?? undefined,
  };
}

function cleanupVsixE2ETempRoot(directory) {
  try {
    fs.rmSync(directory, {
      recursive: true,
      force: true,
      maxRetries: process.platform === "win32" ? 5 : 0,
      retryDelay: process.platform === "win32" ? 200 : 0,
    });
  } catch {
    console.warn(`Trainer VSIX E2E cleanup could not finish; temporary files remain at: ${directory}`);
  }
}

function writeUserSettings() {
  const settings = {
    "security.workspace.trust.enabled": false,
    "telemetry.telemetryLevel": "off",
    "update.mode": "none",
    "extensions.autoCheckUpdates": false,
    "extensions.autoUpdate": false,
    "workbench.startupEditor": "none",
    "chat.disableAIFeatures": true,
    "disableAICustomizations": true,
    "workbench.disableAICustomizations": true,
    "workbench.welcomePage.walkthroughs.openOnInstall": false,
  };
  fs.writeFileSync(
    path.join(userDataDir, "User", "settings.json"),
    `${JSON.stringify(settings, null, 2)}\n`,
    "utf8",
  );
}

function createVsixE2ETempRoot() {
  const requestedRoot = (process.env.TRAINER_VSIX_E2E_TEMP_ROOT || "").trim();
  if (!requestedRoot) {
    return fs.mkdtempSync(path.join(os.tmpdir(), "trainer-vsix-e2e-"));
  }

  const resolvedRoot = path.resolve(requestedRoot);
  const maxRootLength = 40;
  if (resolvedRoot.length > maxRootLength) {
    throw new Error(
      `TRAINER_VSIX_E2E_TEMP_ROOT must be ${maxRootLength} characters or fewer to avoid Windows path limits: ${resolvedRoot}`,
    );
  }
  if (!fs.existsSync(resolvedRoot) || !fs.statSync(resolvedRoot).isDirectory()) {
    throw new Error(`TRAINER_VSIX_E2E_TEMP_ROOT must be an existing directory: ${resolvedRoot}`);
  }
  try {
    fs.accessSync(resolvedRoot, fs.constants.W_OK);
  } catch (error) {
    throw new Error(`TRAINER_VSIX_E2E_TEMP_ROOT must be writable: ${resolvedRoot}`, { cause: error });
  }

  return fs.mkdtempSync(path.join(resolvedRoot, "trainer-vsix-e2e-"));
}

function writeWorkspace() {
  fs.writeFileSync(
    path.join(workspaceDir, "trainer-smoke.md"),
    [
      "# Trainer Smoke Workspace",
      "",
      "This temporary workspace is created by verify-vsix-e2e.mjs.",
      "It must only verify that Trainer behaves as a coach inside VS Code.",
      "",
    ].join("\n"),
    "utf8",
  );

  const resourceFixtures = [
    {
      name: "vsix-e2e-sandbox-capability.md",
      content:
        "# VSIX E2E capability proof\n\nThis file verifies resource upload inside installed extension smoke.\n",
    },
    {
      name: "vsix-resource-detail-proof.md",
      content:
        "# VSIX Resource Detail Proof\n\nInstalled extension authoritative resource detail for the resource surface.\n",
    },
    {
      name: "vsix-sandbox-preview-proof.md",
      content:
        "# VSIX Sandbox Preview Proof\n\nInstalled extension authoritative sandbox preview for the resource surface.\n",
    },
  ];
  for (const fixture of resourceFixtures) {
    fs.writeFileSync(path.join(workspaceDir, fixture.name), fixture.content, "utf8");
  }
}

function provisionTemporaryTrainerWorkspace() {
  const rootPath = path.resolve(trainerWorkspaceDir);
  const directories = [
    "Projects",
    "Knowledge",
    "Skills",
    "Agents",
    "Assets",
    ".trainer",
    path.join(".trainer", "memory"),
    path.join(".trainer", "plans"),
    path.join(".trainer", "indexes"),
    path.join(".trainer", "checkpoints"),
    path.join(".trainer", "logs"),
    path.join(".trainer", "cache"),
  ];
  for (const directory of directories) {
    fs.mkdirSync(path.join(rootPath, directory), { recursive: true });
  }

  const now = new Date().toISOString();
  fs.writeFileSync(
    path.join(rootPath, ".trainer", "workspace.json"),
    `${JSON.stringify(
      {
        schemaVersion: 2,
        kind: "trainer-workspace",
        rootPath,
        canonicalRootPath: rootPath,
        legacyRootPaths: [],
        manifestRevision: 1,
        pathRevision: 0,
        identityStatus: "pending",
        createdAt: now,
        updatedAt: now,
        directories,
        projects: {},
      },
      null,
      2,
    )}\n`,
    "utf8",
  );

  const globalStorageDir = path.join(userDataDir, "User", "globalStorage");
  fs.mkdirSync(globalStorageDir, { recursive: true });
  const database = new DatabaseSync(path.join(globalStorageDir, "state.vscdb"));
  try {
    database.exec("CREATE TABLE IF NOT EXISTS ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)");
    const extensionState = readVsCodeMementoObject(
      database.prepare("SELECT value FROM ItemTable WHERE key = ?").get(extensionId)?.value,
    );
    extensionState["trainer.workspace.root.v1"] = rootPath;
    database.prepare("INSERT INTO ItemTable (key, value) VALUES (?, ?)").run(
      extensionId,
      JSON.stringify(extensionState),
    );

    const keyIndex = `extensionKeys/${extensionId}@${packageJson.version}`;
    const mementoKeys = readVsCodeMementoKeyList(
      database.prepare("SELECT value FROM ItemTable WHERE key = ?").get(keyIndex)?.value,
    );
    if (!mementoKeys.includes("trainer.workspace.root.v1")) {
      mementoKeys.push("trainer.workspace.root.v1");
    }
    database.prepare("INSERT INTO ItemTable (key, value) VALUES (?, ?)").run(
      keyIndex,
      JSON.stringify(mementoKeys),
    );
  } finally {
    database.close();
  }
}

function readVsCodeMementoObject(value) {
  const text = Buffer.isBuffer(value) ? value.toString("utf8") : typeof value === "string" ? value : "";
  if (!text) {
    return {};
  }
  try {
    const parsed = JSON.parse(text);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function readVsCodeMementoKeyList(value) {
  const text = Buffer.isBuffer(value) ? value.toString("utf8") : typeof value === "string" ? value : "";
  if (!text) {
    return [];
  }
  try {
    const parsed = JSON.parse(text);
    return Array.isArray(parsed)
      ? [...new Set(parsed.filter((item) => typeof item === "string" && item.trim()).map((item) => item.trim()))]
      : [];
  } catch {
    return [];
  }
}

function writeDriverExtension(providerConfiguration) {
  const providerSavePayloadTemplate = buildVsixE2EProviderSavePayloadTemplate(providerConfiguration);

  fs.writeFileSync(
    path.join(driverDir, "package.json"),
    `${JSON.stringify(
      {
        name: "trainer-vsix-e2e-driver",
        displayName: "Trainer VSIX E2E Driver",
        version: "0.0.0",
        publisher: "local",
        engines: { vscode: "^1.96.0" },
        activationEvents: ["onStartupFinished"],
        main: "./extension.js",
      },
      null,
      2,
    )}\n`,
    "utf8",
  );

  fs.writeFileSync(
    path.join(driverDir, "extension.js"),
    String.raw`
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const { execFileSync } = require("node:child_process");
const vscode = require("vscode");

async function activate() {
  const startedAt = Date.now();
const reportPath = process.env.TRAINER_E2E_REPORT_PATH;
const extensionId = process.env.TRAINER_E2E_TARGET_EXTENSION_ID || "local.trainer-extension";
const artifactsDir = process.env.TRAINER_E2E_ARTIFACTS_DIR || "";
const smokeUserDataDir = process.env.TRAINER_E2E_USER_DATA_DIR || "";
const smokeWorkspaceDir = process.env.TRAINER_E2E_WORKSPACE_DIR || "";
const smokeTrainerWorkspaceDir = process.env.TRAINER_E2E_TRAINER_WORKSPACE_DIR || "";
const providerSavePayloadTemplate = ${JSON.stringify(providerSavePayloadTemplate)};
const steps = [];

  const currentSidecarPort = () => {
    const trainerExtension = vscode.extensions.getExtension(extensionId);
    const exported = trainerExtension && trainerExtension.isActive ? trainerExtension.exports : undefined;
    const state = exported && typeof exported.getDebugState === "function" ? exported.getDebugState() : null;
    const port = state && state.sidecar ? Number(state.sidecar.port) : NaN;
    if (!Number.isFinite(port) || port <= 0) {
      throw new Error("No current sidecar port is available from the installed Trainer extension.");
    }
    return port;
  };

  const record = async (name, fn, options = {}) => {
    const step = { name, ok: false, startedAt: new Date().toISOString() };
    steps.push(step);
    try {
      const data = await fn();
      step.ok = options.ok === undefined ? true : Boolean(options.ok(data));
      step.data = sanitize(data);
      if (!step.ok) {
        step.error = options.errorMessage ? options.errorMessage(data) : "Step returned a non-OK result.";
      }
      return data;
    } catch (error) {
      step.error = error && error.stack ? error.stack : String(error);
      throw error;
    } finally {
      step.finishedAt = new Date().toISOString();
      step.durationMs = Date.now() - Date.parse(step.startedAt);
    }
  };

  const readVisibleFacts = (view) => {
    const trainerExtension = vscode.extensions.getExtension(extensionId);
    const exported = trainerExtension && trainerExtension.isActive ? trainerExtension.exports : undefined;
    const state = exported && typeof exported.getDebugState === "function" ? exported.getDebugState() : null;
    return state && state.visibleFacts ? state.visibleFacts[view] || null : null;
  };

  const waitForVisibleFacts = async (view, matches, timeoutMs = 10000) => {
    const deadline = Date.now() + timeoutMs;
    let latest = readVisibleFacts(view);
    while (Date.now() < deadline) {
      latest = readVisibleFacts(view);
      if (matches(latest)) {
        return latest;
      }
      await sleep(120);
    }
    return latest;
  };

  let finalReport;
  try {
    const trainerExtension = await record("find-installed-extension", async () => {
      const extension = vscode.extensions.getExtension(extensionId);
      if (!extension) {
        throw new Error("Installed Trainer extension not found: " + extensionId);
      }
      return {
        id: extension.id,
        packageJSON: {
          name: extension.packageJSON && extension.packageJSON.name,
          publisher: extension.packageJSON && extension.packageJSON.publisher,
          version: extension.packageJSON && extension.packageJSON.version,
        },
      };
    });

    await record("activate-installed-extension", async () => {
      const extension = vscode.extensions.getExtension(extensionId);
      if (!extension) {
        throw new Error("Trainer extension disappeared before activation.");
      }
      await extension.activate();
      return { id: extension.id, isActive: extension.isActive };
    }, { ok: (data) => data && data.isActive === true });

    await record("open-coach-sidebar", async () => {
      const result = await vscode.commands.executeCommand("trainer.openWorkbench");
      await sleep(1500);
      return result;
    }, { ok: (data) => data && data.ok === true });

    await record("focus-sidebar", async () => {
      await vscode.commands.executeCommand("workbench.view.extension.trainer");
      try {
        await vscode.commands.executeCommand("trainer.sidebar.focus");
      } catch (error) {
        return { focused: false, detail: String(error) };
      }
      return { focused: true };
    }, { ok: (data) => data && data.focused === true });

    const sidecarResult = await record("restart-sidecar", async () => {
      const result = await vscode.commands.executeCommand("trainer.sidecar.restart");
      return result;
    }, {
      ok: (data) => data && data.ok === true && data.data && data.data.lifecycle === "ready" && Number.isFinite(data.data.port),
      errorMessage: (data) => "Sidecar did not reach ready state: " + JSON.stringify(data),
    });

    await record("probe-sidecar-health", async () => {
      const port = currentSidecarPort();
      return await getJson(port, "/health");
    }, { ok: (data) => data && (data.ok === true || data.status === "ok" || data.status === "healthy") });

    const admittedWorkspace = await record("admit-temporary-trainer-workspace", async () => {
      const commandResult = await vscode.commands.executeCommand("trainer.workspace.adoptProject");
      await sleep(900);
      const trainerExtension = vscode.extensions.getExtension(extensionId);
      const exported = trainerExtension && trainerExtension.isActive ? trainerExtension.exports : undefined;
      const state = exported && typeof exported.getDebugState === "function" ? exported.getDebugState() : null;
      const trainerWorkspace =
        state && state.bootstrap && state.bootstrap.memory && state.bootstrap.memory.workspace
          ? state.bootstrap.memory.workspace.trainerWorkspace || null
          : null;
      return {
        commandOk: commandResult && commandResult.ok === true,
        rootPath: trainerWorkspace && trainerWorkspace.rootPath || null,
        projectPath: trainerWorkspace && trainerWorkspace.projectPath || null,
        status: trainerWorkspace && trainerWorkspace.status || null,
        rootId: trainerWorkspace && trainerWorkspace.rootId || null,
        projectId: trainerWorkspace && trainerWorkspace.projectId || null,
        contextId: trainerWorkspace && trainerWorkspace.contextId || null,
        sessionId: state && state.sessionId || null,
      };
    }, {
      ok: (data) =>
        Boolean(
          data &&
            data.commandOk === true &&
            data.status === "managed" &&
            data.rootPath &&
            data.projectPath &&
            sameLocalPath(data.rootPath, smokeTrainerWorkspaceDir) &&
            sameLocalPath(data.projectPath, smokeWorkspaceDir) &&
            data.rootId &&
            data.projectId &&
            data.contextId,
        ),
      errorMessage: (data) =>
        "Temporary Trainer Workspace Root was not admitted before gated commands: " + JSON.stringify(data),
    });
    const managedContextId =
      admittedWorkspace && typeof admittedWorkspace.contextId === "string"
        ? admittedWorkspace.contextId
        : "";
    if (!managedContextId) {
      throw new Error("Managed Trainer Workspace did not return a contextId.");
    }

    await record("refresh-memory", async () => {
      return await vscode.commands.executeCommand("trainer.memory.refresh");
    }, { ok: (data) => data && data.ok === true });

    const faultProfile = (process.env.TRAINER_E2E_FAULT_PROFILE || "").trim();
    if (faultProfile === "sidecar-restart") {
      await record("inject-sidecar-restart-fault", async () => {
        const stopped = await vscode.commands.executeCommand("trainer.sidecar.stop");
        await sleep(1200);
        const restarted = await vscode.commands.executeCommand("trainer.sidecar.restart");
        await sleep(1600);

        const restartedPort =
          restarted &&
          restarted.data &&
          typeof restarted.data.port === "number" &&
          Number.isFinite(restarted.data.port)
            ? restarted.data.port
            : null;
        if (!restartedPort) {
          throw new Error("Fault recovery did not return a restarted sidecar port.");
        }

        const health = await getJson(restartedPort, "/health");
        const recoveredMemory = await vscode.commands.executeCommand("trainer.memory.refresh");

        return {
          stoppedOk: stopped && stopped.ok === true,
          restartedOk: restarted && restarted.ok === true,
          restartedLifecycle:
            restarted && restarted.data && restarted.data.lifecycle
              ? restarted.data.lifecycle
              : null,
          restartedPort,
          healthOk:
            health && (health.ok === true || health.status === "ok" || health.status === "healthy"),
          recoveredMemoryOk: recoveredMemory && recoveredMemory.ok === true,
        };
      }, {
        ok: (data) =>
          Boolean(
            data &&
              data.stoppedOk === true &&
              data.restartedOk === true &&
              data.restartedLifecycle === "ready" &&
              Number.isFinite(data.restartedPort) &&
              data.healthOk === true &&
              data.recoveredMemoryOk === true,
          ),
        errorMessage: (data) =>
          "Sidecar restart fault recovery mismatch: " + JSON.stringify(data),
      });
    }

    await record("upload-inline-resource", async () => {
      return await vscode.commands.executeCommand("trainer.resource.upload", {
        mode: "files",
        uploads: [
          {
            name: "vsix-e2e-sandbox-capability.md",
            kind: "markdown",
            source: path.join(smokeWorkspaceDir, "vsix-e2e-sandbox-capability.md"),
            tags: ["vsix-e2e", "sandbox-capability"],
          },
        ],
      });
    }, {
      ok: (data) => {
        const payload = data && data.data;
        return Boolean(
          data &&
            data.ok === true &&
            Array.isArray(payload) &&
            payload.some((item) => item && (item.id || item.resource_id)),
        );
      },
      errorMessage: (data) => "Inline resource upload failed: " + JSON.stringify(data),
    });

    const sandboxRefresh = await record("refresh-sandbox-capability", async () => {
      return await vscode.commands.executeCommand("trainer.sandbox.refresh");
    }, {
      ok: (data) => data && data.ok === true && data.data && typeof data.data === "object",
      errorMessage: (data) => "Sandbox refresh failed: " + JSON.stringify(data),
    });

    const capabilityTruth = await record("assert-sandbox-capability-truth", async () => {
      const sandboxState = sandboxRefresh && sandboxRefresh.data ? sandboxRefresh.data : null;
      const capabilitySummary = readSandboxCapabilitySummary(sandboxState);
      const networkStatus = readSandboxField(capabilitySummary, "network_execution_status", "networkExecutionStatus");
      const permissionState = readSandboxField(capabilitySummary, "permission_state", "permissionState");
      const skillManifestStatus = readSandboxField(
        capabilitySummary,
        "skill_manifest_status",
        "skillManifestStatus",
      );
      const skillRuntimeStatus = readSandboxField(
        capabilitySummary,
        "skill_runtime_status",
        "skillRuntimeStatus",
      );
      const networkFacts = readSandboxField(networkStatus, "network_facts", "networkFacts");
      const nonPython = readSandboxField(networkFacts, "non_python", "nonPython");
      const osContainer = readSandboxField(networkFacts, "os_container", "osContainer");
      const osContainerProbe = readSandboxField(networkFacts, "os_container_probe", "osContainerProbe");
      const platformInfo = capabilitySummary && typeof capabilitySummary === "object" ? capabilitySummary.platform || null : null;

      return {
        hasCapabilitySummary: Boolean(capabilitySummary),
        permissionState: permissionState || null,
        skillManifestStatus:
          skillManifestStatus && typeof skillManifestStatus === "object" ? skillManifestStatus.status || null : null,
        skillManifestPolicy:
          skillManifestStatus && typeof skillManifestStatus === "object" ? skillManifestStatus.policy || null : null,
        skillRuntimeStatus:
          skillRuntimeStatus && typeof skillRuntimeStatus === "object" ? skillRuntimeStatus.status || null : null,
        skillRuntimePolicy:
          skillRuntimeStatus && typeof skillRuntimeStatus === "object" ? skillRuntimeStatus.policy || null : null,
        platformOs: platformInfo && typeof platformInfo === "object" ? platformInfo.os || null : null,
        networkExecutionStatus: networkStatus && typeof networkStatus === "object" ? networkStatus.status || null : null,
        networkReasonCode:
          networkStatus && typeof networkStatus === "object"
            ? networkStatus.reason_code || networkStatus.reasonCode || null
            : null,
        networkPolicy: networkStatus && typeof networkStatus === "object" ? networkStatus.policy || null : null,
        nonPythonStatus: nonPython && typeof nonPython === "object" ? nonPython.status || null : null,
        nonPythonCurrentEnforcement:
          nonPython && typeof nonPython === "object"
            ? nonPython.current_enforcement || nonPython.currentEnforcement || null
            : null,
        nonPythonReasonCode:
          nonPython && typeof nonPython === "object"
            ? nonPython.reason_code || nonPython.reasonCode || null
            : null,
        nonPythonRequiredExecutor:
          nonPython && typeof nonPython === "object"
            ? nonPython.required_executor || nonPython.requiredExecutor || null
            : null,
        osContainerStatus: osContainer && typeof osContainer === "object" ? osContainer.status || null : null,
        osContainerCurrentEnforcement:
          osContainer && typeof osContainer === "object"
            ? osContainer.current_enforcement || osContainer.currentEnforcement || null
            : null,
        osContainerRequiredExecutor:
          osContainer && typeof osContainer === "object"
            ? osContainer.required_executor || osContainer.requiredExecutor || null
            : null,
        osContainerReasonCode:
          osContainer && typeof osContainer === "object"
            ? osContainer.reason_code || osContainer.reasonCode || null
            : null,
        osContainerProbeAvailability:
          osContainerProbe && typeof osContainerProbe === "object"
            ? osContainerProbe.availability || null
            : null,
        osContainerSelectedRuntime:
          osContainerProbe && typeof osContainerProbe === "object"
            ? osContainerProbe.selected_runtime || osContainerProbe.selectedRuntime || null
            : null,
        osContainerSelectedEntryRuntime:
          osContainerProbe && typeof osContainerProbe === "object"
            ? osContainerProbe.selected_entry_runtime || osContainerProbe.selectedEntryRuntime || null
            : null,
        osContainerProbeReasonCode:
          osContainerProbe && typeof osContainerProbe === "object"
            ? osContainerProbe.reason_code || osContainerProbe.reasonCode || null
            : null,
        osContainerSupportedEntryRuntimes:
          osContainerProbe && typeof osContainerProbe === "object"
            ? osContainerProbe.supported_entry_runtimes || osContainerProbe.supportedEntryRuntimes || []
            : [],
      };
    }, {
      ok: (data) =>
        Boolean(
          data &&
            data.hasCapabilitySummary === true &&
            data.permissionState === "coach_only" &&
            data.skillManifestStatus === "available" &&
            data.skillManifestPolicy === "trainer.resource_sandbox.skill_manifest.v1" &&
            data.skillRuntimeStatus === "available" &&
            data.skillRuntimePolicy === "trainer.resource_sandbox.skill_runtime.v1" &&
            ["windows", "macos", "linux"].includes(String(data.platformOs || "")) &&
            data.networkExecutionStatus === "degraded" &&
            installedStateNetworkReasonCodes().includes(String(data.networkReasonCode || "")) &&
            (
              String(data.osContainerReasonCode || "") ===
                String(data.osContainerProbeReasonCode || "") ||
              (
                data.osContainerProbeAvailability === "available" &&
                String(data.osContainerProbeReasonCode || "") === ""
              )
            ) &&
            data.nonPythonStatus === "guarded_allowlist_only" &&
            data.nonPythonCurrentEnforcement === "node_socket_guard" &&
            ["", null].includes(data.nonPythonReasonCode) &&
            data.nonPythonRequiredExecutor === "node_socket_guard" &&
            data.osContainerRequiredExecutor === "os_container_egress" &&
            ["missing", "blocked", "enforced"].includes(String(data.osContainerStatus || "")) &&
            (
              data.osContainerProbeAvailability === "available"
                ? data.osContainerStatus === "enforced" && data.osContainerCurrentEnforcement === "os_container_egress"
                : (
                    ["missing", "blocked"].includes(String(data.osContainerStatus || "")) &&
                    data.osContainerCurrentEnforcement !== "os_container_egress"
                  )
            ),
        ),
      errorMessage: (data) =>
        "Sandbox capability truth mismatch. Expected public skill-manifest/runtime audit capability, permission_state=coach_only, network_execution_status=degraded, and an installed-state network reason that matches the current host/runtime truth: " +
        JSON.stringify(data),
    });

    const providerBaseUrl = (process.env.TRAINER_E2E_PROVIDER_BASE_URL || "").trim();
    const providerApiKey = (process.env.TRAINER_E2E_PROVIDER_API_KEY || "").trim();
    const providerModel = (process.env.TRAINER_E2E_PROVIDER_MODEL || "").trim();
    const providerSource = process.env.TRAINER_E2E_PROVIDER_SOURCE === "external" ? "external" : "fixture";

    const hasProviderEnv = Boolean(providerBaseUrl && providerApiKey && providerModel);
    if (!hasProviderEnv) {
      throw new Error("VSIX E2E provider runtime did not provide a complete connection.");
    }
    const providerBoundTimeoutOverrideMs = Number.parseInt(
      process.env.TRAINER_E2E_PROVIDER_TIMEOUT_MS ?? "",
      10,
    );
    const providerBoundRequestTimeoutMs =
      Number.isFinite(providerBoundTimeoutOverrideMs) && providerBoundTimeoutOverrideMs >= 30_000
        ? providerBoundTimeoutOverrideMs
        : 150_000;
    const postProviderBoundJson = (port, requestPath, body) =>
      postJson(port, requestPath, body, providerBoundRequestTimeoutMs);
    const providerSettingsConfig = () => ({
      ...providerSavePayloadTemplate,
      baseUrl: providerBaseUrl,
      apiKeyRef: "trainer.default",
      model: providerModel,
    });
    const providerTransportConfig = () => ({
      ...providerSavePayloadTemplate,
      base_url: providerBaseUrl,
      api_key_ref: "trainer.default",
      model: providerModel,
    });
    const hasCoachConversationMetadata = (data) => {
      const response = data && data.data;
      const text = JSON.stringify(response || {});
      return Boolean(data && data.ok === true && /conversation_candidates|coach_visible_status|assistant|message/i.test(text));
    };

    await record("provider-and-message", async () => {
      await record("set-provider-verification-language", async () => {
        const result = await vscode.commands.executeCommand("trainer.memory.saveCoachSettings", {
          responseLanguage: "zh-CN",
          answerMode: "coach-first",
        });
        return {
          commandOk: Boolean(result && result.ok === true),
          responseLanguage: "zh-CN",
        };
      }, {
        ok: (data) => data && data.commandOk === true && data.responseLanguage === "zh-CN",
        errorMessage: (data) =>
          "Failed to persist zh-CN before provider verification: " + JSON.stringify(data),
      });

      await record("save-provider", async () => {
        return await vscode.commands.executeCommand("trainer.provider.save", {
          ...providerSavePayloadTemplate,
          baseUrl: providerBaseUrl,
          model: providerModel,
          apiKey: providerApiKey,
          replaceApiKey: true,
        });
      }, { ok: (data) => data && data.ok === true });

      const coachMessageResult = await record("send-coach-message", async () => {
        return await vscode.commands.executeCommand("trainer.session.sendMessage", {
          text: "请只作为代码教练回答：我想理解这个临时项目，先给我一个不替我写代码的最小训练切片。",
          intent: "coach",
          responseLanguage: "zh-CN",
          answerMode: "coach-first",
        });
      }, {
        ok: hasCoachConversationMetadata,
        errorMessage: (data) => "Coach message did not return expected conversation metadata: " + JSON.stringify(data),
      });
      if (!hasCoachConversationMetadata(coachMessageResult)) {
        throw new Error("Coach message did not complete through the configured provider.");
      }
      return { source: providerSource, model: providerModel };
    }, {
      ok: (data) => data && (data.source === "fixture" || data.source === "external") && Boolean(data.model),
      errorMessage: (data) => "Provider/message journey did not finish: " + JSON.stringify(data),
    });

    const reviewQueueSeed = await record("seed-review-queue-through-public-command", async () => {
      const reviewResult = await vscode.commands.executeCommand("trainer.training.reviewQueueAction", {
        concept: "dependency injection",
        action: "reset",
        note: "Still needs another governed pass before transfer.",
      });
      const response = reviewResult && reviewResult.data ? reviewResult.data : null;
      const actions = Array.isArray(response && response.actions) ? response.actions : [];
      const createdAction = actions[0] || null;
      const trainerExtension = vscode.extensions.getExtension(extensionId);
      const exported = trainerExtension && trainerExtension.isActive ? trainerExtension.exports : undefined;
      const state =
        exported && typeof exported.getDebugState === "function"
          ? exported.getDebugState()
          : null;
      const trainingState = state && state.bootstrap ? state.bootstrap.workspaceTrainingState || null : null;
      const reviewArtifact = trainingState && trainingState.reviewArtifact ? trainingState.reviewArtifact : null;
      return {
        commandOk: Boolean(reviewResult && reviewResult.ok === true),
        responseOk: Boolean(response && response.ok === true),
        actionCount: actions.length,
        action: createdAction ? createdAction.action || null : null,
        actionConcept: createdAction ? createdAction.concept || null : null,
        actionOutcome: createdAction ? createdAction.outcome || null : null,
        reviewArtifactId: reviewArtifact ? reviewArtifact.id || null : null,
        reviewArtifactSource: reviewArtifact ? reviewArtifact.source || null : null,
        reviewArtifactFocusArea: reviewArtifact ? reviewArtifact.focusArea || null : null,
        reviewArtifactLastAction: reviewArtifact ? reviewArtifact.lastAction || null : null,
        latestTrainingSubmode: trainingState ? trainingState.latestTrainingSubmode || null : null,
      };
    }, {
      ok: (data) =>
        Boolean(
          data &&
            data.commandOk === true &&
            data.responseOk === true &&
            data.actionCount >= 1 &&
            data.action === "reset" &&
            data.actionConcept === "dependency injection" &&
            data.actionOutcome === "needs_more_practice" &&
            data.reviewArtifactId &&
            data.reviewArtifactSource === "review_queue" &&
            data.reviewArtifactFocusArea === "dependency injection" &&
            data.reviewArtifactLastAction === "reviewed" &&
            data.latestTrainingSubmode === "review_queue",
        ),
      errorMessage: (data) =>
        "Installed-state review queue seed mismatch: " + JSON.stringify(data),
    });

    await record("assert-training-review-queue-visible-truth", async () => {
      const expectedReviewArtifactId = reviewQueueSeed && reviewQueueSeed.reviewArtifactId;
      const trainerExtension = vscode.extensions.getExtension(extensionId);
      const exported = trainerExtension && trainerExtension.isActive ? trainerExtension.exports : undefined;
      const state =
        exported && typeof exported.getDebugState === "function"
          ? exported.getDebugState()
          : null;
      const trainingState = state && state.bootstrap ? state.bootstrap.workspaceTrainingState || null : null;
      const reviewArtifact = trainingState && trainingState.reviewArtifact ? trainingState.reviewArtifact : null;
      return {
        hasHostTrainingState: Boolean(trainingState),
        workbenchVisible: Boolean(state && state.workbench && state.workbench.viewVisible === true),
        latestTrainingSubmode: trainingState ? trainingState.latestTrainingSubmode || null : null,
        reviewArtifactId: reviewArtifact ? reviewArtifact.id || null : null,
        reviewArtifactSource: reviewArtifact ? reviewArtifact.source || null : null,
        reviewArtifactStatus: reviewArtifact ? reviewArtifact.status || null : null,
        expectedReviewArtifactId,
      };
      }, {
        ok: (data) =>
          Boolean(
            data &&
              data.hasHostTrainingState === true &&
              data.workbenchVisible === true &&
              data.latestTrainingSubmode === "review_queue" &&
              data.reviewArtifactId === data.expectedReviewArtifactId &&
              data.reviewArtifactSource === "review_queue" &&
              data.reviewArtifactStatus === "active" &&
              data.expectedReviewArtifactId
          ),
        errorMessage: (data) =>
          "Installed-state review queue host-state mismatch: " + JSON.stringify(data),
      });

      await record("capture-training-review-queue-installed-screenshot", async () => {
        const captured = captureVsCodeWindowArtifacts({
          label: "training-review-queue",
          artifactsDir,
          sideBarRatio: 0.36,
          userDataDir: smokeUserDataDir,
          workspaceDir: smokeWorkspaceDir,
          vscodePid: process.env.VSCODE_PID || "",
        });
        return {
          ...captured,
          exists:
            Boolean(captured.windowScreenshotPath && fs.existsSync(captured.windowScreenshotPath)) &&
            Boolean(captured.sidebarScreenshotPath && fs.existsSync(captured.sidebarScreenshotPath)),
        };
      }, {
        ok: isWindowCaptureVerified,
        errorMessage: (data) =>
          "Installed-state training screenshot capture failed: " + JSON.stringify(data),
      });

      await record("assert-training-theory-drill-visible-truth", async () => {
        const port = currentSidecarPort();

        const started = await postJson(port, "/session/start", {
          workspace_id: managedContextId,
          workspace_name: path.basename(smokeWorkspaceDir) || "trainer-vsix-e2e",
          workspace_path: smokeWorkspaceDir,
          profile: {
            long_term_goal: "Installed-state theory drill truth must stay object-level and learner-owned.",
            weekly_hours: 4,
            teaching_style: "guided",
            answer_policy: "guided",
            preferred_libraries: ["FastAPI"],
          },
        });
        const sessionId = started && (started.session_id || started.sessionId);
        if (!sessionId) {
          throw new Error("Theory drill smoke did not return a session id.");
        }

        const generatedCardResult = await vscode.commands.executeCommand("trainer.training.generateCard", {
          source: "vsix_e2e",
          cardType: "flash",
          submode: "flash",
          focusArea: "dependency injection",
          targetSkill: "FastAPI Depends",
          prompt: "Create one small recall card about FastAPI dependency injection.",
        });
        const generatedCard = generatedCardResult && generatedCardResult.data
          ? generatedCardResult.data.card || null
          : null;
        const generatedCardId = generatedCard && (generatedCard.card_id || generatedCard.cardId)
          ? generatedCard.card_id || generatedCard.cardId
          : null;
        if (!generatedCardResult || generatedCardResult.ok !== true || !generatedCardId) {
          throw new Error("Public training card command did not materialize a card.");
        }

        await postJson(port, "/learning/signal", {
          session_id: sessionId,
          workspace_id: managedContextId,
          concepts: ["FastAPI"],
          outcome: "repeated_error",
          summary: "The learner needs one governed FastAPI dependency practice loop.",
          focus_area: "dependency injection",
          scenario: "dependency_mastery",
          related_api: "Depends",
          blocked_reason: "The learner has not yet connected Depends to a route boundary.",
          repetition_count: 1,
        });
        await vscode.commands.executeCommand("trainer.memory.refresh");

        const dependencyMasterySeed = await record(
          "seed-dependency-mastery-through-public-command",
          async () => {
            const actionResult = await vscode.commands.executeCommand(
              "trainer.training.dependencySkillMapAction",
              {
                dependencyKey: "fastapi",
                action: "mark_practiced",
                note: "Create one governed FastAPI dependency practice map before the theory drill.",
                relatedApi: "Depends",
                scenario: "dependency_mastery",
              },
            );
            const response = actionResult && actionResult.data ? actionResult.data : null;
            const maps = Array.isArray(response && response.maps) ? response.maps : [];
            const dependencyMap = maps.find(
              (item) =>
                item &&
                String(item.dependency_key || item.dependencyKey || "").toLowerCase() === "fastapi",
            );
            const responseScenarioLab = response && response.scenario_lab ? response.scenario_lab : null;
            const trainerExtension = vscode.extensions.getExtension(extensionId);
            const exported = trainerExtension && trainerExtension.isActive ? trainerExtension.exports : undefined;
            const state =
              exported && typeof exported.getDebugState === "function"
                ? exported.getDebugState()
                : null;
            const trainingState = state && state.bootstrap ? state.bootstrap.workspaceTrainingState || null : null;
            const hostScenarioLab = trainingState && trainingState.scenarioLab ? trainingState.scenarioLab : null;
            return {
              commandOk: Boolean(actionResult && actionResult.ok === true),
              responseOk: Boolean(response && response.ok === true),
              mapCount: maps.length,
              dependencyKey: dependencyMap ? dependencyMap.dependency_key || dependencyMap.dependencyKey || null : null,
              responseScenarioLabId: responseScenarioLab ? responseScenarioLab.id || null : null,
              hostScenarioLabId: hostScenarioLab ? hostScenarioLab.id || null : null,
            };
          },
          {
            ok: (data) =>
              Boolean(
                data &&
                  data.commandOk === true &&
                  data.responseOk === true &&
                  data.mapCount >= 1 &&
                  String(data.dependencyKey || "").toLowerCase() === "fastapi" &&
                  data.responseScenarioLabId &&
                  data.hostScenarioLabId === data.responseScenarioLabId,
              ),
            errorMessage: (data) =>
              "Public dependency mastery seed mismatch: " + JSON.stringify(data),
          },
        );
        if (!dependencyMasterySeed || dependencyMasterySeed.mapCount < 1) {
          throw new Error("Public dependency skill map command did not establish FastAPI mastery.");
        }

        await postJson(port, "/learning/signal", {
          session_id: sessionId,
          workspace_id: managedContextId,
          concepts: ["FastAPI", "Depends"],
          outcome: "repeated_error",
          summary: "Still cannot explain when to use Depends in a concrete route.",
          focus_area: "dependency injection",
          scenario: "dependency_mastery",
          related_api: "Depends",
          blocked_reason: "The learner still cannot connect Depends back to a real route.",
          repetition_count: 2,
        });
        await vscode.commands.executeCommand("trainer.memory.refresh");
        await sleep(400);

        const trainerExtension = vscode.extensions.getExtension(extensionId);
        const exported = trainerExtension && trainerExtension.isActive ? trainerExtension.exports : undefined;
        const bootstrapState =
          exported && typeof exported.getDebugState === "function"
            ? exported.getDebugState()
            : null;
        const trainingState =
          bootstrapState && bootstrapState.bootstrap
            ? bootstrapState.bootstrap.workspaceTrainingState || null
            : null;
        const theoryDrill = trainingState && trainingState.theoryDrill ? trainingState.theoryDrill : null;
        if (!theoryDrill || !theoryDrill.id) {
          throw new Error("Theory drill was not materialized into host memory.");
        }
        const pendingTheoryQuestion =
          Array.isArray(theoryDrill.questions) &&
          Number.isInteger(theoryDrill.currentQuestionIndex) &&
          theoryDrill.questions[theoryDrill.currentQuestionIndex]
            ? theoryDrill.questions[theoryDrill.currentQuestionIndex]
            : Array.isArray(theoryDrill.questions) && theoryDrill.questions[0]
              ? theoryDrill.questions[0]
              : null;
        if (!pendingTheoryQuestion || !pendingTheoryQuestion.id) {
          throw new Error("Theory drill did not expose a current question.");
        }

        await vscode.commands.executeCommand("trainer.training.theoryDrillAnswer", {
          theoryDrillId: theoryDrill.id,
          questionId: pendingTheoryQuestion.id,
          learnerAnswer: "I still mix dependency injection with any helper function.",
        });
        await sleep(500);

        const refreshedBootstrapState =
          exported && typeof exported.getDebugState === "function"
            ? exported.getDebugState()
            : null;
        const refreshedTrainingState =
          refreshedBootstrapState && refreshedBootstrapState.bootstrap
            ? refreshedBootstrapState.bootstrap.workspaceTrainingState || null
            : null;
        const refreshedTheoryDrill =
          refreshedTrainingState && refreshedTrainingState.theoryDrill
            ? refreshedTrainingState.theoryDrill
            : null;
        if (!refreshedTheoryDrill || !refreshedTheoryDrill.id) {
          throw new Error("Theory drill disappeared after the installed-state wrong answer path.");
        }
        const theoryDrillId = refreshedTheoryDrill.id;
        const theoryQuestion =
          Array.isArray(refreshedTheoryDrill.questions) &&
          Number.isInteger(refreshedTheoryDrill.currentQuestionIndex) &&
          refreshedTheoryDrill.questions[refreshedTheoryDrill.currentQuestionIndex]
            ? refreshedTheoryDrill.questions[refreshedTheoryDrill.currentQuestionIndex]
            : Array.isArray(refreshedTheoryDrill.questions) && refreshedTheoryDrill.questions[0]
              ? refreshedTheoryDrill.questions[0]
              : pendingTheoryQuestion;

        const state =
          exported && typeof exported.getDebugState === "function"
            ? exported.getDebugState()
            : null;
        const currentTrainingState =
          state && state.bootstrap ? state.bootstrap.workspaceTrainingState || null : null;
        const currentTheoryDrill =
          currentTrainingState && currentTrainingState.theoryDrill
            ? currentTrainingState.theoryDrill
            : null;
        return {
          sessionId,
          generatedCardId,
          generatedCardPresent: Boolean(
            currentTrainingState &&
              Array.isArray(currentTrainingState.trainingCardCandidates) &&
              currentTrainingState.trainingCardCandidates.some(
                (candidate) => candidate && candidate.cardId === generatedCardId,
              ),
          ),
          theoryDrillId,
          hasHostTrainingState: Boolean(currentTrainingState),
          workbenchVisible: Boolean(state && state.workbench && state.workbench.viewVisible === true),
          currentTheoryDrillId: currentTheoryDrill ? currentTheoryDrill.id || null : null,
          theoryDrillTitle: currentTheoryDrill ? currentTheoryDrill.title || null : null,
          theoryDrillStatus: currentTheoryDrill ? currentTheoryDrill.status || null : null,
          theoryQuestionPrompt: theoryQuestion ? theoryQuestion.prompt || null : null,
        };
      }, {
        ok: (data) =>
          Boolean(
            data &&
              data.hasHostTrainingState === true &&
              data.workbenchVisible === true &&
              data.generatedCardPresent === true &&
              data.currentTheoryDrillId === data.theoryDrillId &&
              typeof data.theoryDrillTitle === "string" &&
              data.theoryDrillTitle.length > 0 &&
              ["ready", "in_progress", "completed", "archived"].includes(String(data.theoryDrillStatus || "")) &&
              typeof data.theoryQuestionPrompt === "string" &&
              data.theoryQuestionPrompt.length > 0
          ),
        errorMessage: (data) =>
          "Installed-state theory drill host-state mismatch: " + JSON.stringify(data),
      });

      await record("capture-training-theory-drill-installed-screenshot", async () => {
        const captured = captureVsCodeWindowArtifacts({
          label: "training-theory-drill",
          artifactsDir,
          sideBarRatio: 0.36,
          userDataDir: smokeUserDataDir,
          workspaceDir: smokeWorkspaceDir,
          vscodePid: process.env.VSCODE_PID || "",
        });
        return {
          ...captured,
          exists:
            Boolean(captured.windowScreenshotPath && fs.existsSync(captured.windowScreenshotPath)) &&
            Boolean(captured.sidebarScreenshotPath && fs.existsSync(captured.sidebarScreenshotPath)),
        };
      }, {
        ok: isWindowCaptureVerified,
        errorMessage: (data) =>
          "Installed-state theory drill screenshot capture failed: " + JSON.stringify(data),
      });

      await record("assert-training-scenario-lab-visible-truth", async () => {
        const port = currentSidecarPort();

        const started = await postJson(port, "/session/start", {
          workspace_id: managedContextId,
          workspace_name: path.basename(smokeWorkspaceDir) || "trainer-vsix-e2e",
          workspace_path: smokeWorkspaceDir,
          profile: {
            long_term_goal: "Installed-state scenario lab truth must stay learner-owned and restorable.",
            weekly_hours: 4,
            teaching_style: "guided",
            answer_policy: "guided",
            preferred_libraries: ["FastAPI"],
          },
        });
        const sessionId = started && (started.session_id || started.sessionId);
        if (!sessionId) {
          throw new Error("Scenario lab smoke did not return a session id.");
        }

        await postJson(port, "/learning/signal", {
          session_id: sessionId,
          workspace_id: managedContextId,
          concepts: ["FastAPI", "Depends"],
          outcome: "repeated_error",
          summary: "Still cannot explain when to use Depends in a concrete route.",
          focus_area: "dependency injection",
          scenario: "dependency_mastery",
          related_api: "Depends",
          blocked_reason: "The learner still cannot connect Depends back to a real route.",
        });
        await vscode.commands.executeCommand("trainer.memory.refresh");
        await sleep(300);

        const trainerExtension = vscode.extensions.getExtension(extensionId);
        const exported = trainerExtension && trainerExtension.isActive ? trainerExtension.exports : undefined;
        const bootstrapState =
          exported && typeof exported.getDebugState === "function"
            ? exported.getDebugState()
            : null;
        const trainingState =
          bootstrapState && bootstrapState.bootstrap
            ? bootstrapState.bootstrap.workspaceTrainingState || null
            : null;
        const memory = bootstrapState && bootstrapState.bootstrap ? bootstrapState.bootstrap.memory || null : null;
        let scenarioLab =
          (trainingState && trainingState.scenarioLab) ||
          (memory && memory.scenarioLab) ||
          null;
        if (!scenarioLab || !scenarioLab.id) {
          const theoryDrill =
            (trainingState && trainingState.theoryDrill) ||
            (memory && memory.theoryDrill) ||
            null;
          const pendingTheoryQuestion =
            theoryDrill &&
            Array.isArray(theoryDrill.questions) &&
            Number.isInteger(theoryDrill.currentQuestionIndex) &&
            theoryDrill.questions[theoryDrill.currentQuestionIndex]
              ? theoryDrill.questions[theoryDrill.currentQuestionIndex]
              : theoryDrill && Array.isArray(theoryDrill.questions) && theoryDrill.questions[0]
                ? theoryDrill.questions[0]
                : null;
          const theoryQuestionId =
            pendingTheoryQuestion && (pendingTheoryQuestion.questionId || pendingTheoryQuestion.id);
          if (!theoryDrill || !theoryDrill.id || !theoryQuestionId) {
            throw new Error("Neither scenario lab nor theory drill was materialized into host memory.");
          }
          await vscode.commands.executeCommand("trainer.theoryDrill.submitAnswer", {
            theoryDrillId: theoryDrill.id,
            questionId: theoryQuestionId,
            learnerAnswer: "I still cannot connect Depends back to a learner-owned route slice.",
          });
          await sleep(500);
        }

        const refreshedState =
          exported && typeof exported.getDebugState === "function"
            ? exported.getDebugState()
            : null;
        const refreshedMemory =
          refreshedState && refreshedState.bootstrap ? refreshedState.bootstrap.memory || null : null;
        const refreshedTrainingState =
          refreshedState && refreshedState.bootstrap
            ? refreshedState.bootstrap.workspaceTrainingState || null
            : null;
        scenarioLab =
          (refreshedTrainingState && refreshedTrainingState.scenarioLab) ||
          (refreshedMemory && refreshedMemory.scenarioLab) ||
          null;
        if (!scenarioLab || !scenarioLab.id) {
          throw new Error("Scenario lab was not materialized into host memory.");
        }
        const scenarioLabId = scenarioLab.id;

        const restoreResult = await vscode.commands.executeCommand("trainer.debug.restoreView", {
          sessionId,
          workspaceId: managedContextId,
          activeView: "practice",
          trainingSubmode: "practice",
          trainingRestoreTarget: "scenario_lab",
          scenarioLabId,
          workspaceLabel: "trainer-vsix-e2e",
          resumeReason: "Show the installed scenario lab truth.",
          focusArea: scenarioLab.focusArea || "dependency injection",
        });
        if (!restoreResult || restoreResult.ok !== true) {
          throw new Error("Scenario lab restore command did not succeed: " + JSON.stringify(restoreResult));
        }
        const visible = await waitForVisibleFacts(
          "training",
          (facts) =>
            Boolean(
              facts &&
                facts.surface === "training" &&
                facts.activeView === "training" &&
                facts.restoreKind === "scenario_lab" &&
                facts.scenarioLabVisible === true &&
                facts.scenarioLabId === scenarioLabId &&
                facts.scenarioLabTitle === scenarioLab.title &&
                facts.singleCardImmersive === true &&
                facts.cardOnlyMode === true,
            ),
        );
        const facts = visible;
        return {
          sessionId,
          scenarioLabId,
          restoreSucceeded: restoreResult.ok === true,
          hasVisibleFacts: Boolean(visible),
          surface: visible ? visible.surface || null : null,
          activeView: visible ? visible.activeView || null : null,
          restoreKind: facts ? facts.restoreKind || null : null,
          surfaceMode: facts ? facts.surfaceMode || null : null,
          activeSubmode: facts ? facts.activeSubmode || null : null,
          scenarioLabMaterialized: Boolean(scenarioLab && scenarioLab.id),
          scenarioLabVisible: facts ? facts.scenarioLabVisible === true : false,
          visibleScenarioLabId: facts ? facts.scenarioLabId || null : null,
          scenarioLabTitle: facts ? facts.scenarioLabTitle || null : null,
          scenarioLabStatus: facts ? facts.scenarioLabStatus || null : null,
          scenarioLabScenario: facts ? facts.scenarioLabScenario || null : null,
          expectedScenarioLabTitle: scenarioLab ? scenarioLab.title || null : null,
          singleCardImmersive: facts ? facts.singleCardImmersive === true : false,
          routeStripCollapsedByDefault: facts ? facts.routeStripCollapsedByDefault === true : false,
          cardOnlyMode: facts ? facts.cardOnlyMode === true : false,
          secondaryPanelsCollapsedByDefault: facts ? facts.secondaryPanelsCollapsedByDefault === true : false,
        };
      }, {
        ok: (data) =>
          Boolean(
              data &&
              data.restoreSucceeded === true &&
              data.hasVisibleFacts === true &&
              data.surface === "training" &&
              data.activeView === "training" &&
              data.surfaceMode === "project" &&
              ["practice", "review", "review_queue", "flash"].includes(String(data.activeSubmode || "")) &&
              data.scenarioLabMaterialized === true &&
              typeof data.expectedScenarioLabTitle === "string" &&
              data.expectedScenarioLabTitle.length > 0 &&
              data.restoreKind === "scenario_lab" &&
              data.scenarioLabVisible === true &&
              data.visibleScenarioLabId === data.scenarioLabId &&
              data.scenarioLabTitle === data.expectedScenarioLabTitle &&
              data.singleCardImmersive === true &&
              data.routeStripCollapsedByDefault === true &&
              data.cardOnlyMode === true &&
              data.secondaryPanelsCollapsedByDefault === true
          ),
        errorMessage: (data) =>
          "Installed-state scenario lab handoff truth mismatch: " + JSON.stringify(data),
      });

      await record("capture-training-scenario-lab-installed-screenshot", async () => {
        const captured = captureVsCodeWindowArtifacts({
          label: "training-scenario-lab",
          artifactsDir,
          sideBarRatio: 0.36,
          userDataDir: smokeUserDataDir,
          workspaceDir: smokeWorkspaceDir,
          vscodePid: process.env.VSCODE_PID || "",
        });
        return {
          ...captured,
          exists:
            Boolean(captured.windowScreenshotPath && fs.existsSync(captured.windowScreenshotPath)) &&
            Boolean(captured.sidebarScreenshotPath && fs.existsSync(captured.sidebarScreenshotPath)),
        };
      }, {
        ok: isWindowCaptureVerified,
        errorMessage: (data) =>
          "Installed-state scenario lab screenshot capture failed: " + JSON.stringify(data),
      });

      if (hasProviderEnv) {
      await record("assert-training-next-hop-visible-truth", async () => {
        const port = currentSidecarPort();

        const started = await postProviderBoundJson(port, "/session/start", {
          workspace_id: managedContextId,
          workspace_name: path.basename(smokeWorkspaceDir) || "trainer-vsix-e2e",
          workspace_path: smokeWorkspaceDir,
          profile: {
            long_term_goal: "Installed-state next-hop truth must stay governed and learner-owned.",
            weekly_hours: 4,
            teaching_style: "guided",
            answer_policy: "guided",
            preferred_libraries: ["FastAPI"],
          },
        });
        const sessionId = started && (started.session_id || started.sessionId);
        if (!sessionId) {
          throw new Error("Next-hop smoke did not return a session id.");
        }

        const bootstrapProvider = await postJson(port, "/memory/settings", {
          session_id: sessionId,
          workspace_id: managedContextId,
          response_language: "zh-CN",
          answer_mode: "coach-first",
        });
        if (!bootstrapProvider || bootstrapProvider.ok === false) {
          throw new Error("Failed to save provider settings before next-hop smoke.");
        }

        await postProviderBoundJson(port, "/turn", {
          session_id: sessionId,
          workspace_id: managedContextId,
          intent: "coach",
          message: "先给我一张不替我写代码的最小实战卡，聚焦 FastAPI Depends 边界。",
          response_language: "zh-CN",
          answer_mode: "coach-first",
          use_agent_loop: false,
          provider: providerTransportConfig(),
          api_key: providerApiKey,
        });
        await sleep(600);

        const activeCard = await getJson(
          port,
          "/training/active-card?workspace_id=" +
            encodeURIComponent(managedContextId) +
            "&session_id=" +
            encodeURIComponent(sessionId),
        );
        const activeCardId =
          activeCard &&
          (activeCard.selected_card_id ||
            activeCard.selectedCardId ||
            (activeCard.selected_card &&
              (activeCard.selected_card.card_id || activeCard.selected_card.cardId)) ||
            (activeCard.selectedCard &&
              (activeCard.selectedCard.card_id || activeCard.selectedCard.cardId)));
        if (!activeCardId) {
          throw new Error("Next-hop smoke did not create an active training card.");
        }

        const practiceReturn = await postJson(port, "/training/practice-return", {
          workspace_id: managedContextId,
          card_id: activeCardId,
          passed: true,
          summary: "我完成了最小练习，并提交结果等待核验。",
          next_step: "核验当前文件后，再继续下一张训练卡。",
          focus_area: "FastAPI Depends 边界",
          evidence_source: "learner_return",
        });
        if (!practiceReturn || practiceReturn.ok !== true) {
          throw new Error("Practice return smoke did not record the training result.");
        }

        const summary = await getJson(
          port,
          "/memory/summary?session_id=" +
            encodeURIComponent(sessionId) +
            "&workspace_id=" +
            encodeURIComponent(managedContextId),
        );
        const summaryMemory =
          summary && summary.memory && typeof summary.memory === "object" ? summary.memory : null;
        const summaryWorkspace =
          summaryMemory && summaryMemory.workspace && typeof summaryMemory.workspace === "object"
            ? summaryMemory.workspace
            : null;
        const summaryNextHop =
          summaryWorkspace &&
          summaryWorkspace.latest_training_next_hop &&
          typeof summaryWorkspace.latest_training_next_hop === "object"
            ? summaryWorkspace.latest_training_next_hop
            : summaryWorkspace &&
                summaryWorkspace.latestTrainingNextHop &&
                typeof summaryWorkspace.latestTrainingNextHop === "object"
              ? summaryWorkspace.latestTrainingNextHop
              : null;
        const expectedNextHop = summaryNextHop;
        if (!expectedNextHop) {
          throw new Error("Next-hop smoke did not materialize latest_training_next_hop.");
        }
        const expectedReviewArtifactId =
          expectedNextHop.review_artifact_id ||
          expectedNextHop.reviewArtifactId ||
          null;

        await vscode.commands.executeCommand("trainer.memory.refresh");
        await sleep(500);
        await vscode.commands.executeCommand("trainer.debug.restoreView", {
          sessionId,
          workspaceId: managedContextId,
          activeView: "practice",
          trainingSubmode: "practice",
          trainingRestoreTarget: "next_hop",
          reviewArtifactId: expectedReviewArtifactId || undefined,
          workspaceLabel: "trainer-vsix-e2e",
          resumeReason: "Show the installed next-hop truth.",
          focusArea:
            expectedNextHop.why_now ||
            expectedNextHop.whyNow ||
            "dependency injection",
        });
        await sleep(1400);

        const trainerExtension = vscode.extensions.getExtension(extensionId);
        const exported = trainerExtension && trainerExtension.isActive ? trainerExtension.exports : undefined;
        const state =
          exported && typeof exported.getDebugState === "function"
            ? exported.getDebugState()
            : null;
        const bootstrapTrainingState =
          state && state.bootstrap ? state.bootstrap.workspaceTrainingState || null : null;
        const bootstrapMemory =
          state && state.bootstrap && state.bootstrap.memory && typeof state.bootstrap.memory === "object"
            ? state.bootstrap.memory
            : null;
        const bootstrapWorkspace =
          bootstrapTrainingState ||
          (bootstrapMemory &&
            bootstrapMemory.workspace &&
            typeof bootstrapMemory.workspace === "object"
              ? bootstrapMemory.workspace
              : null);
        const bootstrapNextHop =
          (bootstrapTrainingState && bootstrapTrainingState.latestTrainingNextHop) ||
          (bootstrapWorkspace &&
            bootstrapWorkspace.latestTrainingNextHop &&
            typeof bootstrapWorkspace.latestTrainingNextHop === "object"
              ? bootstrapWorkspace.latestTrainingNextHop
              : null);
        const bootstrapLedger = Array.isArray(
          bootstrapTrainingState && bootstrapTrainingState.trainingEventLedger,
        )
          ? bootstrapTrainingState.trainingEventLedger
          : Array.isArray(bootstrapMemory && bootstrapMemory.trainingEventLedger)
          ? bootstrapMemory.trainingEventLedger
          : [];
        const bootstrapLatestMaterializedEvent = [...bootstrapLedger]
          .filter(
            (item) =>
              item &&
              (item.eventType === "training_next_hop_materialized" ||
                item.event_type === "training_next_hop_materialized"),
          )
          .sort((left, right) => {
            const leftTime = Date.parse((left && (left.createdAt || left.created_at)) || "") || 0;
            const rightTime = Date.parse((right && (right.createdAt || right.created_at)) || "") || 0;
            return rightTime - leftTime;
          })[0] || null;
        const visible = state && state.visibleFacts ? state.visibleFacts.training || null : null;
        const facts = visible;
        const expectedCandidateType = expectedNextHop.candidate_type || expectedNextHop.candidateType || null;
        const expectedTargetKind = expectedNextHop.target_kind || expectedNextHop.targetKind || null;
        const expectedTargetId = expectedNextHop.target_id || expectedNextHop.targetId || null;
        const expectedPlanEvidenceId =
          expectedNextHop.plan_evidence_id || expectedNextHop.planEvidenceId || null;
        const expectedContinueIn = expectedNextHop.continue_in || expectedNextHop.continueIn || null;
        const expectedStatus = expectedNextHop.status || null;
        const expectedReviewArtifactIdFromHop = expectedReviewArtifactId;
        const ledgerEvents = Array.isArray(summaryMemory && summaryMemory.training_event_ledger)
          ? summaryMemory.training_event_ledger
          : [];
        const hasPracticeReturnEvent = ledgerEvents.some(
          (item) =>
            item &&
            (item.event_type === "practice_evaluation_recorded" ||
              item.eventType === "practice_evaluation_recorded"),
        );

        return {
          sessionId,
          activeCardId,
          practiceReturnRecorded: practiceReturn.ok === true,
          hasPracticeReturnEvent,
          hasVisibleFacts: Boolean(visible),
          surface: visible ? visible.surface || null : null,
          activeView: visible ? visible.activeView || null : null,
          surfaceMode: facts ? facts.surfaceMode || null : null,
          activeSubmode: facts ? facts.activeSubmode || null : null,
          nextHopVisible: facts ? facts.nextHopVisible === true : false,
          nextHopTitle: facts ? facts.nextHopTitle || null : null,
          nextHopStatus: facts ? facts.nextHopStatus || null : null,
          nextHopContinueIn: facts ? facts.nextHopContinueIn || null : null,
          nextHopCandidateType: facts ? facts.nextHopCandidateType || null : null,
          nextHopTargetKind: facts ? facts.nextHopTargetKind || null : null,
          nextHopTargetId: facts ? facts.nextHopTargetId || null : null,
          nextHopReviewArtifactId: facts ? facts.nextHopReviewArtifactId || null : null,
          nextHopPlanEvidenceId: facts ? facts.nextHopPlanEvidenceId || null : null,
          bootstrapWorkspaceId:
            bootstrapWorkspace
              ? bootstrapWorkspace.workspaceId || bootstrapWorkspace.workspace_id || null
              : null,
          bootstrapNextHopCandidateType:
            bootstrapNextHop
              ? bootstrapNextHop.candidateType || bootstrapNextHop.candidate_type || null
              : null,
          bootstrapNextHopTargetKind:
            bootstrapNextHop
              ? bootstrapNextHop.targetKind || bootstrapNextHop.target_kind || null
              : null,
          bootstrapNextHopTargetId:
            bootstrapNextHop
              ? bootstrapNextHop.targetId || bootstrapNextHop.target_id || null
              : null,
          bootstrapNextHopStatus:
            bootstrapNextHop
              ? bootstrapNextHop.status || null
              : null,
          bootstrapNextHopContinueIn:
            bootstrapNextHop
              ? bootstrapNextHop.continueIn || bootstrapNextHop.continue_in || null
              : null,
          bootstrapLatestMaterializedEventType:
            bootstrapLatestMaterializedEvent
              ? bootstrapLatestMaterializedEvent.eventType || bootstrapLatestMaterializedEvent.event_type || null
              : null,
          bootstrapLatestMaterializedCandidateType:
            bootstrapLatestMaterializedEvent
              ? bootstrapLatestMaterializedEvent.candidateType || bootstrapLatestMaterializedEvent.candidate_type || null
              : null,
          bootstrapLatestMaterializedTargetId:
            bootstrapLatestMaterializedEvent
              ? bootstrapLatestMaterializedEvent.candidateTargetId || bootstrapLatestMaterializedEvent.candidate_target_id || null
              : null,
          bootstrapLatestMaterializedStatus:
            bootstrapLatestMaterializedEvent
              ? bootstrapLatestMaterializedEvent.candidateStatus || bootstrapLatestMaterializedEvent.candidate_status || null
              : null,
          expectedCandidateType,
          expectedTargetKind,
          expectedTargetId,
          expectedPlanEvidenceId,
          expectedContinueIn,
          expectedStatus,
          expectedReviewArtifactId: expectedReviewArtifactIdFromHop,
          singleCardImmersive: facts ? facts.singleCardImmersive === true : false,
          routeStripCollapsedByDefault: facts ? facts.routeStripCollapsedByDefault === true : false,
          cardOnlyMode: facts ? facts.cardOnlyMode === true : false,
          secondaryPanelsCollapsedByDefault: facts ? facts.secondaryPanelsCollapsedByDefault === true : false,
        };
      }, {
        ok: (data) =>
          Boolean(
            data &&
              data.practiceReturnRecorded === true &&
              data.hasPracticeReturnEvent === true &&
              data.hasVisibleFacts === true &&
              data.surface === "training" &&
              data.activeView === "training" &&
              data.surfaceMode === "project" &&
              (
                data.activeSubmode === "practice" ||
                data.activeSubmode === "flash"
              ) &&
              data.nextHopVisible === true &&
              typeof data.nextHopTitle === "string" &&
              data.nextHopTitle.length > 0 &&
                ["created", "surfaced", "accepted", "continued_in_chat", "dismissed", "deferred", "blocked", "expired", "archived", "verification_required"].includes(
                String(data.nextHopStatus || ""),
              ) &&
              String(data.nextHopStatus || "") === String(data.expectedStatus || "") &&
              String(data.nextHopContinueIn || "") === String(data.expectedContinueIn || "") &&
              String(data.nextHopCandidateType || "") === String(data.expectedCandidateType || "") &&
              String(data.nextHopTargetKind || "") === String(data.expectedTargetKind || "") &&
              String(data.nextHopTargetId || "") === String(data.expectedTargetId || "") &&
              String(data.nextHopReviewArtifactId || "") === String(data.expectedReviewArtifactId || "") &&
              (
                !data.expectedPlanEvidenceId ||
                String(data.nextHopPlanEvidenceId || "") === String(data.expectedPlanEvidenceId || "")
              ) &&
              data.singleCardImmersive === true &&
              data.routeStripCollapsedByDefault === true &&
              data.cardOnlyMode === true &&
              data.secondaryPanelsCollapsedByDefault === true
          ),
        errorMessage: (data) =>
          "Installed-state next-hop visible truth mismatch: " + JSON.stringify(data),
      });

      await record("capture-training-next-hop-installed-screenshot", async () => {
        const captured = captureVsCodeWindowArtifacts({
          label: "training-next-hop",
          artifactsDir,
          sideBarRatio: 0.36,
          userDataDir: smokeUserDataDir,
          workspaceDir: smokeWorkspaceDir,
          vscodePid: process.env.VSCODE_PID || "",
        });
        return {
          ...captured,
          exists:
            Boolean(captured.windowScreenshotPath && fs.existsSync(captured.windowScreenshotPath)) &&
            Boolean(captured.sidebarScreenshotPath && fs.existsSync(captured.sidebarScreenshotPath)),
        };
      }, {
        ok: isWindowCaptureVerified,
        errorMessage: (data) =>
          "Installed-state next-hop screenshot capture failed: " + JSON.stringify(data),
      });

      await record("assert-resources-resource-detail-visible-truth", async () => {
        const uploadResult = await vscode.commands.executeCommand("trainer.resource.upload", {
          mode: "files",
          uploads: [
            {
              name: "vsix-resource-detail-proof.md",
              kind: "markdown",
              source: path.join(smokeWorkspaceDir, "vsix-resource-detail-proof.md"),
              tags: ["vsix-e2e", "resource-detail"],
            },
          ],
        });
        const uploadedItems =
          uploadResult && uploadResult.data && Array.isArray(uploadResult.data) ? uploadResult.data : [];
        const resourceItem = uploadedItems[0] || null;
        const resourceId =
          resourceItem && (resourceItem.id || resourceItem.resource_id || resourceItem.resourceId)
            ? resourceItem.id || resourceItem.resource_id || resourceItem.resourceId
            : null;
        if (!resourceId) {
          throw new Error("Resource detail smoke did not return a resource id.");
        }

        await vscode.commands.executeCommand("trainer.debug.restoreView", {
          activeView: "resources",
          resourceSurface: "detail",
          resourceId,
          resourceDetailId: resourceId,
          workspaceLabel: "trainer-vsix-e2e",
          resumeReason: "Show the installed resource detail truth.",
          focusArea: "resource detail",
        });
        await sleep(1500);

        const trainerExtension = vscode.extensions.getExtension(extensionId);
        const exported = trainerExtension && trainerExtension.isActive ? trainerExtension.exports : undefined;
        const state =
          exported && typeof exported.getDebugState === "function"
            ? exported.getDebugState()
            : null;
        const visible = state && state.visibleFacts ? state.visibleFacts.resources || null : null;
        const facts = visible;
        return {
          resourceId,
          hasVisibleFacts: Boolean(visible),
          surface: visible ? visible.surface || null : null,
          activeView: visible ? visible.activeView || null : null,
          activeSurface: facts ? facts.activeSurface || null : null,
          resourceDetailVisible: facts ? facts.resourceDetailVisible === true : false,
          resourceDetailId: facts ? facts.resourceDetailId || null : null,
          resourceDetailTitle: facts ? facts.resourceDetailTitle || null : null,
          selectedResourceId: facts ? facts.selectedResourceId || null : null,
          singleWorkbenchSurface: facts ? facts.singleWorkbenchSurface === true : false,
          compactMode: facts ? facts.compactMode === true : false,
          detailPaneVisible: facts ? facts.detailPaneVisible === true : false,
          sandboxPaneVisible: facts ? facts.sandboxPaneVisible === true : false,
          previewPaneVisible: facts ? facts.previewPaneVisible === true : false,
        };
      }, {
        ok: (data) =>
          Boolean(
            data &&
              data.hasVisibleFacts === true &&
              data.surface === "resources" &&
              data.activeView === "resources" &&
              data.activeSurface === "detail" &&
              data.resourceDetailVisible === true &&
              data.resourceDetailId === data.resourceId &&
              data.selectedResourceId === data.resourceId &&
              typeof data.resourceDetailTitle === "string" &&
              data.resourceDetailTitle.length > 0 &&
              data.singleWorkbenchSurface === true &&
              data.compactMode === true &&
              data.detailPaneVisible === true &&
              data.sandboxPaneVisible === false &&
              data.previewPaneVisible === false
          ),
        errorMessage: (data) =>
          "Installed-state resource detail visible truth mismatch: " + JSON.stringify(data),
      });

      await record("capture-resources-detail-installed-screenshot", async () => {
        const captured = captureVsCodeWindowArtifacts({
          label: "resources-detail",
          artifactsDir,
          sideBarRatio: 0.36,
          userDataDir: smokeUserDataDir,
          workspaceDir: smokeWorkspaceDir,
          vscodePid: process.env.VSCODE_PID || "",
        });
        return {
          ...captured,
          exists:
            Boolean(captured.windowScreenshotPath && fs.existsSync(captured.windowScreenshotPath)) &&
            Boolean(captured.sidebarScreenshotPath && fs.existsSync(captured.sidebarScreenshotPath)),
        };
      }, {
        ok: isWindowCaptureVerified,
        errorMessage: (data) =>
          "Installed-state resource detail screenshot capture failed: " + JSON.stringify(data),
      });

      const sandboxNativeOpenTruth = await record("assert-resources-sandbox-native-open-truth", async () => {
        const uploadResult = await vscode.commands.executeCommand("trainer.resource.upload", {
          mode: "files",
          uploads: [
            {
              name: "vsix-sandbox-preview-proof.md",
              kind: "markdown",
              source: path.join(smokeWorkspaceDir, "vsix-sandbox-preview-proof.md"),
              tags: ["vsix-e2e", "sandbox-preview"],
            },
          ],
        });
        const uploadedItems =
          uploadResult && uploadResult.data && Array.isArray(uploadResult.data) ? uploadResult.data : [];
        const resourceItem = uploadedItems[0] || null;
        const sandboxPath =
          resourceItem && (resourceItem.sandbox_path || resourceItem.sandboxPath)
            ? resourceItem.sandbox_path || resourceItem.sandboxPath
            : null;
        if (!sandboxPath) {
          throw new Error("Sandbox preview smoke did not return a sandbox path.");
        }

        const nativeOpenResult = await vscode.commands.executeCommand("trainer.sandbox.preview", { path: sandboxPath });
        await sleep(500);
        const nativeOpenPath = vscode.window.activeTextEditor?.document.uri.fsPath ?? null;
        const restoreResult = await vscode.commands.executeCommand("trainer.debug.restoreView", {
          workspaceId: managedContextId,
          activeView: "resources",
          resourceSurface: "sandbox",
          sandboxPath,
          previewPath: sandboxPath,
          workspaceLabel: "trainer-vsix-e2e",
          resumeReason: "Show the installed sandbox native-open state.",
          focusArea: "sandbox native open",
        });
        if (!restoreResult || restoreResult.ok !== true) {
          throw new Error("Sandbox restore command did not succeed: " + JSON.stringify(restoreResult));
        }
        const visible = await waitForVisibleFacts(
          "resources",
          (facts) =>
            Boolean(
              facts &&
                facts.surface === "resources" &&
                facts.activeView === "resources" &&
                facts.activeSurface === "sandbox" &&
                facts.selectedSandboxPath === sandboxPath &&
                facts.singleWorkbenchSurface === true &&
                facts.sandboxPaneVisible === true &&
                facts.detailPaneVisible === false &&
                facts.previewPaneVisible === false,
            ),
        );
        return {
          sandboxPath,
          nativeOpen: nativeOpenResult?.data?.nativeOpen === true,
          nativeOpenPath,
          restoreSucceeded: restoreResult.ok === true,
          hasVisibleFacts: Boolean(visible),
          activeSurface: visible ? visible.activeSurface || null : null,
          selectedSandboxPath: visible ? visible.selectedSandboxPath || null : null,
          singleWorkbenchSurface: visible ? visible.singleWorkbenchSurface === true : false,
          detailPaneVisible: visible ? visible.detailPaneVisible === true : false,
          sandboxPaneVisible: visible ? visible.sandboxPaneVisible === true : false,
          previewPaneVisible: visible ? visible.previewPaneVisible === true : false,
        };
      }, {
        ok: (data) =>
          Boolean(
            data &&
              data.nativeOpen === true &&
              pathsReferToSameFile(data.nativeOpenPath, data.sandboxPath) &&
              data.restoreSucceeded === true &&
              data.hasVisibleFacts === true &&
              data.activeSurface === "sandbox" &&
              data.selectedSandboxPath === data.sandboxPath &&
              data.singleWorkbenchSurface === true &&
              data.detailPaneVisible === false &&
              data.sandboxPaneVisible === true &&
              data.previewPaneVisible === false
          ),
        errorMessage: (data) =>
          "Installed-state sandbox native-open truth mismatch: " + JSON.stringify(data),
      });

      await record("capture-resources-sandbox-native-open-installed-screenshot", async () => {
        const captured = captureVsCodeWindowArtifacts({
          label: "resources-sandbox-native-open",
          artifactsDir,
          sideBarRatio: 0.36,
          userDataDir: smokeUserDataDir,
          workspaceDir: smokeWorkspaceDir,
          vscodePid: process.env.VSCODE_PID || "",
        });
        return {
          ...captured,
          exists:
            Boolean(captured.windowScreenshotPath && fs.existsSync(captured.windowScreenshotPath)) &&
            Boolean(captured.sidebarScreenshotPath && fs.existsSync(captured.sidebarScreenshotPath)),
        };
      }, {
        ok: isWindowCaptureVerified,
        errorMessage: (data) =>
          "Installed-state sandbox preview screenshot capture failed: " + JSON.stringify(data),
      });

      await record("assert-resources-sandbox-capability-visible-truth", async () => {
        const sandboxPath = sandboxNativeOpenTruth && sandboxNativeOpenTruth.sandboxPath;
        if (typeof sandboxPath !== "string" || !sandboxPath) {
          throw new Error("Sandbox capability check is missing the native-open sandbox path.");
        }
        const restoreResult = await vscode.commands.executeCommand("trainer.debug.restoreView", {
          workspaceId: managedContextId,
          activeView: "resources",
          resourceSurface: "sandbox",
          sandboxPath,
          previewPath: sandboxPath,
          workspaceLabel: "trainer-vsix-e2e",
          resumeReason: "Show the governed sandbox capability facts.",
          focusArea: "resource sandbox",
        });
        if (!restoreResult || restoreResult.ok !== true) {
          throw new Error("Sandbox capability restore command did not succeed: " + JSON.stringify(restoreResult));
        }
        const visible = await waitForVisibleFacts(
          "resources",
          (facts) =>
            Boolean(
              facts &&
                facts.surface === "resources" &&
                facts.activeView === "resources" &&
                facts.activeSurface === "sandbox" &&
                facts.selectedSandboxPath === sandboxPath &&
                facts.singleWorkbenchSurface === true &&
                facts.sandboxPaneVisible === true &&
                facts.detailPaneVisible === false &&
                facts.previewPaneVisible === false,
            ),
        );
        const facts = visible;
        return {
          sandboxPath,
          restoreSucceeded: restoreResult.ok === true,
          hasVisibleFacts: Boolean(visible),
          surface: visible ? visible.surface || null : null,
          activeView: visible ? visible.activeView || null : null,
          activeSurface: facts ? facts.activeSurface || null : null,
          selectedSandboxPath: facts ? facts.selectedSandboxPath || null : null,
          singleWorkbenchSurface: facts ? facts.singleWorkbenchSurface === true : false,
          compactMode: facts ? facts.compactMode === true : false,
          modebarHiddenInCompact: facts ? facts.modebarHiddenInCompact === true : false,
          detailPaneVisible: facts ? facts.detailPaneVisible === true : false,
          sandboxPaneVisible: facts ? facts.sandboxPaneVisible === true : false,
          previewPaneVisible: facts ? facts.previewPaneVisible === true : false,
        };
      }, {
        ok: (data) =>
          Boolean(
            data &&
              data.restoreSucceeded === true &&
              data.hasVisibleFacts === true &&
              data.surface === "resources" &&
              data.activeView === "resources" &&
              data.activeSurface === "sandbox" &&
              typeof data.selectedSandboxPath === "string" &&
              data.selectedSandboxPath === data.sandboxPath &&
              data.singleWorkbenchSurface === true &&
              data.detailPaneVisible === false &&
              data.sandboxPaneVisible === true &&
              data.previewPaneVisible === false
          ),
        errorMessage: (data) =>
          "Installed-state resources sandbox capability visible truth mismatch: " + JSON.stringify(data),
      });

      await record("capture-resources-sandbox-installed-screenshot", async () => {
        const captured = captureVsCodeWindowArtifacts({
          label: "resources-sandbox-capability",
          artifactsDir,
          sideBarRatio: 0.36,
          userDataDir: smokeUserDataDir,
          workspaceDir: smokeWorkspaceDir,
          vscodePid: process.env.VSCODE_PID || "",
        });
        return {
          ...captured,
          exists:
            Boolean(captured.windowScreenshotPath && fs.existsSync(captured.windowScreenshotPath)) &&
            Boolean(captured.sidebarScreenshotPath && fs.existsSync(captured.sidebarScreenshotPath)),
        };
      }, {
        ok: isWindowCaptureVerified,
        errorMessage: (data) =>
          "Installed-state resources screenshot capture failed: " + JSON.stringify(data),
      });

      await record("assert-top-title-and-theme-typography-truth", async () => {
        const trainerExtension = vscode.extensions.getExtension(extensionId);
        const extensionPackage =
          trainerExtension && trainerExtension.packageJSON ? trainerExtension.packageJSON : null;
        const contributes =
          extensionPackage && extensionPackage.contributes ? extensionPackage.contributes : {};
        const viewsContainers =
          contributes && contributes.viewsContainers ? contributes.viewsContainers : {};
        const activitybarViews = Array.isArray(viewsContainers.activitybar)
          ? viewsContainers.activitybar
          : [];
        const trainerContainer =
          activitybarViews.find((item) => item && item.id === "trainer") || null;
        const views = contributes && contributes.views ? contributes.views : {};
        const trainerViews = Array.isArray(views.trainer) ? views.trainer : [];
        const trainerSidebarView =
          trainerViews.find((item) => item && item.id === "trainer.sidebar") || null;
        const openCommand = Array.isArray(contributes.commands)
          ? contributes.commands.find(
              (item) => item && item.command === "trainer.openWorkbench",
            ) || null
          : null;

        const originalTheme = vscode.workspace
          .getConfiguration("workbench")
          .get("colorTheme");

        const themeScenarios = [
          {
            id: "dark",
            expectedKind: "dark",
            candidates: ["Default Dark Modern", "Default Dark+", "Dark+ (default dark)"],
          },
          {
            id: "light",
            expectedKind: "light",
            candidates: ["Default Light Modern", "Default Light+", "Light+ (default light)"],
          },
          {
            id: "high-contrast",
            expectedKind: "high-contrast",
            candidates: [
              "Default High Contrast",
              "Default High Contrast Light",
              "High Contrast",
              "High Contrast Light",
            ],
          },
        ];

        const themeRuns = [];
        for (const scenario of themeScenarios) {
          const applied = await applyThemeScenario(scenario);
          await sleep(400);
          const captured = captureVsCodeWindowArtifacts({
            label: "header-font-" + scenario.id,
            artifactsDir,
            sideBarRatio: 0.36,
            userDataDir: smokeUserDataDir,
            workspaceDir: smokeWorkspaceDir,
            vscodePid: process.env.VSCODE_PID || "",
          });
          themeRuns.push({
            ...applied,
            screenshot: {
              skipped: captured.skipped === true,
              captureRequired: captured.captureRequired !== false,
              capturePlatform: captured.capturePlatform || process.platform,
              reason: captured.reason || null,
              windowScreenshotPath: captured.windowScreenshotPath || null,
              sidebarScreenshotPath: captured.sidebarScreenshotPath || null,
              exists: Boolean(
                captured.windowScreenshotPath &&
                  fs.existsSync(captured.windowScreenshotPath) &&
                  captured.sidebarScreenshotPath &&
                  fs.existsSync(captured.sidebarScreenshotPath),
              ),
              windowTitle: captured.windowTitle || null,
              captureMethod: captured.captureMethod || null,
            },
          });
        }

        if (typeof originalTheme === "string" && originalTheme.trim().length > 0) {
          try {
            await vscode.workspace
              .getConfiguration("workbench")
              .update(
                "colorTheme",
                originalTheme,
                vscode.ConfigurationTarget.Global,
              );
          } catch {
            // Ignore restore failure in ephemeral smoke profile.
          }
        }

        const runtimeTitleEvidence = readInstalledRuntimeViewTitleEvidence(extensionId);

        return {
          containerId: trainerContainer ? trainerContainer.id || null : null,
          containerTitle: trainerContainer ? trainerContainer.title || null : null,
          viewId: trainerSidebarView ? trainerSidebarView.id || null : null,
          viewName: trainerSidebarView ? trainerSidebarView.name || null : null,
          contextualTitle:
            trainerSidebarView && typeof trainerSidebarView.contextualTitle === "string"
              ? trainerSidebarView.contextualTitle
              : null,
          openCommandTitle: openCommand ? openCommand.title || null : null,
          runtimeWebviewTitle: runtimeTitleEvidence.title,
          runtimeTitleAssignmentFound: runtimeTitleEvidence.titleAssignmentFound,
          runtimeTitleSourcePath: runtimeTitleEvidence.sourcePath,
          themeRuns,
        };
      }, {
        ok: (data) =>
          Boolean(
            data &&
              data.containerId === "trainer" &&
              typeof data.containerTitle === "string" &&
              data.containerTitle.toLowerCase() === "trainer" &&
              data.viewId === "trainer.sidebar" &&
              typeof data.viewName === "string" &&
              data.viewName.toLowerCase() === "trainer" &&
              (data.contextualTitle === null || data.contextualTitle.toLowerCase() === "trainer") &&
              typeof data.openCommandTitle === "string" &&
              /open.*sidebar/i.test(data.openCommandTitle) &&
              data.runtimeTitleAssignmentFound === true &&
              typeof data.runtimeWebviewTitle === "string" &&
              data.runtimeWebviewTitle.toLowerCase() === "trainer" &&
              Array.isArray(data.themeRuns) &&
              data.themeRuns.length === 3 &&
              data.themeRuns.every(
                (run) =>
                  run &&
                  run.applied === true &&
                  run.kindMatch === true &&
                  run.screenshot &&
                  isWindowCaptureVerified(run.screenshot),
              )
          ),
        errorMessage: (data) =>
          "Installed-state title/theme typography regression mismatch: " + JSON.stringify(data),
      });

      await record("assert-cross-workspace-reopen-history-truth", async () => {
        const port = currentSidecarPort();

        const oldWorkspaceId = "trainer-vsix-reopen-old";
        const newWorkspaceId = "trainer-vsix-reopen-new";
        const oldWorkspaceName = "trainer-vsix-reopen-old";
        const newWorkspaceName = "trainer-vsix-reopen-new";
        const newResourceName = "VSIX Reopen Resource";

        const oldStart = await postProviderBoundJson(port, "/session/start", {
          workspace_context: {
            workspace_id: oldWorkspaceId,
            name: oldWorkspaceName,
            workspace_path: oldWorkspaceId,
          },
          user_profile: {
            long_term_goal: "Old workspace state must never leak into installed-state reopen truth",
            weekly_hours: 4,
            teaching_style: "guided",
            allow_direct_answers: false,
            focus_libraries: ["FastAPI"],
          },
          initial_message: "Old workspace state must disappear after the installed extension reopen handoff.",
        });
        const oldSessionId = oldStart && (oldStart.session_id || oldStart.sessionId);
        if (!oldSessionId) {
          throw new Error("Installed-state reopen smoke did not return an old session id.");
        }

        await postProviderBoundJson(port, "/session/message", {
          session_id: oldSessionId,
          workspace_id: oldWorkspaceId,
          message:
            "OLD-WORKSPACE-MARKER keep this thread out of the installed-state rebound truth. 先别进训练，也别改计划。",
          response_language: "zh-CN",
          provider: providerTransportConfig(),
          api_key: providerApiKey,
        });

        const newStart = await postProviderBoundJson(port, "/session/start", {
          workspace_id: newWorkspaceId,
          workspace_name: newWorkspaceName,
          profile: {
            long_term_goal: "Installed VSIX reopen truth must drive every restored view",
            weekly_hours: 5,
            teaching_style: "guided",
            answer_policy: "guided",
            preferred_libraries: ["FastAPI"],
          },
        });
        const newSessionId = newStart && (newStart.session_id || newStart.sessionId);
        if (!newSessionId) {
          throw new Error("Installed-state reopen smoke did not return a new session id.");
        }

        await postJson(port, "/memory/settings", {
          session_id: newSessionId,
          workspace_id: newWorkspaceId,
          response_language: "zh-CN",
          answer_mode: "guided",
          provider: providerSettingsConfig(),
          api_key: providerApiKey,
        });

        await postProviderBoundJson(port, "/session/message", {
          session_id: newSessionId,
          workspace_id: newWorkspaceId,
          message:
            "NEW-WORKSPACE-MARKER 先别进训练，也别改计划，直接用对话告诉我当前最小可验证动作，并说明你正在做什么。",
          response_language: "zh-CN",
          provider: providerTransportConfig(),
          api_key: providerApiKey,
        });

        await postProviderBoundJson(port, "/plan/generate", {
          session_id: newSessionId,
          workspace_id: newWorkspaceId,
          profile: {
            long_term_goal: "Installed VSIX reopen truth must drive every restored view",
            long_term_goals: ["Installed VSIX reopen truth must drive every restored view"],
            weekly_hours: 5,
            teaching_style: "guided",
            answer_policy: "guided",
            target_project: newWorkspaceName,
            preferred_libraries: ["FastAPI"],
          },
          goals: ["Installed VSIX reopen truth must drive every restored view"],
          constraints: [],
          resource_ids: [],
        });

        await postProviderBoundJson(port, "/task/next", {
          session_id: newSessionId,
          workspace_id: newWorkspaceId,
          focus_area: "Installed-state cross-workspace reopen proof",
          response_language: "en-US",
        });

        const routedCard = await postJson(port, "/training/generate-card", {
          workspace_id: newWorkspaceId,
          source: "practice_feedback",
          card_type: "practice",
          focus_area: "Installed-state cross-workspace reopen proof",
          target_skill: "Keep the new workspace state isolated and verifiable.",
          context_hint: "Generate a small practice card for the reopened workspace.",
          response_language: "en-US",
        });
        if (!routedCard || !routedCard.card) {
          throw new Error("Installed-state reopen smoke did not route a training card.");
        }
        const routedCardId = routedCard.card.card_id || routedCard.card.cardId || null;
        if (!routedCardId) {
          throw new Error("Installed-state reopen smoke did not return the routed card id.");
        }

        const upload = await postJson(port, "/resource/upload", {
          workspace_id: newWorkspaceId,
          kind: "markdown",
          name: newResourceName,
          source: "vsix-reopen-resource.md",
          content: "# VSIX Reopen Resource\nKeep the installed extension authoritative.\n",
          source_type: "file",
          tags: ["vsix-e2e", "reopen", "audit"],
        });
        const resourceId = upload && (upload.id || upload.resource_id || upload.resourceId);
        if (!resourceId) {
          throw new Error("Installed-state reopen smoke did not return a resource id.");
        }

        await postJson(port, "/resource/index", {
          workspace_id: newWorkspaceId,
          resource_id: resourceId,
        });

        const reboundSummary = await getJson(
          port,
          "/memory/summary?session_id=" +
            encodeURIComponent(newSessionId) +
            "&workspace_id=" +
            encodeURIComponent(newWorkspaceId),
        );
        const reboundHistory = await getJson(
          port,
          "/session/history?session_id=" +
            encodeURIComponent(newSessionId) +
            "&workspace_id=" +
            encodeURIComponent(newWorkspaceId),
        );
        const summaryWorkspaceId =
          reboundSummary &&
          reboundSummary.memory &&
          reboundSummary.memory.workspace &&
          (
            reboundSummary.memory.workspace.workspace_id ||
            reboundSummary.memory.workspace.workspaceId
          );
        const trainingRouteCardId =
          reboundSummary &&
          reboundSummary.memory &&
          reboundSummary.memory.active_training_card_routing &&
          (
            reboundSummary.memory.active_training_card_routing.selected_card_id ||
            reboundSummary.memory.active_training_card_routing.selectedCardId
          );
        const planId = reboundSummary && reboundSummary.plan ? reboundSummary.plan.id || null : null;
        const currentStageTitle =
          reboundSummary &&
          reboundSummary.plan_runtime_status &&
          reboundSummary.plan_runtime_status.current_stage
            ? reboundSummary.plan_runtime_status.current_stage.title || null
            : null;
        const summaryResources =
          reboundSummary &&
          reboundSummary.memory &&
          Array.isArray(reboundSummary.memory.resources)
            ? reboundSummary.memory.resources
            : [];
        const resourceDetail =
          summaryResources.find(
            (item) =>
              item &&
              String(item.id || item.resource_id || item.resourceId || "") === String(resourceId),
          ) || null;
        const resourceNames = summaryResources.map((item) => item && item.name).filter(Boolean);
        const assistantMessages =
          reboundSummary && Array.isArray(reboundSummary.messages)
            ? reboundSummary.messages
                .filter((item) => item && item.role === "assistant")
                .map((item) => item.content || "")
            : [];
        const userMessages =
          reboundSummary && Array.isArray(reboundSummary.messages)
            ? reboundSummary.messages
                .filter((item) => item && item.role === "user")
                .map((item) => item.content || "")
            : [];
        const historySummaries = Array.isArray(reboundHistory)
          ? reboundHistory.map((item) => String((item && item.summary) || ""))
          : [];

        return {
          oldSessionId,
          newSessionId,
          workspaceId: summaryWorkspaceId,
          planId,
          currentStageTitle,
          routedCardId,
          trainingRouteCardId,
          resourceNames,
          userHasNewWorkspaceMarker: userMessages.some((item) => String(item).includes("NEW-WORKSPACE-MARKER")),
          userLeaksOldWorkspaceMarker: userMessages.some((item) => String(item).includes("OLD-WORKSPACE-MARKER")),
          assistantMessageCount: assistantMessages.length,
          assistantHasVisibleReply: assistantMessages.some((item) => String(item).trim().length > 0),
          historyHasNewWorkspaceMarker: historySummaries.some((item) => String(item).includes("NEW-WORKSPACE-MARKER")),
          historyLeaksOldWorkspaceMarker: historySummaries.some((item) => String(item).includes("OLD-WORKSPACE-MARKER")),
          resourceDetailName: resourceDetail && resourceDetail.name ? resourceDetail.name : null,
          resourceDetailSummary: resourceDetail && resourceDetail.summary ? resourceDetail.summary : null,
        };
      }, {
        ok: (data) =>
          Boolean(
            data &&
              data.workspaceId === "trainer-vsix-reopen-new" &&
              typeof data.planId === "string" &&
              data.planId.length > 0 &&
              typeof data.currentStageTitle === "string" &&
              data.currentStageTitle.length > 0 &&
              data.trainingRouteCardId === data.routedCardId &&
              Array.isArray(data.resourceNames) &&
              data.resourceNames.includes("VSIX Reopen Resource") &&
              data.userHasNewWorkspaceMarker === true &&
              data.userLeaksOldWorkspaceMarker === false &&
              data.assistantMessageCount >= 1 &&
              data.assistantHasVisibleReply === true &&
              data.historyHasNewWorkspaceMarker === true &&
              data.historyLeaksOldWorkspaceMarker === false &&
              data.resourceDetailName === "VSIX Reopen Resource" &&
              /installed extension authoritative/i.test(String(data.resourceDetailSummary || "")),
          ),
        errorMessage: (data) =>
          "Installed-state cross-workspace reopen truth mismatch. Expected the rebound summary/history/resource surfaces to keep only the new workspace and its real-provider conversation history: " +
          JSON.stringify(data),
      });
    }

    finalReport = {
      ok: steps.every((step) => step.ok),
      extensionId,
      trainerExtension,
      durationMs: Date.now() - startedAt,
      steps,
    };
  } catch (error) {
    finalReport = {
      ok: false,
      extensionId,
      durationMs: Date.now() - startedAt,
      steps,
      error: error && error.stack ? error.stack : String(error),
    };
  }

  if (reportPath) {
    fs.writeFileSync(reportPath, JSON.stringify(finalReport, null, 2) + "\n", "utf8");
  }

  setTimeout(() => {
    vscode.commands.executeCommand("workbench.action.closeWindow");
  }, 500);
}

function deactivate() {}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function sleepSync(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

function sameLocalPath(left, right) {
  if (typeof left !== "string" || typeof right !== "string" || !left || !right) {
    return false;
  }
  const normalize = (value) => path.resolve(value).replace(/[\\/]+$/, "");
  const normalizedLeft = normalize(left);
  const normalizedRight = normalize(right);
  return process.platform === "win32"
    ? normalizedLeft.toLocaleLowerCase("en-US") === normalizedRight.toLocaleLowerCase("en-US")
    : normalizedLeft === normalizedRight;
}

function sanitize(value) {
  const seen = new WeakSet();
  return JSON.parse(JSON.stringify(value, (key, nested) => {
    if (/api[_-]?key|authorization|token|secret|password/i.test(key)) {
      return "[redacted]";
    }
    if (typeof nested === "object" && nested !== null) {
      if (seen.has(nested)) {
        return "[circular]";
      }
      seen.add(nested);
    }
    return nested;
  }));
}

function isWindowCaptureVerified(data) {
  if (!data || typeof data !== "object") {
    return false;
  }
  if (data.skipped === true) {
    return (
      data.captureRequired === false &&
      typeof data.capturePlatform === "string" &&
      data.capturePlatform !== "win32" &&
      typeof data.reason === "string" &&
      data.reason.trim().length > 0
    );
  }
  return Boolean(
    data.exists === true && data.windowScreenshotPath && data.sidebarScreenshotPath,
  );
}

function captureVsCodeWindowArtifacts({ label, artifactsDir, sideBarRatio, userDataDir, workspaceDir, vscodePid }) {
  if (process.platform !== "win32") {
    return {
      skipped: true,
      captureRequired: false,
      capturePlatform: process.platform,
      reason: "Window capture is only implemented for win32 in this smoke driver, current platform=" + process.platform + ".",
      windowScreenshotPath: null,
      sidebarScreenshotPath: null,
    };
  }
  if (!artifactsDir) {
    return {
      skipped: false,
      captureRequired: true,
      capturePlatform: process.platform,
      reason: "No artifacts directory was provided.",
      windowScreenshotPath: null,
      sidebarScreenshotPath: null,
    };
  }

  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const windowScreenshotPath = path.join(artifactsDir, "vsix-" + label + "-window-" + stamp + ".png");
  const sidebarScreenshotPath = path.join(artifactsDir, "vsix-" + label + "-sidebar-" + stamp + ".png");
  const scriptPath = path.join(os.tmpdir(), "trainer-vsix-capture-" + stamp + ".ps1");
  const sideBarPercent = Math.max(0.2, Math.min(0.6, Number(sideBarRatio) || 0.36));
  const captureRetries = Math.max(
    1,
    Math.min(6, Number.parseInt(process.env.TRAINER_E2E_CAPTURE_RETRIES ?? "4", 10) || 4),
  );
  const captureRetryDelayMs = Math.max(
    150,
    Math.min(
      5000,
      Number.parseInt(process.env.TRAINER_E2E_CAPTURE_RETRY_DELAY_MS ?? "600", 10) || 600,
    ),
  );

  const script = [
    "Add-Type -AssemblyName System.Drawing",
    "Add-Type -TypeDefinition @'",
    "using System;",
    "using System.Runtime.InteropServices;",
    "public static class TrainerCaptureNative {",
    "  [DllImport(\"user32.dll\")] public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);",
    "  public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);",
    "  [DllImport(\"user32.dll\")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);",
    "  [DllImport(\"user32.dll\")] [return: MarshalAs(UnmanagedType.Bool)] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);",
    "  [DllImport(\"user32.dll\")] [return: MarshalAs(UnmanagedType.Bool)] public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdcBlt, uint nFlags);",
    "  [DllImport(\"user32.dll\")] [return: MarshalAs(UnmanagedType.Bool)] public static extern bool IsWindowVisible(IntPtr hWnd);",
    "  [DllImport(\"user32.dll\", CharSet = CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, System.Text.StringBuilder text, int maxCount);",
    "  [DllImport(\"user32.dll\")] [return: MarshalAs(UnmanagedType.Bool)] public static extern bool SetForegroundWindow(IntPtr hWnd);",
    "  [DllImport(\"user32.dll\")] [return: MarshalAs(UnmanagedType.Bool)] public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);",
    "  [DllImport(\"user32.dll\")] [return: MarshalAs(UnmanagedType.Bool)] public static extern bool IsIconic(IntPtr hWnd);",
    "  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }",
    "}",
    "'@",
    "$windowPath = '" + escapePowerShellLiteral(windowScreenshotPath) + "'",
    "$sidebarPath = '" + escapePowerShellLiteral(sidebarScreenshotPath) + "'",
    "$sideBarPercent = " + String(sideBarPercent),
    "$userDataDir = '" + escapePowerShellLiteral(userDataDir || "") + "'",
    "$workspaceDir = '" + escapePowerShellLiteral(workspaceDir || "") + "'",
    "$preferredPid = 0",
    "if ('" + escapePowerShellLiteral(vscodePid || "") + "') {",
    "  try { $preferredPid = [int]('" + escapePowerShellLiteral(vscodePid || "") + "') } catch { $preferredPid = 0 }",
    "}",
    "function Get-WindowTitle([IntPtr]$Handle) {",
    "  $builder = New-Object System.Text.StringBuilder 512",
    "  [void][TrainerCaptureNative]::GetWindowText($Handle, $builder, $builder.Capacity)",
    "  return $builder.ToString()",
    "}",
    "function Get-WindowCandidatesForPid([int]$TargetProcessId) {",
    "  $results = New-Object System.Collections.Generic.List[object]",
    "  if ($TargetProcessId -le 0) { return $results }",
    "  $callback = [TrainerCaptureNative+EnumWindowsProc]{",
    "    param($Handle, $Ignored)",
    "    $windowPid = 0",
    "    [void][TrainerCaptureNative]::GetWindowThreadProcessId($Handle, [ref]$windowPid)",
    "    if ($windowPid -ne $TargetProcessId) { return $true }",
    "    if (-not [TrainerCaptureNative]::IsWindowVisible($Handle)) { return $true }",
    "    $candidateRect = New-Object TrainerCaptureNative+RECT",
    "    [void][TrainerCaptureNative]::GetWindowRect($Handle, [ref]$candidateRect)",
    "    $candidateWidth = [Math]::Max(0, $candidateRect.Right - $candidateRect.Left)",
    "    $candidateHeight = [Math]::Max(0, $candidateRect.Bottom - $candidateRect.Top)",
    "    if ($candidateWidth -lt 300 -or $candidateHeight -lt 200) { return $true }",
    "    $results.Add([pscustomobject]@{",
    "      Handle = $Handle;",
    "      ProcessId = $TargetProcessId;",
    "      Title = Get-WindowTitle $Handle;",
    "      Left = $candidateRect.Left;",
    "      Top = $candidateRect.Top;",
    "      Width = $candidateWidth;",
    "      Height = $candidateHeight;",
    "      Area = $candidateWidth * $candidateHeight",
    "    }) | Out-Null",
    "    return $true",
    "  }",
    "  [void][TrainerCaptureNative]::EnumWindows($callback, [IntPtr]::Zero)",
    "  return $results",
    "}",
    "$candidatePids = New-Object System.Collections.Generic.List[int]",
    "if ($preferredPid -gt 0) { $candidatePids.Add($preferredPid) | Out-Null }",
    "$processMatches = @()",
    "try {",
    "  $processMatches = Get-CimInstance Win32_Process | Where-Object {",
    "    $_.Name -match '^Code( - Insiders)?\\.exe$' -and",
    "    (",
    "      ($userDataDir -and $_.CommandLine -and $_.CommandLine.IndexOf($userDataDir, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) -or",
    "      ($workspaceDir -and $_.CommandLine -and $_.CommandLine.IndexOf($workspaceDir, [System.StringComparison]::OrdinalIgnoreCase) -ge 0)",
    "    )",
    "  } | Sort-Object CreationDate -Descending",
    "} catch {",
    "  $processMatches = @()",
    "}",
    "foreach ($processMatch in $processMatches) {",
    "  if ($processMatch.ProcessId -and -not $candidatePids.Contains([int]$processMatch.ProcessId)) {",
    "    $candidatePids.Add([int]$processMatch.ProcessId) | Out-Null",
    "  }",
    "}",
    "$windowCandidates = New-Object System.Collections.Generic.List[object]",
    "for ($captureAttempt = 1; $captureAttempt -le 5 -and $windowCandidates.Count -eq 0; $captureAttempt++) {",
    "  $windowCandidates = New-Object System.Collections.Generic.List[object]",
    "  foreach ($candidatePid in $candidatePids) {",
    "    foreach ($candidate in (Get-WindowCandidatesForPid $candidatePid)) {",
    "      $windowCandidates.Add($candidate) | Out-Null",
    "    }",
    "  }",
    "  if ($windowCandidates.Count -eq 0 -and $captureAttempt -lt 5) {",
    "    Start-Sleep -Milliseconds 250",
    "  }",
    "}",
    "if ($windowCandidates.Count -eq 0) {",
    "  throw ('No VS Code window matched user-data-dir/workspace hints. preferredPid=' + $preferredPid + '; candidatePids=' + (($candidatePids | ForEach-Object { $_ }) -join ',') + '; userDataDir=' + $userDataDir + '; workspaceDir=' + $workspaceDir)",
    "}",
    "$target = $windowCandidates | Sort-Object Area -Descending | Select-Object -First 1",
    "$handle = $target.Handle",
    "if ($handle -eq [IntPtr]::Zero) { throw 'Resolved VS Code window handle was zero.' }",
    "if ([TrainerCaptureNative]::IsIconic($handle)) { [void][TrainerCaptureNative]::ShowWindowAsync($handle, 9) }",
    "[void][TrainerCaptureNative]::ShowWindowAsync($handle, 5)",
    "[void][TrainerCaptureNative]::SetForegroundWindow($handle)",
    "Start-Sleep -Milliseconds 450",
    "$rect = New-Object TrainerCaptureNative+RECT",
    "[void][TrainerCaptureNative]::GetWindowRect($handle, [ref]$rect)",
    "$width = [Math]::Max(1, $rect.Right - $rect.Left)",
    "$height = [Math]::Max(1, $rect.Bottom - $rect.Top)",
    "$bitmap = New-Object System.Drawing.Bitmap $width, $height",
    "$graphics = [System.Drawing.Graphics]::FromImage($bitmap)",
    "$hdc = $graphics.GetHdc()",
    "$printSucceeded = $false",
    "try {",
    "  $printSucceeded = [TrainerCaptureNative]::PrintWindow($handle, $hdc, 2)",
    "} finally {",
    "  $graphics.ReleaseHdc($hdc)",
    "}",
    "if (-not $printSucceeded) {",
    "  $graphics.CopyFromScreen($rect.Left, $rect.Top, 0, 0, $bitmap.Size)",
    "}",
    "$bitmap.Save($windowPath, [System.Drawing.Imaging.ImageFormat]::Png)",
    "$sidebarWidth = [Math]::Max(1, [int]([Math]::Round($width * $sideBarPercent)))",
    "$sidebarBitmap = $bitmap.Clone((New-Object System.Drawing.Rectangle 0, 0, $sidebarWidth, $height), $bitmap.PixelFormat)",
    "$sidebarBitmap.Save($sidebarPath, [System.Drawing.Imaging.ImageFormat]::Png)",
    "$graphics.Dispose()",
    "$bitmap.Dispose()",
    "$sidebarBitmap.Dispose()",
    "$captureMethod = if ($printSucceeded) { 'printwindow' } else { 'copyfromscreen' }",
    "Write-Output (@{ windowScreenshotPath=$windowPath; sidebarScreenshotPath=$sidebarPath; width=$width; height=$height; sidebarWidth=$sidebarWidth; windowTitle=$target.Title; windowProcessId=$target.ProcessId; captureLeft=$rect.Left; captureTop=$rect.Top; captureMethod=$captureMethod } | ConvertTo-Json -Compress)",
  ].join("\n");

  fs.writeFileSync(scriptPath, script, "utf8");
  try {
    let lastError = null;
    for (let attempt = 1; attempt <= captureRetries; attempt += 1) {
      try {
        const output = execFileSync(
          "powershell.exe",
          ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", scriptPath],
          { encoding: "utf8", timeout: 15000 },
        ).trim();
        return output ? JSON.parse(output) : { windowScreenshotPath, sidebarScreenshotPath };
      } catch (error) {
        lastError = error;
        if (attempt < captureRetries && isRetryableWindowCaptureError(error)) {
          sleepSync(captureRetryDelayMs);
          continue;
        }
        throw error;
      }
    }

    throw lastError ?? new Error("VS Code window capture failed without a concrete error.");
  } finally {
    fs.rmSync(scriptPath, { force: true });
  }
}

function escapePowerShellLiteral(value) {
  return String(value).replace(/'/g, "''");
}

function isRetryableWindowCaptureError(error) {
  const text =
    error && typeof error === "object" && "message" in error ? String(error.message) : String(error);
  return /No VS Code window matched user-data-dir\/workspace hints|Resolved VS Code window handle was zero/i.test(
    text,
  );
}

function readSandboxCapabilitySummary(state) {
  if (!state || typeof state !== "object") {
    return null;
  }
  return state.capability_summary || state.capabilitySummary || null;
}

function readSandboxField(record, snakeKey, camelKey) {
  if (!record || typeof record !== "object") {
    return null;
  }
  return record[snakeKey] ?? record[camelKey] ?? null;
}

function pathsReferToSameFile(left, right) {
  if (typeof left !== "string" || typeof right !== "string" || !left || !right) {
    return false;
  }
  const normalize = (value) => path.resolve(value).replace(/\\/g, "/");
  const normalizedLeft = normalize(left);
  const normalizedRight = normalize(right);
  return process.platform === "win32"
    ? normalizedLeft.toLowerCase() === normalizedRight.toLowerCase()
    : normalizedLeft === normalizedRight;
}

function installedStateNetworkReasonCodes() {
  return [
    "network_egress_enforcement_missing",
    "network_egress_os_container_runtime_missing",
    "network_egress_os_container_daemon_unreachable",
    "network_egress_os_container_image_missing",
    "network_egress_os_container_image_untrusted",
    "network_egress_os_container_executor_not_implemented",
    "network_egress_os_container_probe_failed",
  ];
}

function normalizeThemeKind(kind) {
  if (kind === vscode.ColorThemeKind.Dark) {
    return "dark";
  }
  if (kind === vscode.ColorThemeKind.Light) {
    return "light";
  }
  if (
    kind === vscode.ColorThemeKind.HighContrast ||
    kind === vscode.ColorThemeKind.HighContrastLight
  ) {
    return "high-contrast";
  }
  return "unknown";
}

function readInstalledRuntimeViewTitleEvidence(installedExtensionId) {
  const extension = vscode.extensions.getExtension(installedExtensionId);
  const extensionPath =
    extension && extension.extensionPath ? extension.extensionPath : null;
  if (!extensionPath) {
    return {
      title: null,
      titleAssignmentFound: false,
      sourcePath: null,
    };
  }
  const sourcePath = path.join(
    extensionPath,
    "dist",
    "extension",
    "src",
    "core",
    "webviewBridge.js",
  );
  if (!fs.existsSync(sourcePath)) {
    return {
      title: null,
      titleAssignmentFound: false,
      sourcePath,
    };
  }
  const source = fs.readFileSync(sourcePath, "utf8");
  const assignmentMatch = source.match(/webviewView\.title\s*=\s*['"]([^'"]+)['"]/);
  return {
    title: assignmentMatch ? assignmentMatch[1] : null,
    titleAssignmentFound: Boolean(assignmentMatch),
    sourcePath,
  };
}

async function applyThemeScenario(scenario) {
  const workbenchConfig = vscode.workspace.getConfiguration("workbench");
  const tried = [];
  let selectedTheme = String(workbenchConfig.get("colorTheme") || "");
  let applied = false;

  for (const candidate of scenario.candidates) {
    tried.push(candidate);
    try {
      await workbenchConfig.update(
        "colorTheme",
        candidate,
        vscode.ConfigurationTarget.Global,
      );
      await sleep(420);
      selectedTheme = String(
        vscode.workspace.getConfiguration("workbench").get("colorTheme") || candidate,
      );
      const activeKind = normalizeThemeKind(vscode.window.activeColorTheme.kind);
      if (activeKind === scenario.expectedKind) {
        applied = true;
        return {
          id: scenario.id,
          expectedKind: scenario.expectedKind,
          activeKind,
          kindMatch: true,
          selectedTheme,
          applied,
          tried,
        };
      }
    } catch (error) {
      selectedTheme = String(
        vscode.workspace.getConfiguration("workbench").get("colorTheme") || candidate,
      );
    }
  }

  const activeKind = normalizeThemeKind(vscode.window.activeColorTheme.kind);
  return {
    id: scenario.id,
    expectedKind: scenario.expectedKind,
    activeKind,
    kindMatch: activeKind === scenario.expectedKind,
    selectedTheme,
    applied,
    tried,
  };
}

function getJson(port, requestPath, timeoutMs = 15000) {
  return new Promise((resolve, reject) => {
    const request = http.request(
      {
        method: "GET",
        host: "127.0.0.1",
        port,
        path: requestPath,
        timeout: timeoutMs,
      },
      (response) => {
        const chunks = [];
        response.on("data", (chunk) => chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)));
        response.on("end", () => {
          const text = Buffer.concat(chunks).toString("utf8");
          if ((response.statusCode || 500) >= 400) {
            reject(new Error("GET " + requestPath + " failed (" + response.statusCode + "): " + text));
            return;
          }
          try {
            resolve(text.trim() ? JSON.parse(text) : {});
          } catch (error) {
            reject(new Error("Invalid JSON from " + requestPath + ": " + error.message));
          }
        });
      },
    );
    request.on("timeout", () => request.destroy(new Error("GET " + requestPath + " timed out")));
    request.on("error", reject);
    request.end();
  });
}

function postJson(port, requestPath, body, timeoutMs = 15000) {
  return new Promise((resolve, reject) => {
    const payload = Buffer.from(JSON.stringify(body || {}), "utf8");
    const request = http.request(
      {
        method: "POST",
        host: "127.0.0.1",
        port,
        path: requestPath,
        timeout: timeoutMs,
        headers: {
          "content-type": "application/json",
          "content-length": payload.length,
        },
      },
      (response) => {
        const chunks = [];
        response.on("data", (chunk) => chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)));
        response.on("end", () => {
          const text = Buffer.concat(chunks).toString("utf8");
          if ((response.statusCode || 500) >= 400) {
            reject(new Error("POST " + requestPath + " failed (" + response.statusCode + "): " + text));
            return;
          }
          try {
            resolve(text.trim() ? JSON.parse(text) : {});
          } catch (error) {
            reject(new Error("Invalid JSON from " + requestPath + ": " + error.message));
          }
        });
      },
    );
    request.on("timeout", () => request.destroy(new Error("POST " + requestPath + " timed out")));
    request.on("error", reject);
    request.write(payload);
    request.end();
  });
}

module.exports = { activate, deactivate };
`,
    "utf8",
  );
}

function runCode(args, options = {}) {
  const result =
    process.platform === "win32" && codeCli.toLowerCase().endsWith(".cmd")
      ? spawnSync(process.env.ComSpec ?? "cmd.exe", ["/d", "/c", buildWindowsCmd(codeCli, args)], {
          cwd: extensionDir,
          encoding: "utf8",
          env: options.env ?? process.env,
          timeout: options.timeout,
          windowsVerbatimArguments: true,
        })
      : spawnSync(codeCli, args, {
          cwd: extensionDir,
          encoding: "utf8",
          env: options.env ?? process.env,
          timeout: options.timeout,
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

function runSmokeDriverWithRetry(args, options, expectedReportPath, currentUserDataDir) {
  const retries = Math.max(
    1,
    Number.parseInt(process.env.TRAINER_E2E_LAUNCH_RETRIES ?? "4", 10),
  );
  const delayMs = Math.max(
    1000,
    Number.parseInt(process.env.TRAINER_E2E_LAUNCH_RETRY_DELAY_MS ?? "15000", 10),
  );

  let lastResult = null;
  for (let attempt = 1; attempt <= retries; attempt += 1) {
    if (fs.existsSync(expectedReportPath)) {
      fs.rmSync(expectedReportPath, { force: true });
    }

    lastResult = runCode(args, options);
    if (fs.existsSync(expectedReportPath)) {
      return lastResult;
    }

    const updateEvidence = readVsCodeUpdateLockEvidence(path.join(currentUserDataDir, "logs"));
    if (!updateEvidence) {
      return lastResult;
    }

    if (attempt === retries) {
      fail(
        [
          `VSIX E2E launch hit the VS Code updater lock ${retries} times.`,
          `Latest update evidence: ${updateEvidence}`,
          `VS Code stdout:\n${lastResult.stdout ?? ""}`,
          `VS Code stderr:\n${lastResult.stderr ?? ""}`,
        ].join("\n"),
      );
    }

    sleepSync(delayMs);
  }

  return lastResult;
}

function readVsCodeUpdateLockEvidence(logsRoot) {
  if (!fs.existsSync(logsRoot)) {
    return null;
  }

  const pending = [logsRoot];
  const mainLogs = [];
  while (pending.length > 0) {
    const current = pending.pop();
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const entryPath = path.join(current, entry.name);
      if (entry.isDirectory()) {
        pending.push(entryPath);
        continue;
      }
      if (entry.isFile() && entry.name === "main.log") {
        mainLogs.push(entryPath);
      }
    }
  }

  mainLogs.sort((left, right) => fs.statSync(right).mtimeMs - fs.statSync(left).mtimeMs);
  for (const logPath of mainLogs) {
    const text = fs.readFileSync(logPath, "utf8");
    const match = text.match(/Code is currently being updated[\s\S]*?(?=\r?\n|$)/i);
    if (match) {
      return `${logPath}: ${match[0].trim()}`;
    }
  }
  return null;
}

function sleepSync(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

function buildWindowsCmd(command, args) {
  return ["call", quoteWindowsCmdArg(command), ...args.map(quoteWindowsCmdArg)].join(" ");
}

function quoteWindowsCmdArg(value) {
  return `"${String(value).replace(/"/g, '\\"')}"`;
}

function readJsonIfExists(filePath) {
  try {
    if (!fs.existsSync(filePath)) {
      return undefined;
    }
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return undefined;
  }
}

function normalizeError(error) {
  if (error instanceof Error) {
    return {
      name: error.name,
      message: error.message,
      stack: error.stack ?? null,
    };
  }
  return {
    name: "Error",
    message: String(error),
    stack: null,
  };
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

function fail(message) {
  throw new Error(String(message));
}
