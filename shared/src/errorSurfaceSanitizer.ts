export type ErrorSurfaceKind =
  | "safe"
  | "secret"
  | "traceback"
  | "json_body"
  | "upstream"
  | "thinking"
  | "unverified"
  | "empty";

export interface ErrorSurfaceRecord {
  kind: ErrorSurfaceKind;
  message: string;
  why: string;
  next: string;
  authoritative: boolean;
}

export interface SanitizeErrorSurfaceOptions {
  language?: string;
  acknowledged?: boolean;
  fallback?: string;
}

const KEY_SHAPED_PATTERN =
  /\b(?:sk|rk|pk|ak)-[A-Za-z0-9_-]{8,}\b|\bAIza[0-9A-Za-z_-]{10,}\b/g;
const BEARER_PATTERN = /\bBearer\s+[A-Za-z0-9._\-+=/]{8,}/gi;
const SECRET_FIELD_PATTERN =
  /\b(?:api[_-]?key|access[_-]?token|authorization|client[_-]?secret|secret|password|token)\s*[:=]\s*["']?[^\s"'\\,;]+["']?/gi;
const SECRET_STORAGE_PATTERN = /\bSecretStorage\b/gi;
const TRACEBACK_PATTERN =
  /Traceback \(most recent call last\)|File "[^"]+", line \d+|^\s*at \S+(?:\.\S+)* \([^)]+:\d+:\d+\)|\bstack trace\b/im;
const THINK_PATTERN =
  /<think\b[^>]*>[\s\S]*?<\/think>|\breasoning_content\b|\bredactedthinking\b|<\|?(?:think|reasoning)\|?>/i;
const UPSTREAM_PATTERN =
  /\b(?:upstream[_ ]?(?:body|payload|response)|provider response body|response body)\b/i;
const HTTP_DUMP_PATTERN = /\bHTTP\/\d(?:\.\d)?\b|\b<(?:html|head|body|pre)\b/i;
const BARE_SUCCESS_PATTERN = /^(?:ok|okay|success|successful|ready|completed|complete|pass|passed|done)\b/i;
const REDACTED = "[redacted]";

type SurfaceCopy = {
  secret: { message: string; why: string; next: string };
  traceback: { message: string; why: string; next: string };
  jsonBody: { message: string; why: string; next: string };
  upstream: { message: string; why: string; next: string };
  thinking: { message: string; why: string; next: string };
  unverified: { message: string; why: string; next: string };
  empty: { message: string; why: string; next: string };
  fallback: { message: string; why: string; next: string };
};

const SURFACE_COPY: Record<string, SurfaceCopy> = {
  "zh-CN": {
    secret: {
      message: "这条错误里的密钥已被隐藏。",
      why: "密钥、令牌或 SecretStorage 值不能出现在界面上。",
      next: "打开设置检查连接，然后重试。",
    },
    traceback: {
      message: "这一步失败了，技术细节已隐藏。",
      why: "堆栈或运行时转储对学习没有帮助。",
      next: "稍后再试；若继续失败，先在设置里检查连接。",
    },
    jsonBody: {
      message: "上游返回内容已隐藏。",
      why: "原始 JSON 或接口响应不能当作错误说明。",
      next: "稍后再试，或打开设置检查连接。",
    },
    upstream: {
      message: "上游响应已被隐藏。",
      why: "提供方响应正文不能直接展示。",
      next: "稍后再试，或打开设置检查连接。",
    },
    thinking: {
      message: "隐藏推理内容已移除。",
      why: "思考过程不应泄漏到可见界面。",
      next: "继续看可见回复，或再试一次。",
    },
    unverified: {
      message: "还没有权威确认，不能当作成功。",
      why: "没有确认回执时，界面不能显示已完成。",
      next: "先等确认，不要当成已经成功。",
    },
    empty: {
      message: "这一步没有完成。",
      why: "错误内容为空，还不能判断原因。",
      next: "再试一次；若继续失败，打开设置检查连接。",
    },
    fallback: {
      message: "这一步没有完成。",
      why: "目前只有可理解的失败说明，没有底层细节。",
      next: "再试一次；若继续失败，打开设置检查连接。",
    },
  },
  "en-US": {
    secret: {
      message: "A secret value was removed from this error.",
      why: "API keys, bearer tokens, and SecretStorage values must not appear in the UI.",
      next: "Open Settings, check the connection, then try again.",
    },
    traceback: {
      message: "This step failed. Technical details were hidden.",
      why: "A traceback or runtime dump is not a learner-facing explanation.",
      next: "Try again shortly. If it keeps failing, check the connection in Settings.",
    },
    jsonBody: {
      message: "The upstream response was hidden.",
      why: "Raw JSON or provider response bodies are not the error the user should see.",
      next: "Try again, or check the connection in Settings.",
    },
    upstream: {
      message: "The provider response was hidden.",
      why: "Upstream response bodies must not be shown as the error.",
      next: "Try again, or check the connection in Settings.",
    },
    thinking: {
      message: "Hidden reasoning was removed.",
      why: "Think-text and hidden reasoning must not leak into the visible UI.",
      next: "Continue from the visible reply, or try again.",
    },
    unverified: {
      message: "This is not confirmed yet, so it is not success.",
      why: "The UI cannot treat a step as done without an authoritative acknowledgement.",
      next: "Wait for acknowledgement before treating this as complete.",
    },
    empty: {
      message: "This step did not finish.",
      why: "The error text was empty, so the cause is still unknown.",
      next: "Try again. If it keeps failing, check the connection in Settings.",
    },
    fallback: {
      message: "This step did not finish.",
      why: "Only a learner-facing failure remains after unsafe details were removed.",
      next: "Try again. If it keeps failing, check the connection in Settings.",
    },
  },
  "es-ES": {
    secret: {
      message: "Se ocultó un valor secreto de este error.",
      why: "Las claves, tokens y valores de SecretStorage no pueden aparecer en la interfaz.",
      next: "Abre Ajustes, comprueba la conexión y vuelve a intentarlo.",
    },
    traceback: {
      message: "Este paso falló. Se ocultaron los detalles técnicos.",
      why: "Un volcado o traza no explica el fallo a quien está aprendiendo.",
      next: "Inténtalo de nuevo. Si sigue fallando, revisa la conexión en Ajustes.",
    },
    jsonBody: {
      message: "Se ocultó la respuesta del proveedor.",
      why: "El JSON crudo no es la explicación que debe verse.",
      next: "Inténtalo de nuevo o revisa la conexión en Ajustes.",
    },
    upstream: {
      message: "Se ocultó la respuesta del proveedor.",
      why: "El cuerpo de la respuesta no debe mostrarse como error.",
      next: "Inténtalo de nuevo o revisa la conexión en Ajustes.",
    },
    thinking: {
      message: "Se eliminó el razonamiento oculto.",
      why: "El texto de pensamiento no debe filtrarse a la interfaz.",
      next: "Sigue con la respuesta visible o inténtalo de nuevo.",
    },
    unverified: {
      message: "Aún no hay confirmación, así que no es un éxito.",
      why: "Sin acuse de recibo, la interfaz no puede marcar esto como listo.",
      next: "Espera la confirmación antes de darlo por terminado.",
    },
    empty: {
      message: "Este paso no terminó.",
      why: "El texto del error estaba vacío, así que la causa sigue sin verse.",
      next: "Inténtalo de nuevo. Si sigue fallando, revisa la conexión en Ajustes.",
    },
    fallback: {
      message: "Este paso no terminó.",
      why: "Solo queda una explicación comprensible, sin detalles internos.",
      next: "Inténtalo de nuevo. Si sigue fallando, revisa la conexión en Ajustes.",
    },
  },
  "fr-FR": {
    secret: {
      message: "Une valeur secrète a été retirée de cette erreur.",
      why: "Les clés, jetons et valeurs SecretStorage ne doivent pas apparaître.",
      next: "Ouvrez Réglages, vérifiez la connexion, puis réessayez.",
    },
    traceback: {
      message: "Cette étape a échoué. Les détails techniques ont été masqués.",
      why: "Une trace d'exécution n'explique pas l'échec à l'apprenant.",
      next: "Réessayez. Si cela continue, vérifiez la connexion dans Réglages.",
    },
    jsonBody: {
      message: "La réponse du fournisseur a été masquée.",
      why: "Le JSON brut n'est pas l'explication à afficher.",
      next: "Réessayez, ou vérifiez la connexion dans Réglages.",
    },
    upstream: {
      message: "La réponse du fournisseur a été masquée.",
      why: "Le corps de réponse ne doit pas servir d'erreur visible.",
      next: "Réessayez, ou vérifiez la connexion dans Réglages.",
    },
    thinking: {
      message: "Le raisonnement caché a été retiré.",
      why: "Le texte de réflexion ne doit pas fuiter dans l'interface.",
      next: "Continuez avec la réponse visible, ou réessayez.",
    },
    unverified: {
      message: "Ce n'est pas encore confirmé, donc ce n'est pas un succès.",
      why: "Sans accusé de réception, l'interface ne peut pas afficher « terminé ».",
      next: "Attendez la confirmation avant de considérer cela comme fini.",
    },
    empty: {
      message: "Cette étape n'est pas terminée.",
      why: "Le texte d'erreur était vide, la cause reste inconnue.",
      next: "Réessayez. Si cela continue, vérifiez la connexion dans Réglages.",
    },
    fallback: {
      message: "Cette étape n'est pas terminée.",
      why: "Il ne reste qu'une explication claire, sans détail interne.",
      next: "Réessayez. Si cela continue, vérifiez la connexion dans Réglages.",
    },
  },
  "de-DE": {
    secret: {
      message: "Ein geheimer Wert wurde aus diesem Fehler entfernt.",
      why: "API-Schlüssel, Token und SecretStorage-Werte dürfen nicht sichtbar sein.",
      next: "Öffne Einstellungen, prüfe die Verbindung und versuche es erneut.",
    },
    traceback: {
      message: "Dieser Schritt ist fehlgeschlagen. Technische Details wurden ausgeblendet.",
      why: "Ein Stacktrace erklärt den Fehler nicht für Lernende.",
      next: "Versuche es erneut. Wenn es weiter scheitert, prüfe die Verbindung in Einstellungen.",
    },
    jsonBody: {
      message: "Die Anbieterantwort wurde ausgeblendet.",
      why: "Rohes JSON ist keine sichtbare Fehlererklärung.",
      next: "Versuche es erneut oder prüfe die Verbindung in Einstellungen.",
    },
    upstream: {
      message: "Die Anbieterantwort wurde ausgeblendet.",
      why: "Antwortkörper dürfen nicht als Fehler angezeigt werden.",
      next: "Versuche es erneut oder prüfe die Verbindung in Einstellungen.",
    },
    thinking: {
      message: "Verborgenes Reasoning wurde entfernt.",
      why: "Denktext darf nicht in die Oberfläche gelangen.",
      next: "Lies die sichtbare Antwort oder versuche es erneut.",
    },
    unverified: {
      message: "Das ist noch nicht bestätigt und daher kein Erfolg.",
      why: "Ohne Bestätigung darf die Oberfläche das nicht als erledigt zeigen.",
      next: "Warte auf die Bestätigung, bevor du es als fertig behandelst.",
    },
    empty: {
      message: "Dieser Schritt ist nicht abgeschlossen.",
      why: "Der Fehlertext war leer, die Ursache ist noch unbekannt.",
      next: "Versuche es erneut. Wenn es weiter scheitert, prüfe die Verbindung in Einstellungen.",
    },
    fallback: {
      message: "Dieser Schritt ist nicht abgeschlossen.",
      why: "Es bleibt nur eine verständliche Erklärung, ohne interne Details.",
      next: "Versuche es erneut. Wenn es weiter scheitert, prüfe die Verbindung in Einstellungen.",
    },
  },
  "ja-JP": {
    secret: {
      message: "このエラーから秘密の値を隠しました。",
      why: "APIキー、トークン、SecretStorage の値は画面に出せません。",
      next: "設定で接続を確認してから、もう一度試してください。",
    },
    traceback: {
      message: "この手順は失敗しました。技術詳細は非表示です。",
      why: "スタックトレースは学習者向けの説明ではありません。",
      next: "もう一度試してください。続く場合は設定で接続を確認してください。",
    },
    jsonBody: {
      message: "上流の応答は非表示にしました。",
      why: "生の JSON をエラー説明にしてはいけません。",
      next: "もう一度試すか、設定で接続を確認してください。",
    },
    upstream: {
      message: "プロバイダー応答は非表示にしました。",
      why: "応答本文をエラーとして見せてはいけません。",
      next: "もう一度試すか、設定で接続を確認してください。",
    },
    thinking: {
      message: "非表示の推論は取り除きました。",
      why: "思考テキストを画面に漏らしてはいけません。",
      next: "見える返信を続けるか、もう一度試してください。",
    },
    unverified: {
      message: "まだ確認されていないので、成功ではありません。",
        why: "確認がなければ、完了として表示できません。",
      next: "確認を待ってから完了として扱ってください。",
    },
    empty: {
      message: "この手順は完了していません。",
      why: "エラー文が空なので、原因はまだ分かりません。",
      next: "もう一度試してください。続く場合は設定で接続を確認してください。",
    },
    fallback: {
      message: "この手順は完了していません。",
      why: "分かる失敗説明だけが残っています。内部詳細はありません。",
      next: "もう一度試してください。続く場合は設定で接続を確認してください。",
    },
  },
  "ko-KR": {
    secret: {
      message: "이 오류에서 비밀 값을 숨겼습니다.",
      why: "API 키, 토큰, SecretStorage 값은 화면에 나타날 수 없습니다.",
      next: "설정에서 연결을 확인한 뒤 다시 시도하세요.",
    },
    traceback: {
      message: "이 단계가 실패했습니다. 기술 세부 정보는 숨겼습니다.",
      why: "스택 추적은 학습자에게 보여줄 설명이 아닙니다.",
      next: "다시 시도하세요. 계속 실패하면 설정에서 연결을 확인하세요.",
    },
    jsonBody: {
      message: "업스트림 응답을 숨겼습니다.",
      why: "원본 JSON은 오류 설명이 아닙니다.",
      next: "다시 시도하거나 설정에서 연결을 확인하세요.",
    },
    upstream: {
      message: "제공자 응답을 숨겼습니다.",
      why: "응답 본문을 오류로 보여주면 안 됩니다.",
      next: "다시 시도하거나 설정에서 연결을 확인하세요.",
    },
    thinking: {
      message: "숨겨진 추론을 제거했습니다.",
      why: "사고 텍스트가 화면에 새면 안 됩니다.",
      next: "보이는 답변을 이어가거나 다시 시도하세요.",
    },
    unverified: {
      message: "아직 확인되지 않았으므로 성공이 아닙니다.",
      why: "확인 응답이 없으면 완료로 표시할 수 없습니다.",
      next: "확인을 받은 뒤에 완료로 다루세요.",
    },
    empty: {
      message: "이 단계가 끝나지 않았습니다.",
      why: "오류 문구가 비어 있어 원인을 아직 알 수 없습니다.",
      next: "다시 시도하세요. 계속 실패하면 설정에서 연결을 확인하세요.",
    },
    fallback: {
      message: "이 단계가 끝나지 않았습니다.",
      why: "이해할 수 있는 실패 설명만 남았고, 내부 세부 정보는 없습니다.",
      next: "다시 시도하세요. 계속 실패하면 설정에서 연결을 확인하세요.",
    },
  },
  "pt-BR": {
    secret: {
      message: "Um valor secreto foi removido deste erro.",
      why: "Chaves, tokens e valores do SecretStorage não podem aparecer na interface.",
      next: "Abra Configurações, verifique a conexão e tente de novo.",
    },
    traceback: {
      message: "Esta etapa falhou. Os detalhes técnicos foram ocultados.",
      why: "Um traceback não é uma explicação para quem está aprendendo.",
      next: "Tente de novo. Se continuar falhando, verifique a conexão em Configurações.",
    },
    jsonBody: {
      message: "A resposta do provedor foi ocultada.",
      why: "JSON cru não é a explicação que deve aparecer.",
      next: "Tente de novo ou verifique a conexão em Configurações.",
    },
    upstream: {
      message: "A resposta do provedor foi ocultada.",
      why: "O corpo da resposta não deve ser mostrado como erro.",
      next: "Tente de novo ou verifique a conexão em Configurações.",
    },
    thinking: {
      message: "O raciocínio oculto foi removido.",
      why: "O texto de pensamento não pode vazar para a interface.",
      next: "Siga com a resposta visível ou tente de novo.",
    },
    unverified: {
      message: "Ainda não há confirmação, então isto não é sucesso.",
      why: "Sem confirmação, a interface não pode marcar como concluído.",
      next: "Espere a confirmação antes de tratar como pronto.",
    },
    empty: {
      message: "Esta etapa não terminou.",
      why: "O texto do erro estava vazio, então a causa ainda não aparece.",
      next: "Tente de novo. Se continuar falhando, verifique a conexão em Configurações.",
    },
    fallback: {
      message: "Esta etapa não terminou.",
      why: "Sobrou só uma falha compreensível, sem detalhes internos.",
      next: "Tente de novo. Se continuar falhando, verifique a conexão em Configurações.",
    },
  },
};

function copyFor(language?: string): SurfaceCopy {
  return SURFACE_COPY[language ?? ""] ?? SURFACE_COPY["en-US"];
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function inspectText(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  if (value instanceof Error) {
    return value.message || value.name;
  }
  if (value === undefined || value === null) {
    return "";
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function compact(text: string, limit = 220): string {
  const normalized = text.replace(/\s+/g, " ").trim();
  if (normalized.length <= limit) {
    return normalized;
  }
  return `${normalized.slice(0, limit - 1).trimEnd()}…`;
}

function redactSecretShapes(text: string): { text: string; redacted: boolean } {
  const next = text
    .replace(KEY_SHAPED_PATTERN, REDACTED)
    .replace(BEARER_PATTERN, "Bearer [redacted]")
    .replace(SECRET_FIELD_PATTERN, (match) => {
      const separator = match.includes("=") ? "=" : match.includes(":") ? ":" : "=";
      const name = match.split(/[:=]/)[0]?.trim() || "secret";
      return `${name}${separator}[redacted]`;
    })
    .replace(SECRET_STORAGE_PATTERN, "SecretStorage");
  return { text: next, redacted: next !== text };
}

function parseJsonCandidate(text: string): unknown | undefined {
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

function looksLikeJsonBody(text: string): boolean {
  const trimmed = text.trim();
  if (!trimmed) {
    return false;
  }
  if (trimmed[0] === "{" || trimmed[0] === "[") {
    const parsed = parseJsonCandidate(trimmed);
    return Array.isArray(parsed) || Boolean(asRecord(parsed));
  }
  const embedded = trimmed.replace(/^[^[{]*/, "").trim();
  if (!embedded || (embedded[0] !== "{" && embedded[0] !== "[")) {
    return false;
  }
  const parsed = parseJsonCandidate(embedded);
  if (Array.isArray(parsed)) {
    return true;
  }
  const record = asRecord(parsed);
  if (!record) {
    return /"(?:choices|content|error|token|api_key|upstream_body)"/.test(trimmed);
  }
  const keys = Object.keys(record).map((key) => key.toLowerCase());
  return keys.some((key) =>
    [
      "choices",
      "content",
      "error",
      "data",
      "upstream_body",
      "payload",
      "response",
      "token",
      "api_key",
    ].includes(key),
  );
}

function looksLikeBareSuccess(text: string): boolean {
  return BARE_SUCCESS_PATTERN.test(text.trim());
}

function recordForKind(
  kind: Exclude<ErrorSurfaceKind, "safe">,
  language: string | undefined,
  fallback?: string,
): ErrorSurfaceRecord {
  const copy = copyFor(language);
  const selected =
    kind === "secret"
      ? copy.secret
      : kind === "traceback"
        ? copy.traceback
        : kind === "json_body"
          ? copy.jsonBody
          : kind === "upstream"
            ? copy.upstream
            : kind === "thinking"
              ? copy.thinking
              : kind === "unverified"
                ? copy.unverified
                : kind === "empty"
                  ? copy.empty
                  : copy.fallback;
  return {
    kind,
    message: compact(fallback?.trim() || selected.message),
    why: selected.why,
    next: selected.next,
    authoritative: false,
  };
}

export function isAuthoritativeAck(value: unknown): boolean {
  if (value === true) {
    return true;
  }
  const record = asRecord(value);
  if (!record) {
    return false;
  }
  if (record.acknowledged === true || record.acked === true) {
    return true;
  }
  if (typeof record.ackedAt === "string" && record.ackedAt.trim()) {
    return true;
  }
  const status = typeof record.status === "string" ? record.status.trim().toLowerCase() : "";
  const phase = typeof record.phase === "string" ? record.phase.trim().toLowerCase() : "";
  return status === "verified" || phase === "acked";
}

export function sanitizeErrorSurface(
  value: unknown,
  options?: SanitizeErrorSurfaceOptions,
): ErrorSurfaceRecord {
  const language = options?.language;
  const acknowledged = options?.acknowledged === true || isAuthoritativeAck(value);
  const raw = inspectText(value).trim();
  if (!raw) {
    return recordForKind("empty", language, options?.fallback);
  }

  if (THINK_PATTERN.test(raw)) {
    return recordForKind("thinking", language, options?.fallback);
  }
  if (TRACEBACK_PATTERN.test(raw)) {
    return recordForKind("traceback", language, options?.fallback);
  }
  if (looksLikeJsonBody(raw)) {
    return recordForKind("json_body", language, options?.fallback);
  }
  if (UPSTREAM_PATTERN.test(raw) || HTTP_DUMP_PATTERN.test(raw)) {
    return recordForKind("upstream", language, options?.fallback);
  }

  const redacted = redactSecretShapes(raw);
  if (redacted.redacted) {
    const remainder = compact(redacted.text);
    const hasHumanRemainder = remainder.length > 0 && remainder !== REDACTED && !looksLikeBareSuccess(remainder);
    if (hasHumanRemainder && !TRACEBACK_PATTERN.test(remainder) && !looksLikeJsonBody(remainder)) {
      const copy = copyFor(language);
      return {
        kind: "secret",
        message: remainder,
        why: copy.secret.why,
        next: copy.secret.next,
        authoritative: false,
      };
    }
    return recordForKind("secret", language, options?.fallback);
  }

  if (!acknowledged && looksLikeBareSuccess(redacted.text)) {
    return recordForKind("unverified", language, options?.fallback);
  }

  const copy = copyFor(language);
  return {
    kind: "safe",
    message: compact(redacted.text || options?.fallback || copy.fallback.message),
    why: copy.fallback.why,
    next: copy.fallback.next,
    authoritative: acknowledged,
  };
}

export function sanitizeErrorSurfaceText(value: unknown, language?: string): string {
  const raw = inspectText(value).trim();
  if (!raw) {
    return "";
  }
  const surface = sanitizeErrorSurface(value, { language });
  if (surface.kind === "safe") {
    return surface.message;
  }
  return compact(`${surface.message} ${surface.next}`);
}

function waitingComposerEnqueueGuidance(language?: string): { message: string; why: string; next: string } {
  if (language === "zh-CN") {
    return {
      message: "这条验证说明没有进入待确认队列。",
      why: "计划仍在等待证据，没有新增待采纳项。",
      next: "回到证据输入框再试一次。",
    };
  }
  return {
    message: "The verify note was not queued.",
    why: "Plan is still waiting for evidence. No pending item was added.",
    next: "Retry in the evidence composer.",
  };
}

export function waitingComposerEnqueueFailureSurface(
  value: unknown,
  language?: string,
): ErrorSurfaceRecord {
  const guidance = waitingComposerEnqueueGuidance(language);
  const surface = sanitizeErrorSurface(value, { language, fallback: guidance.message });
  return {
    kind: surface.kind,
    message: surface.message,
    why: guidance.why,
    next: guidance.next,
    authoritative: false,
  };
}

export function waitingComposerEnqueueFailureText(value: unknown, language?: string): string {
  const surface = waitingComposerEnqueueFailureSurface(value, language);
  return compact(`${surface.message} ${surface.why} ${surface.next}`);
}

export function sanitizeErrorSurfaceJson(value: unknown, language?: string): string {
  if (value === undefined || value === null) {
    return "";
  }
  const record = asRecord(value);
  if (record) {
    const cleaned: Record<string, unknown> = {};
    for (const [key, entry] of Object.entries(record)) {
      if (/^(?:api[_-]?key|access[_-]?token|authorization|client[_-]?secret|secret|password|token)$/i.test(key)) {
        cleaned[key] = REDACTED;
        continue;
      }
      if (typeof entry === "string") {
        const surface = sanitizeErrorSurface(entry, { language });
        cleaned[key] = surface.kind === "safe" ? surface.message : REDACTED;
        continue;
      }
      cleaned[key] = entry;
    }
    try {
      const rendered = JSON.stringify(cleaned, null, 2);
      if (TRACEBACK_PATTERN.test(rendered) || THINK_PATTERN.test(rendered)) {
        return sanitizeErrorSurface(rendered, { language }).message;
      }
      return redactSecretShapes(rendered).text;
    } catch {
      return sanitizeErrorSurfaceText(value, language);
    }
  }
  if (typeof value === "string") {
    return sanitizeErrorSurfaceText(value, language);
  }
  try {
    return sanitizeErrorSurfaceJson(JSON.parse(JSON.stringify(value)), language);
  } catch {
    return sanitizeErrorSurfaceText(value, language);
  }
}

export function describeSafeStructuredValue(
  value: unknown,
  language?: string,
  emptyLabel = "",
): string {
  if (value === undefined || value === null) {
    return emptyLabel;
  }
  if (typeof value === "string") {
    return sanitizeErrorSurfaceText(value, language) || emptyLabel;
  }
  const record = asRecord(value);
  if (record) {
    const lines: string[] = [];
    for (const [key, entry] of Object.entries(record)) {
      if (/^(?:api[_-]?key|access[_-]?token|authorization|client[_-]?secret|secret|password|token)$/i.test(key)) {
        continue;
      }
      if (typeof entry === "string" && entry.trim()) {
        const text = sanitizeErrorSurfaceText(entry, language);
        if (text) {
          lines.push(`${key}: ${text}`);
        }
        continue;
      }
      if (typeof entry === "number" && Number.isFinite(entry)) {
        lines.push(`${key}: ${entry}`);
        continue;
      }
      if (typeof entry === "boolean") {
        lines.push(`${key}: ${entry}`);
      }
    }
    if (lines.length > 0) {
      return lines.join(" · ");
    }
  }
  const surface = sanitizeErrorSurface(value, { language });
  if (surface.kind === "safe" && !looksLikeJsonBody(inspectText(value))) {
    return surface.message || emptyLabel;
  }
  return compact(`${surface.message} ${surface.next}`) || emptyLabel;
}

const SECRET_FIELD_KEY =
  /^(?:api[_-]?key|access[_-]?token|authorization|client[_-]?secret|secret|password|token)$/i;
const TOOL_ERROR_FIELD_KEY =
  /^(?:error|detail|message|traceback|upstream_body|stack|exception|reason)$/i;
const TOOL_DUMP_KEYS = new Set(["choices", "upstream_body", "reasoning_content"]);

function hostStringNeedsSurface(text: string, treatAsError: boolean): boolean {
  if (treatAsError) {
    return true;
  }
  return (
    TRACEBACK_PATTERN.test(text) ||
    looksLikeJsonBody(text) ||
    THINK_PATTERN.test(text) ||
    UPSTREAM_PATTERN.test(text) ||
    HTTP_DUMP_PATTERN.test(text) ||
    redactSecretShapes(text).redacted
  );
}

export function sanitizeHostToolResult(value: unknown, language?: string): unknown {
  if (value === undefined || value === null) {
    return value;
  }
  if (typeof value === "string") {
    return sanitizeErrorSurfaceText(value, language);
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return value;
  }
  if (Array.isArray(value)) {
    return value.map((item) => {
      if (typeof item === "string") {
        return hostStringNeedsSurface(item, false)
          ? sanitizeErrorSurfaceText(item, language)
          : item;
      }
      return sanitizeHostToolResult(item, language);
    });
  }
  const record = asRecord(value);
  if (!record) {
    return sanitizeErrorSurfaceText(value, language);
  }
  const lowerKeys = Object.keys(record).map((key) => key.toLowerCase());
  if (lowerKeys.some((key) => TOOL_DUMP_KEYS.has(key))) {
    return { error: sanitizeErrorSurfaceText(value, language) };
  }
  const cleaned: Record<string, unknown> = {};
  for (const [key, entry] of Object.entries(record)) {
    if (SECRET_FIELD_KEY.test(key)) {
      cleaned[key] = REDACTED;
      continue;
    }
    if (typeof entry === "string") {
      cleaned[key] = hostStringNeedsSurface(entry, TOOL_ERROR_FIELD_KEY.test(key))
        ? sanitizeErrorSurfaceText(entry, language)
        : entry;
      continue;
    }
    cleaned[key] = sanitizeHostToolResult(entry, language);
  }
  return cleaned;
}
