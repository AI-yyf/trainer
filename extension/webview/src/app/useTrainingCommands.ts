import { useCallback } from "react";
import { trainerCommands } from "../../../../shared/src/commands";
import { postMessage } from "../lib/vscode";
import type { ActiveWorkbenchView } from "../lib/types";

const TRAINING_PERSISTENCE_REQUEST_ID_KEY = "__trainerTrainingPersistenceId";

/** Fail-closed: these must carry a persistence id so host request_id is non-empty. */
const DURABLE_TRAINING_COMMAND_IDS = new Set<string>([
  trainerCommands.trainingCardStatusTransition,
  trainerCommands.trainingReflect,
  trainerCommands.trainingReturn,
  trainerCommands.trainingAttemptStart,
  trainerCommands.trainingAttemptUpdate,
  trainerCommands.trainingAttemptEvidence,
  trainerCommands.trainingAttemptRecover,
  trainerCommands.trainingAttemptClose,
]);

function sendTrainingCommand(commandId: string, payload: Record<string, unknown>): void {
  postMessage({
    type: "command/execute",
    payload: { commandId, payload },
  });
}

export interface TrainingAttemptLifecycle {
  /** 进入/恢复正式卡片时调用:幂等 start/recover。 */
  startOrRecover: (cardId: string, options?: { filePath?: string; fileHash?: string; fileVersion?: number }) => void;
  /** Try 草稿变化:由调用方节流后调用。 */
  updateDraft: (attemptId: string, answerDraft: string) => void;
  /** 使用提示后:推进 assistance level。 */
  /** §五: record hint usage against the card's active attempt (server resolves it). */
  updateAssistance: (cardId: string, assistanceLevel: string) => void;
  /** Verify 完成:提交证据绑定(身份服务端从 attempt 派生;trust 级别由服务端定)。 */
  submitEvidence: (
    attemptId: string,
    evidence: {
      artifactHash: string;
      result: string;
      runnerVersion?: string;
      executionLocation?: string;
      limitations?: string[];
      /** Optional citation anchor; the server resolves version/hash/location. */
      resourceId?: string;
      resourceVersionId?: string;
    },
  ) => void;
  /** Reflect 提交后保持同一 attempt(无需新调用,占位语义清晰)。 */
  keepSameAttempt: () => void;
  /** Return:关闭生命周期,历史保留。 */
  close: (attemptId: string) => void;
}

export function useTrainingAttemptLifecycle(): TrainingAttemptLifecycle {
  return {
    startOrRecover: (cardId, options) => {
      sendTrainingCommand(trainerCommands.trainingAttemptStart, {
        cardId,
        ...(options ?? {}),
      });
    },
    updateDraft: (attemptId, answerDraft) => {
      sendTrainingCommand(trainerCommands.trainingAttemptUpdate, {
        attemptId,
        answerDraft,
      });
    },
    updateAssistance: (cardId, assistanceLevel) => {
      sendTrainingCommand(trainerCommands.trainingAttemptUpdate, {
        cardId,
        assistanceLevel,
      });
    },
    submitEvidence: (attemptId, evidence) => {
      sendTrainingCommand(trainerCommands.trainingAttemptEvidence, {
        attemptId,
        ...evidence,
      });
    },
    keepSameAttempt: () => undefined,
    close: (attemptId) => {
      sendTrainingCommand(trainerCommands.trainingAttemptClose, { attemptId });
    },
  };
}

type TrainingCoachBridgeInput = {
  title: string;
  prompt: string;
  detail: string;
  ctaLabel: string;
  summaryLines: string[];
};

type FlashPracticeBridgeInput = {
  cardId: string;
  cardTitle: string;
  focusArea: string;
  prompt: string;
};

type PracticeFileVerificationRequestInput = {
  cardId: string;
  cardTitle: string;
  acceptanceCriteria: string[];
  learnerDeliverables: string[];
};

type RequestTrainingPersistence = (
  commandId: string,
  payload: Record<string, unknown>,
) => Promise<unknown>;

type TrainingCommandBridgeOptions = {
  onOpenCoachWithBridge?: (bridge: TrainingCoachBridgeInput) => void;
  /** Same App wrapper that stamps __trainerTrainingPersistenceId before host relay. */
  requestTrainingPersistence?: RequestTrainingPersistence;
};

export function useTrainingCommands(
  setActiveView: (view: ActiveWorkbenchView) => void,
  { onOpenCoachWithBridge, requestTrainingPersistence }: TrainingCommandBridgeOptions = {},
) {
  const sendDurableTrainingCommand = useCallback(
    (commandId: string, payload: Record<string, unknown>) => {
      if (!DURABLE_TRAINING_COMMAND_IDS.has(commandId)) {
        sendTrainingCommand(commandId, payload);
        return;
      }
      if (requestTrainingPersistence) {
        void requestTrainingPersistence(commandId, payload);
        return;
      }
      const existing = payload[TRAINING_PERSISTENCE_REQUEST_ID_KEY];
      const persistenceId =
        typeof existing === "string" && existing.trim()
          ? existing.trim()
          : `training-persistence-${Date.now().toString(36)}`;
      sendTrainingCommand(commandId, {
        ...payload,
        [TRAINING_PERSISTENCE_REQUEST_ID_KEY]: persistenceId,
      });
    },
    [requestTrainingPersistence],
  );

  const onRefreshTask = useCallback((focusArea?: string) => {
    sendTrainingCommand(trainerCommands.trainingGenerateCard, {
      focusArea,
      cardType: "practice",
      submode: "practice",
    });
  }, []);

  const onOpenCoachFromPractice = useCallback((bridge: TrainingCoachBridgeInput) => {
    if (onOpenCoachWithBridge) {
      onOpenCoachWithBridge(bridge);
      return;
    }
    setActiveView("coach");
  }, [onOpenCoachWithBridge, setActiveView]);

  const onRefreshDeck = useCallback(() => {
    sendTrainingCommand(trainerCommands.trainingGenerateCard, { submode: "flash" });
  }, []);

  const onSubmitFlashAnswer = useCallback((payload: Record<string, unknown>) => {
    sendTrainingCommand(trainerCommands.trainingFlashcardAnswer, payload);
  }, []);

  const onSubmitTheoryDrillAnswer = useCallback((payload: Record<string, unknown>) => {
    sendTrainingCommand(trainerCommands.trainingTheoryDrillAnswer, payload);
  }, []);

  const onTheoryDrillAction = useCallback((payload: Record<string, unknown>) => {
    sendTrainingCommand(trainerCommands.trainingTheoryDrillAnswer, { ...payload, action: payload.action });
  }, []);

  const onOpenCoachFromFlash = useCallback(() => setActiveView("coach"), [setActiveView]);
  const onOpenCoachBridgeFromFlash = useCallback((bridge: TrainingCoachBridgeInput) => {
    if (onOpenCoachWithBridge) {
      onOpenCoachWithBridge(bridge);
      return;
    }
    setActiveView("coach");
  }, [onOpenCoachWithBridge, setActiveView]);

  const onOpenPracticeFromFlash = useCallback((bridge: FlashPracticeBridgeInput) => {
    sendTrainingCommand(trainerCommands.trainingGenerateCard, {
      source: "conversation_gap",
      cardType: "practice",
      submode: "practice",
      focusArea: bridge.focusArea,
      targetSkill: bridge.cardTitle,
      prompt: bridge.prompt,
    });
  }, []);

  const onOpenResources = useCallback(() => setActiveView("resources"), [setActiveView]);

  const onCreateFlashcard = useCallback((payload: Record<string, unknown>) => {
    sendTrainingCommand(trainerCommands.trainingFlashcardCreate, payload);
  }, []);

  const onOpenReviewCoach = useCallback(() => setActiveView("coach"), [setActiveView]);

  const onReviewQueueAction = useCallback((payload: Record<string, unknown>) => {
    sendTrainingCommand(trainerCommands.trainingReviewQueueAction, payload);
  }, []);

  const onReviewArtifactAction = useCallback((payload: Record<string, unknown>) => {
    sendTrainingCommand(trainerCommands.trainingReviewArtifactAction, payload);
  }, []);

  const onScenarioLabAction = useCallback((payload: Record<string, unknown>) => {
    sendTrainingCommand(trainerCommands.trainingScenarioLabAction, payload);
  }, []);

  const onDependencySkillMapAction = useCallback((payload: Record<string, unknown>) => {
    sendTrainingCommand(trainerCommands.trainingDependencySkillMapAction, payload);
  }, []);

  const onCardStatusTransition = useCallback((cardId: string, newStatus: string, reason?: string) => {
    sendDurableTrainingCommand(trainerCommands.trainingCardStatusTransition, {
      cardId,
      newStatus,
      reason,
    });
  }, [sendDurableTrainingCommand]);

  const onVerifyCurrentFile = useCallback((request: PracticeFileVerificationRequestInput) => {
    sendTrainingCommand(trainerCommands.evaluateCurrentFile, {
      source: "training",
      cardId: request.cardId,
      cardTitle: request.cardTitle,
      acceptanceCriteria: request.acceptanceCriteria,
      learnerDeliverables: request.learnerDeliverables,
    });
  }, []);

  return {
    onRefreshTask,
    onOpenCoachFromPractice,
    onRefreshDeck,
    onSubmitFlashAnswer,
    onSubmitTheoryDrillAnswer,
    onTheoryDrillAction,
    onOpenCoachFromFlash,
    onOpenCoachBridgeFromFlash,
    onOpenPracticeFromFlash,
    onOpenResources,
    onCreateFlashcard,
    onOpenReviewCoach,
    onReviewQueueAction,
    onReviewArtifactAction,
    onScenarioLabAction,
    onDependencySkillMapAction,
    onCardStatusTransition,
    onVerifyCurrentFile,
  };
}
