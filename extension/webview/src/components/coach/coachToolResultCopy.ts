import type { ComposerLanguage } from "../../lib/types";

type CoachToolResultCopy = {
  update: string;
  completed: string;
  currentStep: string;
  failed: string;
  retry: string;
  next: string;
  needsRetry: string;
  blocked: string;
  found: (count: number) => string;
  checked: (count: number) => string;
  cardReady: string;
  noPlan: string;
};

const copy: Record<ComposerLanguage, CoachToolResultCopy> = {
  "zh-CN": {
    update: "\u5de5\u5177\u66f4\u65b0", completed: "\u5df2\u5b8c\u6210", currentStep: "\u5f53\u524d\u6b65\u9aa4",
    failed: "\u8fd9\u4e00\u6b65\u6ca1\u6709\u5b8c\u6210", retry: "\u53ef\u4ee5\u7a0d\u540e\u91cd\u8bd5\uff1b\u82e5\u6301\u7eed\u5931\u8d25\uff0c\u8bf7\u5148\u5728\u8bbe\u7f6e\u4e2d\u68c0\u67e5\u8fde\u63a5\u72b6\u6001\u3002", next: "\u4e0b\u4e00\u6b65\uff1a",
    needsRetry: "\u9700\u8981\u518d\u8bd5\u4e00\u6b21", blocked: "\u6709\u4e00\u6b65\u6ca1\u6709\u5b8c\u6210\u3002\u4f60\u53ef\u4ee5\u7ee7\u7eed\u63d0\u95ee\uff0c\u6216\u7a0d\u540e\u91cd\u8bd5\u3002",
    found: (count) => `\u627e\u5230 ${count} \u9879`, checked: (count) => `\u5df2\u6838\u5bf9 ${count} \u884c`, cardReady: "\u8bad\u7ec3\u5361\u5df2\u51c6\u5907\u597d", noPlan: "\u8fd8\u6ca1\u6709\u6b63\u5f0f\u8ba1\u5212",
  },
  "en-US": {
    update: "Tool update", completed: "Completed", currentStep: "Current step", failed: "This step did not finish", retry: "Try again shortly. If it keeps failing, check the connection in Settings.", next: "Next: ",
    needsRetry: "Needs another try", blocked: "One step did not finish. You can keep asking or try again shortly.", found: (count) => `Found ${count} items`, checked: (count) => `Checked ${count} lines`, cardReady: "Training card is ready", noPlan: "No formal plan yet",
  },
  "es-ES": {
    update: "Actualizaci\u00f3n de la herramienta", completed: "Completado", currentStep: "Paso actual", failed: "Este paso no se complet\u00f3", retry: "Vuelve a intentarlo en un momento. Si sigue fallando, revisa la conexi\u00f3n en Configuraci\u00f3n.", next: "Siguiente paso: ",
    needsRetry: "Necesita otro intento", blocked: "Un paso no se complet\u00f3. Puedes seguir preguntando o volver a intentarlo en un momento.", found: (count) => `Se encontraron ${count} elementos`, checked: (count) => `Se revisaron ${count} l\u00edneas`, cardReady: "La tarjeta de entrenamiento est\u00e1 lista", noPlan: "A\u00fan no hay un plan formal",
  },
  "fr-FR": {
    update: "Mise \u00e0 jour de l'outil", completed: "Termin\u00e9", currentStep: "\u00c9tape en cours", failed: "Cette \u00e9tape ne s'est pas termin\u00e9e", retry: "R\u00e9essayez dans un instant. Si le probl\u00e8me persiste, v\u00e9rifiez la connexion dans Param\u00e8tres.", next: "Ensuite : ",
    needsRetry: "Nouvel essai requis", blocked: "Une \u00e9tape ne s'est pas termin\u00e9e. Vous pouvez continuer \u00e0 demander ou r\u00e9essayer dans un instant.", found: (count) => `${count} \u00e9l\u00e9ments trouv\u00e9s`, checked: (count) => `${count} lignes v\u00e9rifi\u00e9es`, cardReady: "La carte d'entra\u00eenement est pr\u00eate", noPlan: "Pas encore de plan officiel",
  },
  "de-DE": {
    update: "Werkzeugaktualisierung", completed: "Abgeschlossen", currentStep: "Aktueller Schritt", failed: "Dieser Schritt wurde nicht abgeschlossen", retry: "Versuche es gleich noch einmal. Wenn es weiterhin fehlschl\u00e4gt, pr\u00fcfe die Verbindung in den Einstellungen.", next: "N\u00e4chster Schritt: ",
    needsRetry: "Noch ein Versuch n\u00f6tig", blocked: "Ein Schritt wurde nicht abgeschlossen. Du kannst weiterfragen oder es gleich noch einmal versuchen.", found: (count) => `${count} Eintr\u00e4ge gefunden`, checked: (count) => `${count} Zeilen gepr\u00fcft`, cardReady: "Trainingskarte ist bereit", noPlan: "Noch kein formeller Plan",
  },
  "ja-JP": {
    update: "\u30c4\u30fc\u30eb\u306e\u66f4\u65b0", completed: "\u5b8c\u4e86", currentStep: "\u73fe\u5728\u306e\u624b\u9806", failed: "\u3053\u306e\u624b\u9806\u306f\u5b8c\u4e86\u3057\u307e\u305b\u3093\u3067\u3057\u305f", retry: "\u5c11\u3057\u5f85\u3063\u3066\u304b\u3089\u3082\u3046\u4e00\u5ea6\u8a66\u3057\u3066\u304f\u3060\u3055\u3044\u3002\u7d9a\u304f\u5834\u5408\u306f\u3001\u8a2d\u5b9a\u3067\u63a5\u7d9a\u72b6\u614b\u3092\u78ba\u8a8d\u3057\u3066\u304f\u3060\u3055\u3044\u3002", next: "\u6b21\u306e\u624b\u9806: ",
    needsRetry: "\u3082\u3046\u4e00\u5ea6\u8a66\u3059\u5fc5\u8981\u304c\u3042\u308a\u307e\u3059", blocked: "\u4e00\u3064\u306e\u624b\u9806\u304c\u5b8c\u4e86\u3057\u307e\u305b\u3093\u3067\u3057\u305f\u3002\u8cea\u554f\u3092\u7d9a\u3051\u308b\u304b\u3001\u5c11\u3057\u5f85\u3063\u3066\u518d\u8a66\u884c\u3067\u304d\u307e\u3059\u3002", found: (count) => `${count}\u4ef6\u898b\u3064\u304b\u308a\u307e\u3057\u305f`, checked: (count) => `${count}\u884c\u3092\u78ba\u8a8d\u3057\u307e\u3057\u305f`, cardReady: "\u30c8\u30ec\u30fc\u30cb\u30f3\u30b0\u30ab\u30fc\u30c9\u306e\u6e96\u5099\u304c\u3067\u304d\u307e\u3057\u305f", noPlan: "\u307e\u3060\u6b63\u5f0f\u306a\u8a08\u753b\u306f\u3042\u308a\u307e\u305b\u3093",
  },
  "ko-KR": {
    update: "\ub3c4\uad6c \uc5c5\ub370\uc774\ud2b8", completed: "\uc644\ub8cc", currentStep: "\ud604\uc7ac \ub2e8\uacc4", failed: "\uc774 \ub2e8\uacc4\ub97c \uc644\ub8cc\ud558\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4", retry: "\uc7a0\uc2dc \ud6c4 \ub2e4\uc2dc \uc2dc\ub3c4\ud574 \ubcf4\uc138\uc694. \uacc4\uc18d \uc2e4\ud328\ud558\uba74 \uc124\uc815\uc5d0\uc11c \uc5f0\uacb0 \uc0c1\ud0dc\ub97c \ud655\uc778\ud574 \ubcf4\uc138\uc694.", next: "\ub2e4\uc74c: ",
    needsRetry: "\ud55c \ubc88 \ub354 \uc2dc\ub3c4\ud574 \ubcf4\uc138\uc694", blocked: "\ud55c \ub2e8\uacc4\uac00 \uc644\ub8cc\ub418\uc9c0 \uc54a\uc558\uc2b5\ub2c8\ub2e4. \uacc4\uc18d \uc9c8\ubb38\ud558\uac70\ub098 \uc7a0\uc2dc \ud6c4 \ub2e4\uc2dc \uc2dc\ub3c4\ud560 \uc218 \uc788\uc2b5\ub2c8\ub2e4.", found: (count) => `${count}\uac1c \ud56d\ubaa9\uc744 \ucc3e\uc558\uc2b5\ub2c8\ub2e4`, checked: (count) => `${count}\uc904\uc744 \ud655\uc778\ud588\uc2b5\ub2c8\ub2e4`, cardReady: "\ud6c8\ub828 \uce74\ub4dc\uac00 \uc900\ube44\ub418\uc5c8\uc2b5\ub2c8\ub2e4", noPlan: "\uc544\uc9c1 \uc815\uc2dd \uacc4\ud68d\uc774 \uc5c6\uc2b5\ub2c8\ub2e4",
  },
  "pt-BR": {
    update: "Atualiza\u00e7\u00e3o da ferramenta", completed: "Conclu\u00eddo", currentStep: "Etapa atual", failed: "Esta etapa n\u00e3o foi conclu\u00edda", retry: "Tente novamente em instantes. Se continuar falhando, verifique a conex\u00e3o em Configura\u00e7\u00f5es.", next: "Pr\u00f3ximo passo: ",
    needsRetry: "Precisa tentar novamente", blocked: "Uma etapa n\u00e3o foi conclu\u00edda. Voc\u00ea pode continuar perguntando ou tentar de novo em instantes.", found: (count) => `${count} itens encontrados`, checked: (count) => `${count} linhas verificadas`, cardReady: "O cart\u00e3o de treinamento est\u00e1 pronto", noPlan: "Ainda n\u00e3o h\u00e1 um plano formal",
  },
};

const technicalResultPattern =
  /(?:traceback|stack trace|exception|\bhttps?:\/\/|\bhttps?\s+\d{3}\b|\b[45]\d{2}\b|\b(?:error|err)\s*[:=]|[A-Za-z]:[\\/]|(?:^|\s)\/(?:[\w.-]+\/)+|[{}\[\]]|\bat\s+\w+\s*\()/i;

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

export function resolveCoachToolResultCopy(language: ComposerLanguage): CoachToolResultCopy {
  return copy[language] ?? copy["en-US"];
}

export function safeCoachResultText(value: unknown, maxLength = 120): string | undefined {
  if (typeof value !== "string") {
    return undefined;
  }
  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized || technicalResultPattern.test(normalized)) {
    return undefined;
  }
  return normalized.length > maxLength
    ? `${normalized.slice(0, maxLength - 1).trimEnd()}...`
    : normalized;
}

export function hasCoachToolResultFailure(error: unknown, result: unknown): boolean {
  if (typeof error === "string" && error.trim().length > 0) {
    return true;
  }
  const record = asRecord(result);
  return Boolean(
    record &&
      (record.ok === false || record.success === false || record.status === "failed" ||
        (typeof record.error === "string" && record.error.trim().length > 0)),
  );
}

export function summarizeSafeCoachToolResult(
  result: unknown,
  language: ComposerLanguage,
): string | undefined {
  const record = asRecord(result);
  if (!record) {
    return undefined;
  }
  const text = resolveCoachToolResultCopy(language);
  const items = Array.isArray(record.hits)
    ? record.hits
    : Array.isArray(record.items)
      ? record.items
      : undefined;
  if (items) {
    return text.found(items.length);
  }
  if (typeof record.line_count === "number") {
    return text.checked(record.line_count);
  }
  if (typeof record.card_id === "string" && record.card_id.trim()) {
    return text.cardReady;
  }
  if (record.plan === null || record.summary === "no plan exists for this workspace yet") {
    return text.noPlan;
  }
  // Agent activity results may carry a concise human-readable hint. Keep the
  // existing safety filter so transport diagnostics and structured payloads
  // never reach the compact status rail.
  for (const key of ["summary", "note"]) {
    const safeHint = safeCoachResultText(record[key]);
    if (safeHint) {
      return safeHint;
    }
  }
  // Tool payload prose can contain provider diagnostics. Generic status UI only shows
  // local interpretations of known fields, never arbitrary result text.
  return undefined;
}
