import {
  useCallback,
  useEffect,
  useMemo,
  useRef
} from "react";
import { readTrainingCardList,readTrainingCardText } from "../lib/boundTrainingCardFacts";
import { CommandPalette } from "../templates/CommandPalette";

import { trainerCommands } from "../../../../shared/src/commands";
import {
  resolveTrainerSkillText,
  trainerSkillTriggerToken
} from "../../../../shared/src/skillCatalog";
import {
  composeTrainingCoachBridgeDraft
} from "../../../../shared/src/trainingCoachBridge";
import {
  ComposerContextMenu,
  ComposerModelMenu,
  ComposerResourcesMenu
} from "../components/composer";
import {
  SkillCubeIcon
} from "../components/icons";
import {
  appUiAltCopy,
  appUiCopy,
} from "../lib/i18n/appUiCopy";
import { resolvePlanComposerCopy } from "../lib/i18n/planComposerCopy";
import { PLAN_COPY } from "../lib/i18n/segments/planInlineText";
import { unifiedComposerCommands } from "../lib/unifiedComposerIntent";
import {
  postMessage
} from "../lib/vscode";
import { useComposerDockAnchor } from "./useComposerDockAnchor";
import {
  type PlanComposerMode
} from "./useLearningPlanController";
import { useTrainingAttemptLifecycle } from "./useTrainingCommands";

// ContextMenu type imported from useMenuState
import {
  type WorkbenchCtxAfterE5a
} from "./App";
import {
  COMPOSER_MODEL_PICKER_INITIAL_OPTION_LIMIT,
  RESOURCE_UPLOAD_LIMIT,
  UtilityComposerModeOption,
  focusComposerInput,
  sendContextShortSummary,
  trainingPersistenceFailureMessage,
  triggerResourceUpload,
  truncateInlineText
} from "./appHelpers";

export function useTrainingAttemptAndComposerModes(ctx: WorkbenchCtxAfterE5a) {
  const {
    planIsFrozen,
    resolvedPlanComposerMode,
    data,
    layout,
    setActiveView,
    setComposerDraft,
    setContextDetail,
    setIncludeRelatedFiles,
    setFollowCurrentFile,
    setOperationMessage,
    trainingComposerPracticeReturnMode,
    setTrainingComposerRoute,
    setTrainingVerifyNotice,
    requestTrainingPersistence,
    streaming,
    openMenu,
    setOpenMenu,
    selectedCommandIndex,
    setSelectedCommandIndex,
    dismissedComposerDeck,
    setDismissedComposerDeck,
    isBrowserPreview,
    activeView,
    t,
    composerDeckRef,
    streamResumeDraftRef,
    composerModelSearchRef,
    uploadFilesInputRef,
    uploadFolderInputRef,
    pendingTrainingHandoffSubmissionRef,
    requestCoachComposerFocus,
    draft,
    composerDraftScope,
    composerHasSavedProfiles,
    composerProviderCopy,
    composerProviderMenuItems,
    composerModelQuery,
    setComposerModelQuery,
    filteredComposerProviderMenuItems,
    composerThinkingDescriptor,
    refreshComposerProviderModels,
    setComposerThinking,
    switchComposerProviderModel,
    switchComposerProviderModelForProfile,
    hasFormalPlan,
    activePlanStage,
    leftoverTrainingHandoffChromeNotLive,
    leftoverResourceSelectedDetailNotLive,
    resolvedCoachFocus,
    resolvedCoachStage,
    recoveredDisplayFacts,
    formalPlanLive,
    livePlanTitle,
    livePlanSummary,
    liveSandboxState,
    trainingState,
    selectedTrainingCardCandidate,
    reviewArtifactForeground,
    trainingCardType,
    activeTrainingCardId,
    selectedTrainingRouteCard,
    activityDraft,
    setActivityDraft,
    visibleTrainingCardTitle,
    trainingFilesToTouch,
    trainingDeliverables,
    authoritativeVerifyItems,
    trainingNextAfterCompletionText,
    trainingFallbackActionText,
    trainingHandoffReflectionRequired,
    trainingHandoffReturnRequired,
    trainingHandoffId,
    practiceExpectedSymbols,
    trainingCardVerified,
    trainingCardBlocked,
    trainingComposerReflectReason,
    trainingComposerStudyMode,
    trainingCoachBridge,
    trainingComposerSelectedVerifyItem,
    boundTrainingCardFacts,
    trainingComposerManualPracticeMode,
    trainingComposerFilePracticeMode,
    trainingComposerReflectMode,
    trainingComposerReturnMode,
    customSkills,
    availableSkillCatalog,
    selectSkillSuggestion,
    openSkillSettings,
    composerUsesTrainingFlow,
    activeSkillDraft,
    matchingLocalSkills,
    matchingLocalCommands,
    runComposerCommand,
  } = ctx;
  // Phase-D training attempt lifecycle: entering a formal card starts/resumes
  // an attempt; the Try draft is throttled into attempt updates; hints bump
  // the assistance level; return closes the lifecycle. Identity fields are
  // derived server-side from the persisted attempt.
  // Rules of Hooks: call the hook at top level. It returns a stable identity
  // (internal useMemo), so the dependent effects below do not re-fire per render.
  const attemptLifecycle = useTrainingAttemptLifecycle();
  // The start/recover effect reads the active file as a snapshot only; keeping
  // it in a ref avoids making a file switch restart the attempt.
  const attemptStartFilePathRef = useRef<string | undefined>(data.liveContext?.activeFile);
  attemptStartFilePathRef.current = data.liveContext?.activeFile;

  // When a formal training card becomes active, start or resume its attempt.
  useEffect(() => {
    if (activeView !== "training" || !activeTrainingCardId || isBrowserPreview || trainingComposerReturnMode || reviewArtifactForeground) {
      return;
    }
    attemptLifecycle.startOrRecover(activeTrainingCardId, {
      filePath: attemptStartFilePathRef.current ?? undefined,
    });
  }, [activeView, activeTrainingCardId, attemptLifecycle, isBrowserPreview, trainingComposerReturnMode, reviewArtifactForeground]);

  const handleHintReveal = useCallback(
    (hintLevel: number) => {
      if (!activeTrainingCardId || isBrowserPreview) {
        return;
      }
      const clamped = Math.min(3, Math.max(1, hintLevel));
      attemptLifecycle.updateAssistance(activeTrainingCardId, `hint_level_${clamped}`);
    },
    [activeTrainingCardId, attemptLifecycle, isBrowserPreview],
  );

  const checkRemoteRunnerBoundary = useCallback((): string | null => {
    // TR-100: remote workspace without a runner must not silently verify.
    const wsRoot = data.memory.workspace?.workspaceId ?? "";
    if (!wsRoot) return null;
    // VS Code remote workspaces use vscode-remote:// or ssh:// URI schemes.
    const isRemote = wsRoot.startsWith("vscode-remote://") || wsRoot.startsWith("ssh://");
    if (!isRemote) return null;
    return "Remote workspace detected but no remote verification runner is available. Trainer will not run local checks against a remote project.";
  }, [data.memory.workspace?.workspaceId]);

  const handleVerifyTrainingFromIde = useCallback(() => {
    const boundaryNotice = checkRemoteRunnerBoundary();
    if (boundaryNotice) {
      // The card owns this notice; the surface is no longer pre-set — the
      // following verify failure carries the training marker and scopes itself.
      setTrainingVerifyNotice(boundaryNotice);
      return;
    }
    if (isBrowserPreview || leftoverTrainingHandoffChromeNotLive || !activeTrainingCardId) {
      const notice = leftoverTrainingHandoffChromeNotLive
        ? appUiCopy(layout.composerLanguage, "验证未通过：当前训练卡片不是实时状态。")
        : !activeTrainingCardId
          ? appUiCopy(layout.composerLanguage, "没有可验证的当前文件。")
          : appUiCopy(layout.composerLanguage, "预览不能验真实工作区文件。请回 VS Code 打开文件后再验证。");
      setTrainingVerifyNotice(notice);
      return;
    }
    postMessage({
      type: "command/execute",
      payload: {
        commandId: trainerCommands.evaluateCurrentFile,
        payload: {
          source: "training",
          trainingPhase: "verify",
          cardId: activeTrainingCardId,
          cardTitle: readTrainingCardText(boundTrainingCardFacts, "title", () => visibleTrainingCardTitle),
          acceptanceCriteria: boundTrainingCardFacts
            ? boundTrainingCardFacts.lists.acceptanceCriteria ?? boundTrainingCardFacts.lists.verificationSteps ?? []
            : selectedTrainingCardCandidate?.acceptanceCriteria?.length
              ? selectedTrainingCardCandidate.acceptanceCriteria
              : selectedTrainingRouteCard?.acceptanceCriteria?.length
                ? selectedTrainingRouteCard.acceptanceCriteria
                : authoritativeVerifyItems,
          learnerDeliverables: readTrainingCardList(boundTrainingCardFacts, "learnerDeliverables", () => trainingDeliverables),
          expectedSymbols: trainingCardType === "practice" ? readTrainingCardList(boundTrainingCardFacts, "expectedSymbols", () => practiceExpectedSymbols) : [],
          filesToTouch: readTrainingCardList(boundTrainingCardFacts, "filesToTouch", () => trainingFilesToTouch),
        },
      },
    });
  }, [
    leftoverTrainingHandoffChromeNotLive,
    activeTrainingCardId,
    boundTrainingCardFacts,
    authoritativeVerifyItems,
    selectedTrainingCardCandidate?.acceptanceCriteria,
    selectedTrainingRouteCard?.acceptanceCriteria,
    isBrowserPreview,
    layout.composerLanguage,
    trainingFilesToTouch,
    practiceExpectedSymbols,
    setOperationMessage,
    trainingCardType,
    trainingDeliverables,
    visibleTrainingCardTitle,
  ]);

  const handleSubmitTrainingEvidence = useCallback(async (evidence: string, returnMode = trainingComposerPracticeReturnMode): Promise<boolean> => {
    if (leftoverTrainingHandoffChromeNotLive) {
      return false;
    }
    const normalizedEvidence = evidence.trim();
    if (reviewArtifactForeground && trainingState?.reviewArtifact?.id) {
      if (!normalizedEvidence) {
        return false;
      }
      await requestTrainingPersistence(trainerCommands.trainingReviewArtifactAction, {
        reviewArtifactId: trainingState.reviewArtifact.id,
        action: "resolved",
        note: normalizedEvidence,
      });
      return true;
    }
    const shouldSubmitTrainingHandoffReturn =
      trainingComposerReturnMode &&
      trainingHandoffReturnRequired &&
      Boolean(activeTrainingCardId);
    if (shouldSubmitTrainingHandoffReturn && activeTrainingCardId) {
      pendingTrainingHandoffSubmissionRef.current = {
        phase: "return",
        cardId: activeTrainingCardId,
      };
      try {
        await requestTrainingPersistence(trainerCommands.trainingReturn, {
          cardId: activeTrainingCardId,
          handoffId: trainingHandoffId ?? "",
        });
      } catch (error) {
        pendingTrainingHandoffSubmissionRef.current = undefined;
        throw error;
      }
      return false;
    }

    if (!normalizedEvidence) {
      return false;
    }

    const practiceResultMode = returnMode === "result";
    const practiceBlockedMode = returnMode === "blocked";

    const shouldSubmitTrainingHandoffReflection =
      trainingComposerReflectMode &&
      trainingHandoffReflectionRequired &&
      Boolean(activeTrainingCardId);
    if (shouldSubmitTrainingHandoffReflection && activeTrainingCardId) {
      pendingTrainingHandoffSubmissionRef.current = {
        phase: "reflect",
        cardId: activeTrainingCardId,
      };
      try {
        await requestTrainingPersistence(trainerCommands.trainingReflect, {
          cardId: activeTrainingCardId,
          handoffId: trainingHandoffId ?? "",
          reflection: normalizedEvidence,
        });
      } catch (error) {
        pendingTrainingHandoffSubmissionRef.current = undefined;
        throw error;
      }
      return false;
    }

    if (trainingComposerStudyMode && activeTrainingCardId) {
      await requestTrainingPersistence(trainerCommands.trainingCardStatusTransition, {
        cardId: activeTrainingCardId,
        newStatus: "active",
        reason: "study_note_submitted",
      });
    }

    const shouldReviewAnsweredFlash =
      trainingComposerReflectMode &&
      trainingComposerReflectReason === "flash_answered" &&
      activeTrainingCardId;

    if (shouldReviewAnsweredFlash && activeTrainingCardId) {
      await requestTrainingPersistence(trainerCommands.trainingCardStatusTransition, {
        cardId: activeTrainingCardId,
        newStatus: "reviewed",
        reason: "flash_reflection_submitted",
      });
    }

    const shouldSubmitManualPracticeReturn =
      trainingComposerManualPracticeMode && activeTrainingCardId;
    const shouldSubmitBlockedFilePracticeReturn =
      trainingComposerFilePracticeMode && practiceBlockedMode && activeTrainingCardId;

    let authoritativePracticeStatus: string | undefined;
    if ((shouldSubmitManualPracticeReturn || shouldSubmitBlockedFilePracticeReturn) && activeTrainingCardId) {
      const passed = Boolean(shouldSubmitManualPracticeReturn && practiceResultMode);
      // commandId: trainerCommands.trainingPracticeReturn — persist the single-card practice return.
      const response = await requestTrainingPersistence(trainerCommands.trainingPracticeReturn, {
        cardId: activeTrainingCardId,
        passed,
        summary: normalizedEvidence,
        nextStep: passed
          ? (trainingNextAfterCompletionText ?? trainingState?.latestLearningFollowup ?? "")
          : (trainingFallbackActionText ?? trainingState?.latestLearningFollowup ?? ""),
        focusArea:
          trainingState?.latestLearningFocusArea ??
          selectedTrainingCardCandidate?.focusArea ??
          selectedTrainingRouteCard?.focusArea ??
          resolvedCoachFocus ??
          "",
        failedChecks:
          passed || !trainingComposerSelectedVerifyItem
            ? []
            : [trainingComposerSelectedVerifyItem],
        evidenceSource: "learner_return",
      });
      const workspace =
        response && typeof response === "object" && !Array.isArray(response)
          ? (response as { workspace?: unknown }).workspace
          : undefined;
      const selectedCardStatus =
        workspace && typeof workspace === "object" && !Array.isArray(workspace)
          ? (workspace as { selected_card_status?: unknown }).selected_card_status
          : undefined;
      authoritativePracticeStatus =
        typeof selectedCardStatus === "string" ? selectedCardStatus : undefined;
    }

    const manualPracticeBlocked =
      trainingComposerManualPracticeMode && practiceBlockedMode;
    const filePracticeBlocked = trainingComposerFilePracticeMode && practiceBlockedMode;
    const trainingFailureOutcome =
      manualPracticeBlocked ||
      filePracticeBlocked ||
      trainingCardBlocked ||
      authoritativePracticeStatus === "blocked";
    const trainingPassOutcome =
      authoritativePracticeStatus === "active" ||
      (!authoritativePracticeStatus && trainingCardVerified);

    await requestTrainingPersistence(trainerCommands.evidenceEnqueue, {
      source: "learning_signal",
      summary: normalizedEvidence,
      concepts: [
        trainingState?.latestLearningFocusArea,
        selectedTrainingCardCandidate?.focusArea,
        resolvedCoachFocus,
      ].filter((value): value is string => Boolean(value?.trim())),
      outcome: trainingFailureOutcome ? "fail" : trainingPassOutcome ? "pass" : "note",
      sourceCardId: activeTrainingCardId,
      targetPlanStageId: activePlanStage?.id,
      confidence: trainingPassOutcome ? 0.86 : trainingFailureOutcome ? 0.52 : 0.68,
    });
    return true;
  }, [
    activePlanStage?.id,
    activeTrainingCardId,
    leftoverTrainingHandoffChromeNotLive,
    requestTrainingPersistence,
    reviewArtifactForeground,
    resolvedCoachFocus,
    selectedTrainingCardCandidate?.focusArea,
    selectedTrainingRouteCard?.focusArea,
    trainingComposerFilePracticeMode,
    trainingComposerReflectMode,
    trainingComposerReflectReason,
    trainingComposerReturnMode,
    trainingCardBlocked,
    trainingComposerManualPracticeMode,
    trainingComposerPracticeReturnMode,
    trainingComposerSelectedVerifyItem,
    trainingComposerStudyMode,
    trainingCardVerified,
    trainingFallbackActionText,
    trainingHandoffReflectionRequired,
    trainingHandoffReturnRequired,
    trainingHandoffId,
    trainingNextAfterCompletionText,
    trainingState?.latestLearningFocusArea,
    trainingState?.latestLearningFollowup,
    trainingState?.reviewArtifact?.id,
  ]);

  const handleResumeTrainingInCoach = useCallback(() => {
    if (leftoverTrainingHandoffChromeNotLive) {
      setActiveView("coach");
      requestCoachComposerFocus();
      return;
    }
    if (reviewArtifactForeground && trainingState?.reviewArtifact?.status === "resolved") {
      const title = trainingState.reviewArtifact.title ?? trainingState.reviewArtifact.focusArea ?? "review";
      const result = trainingState.reviewArtifact.verifiedResult ?? trainingState.reviewArtifact.summary ?? "";
      setActiveView("coach");
      setComposerDraft(
        appUiCopy(layout.composerLanguage, "我完成了“{t}”的回顾。结论：{r}\n\n请帮我安排下一步。")
          .replace("{t}", () => title)
          .replace("{r}", () => result),
      );
      requestCoachComposerFocus();
      return;
    }

    if (trainingHandoffReflectionRequired) {
      setTrainingComposerRoute("card");
      setActivityDraft("");
      window.requestAnimationFrame(() => {
        focusComposerInput();
      });
      return;
    }

    if (trainingHandoffReturnRequired && trainingState?.selectedCardId) {
      void handleSubmitTrainingEvidence("").catch(() => {
        setOperationMessage({
          tone: "error",
          message: trainingPersistenceFailureMessage(layout.composerLanguage),
        });
      });
      return;
    }

    setActiveView("coach");
    setComposerDraft(composeTrainingCoachBridgeDraft(trainingCoachBridge));
    requestCoachComposerFocus();
  }, [
    handleSubmitTrainingEvidence,
    layout.composerLanguage,
    leftoverTrainingHandoffChromeNotLive,
    requestCoachComposerFocus,
    reviewArtifactForeground,
    setActiveView,
    setComposerDraft,
    setOperationMessage,
    trainingCoachBridge,
    trainingHandoffReflectionRequired,
    trainingHandoffReturnRequired,
    trainingState?.reviewArtifact?.focusArea,
    trainingState?.reviewArtifact?.status,
    trainingState?.reviewArtifact?.summary,
    trainingState?.reviewArtifact?.title,
    trainingState?.reviewArtifact?.verifiedResult,
    trainingState?.selectedCardId,
  ]);


  const selectedResourceNavigationLabel = leftoverResourceSelectedDetailNotLive
    ? undefined
    : truncateInlineText(
        data.memory.selectedResourceDetail?.title ??
          data.memory.selectedResourceDetail?.sandboxPath ??
          liveSandboxState?.selectedPath,
        layout.composerLanguage === "zh-CN" ? 22 : 46,
      ) ??
      truncateInlineText(
        data.memory.selectedResourceDetail?.source,
        layout.composerLanguage === "zh-CN" ? 22 : 46,
      );
  const dockStageProgressLabel = hasFormalPlan && activePlanStage
    ? PLAN_COPY[layout.composerLanguage].stageProgress
        .replace(
          "{index}",
          String(
            data.plan.stages.findIndex((stage) => stage.id === activePlanStage.id) + 1,
          ),
        )
        .replace("{total}", String(data.plan.stages.length))
    : null;
  const dockAnchorControl = useComposerDockAnchor(
    activeView,
    activePlanStage?.title,
    dockStageProgressLabel,
    selectedResourceNavigationLabel,
  );
  const planComposerModes = useMemo<UtilityComposerModeOption<PlanComposerMode>[]>(() => {
    const planComposerText = resolvePlanComposerCopy(layout.composerLanguage);
    const isZh = layout.composerLanguage === "zh-CN";
    const stageLabel =
      truncateInlineText(
        formalPlanLive
          ? activePlanStage?.title ?? resolvedCoachStage ?? resolvedCoachFocus ?? livePlanSummary
          : recoveredDisplayFacts.currentStep || livePlanTitle,
        isZh ? 22 : 48,
      ) ?? planComposerText.currentThread;
    const explainMode = planComposerText.modes.explain;
    const generateMode = planComposerText.modes.generate;
    const evidenceMode = planComposerText.modes.evidence;
    const blockerMode = planComposerText.modes.blocker;
    const modes: UtilityComposerModeOption<PlanComposerMode>[] = [
      {
        id: "explain",
        label: explainMode.label,
        header: stageLabel,
        summary: `${planComposerText.planLabel} · ${explainMode.label}`,
        hint: explainMode.hint,
        placeholder: explainMode.placeholder,
        accessibilityLabel: explainMode.accessibilityLabel,
        prompts: [
          {
            id: "plan-explain-stage",
            label: explainMode.primaryPrompt.label,
            prompt: explainMode.primaryPrompt.prompt,
          },
          {
            id: "plan-why-now",
            label: explainMode.secondaryPrompt.label,
            prompt: explainMode.secondaryPrompt.prompt,
          },
        ],
      },
      {
        id: "generate",
        label: generateMode.label,
        header: generateMode.header,
        summary: `${planComposerText.planLabel} · ${generateMode.label}`,
        hint: generateMode.hint,
        placeholder: generateMode.placeholder,
        accessibilityLabel: generateMode.accessibilityLabel,
        prompts: [
          {
            id: "plan-generate",
            label: generateMode.primaryPrompt.label,
            prompt: generateMode.primaryPrompt.prompt,
          },
          {
            id: "plan-restructure",
            label: generateMode.secondaryPrompt.label,
            prompt: generateMode.secondaryPrompt.prompt,
          },
        ],
      },
      {
        id: "evidence",
        label: evidenceMode.label,
        header: evidenceMode.header,
        summary: `${planComposerText.planLabel} · ${evidenceMode.label}`,
        hint: evidenceMode.hint,
        placeholder: evidenceMode.placeholder,
        accessibilityLabel: evidenceMode.accessibilityLabel,
        prompts: [
          {
            id: "plan-evidence-note",
            label: evidenceMode.primaryPrompt.label,
            prompt: evidenceMode.primaryPrompt.prompt,
          },
          {
            id: "plan-adoption-gap",
            label: evidenceMode.secondaryPrompt.label,
            prompt: evidenceMode.secondaryPrompt.prompt,
          },
        ],
      },
      {
        id: "blocker",
        label: blockerMode.label,
        header: blockerMode.header,
        summary: `${planComposerText.planLabel} · ${blockerMode.label}`,
        hint: blockerMode.hint,
        placeholder: blockerMode.placeholder,
        accessibilityLabel: blockerMode.accessibilityLabel,
        prompts: [
          {
            id: "plan-shrink-next",
            label: blockerMode.primaryPrompt.label,
            prompt: blockerMode.primaryPrompt.prompt,
          },
          {
            id: "plan-blocker",
            label: blockerMode.secondaryPrompt.label,
            prompt: blockerMode.secondaryPrompt.prompt,
          },
        ],
      },
    ];
    return planIsFrozen ? modes.filter((mode) => mode.id !== "generate") : modes;
  }, [
    activePlanStage?.title,
    data.plan.stages.length,
    formalPlanLive,
    livePlanSummary,
    livePlanTitle,
    layout.composerLanguage,
    recoveredDisplayFacts.currentStep,
    resolvedCoachFocus,
    resolvedCoachStage,
  ]);
  const activePlanComposerMode =
    planComposerModes.find((mode) => mode.id === resolvedPlanComposerMode) ??
    planComposerModes[0];

  const handleCancelStream = useCallback((options?: { restoreDraft?: boolean }) => {
    if (!streaming.isStreaming) {
      return;
    }
    const shouldRestoreDraft =
      options && typeof options === "object" && "restoreDraft" in options
        ? options.restoreDraft !== false
        : true;
    const resumeDraft = streamResumeDraftRef.current;
    if (shouldRestoreDraft && resumeDraft.trim() && !draft.trim()) {
      // Restore the sent text only when the learner has not already started
      // editing a new draft while the reply was in flight.
      setComposerDraft(resumeDraft);
    }
    postMessage({
      type: "session/cancelStreamMessage",
      payload: streaming.streamMessageId ? { messageId: streaming.streamMessageId } : undefined,
    });
  }, [draft, setComposerDraft, streaming.isStreaming, streaming.streamMessageId]);

  const streamWasActiveRef = useRef(streaming.isStreaming);
  // §3.7 red line 5 (stay mode): the store owns the stay-send marker and the
  // returnToSurface notice (raised inside the stream/complete reducer, so a
  // batched fixture completion still closes the loop); the App only navigates
  // or dismisses.
  useEffect(() => {
    if (!openMenu) {
      return;
    }
    const dismiss = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setOpenMenu(undefined);
      }
    };
    document.addEventListener("keydown", dismiss, true);
    return () => document.removeEventListener("keydown", dismiss, true);
  }, [openMenu, setOpenMenu]);

  useEffect(() => {
    const wasActive = streamWasActiveRef.current;
    streamWasActiveRef.current = streaming.isStreaming;
    if (wasActive && !streaming.isStreaming && streaming.completionStopReason !== "cancelled") {
      streamResumeDraftRef.current = "";
    }
  }, [streaming.completionStopReason, streaming.isStreaming]);

  const renderComposerAccessory = () => {
    if (!openMenu) {
      return null;
    }

    if (openMenu === "resources") {
      return (
        <ComposerResourcesMenu
          copy={t}
          composerLanguage={layout.composerLanguage}
          localize={appUiCopy}
          resources={data.resources}
          isBrowserPreview={isBrowserPreview}
          uploadInputRefs={{ filesInputRef: uploadFilesInputRef, folderInputRef: uploadFolderInputRef }}
          uploadLimit={RESOURCE_UPLOAD_LIMIT}
          onTriggerUpload={triggerResourceUpload}
        />
      );
    }

    if (openMenu === "model") {
      return (
        <ComposerModelMenu
          copy={t}
          providerCopy={composerProviderCopy}
          composerLanguage={layout.composerLanguage}
          localize={appUiCopy}
          localizeAlt={appUiAltCopy}
          providerConfig={data.providerConfig}
          menuItems={composerProviderMenuItems}
          filteredMenuItems={filteredComposerProviderMenuItems}
          hasSavedProfiles={composerHasSavedProfiles}
          modelQuery={composerModelQuery}
          onModelQueryChange={setComposerModelQuery}
          modelSearchRef={composerModelSearchRef}
          thinkingDescriptor={composerThinkingDescriptor}
          onThinkingChange={setComposerThinking}
          onRefreshModels={refreshComposerProviderModels}
          onSwitchModel={switchComposerProviderModel}
          onSwitchProviderModel={switchComposerProviderModelForProfile}
          initialOptionLimit={COMPOSER_MODEL_PICKER_INITIAL_OPTION_LIMIT}
        />
      );
    }

    return (
      <ComposerContextMenu
        copy={t}
        contextSummary={sendContextShortSummary(data, layout, t) ?? ""}
        relatedFilesCount={data.liveContext.relatedFiles.length}
        includeRelatedFiles={layout.includeRelatedFiles}
        followCurrentFile={layout.followCurrentFile}
        contextDetail={layout.contextDetail}
        onToggleRelatedFiles={() => setIncludeRelatedFiles(!layout.includeRelatedFiles)}
        onToggleFollowCurrentFile={() => setFollowCurrentFile(!layout.followCurrentFile)}
        onContextDetailChange={setContextDetail}
      />
    );
  };

  const unifiedCommandSuggestions = unifiedComposerCommands(composerUsesTrainingFlow ? activityDraft : draft, layout.composerLanguage);
  const selectUnifiedCommand = (command: string) => {
    const value = command + " ";
    if (composerUsesTrainingFlow) setActivityDraft(value);
    else setComposerDraft(value, composerDraftScope);
    setDismissedComposerDeck("command");
    requestCoachComposerFocus();
  };
  const renderCommandDeck = () => {
    if (
      dismissedComposerDeck === "command" ||
      !((composerUsesTrainingFlow ? activityDraft : draft).trim().startsWith("/")) ||
      (unifiedCommandSuggestions.length === 0 && (composerUsesTrainingFlow || matchingLocalCommands.length === 0))
    ) {
      return null;
    }

    return (
      <div ref={composerDeckRef} className="command-deck" role="list" aria-label={t.slashCommands}>
        <div className="command-deck__header">
          <strong>{t.slashCommands}</strong>
          <span className="command-deck__hint">
            {appUiCopy(layout.composerLanguage, "Enter 执行，Tab 补全。")}
          </span>
        </div>
        <div className="command-deck__list">
          {unifiedCommandSuggestions.map((command) => (
            <button key={command} type="button" className="command-deck__item"
              onClick={() => selectUnifiedCommand(command)}>
              <span className="command-deck__command">{command}</span>
            </button>
          ))}
          {(composerUsesTrainingFlow ? [] : matchingLocalCommands).map((command) => (
            <button
              key={command.command}
              className={`command-deck__item ${
                matchingLocalCommands[selectedCommandIndex]?.command === command.command ? "is-active" : ""
              }`}
              type="button"
              aria-label={`${command.command}: ${command.title}`}
              title={[command.command, command.title, command.description].filter(Boolean).join(" · ")}
              onMouseEnter={() => {
                const index = matchingLocalCommands.findIndex((item) => item.command === command.command);
                if (index >= 0) {
                  setSelectedCommandIndex(index);
                }
              }}
              onClick={() => {
                runComposerCommand(command);
              }}
            >
              <span className="command-deck__command">{command.command}</span>
              <span className="command-deck__body">
                <strong>{command.title}</strong>
                <span>{command.description}</span>
              </span>
            </button>
          ))}
        </div>
      </div>
    );
  };

  const renderSkillDeck = () => {
    if (dismissedComposerDeck === "skill" || !activeSkillDraft.startsWith("$")) return null;
    const draftTriggerToken = trainerSkillTriggerToken(activeSkillDraft) ?? "$";
    const creatableTrigger = draftTriggerToken.length > 1 && !availableSkillCatalog.some((skill) => skill.trigger.toLowerCase() === draftTriggerToken.toLowerCase()) ? draftTriggerToken : undefined;
    const customSkillIds = new Set(customSkills.map((skill) => skill.id));
    return <CommandPalette containerRef={composerDeckRef} label={appUiCopy(layout.composerLanguage, "技能")}
      groupLabel={appUiCopy(layout.composerLanguage, "技能")}
      empty={appUiCopy(layout.composerLanguage, "没有匹配到 skill。继续输入，或者直接当作普通消息发送。")}
      moreLabel={appUiCopy(layout.composerLanguage, "↓ 还有 {n} 条")}
      selectedIndex={selectedCommandIndex} onHighlight={setSelectedCommandIndex}
      entries={matchingLocalSkills.map((skill) => ({ id: skill.id, trigger: skill.trigger,
        title: resolveTrainerSkillText(skill.title, layout.composerLanguage),
        detail: resolveTrainerSkillText(skill.detail, layout.composerLanguage),
        icon: <SkillCubeIcon size={16} />,
        tag: customSkillIds.has(skill.id) ? appUiCopy(layout.composerLanguage, "个人") : undefined,
        onSelect: () => selectSkillSuggestion(skill) }))}
      footer={<><button type="button" className="template-back" onClick={() => openSkillSettings(creatableTrigger)}>{creatableTrigger ? appUiCopy(layout.composerLanguage, "创建技能 {v}").replace("{v}", creatableTrigger) : appUiCopy(layout.composerLanguage, "管理技能")}</button></>} />;
  };


  return {
    attemptLifecycle,
    handleHintReveal,
    handleVerifyTrainingFromIde,
    handleSubmitTrainingEvidence,
    handleResumeTrainingInCoach,
    selectedResourceNavigationLabel,
    dockStageProgressLabel,
    dockAnchorControl,
    activePlanComposerMode,
    handleCancelStream,
    renderComposerAccessory,
    unifiedCommandSuggestions,
    selectUnifiedCommand,
    renderCommandDeck,
    renderSkillDeck,
  };
}
