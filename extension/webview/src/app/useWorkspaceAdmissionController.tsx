import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  type Dispatch,
  type MutableRefObject,
  type ReactNode,
  type SetStateAction,
} from "react";

import { trainerCommands } from "../../../../shared/src/commands";
import {
  deriveOnboardingSteps,
  resolveEffectiveTrustState,
} from "../../../../shared/src/onboarding";
import type { TrainerOperationMessage } from "../../../../shared/src/protocol";
import { readWorkspaceTrustStateFromCapabilitySummary } from "../../../../shared/src/workspaceTrustState";
import { OnboardingWizard, WorkspaceAdmissionPanel } from "../components/firstlook";
import type { composerDockDraftScope } from "../lib/composerDock";
import { appUiCopy } from "../lib/i18n/appUiCopy";
import type { Copy } from "../lib/i18n/copy";
import type { OperationMessageSurface } from "../lib/operationMessageGovernance";
import type {
  ActiveWorkbenchView,
  BootstrapData,
  ComposerLanguage,
  MessageAttachment,
  ProviderConfigView,
} from "../lib/types";
import { postMessage } from "../lib/vscode";
import { requireBrowserPreviewAdapter, type SettingsActionState } from "./appHelpers";
import type { ProviderDraft } from "../components/settings/CoachSettingsView";
import { useWorkbenchState } from "./useWorkbenchState";

export type ComposerDraftScopeKey = ReturnType<typeof composerDockDraftScope>;

export interface PendingPostAdmissionSend {
  text: string;
  attachments: MessageAttachment[];
  draftScope: ComposerDraftScopeKey;
  goalMode: boolean;
  goalText?: string;
  activeView: ActiveWorkbenchView;
}

export interface UseWorkspaceAdmissionStateParams {
  data: BootstrapData;
  composerLanguage: ComposerLanguage;
  t: Copy;
  setActiveView: (view: ActiveWorkbenchView) => void;
}

export function useWorkspaceAdmissionState({
  data,
  composerLanguage,
  t,
  setActiveView,
}: UseWorkspaceAdmissionStateParams) {
  const pendingPostAdmissionSendRef = useRef<PendingPostAdmissionSend | null>(null);
  const workspaceSettings = data.memory.workspace;
  const trainerWorkspaceAdmission = workspaceSettings?.trainerWorkspace;
  const canCaptureGoalBeforeWorkspaceSetup =
    trainerWorkspaceAdmission?.status === "root-missing";
  const canChatBeforeProjectAdmission =
    trainerWorkspaceAdmission?.status === "project-found";
  const workspaceAuthority = data.memory.sandboxState?.authority;

  const resourceWriteAccess = trainerWorkspaceAdmission
    ? {
        allowed: trainerWorkspaceAdmission.status === "managed",
        reason:
          trainerWorkspaceAdmission.status === "root-missing"
            ? t.workspaceAdmissionRootMissingDetail
            : undefined,
      }
    : workspaceAuthority?.resourceWriteAllowed === true
      ? {
          allowed:
            workspaceAuthority.authorityScope === "trainer_sandbox" &&
            workspaceAuthority.resourceWriteEvidence?.operation === "write" &&
            workspaceAuthority.resourceWriteEvidence.scope === "trainer_sandbox" &&
            workspaceAuthority.resourceWriteEvidence.allowed === true,
          reason: workspaceAuthority.resourceWriteEvidence?.reason,
        }
      : {
          allowed: false,
          reason: appUiCopy(
            composerLanguage,
            "资料写入权限还没确认。先在设置里选工作区根目录。",
          ),
        };

  const workspaceSessionBlocked =
    trainerWorkspaceAdmission?.status === "root-missing" ||
    trainerWorkspaceAdmission?.status === "project-found" ||
    trainerWorkspaceAdmission?.status === "browse" ||
    trainerWorkspaceAdmission?.status === "ignored";

  const workspaceSessionBlockTitle =
    trainerWorkspaceAdmission?.status === "root-missing"
      ? t.workspaceAdmissionRootMissing
      : trainerWorkspaceAdmission?.status === "project-found"
        ? t.workspaceAdmissionProjectFound
        : trainerWorkspaceAdmission?.status === "browse"
          ? t.workspaceAdmissionBrowse
          : trainerWorkspaceAdmission?.status === "ignored"
            ? t.workspaceAdmissionIgnored
            : undefined;

  const workspaceSessionBlockMessage =
    trainerWorkspaceAdmission?.status === "root-missing"
      ? t.workspaceAdmissionRootMissingDetail
      : trainerWorkspaceAdmission?.status === "project-found"
        ? t.workspaceAdmissionProjectFoundDetail
        : trainerWorkspaceAdmission?.status === "browse"
          ? t.workspaceAdmissionBrowseDetail
          : trainerWorkspaceAdmission?.status === "ignored"
            ? t.workspaceAdmissionIgnoredDetail
            : undefined;

  const openWorkspaceAdmission = useCallback(() => {
    if (trainerWorkspaceAdmission?.status === "root-missing") {
      useWorkbenchState.getState().requestSettingsCategory("workspace");
      setActiveView("settings");
      return;
    }
    setActiveView("coach");
  }, [setActiveView, trainerWorkspaceAdmission?.status]);

  const runWorkspaceAdmissionCommand = useCallback((commandId: string, payload?: unknown) => {
    postMessage({
      type: "command/execute",
      payload: payload === undefined ? { commandId } : { commandId, payload },
    });
  }, []);

  return {
    pendingPostAdmissionSendRef,
    trainerWorkspaceAdmission,
    canCaptureGoalBeforeWorkspaceSetup,
    canChatBeforeProjectAdmission,
    workspaceAuthority,
    resourceWriteAccess,
    workspaceSessionBlocked,
    workspaceSessionBlockTitle,
    workspaceSessionBlockMessage,
    openWorkspaceAdmission,
    runWorkspaceAdmissionCommand,
  };
}

export interface UseWorkspaceAdmissionFlowParams {
  trainerWorkspaceAdmission: NonNullable<BootstrapData["memory"]["workspace"]>["trainerWorkspace"];
  workspaceSessionBlocked: boolean;
  windowTrusted: boolean;
  liveSandboxCapabilitySummary: Record<string, unknown> | undefined;
  firstLookSubjectFamily: "literature" | "code" | undefined;
  providerConfig: ProviderConfigView;
  providerSendBlocked: boolean;
  providerCanCoachNow: boolean;
  providerBlockReason: string | undefined;
  capabilitySendBlocked: boolean;
  isStreaming: boolean;
  isBrowserPreview: boolean;
  composerLanguage: ComposerLanguage;
  providerDraft: ProviderDraft;
  setProviderDraft: Dispatch<SetStateAction<ProviderDraft>>;
  settingsActionState: SettingsActionState | undefined;
  setSettingsActionState: (next?: SettingsActionState) => void;
  setOperationMessage: (
    message?: TrainerOperationMessage,
    surface?: OperationMessageSurface,
  ) => void;
  setComposerDraft: (draft: string, scope?: ComposerDraftScopeKey) => void;
  setComposerAttachments: (attachments: MessageAttachment[]) => void;
  pendingPostAdmissionSendRef: MutableRefObject<PendingPostAdmissionSend | null>;
  handleSubmitRef: MutableRefObject<
    | ((
        confirmedActionKey?: string,
        overrideSubmission?: { text: string; attachments?: MessageAttachment[] },
      ) => Promise<void>)
    | null
  >;
  sendTurnRef: MutableRefObject<
    (input: {
      text: string;
      intent: "coach";
      intentSource: "explicit";
      stream: true;
      activeView: ActiveWorkbenchView;
      attachments?: MessageAttachment[];
      goalMode: boolean;
      goalText?: string;
    }) => void
  >;
  runWorkspaceAdmissionCommand: (commandId: string, payload?: unknown) => void;
  saveProviderDraft: () => void;
  openProviderSetup: () => void;
}

export function useWorkspaceAdmissionFlow({
  trainerWorkspaceAdmission,
  workspaceSessionBlocked,
  windowTrusted,
  liveSandboxCapabilitySummary,
  firstLookSubjectFamily,
  providerConfig,
  providerSendBlocked,
  providerCanCoachNow,
  providerBlockReason,
  capabilitySendBlocked,
  isStreaming,
  isBrowserPreview,
  composerLanguage,
  providerDraft,
  setProviderDraft,
  settingsActionState,
  setSettingsActionState,
  setOperationMessage,
  setComposerDraft,
  setComposerAttachments,
  pendingPostAdmissionSendRef,
  handleSubmitRef,
  sendTurnRef,
  runWorkspaceAdmissionCommand,
  saveProviderDraft,
  openProviderSetup,
}: UseWorkspaceAdmissionFlowParams): {
  onboarding: ReturnType<typeof deriveOnboardingSteps>;
  onboardingWizard: ReactNode;
  workspaceAdmissionContent: ReactNode;
} {
  useEffect(() => {
    const admissionStatus = trainerWorkspaceAdmission?.status;
    if (admissionStatus === "browse" || admissionStatus === "ignored") {
      pendingPostAdmissionSendRef.current = null;
      return;
    }
    if (admissionStatus !== "managed" || workspaceSessionBlocked || isStreaming) {
      return;
    }
    const pending = pendingPostAdmissionSendRef.current;
    if (!pending) {
      return;
    }
    pendingPostAdmissionSendRef.current = null;
    if (!providerCanCoachNow || providerBlockReason || capabilitySendBlocked) {
      return;
    }
    const { layout: currentLayout } = useWorkbenchState.getState();
    const currentDraft =
      currentLayout.composerDraftScope === pending.draftScope
        ? currentLayout.composerDraft
        : currentLayout.composerDrafts?.[pending.draftScope];
    if ((currentDraft ?? "").trim() === pending.text) {
      setComposerDraft("", pending.draftScope);
      setComposerAttachments([]);
    }
    if (!pending.goalMode) {
      void handleSubmitRef.current?.(undefined, {
        text: pending.text,
        attachments: pending.attachments,
      });
      return;
    }
    sendTurnRef.current({
      text: pending.text,
      intent: "coach",
      intentSource: "explicit",
      stream: true,
      activeView: pending.activeView,
      attachments: pending.attachments.length ? pending.attachments : undefined,
      goalMode: pending.goalMode,
      goalText: pending.goalText,
    });
  }, [
    capabilitySendBlocked,
    handleSubmitRef,
    isStreaming,
    pendingPostAdmissionSendRef,
    providerBlockReason,
    providerCanCoachNow,
    sendTurnRef,
    setComposerAttachments,
    setComposerDraft,
    trainerWorkspaceAdmission?.status,
    workspaceSessionBlocked,
  ]);

  const effectiveWorkspaceTrustState = resolveEffectiveTrustState(
    readWorkspaceTrustStateFromCapabilitySummary(liveSandboxCapabilitySummary),
    windowTrusted,
  );

  const onboarding = deriveOnboardingSteps({
    workspaceAdmissionStatus: trainerWorkspaceAdmission?.status,
    workspaceTrustState: effectiveWorkspaceTrustState,
    providerConfigured: providerConfig.configured,
    providerApiKeyConfigured: providerConfig.apiKeyConfigured,
    providerSendBlocked,
  });

  const onboardingActive = !onboarding.complete && !providerConfig.configured;

  const onboardingListModels = useMemo(() => {
    if (isBrowserPreview) {
      return async (baseUrl: string, apiKey: string): Promise<string[]> => {
        const browserPreview = await requireBrowserPreviewAdapter();
        return browserPreview.listBrowserPreviewDraftModels({ baseUrl }, apiKey);
      };
    }
    return (baseUrl: string, apiKey: string): Promise<string[]> =>
      new Promise<string[]>((resolve) => {
        const trimmedUrl = baseUrl.trim().replace(/\/+$/, "");
        if (!trimmedUrl) {
          resolve([]);
          return;
        }
        let settled = false;
        const finish = (models: string[]) => {
          if (settled) return;
          settled = true;
          window.clearTimeout(timer);
          unsubscribe();
          resolve(models);
        };
        const unsubscribe = useWorkbenchState.subscribe((state) => {
          const listing = state.data.providerConfig.modelListing as
            | { source?: string; baseUrl?: string; status?: string; availableModels?: unknown }
            | undefined;
          if (!listing || listing.source !== "draft" || listing.status === "loading") {
            return;
          }
          const listedUrl = String(listing.baseUrl ?? "").trim().replace(/\/+$/, "");
          if (listedUrl && listedUrl !== trimmedUrl && !listedUrl.endsWith(trimmedUrl)) {
            return;
          }
          const models = Array.isArray(listing.availableModels)
            ? listing.availableModels.filter(
                (item): item is string => typeof item === "string" && Boolean(item.trim()),
              )
            : [];
          finish(models);
        });
        const timer = window.setTimeout(() => finish([]), 15_000);
        postMessage({
          type: "command/execute",
          payload: {
            commandId: trainerCommands.refreshProviderModels,
            payload: {
              draft: {
                baseUrl: trimmedUrl,
                ...(apiKey.trim() ? { apiKey: apiKey.trim() } : {}),
                protocol: providerDraft.protocol,
              },
            },
          },
        });
      });
  }, [isBrowserPreview, providerDraft.protocol]);

  const startOnboardingTrial = useCallback(() => {
    setSettingsActionState({
      kind: "start-provider-trial",
      targets: ["provider"],
    });
    if (isBrowserPreview) {
      setOperationMessage({
        tone: "info",
        message: appUiCopy(composerLanguage, "练习模式需要在 VS Code 扩展中启动。"),
      });
      return;
    }
    postMessage({
      type: "command/execute",
      payload: { commandId: trainerCommands.startProviderTrial },
    });
  }, [composerLanguage, isBrowserPreview, setOperationMessage, setSettingsActionState]);

  const onboardingWizard = onboardingActive ? (
    <OnboardingWizard
      steps={onboarding.steps}
      activeStepId={onboarding.activeStepId}
      complete={onboarding.complete}
      busy={settingsActionState?.kind === "save-provider"}
      trialBusy={settingsActionState?.kind === "start-provider-trial"}
      draftBaseUrl={providerDraft.baseUrl}
      draftApiKey={providerDraft.apiKey}
      draftModel={providerDraft.model}
      hasStoredApiKey={providerConfig.apiKeyConfigured}
      onDraftChange={(patch) => setProviderDraft((draft: ProviderDraft) => ({ ...draft, ...patch }))}
      onListModels={onboardingListModels}
      onChooseWorkspaceRoot={() =>
        runWorkspaceAdmissionCommand(trainerCommands.chooseTrainerWorkspaceRoot)
      }
      onTrustWindow={() =>
        postMessage({
          type: "command/execute",
          payload: { commandId: trainerCommands.trustWorkspaceWindow },
        })
      }
      onSaveConnection={saveProviderDraft}
      onStartTrial={startOnboardingTrial}
      onOpenSettings={() => openProviderSetup()}
    />
  ) : null;

  const workspaceAdmissionContent = trainerWorkspaceAdmission ? (
    <WorkspaceAdmissionPanel
      status={trainerWorkspaceAdmission.status}
      projectName={trainerWorkspaceAdmission.projectName}
      projectPath={trainerWorkspaceAdmission.projectPath}
      subjectFamily={firstLookSubjectFamily}
      reconciliation={trainerWorkspaceAdmission.reconciliation}
      onRetryAdmission={() =>
        runWorkspaceAdmissionCommand(trainerCommands.retryWorkspaceAdmission, {
          responseLanguage: composerLanguage,
        })
      }
      onContinueAdmission={() =>
        runWorkspaceAdmissionCommand(trainerCommands.continueWorkspaceAdmission, {
          responseLanguage: composerLanguage,
        })
      }
      onAbandonAdmission={() =>
        runWorkspaceAdmissionCommand(trainerCommands.abandonWorkspaceAdmission)
      }
      onSelectWorkspaceRoot={() =>
        runWorkspaceAdmissionCommand(trainerCommands.chooseTrainerWorkspaceRoot)
      }
      onSelectProject={() => runWorkspaceAdmissionCommand(trainerCommands.chooseWorkspaceProject)}
      onAddProject={() =>
        runWorkspaceAdmissionCommand(trainerCommands.adoptWorkspaceProject, {
          responseLanguage: composerLanguage,
        })
      }
      onBrowseProject={() => runWorkspaceAdmissionCommand(trainerCommands.browseWorkspaceProject)}
      onIgnoreProject={() => runWorkspaceAdmissionCommand(trainerCommands.ignoreWorkspaceProject)}
      onDeleteProject={() => runWorkspaceAdmissionCommand(trainerCommands.deleteWorkspaceProject)}
    />
  ) : null;

  return {
    onboarding,
    onboardingWizard,
    workspaceAdmissionContent,
  };
}
