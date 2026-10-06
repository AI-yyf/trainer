import type { TrainerOperationMessage } from "../../../../shared/src/protocol";
import type { ComposerLanguage } from "./types";

// Pure operation-message governance: message parsing markers, localized
// failure copy, failure sanitization and surface attribution. No React, no
// store access — App.tsx keeps a thin component-side adapter
// (setOperationMessage) that calls into this module.
//
// §四十四: domain failures localize to their owning surface. "global" renders
// on every view; every other scope renders only while its own view is active.

export type OperationMessage = TrainerOperationMessage;

export type OperationMessageSurface = "global" | "training" | "plan" | "resources";

export type RecoverableFailureKind = "bootstrap" | "send" | "upload" | "provider" | "operation";

export type LivePlanTaskGateKind = "no_live" | "leftover";

export const recoverableFailureCopy: Record<
  ComposerLanguage,
  Record<RecoverableFailureKind, string>
> = {
  "zh-CN": {
    bootstrap: "暂时没能打开预览。等一会儿再试。",
    send: "这条消息没有发出去。检查一下连接，再试一次。",
    upload: "这个文件暂时没导入成功。确认文件没问题后再试。",
    provider: "还没连上模型。检查一下设置，再试一次。",
    operation: "这一步暂时没完成。再试一次。",
  },
  "en-US": {
    bootstrap: "Preview data could not load. Try again shortly.",
    send: "The message was not sent. Check the connection and try again.",
    upload: "The resource could not be imported. Check the file and try again.",
    provider: "The provider action did not finish. Check the settings and try again.",
    operation: "That action did not finish. Try again.",
  },
  "es-ES": {
    bootstrap: "La vista previa no se pudo abrir por ahora. Vuelve a intentarlo en un momento.",
    send: "El mensaje no se envió. Revisa la conexión e inténtalo de nuevo.",
    upload: "El archivo no se pudo importar. Revisa el archivo e inténtalo de nuevo.",
    provider: "No se pudo completar la conexión del modelo. Revisa los ajustes e inténtalo de nuevo.",
    operation: "Esta acción no se pudo completar. Inténtalo de nuevo.",
  },
  "fr-FR": {
    bootstrap: "La prévisualisation ne s'est pas ouverte. Réessayez dans un instant.",
    send: "Le message n'a pas été envoyé. Vérifiez la connexion puis réessayez.",
    upload: "Le fichier n'a pas pu être importé. Vérifiez-le puis réessayez.",
    provider: "La connexion au modèle n'a pas abouti. Vérifiez les réglages puis réessayez.",
    operation: "Cette action n'a pas pu être terminée. Réessayez.",
  },
  "de-DE": {
    bootstrap: "Die Vorschau konnte nicht geöffnet werden. Versuche es gleich noch einmal.",
    send: "Die Nachricht wurde nicht gesendet. Prüfe die Verbindung und versuche es erneut.",
    upload: "Die Datei konnte nicht importiert werden. Prüfe die Datei und versuche es erneut.",
    provider: "Die Modellverbindung konnte nicht abgeschlossen werden. Prüfe die Einstellungen und versuche es erneut.",
    operation: "Dieser Schritt konnte nicht abgeschlossen werden. Versuche es erneut.",
  },
  "ja-JP": {
    bootstrap: "プレビューを開けませんでした。少し待ってからもう一度試してください。",
    send: "メッセージを送信できませんでした。接続を確認して、もう一度試してください。",
    upload: "ファイルを取り込めませんでした。ファイルを確認して、もう一度試してください。",
    provider: "モデルへの接続を完了できませんでした。設定を確認して、もう一度試してください。",
    operation: "この操作を完了できませんでした。もう一度試してください。",
  },
  "ko-KR": {
    bootstrap: "미리 보기를 열 수 없었습니다. 잠시 후 다시 시도하세요.",
    send: "메시지를 보내지 못했습니다. 연결을 확인한 뒤 다시 시도하세요.",
    upload: "파일을 가져오지 못했습니다. 파일을 확인하고 다시 시도하세요.",
    provider: "모델 연결을 완료하지 못했습니다. 설정을 확인한 뒤 다시 시도하세요.",
    operation: "이 작업을 완료하지 못했습니다. 다시 시도하세요.",
  },
  "pt-BR": {
    bootstrap: "Não foi possível abrir a visualização agora. Tente novamente em instantes.",
    send: "Não foi possível enviar a mensagem. Verifique a conexão e tente novamente.",
    upload: "Não foi possível importar o arquivo. Verifique o arquivo e tente novamente.",
    provider: "Não foi possível concluir a conexão com o modelo. Verifique as configurações e tente novamente.",
    operation: "Não foi possível concluir esta ação. Tente novamente.",
  },
};

export const PLAN_REVISION_CONFLICT_MARKER =
  /\[\[trainer-plan-revision-conflict(?::(\d+))?\]\](?:\s|$)/i;

export const LIVE_PLAN_TASK_GATE_MARKER =
  /^\[\[trainer-live-plan-task-gate:(no_live|leftover)\]\](?:\s|$)/i;

// Host attestation delivery failed: the run completed but the evidence never
// reached the training ledger. The host ships only this language-neutral
// marker; the copy and the Training-surface scoping live here.
export const ATTESTATION_UNDELIVERED_MARKER =
  /\[\[trainer-attestation-undelivered\]\](?:\s|$)/i;

export function detectAttestationUndelivered(message: string): boolean {
  return ATTESTATION_UNDELIVERED_MARKER.test(message.trim());
}

export function attestationUndeliveredMessage(language: ComposerLanguage): string {
  const copy: Record<ComposerLanguage, string> = {
    "zh-CN": "结果已验证，但证据还没有送达教练。重新验证一次即可补记。",
    "en-US": "The result was verified, but the evidence did not reach the trainer. Run the verification again to record it.",
    "es-ES": "El resultado se verificó, pero la evidencia no llegó al entrenador. Vuelve a ejecutar la verificación para registrarlo.",
    "fr-FR": "Le résultat a été vérifié, mais la preuve n'est pas parvenue au coach. Relancez la vérification pour l'enregistrer.",
    "de-DE": "Das Ergebnis wurde verifiziert, aber der Nachweis hat den Trainer nicht erreicht. Führe die Verifizierung erneut aus, um ihn zu erfassen.",
    "ja-JP": "結果は検証されましたが、エビデンスがまだコーチに届いていません。もう一度検証を実行すると記録されます。",
    "ko-KR": "결과는 검증되었지만 증거가 아직 코치에 전달되지 않았습니다. 검증을 다시 실행하면 기록됩니다.",
    "pt-BR": "O resultado foi verificado, mas a evidência não chegou ao treinador. Execute a verificação novamente para registrá-la.",
  };
  return copy[language] ?? copy["en-US"];
}

export function providerRecoveryMessage(language: ComposerLanguage): string {
  const copy: Record<ComposerLanguage, string> = {
    "zh-CN": "连接还没有通过。请检查服务地址、API key 和模型名称，然后再试一次。",
    "en-US": "The connection did not pass yet. Check the service address, API key, and model name, then try again.",
    "es-ES": "La conexión aún no pasó la comprobación. Revisa la dirección del servicio, la clave API y el modelo, e inténtalo de nuevo.",
    "fr-FR": "La connexion n'a pas encore passé la vérification. Vérifiez l'adresse du service, la clé API et le modèle, puis réessayez.",
    "de-DE": "Die Verbindung hat die Prüfung noch nicht bestanden. Prüfen Sie Serviceadresse, API-Schlüssel und Modellnamen und versuchen Sie es erneut.",
    "ja-JP": "接続はまだ確認できていません。サービスのアドレス、API キー、モデル名を確認して、もう一度試してください。",
    "ko-KR": "연결 확인이 아직 끝나지 않았습니다. 서비스 주소, API 키, 모델 이름을 확인한 뒤 다시 시도하세요.",
    "pt-BR": "A conexão ainda não passou na verificação. Confira o endereço do serviço, a chave de API e o modelo, depois tente novamente.",
  };
  return copy[language] ?? copy["en-US"];
}

export function recoverableFailureMessage(
  kind: RecoverableFailureKind,
  language: ComposerLanguage,
): string {
  if (kind === "provider") {
    return providerRecoveryMessage(language);
  }
  return recoverableFailureCopy[language]?.[kind] ?? recoverableFailureCopy["en-US"][kind];
}

export function livePlanTaskGateFailureMessage(
  kind: LivePlanTaskGateKind,
  language: ComposerLanguage,
): string {
  const copy: Record<ComposerLanguage, Record<LivePlanTaskGateKind, string>> = {
    "zh-CN": {
      no_live: "当前没有正式计划，所以还不能改计划或生成任务。先生成计划，再试一次。",
      leftover: "这里只有旧计划痕迹，不是当前正式计划。先生成计划，再试一次。",
    },
    "en-US": {
      no_live:
        "No live plan is bound, so Trainer will not invent a task or mutate leftover as live. Generate a plan first.",
      leftover:
        "Only leftover plan traces remain, not a live plan. Generate a plan first; Trainer will not resurrect leftover as live.",
    },
    "es-ES": {
      no_live:
        "No hay un plan en vivo, así que Trainer no inventará una tarea ni mutará un resto como vivo. Genera un plan primero.",
      leftover:
        "Solo quedan rastros de un plan anterior, no un plan en vivo. Genera un plan primero; Trainer no resucitará el resto como vivo.",
    },
    "fr-FR": {
      no_live:
        "Aucun plan actif n'est lié, donc Trainer n'inventera pas de tâche et ne mutera pas un reste comme actif. Générez d'abord un plan.",
      leftover:
        "Il ne reste que des traces d'ancien plan, pas un plan actif. Générez d'abord un plan ; Trainer ne ressuscitera pas le reste comme actif.",
    },
    "de-DE": {
      no_live:
        "Es ist kein live-Plan gebunden, daher erfindet Trainer keine Aufgabe und mutiert keinen Rest als live. Erzeuge zuerst einen Plan.",
      leftover:
        "Nur Restspuren eines Plans sind da, kein live-Plan. Erzeuge zuerst einen Plan; Trainer belebt keinen Rest als live wieder.",
    },
    "ja-JP": {
      no_live:
        "正式な計画がないため、タスク作成や古い計画の更新はできません。先に計画を生成してください。",
      leftover:
        "残っているのは古い計画の痕跡だけで、正式な計画ではありません。先に計画を生成してください。",
    },
    "ko-KR": {
      no_live:
        "살아있는 계획이 없어 과제를 만들거나 남은 계획을 바꾸지 않습니다. 먼저 계획을 생성하세요.",
      leftover:
        "남은 건 예전 계획 흔적일 뿐, 현재 계획이 아닙니다. 먼저 계획을 생성하세요. 남은 계획을 되살리지 않습니다.",
    },
    "pt-BR": {
      no_live:
        "Não há plano ao vivo vinculado, então o Trainer não inventará uma tarefa nem mutará resto como ao vivo. Gere um plano primeiro.",
      leftover:
        "Só restam rastros de plano antigo, não um plano ao vivo. Gere um plano primeiro; o Trainer não ressuscitará o resto como ao vivo.",
    },
  };
  return copy[language]?.[kind] ?? copy["en-US"][kind];
}

export function planRevisionConflictMessage(
  currentRevision: string | undefined,
  language: ComposerLanguage,
): string {
  const rev = currentRevision ?? "?";
  const copy: Record<ComposerLanguage, string> = {
    "zh-CN": `计划已被另一个窗口修改（当前版本 ${rev}）。请刷新后重试，系统已阻止覆盖。`,
    "en-US": `The plan was modified in another window (current revision ${rev}). Refresh and retry — the overwrite was blocked.`,
    "es-ES": `El plan fue modificado en otra ventana (revisión actual ${rev}). Actualice y reintente; la sobrescritura fue bloqueada.`,
    "fr-FR": `Le plan a été modifié dans une autre fenêtre (révision actuelle ${rev}). Actualisez et réessayez ; l'écrasement a été bloqué.`,
    "de-DE": `Der Plan wurde in einem anderen Fenster geändert (aktuelle Revision ${rev}). Aktualisieren und wiederholen — die Überschreibung wurde blockiert.`,
    "ja-JP": `プランが別のウィンドウで変更されました（現在のリビジョン ${rev}）。更新して再試行してください。上書きはブロックされました。`,
    "ko-KR": `플랜이 다른 창에서 수정되었습니다 (현재 버전 ${rev}). 새로고침 후 재시도하세요. 덮어쓰기가 차단되었습니다.`,
    "pt-BR": `O plano foi modificado em outra janela (revisão atual ${rev}). Atualize e tente novamente; a sobrescrita foi bloqueada.`,
  };
  return copy[language] ?? copy["en-US"];
}

export function detectPlanRevisionConflict(message: string): { revision: string } | undefined {
  const match = PLAN_REVISION_CONFLICT_MARKER.exec(message.trim());
  return match ? { revision: match[1] ?? "?" } : undefined;
}

export function parseLivePlanTaskGateMarker(message: string): LivePlanTaskGateKind | undefined {
  const match = LIVE_PLAN_TASK_GATE_MARKER.exec(message.trim());
  const kind = match?.[1]?.toLowerCase();
  return kind === "no_live" || kind === "leftover" ? kind : undefined;
}

export function sanitizeOperationFailureMessage(
  message: OperationMessage,
  language: ComposerLanguage,
): OperationMessage {
  if (message.tone !== "error") {
    return message;
  }

  const localRecoveryMessages = Object.values(
    recoverableFailureCopy[language] ?? recoverableFailureCopy["en-US"],
  );
  localRecoveryMessages.push(providerRecoveryMessage(language));
  localRecoveryMessages.push(livePlanTaskGateFailureMessage("no_live", language));
  localRecoveryMessages.push(livePlanTaskGateFailureMessage("leftover", language));
  localRecoveryMessages.push(
    "验证未通过：当前训练卡片不是实时状态。",
    "没有可验证的当前文件。",
    "预览不能验真实工作区文件。请回 VS Code 打开文件后再验证。",
    "Verification failed: this training card is not live.",
    "There is no current file to verify.",
    "Preview cannot verify a real workspace file. Open the file in VS Code, then verify there.",
  );
  const revisionConflict2 = detectPlanRevisionConflict(message.message);
  const livePlanGate = parseLivePlanTaskGateMarker(message.message);
  return {
    tone: "error",
    message: detectAttestationUndelivered(message.message)
      ? attestationUndeliveredMessage(language)
      : revisionConflict2
      ? planRevisionConflictMessage(revisionConflict2.revision, language)
      : livePlanGate
      ? livePlanTaskGateFailureMessage(livePlanGate, language)
      : localRecoveryMessages.includes(message.message)
        ? message.message
        : recoverableFailureMessage("operation", language),
  };
}

/** Surface attribution for a banner message: an explicit surface wins; plan
 * conflict / live-plan gate markers stay inside Learning and an attestation
 * delivery failure stays inside Training, even when relayed by a generic
 * caller; everything else stays global. */
export function resolveOperationMessageSurface(
  message: string | undefined,
  explicitSurface?: OperationMessageSurface,
): OperationMessageSurface {
  if (!message) {
    return "global";
  }
  if (explicitSurface) {
    return explicitSurface;
  }
  if (detectAttestationUndelivered(message)) {
    return "training";
  }
  if (detectPlanRevisionConflict(message) || parseLivePlanTaskGateMarker(message)) {
    return "plan";
  }
  return "global";
}
