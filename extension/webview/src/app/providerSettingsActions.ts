import {
  DEFAULT_ANSWER_MODE,
  DEFAULT_TEACHING_STYLE,
  loadBrowserPreviewModule,
  normalizeOperationMessageKey,
  type BrowserPreviewModule,
  type OperationMessage,
  type SettingsActionState,
} from "./appHelpers";
import { useWorkbenchState } from "./useWorkbenchState";
import { appUiCopy } from "../lib/i18n/appUiCopy";
import { recoverableFailureMessage } from "../lib/operationMessageGovernance";
import { postMessage } from "../lib/vscode";
import type {
  CoachAnswerMode,
  CoachDefaults,
  ComposerLanguage,
  HostMessage,
  TeachingStyle,
} from "../lib/types";
import { trainerCommands } from "../../../../shared/src/commands";

type ProviderSavePayload = Parameters<
  BrowserPreviewModule["saveBrowserPreviewProviderProfile"]
>[0];

export interface ProviderSettingsActionsDeps {
  language: ComposerLanguage;
  isBrowserPreview: boolean;
  previewSessionId?: string;
  providerSavePayload: ProviderSavePayload;
  providerDraftHasChanges: boolean;
  providerConfigured: boolean;
  operationMessage?: OperationMessage;
  baselineConnectedMessage: string;
  setSettingsActionState: (next?: SettingsActionState) => void;
  setPreviewSessionId: (sessionId: string) => void;
  applyPreviewHostMessages: (messages: HostMessage[], isProviderAction?: boolean) => void;
  persistCoachSettings: (overrides?: Partial<{
    responseLanguage: ComposerLanguage;
    answerMode: CoachAnswerMode;
    teachingStyle: TeachingStyle;
    coachDefaults: CoachDefaults;
    followCurrentFile: boolean;
    contextDetail: "focused" | "balanced" | "full";
    includeCurrentFile: boolean;
    includeSelection: boolean;
    includeDiagnostics: boolean;
    includeRelatedFiles: boolean;
  }>) => void;
  defaultCoachDefaults: CoachDefaults;
}

/**
 * Provider connection actions for the Settings route.
 *
 * The browser-preview branches and host command payloads live here so
 * App.tsx keeps only state wiring; each action keeps the same baseline
 * message key and single-flight semantics as the original inline handlers.
 */
export function buildProviderSettingsActions(deps: ProviderSettingsActionsDeps) {
  const {
    language,
    isBrowserPreview,
    previewSessionId,
    providerSavePayload,
    providerDraftHasChanges,
    providerConfigured,
    operationMessage,
    baselineConnectedMessage,
    setSettingsActionState,
    setPreviewSessionId,
    applyPreviewHostMessages,
    persistCoachSettings,
    defaultCoachDefaults,
  } = deps;

  const baselineMessageKey = () =>
    normalizeOperationMessageKey(operationMessage) ?? baselineConnectedMessage.toLowerCase();

  const previewFailure = () =>
    recoverableFailureMessage("provider", language);

  const runPreviewAction = async (
    action: (browserPreview: BrowserPreviewModule) => Promise<{
      sessionId: string;
      messages: HostMessage[];
    }>,
  ) => {
    try {
      const browserPreview = await loadBrowserPreviewModule();
      const result = await action(browserPreview);
      setPreviewSessionId(result.sessionId);
      applyPreviewHostMessages(result.messages, true);
    } catch {
      useWorkbenchState.getState().setOperationMessage({
        tone: "error",
        message: previewFailure(),
      });
    }
  };

  return {
    onSaveProviderProfile: () => {
      setSettingsActionState({
        kind: "save-provider",
        targets: ["provider"],
        baselineMessageKey: baselineMessageKey(),
      });
      if (isBrowserPreview) {
        void runPreviewAction((browserPreview) =>
          browserPreview.saveBrowserPreviewProviderProfile(providerSavePayload, previewSessionId),
        );
        return;
      }
      postMessage({
        type: "command/execute",
        payload: {
          commandId: trainerCommands.saveProviderProfile,
          payload: providerSavePayload,
        },
      });
    },
    onRefreshProviderProfiles: () => {
      setSettingsActionState({
        kind: "refresh-provider-models",
        targets: ["provider"],
        baselineMessageKey: baselineMessageKey(),
      });
      if (isBrowserPreview) {
        void runPreviewAction((browserPreview) =>
          browserPreview.refreshBrowserPreviewProviderProfiles(previewSessionId),
        );
        return;
      }
      postMessage({
        type: "command/execute",
        payload: { commandId: trainerCommands.refreshProviderProfiles },
      });
    },
    onSwitchProviderProfile: (profileId: string) => {
      setSettingsActionState({
        kind: "save-provider",
        targets: ["provider"],
        baselineMessageKey: baselineMessageKey(),
      });
      if (isBrowserPreview) {
        void runPreviewAction((browserPreview) =>
          browserPreview.switchBrowserPreviewProviderProfile(profileId, previewSessionId),
        );
        return;
      }
      postMessage({
        type: "command/execute",
        payload: {
          commandId: trainerCommands.switchProviderProfile,
          payload: { profileId, reason: "settings_switch" },
        },
      });
    },
    onRefreshProviderModels: () => {
      const shouldUseDraft = providerDraftHasChanges || !providerConfigured;
      setSettingsActionState({
        kind: "refresh-provider-models",
        targets: ["provider"],
        baselineMessageKey: baselineMessageKey(),
      });
      if (isBrowserPreview) {
        void runPreviewAction((browserPreview) =>
          browserPreview.refreshBrowserPreviewProviderModels(
            shouldUseDraft ? providerSavePayload : undefined,
            previewSessionId,
          ),
        );
        return;
      }
      postMessage({
        type: "command/execute",
        payload: {
          commandId: trainerCommands.refreshProviderModels,
          ...(shouldUseDraft ? { payload: { draft: providerSavePayload } } : {}),
        },
      });
    },
    onTestProvider: () => {
      const requestId = `provider-test-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      setSettingsActionState({
        kind: "test-provider",
        targets: ["provider"],
        baselineMessageKey: baselineMessageKey(),
        requestId,
      });
      if (isBrowserPreview) {
        void runPreviewAction((browserPreview) =>
          browserPreview.testBrowserPreviewProvider(
            providerDraftHasChanges ? providerSavePayload : undefined,
            previewSessionId,
          ),
        );
        return;
      }
      postMessage({
        type: "command/execute",
        payload: {
          commandId: trainerCommands.testProvider,
          payload: {
            responseLanguage: language,
            requestId,
            ...(providerDraftHasChanges ? { draft: providerSavePayload } : {}),
          },
        },
      });
    },
    onRestartSidecar: isBrowserPreview
      ? undefined
      : () =>
          postMessage({
            type: "command/execute",
            payload: { commandId: trainerCommands.restartSidecar },
          }),
    onClearProvider: () => {
      setSettingsActionState({
        kind: "clear-provider",
        targets: ["provider"],
        baselineMessageKey: baselineMessageKey(),
      });
      if (isBrowserPreview) {
        void runPreviewAction((browserPreview) =>
          browserPreview.clearBrowserPreviewProvider(previewSessionId),
        );
        return;
      }
      postMessage({
        type: "command/execute",
        payload: { commandId: "trainer.provider.clear" },
      });
    },
    onOpenConfig: () => {
      setSettingsActionState({
        kind: "open-config",
        targets: ["provider"],
        baselineMessageKey: baselineMessageKey(),
      });
      if (isBrowserPreview) {
        useWorkbenchState.getState().setOperationMessage({
          tone: "info",
          message: appUiCopy(
            language,
            "浏览器预览没有工作区配置文件入口。这个按钮只在 VS Code 侧栏里可用。",
          ),
        });
        return;
      }
      postMessage({
        type: "command/execute",
        payload: { commandId: "trainer.config.openWorkspace" },
      });
    },
    onResetDefaults: () => {
      const defaultLanguage =
        typeof navigator !== "undefined" && navigator.language.toLowerCase().startsWith("zh")
          ? "zh-CN"
          : "en-US";
      setSettingsActionState({
        kind: "reset-defaults",
        targets: ["coachDefaults", "workspaceControl"],
        baselineMessageKey: baselineMessageKey(),
      });
      const store = useWorkbenchState.getState();
      store.setThemePreference("system");
      store.setComposerLanguage(defaultLanguage);
      store.setComposerAnswerMode(DEFAULT_ANSWER_MODE);
      store.setTeachingStyle(DEFAULT_TEACHING_STYLE);
      store.setFollowCurrentFile(true);
      store.setContextDetail("balanced");
      store.setIncludeCurrentFile(true);
      store.setIncludeSelection(true);
      store.setIncludeDiagnostics(true);
      store.setIncludeRelatedFiles(true);
      store.setCoachDefaults(defaultCoachDefaults);
      persistCoachSettings({
        responseLanguage: defaultLanguage,
        answerMode: DEFAULT_ANSWER_MODE,
        teachingStyle: DEFAULT_TEACHING_STYLE,
        followCurrentFile: true,
        contextDetail: "balanced",
        includeCurrentFile: true,
        includeSelection: true,
        includeDiagnostics: true,
        includeRelatedFiles: true,
        coachDefaults: defaultCoachDefaults,
      });
      store.setOperationMessage({
        tone: "success",
        message: appUiCopy(defaultLanguage, "已恢复教练默认设置。"),
      });
    },
  };
}
