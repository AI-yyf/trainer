import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import * as fs from 'node:fs';
import * as net from 'node:net';
import * as path from 'node:path';

import * as vscode from 'vscode';

import { SIDECAR_DEFAULTS, STORAGE_KEYS } from './constants';
import { SidecarHttpClient } from './httpClient';
import type { ManagedDataFolderView, SidecarStatus } from './types';

interface LaunchCandidate {
  label: string;
  command: string;
  args: string[];
  cwd: string;
  env?: Record<string, string>;
}

const SIDECAR_BINARY_MANIFEST_FILE = 'trainer-sidecar-manifest.json';

export interface ManagedDataFolderChangeResult {
  changed: boolean;
  previousPath: string;
  next: ManagedDataFolderView;
  migration:
    | 'not_needed'
    | 'copied'
    | 'source_missing'
    | 'skipped_nonempty_target'
    | 'skipped_nested_target';
}

export interface ManagedDataFolderConfigureOptions {
  /**
   * Root migration and backup restore prepare a verified snapshot before the
   * data-folder pointer changes. Ordinary folder picking must never take over
   * an existing directory whose contents were not copied in this operation.
   */
  allowExistingTarget?: boolean;
}

export interface ManagedDataRootScope {
  rootId?: string;
  legacyWorkspaceFolder?: string;
}

export class SidecarProcessManager implements vscode.Disposable {
  private readonly statusEmitter = new vscode.EventEmitter<SidecarStatus>();
  private readonly client = new SidecarHttpClient();
  private readonly managedDataFolderFallback = new Map<string, string | undefined>();

  private managedDataRootId?: string;
  private managedDataLegacyWorkspaceFolder?: string;
  private managedDataScopeRestartPending = false;

  private process?: ChildProcessWithoutNullStreams;
  private ensurePromise?: Promise<SidecarStatus>;
  private startPromise?: Promise<SidecarStatus>;
  private status: SidecarStatus = {
    lifecycle: 'idle',
    host: SIDECAR_DEFAULTS.host,
    canStart: false,
    detail: 'Sidecar not started yet.',
  };

  readonly onDidChangeStatus = this.statusEmitter.event;

  constructor(
    private readonly extensionContext: vscode.ExtensionContext,
    private readonly outputChannel: vscode.OutputChannel,
  ) {}

  getStatus(): SidecarStatus {
    return { ...this.status };
  }

  async setManagedDataRootScope(scope: ManagedDataRootScope = {}): Promise<boolean> {
    const rootId = normalizeOptionalRootId(scope.rootId);
    const legacyWorkspaceFolder = normalizeOptionalDirectoryPath(scope.legacyWorkspaceFolder);
    const scopeChanged =
      this.managedDataRootId !== rootId ||
      (!rootId && this.managedDataLegacyWorkspaceFolder !== legacyWorkspaceFolder);

    this.managedDataRootId = rootId;
    this.managedDataLegacyWorkspaceFolder = legacyWorkspaceFolder;

    if (rootId) {
      await this.migrateLegacyManagedDataFolderPointer(rootId, legacyWorkspaceFolder);
    }
    if (scopeChanged && (this.process || this.status.lifecycle === 'ready' || this.status.lifecycle === 'starting')) {
      this.managedDataScopeRestartPending = true;
    }
    return scopeChanged;
  }

  hasPendingManagedDataScopeRestart(): boolean {
    return this.managedDataScopeRestartPending;
  }

  getManagedDataFolderSnapshot(workspaceFolder?: string): ManagedDataFolderView {
    const defaultPath = this.resolveDefaultSidecarDataDirectory();
    const configuredPath = this.getConfiguredManagedDataFolder(workspaceFolder);
    const localConfiguredPath = isUsableLocalDataDirectory(configuredPath)
      ? configuredPath
      : undefined;
    const effectivePath = localConfiguredPath ?? defaultPath;
    fs.mkdirSync(effectivePath, { recursive: true });
    return {
      configuredPath: localConfiguredPath,
      effectivePath,
      defaultPath,
      source: localConfiguredPath ? 'custom' : 'recommended',
      status: 'ready',
    };
  }

  async configureManagedDataFolder(
    targetPath: string,
    workspaceFolder?: string,
    options: ManagedDataFolderConfigureOptions = {},
  ): Promise<ManagedDataFolderChangeResult> {
    const normalizedTargetPath = normalizeDirectoryPath(targetPath);
    if (!isUsableLocalDataDirectory(normalizedTargetPath)) {
      throw new Error('Trainer managed data folder must be a local directory.');
    }
    const previous = this.getManagedDataFolderSnapshot(workspaceFolder);
    if (pathsEqual(previous.effectivePath, normalizedTargetPath)) {
      return {
        changed: false,
        previousPath: previous.effectivePath,
        next: previous,
        migration: 'not_needed',
      };
    }

    const defaultPath = this.resolveDefaultSidecarDataDirectory();
    if (pathsEqual(normalizedTargetPath, defaultPath)) {
      return this.resetManagedDataFolder(workspaceFolder, options);
    }

    if (isNestedPath(previous.effectivePath, normalizedTargetPath)) {
      throw new Error('Trainer managed data folder cannot be nested inside its current data directory.');
    }
    if (!directoryIsEmpty(normalizedTargetPath) && !options.allowExistingTarget) {
      throw new Error(
        'Trainer managed data folder target must be empty unless it was prepared by workspace recovery.',
      );
    }

    await this.stopForManagedDataTransfer();
    fs.mkdirSync(normalizedTargetPath, { recursive: true });
    const migration = this.migrateManagedDataFolder(previous.effectivePath, normalizedTargetPath);
    if (migration === 'skipped_nested_target') {
      throw new Error('Trainer managed data folder cannot be nested inside its current data directory.');
    }
    await this.persistConfiguredManagedDataFolder(workspaceFolder, normalizedTargetPath);
    return {
      changed: true,
      previousPath: previous.effectivePath,
      next: this.getManagedDataFolderSnapshot(workspaceFolder),
      migration,
    };
  }

  async resetManagedDataFolder(
    workspaceFolder?: string,
    options: ManagedDataFolderConfigureOptions = {},
  ): Promise<ManagedDataFolderChangeResult> {
    const previous = this.getManagedDataFolderSnapshot(workspaceFolder);
    const defaultPath = this.resolveDefaultSidecarDataDirectory();
    if (pathsEqual(previous.effectivePath, defaultPath) && !previous.configuredPath) {
      return {
        changed: false,
        previousPath: previous.effectivePath,
        next: previous,
        migration: 'not_needed',
      };
    }

    if (isNestedPath(previous.effectivePath, defaultPath)) {
      throw new Error('Trainer managed data folder cannot be nested inside its current data directory.');
    }
    if (!directoryIsEmpty(defaultPath) && !options.allowExistingTarget) {
      throw new Error(
        'The recommended Trainer data folder already contains data. Choose a new empty folder or use workspace recovery.',
      );
    }

    await this.stopForManagedDataTransfer();
    fs.mkdirSync(defaultPath, { recursive: true });
    const migration = this.migrateManagedDataFolder(previous.effectivePath, defaultPath);
    if (migration === 'skipped_nested_target') {
      throw new Error('Trainer managed data folder cannot be nested inside its current data directory.');
    }
    await this.persistConfiguredManagedDataFolder(workspaceFolder, undefined);
    return {
      changed: true,
      previousPath: previous.effectivePath,
      next: this.getManagedDataFolderSnapshot(workspaceFolder),
      migration,
    };
  }

  async ensureRunning(): Promise<SidecarStatus> {
    if (this.ensurePromise) {
      return this.ensurePromise;
    }

    const ensurePromise = this.ensureRunningInternal();
    this.ensurePromise = ensurePromise;
    try {
      return await ensurePromise;
    } finally {
      if (this.ensurePromise === ensurePromise) {
        this.ensurePromise = undefined;
      }
    }
  }

  private async ensureRunningInternal(): Promise<SidecarStatus> {
    if (this.managedDataScopeRestartPending) {
      await this.stop();
      this.managedDataScopeRestartPending = false;
    }

    if (this.startPromise) {
      return this.startPromise;
    }

    if (this.status.port) {
      const healthy = await this.client.probeHealth(this.status.port);
      if (healthy) {
        this.updateStatus({
          ...this.status,
          lifecycle: 'ready',
          lastHealthcheckAt: new Date().toISOString(),
        });
        return this.getStatus();
      }

      if (this.process?.exitCode === null) {
        this.updateStatus({
          ...this.status,
          // A slow provider turn can occupy the sidecar long enough for a health
          // probe to miss. Keep the live process routable so follow-up commands
          // are not rejected before it has a chance to finish the active request.
          lifecycle: 'ready',
          detail:
            'Sidecar is still running and may be processing a request. Its health check did not answer yet; it will be checked again before a restart.',
        });
        return this.getStatus();
      }
    }

    if (this.process) {
      this.process = undefined;
    }

    this.startPromise = this.start();
    try {
      return await this.startPromise;
    } finally {
      this.startPromise = undefined;
    }
  }

  async stop(): Promise<void> {
    if (!this.process && this.startPromise) {
      await this.startPromise.catch(() => undefined);
      if (this.process) {
        await this.stop();
        return;
      }
    }
    if (!this.process) {
      this.updateStatus({
        ...this.status,
        lifecycle: 'stopped',
        detail: 'Sidecar is not running.',
      });
      return;
    }

    const process = this.process;
    const didExit = await this.terminateChild(process);

    if (!didExit) {
      this.updateStatus({
        ...this.status,
        lifecycle: 'error',
        detail: 'Sidecar did not stop before the workspace data operation timed out.',
      });
      throw new Error('Sidecar did not stop before the workspace data operation timed out.');
    }
    if (this.process === process) {
      this.process = undefined;
    }
    if (this.startPromise) {
      await this.startPromise.catch(() => undefined);
    }

    this.updateStatus({
      lifecycle: 'stopped',
      host: SIDECAR_DEFAULTS.host,
      canStart: this.status.canStart,
      detail: 'Sidecar stopped.',
    });
  }

  async restart(): Promise<SidecarStatus> {
    await this.stop();
    return this.ensureRunning();
  }

  dispose(): void {
    void this.stop();
    this.statusEmitter.dispose();
  }

  private async start(): Promise<SidecarStatus> {
    const port = await this.resolveLaunchPort();
    const candidates = this.buildLaunchCandidates(port);
    if (candidates.length === 0) {
      const status: SidecarStatus = {
        lifecycle: 'unavailable',
        host: SIDECAR_DEFAULTS.host,
        canStart: false,
        detail: this.getUnavailableLaunchDetail(),
      };
      this.updateStatus(status);
      return status;
    }

    let lastError: Error | undefined;

    for (const candidate of candidates) {
      try {
        return await this.launchCandidate(candidate, port);
      } catch (error) {
        lastError = error instanceof Error ? error : new Error(String(error));
        this.outputChannel.appendLine(
          `[sidecar] launch failed for ${candidate.command}: ${lastError.message}`,
        );
        if (this.process?.exitCode === null) {
          break;
        }
      }
    }

    const status: SidecarStatus = {
      lifecycle: 'error',
      host: SIDECAR_DEFAULTS.host,
      port,
      canStart: true,
      detail: lastError?.message ?? 'Unable to start sidecar.',
    };
    this.updateStatus(status);
    return status;
  }

  private async launchCandidate(candidate: LaunchCandidate, port: number): Promise<SidecarStatus> {
    this.outputChannel.appendLine(
      `[sidecar] starting (${candidate.label}): ${candidate.command} ${candidate.args.join(' ')}`,
    );

    const child = spawn(candidate.command, candidate.args, {
      cwd: candidate.cwd,
      env: {
        ...process.env,
        // Do not leak an embedding Python environment into the PyInstaller
        // sidecar; PYTHONHOME/PYTHONPATH can hide its bundled stdlib.
        PYTHONHOME: undefined,
        PYTHONPATH: undefined,
        PYTHONEXECUTABLE: undefined,
        TRAINER_HOST: SIDECAR_DEFAULTS.host,
        PYTHONUNBUFFERED: '1',
        TRAINER_PORT: String(port),
        TRAINER_DATA_DIR: this.resolveSidecarDataDirectory(),
        ...candidate.env,
      },
      stdio: 'pipe',
      windowsHide: true,
    });

    child.stdout.on('data', (chunk) => {
      this.outputChannel.append(chunk.toString());
    });
    child.stderr.on('data', (chunk) => {
      this.outputChannel.append(chunk.toString());
    });

    const commandLine = `${candidate.command} ${candidate.args.join(' ')}`;
    this.process = child;
    this.updateStatus({
      lifecycle: 'starting',
      host: SIDECAR_DEFAULTS.host,
      port,
      pid: child.pid,
      commandLine,
      canStart: true,
      detail: 'Waiting for sidecar health check.',
    });

    const exitPromise = new Promise<never>((_, reject) => {
      child.once('error', reject);
      child.once('exit', (code, signal) => {
        reject(new Error(`Sidecar exited before readiness (code=${code}, signal=${signal})`));
      });
    });

    try {
      await Promise.race([this.waitForHealth(port), exitPromise]);

      child.removeAllListeners('exit');
      child.removeAllListeners('error');
      child.once('exit', (code, signal) => {
        if (this.process === child) {
          this.process = undefined;
          this.updateStatus({
            lifecycle: 'stopped',
            host: SIDECAR_DEFAULTS.host,
            canStart: true,
            detail: `Sidecar exited (code=${code}, signal=${signal}).`,
          });
        }
      });

      const status: SidecarStatus = {
        lifecycle: 'ready',
        host: SIDECAR_DEFAULTS.host,
        port,
        pid: child.pid,
        commandLine,
        canStart: true,
        detail: 'Sidecar ready.',
        lastHealthcheckAt: new Date().toISOString(),
      };
      this.updateStatus(status);
      return status;
    } catch (error) {
      const didExit = await this.terminateChild(child);
      if (!didExit) {
        const detail = error instanceof Error ? error.message : String(error);
        this.updateStatus({
          lifecycle: 'error',
          host: SIDECAR_DEFAULTS.host,
          port,
          pid: child.pid,
          commandLine,
          canStart: true,
          detail: `Sidecar failed to start and did not stop cleanly: ${detail}`,
        });
        throw new Error(`Sidecar failed to start and did not stop cleanly: ${detail}`);
      }
      if (this.process === child) {
        this.process = undefined;
      }
      throw error;
    }
  }

  private async resolveLaunchPort(): Promise<number> {
    const configuredPort = this.readConfiguredSidecarPort();
    if (configuredPort !== undefined) {
      if (await isPortAvailable(configuredPort)) {
        return configuredPort;
      }
      this.outputChannel.appendLine(
        `[sidecar] configured port ${configuredPort} is unavailable; using a managed fallback port.`,
      );
    }
    return findAvailablePort(SIDECAR_DEFAULTS.portStart, SIDECAR_DEFAULTS.portEnd);
  }

  private readConfiguredSidecarPort(): number | undefined {
    const configuredPort = vscode.workspace?.getConfiguration?.('trainer')?.get<unknown>('sidecar.port');
    if (
      typeof configuredPort !== 'number' ||
      !Number.isInteger(configuredPort) ||
      configuredPort < 1 ||
      configuredPort > 65_535
    ) {
      return undefined;
    }
    return configuredPort;
  }

  private async terminateChild(process: ChildProcessWithoutNullStreams): Promise<boolean> {
    return new Promise<boolean>((resolve) => {
      let settled = false;
      const finish = (value: boolean) => {
        if (settled) {
          return;
        }
        settled = true;
        clearTimeout(timeout);
        process.removeListener('exit', onExit);
        resolve(value);
      };
      const onExit = () => finish(true);
      const timeout = setTimeout(() => finish(false), 5_000);
      process.once('exit', onExit);
      if (process.exitCode !== null) {
        finish(true);
        return;
      }
      try {
        process.kill();
      } catch {
        finish(false);
      }
    });
  }

  private async waitForHealth(port: number): Promise<void> {
    const startedAt = Date.now();
    while (Date.now() - startedAt < SIDECAR_DEFAULTS.startupTimeoutMs) {
      if (await this.client.probeHealth(port)) {
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 750));
    }

    throw new Error('Timed out waiting for sidecar health check.');
  }

  private async stopForManagedDataTransfer(): Promise<void> {
    if (this.process || this.status.lifecycle === 'starting') {
      await this.stop();
    }
  }

  private getConfiguredManagedDataFolder(workspaceFolder?: string): string | undefined {
    const storageKey = this.getManagedDataFolderStorageKey(workspaceFolder);
    return this.getConfiguredManagedDataFolderForStorageKey(storageKey);
  }

  private getConfiguredManagedDataFolderForStorageKey(storageKey: string): string | undefined {
    const workspaceState = this.extensionContext.workspaceState;
    if (workspaceState?.get) {
      return normalizeOptionalDirectoryPath(workspaceState.get<string>(storageKey));
    }
    const globalState = this.extensionContext.globalState;
    if (globalState?.get) {
      return normalizeOptionalDirectoryPath(globalState.get<string>(storageKey));
    }
    return normalizeOptionalDirectoryPath(this.managedDataFolderFallback.get(storageKey));
  }

  private async persistConfiguredManagedDataFolder(
    workspaceFolder: string | undefined,
    configuredPath: string | undefined,
  ): Promise<void> {
    const storageKey = this.getManagedDataFolderStorageKey(workspaceFolder);
    await this.persistConfiguredManagedDataFolderForStorageKey(storageKey, configuredPath);
  }

  private async persistConfiguredManagedDataFolderForStorageKey(
    storageKey: string,
    configuredPath: string | undefined,
  ): Promise<void> {
    const normalizedPath = normalizeOptionalDirectoryPath(configuredPath);
    const workspaceState = this.extensionContext.workspaceState;
    if (workspaceState?.update) {
      await workspaceState.update(storageKey, normalizedPath);
      return;
    }
    const globalState = this.extensionContext.globalState;
    if (globalState?.update) {
      await globalState.update(storageKey, normalizedPath);
      return;
    }
    this.managedDataFolderFallback.set(storageKey, normalizedPath);
  }

  private getManagedDataFolderStorageKey(workspaceFolder?: string): string {
    if (this.managedDataRootId) {
      return `${STORAGE_KEYS.managedDataFolderByWorkspacePrefix}:root:${encodeURIComponent(
        this.managedDataRootId,
      )}`;
    }
    return this.getLegacyManagedDataFolderStorageKey(
      workspaceFolder ?? this.managedDataLegacyWorkspaceFolder,
    );
  }

  private getLegacyManagedDataFolderStorageKey(workspaceFolder?: string): string {
    return `${STORAGE_KEYS.managedDataFolderByWorkspacePrefix}:${
      workspaceFolder ? normalizeDirectoryPath(workspaceFolder) : '__default__'
    }`;
  }

  private resolveDefaultSidecarDataDirectory(): string {
    const globalStoragePath = this.extensionContext.globalStorageUri.fsPath;
    const sidecarDataPath = this.managedDataRootId
      ? path.join(globalStoragePath, 'sidecar', 'roots', encodeURIComponent(this.managedDataRootId))
      : path.join(globalStoragePath, 'sidecar');
    fs.mkdirSync(sidecarDataPath, { recursive: true });
    return sidecarDataPath;
  }

  private async migrateLegacyManagedDataFolderPointer(
    rootId: string,
    legacyWorkspaceFolder: string | undefined,
  ): Promise<void> {
    const rootStorageKey = `${STORAGE_KEYS.managedDataFolderByWorkspacePrefix}:root:${encodeURIComponent(
      rootId,
    )}`;
    if (this.getConfiguredManagedDataFolderForStorageKey(rootStorageKey)) {
      return;
    }

    const legacyStorageKey = this.getLegacyManagedDataFolderStorageKey(legacyWorkspaceFolder);
    const legacyConfiguredPath = this.getConfiguredManagedDataFolderForStorageKey(legacyStorageKey);
    if (!legacyConfiguredPath) {
      return;
    }

    await this.persistConfiguredManagedDataFolderForStorageKey(rootStorageKey, legacyConfiguredPath);
    await this.persistConfiguredManagedDataFolderForStorageKey(legacyStorageKey, undefined);
  }

  private migrateManagedDataFolder(sourcePath: string, targetPath: string): ManagedDataFolderChangeResult['migration'] {
    if (pathsEqual(sourcePath, targetPath)) {
      return 'not_needed';
    }
    if (!fs.existsSync(sourcePath)) {
      return 'source_missing';
    }
    if (isNestedPath(sourcePath, targetPath) || isNestedPath(targetPath, sourcePath)) {
      return 'skipped_nested_target';
    }
    if (!directoryIsEmpty(targetPath)) {
      return 'skipped_nonempty_target';
    }

    for (const childName of fs.readdirSync(sourcePath)) {
      const childSource = path.join(sourcePath, childName);
      const childTarget = path.join(targetPath, childName);
      fs.cpSync(childSource, childTarget, { recursive: true });
    }
    return 'copied';
  }

  private buildLaunchCandidates(port: number): LaunchCandidate[] {
    const bundledCandidates: LaunchCandidate[] = [];
    const bundledBinary = this.resolveBundledBinary();
    if (bundledBinary) {
      bundledCandidates.push({
        label: 'bundled-binary',
        command: bundledBinary,
        args: ['--host', SIDECAR_DEFAULTS.host, '--port', String(port)],
        cwd: path.dirname(bundledBinary),
      });
    }

    if (!this.canUseDevelopmentSourceSidecar()) {
      return bundledCandidates;
    }

    const serverDir = this.resolveServerDirectory();
    if (!serverDir) {
      return bundledCandidates;
    }

    const launcherScript = path.join(serverDir, 'run_sidecar.py');
    if (!fs.existsSync(launcherScript)) {
      return bundledCandidates;
    }

    if (this.isBundledServerDirectory(serverDir) && bundledCandidates.length === 0) {
      return [];
    }

    const sourceCandidates: LaunchCandidate[] = [];
    const localPython = this.resolveProjectPython(serverDir);
    if (localPython) {
      sourceCandidates.push({
        label: 'workspace-venv',
        command: localPython,
        args: [launcherScript, '--host', SIDECAR_DEFAULTS.host, '--port', String(port)],
        cwd: serverDir,
      });
    }

    sourceCandidates.push({
      label: 'uv-run',
      command: 'uv',
      args: ['run', '--directory', serverDir, 'python', 'run_sidecar.py', '--host', SIDECAR_DEFAULTS.host, '--port', String(port)],
      cwd: serverDir,
    });
    sourceCandidates.push(
      ...systemPythonCommands().map(({ label, command }) => ({
        label,
        command,
        args: [launcherScript, '--host', SIDECAR_DEFAULTS.host, '--port', String(port)],
        cwd: serverDir,
      })),
    );

    const preferSourceCandidates =
      sourceCandidates.length > 0 && !this.isBundledServerDirectory(serverDir);
    return preferSourceCandidates
      ? [...sourceCandidates, ...bundledCandidates]
      : [...bundledCandidates, ...sourceCandidates];
  }

  private resolveServerDirectory(): string | undefined {
    const bundledServer = path.join(this.extensionContext.extensionPath, 'bundled', 'server');
    const candidates = this.canUseDevelopmentSourceSidecar()
      ? [
          vscode.workspace.workspaceFolders?.[0]
            ? path.join(vscode.workspace.workspaceFolders[0].uri.fsPath, 'server')
            : undefined,
          bundledServer,
          path.resolve(this.extensionContext.extensionPath, '..', 'server'),
        ]
      : [bundledServer];

    for (const candidate of candidates) {
      if (candidate && fs.existsSync(candidate) && fs.statSync(candidate).isDirectory()) {
        return candidate;
      }
    }

    return undefined;
  }

  private canUseDevelopmentSourceSidecar(): boolean {
    return this.extensionContext.extensionMode === vscode.ExtensionMode.Development;
  }

  private resolveProjectPython(serverDir: string): string | undefined {
    const candidates = process.platform === 'win32'
      ? [
          path.join(serverDir, '.venv', 'Scripts', 'python.exe'),
          path.join(serverDir, '.venv-mac', 'Scripts', 'python.exe'),
        ]
      : [
          path.join(serverDir, '.venv-mac', 'bin', 'python'),
          path.join(serverDir, '.venv', 'bin', 'python'),
          path.join(serverDir, '.venv', 'Scripts', 'python.exe'),
        ];

    return candidates.find((candidate) => fs.existsSync(candidate));
  }

  private isBundledServerDirectory(serverDir: string): boolean {
    const bundledServer = path.join(this.extensionContext.extensionPath, 'bundled', 'server');
    return path.resolve(serverDir) === path.resolve(bundledServer);
  }

  private resolveBundledBinary(): string | undefined {
    const platformKey = `${process.platform}-${process.arch}`;
    const bundledBinDir = path.join(
      this.extensionContext.extensionPath,
      'bundled',
      'bin',
      platformKey,
    );
    const executableName = process.platform === 'win32' ? 'trainer-sidecar.exe' : 'trainer-sidecar';
    const manifestPath = path.join(bundledBinDir, SIDECAR_BINARY_MANIFEST_FILE);
    if (!hasTrustedBundledBinaryManifest(manifestPath, platformKey, executableName)) {
      return undefined;
    }
    const candidates = [
      path.join(bundledBinDir, executableName),
      path.join(bundledBinDir, 'trainer-sidecar', executableName),
    ];

    return candidates.find((candidate) => {
      if (!fs.existsSync(candidate)) {
        return false;
      }

      try {
        return fs.statSync(candidate).isFile();
      } catch {
        return false;
      }
    });
  }

  private resolveSidecarDataDirectory(): string {
    return this.getManagedDataFolderSnapshot(
      this.managedDataLegacyWorkspaceFolder ?? vscode.workspace.workspaceFolders?.[0]?.uri.fsPath,
    )
      .effectivePath;
  }

  private getUnavailableLaunchDetail(): string {
    const serverDir = this.resolveServerDirectory();
    if (serverDir && this.isBundledServerDirectory(serverDir) && !this.resolveBundledBinary()) {
      const targetPlatform = `${process.platform}-${process.arch}`;
      const targetLabel = describeNativeRuntimeTarget(targetPlatform);
      return `This Trainer package does not include a verified runtime for ${targetLabel}. Install the Trainer VSIX built for ${targetLabel}, then reopen Trainer.`;
    }
    return 'No Trainer sidecar binary or server source could be found.';
  }

  private updateStatus(status: SidecarStatus): void {
    this.status = status;
    this.statusEmitter.fire(this.getStatus());
  }
}

function isUsableLocalDataDirectory(candidate?: string): boolean {
  const normalized = String(candidate || '').trim();
  if (!normalized || normalized.includes('://')) {
    return false;
  }
  if (
    process.platform === 'win32' &&
    (normalized.startsWith('/') || normalized.startsWith('\\')) &&
    !normalized.startsWith('\\\\')
  ) {
    return false;
  }
  try {
    fs.mkdirSync(normalized, { recursive: true });
    return true;
  } catch {
    return false;
  }
}

function systemPythonCommands(): Array<Pick<LaunchCandidate, 'label' | 'command'>> {
  if (process.platform === 'win32') {
    return [{ label: 'system-python', command: 'python' }];
  }

  return [
    { label: 'system-python3.12', command: 'python3.12' },
    { label: 'system-python3', command: 'python3' },
    { label: 'system-python', command: 'python' },
  ];
}

function describeNativeRuntimeTarget(targetPlatform: string): string {
  const labels: Record<string, string> = {
    'win32-x64': 'Windows x64',
    'win32-arm64': 'Windows ARM64',
    'darwin-x64': 'macOS Intel',
    'darwin-arm64': 'macOS Apple Silicon',
    'linux-x64': 'Linux x64',
    'linux-arm64': 'Linux ARM64',
  };
  return labels[targetPlatform] ?? targetPlatform;
}

function hasTrustedBundledBinaryManifest(
  manifestPath: string,
  platformKey: string,
  entryName: string,
): boolean {
  try {
    const parsed: unknown = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
    if (!isRecord(parsed) || parsed.manifestVersion !== 1) {
      return false;
    }
    if (parsed.platform !== platformKey || parsed.entryName !== entryName) {
      return false;
    }
    if (!isRecord(parsed.sourceSnapshot)) {
      return false;
    }
    const { fileCount, sha256 } = parsed.sourceSnapshot;
    return (
      typeof fileCount === 'number' &&
      Number.isInteger(fileCount) &&
      fileCount >= 0 &&
      typeof sha256 === 'string' &&
      /^[a-f0-9]{64}$/i.test(sha256)
    );
  } catch {
    return false;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function normalizeOptionalDirectoryPath(value: string | undefined): string | undefined {
  if (!value?.trim()) {
    return undefined;
  }
  return normalizeDirectoryPath(value);
}

function normalizeOptionalRootId(value: string | undefined): string | undefined {
  const normalized = value?.trim();
  return normalized || undefined;
}

function normalizeDirectoryPath(value: string): string {
  return path.resolve(value.trim());
}

function pathsEqual(left: string, right: string): boolean {
  return comparableDirectoryPath(left) === comparableDirectoryPath(right);
}

function isNestedPath(basePath: string, candidatePath: string): boolean {
  const relative = path.relative(comparableDirectoryPath(basePath), comparableDirectoryPath(candidatePath));
  return (
    Boolean(relative) &&
    relative !== '..' &&
    !relative.startsWith(`..${path.sep}`) &&
    !path.isAbsolute(relative)
  );
}

function comparableDirectoryPath(value: string): string {
  const normalized = normalizeDirectoryPath(value);
  return process.platform === 'win32' ? normalized.toLowerCase() : normalized;
}

function directoryIsEmpty(targetPath: string): boolean {
  if (!fs.existsSync(targetPath)) {
    return true;
  }
  try {
    return fs.readdirSync(targetPath).length === 0;
  } catch {
    return false;
  }
}

async function findAvailablePort(start: number, end: number): Promise<number> {
  for (let port = start; port <= end; port += 1) {
    if (await isPortAvailable(port)) {
      return port;
    }
  }

  throw new Error(`No free port found in ${start}-${end}.`);
}

async function isPortAvailable(port: number): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    const server = net.createServer();
    server.once('error', () => resolve(false));
    server.once('listening', () => {
      server.close(() => resolve(true));
    });
    server.listen(port, SIDECAR_DEFAULTS.host);
  });
}
