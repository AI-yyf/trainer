import { useMemo } from "react";
import {
  leftoverSettingsLearnerProjectOnboardingIsNotLive,
  leftoverSettingsProfileRhythmIsNotLive,
} from "../../../../../shared/src/planOrientationGovernance";
import { planRuntimeStatusFromRecovery } from "../../../../../shared/src/workspaceRecoveryGovernance";
import type { TrainerOperationMessage } from "../../../../../shared/src/protocol";
import { trainerCommands } from "../../../../../shared/src/commands";
import {
  resolveOperationMessageSurface,
  sanitizeOperationFailureMessage,
  type OperationMessageSurface,
} from "../../lib/operationMessageGovernance";
import { appUiCopy } from "../../lib/i18n/appUiCopy";
import { postMessage, requestNativeSkillDraft } from "../../lib/vscode";
import type {
  CoachDefaults,
  ComposerLanguage,
  LearningSurfaceAlignment,
  ManagedDataFolder,
  MemoryShareGrant,
  ProviderConfigView,
  TeachingStyle,
  ThemePreference,
  TrainerWorkspaceAdmission,
} from "../../lib/types";
import { useWorkbenchState } from "../../app/useWorkbenchState";

/**
 * Selector module for CoachSettingsView (props-debt round: store-driven data).
 *
 * Every field this view reads that already lives in the workbench store is
 * selected here instead of being threaded through `CoachSettingsViewProps` —
 * provider facts, connection state, workspace/memory facts, the persisted
 * layout (theme/language/teaching/context knobs), and the leftover-not-live
 * gating flags. Pure `command/execute` relays (no App-local closure state)
 * are rebuilt here too, including their browser-preview guards.
 *
 * What deliberately stays a prop: values only App can produce (provider draft
 * controller state, per-section action status, capability verdict scoped to
 * App's provider-test clock, leftover coach chrome, the guard-pinned
 * `sectionRequest` / `skillSharing` surface) and callbacks closing over
 * App-local state (preview session, settings action state, the debounced
 * coach-settings persist).
 */

type BrowserPreviewModule = typeof import("../../lib/browserSidecar");

let browserPreviewModulePromise: Promise<BrowserPreviewModule> | undefined;

async function loadBrowserPreviewModule(): Promise<BrowserPreviewModule> {
  browserPreviewModulePromise ??= import("../../lib/browserSidecar");
  return browserPreviewModulePromise;
}

/** Same environment check App performs before taking a preview-only branch. */
function inBrowserPreviewEnvironment(): boolean {
  return (
    typeof window !== "undefined" &&
    (window.__TRAINER_BROWSER_PREVIEW__ === true || !window.acquireVsCodeApi)
  );
}

/** Neutral coach defaults restored by "reset to defaults" (App parity). */
const DEFAULT_COACH_DEFAULTS: CoachDefaults = {
  memoryScope: "project",
  workingSetMode: "balanced",
  reviewCadence: "steady",
  reviewReminderMode: "due",
  workspaceMemoryToggles: {
    decisions: true,
    patterns: true,
    resources: true,
  },
};

export interface CoachSettingsViewStateOptions {
  /**
   * App-owned debounced persist trigger (`queueCoachSettingsSave`). The
   * setters below apply each change to the store immediately; App alone
   * decides when (and how) the change is persisted to the host.
   */
  onCoachSettingsMutated?: () => void;
}

export interface CoachSettingsViewState {
  // §store facts
  provider: ProviderConfigView;
  backendConnectionState: "starting" | "connected" | "offline";
  memoryShareGrants: MemoryShareGrant[];
  resourceSandbox: ManagedDataFolder | null;
  trainerWorkspace: TrainerWorkspaceAdmission | undefined;
  remoteWorkspaceName: string | undefined;
  personalAccountTrusted: boolean;
  // §layout knobs
  themePreference: ThemePreference;
  learningSurfaceAlignment: LearningSurfaceAlignment;
  language: ComposerLanguage;
  answerMode: "auto" | "coach-first" | "balanced" | "direct";
  teachingStyle: TeachingStyle;
  coachDefaults: CoachDefaults;
  followCurrentFile: boolean;
  contextDetail: "focused" | "balanced" | "full";
  includeCurrentFile: boolean;
  includeSelection: boolean;
  includeDiagnostics: boolean;
  includeRelatedFiles: boolean;
  // §leftover-gated profile facts
  learnerName: string | undefined;
  targetProject: string | undefined;
  preferredRhythm: string | undefined;
  preferredLearningMode: string | undefined;
  onboardingRequest: string | undefined;
  projectContext: string | undefined;
  longTermMemoryStateLabel: string;
  // §actions
  onThemePreferenceChange: (value: ThemePreference) => void;
  onLearningSurfaceAlignmentChange: (value: LearningSurfaceAlignment) => void;
  onLanguageChange: (value: ComposerLanguage) => void;
  onAnswerModeChange: (value: "auto" | "coach-first" | "balanced" | "direct") => void;
  onTeachingStyleChange: (value: TeachingStyle) => void;
  onFollowCurrentFileChange: (value: boolean) => void;
  onCoachDefaultsChange: (value: Partial<CoachDefaults>) => void;
  onContextDetailChange: (value: "focused" | "balanced" | "full") => void;
  onIncludeCurrentFileChange: (value: boolean) => void;
  onIncludeSelectionChange: (value: boolean) => void;
  onIncludeDiagnosticsChange: (value: boolean) => void;
  onIncludeRelatedFilesChange: (value: boolean) => void;
  onNavigateToView: (view: "resources" | "training") => void;
  onGenerateSkillDraft: (
    description: string,
  ) => Promise<
    | { trigger: string; title: string; detail: string; prompt: string; source: "model" | "template" }
    | undefined
  >;
  onGrantMemoryShare: (() => void) | undefined;
  onRevokeMemoryShare: ((sourceWorkspaceId: string) => void) | undefined;
  onSetPersonalAccountTrust: ((enabled: boolean) => void) | undefined;
  onTrustWindow: () => void;
  onRefreshWorkspaceAuthority: () => void;
  onChooseTrainerWorkspaceRoot: () => void;
  onMigrateTrainerWorkspaceRoot: () => void;
  onBackupTrainerWorkspace: () => void;
  onRestoreTrainerWorkspaceBackup: () => void;
  onChooseManagedDataFolder: () => void;
  onResetManagedDataFolder: () => void;
  onRefreshMemory: () => void;
  onShareSession: () => Promise<void>;
}

export function useCoachSettingsViewState({
  onCoachSettingsMutated,
}: CoachSettingsViewStateOptions): CoachSettingsViewState {
  // §selector reads — one atomic selector per store field this view consumes.
  const provider = useWorkbenchState((state) => state.data.providerConfig);
  const backendConnectionState = useWorkbenchState((state) => state.data.connection.state);
  const memoryWorkspace = useWorkbenchState((state) => state.data.memory.workspace);
  const memoryShareGrants = useWorkbenchState((state) => state.data.memory.memoryShareGrants);
  const workspace = useWorkbenchState((state) => state.data.workspace);
  const profile = useWorkbenchState((state) => state.data.profile);
  const conversation = useWorkbenchState((state) => state.data.conversation);
  const planRuntimeStatus = useWorkbenchState((state) => state.data.planRuntimeStatus);
  const workspaceTrainingState = useWorkbenchState(
    (state) => state.data.workspaceTrainingState,
  );
  const sessionHistoryRestored = useWorkbenchState(
    (state) => state.data.sessionHistoryRestored,
  );
  const themePreference = useWorkbenchState((state) => state.layout.themePreference);
  const learningSurfaceAlignment = useWorkbenchState(
    (state) => state.layout.learningSurfaceAlignment,
  );
  const language = useWorkbenchState((state) => state.layout.composerLanguage);
  const answerMode = useWorkbenchState((state) => state.layout.composerAnswerMode);
  const teachingStyle = useWorkbenchState((state) => state.layout.teachingStyle);
  const layoutCoachDefaults = useWorkbenchState((state) => state.layout.coachDefaults);
  const followCurrentFile = useWorkbenchState((state) => state.layout.followCurrentFile);
  const contextDetail = useWorkbenchState((state) => state.layout.contextDetail);
  const includeCurrentFile = useWorkbenchState((state) => state.layout.includeCurrentFile);
  const includeSelection = useWorkbenchState((state) => state.layout.includeSelection);
  const includeDiagnostics = useWorkbenchState((state) => state.layout.includeDiagnostics);
  const includeRelatedFiles = useWorkbenchState((state) => state.layout.includeRelatedFiles);

  // §actions — store actions are stable identities.
  const setThemePreference = useWorkbenchState((state) => state.setThemePreference);
  const setLearningSurfaceAlignment = useWorkbenchState(
    (state) => state.setLearningSurfaceAlignment,
  );
  const setComposerLanguage = useWorkbenchState((state) => state.setComposerLanguage);
  const setComposerAnswerMode = useWorkbenchState((state) => state.setComposerAnswerMode);
  const setTeachingStyle = useWorkbenchState((state) => state.setTeachingStyle);
  const setFollowCurrentFile = useWorkbenchState((state) => state.setFollowCurrentFile);
  const setCoachDefaults = useWorkbenchState((state) => state.setCoachDefaults);
  const setContextDetail = useWorkbenchState((state) => state.setContextDetail);
  const setIncludeCurrentFile = useWorkbenchState((state) => state.setIncludeCurrentFile);
  const setIncludeSelection = useWorkbenchState((state) => state.setIncludeSelection);
  const setIncludeDiagnostics = useWorkbenchState((state) => state.setIncludeDiagnostics);
  const setIncludeRelatedFiles = useWorkbenchState((state) => state.setIncludeRelatedFiles);
  const setActiveView = useWorkbenchState((state) => state.setActiveView);

  const isBrowserPreview = inBrowserPreviewEnvironment();

  // §四十四 single-channel write, same composition as App's operation-status
  // controller: sanitize + resolve the surface from the raw text, then write
  // message and surface in one store update.
  const setOperationMessage = (
    message?: TrainerOperationMessage,
    surface?: OperationMessageSurface,
  ): void => {
    const resolvedSurface = resolveOperationMessageSurface(message?.message, surface);
    useWorkbenchState.getState().setOperationMessage(
      message ? sanitizeOperationFailureMessage(message, language) : undefined,
      resolvedSurface,
    );
  };

  // Leftover-not-live gating: first runs must not present recovered-session
  // profile facts as live (same pure governance helpers App applies).
  const recoveredRuntime =
    planRuntimeStatus?.recovered === true ||
    Boolean(
      planRuntimeStatusFromRecovery(
        memoryWorkspace?.latestPlanRuntime,
        memoryWorkspace?.workspaceId ?? workspaceTrainingState?.workspaceId ?? "",
      ),
    );
  const runtimeCurrentStep =
    planRuntimeStatus?.currentStep ?? planRuntimeStatus?.currentMainThread?.currentStep;
  const leftoverSettingsProfileRhythmNotLive =
    !sessionHistoryRestored &&
    leftoverSettingsProfileRhythmIsNotLive({
      recovered: recoveredRuntime,
      runtimeCurrentStep,
    });
  const leftoverSettingsLearnerProjectOnboardingNotLive =
    !sessionHistoryRestored &&
    leftoverSettingsLearnerProjectOnboardingIsNotLive({
      recovered: recoveredRuntime,
      runtimeCurrentStep,
    });

  // Settings save on change: apply now, let App decide when to persist. The
  // App-side wrappers previously did exactly this (apply + queue) inline.
  const mutateCoachSettings = () => {
    onCoachSettingsMutated?.();
  };

  const onGenerateSkillDraft = useMemo(() => {
    if (!isBrowserPreview) {
      return requestNativeSkillDraft;
    }
    return async (description: string) => {
      const browserPreview = await loadBrowserPreviewModule();
      return browserPreview.generateBrowserPreviewSkillDraft(description);
    };
  }, [isBrowserPreview]);

  const onShareSession = async () => {
    const lines = conversation
      .filter((message) => message.body?.trim())
      .map((message) => {
        const role =
          message.role === "user" ? appUiCopy(language, "我") : appUiCopy(language, "教练");
        return `**${role}**: ${message.body.trim()}`;
      });
    if (!lines.length) {
      setOperationMessage({
        tone: "info",
        message: appUiCopy(language, "还没有会话内容可以分享。"),
      });
      return;
    }
    const title = appUiCopy(language, "Trainer 会话");
    const text = `# ${title}\n\n${lines.join("\n\n")}`;
    try {
      await navigator.clipboard.writeText(text);
      setOperationMessage({
        tone: "success",
        message: appUiCopy(language, "会话摘要已复制到剪贴板。"),
      });
    } catch {
      setOperationMessage({
        tone: "error",
        message: appUiCopy(language, "复制失败，请重试。"),
      });
    }
  };

  return {
    // §store facts
    provider,
    backendConnectionState,
    memoryShareGrants: memoryShareGrants ?? [],
    resourceSandbox: memoryWorkspace?.resourceSandbox ?? null,
    trainerWorkspace: memoryWorkspace?.trainerWorkspace,
    remoteWorkspaceName: workspace?.isRemoteWorkspace ? workspace.remoteName : undefined,
    personalAccountTrusted: memoryWorkspace?.personalAccountTrusted === true,
    // §layout knobs
    themePreference,
    learningSurfaceAlignment,
    language,
    answerMode,
    teachingStyle,
    coachDefaults: leftoverSettingsProfileRhythmNotLive
      ? DEFAULT_COACH_DEFAULTS
      : layoutCoachDefaults,
    followCurrentFile,
    contextDetail,
    includeCurrentFile,
    includeSelection,
    includeDiagnostics,
    includeRelatedFiles,
    // §leftover-gated profile facts
    learnerName: leftoverSettingsLearnerProjectOnboardingNotLive
      ? undefined
      : profile.learnerName,
    targetProject: leftoverSettingsLearnerProjectOnboardingNotLive
      ? undefined
      : profile.targetProject,
    preferredRhythm: leftoverSettingsProfileRhythmNotLive ? undefined : profile.preferredRhythm,
    preferredLearningMode: leftoverSettingsProfileRhythmNotLive
      ? undefined
      : profile.preferredLearningMode,
    onboardingRequest: leftoverSettingsLearnerProjectOnboardingNotLive
      ? undefined
      : profile.onboardingRequest,
    projectContext: leftoverSettingsLearnerProjectOnboardingNotLive
      ? undefined
      : profile.projectContext,
    longTermMemoryStateLabel: appUiCopy(language, "已启用"),
    // §actions — plain setters apply directly; mutated knobs queue App's persist.
    onThemePreferenceChange: setThemePreference,
    onLearningSurfaceAlignmentChange: setLearningSurfaceAlignment,
    onLanguageChange: (value) => {
      setComposerLanguage(value);
      mutateCoachSettings();
    },
    onAnswerModeChange: (value) => {
      setComposerAnswerMode(value);
      mutateCoachSettings();
    },
    onTeachingStyleChange: (value) => {
      setTeachingStyle(value);
      mutateCoachSettings();
    },
    onFollowCurrentFileChange: (value) => {
      setFollowCurrentFile(value);
      mutateCoachSettings();
    },
    onCoachDefaultsChange: (value) => {
      setCoachDefaults(value);
      mutateCoachSettings();
    },
    onContextDetailChange: (value) => {
      setContextDetail(value);
      mutateCoachSettings();
    },
    onIncludeCurrentFileChange: (value) => {
      setIncludeCurrentFile(value);
      mutateCoachSettings();
    },
    onIncludeSelectionChange: (value) => {
      setIncludeSelection(value);
      mutateCoachSettings();
    },
    onIncludeDiagnosticsChange: (value) => {
      setIncludeDiagnostics(value);
      mutateCoachSettings();
    },
    onIncludeRelatedFilesChange: (value) => {
      setIncludeRelatedFiles(value);
      mutateCoachSettings();
    },
    onNavigateToView: setActiveView,
    onGenerateSkillDraft,
    onGrantMemoryShare: isBrowserPreview
      ? undefined
      : () =>
          postMessage({
            type: "command/execute",
            payload: { commandId: trainerCommands.grantMemoryShare },
          }),
    onRevokeMemoryShare: isBrowserPreview
      ? undefined
      : (sourceWorkspaceId) =>
          postMessage({
            type: "command/execute",
            payload: {
              commandId: trainerCommands.revokeMemoryShare,
              payload: { sourceWorkspaceId },
            },
          }),
    onSetPersonalAccountTrust: isBrowserPreview
      ? undefined
      : (enabled) =>
          postMessage({
            type: "command/execute",
            payload: {
              commandId: trainerCommands.setPersonalAccountTrust,
              payload: { enabled },
            },
          }),
    onTrustWindow: () =>
      postMessage({
        type: "command/execute",
        payload: { commandId: trainerCommands.trustWorkspaceWindow },
      }),
    onRefreshWorkspaceAuthority: () => {
      if (isBrowserPreview) {
        setOperationMessage({
          tone: "info",
          message:
            appUiCopy(language, "浏览器预览只显示预置的工作区边界状态。重新读取真实边界请回到 VS Code 侧栏。"),
        });
        return;
      }
      postMessage({
        type: "command/execute",
        payload: { commandId: trainerCommands.refreshWorkspaceAuthority },
      });
    },
    onChooseTrainerWorkspaceRoot: () =>
      postMessage({
        type: "command/execute",
        payload: { commandId: trainerCommands.chooseTrainerWorkspaceRoot },
      }),
    onMigrateTrainerWorkspaceRoot: () =>
      postMessage({
        type: "command/execute",
        payload: { commandId: trainerCommands.migrateTrainerWorkspaceRoot },
      }),
    onBackupTrainerWorkspace: () =>
      postMessage({
        type: "command/execute",
        payload: { commandId: trainerCommands.backupTrainerWorkspace },
      }),
    onRestoreTrainerWorkspaceBackup: () =>
      postMessage({
        type: "command/execute",
        payload: { commandId: trainerCommands.restoreTrainerWorkspaceBackup },
      }),
    onChooseManagedDataFolder: () => {
      if (isBrowserPreview) {
        setOperationMessage({
          tone: "info",
          message:
            appUiCopy(language, "浏览器预览不能修改 managed data folder。请在 VS Code 侧栏里选择真实路径。"),
        });
        return;
      }
      postMessage({
        type: "command/execute",
        payload: { commandId: trainerCommands.chooseManagedDataFolder },
      });
    },
    onResetManagedDataFolder: () => {
      if (isBrowserPreview) {
        setOperationMessage({
          tone: "info",
          message:
            appUiCopy(language, "浏览器预览不能重置 managed data folder。请在 VS Code 侧栏里使用推荐路径。"),
        });
        return;
      }
      postMessage({
        type: "command/execute",
        payload: { commandId: trainerCommands.resetManagedDataFolder },
      });
    },
    onRefreshMemory: () =>
      postMessage({
        type: "command/execute",
        payload: { commandId: "trainer.memory.refresh" },
      }),
    onShareSession,
  };
}
