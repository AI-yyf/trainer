import { useCallback, useMemo, type Dispatch, type SetStateAction } from "react";

import { trainerCommands } from "../../../../shared/src/commands";
import type { TrainerOperationMessage } from "../../../../shared/src/protocol";
import { evaluateProviderModelPolicy } from "../../../../shared/src/providerModelPolicy";
import {
  hasSavedProviderProfiles,
  providerBaseUrlIsLocalService,
} from "../../../../shared/src/providerStatus";
import {
  classifyProviderThinkingSupport,
  describeProviderThinking,
  normalizeProviderThinkingConfig,
  synthesizeProviderThinkingDescriptor,
  thinkingProtocolSupportsWire,
  type ProviderThinkingConfig,
  type ProviderThinkingDescriptor,
} from "../../../../shared/src/providerThinking";
import {
  buildComposerProviderMenuItems,
  compactComposerModelLabel,
  composerModelPolicyHint,
} from "../lib/composerModelHelpers";
import { appUiCopy } from "../lib/i18n/appUiCopy";
import {
  recoverableFailureMessage,
  type OperationMessageSurface,
} from "../lib/operationMessageGovernance";
import type {
  ActiveWorkbenchView,
  ComposerLanguage,
  HostMessage,
  ProviderConfigView,
} from "../lib/types";
import { postMessage } from "../lib/vscode";
import { loadBrowserPreviewModule, providerSettingsLocale } from "./appHelpers";
import { useComposerModelQuery } from "./useComposerModelQuery";
import type { ContextMenu } from "./useMenuState";
import { useWorkbenchState } from "./useWorkbenchState";

export interface UseComposerProviderControllerParams {
  providerConfig: ProviderConfigView;
  composerLanguage: ComposerLanguage;
  composerModelActionDensity: "compact" | "default";
  isBrowserPreview: boolean;
  previewSessionId: string | undefined;
  setPreviewSessionId: (sessionId?: string) => void;
  applyPreviewHostMessages: (messages: HostMessage[], isProviderAction?: boolean) => void;
  setActiveView: (view: ActiveWorkbenchView) => void;
  setOpenMenu: Dispatch<SetStateAction<ContextMenu>>;
  setOperationMessage: (
    message?: TrainerOperationMessage,
    surface?: OperationMessageSurface,
  ) => void;
}

export function useComposerProviderController({
  providerConfig,
  composerLanguage,
  composerModelActionDensity,
  isBrowserPreview,
  previewSessionId,
  setPreviewSessionId,
  applyPreviewHostMessages,
  setActiveView,
  setOpenMenu,
  setOperationMessage,
}: UseComposerProviderControllerParams) {
  const composerHasSavedProfiles = useMemo(
    () => hasSavedProviderProfiles(providerConfig),
    [providerConfig.profileCount, providerConfig.providerProfiles],
  );
  const composerProviderProfileLabel = useMemo(
    () =>
      providerConfig.configured ? providerConfig.profileLabel?.trim() || undefined : undefined,
    [providerConfig.configured, providerConfig.profileLabel],
  );

  const composerProviderCopy = providerSettingsLocale(composerLanguage);
  const composerModelButtonLabel = useMemo(() => {
    if (!providerConfig.configured) {
      return composerHasSavedProfiles
        ? composerProviderCopy.menu.chooseModel
        : composerProviderCopy.menu.model;
    }

    const resolvedModel = providerConfig.resolvedModel?.trim();
    if (resolvedModel) {
      return resolvedModel;
    }

    const configuredModel = providerConfig.model.trim();
    if (configuredModel) {
      return configuredModel;
    }

    if (composerProviderProfileLabel) {
      return composerProviderProfileLabel;
    }

    return composerProviderCopy.menu.model;
  }, [
    composerHasSavedProfiles,
    composerProviderCopy,
    composerProviderProfileLabel,
    providerConfig.configured,
    providerConfig.model,
    providerConfig.resolvedModel,
  ]);

  const composerModelButtonDisplayLabel =
    composerModelActionDensity === "compact"
      ? compactComposerModelLabel(
          composerModelButtonLabel,
          composerProviderProfileLabel ?? providerConfig.name,
          composerLanguage,
        )
      : composerModelButtonLabel;

  const composerActiveModelPolicy = useMemo(() => {
    const resolvedModel = providerConfig.resolvedModel?.trim() ?? "";
    const configuredModel = providerConfig.model.trim();
    return evaluateProviderModelPolicy(
      providerConfig.configured ? resolvedModel || configuredModel : "",
      {
        allowedModels: providerConfig.allowedModels,
        deniedModels: providerConfig.deniedModels,
      },
    );
  }, [
    providerConfig.allowedModels,
    providerConfig.configured,
    providerConfig.deniedModels,
    providerConfig.model,
    providerConfig.resolvedModel,
  ]);

  const composerActiveModelPolicyHint = composerModelPolicyHint(
    composerLanguage,
    composerActiveModelPolicy.reason,
  );
  const composerModelButtonTitle = !providerConfig.configured
    ? composerProviderCopy.menu.manageModels
    : composerActiveModelPolicyHint ??
      (composerProviderProfileLabel && composerProviderProfileLabel !== composerModelButtonLabel
        ? composerProviderCopy.menu.switchModelWithConnection
            .replace("{model}", composerModelButtonLabel)
            .replace("{connection}", composerProviderProfileLabel)
        : composerProviderCopy.menu.switchModel.replace("{model}", composerModelButtonLabel));

  const composerProviderMenuItems = useMemo(
    () => buildComposerProviderMenuItems(providerConfig, composerLanguage),
    [providerConfig, composerLanguage],
  );

  const {
    query: composerModelQuery,
    setQuery: setComposerModelQuery,
    filtered: filteredComposerProviderMenuItems,
  } = useComposerModelQuery(composerProviderMenuItems);

  const composerThinkingDescriptor = useMemo<ProviderThinkingDescriptor | undefined>(() => {
    if (!providerConfig.configured) {
      return undefined;
    }
    const lastTest = providerConfig.lastTestResult as
      | {
          capabilityEvidence?: Array<{
            name?: unknown;
            state?: unknown;
            observed?: unknown;
          }>;
        }
      | undefined;
    const model = providerConfig.resolvedModel ?? providerConfig.model;
    const context = {
      protocol: providerConfig.protocol,
      model,
      providerName: providerConfig.name,
      baseUrl: providerConfig.baseUrl,
      capabilityEvidence: lastTest?.capabilityEvidence,
      modelCapabilities: model ? providerConfig.modelCapabilities?.[model] : undefined,
      profileCapabilities: providerConfig.capabilities,
    };
    if (!thinkingProtocolSupportsWire(providerConfig.protocol)) {
      return undefined;
    }
    const support = classifyProviderThinkingSupport(context);
    if (support === "unsupported") {
      return undefined;
    }
    const storedThinking = normalizeProviderThinkingConfig(
      providerConfig.thinkingConfig,
      providerConfig.protocol,
    );
    const descriptor =
      describeProviderThinking(context, providerConfig.requestDefaults) ??
      synthesizeProviderThinkingDescriptor(context, storedThinking ?? { mode: "auto" });
    if (!descriptor) {
      return undefined;
    }
    return storedThinking ? { ...descriptor, config: storedThinking } : descriptor;
  }, [
    providerConfig.baseUrl,
    providerConfig.capabilities,
    providerConfig.configured,
    providerConfig.lastTestResult,
    providerConfig.model,
    providerConfig.modelCapabilities,
    providerConfig.name,
    providerConfig.protocol,
    providerConfig.requestDefaults,
    providerConfig.resolvedModel,
    providerConfig.thinkingConfig,
  ]);

  const openComposerModelSettings = useCallback(() => {
    setOpenMenu(undefined);
    setComposerModelQuery("");
    useWorkbenchState.getState().requestSettingsCategory("connection");
    setActiveView("settings");
  }, [setActiveView, setComposerModelQuery, setOpenMenu]);

  const toggleComposerModelMenu = useCallback(() => {
    if (!providerConfig.configured && !composerHasSavedProfiles) {
      openComposerModelSettings();
      return;
    }

    setOpenMenu((current) => (current === "model" ? undefined : "model"));
  }, [composerHasSavedProfiles, openComposerModelSettings, providerConfig.configured, setOpenMenu]);

  const refreshComposerProviderModels = useCallback(() => {
    if (!providerConfig.configured) {
      setOperationMessage({
        tone: "info",
        message: appUiCopy(composerLanguage, "先保存连接，再更新模型列表。"),
      });
      return;
    }

    if (
      !providerConfig.apiKeyConfigured &&
      !providerBaseUrlIsLocalService(providerConfig.baseUrl)
    ) {
      setOperationMessage({
        tone: "info",
        message: appUiCopy(composerLanguage, "先填写访问密钥，再更新模型列表。"),
      });
      return;
    }

    if (isBrowserPreview) {
      void loadBrowserPreviewModule()
        .then((browserPreview) =>
          browserPreview.refreshBrowserPreviewProviderModels(previewSessionId),
        )
        .then(({ sessionId, messages }) => {
          setPreviewSessionId(sessionId);
          applyPreviewHostMessages(messages, true);
        })
        .catch(() => {
          setOperationMessage({
            tone: "error",
            message: recoverableFailureMessage("provider", composerLanguage),
          });
        });
      return;
    }

    postMessage({
      type: "command/execute",
      payload: {
        commandId: trainerCommands.refreshProviderModels,
      },
    });
  }, [
    applyPreviewHostMessages,
    composerLanguage,
    isBrowserPreview,
    previewSessionId,
    providerConfig.apiKeyConfigured,
    providerConfig.baseUrl,
    providerConfig.configured,
    setOperationMessage,
    setPreviewSessionId,
  ]);

  const setComposerThinking = useCallback(
    (thinking: ProviderThinkingConfig) => {
      if (isBrowserPreview) {
        setOperationMessage({
          tone: "info",
          message: appUiCopy(composerLanguage, "预览模式不会保存思考强度。"),
        });
        return;
      }
      postMessage({
        type: "command/execute",
        payload: {
          commandId: trainerCommands.setProviderThinking,
          payload: { thinking },
        },
      });
    },
    [composerLanguage, isBrowserPreview, setOperationMessage],
  );

  const switchComposerProviderModel = useCallback(
    (model: string) => {
      const modelPolicy = evaluateProviderModelPolicy(model, {
        allowedModels: providerConfig.allowedModels,
        deniedModels: providerConfig.deniedModels,
      });
      if (!modelPolicy.allowed) {
        setOperationMessage({
          tone: "info",
          message:
            composerModelPolicyHint(composerLanguage, modelPolicy.reason) ??
            appUiCopy(composerLanguage, "\u8bf7\u5148\u9009\u62e9\u4e00\u4e2a\u53ef\u4ee5\u4f7f\u7528\u7684\u6a21\u578b\u3002"),
        });
        return;
      }

      setOpenMenu(undefined);
      setComposerModelQuery("");

      if (isBrowserPreview) {
        void loadBrowserPreviewModule()
          .then((browserPreview) =>
            browserPreview.switchBrowserPreviewProviderModel(modelPolicy.model, previewSessionId),
          )
          .then(({ sessionId, messages }) => {
            setPreviewSessionId(sessionId);
            applyPreviewHostMessages(messages, true);
          })
          .catch(() => {
            setOperationMessage({
              tone: "error",
              message: recoverableFailureMessage("provider", composerLanguage),
            });
          });
        return;
      }

      postMessage({
        type: "command/execute",
        payload: {
          commandId: trainerCommands.switchProviderModel,
          payload: {
            model: modelPolicy.model,
            reason: "composer_model_switch",
          },
        },
      });
    },
    [
      applyPreviewHostMessages,
      composerLanguage,
      isBrowserPreview,
      previewSessionId,
      providerConfig.allowedModels,
      providerConfig.deniedModels,
      setComposerModelQuery,
      setOpenMenu,
      setOperationMessage,
      setPreviewSessionId,
    ],
  );

  const switchComposerProviderModelForProfile = useCallback(
    (profileId: string, model: string) => {
      const normalizedProfileId = profileId.trim();
      if (
        !normalizedProfileId ||
        normalizedProfileId === providerConfig.profileId?.trim()
      ) {
        switchComposerProviderModel(model);
        return;
      }

      setOpenMenu(undefined);
      setComposerModelQuery("");

      if (isBrowserPreview) {
        void loadBrowserPreviewModule()
          .then(async (browserPreview) => {
            const switched = await browserPreview.switchBrowserPreviewProviderProfile(
              normalizedProfileId,
              previewSessionId,
            );
            applyPreviewHostMessages(switched.messages, true);
            setPreviewSessionId(switched.sessionId);
            return browserPreview.switchBrowserPreviewProviderModel(model, switched.sessionId);
          })
          .then(({ sessionId, messages }) => {
            setPreviewSessionId(sessionId);
            applyPreviewHostMessages(messages, true);
          })
          .catch(() => {
            setOperationMessage({
              tone: "error",
              message: recoverableFailureMessage("provider", composerLanguage),
            });
          });
        return;
      }

      postMessage({
        type: "command/execute",
        payload: {
          commandId: trainerCommands.switchProviderModel,
          payload: {
            profileId: normalizedProfileId,
            model,
            reason: "composer_model_switch",
          },
        },
      });
    },
    [
      applyPreviewHostMessages,
      composerLanguage,
      isBrowserPreview,
      previewSessionId,
      providerConfig.profileId,
      setComposerModelQuery,
      setOpenMenu,
      setOperationMessage,
      setPreviewSessionId,
      switchComposerProviderModel,
    ],
  );

  return {
    composerHasSavedProfiles,
    composerProviderProfileLabel,
    composerProviderCopy,
    composerModelButtonLabel,
    composerModelButtonDisplayLabel,
    composerActiveModelPolicy,
    composerActiveModelPolicyHint,
    composerModelButtonTitle,
    composerProviderMenuItems,
    composerModelQuery,
    setComposerModelQuery,
    filteredComposerProviderMenuItems,
    composerThinkingDescriptor,
    openComposerModelSettings,
    toggleComposerModelMenu,
    refreshComposerProviderModels,
    setComposerThinking,
    switchComposerProviderModel,
    switchComposerProviderModelForProfile,
  };
}
