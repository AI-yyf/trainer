import * as crypto from 'node:crypto';
import * as http from 'node:http';

/**
 * Zero-config trial provider: a loopback-only, OpenAI-compatible chat
 * service bundled with the extension so a learner without an API key can
 * complete a real coach round-trip (the sidecar talks to it like any other
 * OpenAI-compatible endpoint). The server binds to 127.0.0.1 on an ephemeral
 * port, never calls out to the network, and dies with the extension host.
 */

export const TRIAL_PROVIDER_MODEL_ID = 'trainer-trial-model';

export const TRIAL_PROVIDER_TEMPLATE_INDEX = 5; // "Ollama (Local)" — compatible chat protocol

type ChatMessageLike = {
  role?: unknown;
  content?: unknown;
};

type ChatCompletionBody = {
  stream?: unknown;
  messages?: unknown;
};

function textFromContent(content: unknown): string {
  if (typeof content === 'string') {
    return content;
  }
  if (Array.isArray(content)) {
    return content
      .map((part) =>
        part && typeof part === 'object' && typeof (part as { text?: unknown }).text === 'string'
          ? (part as { text: string }).text
          : '',
      )
      .join('');
  }
  return '';
}

function lastUserExcerpt(body: ChatCompletionBody): string {
  const messages = Array.isArray(body.messages) ? (body.messages as ChatMessageLike[]) : [];
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message?.role === 'user') {
      const text = textFromContent(message.content).replace(/\s+/g, ' ').trim();
      return text.length > 60 ? `${text.slice(0, 60)}…` : text;
    }
  }
  return '';
}

/**
 * Deterministic practice-mode reply. Honest about being local-only, and
 * mirrors the learner's last message so the round-trip reads naturally.
 */
export function buildTrialCoachReply(body: ChatCompletionBody): string {
  const excerpt = lastUserExcerpt(body);
  const userText = Array.isArray(body.messages)
    ? textFromContent(
        ([...(body.messages as ChatMessageLike[])].reverse().find((m) => m?.role === 'user') ?? {})
          .content,
      )
    : '';
  const chinese = /[\u4e00-\u9fff]/.test(userText);
  const anchor = excerpt ? (chinese ? `你刚提到：“${excerpt}”。` : `You just mentioned: “${excerpt}”.`) : '';
  return chinese
    ? `【Trainer 练习模式】当前连接的是内置本地练习服务，不会调用外部模型。${anchor} 把你的 API Key 粘贴到「设置 → 连接模型」并保存后，教练就能针对这个问题给出真实指导。`
    : `[Trainer practice mode] This is the built-in local practice service; no external model is called. ${anchor} Paste your API key under “Settings → Connect a model” and save, and your coach will give real guidance for this question.`;
}

function completionId(): string {
  return `chatcmpl-trial-${crypto.randomBytes(6).toString('hex')}`;
}

function nowSeconds(): number {
  return Math.floor(Date.now() / 1000);
}

function writeJson(res: http.ServerResponse, status: number, payload: unknown): void {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    'content-type': 'application/json',
    'content-length': Buffer.byteLength(body),
  });
  res.end(body);
}

function modelListPayload(): unknown {
  return {
    object: 'list',
    data: [
      {
        id: TRIAL_PROVIDER_MODEL_ID,
        object: 'model',
        created: nowSeconds(),
        owned_by: 'trainer-trial',
      },
    ],
  };
}

export class TrialProviderServer {
  private server: http.Server | undefined;
  private listening = false;
  private readonly apiKey = `trial-${crypto.randomBytes(16).toString('hex')}`;

  get port(): number | undefined {
    const address = this.server?.address();
    return address && typeof address === 'object' ? address.port : undefined;
  }

  get baseUrl(): string {
    const port = this.port;
    if (!port) {
      throw new Error('Trainer trial service is not listening yet.');
    }
    return `http://127.0.0.1:${port}/v1`;
  }

  get secretApiKey(): string {
    return this.apiKey;
  }

  get isListening(): boolean {
    return this.listening;
  }

  async listen(): Promise<void> {
    if (this.listening) {
      return;
    }
    const server = http.createServer((request, response) => {
      void this.handle(request, response);
    });
    server.on('error', () => {
      this.listening = false;
    });
    await new Promise<void>((resolve, reject) => {
      const onceError = (error: Error): void => {
        reject(error);
      };
      server.once('error', onceError);
      server.listen(0, '127.0.0.1', () => {
        server.off('error', onceError);
        // The extension host keeps the loop alive on its own; unref so a
        // listening trial service never blocks process exit (tests, host
        // shutdown races).
        server.unref();
        resolve();
      });
    });
    this.server = server;
    this.listening = true;
  }

  async close(): Promise<void> {
    const server = this.server;
    this.server = undefined;
    this.listening = false;
    if (!server) {
      return;
    }
    await new Promise<void>((resolve) => {
      server.close(() => resolve());
    });
  }

  private async handle(request: http.IncomingMessage, response: http.ServerResponse): Promise<void> {
    try {
      const url = new URL(request.url ?? '/', `http://127.0.0.1${request.url ?? ''}`);
      const route = `${request.method ?? 'GET'} ${url.pathname}`;
      if (request.method === 'GET' && /\/models$/.test(url.pathname)) {
        writeJson(response, 200, modelListPayload());
        return;
      }
      if (request.method === 'POST' && /\/chat\/completions$/.test(url.pathname)) {
        const raw = await readBody(request);
        let parsed: ChatCompletionBody = {};
        try {
          parsed = raw ? (JSON.parse(raw) as ChatCompletionBody) : {};
        } catch {
          writeJson(response, 400, { error: { message: 'invalid JSON body', type: 'invalid_request_error' } });
          return;
        }
        this.replyCompletion(response, parsed, parsed.stream === true);
        return;
      }
      writeJson(response, 404, { error: { message: `unknown trial route: ${route}`, type: 'invalid_request_error' } });
    } catch (error) {
      writeJson(response, 500, {
        error: {
          message: error instanceof Error ? error.message : String(error),
          type: 'internal_error',
        },
      });
    }
  }

  private replyCompletion(
    response: http.ServerResponse,
    body: ChatCompletionBody,
    stream: boolean,
  ): void {
    const content = buildTrialCoachReply(body);
    const model = TRIAL_PROVIDER_MODEL_ID;
    if (!stream) {
      writeJson(response, 200, {
        id: completionId(),
        object: 'chat.completion',
        created: nowSeconds(),
        model,
        choices: [
          {
            index: 0,
            message: { role: 'assistant', content },
            finish_reason: 'stop',
          },
        ],
        usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
      });
      return;
    }
    response.writeHead(200, {
      'content-type': 'text/event-stream',
      'cache-control': 'no-cache',
      connection: 'keep-alive',
    });
    const chunk = (payload: unknown): void => {
      response.write(`data: ${JSON.stringify(payload)}\n\n`);
    };
    const id = completionId();
    const created = nowSeconds();
    chunk({
      id,
      object: 'chat.completion.chunk',
      created,
      model,
      choices: [{ index: 0, delta: { role: 'assistant' }, finish_reason: null }],
    });
    for (const piece of content.match(/[\s\S]{1,48}/g) ?? []) {
      chunk({
        id,
        object: 'chat.completion.chunk',
        created,
        model,
        choices: [{ index: 0, delta: { content: piece }, finish_reason: null }],
      });
    }
    chunk({
      id,
      object: 'chat.completion.chunk',
      created,
      model,
      choices: [{ index: 0, delta: {}, finish_reason: 'stop' }],
    });
    response.write('data: [DONE]\n\n');
    response.end();
  }
}

let activeTrialServer: TrialProviderServer | undefined;

export async function ensureTrialProviderServer(): Promise<TrialProviderServer> {
  if (activeTrialServer?.isListening) {
    return activeTrialServer;
  }
  const server = new TrialProviderServer();
  await server.listen();
  activeTrialServer = server;
  return server;
}

export async function disposeTrialProviderServer(): Promise<void> {
  const server = activeTrialServer;
  activeTrialServer = undefined;
  await server?.close();
}

async function readBody(request: http.IncomingMessage): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of request) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk as string));
  }
  return Buffer.concat(chunks).toString('utf8');
}
