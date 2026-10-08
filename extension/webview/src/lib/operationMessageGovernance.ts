import { TRAINER_OPERATION_COMPLETED_MARKER, type TrainerOperationMessage } from "../../../../shared/src/protocol";
import type { ComposerLanguage } from "./types";

// Pure operation-message governance: message parsing markers, localized
// failure copy, failure sanitization and surface attribution. No React, no
// store access — App.tsx keeps a thin component-side adapter
// (setOperationMessage) that calls into this module.
//
// §四十四: domain failures localize to their owning surface. "global" renders
// on every view; every other scope renders only while its own view is active.

export type OperationMessage = TrainerOperationMessage;

/** Render the generic acknowledgement in the current locale, keeping facts intact. */
export function operationStatusMessageText(message: OperationMessage, language: ComposerLanguage): string {
  if (message.tone !== "success" || message.message !== TRAINER_OPERATION_COMPLETED_MARKER) {
    return message.message;
  }
  const copy: Record<ComposerLanguage, string> = {
    "zh-CN": "操作已完成。",
    "en-US": "Action completed.",
    "es-ES": "Acción completada.",
    "fr-FR": "Action terminée.",
    "de-DE": "Aktion abgeschlossen.",
    "ja-JP": "操作が完了しました。",
    "ko-KR": "작업이 완료되었습니다.",
    "pt-BR": "Ação concluída.",
  };
  return copy[language];
}

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

// Delivery may have arrived even when the response was lost. This notice
// records uncertainty; it does not invent a verdict or promise replay success.
export const ATTESTATION_UNDELIVERED_MARKER = "[[trainer-attestation-undelivered]]";

/** The host rejected this request before dispatch because its scope changed. */
export const OPERATION_SCOPE_CHANGED_MARKER = "[[trainer-operation-scope-changed]]";

export function detectOperationScopeChanged(message: string): boolean {
  return message.includes(OPERATION_SCOPE_CHANGED_MARKER);
}

export function operationScopeChangedMessage(language: ComposerLanguage): string {
  const copy: Record<ComposerLanguage, string> = {
    "zh-CN": "工作区或会话已切换。这次操作没有执行；请在当前会话重试。",
    "en-US": "The workspace or conversation changed. This action was not run; try again in the current conversation.",
    "es-ES": "El espacio de trabajo o la conversación cambió. Esta acción no se ejecutó; inténtalo de nuevo en la conversación actual.",
    "fr-FR": "L’espace de travail ou la conversation a changé. Cette action n’a pas été exécutée ; réessayez dans la conversation actuelle.",
    "de-DE": "Der Arbeitsbereich oder das Gespräch hat sich geändert. Die Aktion wurde nicht ausgeführt; versuche es im aktuellen Gespräch erneut.",
    "ja-JP": "ワークスペースまたは会話が切り替わりました。この操作は実行されていません。現在の会話でもう一度試してください。",
    "ko-KR": "작업 공간이나 대화가 바뀌었습니다. 이 작업은 실행되지 않았습니다. 현재 대화에서 다시 시도하세요.",
    "pt-BR": "O espaço de trabalho ou a conversa mudou. Esta ação não foi executada; tente novamente na conversa atual.",
  };
  return copy[language];
}

export function detectAttestationUndelivered(message: string): boolean {
  return message.includes(ATTESTATION_UNDELIVERED_MARKER);
}

export function attestationUndeliveredMessage(language: ComposerLanguage): string {
  const copy: Record<ComposerLanguage, string> = {
  "zh-CN": "本次验证结果尚未确认保存。保留当前结果，检查学习状态后再继续。",
  "en-US": "This verification result has not been confirmed as saved. Keep the current result and check the learning state before continuing.",
  "es-ES": "No se ha confirmado que este resultado de verificación se haya guardado. Conserva el resultado y comprueba el estado de aprendizaje antes de continuar.",
  "fr-FR": "L’enregistrement de ce résultat de vérification n’est pas confirmé. Conservez le résultat et vérifiez l’état d’apprentissage avant de continuer.",
  "de-DE": "Die Speicherung dieses Prüfergebnisses ist unbestätigt. Behalte das Ergebnis und prüfe den Lernstand, bevor du fortfährst.",
  "ja-JP": "今回の検証結果が保存されたか確認できていません。結果を保持し、学習状態を確認してから続けてください。",
  "ko-KR": "이번 검증 결과의 저장 여부가 확인되지 않았습니다. 현재 결과를 보관하고 학습 상태를 확인한 뒤 계속하세요.",
  "pt-BR": "O salvamento deste resultado de verificação não foi confirmado. Mantenha o resultado e confira o estado de aprendizagem antes de continuar.",
};
  return copy[language];
}

/** Delivery uncertainty is a Training notice, never a verification verdict. */
export function attestationDeliveryNotice(message: string, language: ComposerLanguage):
  { surface: "training"; message: string } | undefined {
  return detectAttestationUndelivered(message)
    ? { surface: "training", message: attestationUndeliveredMessage(language) }
    : undefined;
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
    ...message,
    tone: "error",
    message: detectOperationScopeChanged(message.message)
      ? operationScopeChangedMessage(language)
      : detectAttestationUndelivered(message.message)
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

/** Surface attribution for a banner message uses current domain facts. */
export interface OperationMessageSurfaceFacts {
  message?: string;
  explicitSurface?: OperationMessageSurface;
  planStateFailure?: boolean;
  resourceOperation?: boolean;
}

/** Every new message resolves its own owner; it cannot inherit a prior scope.
 * Keep the earlier string adapter for callers of the extracted helpers.
 * Attestation uncertainty always belongs to Training, including generic relays. */
export function resolveOperationMessageSurface(
  input: string | undefined | OperationMessageSurfaceFacts,
  explicitSurface?: OperationMessageSurface,
): OperationMessageSurface {
  const facts = typeof input === "object" ? input : { message: input, explicitSurface };
  const message = facts.message;
  if (!message) return "global";
  if (detectAttestationUndelivered(message)) {
    return "training";
  }
  if (facts.explicitSurface) return facts.explicitSurface;
  if (facts.planStateFailure || detectPlanRevisionConflict(message) || parseLivePlanTaskGateMarker(message)) return "plan";
  if (facts.resourceOperation) return "resources";
  return "global";
}
