import * as crypto from 'node:crypto';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import type * as vscode from 'vscode';

export const TRAINER_WORKSPACE_ROOT_STORAGE_KEY = 'trainer.workspace.root.v1';
export const TRAINER_WORKSPACE_PROJECTS_STORAGE_KEY = 'trainer.workspace.projects.v1';
export const TRAINER_WORKSPACE_PENDING_RECONCILIATIONS_STORAGE_KEY =
  'trainer.workspace.pending-reconciliations.v2';
export const TRAINER_WORKSPACE_MANIFEST_FILE = path.join('.trainer', 'workspace.json');
export const TRAINER_WORKSPACE_BACKUP_FILE = path.join('.trainer', 'backup.json');
export const TRAINER_WORKSPACE_RUNTIME_DATA_DIRECTORY = path.join('.trainer', 'runtime');

export const TRAINER_WORKSPACE_DIRECTORIES = [
  'Projects',
  'Knowledge',
  'Skills',
  'Agents',
  'Assets',
  '.trainer',
  path.join('.trainer', 'memory'),
  path.join('.trainer', 'plans'),
  path.join('.trainer', 'indexes'),
  path.join('.trainer', 'checkpoints'),
  path.join('.trainer', 'logs'),
  path.join('.trainer', 'cache'),
] as const;

export const TRAINER_MANAGED_PROJECT_DIRECTORIES = [
  'memory',
  'plans',
  'training',
  'agent',
] as const;

export type TrainerProjectAdoptionMode = 'managed' | 'browse' | 'ignored';

export type TrainerWorkspaceIdentityStatus = 'pending' | 'verified' | 'reconcile-required';

export interface TrainerProjectIdentityRevisions {
  root?: number;
  project?: number;
  context?: number;
}

/** Stable identity issued by the Trainer backend after successful adoption. */
export interface TrainerManagedProjectIdentity {
  rootId: string;
  projectId: string;
  contextId: string;
  /** Canonical Trainer data-root path returned by the backend when available. */
  canonicalRootPath?: string;
  canonicalProjectPath: string;
  legacyAliases?: string[];
  revisions?: TrainerProjectIdentityRevisions;
  pending?: boolean;
  reconcile?: Record<string, unknown>;
}

export interface TrainerWorkspaceProjectState {
  /** Legacy path lookup key. It is never treated as the project identity. */
  fingerprint: string;
  projectPath: string;
  workspaceRoot: string;
  adoptionMode: TrainerProjectAdoptionMode;
  projectLanePath?: string;
  rootId?: string;
  projectId?: string;
  contextId?: string;
  canonicalProjectPath: string;
  legacyAliases: string[];
  manifestRevision: number;
  pathRevision: number;
  identityStatus: TrainerWorkspaceIdentityStatus;
  serverRevisions?: TrainerProjectIdentityRevisions;
  reconcile?: Record<string, unknown>;
  updatedAt: string;
}

export interface TrainerWorkspaceManifest {
  schemaVersion: 2;
  kind: 'trainer-workspace';
  rootPath: string;
  canonicalRootPath: string;
  rootId?: string;
  legacyRootPaths: string[];
  manifestRevision: number;
  pathRevision: number;
  identityStatus: TrainerWorkspaceIdentityStatus;
  createdAt: string;
  updatedAt: string;
  directories: readonly string[];
  projects: Record<string, TrainerWorkspaceProjectState>;
}

export interface TrainerWorkspaceSnapshot {
  rootPath?: string;
  workspaceReady: boolean;
  manifest?: TrainerWorkspaceManifest;
  currentProject?: TrainerWorkspaceProjectState;
}

export interface TrainerWorkspaceRootTransfer {
  sourceRoot: string;
  targetRoot: string;
  projectCount: number;
  completedAt: string;
  managedDataRoot?: string;
}

export interface TrainerWorkspaceRecoveryOptions {
  /**
   * The live sidecar data directory. It is usually outside the workspace root,
   * so recovery operations must capture it explicitly instead of treating the
   * workspace scaffold as a complete snapshot.
   */
  managedDataRoot?: string;
}

interface TrainerWorkspaceRuntimeDataSnapshot {
  relativePath: string;
}

export interface TrainerWorkspaceBackupManifest {
  schemaVersion: 1;
  kind: 'trainer-workspace-backup';
  sourceRoot: string;
  createdAt: string;
  workspaceManifest: TrainerWorkspaceManifest;
  runtimeData?: TrainerWorkspaceRuntimeDataSnapshot;
}

export interface TrainerWorkspaceBackup {
  backupRoot: string;
  sourceRoot: string;
  projectCount: number;
  createdAt: string;
  managedDataRoot?: string;
}

export type TrainerWorkspacePendingReconciliationState = 'waiting' | 'retry-required';

export type TrainerWorkspacePendingReconciliationAction =
  | 'continue-waiting'
  | 'retry'
  | 'abandon';

export interface TrainerWorkspacePendingReconciliationInput {
  /** Stable backend adoption-job identifier, when a background job was started. */
  jobId?: string;
  /**
   * `waiting` preserves a live job that can be polled after the host resumes.
   * All other interrupted admissions require an explicit retry.
   */
  state?: TrainerWorkspacePendingReconciliationState;
  /** A verified identity can be retained when only local persistence failed. */
  identity?: unknown;
}

export interface TrainerWorkspacePendingReconciliation {
  projectPath: string;
  workspaceRoot: string;
  reason: string;
  jobId?: string;
  state: TrainerWorkspacePendingReconciliationState;
  availableActions: readonly TrainerWorkspacePendingReconciliationAction[];
  updatedAt: string;
  identity?: TrainerManagedProjectIdentity;
}

type TrainerWorkspaceProjectRegistry = Record<string, TrainerWorkspaceProjectState>;
type TrainerWorkspacePendingReconciliationRegistry = Record<string, TrainerWorkspacePendingReconciliation>;

interface ResolvedRuntimeDataSnapshot {
  sourceRoot: string;
  relativePath: string;
  isOutsideWorkspaceRoot: boolean;
}

function normalizeRequiredDirectoryPath(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    throw new Error('A workspace directory path is required.');
  }
  return path.resolve(trimmed);
}

function normalizeOptionalDirectoryPath(value: unknown): string | undefined {
  if (typeof value !== 'string' || !value.trim()) {
    return undefined;
  }
  return path.resolve(value.trim());
}

function canonicalPathForComparison(value: string): string {
  const normalized = path.normalize(value);
  return process.platform === 'win32' ? normalized.toLocaleLowerCase('en-US') : normalized;
}

function pathsEqual(left: string, right: string): boolean {
  return canonicalPathForComparison(left) === canonicalPathForComparison(right);
}

function pathContains(parentPath: string, candidatePath: string): boolean {
  const relative = path.relative(parentPath, candidatePath);
  return Boolean(relative) && !relative.startsWith('..') && !path.isAbsolute(relative);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isAdoptionMode(value: unknown): value is TrainerProjectAdoptionMode {
  return value === 'managed' || value === 'browse' || value === 'ignored';
}

function isIdentityStatus(value: unknown): value is TrainerWorkspaceIdentityStatus {
  return value === 'pending' || value === 'verified' || value === 'reconcile-required';
}

function isPendingReconciliationState(
  value: unknown,
): value is TrainerWorkspacePendingReconciliationState {
  return value === 'waiting' || value === 'retry-required';
}

function isSafeIdentity(value: unknown): value is string {
  return typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$/.test(value);
}

function resolvePendingReconciliationActions(
  state: TrainerWorkspacePendingReconciliationState,
  jobId?: string,
): readonly TrainerWorkspacePendingReconciliationAction[] {
  return [
    ...(state === 'waiting' && jobId ? (['continue-waiting'] as const) : []),
    'retry',
    'abandon',
  ];
}

function normalizeStringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return [...new Set(value.filter((item): item is string => typeof item === 'string' && Boolean(item.trim())).map(
    (item) => item.trim(),
  ))];
}

function normalizeRevision(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : fallback;
}

function normalizeServerRevisions(value: unknown): TrainerProjectIdentityRevisions | undefined {
  if (!isRecord(value)) {
    return undefined;
  }
  const revisions: TrainerProjectIdentityRevisions = {
    root: normalizeRevision(value.root),
    project: normalizeRevision(value.project),
    context: normalizeRevision(value.context),
  };
  return revisions.root || revisions.project || revisions.context ? revisions : undefined;
}

function normalizeManagedProjectIdentity(
  value: unknown,
  expectedProjectPath: string,
  expectedRootPath?: string,
): TrainerManagedProjectIdentity {
  if (!isRecord(value)) {
    throw new Error('Trainer backend did not return a project identity.');
  }
  if (value.pending === true) {
    throw new Error('Trainer backend reported that project identity reconciliation is still pending.');
  }
  if (!isSafeIdentity(value.rootId) || !isSafeIdentity(value.projectId) || !isSafeIdentity(value.contextId)) {
    throw new Error('Trainer backend returned an invalid stable project identity.');
  }
  const canonicalProjectPath = normalizeRequiredDirectoryPath(
    typeof value.canonicalProjectPath === 'string' ? value.canonicalProjectPath : '',
  );
  if (!pathsEqual(canonicalProjectPath, expectedProjectPath)) {
    throw new Error('Trainer backend project identity does not match the current project path.');
  }
  const canonicalRootPath = normalizeOptionalDirectoryPath(value.canonicalRootPath);
  if (canonicalRootPath && expectedRootPath && !pathsEqual(canonicalRootPath, expectedRootPath)) {
    throw new Error('Trainer backend project identity does not match the selected workspace root.');
  }
  return {
    rootId: value.rootId,
    projectId: value.projectId,
    contextId: value.contextId,
    canonicalRootPath,
    canonicalProjectPath,
    legacyAliases: normalizeStringList(value.legacyAliases),
    revisions: normalizeServerRevisions(value.revisions),
    reconcile: isRecord(value.reconcile) ? { ...value.reconcile } : undefined,
  };
}

function identityRequiresReconciliation(identity: TrainerManagedProjectIdentity): boolean {
  if (!identity.reconcile) {
    return false;
  }
  for (const value of Object.values(identity.reconcile)) {
    if (!isRecord(value) || typeof value.state !== 'string') {
      continue;
    }
    if (value.state !== 'current' && value.state !== 'reconciled') {
      return true;
    }
  }
  return false;
}

function isNotFoundError(error: unknown): boolean {
  return isRecord(error) && error.code === 'ENOENT';
}

function isTransientWindowsRenameError(error: unknown): boolean {
  return process.platform === 'win32' && isRecord(error) && (error.code === 'EPERM' || error.code === 'EACCES');
}

function chooseNewestProjectState(
  first: TrainerWorkspaceProjectState | undefined,
  second: TrainerWorkspaceProjectState | undefined,
): TrainerWorkspaceProjectState | undefined {
  if (!first) {
    return second;
  }
  if (!second) {
    return first;
  }
  return second.updatedAt >= first.updatedAt ? second : first;
}

export function fingerprintTrainerProjectPath(projectPath: string): string {
  const normalizedPath = normalizeRequiredDirectoryPath(projectPath);
  return crypto.createHash('sha256').update(canonicalPathForComparison(normalizedPath)).digest('hex');
}

export class TrainerWorkspaceService {
  constructor(private readonly extensionContext: vscode.ExtensionContext) {}

  getWorkspaceRoot(): string | undefined {
    return normalizeOptionalDirectoryPath(
      this.extensionContext.globalState.get<unknown>(TRAINER_WORKSPACE_ROOT_STORAGE_KEY),
    );
  }

  getRoot(): string | undefined {
    return this.getWorkspaceRoot();
  }

  async saveWorkspaceRoot(rootPath: string): Promise<TrainerWorkspaceManifest> {
    const normalizedRoot = normalizeRequiredDirectoryPath(rootPath);
    await this.createWorkspaceScaffold(normalizedRoot);

    const existingManifest = await this.readManifestAt(normalizedRoot);
    const now = new Date().toISOString();
    const manifest: TrainerWorkspaceManifest = {
      schemaVersion: 2,
      kind: 'trainer-workspace',
      rootPath: normalizedRoot,
      canonicalRootPath: normalizedRoot,
      rootId: existingManifest?.rootId,
      legacyRootPaths: existingManifest?.legacyRootPaths ?? [],
      manifestRevision: (existingManifest?.manifestRevision ?? 0) + 1,
      pathRevision: existingManifest?.pathRevision ?? 0,
      identityStatus: existingManifest?.identityStatus ?? 'pending',
      createdAt: existingManifest?.createdAt ?? now,
      updatedAt: now,
      directories: [...TRAINER_WORKSPACE_DIRECTORIES],
      projects: this.mergeProjectStatesForRoot(
        normalizedRoot,
        existingManifest?.projects ?? {},
        this.readProjectRegistry(),
      ),
    };

    await this.writeManifestAt(normalizedRoot, manifest);
    await this.extensionContext.globalState.update(TRAINER_WORKSPACE_ROOT_STORAGE_KEY, normalizedRoot);
    return manifest;
  }

  async selectRoot(rootPath: string): Promise<TrainerWorkspaceManifest> {
    return this.saveWorkspaceRoot(rootPath);
  }

  async setRootIdentity(rootId: string, canonicalRootPath: string): Promise<TrainerWorkspaceManifest> {
    const rootPath = normalizeRequiredDirectoryPath(canonicalRootPath);
    const manifest = await this.readManifestAt(rootPath);
    if (!manifest) {
      throw new Error('Trainer workspace manifest is unavailable for the registered root.');
    }
    const updated: TrainerWorkspaceManifest = {
      ...manifest,
      rootPath,
      canonicalRootPath: rootPath,
      rootId,
      identityStatus: 'verified',
      manifestRevision: manifest.manifestRevision + 1,
      updatedAt: new Date().toISOString(),
    };
    await this.writeManifestAt(rootPath, updated);
    await this.extensionContext.globalState.update(TRAINER_WORKSPACE_ROOT_STORAGE_KEY, rootPath);
    return updated;
  }

  async migrateWorkspaceRoot(
    targetPath: string,
    options: TrainerWorkspaceRecoveryOptions = {},
  ): Promise<TrainerWorkspaceRootTransfer> {
    const { rootPath: sourceRoot, manifest } = await this.requireActiveWorkspace();
    const targetRoot = normalizeRequiredDirectoryPath(targetPath);
    this.assertSafeTransferTarget(sourceRoot, targetRoot, 'migrate');
    const runtimeData = await this.prepareRuntimeDataSnapshot(sourceRoot, options.managedDataRoot);
    this.assertSafeTransferTarget(runtimeData.sourceRoot, targetRoot, 'migrate');
    await this.ensureEmptyTargetDirectory(targetRoot);

    const prepared = await this.copyAndPrepareActiveWorkspace(
      sourceRoot,
      sourceRoot,
      targetRoot,
      manifest,
      false,
      runtimeData,
    );
    return this.activateCopiedWorkspace(
      sourceRoot,
      targetRoot,
      prepared.manifest,
      prepared.completedAt,
      runtimeData.relativePath,
    );
  }

  async backupWorkspace(
    backupPath: string,
    options: TrainerWorkspaceRecoveryOptions = {},
  ): Promise<TrainerWorkspaceBackup> {
    const { rootPath: sourceRoot, manifest } = await this.requireActiveWorkspace();
    const backupRoot = normalizeRequiredDirectoryPath(backupPath);
    this.assertSafeTransferTarget(sourceRoot, backupRoot, 'back up');
    const runtimeData = await this.prepareRuntimeDataSnapshot(sourceRoot, options.managedDataRoot);
    this.assertSafeTransferTarget(runtimeData.sourceRoot, backupRoot, 'back up');
    await this.ensureEmptyTargetDirectory(backupRoot);

    const createdAt = new Date().toISOString();
    const backupManifest: TrainerWorkspaceBackupManifest = {
      schemaVersion: 1,
      kind: 'trainer-workspace-backup',
      sourceRoot,
      createdAt,
      workspaceManifest: manifest,
      runtimeData: { relativePath: runtimeData.relativePath },
    };
    await this.copyWorkspaceIntoTarget(sourceRoot, backupRoot, async (stagingRoot) => {
      await this.materializeRuntimeDataSnapshot(stagingRoot, runtimeData);
      await this.writeJsonAtomically(
        path.join(stagingRoot, TRAINER_WORKSPACE_BACKUP_FILE),
        backupManifest,
      );
    });
    return {
      backupRoot,
      sourceRoot,
      projectCount: Object.keys(manifest.projects).length,
      createdAt,
      managedDataRoot: path.join(backupRoot, runtimeData.relativePath),
    };
  }

  async restoreWorkspaceBackup(
    backupPath: string,
    targetPath: string,
  ): Promise<TrainerWorkspaceRootTransfer> {
    const backupRoot = normalizeRequiredDirectoryPath(backupPath);
    const targetRoot = normalizeRequiredDirectoryPath(targetPath);
    this.assertSafeTransferTarget(backupRoot, targetRoot, 'restore');
    const backupManifest = await this.readBackupAt(backupRoot);
    if (!backupManifest.runtimeData) {
      throw new Error(
        'Trainer workspace backup does not include the runtime data required for a complete restore.',
      );
    }
    await this.ensureEmptyTargetDirectory(targetRoot);

    const prepared = await this.copyAndPrepareActiveWorkspace(
      backupRoot,
      backupManifest.sourceRoot,
      targetRoot,
      backupManifest.workspaceManifest,
      true,
    );
    return this.activateCopiedWorkspace(
      backupManifest.sourceRoot,
      targetRoot,
      prepared.manifest,
      prepared.completedAt,
      backupManifest.runtimeData?.relativePath,
    );
  }

  async rollbackWorkspaceRoot(rootPath?: string): Promise<void> {
    if (rootPath) {
      await this.selectRoot(rootPath);
      return;
    }

    const activeRoot = this.getWorkspaceRoot();
    const registry = this.readProjectRegistry();
    if (activeRoot) {
      for (const [fingerprint, project] of Object.entries(registry)) {
        if (pathsEqual(project.workspaceRoot, activeRoot)) {
          delete registry[fingerprint];
        }
      }
    }
    await this.extensionContext.globalState.update(TRAINER_WORKSPACE_PROJECTS_STORAGE_KEY, registry);
    await this.extensionContext.globalState.update(TRAINER_WORKSPACE_ROOT_STORAGE_KEY, undefined);
  }

  async createWorkspaceScaffold(rootPath: string): Promise<void> {
    const normalizedRoot = normalizeRequiredDirectoryPath(rootPath);
    await fs.mkdir(normalizedRoot, { recursive: true });
    await Promise.all(
      TRAINER_WORKSPACE_DIRECTORIES.map((directory) =>
        fs.mkdir(path.join(normalizedRoot, directory), { recursive: true }),
      ),
    );
  }

  async hasWorkspaceScaffold(rootPath = this.getWorkspaceRoot()): Promise<boolean> {
    if (!rootPath) {
      return false;
    }

    const normalizedRoot = normalizeOptionalDirectoryPath(rootPath);
    if (!normalizedRoot || !(await this.isDirectory(normalizedRoot))) {
      return false;
    }

    const checks = await Promise.all(
      TRAINER_WORKSPACE_DIRECTORIES.map((directory) => this.isDirectory(path.join(normalizedRoot, directory))),
    );
    return checks.every(Boolean);
  }

  async readWorkspaceManifest(): Promise<TrainerWorkspaceManifest | undefined> {
    const rootPath = this.getWorkspaceRoot();
    if (!rootPath) {
      return undefined;
    }
    return this.readManifestAt(rootPath);
  }

  async getProjectState(projectPath: string): Promise<TrainerWorkspaceProjectState | undefined> {
    const rootPath = this.getWorkspaceRoot();
    const normalizedProjectPath = normalizeOptionalDirectoryPath(projectPath);
    if (!rootPath || !normalizedProjectPath || !(await this.hasWorkspaceScaffold(rootPath))) {
      return undefined;
    }
    if (!(await this.isDirectory(normalizedProjectPath))) {
      return undefined;
    }

    const manifest = await this.readManifestAt(rootPath);
    if (!manifest) {
      return undefined;
    }
    const state = this.findProjectStateForPath(
      [...Object.values(this.readProjectRegistry()), ...Object.values(manifest.projects)],
      rootPath,
      normalizedProjectPath,
    );
    if (!state) {
      return undefined;
    }
    return { ...state };
  }

  async getProject(projectPath: string): Promise<TrainerWorkspaceProjectState | undefined> {
    return this.getProjectState(projectPath);
  }

  async setProjectAdoption(
    projectPath: string,
    adoptionMode: TrainerProjectAdoptionMode,
    managedIdentity?: TrainerManagedProjectIdentity,
  ): Promise<TrainerWorkspaceProjectState> {
    if (!isAdoptionMode(adoptionMode)) {
      throw new Error(`Unsupported Trainer project adoption mode: ${String(adoptionMode)}.`);
    }

    const rootPath = this.getWorkspaceRoot();
    if (!rootPath || !(await this.hasWorkspaceScaffold(rootPath))) {
      throw new Error('Configure a valid Trainer workspace root before registering a project.');
    }

    const manifest = await this.readManifestAt(rootPath);
    if (!manifest) {
      throw new Error('The configured Trainer workspace does not have a workspace manifest.');
    }

    const normalizedProjectPath = normalizeRequiredDirectoryPath(projectPath);
    if (!(await this.isDirectory(normalizedProjectPath))) {
      throw new Error(`Trainer project directory does not exist: ${normalizedProjectPath}`);
    }

    const rawIdentity = managedIdentity as unknown;
    let identity: TrainerManagedProjectIdentity | undefined;
    try {
      identity = adoptionMode === 'managed'
        ? normalizeManagedProjectIdentity(rawIdentity, normalizedProjectPath, rootPath)
        : undefined;
      const registry = this.readProjectRegistry();
      const existing = this.findProjectStateForIdentityOrPath(
        [...Object.values(manifest.projects), ...Object.values(registry)],
        rootPath,
        normalizedProjectPath,
        identity,
      );
      if (adoptionMode !== 'managed' && existing?.adoptionMode === 'managed') {
        throw new Error(
          'This project is already managed by Trainer and cannot be changed to browse or ignored locally.',
        );
      }
      if (identity) {
        this.assertManagedIdentityCompatible(manifest, existing, identity);
      }

      const updatedAt = new Date().toISOString();
      const projectPathChanged = Boolean(
        existing && !pathsEqual(existing.canonicalProjectPath, normalizedProjectPath),
      );
      const state: TrainerWorkspaceProjectState = {
        fingerprint: fingerprintTrainerProjectPath(normalizedProjectPath),
        projectPath: normalizedProjectPath,
        workspaceRoot: rootPath,
        adoptionMode,
        projectLanePath: existing?.projectLanePath,
        rootId: identity?.rootId ?? existing?.rootId,
        projectId: identity?.projectId ?? existing?.projectId,
        contextId: identity?.contextId ?? existing?.contextId,
        canonicalProjectPath: identity?.canonicalProjectPath ?? normalizedProjectPath,
        legacyAliases: this.mergeLegacyAliases(existing, identity, projectPathChanged),
        manifestRevision: (existing?.manifestRevision ?? 0) + 1,
        pathRevision: (existing?.pathRevision ?? 0) + (projectPathChanged ? 1 : 0),
        identityStatus: identity
          ? identityRequiresReconciliation(identity)
            ? 'reconcile-required'
            : 'verified'
          : existing?.identityStatus ?? 'pending',
        serverRevisions: identity?.revisions ?? existing?.serverRevisions,
        reconcile: identity?.reconcile ?? existing?.reconcile,
        updatedAt,
      };
      if (adoptionMode === 'managed') {
        state.projectLanePath = await this.createManagedProjectLane(rootPath, state);
      }

      this.removeMatchingProjectStates(registry, rootPath, normalizedProjectPath, identity);
      registry[state.fingerprint] = state;
      const manifestProjects = { ...manifest.projects };
      this.removeMatchingProjectStates(manifestProjects, rootPath, normalizedProjectPath, identity);
      const nextManifest: TrainerWorkspaceManifest = {
        ...manifest,
        rootId: identity?.rootId ?? manifest.rootId,
        canonicalRootPath: rootPath,
        manifestRevision: manifest.manifestRevision + 1,
        identityStatus: identity
          ? identityRequiresReconciliation(identity)
            ? 'reconcile-required'
            : 'verified'
          : manifest.identityStatus,
        updatedAt,
        directories: [...TRAINER_WORKSPACE_DIRECTORIES],
        projects: this.mergeProjectStatesForRoot(rootPath, manifestProjects, registry),
      };

      let manifestWritten = false;
      try {
        await this.writeManifestAt(rootPath, nextManifest);
        manifestWritten = true;
        await this.extensionContext.globalState.update(TRAINER_WORKSPACE_PROJECTS_STORAGE_KEY, registry);
      } catch (error) {
        if (manifestWritten) {
          await this.writeManifestAt(rootPath, manifest).catch(() => undefined);
        }
        try {
          await this.extensionContext.globalState.update(
            TRAINER_WORKSPACE_PROJECTS_STORAGE_KEY,
            this.readProjectRegistry(),
          );
        } catch {
          // The original persistence failure remains the actionable error.
        }
        throw error;
      }
      await this.clearPendingReconciliation(normalizedProjectPath).catch(() => undefined);
      return { ...state };
    } catch (error) {
      if (adoptionMode === 'managed') {
        await this.recordManagedProvisioningPending(
          normalizedProjectPath,
          error instanceof Error ? error.message : String(error),
          { identity: rawIdentity },
        ).catch(() => undefined);
      }
      throw error;
    }
  }

  async setProjectAdmission(
    projectPath: string,
    adoptionMode: TrainerProjectAdoptionMode,
    managedIdentity?: TrainerManagedProjectIdentity,
  ): Promise<TrainerWorkspaceProjectState> {
    return this.setProjectAdoption(projectPath, adoptionMode, managedIdentity);
  }

  async deleteManagedProject(projectPath: string): Promise<TrainerWorkspaceProjectState> {
    const rootPath = this.getWorkspaceRoot();
    if (!rootPath || !(await this.hasWorkspaceScaffold(rootPath))) {
      throw new Error('Configure a valid Trainer workspace root before deleting a project.');
    }

    const manifest = await this.readManifestAt(rootPath);
    if (!manifest) {
      throw new Error('The configured Trainer workspace does not have a workspace manifest.');
    }

    const normalizedProjectPath = normalizeRequiredDirectoryPath(projectPath);
    const existing = this.findProjectStateForPath(
      [...Object.values(manifest.projects), ...Object.values(this.readProjectRegistry())],
      rootPath,
      normalizedProjectPath,
    );
    if (!existing) {
      throw new Error('This folder is not a Trainer project.');
    }
    if (existing.adoptionMode !== 'managed') {
      throw new Error(
        'Only managed Trainer projects can be deleted. Use ignore for folders that were never added.',
      );
    }

    const identity =
      existing.rootId && existing.projectId && existing.contextId
        ? {
            rootId: existing.rootId,
            projectId: existing.projectId,
            contextId: existing.contextId,
            canonicalProjectPath: existing.canonicalProjectPath,
            legacyAliases: existing.legacyAliases,
          }
        : undefined;
    const registry = this.readProjectRegistry();
    this.removeMatchingProjectStates(registry, rootPath, normalizedProjectPath, identity);
    const manifestProjects = { ...manifest.projects };
    this.removeMatchingProjectStates(manifestProjects, rootPath, normalizedProjectPath, identity);

    const updatedAt = new Date().toISOString();
    const nextManifest: TrainerWorkspaceManifest = {
      ...manifest,
      manifestRevision: manifest.manifestRevision + 1,
      updatedAt,
      directories: [...TRAINER_WORKSPACE_DIRECTORIES],
      projects: this.mergeProjectStatesForRoot(rootPath, manifestProjects, registry),
    };

    let manifestWritten = false;
    try {
      await this.writeManifestAt(rootPath, nextManifest);
      manifestWritten = true;
      await this.extensionContext.globalState.update(TRAINER_WORKSPACE_PROJECTS_STORAGE_KEY, registry);
    } catch (error) {
      if (manifestWritten) {
        await this.writeManifestAt(rootPath, manifest).catch(() => undefined);
      }
      try {
        await this.extensionContext.globalState.update(
          TRAINER_WORKSPACE_PROJECTS_STORAGE_KEY,
          this.readProjectRegistry(),
        );
      } catch {
        // The original persistence failure remains the actionable error.
      }
      throw error;
    }
    await this.clearPendingReconciliation(normalizedProjectPath).catch(() => undefined);
    return { ...existing };
  }

  async recordManagedProvisioningPending(
    projectPath: string,
    reason: string,
    input: TrainerWorkspacePendingReconciliationInput = {},
  ): Promise<void> {
    const rootPath = this.getWorkspaceRoot();
    const normalizedProjectPath = normalizeRequiredDirectoryPath(projectPath);
    if (!rootPath) {
      return;
    }
    let normalizedIdentity: TrainerManagedProjectIdentity | undefined;
    try {
      normalizedIdentity = input.identity
        ? normalizeManagedProjectIdentity(input.identity, normalizedProjectPath, rootPath)
        : undefined;
    } catch {
      // A malformed server response is retained as a pending reconciliation without copied IDs.
    }
    const jobId = isSafeIdentity(input.jobId) ? input.jobId : undefined;
    const state = isPendingReconciliationState(input.state) ? input.state : 'retry-required';
    const pending = this.readPendingReconciliations();
    pending[fingerprintTrainerProjectPath(normalizedProjectPath)] = {
      projectPath: normalizedProjectPath,
      workspaceRoot: rootPath,
      reason: reason.trim() || 'Managed project provisioning needs reconciliation.',
      jobId,
      state,
      availableActions: resolvePendingReconciliationActions(state, jobId),
      updatedAt: new Date().toISOString(),
      identity: normalizedIdentity,
    };
    await this.extensionContext.globalState.update(
      TRAINER_WORKSPACE_PENDING_RECONCILIATIONS_STORAGE_KEY,
      pending,
    );
  }

  getManagedProvisioningPending(projectPath: string): TrainerWorkspacePendingReconciliation | undefined {
    const normalizedProjectPath = normalizeOptionalDirectoryPath(projectPath);
    const rootPath = this.getWorkspaceRoot();
    if (!normalizedProjectPath || !rootPath) {
      return undefined;
    }
    const pending = this.readPendingReconciliations()[fingerprintTrainerProjectPath(normalizedProjectPath)];
    if (!pending || !pathsEqual(pending.workspaceRoot, rootPath)) {
      return undefined;
    }
    return {
      ...pending,
      availableActions: [...pending.availableActions],
      identity: pending.identity ? { ...pending.identity } : undefined,
    };
  }

  async abandonManagedProvisioning(projectPath: string): Promise<void> {
    await this.clearPendingReconciliation(projectPath);
  }

  async toSnapshot(currentWorkspacePath?: string): Promise<TrainerWorkspaceSnapshot> {
    const rootPath = this.getWorkspaceRoot();
    if (!rootPath || !(await this.hasWorkspaceScaffold(rootPath))) {
      return { rootPath, workspaceReady: false };
    }

    const manifest = await this.readManifestAt(rootPath);
    if (!manifest) {
      return { rootPath, workspaceReady: false };
    }

    const currentProject = currentWorkspacePath
      ? await this.getProjectState(currentWorkspacePath)
      : undefined;
    return {
      rootPath,
      workspaceReady: true,
      manifest,
      currentProject,
    };
  }

  private findProjectStateForPath(
    states: readonly TrainerWorkspaceProjectState[],
    rootPath: string,
    projectPath: string,
  ): TrainerWorkspaceProjectState | undefined {
    let matched: TrainerWorkspaceProjectState | undefined;
    for (const state of states) {
      if (this.matchesCurrentProject(state, rootPath, projectPath)) {
        matched = chooseNewestProjectState(matched, state);
      }
    }
    return matched;
  }

  private findProjectStateForIdentityOrPath(
    states: readonly TrainerWorkspaceProjectState[],
    rootPath: string,
    projectPath: string,
    identity?: TrainerManagedProjectIdentity,
  ): TrainerWorkspaceProjectState | undefined {
    let matched = this.findProjectStateForPath(states, rootPath, projectPath);
    if (!identity) {
      return matched;
    }
    for (const state of states) {
      if (pathsEqual(state.workspaceRoot, rootPath) && state.projectId === identity.projectId) {
        matched = chooseNewestProjectState(matched, state);
      }
    }
    return matched;
  }

  private assertManagedIdentityCompatible(
    manifest: TrainerWorkspaceManifest,
    existing: TrainerWorkspaceProjectState | undefined,
    identity: TrainerManagedProjectIdentity,
  ): void {
    if (manifest.rootId && manifest.rootId !== identity.rootId) {
      throw new Error('Trainer backend identity belongs to a different workspace root.');
    }
    if (existing?.rootId && existing.rootId !== identity.rootId) {
      throw new Error('Trainer backend identity does not match the existing project root.');
    }
    if (existing?.projectId && existing.projectId !== identity.projectId) {
      throw new Error('Trainer backend identity would replace an immutable project ID.');
    }
    if (existing?.contextId && existing.contextId !== identity.contextId) {
      throw new Error('Trainer backend identity would replace an immutable context ID.');
    }
  }

  private mergeLegacyAliases(
    existing: TrainerWorkspaceProjectState | undefined,
    identity: TrainerManagedProjectIdentity | undefined,
    projectPathChanged: boolean,
  ): string[] {
    const aliases = [
      ...(existing?.legacyAliases ?? []),
      ...(identity?.legacyAliases ?? []),
      ...(projectPathChanged && existing ? [existing.canonicalProjectPath] : []),
    ];
    return [...new Set(aliases.filter(Boolean))].slice(-32);
  }

  private removeMatchingProjectStates(
    registry: TrainerWorkspaceProjectRegistry,
    rootPath: string,
    projectPath: string,
    identity?: TrainerManagedProjectIdentity,
  ): void {
    for (const [fingerprint, state] of Object.entries(registry)) {
      if (!pathsEqual(state.workspaceRoot, rootPath)) {
        continue;
      }
      if (
        pathsEqual(state.projectPath, projectPath) ||
        pathsEqual(state.canonicalProjectPath, projectPath) ||
        (identity && state.projectId === identity.projectId)
      ) {
        delete registry[fingerprint];
      }
    }
  }

  private readPendingReconciliations(): TrainerWorkspacePendingReconciliationRegistry {
    const raw = this.extensionContext.globalState.get<unknown>(
      TRAINER_WORKSPACE_PENDING_RECONCILIATIONS_STORAGE_KEY,
    );
    if (!isRecord(raw)) {
      return {};
    }
    const pending: TrainerWorkspacePendingReconciliationRegistry = {};
    for (const [fingerprint, value] of Object.entries(raw)) {
      if (!isRecord(value) || typeof value.projectPath !== 'string' || typeof value.workspaceRoot !== 'string') {
        continue;
      }
      const projectPath = normalizeOptionalDirectoryPath(value.projectPath);
      const workspaceRoot = normalizeOptionalDirectoryPath(value.workspaceRoot);
      if (!projectPath || !workspaceRoot || fingerprint !== fingerprintTrainerProjectPath(projectPath)) {
        continue;
      }
      let identity: TrainerManagedProjectIdentity | undefined;
      try {
        identity = value.identity
          ? normalizeManagedProjectIdentity(value.identity, projectPath, workspaceRoot)
          : undefined;
      } catch {
        identity = undefined;
      }
      const jobId = isSafeIdentity(value.jobId) ? value.jobId : undefined;
      const state = isPendingReconciliationState(value.state) ? value.state : 'retry-required';
      pending[fingerprint] = {
        projectPath,
        workspaceRoot,
        reason: typeof value.reason === 'string' ? value.reason : 'Managed project provisioning needs reconciliation.',
        jobId,
        state,
        availableActions: resolvePendingReconciliationActions(state, jobId),
        updatedAt: typeof value.updatedAt === 'string' ? value.updatedAt : new Date(0).toISOString(),
        identity,
      };
    }
    return pending;
  }

  private async clearPendingReconciliation(projectPath: string): Promise<void> {
    const pending = this.readPendingReconciliations();
    const fingerprint = fingerprintTrainerProjectPath(projectPath);
    if (!(fingerprint in pending)) {
      return;
    }
    delete pending[fingerprint];
    await this.extensionContext.globalState.update(
      TRAINER_WORKSPACE_PENDING_RECONCILIATIONS_STORAGE_KEY,
      pending,
    );
  }

  private async requireActiveWorkspace(): Promise<{
    rootPath: string;
    manifest: TrainerWorkspaceManifest;
  }> {
    const rootPath = this.getWorkspaceRoot();
    if (!rootPath || !(await this.hasWorkspaceScaffold(rootPath))) {
      throw new Error('Configure a valid Trainer workspace root before using workspace recovery.');
    }

    const manifest = await this.readManifestAt(rootPath);
    if (!manifest) {
      throw new Error('The configured Trainer workspace does not have a workspace manifest.');
    }
    return { rootPath, manifest };
  }

  private assertSafeTransferTarget(sourceRoot: string, targetRoot: string, action: string): void {
    if (pathsEqual(sourceRoot, targetRoot)) {
      throw new Error(`Cannot ${action} a Trainer workspace onto itself.`);
    }
    if (pathContains(sourceRoot, targetRoot) || pathContains(targetRoot, sourceRoot)) {
      throw new Error(`Cannot ${action} a Trainer workspace into a nested directory.`);
    }
  }

  private async ensureEmptyTargetDirectory(targetRoot: string): Promise<void> {
    try {
      const targetStat = await fs.stat(targetRoot);
      if (!targetStat.isDirectory()) {
        throw new Error(`Trainer workspace target is not a directory: ${targetRoot}`);
      }
      const entries = await fs.readdir(targetRoot);
      if (entries.length > 0) {
        throw new Error(`Trainer workspace target must be empty: ${targetRoot}`);
      }
    } catch (error) {
      if (isNotFoundError(error)) {
        return;
      }
      throw error;
    }
  }

  private async prepareRuntimeDataSnapshot(
    workspaceRoot: string,
    managedDataRoot?: string,
  ): Promise<ResolvedRuntimeDataSnapshot> {
    const sourceRoot = managedDataRoot
      ? normalizeRequiredDirectoryPath(managedDataRoot)
      : path.join(workspaceRoot, TRAINER_WORKSPACE_RUNTIME_DATA_DIRECTORY);
    if (managedDataRoot) {
      if (!(await this.isDirectory(sourceRoot))) {
        throw new Error(`Trainer managed data directory does not exist: ${sourceRoot}`);
      }
    } else {
      await fs.mkdir(sourceRoot, { recursive: true });
    }

    const relative = path.relative(workspaceRoot, sourceRoot);
    const isOutsideWorkspaceRoot =
      Boolean(relative) && (relative.startsWith(`..${path.sep}`) || relative === '..' || path.isAbsolute(relative));
    const relativePath = isOutsideWorkspaceRoot
      ? TRAINER_WORKSPACE_RUNTIME_DATA_DIRECTORY
      : relative
        ? relative.split(path.sep).join('/')
        : '.';

    if (isOutsideWorkspaceRoot) {
      await this.assertExternalRuntimeDataRootSafe(sourceRoot);
    } else {
      await this.assertWorkspaceRuntimeDataRootSafe(workspaceRoot, sourceRoot);
    }

    return {
      sourceRoot,
      relativePath,
      isOutsideWorkspaceRoot,
    };
  }

  private async materializeRuntimeDataSnapshot(
    stagingRoot: string,
    runtimeData: ResolvedRuntimeDataSnapshot,
  ): Promise<void> {
    if (!runtimeData.isOutsideWorkspaceRoot) {
      return;
    }

    const targetRoot = this.resolveRuntimeDataPath(stagingRoot, runtimeData.relativePath);
    await this.assertRuntimeDestinationSafe(stagingRoot, targetRoot);
    await fs.rm(targetRoot, { recursive: true, force: true });
    await fs.mkdir(path.dirname(targetRoot), { recursive: true });
    await fs.cp(runtimeData.sourceRoot, targetRoot, {
      recursive: true,
      force: false,
      errorOnExist: true,
    });
  }

  private resolveRuntimeDataPath(rootPath: string, relativePath: string): string {
    const normalizedRelativePath = relativePath.trim();
    if (!normalizedRelativePath) {
      throw new Error('Trainer runtime data path is required.');
    }
    const resolvedPath = path.resolve(rootPath, normalizedRelativePath);
    if (!pathsEqual(resolvedPath, rootPath) && !pathContains(rootPath, resolvedPath)) {
      throw new Error('Trainer runtime data path must stay inside the workspace snapshot.');
    }
    return resolvedPath;
  }

  private async assertWorkspaceRuntimeDataRootSafe(
    workspaceRoot: string,
    runtimeDataRoot: string,
  ): Promise<void> {
    const normalizedWorkspaceRoot = path.resolve(workspaceRoot);
    const normalizedRuntimeDataRoot = path.resolve(runtimeDataRoot);
    await this.assertRuntimeDestinationSafe(normalizedWorkspaceRoot, normalizedRuntimeDataRoot);
    await this.assertNoSymbolicLinksInDirectory(normalizedRuntimeDataRoot);
  }

  private async assertExternalRuntimeDataRootSafe(runtimeDataRoot: string): Promise<void> {
    const normalizedRuntimeDataRoot = path.resolve(runtimeDataRoot);
    const metadata = await fs.lstat(normalizedRuntimeDataRoot);
    if (metadata.isSymbolicLink()) {
      throw new Error('Trainer managed data directory cannot be a symbolic link or junction.');
    }
    const resolvedRuntimeDataRoot = await fs.realpath(normalizedRuntimeDataRoot);
    if (!pathsEqual(resolvedRuntimeDataRoot, normalizedRuntimeDataRoot)) {
      throw new Error('Trainer managed data directory must not resolve through a symbolic link or junction.');
    }
    await this.assertNoSymbolicLinksInDirectory(normalizedRuntimeDataRoot);
  }

  private async assertRuntimeDestinationSafe(rootPath: string, runtimeDataPath: string): Promise<void> {
    const normalizedRootPath = path.resolve(rootPath);
    const normalizedRuntimeDataPath = path.resolve(runtimeDataPath);
    if (
      !pathsEqual(normalizedRootPath, normalizedRuntimeDataPath) &&
      !pathContains(normalizedRootPath, normalizedRuntimeDataPath)
    ) {
      throw new Error('Trainer runtime data path must stay inside the workspace snapshot.');
    }

    const relativePath = path.relative(normalizedRootPath, normalizedRuntimeDataPath);
    const segments = relativePath && relativePath !== '.' ? relativePath.split(path.sep) : [];
    let currentPath = normalizedRootPath;
    for (const segment of ['', ...segments]) {
      if (segment) {
        currentPath = path.join(currentPath, segment);
      }
      try {
        const metadata = await fs.lstat(currentPath);
        if (metadata.isSymbolicLink()) {
          throw new Error('Trainer runtime data path cannot pass through a symbolic link or junction.');
        }
      } catch (error) {
        if (isNotFoundError(error)) {
          break;
        }
        throw error;
      }
    }

    const realRootPath = await fs.realpath(normalizedRootPath);
    const existingRuntimeDataPath = await this.findNearestExistingPath(normalizedRuntimeDataPath);
    const realExistingRuntimeDataPath = await fs.realpath(existingRuntimeDataPath);
    if (
      !pathsEqual(realRootPath, realExistingRuntimeDataPath) &&
      !pathContains(realRootPath, realExistingRuntimeDataPath)
    ) {
      throw new Error('Trainer runtime data path resolves outside the workspace snapshot.');
    }
  }

  private async findNearestExistingPath(candidatePath: string): Promise<string> {
    let currentPath = candidatePath;
    while (!(await this.pathExists(currentPath))) {
      const parentPath = path.dirname(currentPath);
      if (pathsEqual(parentPath, currentPath)) {
        throw new Error(`Trainer path cannot be resolved: ${candidatePath}`);
      }
      currentPath = parentPath;
    }
    return currentPath;
  }

  private async assertNoSymbolicLinksInDirectory(directoryPath: string): Promise<void> {
    const pendingDirectories = [directoryPath];
    while (pendingDirectories.length > 0) {
      const currentDirectory = pendingDirectories.pop();
      if (!currentDirectory) {
        continue;
      }
      const entries = await fs.readdir(currentDirectory, { withFileTypes: true });
      for (const entry of entries) {
        const entryPath = path.join(currentDirectory, entry.name);
        const metadata = await fs.lstat(entryPath);
        if (metadata.isSymbolicLink()) {
          throw new Error('Trainer runtime data cannot contain symbolic links or junctions.');
        }
        if (metadata.isDirectory()) {
          pendingDirectories.push(entryPath);
        }
      }
    }
  }

  private async copyWorkspaceContents(sourceRoot: string, targetRoot: string): Promise<void> {
    const entries = await fs.readdir(sourceRoot);
    await fs.mkdir(targetRoot, { recursive: true });
    await Promise.all(
      entries.map((entry) =>
        fs.cp(path.join(sourceRoot, entry), path.join(targetRoot, entry), {
          recursive: true,
          force: false,
          errorOnExist: true,
        }),
      ),
    );
  }

  private async copyWorkspaceIntoTarget<T>(
    sourceRoot: string,
    targetRoot: string,
    prepare: (stagingRoot: string) => Promise<T>,
  ): Promise<T> {
    const stagingRoot = await this.createWorkspaceStagingDirectory(targetRoot);
    try {
      await this.copyWorkspaceContents(sourceRoot, stagingRoot);
      const prepared = await prepare(stagingRoot);
      await this.promoteWorkspaceStagingDirectory(stagingRoot, targetRoot);
      return prepared;
    } catch (error) {
      await fs.rm(stagingRoot, { recursive: true, force: true }).catch(() => undefined);
      throw error;
    }
  }

  private async copyAndPrepareActiveWorkspace(
    sourceContentsRoot: string,
    sourceRoot: string,
    targetRoot: string,
    sourceManifest: TrainerWorkspaceManifest,
    removeBackupMarker = false,
    runtimeData?: ResolvedRuntimeDataSnapshot,
  ): Promise<{ manifest: TrainerWorkspaceManifest; completedAt: string }> {
    return this.copyWorkspaceIntoTarget(sourceContentsRoot, targetRoot, async (stagingRoot) => {
      if (runtimeData) {
        await this.materializeRuntimeDataSnapshot(stagingRoot, runtimeData);
      }
      if (removeBackupMarker) {
        await fs.rm(path.join(stagingRoot, TRAINER_WORKSPACE_BACKUP_FILE), { force: true });
      }
      const completedAt = new Date().toISOString();
      const manifest = this.rebaseManifest(sourceManifest, sourceRoot, targetRoot, completedAt);
      await this.writeManifestAt(stagingRoot, manifest);
      await this.rebaseManagedProjectLaneManifests(manifest, completedAt, stagingRoot);
      return { manifest, completedAt };
    });
  }

  private async createWorkspaceStagingDirectory(targetRoot: string): Promise<string> {
    const parentDirectory = path.dirname(targetRoot);
    await fs.mkdir(parentDirectory, { recursive: true });
    return fs.mkdtemp(path.join(parentDirectory, `.${path.basename(targetRoot)}.trainer-stage-`));
  }

  private async promoteWorkspaceStagingDirectory(
    stagingRoot: string,
    targetRoot: string,
  ): Promise<void> {
    try {
      await fs.rmdir(targetRoot);
    } catch (error) {
      if (!isNotFoundError(error)) {
        throw error;
      }
    }
    await this.renameWithTransientWindowsRetry(stagingRoot, targetRoot);
  }

  private async renameWithTransientWindowsRetry(sourcePath: string, targetPath: string): Promise<void> {
    const maxAttempts = 4;
    for (let attempt = 1; ; attempt += 1) {
      try {
        await fs.rename(sourcePath, targetPath);
        return;
      } catch (error) {
        if (!isTransientWindowsRenameError(error) || attempt >= maxAttempts) {
          throw error;
        }
        await new Promise((resolve) => setTimeout(resolve, attempt * 25));
      }
    }
  }

  private async activateCopiedWorkspace(
    sourceRoot: string,
    targetRoot: string,
    manifest: TrainerWorkspaceManifest,
    completedAt: string,
    runtimeDataRelativePath?: string,
  ): Promise<TrainerWorkspaceRootTransfer> {
    const previousRoot = this.getWorkspaceRoot();
    const previousRegistry = this.readProjectRegistry();
    const registry = { ...previousRegistry };
    for (const [fingerprint, project] of Object.entries(registry)) {
      if (pathsEqual(project.workspaceRoot, sourceRoot)) {
        delete registry[fingerprint];
      }
    }
    Object.assign(registry, manifest.projects);
    try {
      await this.extensionContext.globalState.update(TRAINER_WORKSPACE_PROJECTS_STORAGE_KEY, registry);
      await this.extensionContext.globalState.update(TRAINER_WORKSPACE_ROOT_STORAGE_KEY, targetRoot);
    } catch (error) {
      try {
        await this.extensionContext.globalState.update(
          TRAINER_WORKSPACE_PROJECTS_STORAGE_KEY,
          previousRegistry,
        );
      } catch {
        // The original persistence failure remains the actionable error.
      }
      try {
        await this.extensionContext.globalState.update(TRAINER_WORKSPACE_ROOT_STORAGE_KEY, previousRoot);
      } catch {
        // The original persistence failure remains the actionable error.
      }
      throw error;
    }

    return {
      sourceRoot,
      targetRoot,
      projectCount: Object.keys(manifest.projects).length,
      completedAt,
      managedDataRoot: runtimeDataRelativePath
        ? path.join(targetRoot, runtimeDataRelativePath)
        : undefined,
    };
  }

  private rebaseManifest(
    sourceManifest: TrainerWorkspaceManifest,
    sourceRoot: string,
    targetRoot: string,
    updatedAt: string,
  ): TrainerWorkspaceManifest {
    const projects: TrainerWorkspaceProjectRegistry = {};
    for (const [fingerprint, project] of Object.entries(sourceManifest.projects)) {
      projects[fingerprint] = {
        ...project,
        workspaceRoot: targetRoot,
        manifestRevision: project.manifestRevision + 1,
        identityStatus: project.identityStatus === 'verified' ? 'reconcile-required' : project.identityStatus,
        reconcile:
          project.identityStatus === 'verified'
            ? { ...(project.reconcile ?? {}), root: { state: 'reconcile-required', rootPath: targetRoot } }
            : project.reconcile,
        projectLanePath: project.projectLanePath
          ? path.join(targetRoot, path.relative(sourceRoot, project.projectLanePath))
          : undefined,
      };
    }
    return {
      ...sourceManifest,
      rootPath: targetRoot,
      canonicalRootPath: targetRoot,
      legacyRootPaths: [...new Set([...sourceManifest.legacyRootPaths, sourceManifest.canonicalRootPath])]
        .filter((item) => !pathsEqual(item, targetRoot))
        .slice(-32),
      manifestRevision: sourceManifest.manifestRevision + 1,
      pathRevision: sourceManifest.pathRevision + 1,
      identityStatus:
        sourceManifest.identityStatus === 'verified' ? 'reconcile-required' : sourceManifest.identityStatus,
      updatedAt,
      directories: [...TRAINER_WORKSPACE_DIRECTORIES],
      projects,
    };
  }

  private async rebaseManagedProjectLaneManifests(
    manifest: TrainerWorkspaceManifest,
    updatedAt: string,
    physicalWorkspaceRoot: string,
  ): Promise<void> {
    await Promise.all(
      Object.values(manifest.projects)
        .filter((project) => project.adoptionMode === 'managed' && project.projectLanePath)
        .map(async (project) => {
          if (!project.projectLanePath) {
            return;
          }
          const lanePath = path.join(
            physicalWorkspaceRoot,
            path.relative(manifest.rootPath, project.projectLanePath),
          );
          await Promise.all(
            TRAINER_MANAGED_PROJECT_DIRECTORIES.map((directory) =>
              fs.mkdir(path.join(lanePath, directory), { recursive: true }),
            ),
          );
          const projectManifestPath = path.join(lanePath, 'project.json');
          const existingManifest = await this.readJsonRecord(projectManifestPath);
          await this.writeJsonAtomically(projectManifestPath, {
            ...existingManifest,
            schemaVersion: 2,
            kind: 'trainer-project',
            fingerprint: project.fingerprint,
            rootId: project.rootId,
            projectId: project.projectId,
            contextId: project.contextId,
            canonicalProjectPath: project.canonicalProjectPath,
            legacyAliases: project.legacyAliases,
            manifestRevision: project.manifestRevision,
            pathRevision: project.pathRevision,
            identityStatus: project.identityStatus,
            serverRevisions: project.serverRevisions,
            reconcile: project.reconcile,
            sourcePath: project.projectPath,
            workspaceRoot: manifest.rootPath,
            createdAt:
              typeof existingManifest.createdAt === 'string' ? existingManifest.createdAt : project.updatedAt,
            updatedAt,
            directories: [...TRAINER_MANAGED_PROJECT_DIRECTORIES],
          });
        }),
    );
  }

  private async readBackupAt(backupRoot: string): Promise<TrainerWorkspaceBackupManifest> {
    const backupPath = path.join(backupRoot, TRAINER_WORKSPACE_BACKUP_FILE);
    if (!(await this.hasWorkspaceScaffold(backupRoot))) {
      throw new Error(`Trainer workspace backup is incomplete: ${backupRoot}`);
    }
    const rawBackup = await this.readJsonRecord(backupPath);
    if (
      rawBackup.schemaVersion !== 1 ||
      rawBackup.kind !== 'trainer-workspace-backup' ||
      typeof rawBackup.sourceRoot !== 'string' ||
      typeof rawBackup.createdAt !== 'string' ||
      !isRecord(rawBackup.workspaceManifest)
    ) {
      throw new Error(`Trainer workspace backup has an invalid shape: ${backupPath}`);
    }

    const sourceRoot = normalizeOptionalDirectoryPath(rawBackup.sourceRoot);
    if (!sourceRoot) {
      throw new Error(`Trainer workspace backup has an invalid source root: ${backupPath}`);
    }
    const runtimeData = await this.parseRuntimeDataSnapshot(rawBackup.runtimeData, backupRoot, backupPath);
    return {
      schemaVersion: 1,
      kind: 'trainer-workspace-backup',
      sourceRoot,
      createdAt: rawBackup.createdAt,
      workspaceManifest: this.parseManifest(rawBackup.workspaceManifest, sourceRoot, backupPath),
      runtimeData,
    };
  }

  private async parseRuntimeDataSnapshot(
    value: unknown,
    backupRoot: string,
    backupPath: string,
  ): Promise<TrainerWorkspaceRuntimeDataSnapshot | undefined> {
    if (value === undefined) {
      return undefined;
    }
    if (!isRecord(value) || typeof value.relativePath !== 'string') {
      throw new Error(`Trainer workspace backup has an invalid runtime data record: ${backupPath}`);
    }
    const relativePath = value.relativePath.trim();
    const runtimeDataRoot = this.resolveRuntimeDataPath(backupRoot, relativePath);
    if (!(await this.isDirectory(runtimeDataRoot))) {
      throw new Error(`Trainer workspace backup is missing runtime data: ${backupPath}`);
    }
    await this.assertWorkspaceRuntimeDataRootSafe(backupRoot, runtimeDataRoot);
    return { relativePath };
  }

  private async readJsonRecord(filePath: string): Promise<Record<string, unknown>> {
    let content: string;
    try {
      content = await fs.readFile(filePath, 'utf8');
    } catch (error) {
      if (isNotFoundError(error)) {
        return {};
      }
      throw error;
    }
    try {
      const parsed = JSON.parse(content) as unknown;
      if (!isRecord(parsed)) {
        throw new Error(`Trainer workspace JSON has an invalid shape: ${filePath}`);
      }
      return parsed;
    } catch (error) {
      throw new Error(`Trainer workspace JSON is not valid: ${filePath}`, { cause: error });
    }
  }

  private async readManifestAt(rootPath: string): Promise<TrainerWorkspaceManifest | undefined> {
    const manifestPath = path.join(rootPath, TRAINER_WORKSPACE_MANIFEST_FILE);
    let content: string;
    try {
      content = await fs.readFile(manifestPath, 'utf8');
    } catch (error) {
      if (isNotFoundError(error)) {
        return undefined;
      }
      throw error;
    }

    let parsed: unknown;
    try {
      parsed = JSON.parse(content) as unknown;
    } catch (error) {
      throw new Error(`Trainer workspace manifest is not valid JSON: ${manifestPath}`, { cause: error });
    }
    return this.parseManifest(parsed, rootPath, manifestPath);
  }

  private parseManifest(
    value: unknown,
    expectedRootPath: string,
    manifestPath: string,
  ): TrainerWorkspaceManifest {
    if (!isRecord(value)) {
      throw new Error(`Trainer workspace manifest has an invalid shape: ${manifestPath}`);
    }
    if (
      value.kind !== 'trainer-workspace' ||
      typeof value.rootPath !== 'string' ||
      typeof value.createdAt !== 'string' ||
      typeof value.updatedAt !== 'string' ||
      !Array.isArray(value.directories) ||
      !isRecord(value.projects)
    ) {
      throw new Error(`Trainer workspace manifest has an invalid shape: ${manifestPath}`);
    }

    const rootPath = normalizeOptionalDirectoryPath(value.rootPath);
    if (!rootPath || !pathsEqual(rootPath, expectedRootPath)) {
      throw new Error(`Trainer workspace manifest belongs to a different root: ${manifestPath}`);
    }

    const projects: TrainerWorkspaceProjectRegistry = {};
    for (const [fingerprint, rawState] of Object.entries(value.projects)) {
      const state = this.normalizeProjectState(rawState);
      if (!state || state.fingerprint !== fingerprint || !pathsEqual(state.workspaceRoot, rootPath)) {
        throw new Error(`Trainer workspace manifest has an invalid project record: ${manifestPath}`);
      }
      projects[fingerprint] = state;
    }

    if (value.schemaVersion === 1) {
      return {
        schemaVersion: 2,
        kind: 'trainer-workspace',
        rootPath,
        canonicalRootPath: rootPath,
        legacyRootPaths: [],
        manifestRevision: 1,
        pathRevision: 0,
        identityStatus: Object.values(projects).some((project) => project.adoptionMode === 'managed')
          ? 'reconcile-required'
          : 'pending',
        createdAt: value.createdAt,
        updatedAt: value.updatedAt,
        directories: value.directories.filter((directory): directory is string => typeof directory === 'string'),
        projects,
      };
    }
    const manifestRevision = normalizeRevision(value.manifestRevision, -1);
    const pathRevision = normalizeRevision(value.pathRevision, -1);
    if (
      value.schemaVersion !== 2 ||
      typeof value.canonicalRootPath !== 'string' ||
      !Array.isArray(value.legacyRootPaths) ||
      !isIdentityStatus(value.identityStatus) ||
      manifestRevision < 1 ||
      pathRevision < 0 ||
      (value.rootId !== undefined && !isSafeIdentity(value.rootId))
    ) {
      throw new Error(`Trainer workspace manifest has an invalid v2 shape: ${manifestPath}`);
    }
    const canonicalRootPath = normalizeOptionalDirectoryPath(value.canonicalRootPath);
    if (!canonicalRootPath || !pathsEqual(canonicalRootPath, rootPath)) {
      throw new Error(`Trainer workspace manifest has an invalid canonical root: ${manifestPath}`);
    }

    return {
      schemaVersion: 2,
      kind: 'trainer-workspace',
      rootPath,
      canonicalRootPath,
      rootId: value.rootId,
      legacyRootPaths: normalizeStringList(value.legacyRootPaths)
        .map(normalizeOptionalDirectoryPath)
        .filter((candidate): candidate is string => Boolean(candidate && !pathsEqual(candidate, rootPath)))
        .slice(-32),
      manifestRevision,
      pathRevision,
      identityStatus:
        value.rootId && value.identityStatus === 'verified'
          ? 'verified'
          : value.identityStatus === 'verified'
            ? 'reconcile-required'
            : value.identityStatus,
      createdAt: value.createdAt,
      updatedAt: value.updatedAt,
      directories: value.directories.filter((directory): directory is string => typeof directory === 'string'),
      projects,
    };
  }

  private readProjectRegistry(): TrainerWorkspaceProjectRegistry {
    const rawRegistry = this.extensionContext.globalState.get<unknown>(
      TRAINER_WORKSPACE_PROJECTS_STORAGE_KEY,
    );
    if (!isRecord(rawRegistry)) {
      return {};
    }

    const registry: TrainerWorkspaceProjectRegistry = {};
    for (const [fingerprint, rawState] of Object.entries(rawRegistry)) {
      const state = this.normalizeProjectState(rawState);
      if (state && state.fingerprint === fingerprint) {
        registry[fingerprint] = state;
      }
    }
    return registry;
  }

  private normalizeProjectState(value: unknown): TrainerWorkspaceProjectState | undefined {
    if (!isRecord(value)) {
      return undefined;
    }
    if (
      typeof value.fingerprint !== 'string' ||
      typeof value.projectPath !== 'string' ||
      typeof value.workspaceRoot !== 'string' ||
      !isAdoptionMode(value.adoptionMode) ||
      typeof value.updatedAt !== 'string'
    ) {
      return undefined;
    }

    const projectPath = normalizeOptionalDirectoryPath(value.projectPath);
    const workspaceRoot = normalizeOptionalDirectoryPath(value.workspaceRoot);
    if (!projectPath || !workspaceRoot || value.fingerprint !== fingerprintTrainerProjectPath(projectPath)) {
      return undefined;
    }
    const canonicalProjectPath = normalizeOptionalDirectoryPath(value.canonicalProjectPath) ?? projectPath;
    const rootId = value.rootId;
    const projectId = value.projectId;
    const contextId = value.contextId;
    const hasAnyStableIdentity = rootId !== undefined || projectId !== undefined || contextId !== undefined;
    const hasCompleteStableIdentity =
      isSafeIdentity(rootId) && isSafeIdentity(projectId) && isSafeIdentity(contextId);
    if (hasAnyStableIdentity && !hasCompleteStableIdentity) {
      return undefined;
    }
    const requestedIdentityStatus = isIdentityStatus(value.identityStatus) ? value.identityStatus : undefined;
    const identityStatus: TrainerWorkspaceIdentityStatus = hasCompleteStableIdentity
      ? requestedIdentityStatus ?? 'verified'
      : value.adoptionMode === 'managed'
        ? 'reconcile-required'
        : requestedIdentityStatus ?? 'pending';
    return {
      fingerprint: value.fingerprint,
      projectPath,
      workspaceRoot,
      adoptionMode: value.adoptionMode,
      projectLanePath: this.normalizeProjectLanePath(value.projectLanePath, workspaceRoot),
      rootId: hasCompleteStableIdentity ? rootId : undefined,
      projectId: hasCompleteStableIdentity ? projectId : undefined,
      contextId: hasCompleteStableIdentity ? contextId : undefined,
      canonicalProjectPath,
      legacyAliases: normalizeStringList(value.legacyAliases),
      manifestRevision: normalizeRevision(value.manifestRevision, 0),
      pathRevision: normalizeRevision(value.pathRevision, 0),
      identityStatus,
      serverRevisions: normalizeServerRevisions(value.serverRevisions),
      reconcile: isRecord(value.reconcile) ? { ...value.reconcile } : undefined,
      updatedAt: value.updatedAt,
    };
  }

  private normalizeProjectLanePath(value: unknown, workspaceRoot: string): string | undefined {
    const lanePath = normalizeOptionalDirectoryPath(value);
    if (!lanePath) {
      return undefined;
    }
    const projectsRoot = path.join(workspaceRoot, 'Projects');
    const relative = path.relative(projectsRoot, lanePath);
    if (!relative || relative.startsWith('..') || path.isAbsolute(relative)) {
      return undefined;
    }
    return lanePath;
  }

  private matchesCurrentProject(
    state: TrainerWorkspaceProjectState | undefined,
    workspaceRoot: string,
    projectPath: string,
  ): state is TrainerWorkspaceProjectState {
    return Boolean(
      state &&
        pathsEqual(state.workspaceRoot, workspaceRoot) &&
        (pathsEqual(state.projectPath, projectPath) || pathsEqual(state.canonicalProjectPath, projectPath)),
    );
  }

  private async createManagedProjectLane(
    workspaceRoot: string,
    project: TrainerWorkspaceProjectState,
  ): Promise<string> {
    const lanePath = project.projectLanePath ?? path.join(
      workspaceRoot,
      'Projects',
      project.projectId ?? project.fingerprint,
    );
    await Promise.all(
      TRAINER_MANAGED_PROJECT_DIRECTORIES.map((directory) =>
        fs.mkdir(path.join(lanePath, directory), { recursive: true }),
      ),
    );
    const laneManifest = {
      schemaVersion: 2,
      kind: 'trainer-project',
      fingerprint: project.fingerprint,
      rootId: project.rootId,
      projectId: project.projectId,
      contextId: project.contextId,
      canonicalProjectPath: project.canonicalProjectPath,
      legacyAliases: project.legacyAliases,
      manifestRevision: project.manifestRevision,
      pathRevision: project.pathRevision,
      identityStatus: project.identityStatus,
      serverRevisions: project.serverRevisions,
      reconcile: project.reconcile,
      sourcePath: project.projectPath,
      workspaceRoot,
      createdAt: project.updatedAt,
      updatedAt: project.updatedAt,
      directories: [...TRAINER_MANAGED_PROJECT_DIRECTORIES],
    };
    await this.writeJsonAtomically(path.join(lanePath, 'project.json'), laneManifest);
    return lanePath;
  }

  private mergeProjectStatesForRoot(
    rootPath: string,
    manifestProjects: TrainerWorkspaceProjectRegistry,
    registry: TrainerWorkspaceProjectRegistry,
  ): TrainerWorkspaceProjectRegistry {
    const mergedByIdentity = new Map<string, TrainerWorkspaceProjectState>();
    for (const state of [...Object.values(manifestProjects), ...Object.values(registry)]) {
      if (!pathsEqual(state.workspaceRoot, rootPath)) {
        continue;
      }
      const key = state.projectId ? `project:${state.projectId}` : `path:${state.fingerprint}`;
      mergedByIdentity.set(key, chooseNewestProjectState(mergedByIdentity.get(key), state) as TrainerWorkspaceProjectState);
    }
    const merged: TrainerWorkspaceProjectRegistry = {};
    for (const state of mergedByIdentity.values()) {
      merged[state.fingerprint] = { ...state };
    }
    return merged;
  }

  private async writeManifestAt(rootPath: string, manifest: TrainerWorkspaceManifest): Promise<void> {
    const manifestPath = path.join(rootPath, TRAINER_WORKSPACE_MANIFEST_FILE);
    await this.writeJsonAtomically(manifestPath, manifest);
  }

  private async writeJsonAtomically(filePath: string, value: unknown): Promise<void> {
    const temporaryPath = `${filePath}.${process.pid}.${Date.now()}.tmp`;
    const content = `${JSON.stringify(value, null, 2)}\n`;
    try {
      await fs.writeFile(temporaryPath, content, 'utf8');
      await this.renameWithTransientWindowsRetry(temporaryPath, filePath);
    } catch (error) {
      await fs.rm(temporaryPath, { force: true }).catch(() => undefined);
      throw error;
    }
  }

  private async isDirectory(candidate: string): Promise<boolean> {
    try {
      return (await fs.stat(candidate)).isDirectory();
    } catch (error) {
      if (isNotFoundError(error)) {
        return false;
      }
      throw error;
    }
  }

  private async pathExists(candidate: string): Promise<boolean> {
    try {
      await fs.lstat(candidate);
      return true;
    } catch (error) {
      if (isNotFoundError(error)) {
        return false;
      }
      throw error;
    }
  }
}
