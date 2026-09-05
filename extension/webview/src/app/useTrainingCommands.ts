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
]);

function sendTrainingCommand(commandId: string, payload: Record<string, unknown>): void {
  postMessage({
    type: "command/execute",
    payload: { commandId, payload },
  });
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
