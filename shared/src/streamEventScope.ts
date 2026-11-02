/**
 * Stream-complete generation fence.
 *
 * A host snapshot can clear `streamMessageId` while the stream is still
 * marked active. In that state the terminal `stream/complete` frame carries
 * the only remaining identity, so treating it as stale leaves the webview
 * stuck in "streaming" forever and hides the persisted reply. Accept the
 * completion when no id is recorded and the stream is still active; a
 * different recorded id still means a stale/waiters frame and must be ignored.
 */
export interface StreamEventScopeLike {
  isStreaming: boolean;
  streamMessageId?: string;
}

export function isCurrentStreamEvent(
  streaming: StreamEventScopeLike,
  messageId: string | undefined,
): boolean {
  if (messageId === undefined) {
    // Legacy/replay frames may omit the id. The research lane now sends its
    // own id, so the remaining id-less frames belong to the active stream.
    return true;
  }
  if (!streaming.streamMessageId) {
    return streaming.isStreaming;
  }
  return messageId === streaming.streamMessageId;
}
