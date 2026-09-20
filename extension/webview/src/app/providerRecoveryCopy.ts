/**
 * Provider recovery copy + scenario resolution (extracted from App.tsx,
 * batch 7). Pure helpers over the provider view — no component state.
 */

import { describeProviderSendState, hasSavedProviderProfiles } from "../../../../shared/src/providerStatus";
import type { ComposerLanguage } from "../../../../shared/src/types";
import type { ActiveWorkbenchView, ProviderConfigView } from "../lib/types";

function providerHasVerifiedStreamingProbe(
  provider: Pick<ProviderConfigView, "lastTestResult">,
): boolean {
  const lastTest = provider.lastTestResult;
  const streamingEvidence = lastTest?.capabilityEvidence?.find((entry) => {
    const name = entry.name.trim().toLowerCase();
    return name === "streaming" || name === "stream";
  });

  return (
    lastTest?.ok === true &&
    lastTest.streamingReady === true &&
    lastTest.streamProbeStatus === "verified" &&
    streamingEvidence?.state === "verified" &&
    streamingEvidence.observed === true
  );
}

function streamingCapabilityBlockReason(language: ComposerLanguage): string {
  return language === "zh-CN"
    ? "\u5f53\u524d\u8fde\u63a5\u8fd8\u6ca1\u6709\u9a8c\u8bc1\u771f\u5b9e\u6d41\u5f0f\u8f93\u51fa\u3002\u8bf7\u5728\u8bbe\u7f6e\u4e2d\u91cd\u65b0\u6d4b\u8bd5 Provider\uff0c\u786e\u8ba4\u80fd\u89c2\u5bdf\u5230\u589e\u91cf\u7247\u6bb5\u540e\u518d\u5bf9\u8bdd\u3002"
    : "This connection has not verified real incremental output yet. Retest the provider in Settings and continue after a visible stream chunk is observed.";
}

function providerCoachBanner(
  provider: ProviderConfigView,
  language: ComposerLanguage,
  connectionState?: "starting" | "connected" | "offline",
  blockedMessage?: string,
): { tone: "info" | "error"; message: string } | undefined {
  const recovery = providerRecoverySummary(provider, language, connectionState);
  if (connectionState === "offline") {
    return {
      tone: "error",
      message: blockedMessage ?? recovery.detail,
    };
  }

  if (connectionState === "starting") {
    return {
      tone: "info",
      message: blockedMessage ?? recovery.detail,
    };
  }

  const sendState = describeProviderSendState(provider, language);
  const lastCategory = provider.lastTestResult?.errorCategory ?? provider.modelErrorCategory;

  if (
    (sendState.status === "blocked_error" || sendState.status === "degraded_error") &&
    lastCategory === "language_corruption"
  ) {
    return {
      tone: sendState.blocked ? "error" : "info",
      message: blockedMessage ?? providerRecoveryLocale(language).languageIntegrityDetail,
    };
  }

  if (
    (sendState.status === "blocked_error" || sendState.status === "degraded_error") &&
    lastCategory === "language_probe_inconclusive"
  ) {
    return {
      tone: "info",
      message: blockedMessage ?? recovery.detail,
    };
  }

  if (sendState.blocked) {
    return {
      tone: "error",
      message: blockedMessage ?? recovery.detail,
    };
  }

  if ((sendState.status === "degraded_error" || sendState.status === "refreshing") && sendState.warning) {
    return {
      tone: "info",
      message: sendState.warning,
    };
  }

  return undefined;
}

type ProviderRecoveryScenario =
  | "offline"
  | "starting"
  | "saved_connection"
  | "connection_setup"
  | "missing_key"
  | "checking"
  | "needs_attention";

type ProviderRecoverySummary = {
  title: string;
  detail: string;
  actionLabel: string;
};

type ProviderRecoveryLocale = {
  summary: Record<ProviderRecoveryScenario, ProviderRecoverySummary>;
  status: Record<ProviderRecoveryScenario, string>;
  stillAvailableDetail: string;
  languageIntegrityDetail: string;
  draftWhilePaused: string;
  connectionStillWorks: string;
};

const providerRecoveryCopy: Record<ComposerLanguage, ProviderRecoveryLocale> = {
  "zh-CN": {
    summary: {
      offline: {
        title: "Trainer 正在自动恢复",
        detail: "无需重新测试模型连接；后台服务恢复后会继续当前对话。",
        actionLabel: "重试启动",
      },
      starting: {
        title: "Trainer 正在准备中",
        detail: "稍等片刻，当前对话会自动恢复。",
        actionLabel: "查看连接",
      },
      saved_connection: {
        title: "选择一组已保存连接",
        detail: "“设置”里已有可用连接。选中它后继续。",
        actionLabel: "选择连接",
      },
      connection_setup: {
        title: "先连接模型",
        detail: "在“设置”完成连接后，Trainer 会从当前目标继续。",
        actionLabel: "连接模型",
      },
      missing_key: {
        title: "补上 API 密钥",
        detail: "这组连接已保存，但还缺少密钥。",
        actionLabel: "补上密钥",
      },
      checking: {
        title: "正在检查模型连接",
        detail: "Trainer 正在确认连接，请稍等。",
        actionLabel: "查看连接",
      },
      needs_attention: {
        title: "连接需要检查",
        detail: "到“设置”检查连接后再试。",
        actionLabel: "检查连接",
      },
    },
    status: {
      offline: "暂时不可用",
      starting: "准备中",
      saved_connection: "待选择",
      connection_setup: "待连接",
      missing_key: "缺少密钥",
      checking: "检查中",
      needs_attention: "需处理",
    },
    stillAvailableDetail: "仍可查看设置、资料和当前计划；新的教练回合会暂停。",
    languageIntegrityDetail: "消息没有正常送达。请在“设置”更换连接后重新测试。",
    draftWhilePaused: "连接恢复前，先把想法记在这里。",
    connectionStillWorks: "当前连接仍可继续",
  },
  "en-US": {
    summary: {
      offline: {
        title: "Trainer is recovering automatically",
        detail: "There is no need to retest the model connection; this conversation resumes when the local service is ready.",
        actionLabel: "Retry startup",
      },
      starting: {
        title: "Trainer is getting ready",
        detail: "Give it a moment. This conversation will resume automatically.",
        actionLabel: "View connection",
      },
      saved_connection: {
        title: "Choose a saved connection",
        detail: "A saved connection is available in Settings. Select it to continue.",
        actionLabel: "Choose connection",
      },
      connection_setup: {
        title: "Connect a model to begin",
        detail: "Finish the connection in Settings. Trainer will continue from your current goal.",
        actionLabel: "Connect model",
      },
      missing_key: {
        title: "Add the API key",
        detail: "This connection is saved but still needs its key.",
        actionLabel: "Add key",
      },
      checking: {
        title: "Checking the model connection",
        detail: "Wait a moment while Trainer confirms the connection.",
        actionLabel: "View connection",
      },
      needs_attention: {
        title: "Connection needs attention",
        detail: "Check the connection in Settings, then try again.",
        actionLabel: "Check connection",
      },
    },
    status: {
      offline: "Unavailable",
      starting: "Starting",
      saved_connection: "Choose connection",
      connection_setup: "Setup needed",
      missing_key: "Key needed",
      checking: "Checking",
      needs_attention: "Needs attention",
    },
    stillAvailableDetail: "You can still review Settings, resources, and the current plan. New coach turns stay paused.",
    languageIntegrityDetail: "Messages did not arrive intact. In Settings, switch connections and test again.",
    draftWhilePaused: "Keep drafting while setup finishes.",
    connectionStillWorks: "Current connection still works",
  },
  "es-ES": {
    summary: {
      offline: {
        title: "Trainer se está recuperando automáticamente",
        detail: "No hace falta volver a probar el modelo; la conversación continuará cuando el servicio local esté listo.",
        actionLabel: "Reintentar inicio",
      },
      starting: {
        title: "Trainer se está preparando",
        detail: "Espera un momento. Esta conversación se reanudará automáticamente.",
        actionLabel: "Ver conexión",
      },
      saved_connection: {
        title: "Elige una conexión guardada",
        detail: "Hay una conexión guardada en Ajustes. Elígela para continuar.",
        actionLabel: "Elegir conexión",
      },
      connection_setup: {
        title: "Conecta un modelo para empezar",
        detail: "Completa la conexión en Ajustes. Trainer continuará desde tu objetivo actual.",
        actionLabel: "Conectar modelo",
      },
      missing_key: {
        title: "Añade la clave API",
        detail: "La conexión está guardada, pero aún necesita la clave.",
        actionLabel: "Añadir clave",
      },
      checking: {
        title: "Comprobando la conexión del modelo",
        detail: "Espera un momento mientras Trainer confirma la conexión.",
        actionLabel: "Ver conexión",
      },
      needs_attention: {
        title: "La conexión necesita atención",
        detail: "Revisa la conexión en Ajustes y vuelve a intentarlo.",
        actionLabel: "Revisar conexión",
      },
    },
    status: {
      offline: "No disponible",
      starting: "Iniciando",
      saved_connection: "Elegir conexión",
      connection_setup: "Falta configurar",
      missing_key: "Falta clave",
      checking: "Comprobando",
      needs_attention: "Revisar conexión",
    },
    stillAvailableDetail: "Aún puedes revisar Ajustes, recursos y el plan actual. Los nuevos turnos del coach quedan en pausa.",
    languageIntegrityDetail: "Los mensajes no llegaron correctamente. Cambia de conexión en Ajustes y vuelve a probar.",
    draftWhilePaused: "Puedes seguir escribiendo mientras termina la configuración.",
    connectionStillWorks: "La conexión actual sigue funcionando",
  },
  "fr-FR": {
    summary: {
      offline: {
        title: "Trainer se rétablit automatiquement",
        detail: "Inutile de retester le modèle ; la conversation reprendra lorsque le service local sera prêt.",
        actionLabel: "Relancer",
      },
      starting: {
        title: "Trainer se prépare",
        detail: "Patientez un instant. Cette conversation reprendra automatiquement.",
        actionLabel: "Voir la connexion",
      },
      saved_connection: {
        title: "Choisissez une connexion enregistrée",
        detail: "Une connexion enregistrée est disponible dans Paramètres. Sélectionnez-la pour continuer.",
        actionLabel: "Choisir la connexion",
      },
      connection_setup: {
        title: "Connectez un modèle pour commencer",
        detail: "Terminez la connexion dans Paramètres. Trainer reprendra votre objectif actuel.",
        actionLabel: "Connecter un modèle",
      },
      missing_key: {
        title: "Ajoutez la clé API",
        detail: "Cette connexion est enregistrée, mais sa clé manque encore.",
        actionLabel: "Ajouter la clé",
      },
      checking: {
        title: "Vérification de la connexion du modèle",
        detail: "Patientez pendant que Trainer confirme la connexion.",
        actionLabel: "Voir la connexion",
      },
      needs_attention: {
        title: "La connexion demande une vérification",
        detail: "Vérifiez la connexion dans Paramètres, puis réessayez.",
        actionLabel: "Vérifier la connexion",
      },
    },
    status: {
      offline: "Indisponible",
      starting: "Démarrage",
      saved_connection: "Choisir la connexion",
      connection_setup: "Configuration requise",
      missing_key: "Clé requise",
      checking: "Vérification",
      needs_attention: "À vérifier",
    },
    stillAvailableDetail: "Vous pouvez encore consulter Paramètres, les ressources et le plan actuel. Les nouveaux tours du coach restent en pause.",
    languageIntegrityDetail: "Les messages ne sont pas arrivés correctement. Changez de connexion dans Paramètres et testez à nouveau.",
    draftWhilePaused: "Vous pouvez continuer à écrire pendant la préparation.",
    connectionStillWorks: "La connexion actuelle fonctionne encore",
  },
  "de-DE": {
    summary: {
      offline: {
        title: "Trainer stellt sich automatisch wieder her",
        detail: "Der Modellzugang muss nicht erneut getestet werden; die Unterhaltung wird fortgesetzt, sobald der lokale Dienst bereit ist.",
        actionLabel: "Start erneut versuchen",
      },
      starting: {
        title: "Trainer wird vorbereitet",
        detail: "Warte kurz. Diese Unterhaltung wird automatisch fortgesetzt.",
        actionLabel: "Verbindung ansehen",
      },
      saved_connection: {
        title: "Wähle eine gespeicherte Verbindung",
        detail: "In Einstellungen ist eine gespeicherte Verbindung verfügbar. Wähle sie zum Fortfahren.",
        actionLabel: "Verbindung wählen",
      },
      connection_setup: {
        title: "Verbinde ein Modell zum Start",
        detail: "Schließe die Verbindung in Einstellungen ab. Trainer macht bei deinem aktuellen Ziel weiter.",
        actionLabel: "Modell verbinden",
      },
      missing_key: {
        title: "API-Schlüssel hinzufügen",
        detail: "Diese Verbindung ist gespeichert, benötigt aber noch ihren Schlüssel.",
        actionLabel: "Schlüssel hinzufügen",
      },
      checking: {
        title: "Modellverbindung wird geprüft",
        detail: "Warte kurz, während Trainer die Verbindung bestätigt.",
        actionLabel: "Verbindung ansehen",
      },
      needs_attention: {
        title: "Verbindung muss geprüft werden",
        detail: "Prüfe die Verbindung in Einstellungen und versuche es erneut.",
        actionLabel: "Verbindung prüfen",
      },
    },
    status: {
      offline: "Nicht verfügbar",
      starting: "Startet",
      saved_connection: "Verbindung wählen",
      connection_setup: "Einrichtung nötig",
      missing_key: "Schlüssel fehlt",
      checking: "Wird geprüft",
      needs_attention: "Prüfung nötig",
    },
    stillAvailableDetail: "Du kannst weiterhin Einstellungen, Materialien und den aktuellen Plan ansehen. Neue Coach-Runden bleiben pausiert.",
    languageIntegrityDetail: "Nachrichten kamen nicht vollständig an. Wechsle die Verbindung in Einstellungen und teste erneut.",
    draftWhilePaused: "Du kannst weiter schreiben, während die Einrichtung fertig wird.",
    connectionStillWorks: "Die aktuelle Verbindung funktioniert weiter",
  },
  "ja-JP": {
    summary: {
      offline: {
        title: "Trainer は自動復旧中です",
        detail: "モデル接続の再テストは不要です。ローカルサービスの復旧後に会話を続行します。",
        actionLabel: "起動を再試行",
      },
      starting: {
        title: "Trainer は準備中です",
        detail: "少し待ってください。この会話は自動で再開します。",
        actionLabel: "接続を確認",
      },
      saved_connection: {
        title: "保存済みの接続を選択",
        detail: "設定に利用できる接続があります。選択して続行してください。",
        actionLabel: "接続を選択",
      },
      connection_setup: {
        title: "モデルを接続して開始",
        detail: "設定で接続を完了してください。Trainer は現在の目標から続けます。",
        actionLabel: "モデルを接続",
      },
      missing_key: {
        title: "API キーを追加",
        detail: "この接続は保存済みですが、キーがまだ必要です。",
        actionLabel: "キーを追加",
      },
      checking: {
        title: "モデル接続を確認中",
        detail: "Trainer が接続を確認しています。少し待ってください。",
        actionLabel: "接続を確認",
      },
      needs_attention: {
        title: "接続の確認が必要です",
        detail: "設定で接続を確認してから、もう一度試してください。",
        actionLabel: "接続を確認",
      },
    },
    status: {
      offline: "利用不可",
      starting: "準備中",
      saved_connection: "接続を選択",
      connection_setup: "設定が必要",
      missing_key: "キーが必要",
      checking: "確認中",
      needs_attention: "要確認",
    },
    stillAvailableDetail: "設定、資料、現在の計画は引き続き確認できます。新しいコーチ対話は一時停止します。",
    languageIntegrityDetail: "メッセージが正しく届きませんでした。設定で接続を切り替えて、もう一度テストしてください。",
    draftWhilePaused: "設定が終わるまで、ここに考えを書き続けられます。",
    connectionStillWorks: "現在の接続は引き続き使えます",
  },
  "ko-KR": {
    summary: {
      offline: {
        title: "Trainer가 자동으로 복구 중입니다",
        detail: "모델 연결을 다시 테스트할 필요가 없습니다. 로컬 서비스가 준비되면 대화를 계속합니다.",
        actionLabel: "시작 다시 시도",
      },
      starting: {
        title: "Trainer를 준비하는 중입니다",
        detail: "잠시 기다려 주세요. 이 대화는 자동으로 다시 시작됩니다.",
        actionLabel: "연결 보기",
      },
      saved_connection: {
        title: "저장된 연결을 선택하세요",
        detail: "설정에 사용할 수 있는 저장된 연결이 있습니다. 선택한 뒤 계속하세요.",
        actionLabel: "연결 선택",
      },
      connection_setup: {
        title: "모델을 연결해 시작하세요",
        detail: "설정에서 연결을 완료하세요. Trainer가 현재 목표부터 이어갑니다.",
        actionLabel: "모델 연결",
      },
      missing_key: {
        title: "API 키를 추가하세요",
        detail: "이 연결은 저장되었지만 아직 키가 필요합니다.",
        actionLabel: "키 추가",
      },
      checking: {
        title: "모델 연결을 확인하는 중입니다",
        detail: "Trainer가 연결을 확인하는 동안 잠시 기다려 주세요.",
        actionLabel: "연결 보기",
      },
      needs_attention: {
        title: "연결을 확인해야 합니다",
        detail: "설정에서 연결을 확인한 뒤 다시 시도하세요.",
        actionLabel: "연결 확인",
      },
    },
    status: {
      offline: "사용 불가",
      starting: "준비 중",
      saved_connection: "연결 선택",
      connection_setup: "설정 필요",
      missing_key: "키 필요",
      checking: "확인 중",
      needs_attention: "확인 필요",
    },
    stillAvailableDetail: "설정, 자료, 현재 계획은 계속 볼 수 있습니다. 새 코치 대화는 잠시 멈춥니다.",
    languageIntegrityDetail: "메시지가 정상적으로 도착하지 않았습니다. 설정에서 연결을 바꾼 뒤 다시 테스트하세요.",
    draftWhilePaused: "설정이 끝날 때까지 여기에서 계속 작성할 수 있습니다.",
    connectionStillWorks: "현재 연결은 계속 사용할 수 있습니다",
  },
  "pt-BR": {
    summary: {
      offline: {
        title: "O Trainer está se recuperando automaticamente",
        detail: "Não é preciso testar o modelo novamente; a conversa continua quando o serviço local estiver pronto.",
        actionLabel: "Tentar iniciar novamente",
      },
      starting: {
        title: "O Trainer está se preparando",
        detail: "Aguarde um momento. Esta conversa será retomada automaticamente.",
        actionLabel: "Ver conexão",
      },
      saved_connection: {
        title: "Escolha uma conexão salva",
        detail: "Há uma conexão salva em Configurações. Selecione-a para continuar.",
        actionLabel: "Escolher conexão",
      },
      connection_setup: {
        title: "Conecte um modelo para começar",
        detail: "Conclua a conexão em Configurações. O Trainer continuará do seu objetivo atual.",
        actionLabel: "Conectar modelo",
      },
      missing_key: {
        title: "Adicione a chave de API",
        detail: "Esta conexão está salva, mas ainda precisa da chave.",
        actionLabel: "Adicionar chave",
      },
      checking: {
        title: "Verificando a conexão do modelo",
        detail: "Aguarde enquanto o Trainer confirma a conexão.",
        actionLabel: "Ver conexão",
      },
      needs_attention: {
        title: "A conexão precisa de atenção",
        detail: "Verifique a conexão em Configurações e tente novamente.",
        actionLabel: "Verificar conexão",
      },
    },
    status: {
      offline: "Indisponível",
      starting: "Iniciando",
      saved_connection: "Escolher conexão",
      connection_setup: "Configuração necessária",
      missing_key: "Chave necessária",
      checking: "Verificando",
      needs_attention: "Verificar conexão",
    },
    stillAvailableDetail: "Você ainda pode revisar Configurações, recursos e o plano atual. Novos turnos do coach ficam pausados.",
    languageIntegrityDetail: "As mensagens não chegaram corretamente. Troque a conexão em Configurações e teste novamente.",
    draftWhilePaused: "Você pode continuar escrevendo enquanto a configuração termina.",
    connectionStillWorks: "A conexão atual continua funcionando",
  },
};

function providerRecoveryLocale(language: ComposerLanguage): ProviderRecoveryLocale {
  return providerRecoveryCopy[language] ?? providerRecoveryCopy["en-US"];
}

function providerRecoveryScenario(
  provider: ProviderConfigView,
  language: ComposerLanguage,
  connectionState?: "starting" | "connected" | "offline",
): ProviderRecoveryScenario {
  if (connectionState === "offline") {
    return "offline";
  }
  if (connectionState === "starting") {
    return "starting";
  }

  const sendState = describeProviderSendState(provider, language);
  if (sendState.status === "missing_provider") {
    return hasSavedProviderProfiles(provider) ? "saved_connection" : "connection_setup";
  }
  if (sendState.status === "missing_api_key") {
    return "missing_key";
  }
  if (sendState.status === "warming" || sendState.status === "refreshing") {
    return "checking";
  }
  return "needs_attention";
}

function providerRecoverySummary(
  provider: ProviderConfigView,
  language: ComposerLanguage,
  connectionState?: "starting" | "connected" | "offline",
): ProviderRecoverySummary {
  const scenario = providerRecoveryScenario(provider, language, connectionState);
  return providerRecoveryLocale(language).summary[scenario];
}

function providerRecoveryStatusLabel(
  provider: ProviderConfigView,
  language: ComposerLanguage,
  connectionState?: "starting" | "connected" | "offline",
): string {
  const scenario = providerRecoveryScenario(provider, language, connectionState);
  return providerRecoveryLocale(language).status[scenario];
}

function providerSetupSummary(
  provider: ProviderConfigView,
  language: ComposerLanguage,
  connectionState?: "starting" | "connected" | "offline",
): ProviderRecoverySummary {
  return providerRecoverySummary(provider, language, connectionState);
}

function blockedComposerSetupMessage(
  provider: ProviderConfigView,
  language: ComposerLanguage,
  _activeView: ActiveWorkbenchView,
  connectionState?: "starting" | "connected" | "offline",
): string {
  return providerRecoverySummary(provider, language, connectionState).detail;
}

function blockedComposerPresenceMessage(
  provider: ProviderConfigView,
  language: ComposerLanguage,
  connectionState?: "starting" | "connected" | "offline",
): string {
  if (connectionState === "offline" || connectionState === "starting") {
    return providerRecoverySummary(provider, language, connectionState).title;
  }

  const sendState = describeProviderSendState(provider, language);
  const lastCategory = provider.lastTestResult?.errorCategory ?? provider.modelErrorCategory;

  if (
    (sendState.status === "blocked_error" || sendState.status === "degraded_error") &&
    lastCategory === "language_corruption"
  ) {
    return providerRecoveryLocale(language).languageIntegrityDetail;
  }

  return providerRecoverySummary(provider, language, connectionState).title;
}

export {
  blockedComposerPresenceMessage,
  blockedComposerSetupMessage,
  providerCoachBanner,
  providerHasVerifiedStreamingProbe,
  providerRecoveryCopy,
  providerRecoveryLocale,
  providerRecoveryScenario,
  providerRecoveryStatusLabel,
  providerRecoverySummary,
  providerSetupSummary,
  streamingCapabilityBlockReason,
  type ProviderRecoveryLocale,
  type ProviderRecoveryScenario,
  type ProviderRecoverySummary,
};
