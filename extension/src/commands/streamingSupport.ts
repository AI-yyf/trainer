import type * as vscode from 'vscode';

const DEFAULT_FLUSH_DELAY_MS = 32;
const DEFAULT_MAX_CHARS = 320;

export interface BufferedStreamEmitter {
  push(chunk: string): Promise<void>;
  flush(): Promise<void>;
}

export function createBufferedStreamEmitter(
  send: (chunk: string) => Promise<void>,
  options?: {
    flushDelayMs?: number;
    maxChars?: number;
    flushOnNewline?: boolean;
  },
): BufferedStreamEmitter {
  const flushDelayMs = options?.flushDelayMs ?? DEFAULT_FLUSH_DELAY_MS;
  const maxChars = options?.maxChars ?? DEFAULT_MAX_CHARS;
  const flushOnNewline = options?.flushOnNewline ?? true;

  let buffer = '';
  let flushTimer: ReturnType<typeof setTimeout> | undefined;
  let flushChain = Promise.resolve();

  const queueFlush = async (): Promise<void> => {
    if (!buffer) {
      await flushChain;
      return;
    }
    const nextChunk = buffer;
    buffer = '';
    flushChain = flushChain.then(() => send(nextChunk));
    await flushChain;
  };

  const scheduleFlush = (): void => {
    if (flushTimer !== undefined) {
      return;
    }
    flushTimer = setTimeout(() => {
      flushTimer = undefined;
      void queueFlush();
    }, flushDelayMs);
  };

  return {
    async push(chunk: string): Promise<void> {
      if (!chunk) {
        return;
      }
      buffer += chunk;
      if (buffer.length >= maxChars || (flushOnNewline && chunk.includes('\n'))) {
        if (flushTimer !== undefined) {
          clearTimeout(flushTimer);
          flushTimer = undefined;
        }
        await queueFlush();
        return;
      }
      scheduleFlush();
    },
    async flush(): Promise<void> {
      if (flushTimer !== undefined) {
        clearTimeout(flushTimer);
        flushTimer = undefined;
      }
      await queueFlush();
    },
  };
}

export interface StreamPerfTracker {
  markChunk(chunk?: string): void;
  complete(summary?: string): void;
  fail(summary: string): void;
}

export function createStreamPerfTracker(
  outputChannel: vscode.OutputChannel,
  label: string,
): StreamPerfTracker {
  const startedAt = Date.now();
  let firstChunkAt: number | undefined;
  let chunkCount = 0;
  let charCount = 0;

  const renderSummary = (status: string, summary?: string): string => {
    const totalMs = Date.now() - startedAt;
    const firstChunkMs = firstChunkAt !== undefined ? firstChunkAt - startedAt : undefined;
    const parts = [
      `[perf] ${label}`,
      `status=${status}`,
      `total=${totalMs}ms`,
      `firstChunk=${firstChunkMs !== undefined ? `${firstChunkMs}ms` : 'n/a'}`,
      `chunks=${chunkCount}`,
      `chars=${charCount}`,
    ];
    if (summary?.trim()) {
      parts.push(summary.trim());
    }
    return parts.join(' ');
  };

  return {
    markChunk(chunk = ''): void {
      chunkCount += 1;
      charCount += chunk.length;
      if (firstChunkAt === undefined) {
        firstChunkAt = Date.now();
      }
    },
    complete(summary?: string): void {
      outputChannel.appendLine(renderSummary('complete', summary));
    },
    fail(summary: string): void {
      outputChannel.appendLine(renderSummary('error', summary));
    },
  };
}
