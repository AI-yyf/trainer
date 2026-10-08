/** Local host ↔ webview transport identities. These are not evidence revisions. */
export interface WebviewSyncEnvelope {
  generation: number;
  revision: number;
  baseRevision: number;
  messageId: string;
  workspaceId: string;
  sessionId: string;
}

export interface WebviewSyncAck extends WebviewSyncEnvelope {
  status: "received" | "applied" | "duplicate" | "rejected";
  appliedRevision: number;
}

export interface WebviewSyncCursor {
  generation: number;
  revision: number;
  messageId: string;
  workspaceId: string;
  sessionId: string;
}

export type WebviewSyncStatus = "current" | "recovering" | "stale";

export function emptyWebviewSyncCursor(): WebviewSyncCursor {
  return { generation: 0, revision: 0, messageId: "", workspaceId: "", sessionId: "" };
}

export type WebviewSyncDecision = "apply" | "duplicate" | "ignore" | "recover";

/** A full snapshot may advance generation; a delta can only extend its exact base. */
export function decideWebviewSync(
  cursor: WebviewSyncCursor,
  incoming: WebviewSyncEnvelope,
): WebviewSyncDecision {
  if (!Number.isSafeInteger(incoming.generation) || incoming.generation < 1 ||
      !Number.isSafeInteger(incoming.revision) || incoming.revision < 1 ||
      !Number.isSafeInteger(incoming.baseRevision) || incoming.baseRevision < 0 ||
      !incoming.messageId || incoming.baseRevision >= incoming.revision) return "recover";
  if (incoming.generation < cursor.generation || incoming.revision < cursor.revision) return "ignore";
  if (incoming.generation === cursor.generation && incoming.revision === cursor.revision) {
    return incoming.messageId === cursor.messageId ? "duplicate" : "recover";
  }
  const sameScope = incoming.workspaceId === cursor.workspaceId && incoming.sessionId === cursor.sessionId;
  if (incoming.generation === cursor.generation && !sameScope) return "recover";
  if (incoming.baseRevision === 0) return "apply";
  return incoming.generation === cursor.generation && sameScope && incoming.baseRevision === cursor.revision
    ? "apply" : "recover";
}

export function appliedWebviewSyncCursor(envelope: WebviewSyncEnvelope): WebviewSyncCursor {
  const { generation, revision, messageId, workspaceId, sessionId } = envelope;
  return { generation, revision, messageId, workspaceId, sessionId };
}

export interface WebviewOperationIdentity {
  requestId: string;
  generation: number;
  workspaceId: string;
  sessionId: string;
  targetId?: string;
  commandId?: string;
  revision: number;
}

export type WebviewOperationPhase = "pending" | "running" | "succeeded" | "failed" | "interrupted" | "cancelled";

export function operationMatchesWebviewScope(
  operation: WebviewOperationIdentity,
  cursor: WebviewSyncCursor,
): boolean {
  return operation.generation === cursor.generation &&
    operation.workspaceId === cursor.workspaceId && operation.sessionId === cursor.sessionId;
}

export function webviewOperationTargetKey(operation: WebviewOperationIdentity): string {
  return `${operation.commandId ?? "operation"}\u0000${operation.targetId ?? ""}`;
}
