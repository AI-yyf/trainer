import { useCallback, useEffect, useRef, useState } from "react";
import type { MutableRefObject } from "react";

import { trainerCommands } from "../../../../shared/src/commands";
import { operationMatchesWebviewScope } from "../../../../shared/src/webviewSync";
import type { FlashVerificationMode } from "../components/training/TrainingWorkbenchView";
import { detectTrainingVerificationTargetMismatch } from "../lib/operationMessageGovernance";
import { remoteVerificationEventMatchesDisplayedCard } from "../lib/remoteVerificationIdentity";
import type { HostMessage } from "../lib/types";
import { postMessage } from "../lib/vscode";
import { useWorkbenchState } from "./useWorkbenchState";

/**
 * Training-card controller (pilot for the App.tsx controller split, DESIGN.md
 * §3). Owns the training domain's interaction state plus its host-message
 * interception, so App keeps only assembly and routing:
 *
 * - composer card modes (flash mode / verify index / return mode / route drafts)
 * - the streaming remote-verification panel + its request identity
 * - card-owned verify notices
 * - the durable training-persistence request/ack channel (request ids,
 *   timeouts, pending count)
 *
 * Host messages arrive through the returned handlers; they mirror the previous
 * inline branches verbatim so behavior is unchanged.
 */

const TRAINING_PERSISTENCE_TIMEOUT_MS = 45_000;

type PendingTrainingPersistence = {
  commandId: string;
  resolve: (data?: unknown) => void;
  reject: (reason?: unknown) => void;
  timeoutId: number;
};

export type TrainingPracticeReturnMode = "result" | "blocked";
export type TrainingComposerRoute = "card" | "coach";

export interface RemoteVerificationViewState {
  sessionId?: string;
  running: boolean;
  output: string;
  summary?: string;
  finishedState?: "completed" | "cancelled" | "timed_out" | "spawn_failed" | "connection_lost";
  passed?: boolean;
}

export interface TrainingCardController {
  trainingComposerFlashMode: FlashVerificationMode;
  setTrainingComposerFlashMode: (mode: FlashVerificationMode) => void;
  trainingComposerVerifyIndex: number;
  setTrainingComposerVerifyIndex: (index: number) => void;
  trainingComposerPracticeReturnMode: TrainingPracticeReturnMode;
  setTrainingComposerPracticeReturnMode: (mode: TrainingPracticeReturnMode) => void;
  trainingComposerRoute: TrainingComposerRoute;
  setTrainingComposerRoute: (route: TrainingComposerRoute) => void;
  trainingVerifyNotice?: string;
  setTrainingVerifyNotice: (notice?: string) => void;
  remoteVerification: RemoteVerificationViewState;
  /** Card the training surface currently displays; written by App each render. */
  displayedTrainingCardIdRef: MutableRefObject<string | undefined>;
  /** Begin a remote verification run for a card; false when one is already running. */
  beginRemoteVerification: (cardId: string) => boolean;
  stopRemoteVerification: () => void;
  /** Clears the panel + request identity (card or scope changed). */
  resetRemoteVerification: () => void;
  /**
   * Intercepts remoteVerification/* host messages. Returns true when the
   * message was consumed (App must stop processing it).
   */
  handleRemoteVerificationHostMessage: (message: HostMessage) => boolean;
  /**
   * Handles the operation/status failure that settles a remote verification
   * request. "none" = not applicable, "settled" = matched and cleared,
   * "abort" = a failure for another card (App must drop the message).
   */
  handleRemoteVerificationCommandFailure: (
    message: HostMessage,
  ) => "none" | "settled" | "abort";
  /** Durable training persistence: pending count for busy affordances. */
  trainingPersistencePending: boolean;
  requestTrainingPersistence: (
    commandId: string,
    payload: Record<string, unknown>,
  ) => Promise<unknown>;
  /** Resolves the request when its ack arrives; false when it does not match. */
  resolveTrainingPersistenceAck: (message: HostMessage) => boolean;
}

export function useTrainingCardController(): TrainingCardController {
  const [trainingComposerFlashMode, setTrainingComposerFlashMode] =
    useState<FlashVerificationMode>("short");
  const [trainingComposerVerifyIndex, setTrainingComposerVerifyIndex] = useState(0);
  const [trainingComposerPracticeReturnMode, setTrainingComposerPracticeReturnMode] =
    useState<TrainingPracticeReturnMode>("result");
  const [trainingComposerRoute, setTrainingComposerRoute] =
    useState<TrainingComposerRoute>("card");
  const [trainingVerifyNotice, setTrainingVerifyNotice] = useState<string | undefined>();
  const [remoteVerification, setRemoteVerification] = useState<RemoteVerificationViewState>({
    running: false,
    output: "",
  });
  const displayedTrainingCardIdRef = useRef<string | undefined>();
  const remoteVerificationRequestRef = useRef<
    { cardId: string; operation: ReturnType<typeof postMessage> } | undefined
  >();
  const remoteVerificationRunningRef = useRef(remoteVerification.running);
  remoteVerificationRunningRef.current = remoteVerification.running;

  const trainingPersistenceResolversRef = useRef(new Map<string, PendingTrainingPersistence>());
  const trainingPersistenceSequenceRef = useRef(0);
  const [trainingPersistencePending, setTrainingPersistencePending] = useState(false);

  // The training surface owns one displayed card at a time; a card or scope
  // change invalidates the in-flight remote verification panel. App calls
  // resetRemoteVerification() from an effect with the same identity deps it
  // used before the split.
  const resetRemoteVerification = useCallback(() => {
    remoteVerificationRequestRef.current = undefined;
    setRemoteVerification({ running: false, output: "" });
  }, []);

  const beginRemoteVerification = useCallback((cardId: string) => {
    if (remoteVerificationRunningRef.current) {
      return false;
    }
    setRemoteVerification({ running: true, output: "" });
    setTrainingVerifyNotice(undefined);
    const operation = postMessage({
      type: "command/execute",
      payload: {
        commandId: trainerCommands.remoteVerifyActiveFile,
        payload: { expectedCardId: cardId },
      },
    });
    remoteVerificationRequestRef.current = { cardId, operation };
    return true;
  }, []);

  const stopRemoteVerification = useCallback(() => {
    if (!remoteVerificationRunningRef.current) {
      return;
    }
    postMessage({
      type: "command/execute",
      payload: { commandId: trainerCommands.remoteVerifyCancel },
    });
  }, []);

  const handleRemoteVerificationHostMessage = useCallback((message: HostMessage) => {
    if (
      message.type !== "remoteVerification/started" &&
      message.type !== "remoteVerification/stream" &&
      message.type !== "remoteVerification/finished"
    ) {
      return false;
    }
    const cursor = useWorkbenchState.getState().syncCursor;
    const pending = remoteVerificationRequestRef.current;
    if (!remoteVerificationEventMatchesDisplayedCard(message.payload.cardId, displayedTrainingCardIdRef.current) ||
        (message.scope && cursor.generation > 0 &&
          (message.scope.generation !== cursor.generation || message.scope.workspaceId !== cursor.workspaceId ||
            message.scope.sessionId !== cursor.sessionId)) ||
        (message.operation && (!pending?.operation ||
          pending.cardId !== displayedTrainingCardIdRef.current ||
          message.operation.requestId !== pending.operation.requestId ||
          message.operation.commandId !== pending.operation.commandId ||
          !operationMatchesWebviewScope(message.operation, cursor)))) {
      return true;
    }
    if (message.type === "remoteVerification/started") {
      setRemoteVerification({ sessionId: message.payload.sessionId, running: true, output: "" });
    } else if (message.type === "remoteVerification/stream") {
      setRemoteVerification((current) => ({
        ...current,
        output: (current.output + message.payload.text).slice(-20_000),
      }));
    } else {
      setRemoteVerification((current) => ({
        ...current,
        running: false,
        finishedState: message.payload.state,
        passed: message.payload.passed,
        summary: message.payload.summary,
      }));
    }
    return true;
  }, []);

  const handleRemoteVerificationCommandFailure = useCallback(
    (message: HostMessage): "none" | "settled" | "abort" => {
      if (message.type !== "operation/status") {
        return "none";
      }
      const pending = remoteVerificationRequestRef.current;
      const remoteCommandFailure = message.payload.tone === "error" &&
        (message.operation?.commandId === trainerCommands.remoteVerifyActiveFile ||
          detectTrainingVerificationTargetMismatch(message.payload.message));
      if (!remoteCommandFailure) {
        return "none";
      }
      const cursor = useWorkbenchState.getState().syncCursor;
      const matchesPending = pending?.cardId === displayedTrainingCardIdRef.current &&
        (message.operation
          ? pending?.operation?.requestId === message.operation.requestId &&
            message.operation.commandId === trainerCommands.remoteVerifyActiveFile &&
            operationMatchesWebviewScope(message.operation, cursor)
          : !pending?.operation && detectTrainingVerificationTargetMismatch(message.payload.message));
      if (!matchesPending) {
        return "abort";
      }
      remoteVerificationRequestRef.current = undefined;
      setRemoteVerification({ running: false, output: "" });
      setTrainingVerifyNotice(undefined);
      return "settled";
    },
    [],
  );

  const resolveTrainingPersistenceAck = useCallback((message: HostMessage) => {
    if (message.type !== "training/persistenceAck") {
      return false;
    }
    const pending = trainingPersistenceResolversRef.current.get(message.payload.requestId);
    if (!pending || pending.commandId !== message.payload.commandId) {
      return false;
    }
    trainingPersistenceResolversRef.current.delete(message.payload.requestId);
    window.clearTimeout(pending.timeoutId);
    if (trainingPersistenceResolversRef.current.size === 0) {
      setTrainingPersistencePending(false);
    }
    if (message.payload.ok) {
      pending.resolve(message.payload.data);
    } else {
      const failureMessage =
        typeof message.payload.message === "string" && message.payload.message.trim()
          ? message.payload.message
          : "Training persistence was not acknowledged.";
      pending.reject(new Error(failureMessage));
    }
    return true;
  }, []);

  const requestTrainingPersistence = useCallback(
    (commandId: string, payload: Record<string, unknown>): Promise<unknown> => {
      const requestId = `training-persistence-${Date.now().toString(36)}-${++trainingPersistenceSequenceRef.current}`;
      return new Promise<unknown>((resolve, reject) => {
        const timeoutId = window.setTimeout(() => {
          const pending = trainingPersistenceResolversRef.current.get(requestId);
          if (!pending) {
            return;
          }
          trainingPersistenceResolversRef.current.delete(requestId);
          if (trainingPersistenceResolversRef.current.size === 0) {
            setTrainingPersistencePending(false);
          }
          pending.reject(new Error("Training persistence timed out."));
          postMessage({
            type: "command/execute",
            payload: {
              commandId: trainerCommands.trainingReliabilityControl,
              payload: {
                requestId,
                action: "cancel",
              },
            },
          });
        }, TRAINING_PERSISTENCE_TIMEOUT_MS);
        trainingPersistenceResolversRef.current.set(requestId, {
          commandId,
          resolve,
          reject,
          timeoutId,
        });
        setTrainingPersistencePending(true);
        try {
          postMessage({
            type: "command/execute",
            payload: {
              commandId,
              payload: {
                ...payload,
                __trainerTrainingPersistenceId: requestId,
              },
            },
          });
        } catch (error) {
          const pending = trainingPersistenceResolversRef.current.get(requestId);
          trainingPersistenceResolversRef.current.delete(requestId);
          if (trainingPersistenceResolversRef.current.size === 0) {
            setTrainingPersistencePending(false);
          }
          if (pending) {
            window.clearTimeout(pending.timeoutId);
            pending.reject(error);
          } else {
            reject(error);
          }
        }
      });
    },
    [],
  );

  useEffect(() => {
    return () => {
      for (const pending of trainingPersistenceResolversRef.current.values()) {
        window.clearTimeout(pending.timeoutId);
        pending.reject(new Error("Training persistence was interrupted."));
      }
      trainingPersistenceResolversRef.current.clear();
    };
  }, []);

  return {
    trainingComposerFlashMode,
    setTrainingComposerFlashMode,
    trainingComposerVerifyIndex,
    setTrainingComposerVerifyIndex,
    trainingComposerPracticeReturnMode,
    setTrainingComposerPracticeReturnMode,
    trainingComposerRoute,
    setTrainingComposerRoute,
    trainingVerifyNotice,
    setTrainingVerifyNotice,
    remoteVerification,
    displayedTrainingCardIdRef,
    beginRemoteVerification,
    stopRemoteVerification,
    resetRemoteVerification,
    handleRemoteVerificationHostMessage,
    handleRemoteVerificationCommandFailure,
    trainingPersistencePending,
    requestTrainingPersistence,
    resolveTrainingPersistenceAck,
  };
}
