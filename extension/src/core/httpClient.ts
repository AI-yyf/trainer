import * as http from 'node:http';

import { SIDECAR_DEFAULTS } from './constants';

export interface SSEMessage {
  event: string;
  data: string;
}

export interface SidecarRequestOptions {
  /**
   * Applies to this one sidecar request. Values are capped so an upstream
   * provider cannot leave the extension request open indefinitely.
   */
  timeoutMs?: number;
  /** Aborts an in-flight request when the caller cancels the operation. */
  signal?: AbortSignal;
}

export class SidecarRequestAbortedError extends Error {
  constructor(message = 'Sidecar request cancelled.') {
    super(message);
    this.name = 'SidecarRequestAbortedError';
  }
}

export type SidecarErrorPathState = 'available' | 'missing' | 'unavailable' | 'unknown';

export interface SidecarErrorMetadata {
  code?: string;
  category?: string;
  pathState?: SidecarErrorPathState;
  /** Safe short FastAPI string detail when present (never secrets/paths). */
  detail?: string;
}

export class SidecarHttpError extends Error {
  constructor(
    readonly statusCode: number,
    message: string,
    readonly metadata: SidecarErrorMetadata = {},
  ) {
    super(message);
    this.name = 'SidecarHttpError';
  }
}

export class SidecarHttpClient {
  private trainerAdmissionMode: 'browse' | 'ignored' | undefined;

  setTrainerAdmissionMode(mode: string | undefined): void {
    this.trainerAdmissionMode = mode === 'browse' || mode === 'ignored' ? mode : undefined;
  }

  async getJson<T>(port: number, path: string, options?: SidecarRequestOptions): Promise<T> {
    return this.requestJson<T>('GET', port, path, undefined, options);
  }

  async postJson<T>(
    port: number,
    path: string,
    body: unknown,
    options?: SidecarRequestOptions,
  ): Promise<T> {
    return this.requestJson<T>('POST', port, path, body, options);
  }

  async putJson<T>(
    port: number,
    path: string,
    body: unknown,
    options?: SidecarRequestOptions,
  ): Promise<T> {
    return this.requestJson<T>('PUT', port, path, body, options);
  }

  async probeHealth(port: number, path = SIDECAR_DEFAULTS.healthPath): Promise<boolean> {
    try {
      await this.requestJson('GET', port, path);
      return true;
    } catch {
      return false;
    }
  }

  /**
   * Fetch SSE stream from sidecar endpoint.
   * Yields parsed SSE events so callers can react to chunk, complete, and error messages.
   */
  async *fetchSSE(
    port: number,
    path: string,
    body: unknown,
    options?: SidecarRequestOptions,
  ): AsyncGenerator<SSEMessage> {
    const payload = Buffer.from(JSON.stringify(body), 'utf8');
    const timeoutMs = this.resolveRequestTimeoutMs(options?.timeoutMs);
    const signal = options?.signal;
    if (signal?.aborted) {
      throw new SidecarRequestAbortedError();
    }
    let activeResponse: http.IncomingMessage | undefined;
    let activeRequest: http.ClientRequest | undefined;
    let deadlineTimer: ReturnType<typeof setTimeout> | undefined;
    let timedOut = false;
    let aborted = false;
    let removeAbortListener: (() => void) | undefined;
    const timeoutError = (): Error =>
      new Error(`Sidecar request timed out after ${timeoutMs}ms: POST ${path}`);

    const response = await new Promise<http.IncomingMessage>((resolve, reject) => {
      let settled = false;
      const fail = (error: Error): void => {
        if (settled) {
          return;
        }
        settled = true;
        if (deadlineTimer) {
          clearTimeout(deadlineTimer);
        }
        reject(error);
      };
      const succeed = (incoming: http.IncomingMessage): void => {
        if (settled) {
          return;
        }
        settled = true;
        resolve(incoming);
      };
      const request = http.request(
        {
          method: 'POST',
          host: SIDECAR_DEFAULTS.host,
          port,
          path,
          timeout: timeoutMs,
          headers: {
            'content-type': 'application/json',
            'content-length': payload.byteLength,
            accept: 'text/event-stream',
            ...this.trainerAdmissionHeaders(),
          },
        },
        (incoming) => {
          activeResponse = incoming;
          succeed(incoming);
        },
      );
      activeRequest = request;

      const abortForSignal = (): void => {
        if (aborted) {
          return;
        }
        aborted = true;
        const error = new SidecarRequestAbortedError();
        fail(error);
        activeResponse?.destroy(error);
        request.destroy(error);
      };

      const abortForTimeout = (): void => {
        if (timedOut) {
          return;
        }
        timedOut = true;
        const error = timeoutError();
        fail(error);
        activeResponse?.destroy(error);
        request.destroy(error);
      };
      request.on('error', (error) => {
        fail(timedOut ? timeoutError() : error);
      });
      request.on('timeout', abortForTimeout);
      if (signal) {
        signal.addEventListener('abort', abortForSignal, { once: true });
        removeAbortListener = () => signal.removeEventListener('abort', abortForSignal);
      }
      deadlineTimer = setTimeout(abortForTimeout, timeoutMs);
      request.write(payload);
      request.end();
    });

    try {
      if ((response.statusCode ?? 500) >= 400) {
        const errorBody = await this.readResponseBody(response);
        throw new Error(`SSE request failed (${response.statusCode}): ${errorBody || path}`);
      }

      let buffer = '';
      const decoder = new TextDecoder('utf-8');

      for await (const chunk of response) {
        buffer += decoder.decode(chunk, { stream: true });

        for (const eventBlock of takeCompleteSseBlocks(() => {
          const match = /\r?\n\r?\n/.exec(buffer);
          if (!match || match.index === undefined) {
            return undefined;
          }
          const block = buffer.slice(0, match.index);
          buffer = buffer.slice(match.index + match[0].length);
          return block;
        })) {
          const event = parseSseEventBlock(eventBlock);
          if (event) {
            yield event;
          }
        }
      }

      buffer += decoder.decode();
      if (buffer.trim()) {
        const event = parseSseEventBlock(buffer);
        if (event) {
          yield event;
        }
      }
    } catch (error) {
      throw aborted ? new SidecarRequestAbortedError() : timedOut ? timeoutError() : error;
    } finally {
      if (deadlineTimer) {
        clearTimeout(deadlineTimer);
      }
      removeAbortListener?.();
      if (activeResponse && !activeResponse.complete) {
        activeResponse.destroy();
      }
      activeRequest = undefined;
    }
  }

  private async readResponseBody(response: http.IncomingMessage): Promise<string> {
    const chunks: Buffer[] = [];
    for await (const chunk of response) {
      chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
    }
    return Buffer.concat(chunks).toString('utf8');
  }

  private async requestJson<T>(
    method: string,
    port: number,
    path: string,
    body?: unknown,
    options?: SidecarRequestOptions,
  ): Promise<T> {
    const payload = body === undefined ? undefined : Buffer.from(JSON.stringify(body), 'utf8');
    const timeoutMs = this.resolveRequestTimeoutMs(options?.timeoutMs);

    return new Promise<T>((resolve, reject) => {
      let settled = false;
      let deadlineTimer: ReturnType<typeof setTimeout> | undefined;

      const settle = (callback: () => void): void => {
        if (settled) {
          return;
        }
        settled = true;
        if (deadlineTimer) {
          clearTimeout(deadlineTimer);
        }
        callback();
      };
      const fail = (error: Error): void => settle(() => reject(error));
      const succeed = (value: T): void => settle(() => resolve(value));
      const request = http.request(
        {
          method,
          host: SIDECAR_DEFAULTS.host,
          port,
          path,
          timeout: timeoutMs,
          headers: {
            ...(payload
              ? {
                  'content-type': 'application/json',
                  'content-length': payload.byteLength,
                }
              : {}),
            ...this.trainerAdmissionHeaders(),
          },
        },
        (response) => {
          const chunks: Buffer[] = [];
          response.on('data', (chunk: Buffer | string) => {
            chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
          });
          response.on('end', () => {
            if (settled) {
              return;
            }
            const text = Buffer.concat(chunks).toString('utf8');
            if ((response.statusCode ?? 500) >= 400) {
              const parsedError = parseSafeSidecarError(text);
              fail(
                new SidecarHttpError(
                  response.statusCode ?? 500,
                  `Sidecar request failed (${response.statusCode ?? 500}).`,
                  parsedError,
                ),
              );
              return;
            }

            if (!text.trim()) {
              succeed(undefined as T);
              return;
            }

            try {
              succeed(JSON.parse(text) as T);
            } catch (error) {
              fail(
                new Error(
                  `Sidecar returned invalid JSON for ${method} ${path}: ${
                    error instanceof Error ? error.message : String(error)
                  }`,
                ),
              );
            }
          });
          response.on('error', (error) => {
            fail(error);
          });
        },
      );

      const abortForTimeout = (): void => {
        const error = new Error(`Sidecar request timed out after ${timeoutMs}ms: ${method} ${path}`);
        fail(error);
        request.destroy(error);
      };
      request.on('timeout', () => {
        abortForTimeout();
      });
      request.on('error', (error) => {
        fail(error);
      });
      deadlineTimer = setTimeout(abortForTimeout, timeoutMs);

      if (payload) {
        request.write(payload);
      }
      request.end();
    });
  }

  private resolveRequestTimeoutMs(requestedTimeoutMs: number | undefined): number {
    if (
      typeof requestedTimeoutMs !== 'number' ||
      !Number.isFinite(requestedTimeoutMs) ||
      requestedTimeoutMs <= 0
    ) {
      return SIDECAR_DEFAULTS.requestTimeoutMs;
    }

    return Math.min(Math.floor(requestedTimeoutMs), SIDECAR_DEFAULTS.maxRequestTimeoutMs);
  }

  private trainerAdmissionHeaders(): Record<string, string> {
    return this.trainerAdmissionMode
      ? { 'x-trainer-admission-mode': this.trainerAdmissionMode }
      : {};
  }
}

function parseSafeSidecarError(text: string): SidecarErrorMetadata {
  try {
    const parsed: unknown = JSON.parse(text);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return {};
    }
    const record = parsed as Record<string, unknown>;
    const detailRecord =
      typeof record.detail === 'object' && record.detail !== null && !Array.isArray(record.detail)
        ? (record.detail as Record<string, unknown>)
        : record;
    const code =
      typeof detailRecord.code === 'string' && /^[a-z0-9_:-]{1,64}$/i.test(detailRecord.code)
        ? detailRecord.code
        : undefined;
    const category =
      typeof detailRecord.category === 'string' &&
      /^[a-z0-9_:-]{1,64}$/i.test(detailRecord.category)
        ? detailRecord.category
        : undefined;
    const rawPathState = detailRecord.path_state ?? detailRecord.pathState;
    const pathState =
      rawPathState === 'available' ||
      rawPathState === 'missing' ||
      rawPathState === 'unavailable' ||
      rawPathState === 'unknown'
        ? rawPathState
        : undefined;
    const detailText =
      typeof record.detail === 'string'
        ? record.detail.replace(/\s+/g, ' ').trim().slice(0, 280)
        : undefined;
    const safeDetail =
      detailText &&
      detailText.length > 0 &&
      !/[\\/]|sk-|api[_-]?key|bearer\s|authorization/i.test(detailText)
        ? detailText
        : undefined;
    return {
      ...(code ? { code } : {}),
      ...(category ? { category } : {}),
      ...(pathState ? { pathState } : {}),
      ...(safeDetail ? { detail: safeDetail } : {}),
    };
  } catch {
    return {};
  }
}

function* takeCompleteSseBlocks(
  nextBlock: () => string | undefined,
): Generator<string> {
  let block: string | undefined;
  while ((block = nextBlock()) !== undefined) {
    yield block;
  }
}

function parseSseEventBlock(eventBlock: string): SSEMessage | undefined {
  let eventType = 'message';
  const dataLines: string[] = [];
  for (const line of eventBlock.split(/\r\n|\n|\r/)) {
    if (line.startsWith('event:')) {
      eventType = line.slice(6).replace(/^ /, '').trim() || 'message';
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).replace(/^ /, ''));
    }
  }

  const eventData = dataLines.join('\n');
  // Keep error frames in the stream so callers can distinguish a
  // recoverable provider downgrade from a terminal failure.
  if (!eventData || eventData === '[DONE]') {
    return undefined;
  }
  return { event: eventType, data: eventData };
}
