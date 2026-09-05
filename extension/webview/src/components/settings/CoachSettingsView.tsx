import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import {
  countSavedProviderProfiles,
  describeProviderCapabilityMatrixGroups,
  describeProviderDiagnosticVerdict,
  describeProviderProfileSummary,
  describeProviderProtocolSummary,
  describeProviderImageInputState,
  describeProviderSendState,
  describeProviderTestReadiness,
  hasSavedProviderProfiles,
  PROVIDER_TEST_FRESHNESS_WINDOW_MS,
  providerErrorHint,
  type ProviderImageInputState,
  type ProviderSendState,
  type ProviderSendStateStatus,
} from "../../../../../shared/src/providerStatus";
import {
  normalizeProviderProtocol,
  providerProtocolCompletionLabel,
  providerProtocolEndpointHint,
  SUPPORTED_PROVIDER_PROTOCOLS,
} from "../../../../../shared/src/providerProtocols";
import {
  providerModelTokenLimitsKey,
  readProviderModelTokenLimit,
  withProviderModelTokenLimit,
} from "../../../../../shared/src/providerModelTokenLimits";
import {
  evaluateProviderModelPolicy,
  filterProviderModelOptions,
} from "../../../../../shared/src/providerModelPolicy";
import type { ProviderModelTokenLimit, ProviderProtocol } from "../../../../../shared/src/models";
import { isNewApiConnectionType } from "../../../../../shared/src/providerGateway";
import { describeProviderThinking, updateProviderThinking } from "../../../../../shared/src/providerThinking";
import type { ProviderThinkingConfig } from "../../../../../shared/src/providerThinking";
import type { TrainerCapabilityVerdict } from "../../../../../shared/src/capabilityVerdict";
import {
  describeWorkspaceTrustState,
  normalizeWorkspaceTrustState,
  type WorkspaceTrustState,
} from "../../../../../shared/src/workspaceTrustState";
import {
  selectScopedSettingsLastTest,
  settingsCapabilityChipsVisible,
  settingsCapabilitySurfaceStatus,
  settingsProtocolIsKnown,
} from "../../../../../shared/src/settingsCapabilityGovernance";
import { sanitizeErrorSurfaceText } from "../../../../../shared/src/errorSurfaceSanitizer";

import { ActionButton } from "../common";
import { WorkspaceRootRecoveryPanel } from "./WorkspaceRootRecoveryPanel";
import { WorkspaceAuthoritySummary } from "../coach/parts/WorkspaceAuthoritySummary";
import { CollapseSection } from "../common/CollapseSection";
import { StatusPill } from "../StatusPill";
import { CheckMarkIcon, DiagnosticsIcon, FolderIcon, GearIcon, LightningIcon, RefreshIcon, TrashIcon } from "../icons";
import { LANGUAGE_LABELS, SUPPORTED_LANGUAGES } from "../../../../../shared/src";
import { resolveCopy as resolveWorkbenchCopy } from "../../lib/i18n/copy";
import type {
  CapabilityFlags,
  CoachAnswerMode,
  CoachDefaults,
  ComposerLanguage,
  LearningSurfaceAlignment,
  ManagedDataFolder,
  MemoryShareGrant,
  ProviderConfigView,
  TeachingStyle,
  ThemePreference,
  TrainerWorkspaceAdmission,
  WorkspaceMemoryToggles,
  WorkspaceAuthority,
} from "../../lib/types";

type AnswerMode = CoachAnswerMode;
type SaveState = "saved" | "unsaved" | "empty";
type AnswerStylePreset = "simple" | "balanced" | "deep" | "custom";
const DEFAULT_PROVIDER_CONNECTION_NAME = "custom-openai-compatible";
const MODEL_PICKER_RECENT_OPTION_LIMIT = 5;
const MODEL_PICKER_SEARCH_OPTION_LIMIT = 8;
const ANSWER_STYLE_STORAGE_KEY = "trainer.settings.answerStyle";
/** Flash highlight lifetime for status-bar jumps (ms). Skipped under reduced motion. */
const SETTINGS_SECTION_FLASH_MS = 600;

interface AnswerStyleValues {
  contextDetail: "focused" | "balanced" | "full";
  includeCurrentFile: boolean;
  includeSelection: boolean;
  includeDiagnostics: boolean;
  includeRelatedFiles: boolean;
}

const ANSWER_STYLE_PRESETS: Record<"simple" | "balanced" | "deep", AnswerStyleValues> = {
  simple: {
    contextDetail: "focused",
    includeCurrentFile: true,
    includeSelection: false,
    includeDiagnostics: false,
    includeRelatedFiles: false,
  },
  balanced: {
    contextDetail: "balanced",
    includeCurrentFile: true,
    includeSelection: true,
    includeDiagnostics: true,
    includeRelatedFiles: false,
  },
  deep: {
    contextDetail: "full",
    includeCurrentFile: true,
    includeSelection: true,
    includeDiagnostics: true,
    includeRelatedFiles: true,
  },
};

/**
 * Derive the visible answer-style preset from the five context knobs.
 * Load-time derivation covers every legacy field combination: an exact match
 * wins; the rare "everything off + focused" combination resolves to 简单;
 * everything else is 自定义. The five knob values always stay untouched.
 */
function deriveAnswerStylePreset(values: AnswerStyleValues): AnswerStylePreset {
  if (
    values.contextDetail === "focused" &&
    !values.includeSelection &&
    !values.includeDiagnostics &&
    !values.includeRelatedFiles
  ) {
    return "simple";
  }
  for (const preset of ["balanced", "deep"] as const) {
    const target = ANSWER_STYLE_PRESETS[preset];
    if (
      values.contextDetail === target.contextDetail &&
      values.includeCurrentFile === target.includeCurrentFile &&
      values.includeSelection === target.includeSelection &&
      values.includeDiagnostics === target.includeDiagnostics &&
      values.includeRelatedFiles === target.includeRelatedFiles
    ) {
      return preset;
    }
  }
  return "custom";
}

function readStoredAnswerStyle(): AnswerStylePreset | undefined {
  try {
    const stored = window.localStorage.getItem(ANSWER_STYLE_STORAGE_KEY);
    return stored === "simple" || stored === "balanced" || stored === "deep" || stored === "custom"
      ? stored
      : undefined;
  } catch {
    return undefined;
  }
}

function writeStoredAnswerStyle(preset: AnswerStylePreset): void {
  try {
    window.localStorage.setItem(ANSWER_STYLE_STORAGE_KEY, preset);
  } catch {
    // Best-effort persistence; derivation from knob values stays authoritative.
  }
}

function prefersReducedMotion(): boolean {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

function learningSurfaceAlignmentCopy(language: ComposerLanguage): {
  label: string;
  left: string;
  right: string;
} {
  switch (language) {
    case "zh-CN":
      return { label: "内容位置", left: "靠左", right: "靠右" };
    case "es-ES":
      return { label: "Posición del contenido", left: "Izquierda", right: "Derecha" };
    case "fr-FR":
      return { label: "Position du contenu", left: "À gauche", right: "À droite" };
    case "de-DE":
      return { label: "Inhaltsposition", left: "Links", right: "Rechts" };
    case "ja-JP":
      return { label: "コンテンツの位置", left: "左", right: "右" };
    case "ko-KR":
      return { label: "콘텐츠 위치", left: "왼쪽", right: "오른쪽" };
    case "pt-BR":
      return { label: "Posição do conteúdo", left: "Esquerda", right: "Direita" };
    default:
      return { label: "Content position", left: "Left", right: "Right" };
  }
}

interface ProviderProfileView {
  id: string;
  label: string;
  model: string;
  mode?: string;
  protocol?: string;
  baseUrl?: string;
  credentialMode?: string;
  availableModelCount: number;
  isActive: boolean;
  detail?: string;
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined;
}

function asString(value: unknown): string | undefined {
  if (typeof value !== "string") {
    return undefined;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
    : [];
}

function asNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function normalizeProviderBaseUrlDraft(value: string, protocol: ProviderProtocol | undefined): string {
  const trimmed = value.trim();
  if (!trimmed) {
    return "";
  }

  try {
    const parsed = new URL(trimmed);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return trimmed.replace(/\/+$/, "");
    }

    let path = parsed.pathname.replace(/\/+$/, "");
    const loweredPath = path.toLowerCase();
    if (
      protocol === "openai_responses" ||
      protocol === "openai_chat_completions" ||
      protocol === "openai_chat_completions_compatible"
    ) {
      for (const suffix of ["/chat/completions", "/responses"]) {
        if (loweredPath.endsWith(suffix)) {
          path = path.slice(0, -suffix.length) || "/";
          break;
        }
      }
    } else if (protocol === "anthropic_messages" && loweredPath.endsWith("/messages")) {
      path = path.slice(0, -"/messages".length) || "/";
    } else if (
      protocol === "gemini_generate_content" &&
      loweredPath.endsWith(":generatecontent")
    ) {
      const modelMarker = "/models/";
      const markerIndex = loweredPath.lastIndexOf(modelMarker);
      if (markerIndex >= 0) {
        path = path.slice(0, markerIndex) || "/";
      }
    }

    parsed.pathname = path || "/";
    return parsed.toString().replace(/\/$/, "");
  } catch {
    return trimmed.replace(/\/+$/, "");
  }
}

function providerConnectionNameLabel(language: ComposerLanguage): string {
  switch (language) {
    case "zh-CN":
      return "\u8fde\u63a5\u540d\u79f0\uff08\u53ef\u9009\uff09";
    case "es-ES":
      return "Nombre de conexion (opcional)";
    case "fr-FR":
      return "Nom de connexion (facultatif)";
    case "de-DE":
      return "Verbindungsname (optional)";
    case "ja-JP":
      return "\u63a5\u7d9a\u540d\uff08\u4efb\u610f\uff09";
    case "ko-KR":
      return "\uc5f0\uacb0 \uc774\ub984(\uc120\ud0dd)";
    case "pt-BR":
      return "Nome da conexao (opcional)";
    default:
      return "Connection name (optional)";
  }
}

type ProviderConnectionTruthCopy = {
  protocol: string;
  capabilities: string;
  diagnostics: string;
  profiles: string;
  modelHints: string;
  diagnosticNotes: string;
  warnings: string;
  blockedModels: string;
  blockedTaskBindings: string;
  saveFirst: string;
  draftNotTested: string;
  saveFirstStatus: string;
  needsLiveTest: string;
  protocolDraftDetail: (
    draftProtocol: string,
    draftEndpoint: string,
    liveProtocol: string,
    liveEndpoint: string,
  ) => string;
  diagnosticsDraftDetail: string;
  diagnosticsNeedsTest: string;
  capabilityDraftDetail: (protocol: string) => string;
  capabilityLiveDetail: (modelCount: number) => string;
  capabilityNeverTested: string;
  capabilityTestFailed: string;
  capabilityUnknownProtocol: string;
  profileDetail: (profileCount: number) => string;
};

function providerConnectionTruthCopy(language: ComposerLanguage): ProviderConnectionTruthCopy {
  const copy: Record<ComposerLanguage, ProviderConnectionTruthCopy> = {
    "zh-CN": {
      protocol: "连接方式",
      capabilities: "可用能力",
      diagnostics: "连接检查",
      profiles: "已保存连接",
      modelHints: "模型能力提示",
      diagnosticNotes: "最近检查结果",
      warnings: "注意事项",
      blockedModels: "不可用模型",
      blockedTaskBindings: "不可用任务设置",
      saveFirst: "先保存连接，才能查看当前连接的检查结果。",
      draftNotTested: "草稿待测试",
      saveFirstStatus: "先保存",
      needsLiveTest: "需要测试",
      protocolDraftDetail: (draftProtocol, draftEndpoint, liveProtocol, liveEndpoint) =>
        `保存后会改用 ${draftProtocol} · ${draftEndpoint}。当前连接仍在使用 ${liveProtocol} · ${liveEndpoint}。`,
      diagnosticsDraftDetail: "这张检查卡仍在描述当前连接。先保存改动，再重新测试。",
      diagnosticsNeedsTest: "连接已保存，但还没有最近一次测试结果。",
      capabilityDraftDetail: (protocol) =>
        `先保存 ${protocol} 连接，再做一次现场测试。能力只来自那次测试。`,
      capabilityLiveDetail: (modelCount) =>
        modelCount > 0
          ? `已找到 ${modelCount} 个可选模型。能力芯片只显示最近一次测试观察到的结果。`
          : "能力芯片只显示最近一次测试观察到的结果。",
      capabilityNeverTested: "还没有现场测试。这里不显示协议默认能力。",
      capabilityTestFailed: "最近一次测试失败。已清除上次的能力芯片。",
      capabilityUnknownProtocol: "未知连接方式。在测试确认之前，不会假设任何能力。",
      profileDetail: (profileCount) =>
        profileCount > 0 ? `已保存 ${profileCount} 组连接，可随时切换。` : "还没有保存过连接。",
    },
    "en-US": {
      protocol: "Protocol",
      capabilities: "Capabilities",
      diagnostics: "Connection check",
      profiles: "Saved connections",
      modelHints: "Model capability hints",
      diagnosticNotes: "Recent checks",
      warnings: "Warnings",
      blockedModels: "Unavailable models",
      blockedTaskBindings: "Unavailable task settings",
      saveFirst: "Save the connection before relying on its check results.",
      draftNotTested: "Draft not tested",
      saveFirstStatus: "Save first",
      needsLiveTest: "Needs test",
      protocolDraftDetail: (draftProtocol, draftEndpoint, liveProtocol, liveEndpoint) =>
        `After saving, this connection will use ${draftProtocol} · ${draftEndpoint}. It currently uses ${liveProtocol} · ${liveEndpoint}.`,
      diagnosticsDraftDetail: "This check still describes the current connection. Save the changes, then test again.",
      diagnosticsNeedsTest: "The connection is saved, but it has not been tested recently.",
      capabilityDraftDetail: (protocol) =>
        `Save the ${protocol} connection, then run a live test. Chips come only from that test.`,
      capabilityLiveDetail: (modelCount) =>
        modelCount > 0
          ? `${modelCount} models are available. Capability chips show only the latest live observation.`
          : "Capability chips show only the latest live observation.",
      capabilityNeverTested: "No live test yet. Protocol defaults are not shown as capabilities.",
      capabilityTestFailed: "The latest test failed. Previous capability chips were cleared.",
      capabilityUnknownProtocol: "Unknown connection type. No capabilities are assumed until a live test.",
      profileDetail: (profileCount) =>
        profileCount > 0
          ? `${profileCount} saved connections are available to switch between.`
          : "No connections have been saved yet.",
    },
    "es-ES": {
      protocol: "Protocolo",
      capabilities: "Capacidades",
      diagnostics: "Comprobación de conexión",
      profiles: "Conexiones guardadas",
      modelHints: "Notas sobre capacidades del modelo",
      diagnosticNotes: "Comprobaciones recientes",
      warnings: "Avisos",
      blockedModels: "Modelos no disponibles",
      blockedTaskBindings: "Ajustes de tarea no disponibles",
      saveFirst: "Guarda la conexión antes de confiar en sus resultados de comprobación.",
      draftNotTested: "Borrador sin probar",
      saveFirstStatus: "Guardar primero",
      needsLiveTest: "Necesita prueba",
      protocolDraftDetail: (draftProtocol, draftEndpoint, liveProtocol, liveEndpoint) =>
        `Al guardar, esta conexión usará ${draftProtocol} · ${draftEndpoint}. Ahora usa ${liveProtocol} · ${liveEndpoint}.`,
      diagnosticsDraftDetail: "Esta comprobación todavía describe la conexión actual. Guarda los cambios y vuelve a probar.",
      diagnosticsNeedsTest: "La conexión está guardada, pero no se ha probado recientemente.",
      capabilityDraftDetail: (protocol) =>
        `Guarda la conexión ${protocol} y haz una prueba en vivo. Los chips solo salen de esa prueba.`,
      capabilityLiveDetail: (modelCount) =>
        modelCount > 0
          ? `Hay ${modelCount} modelos. Los chips muestran solo la última observación en vivo.`
          : "Los chips muestran solo la última observación en vivo.",
      capabilityNeverTested: "Aún no hay prueba en vivo. No se muestran capacidades por defecto del protocolo.",
      capabilityTestFailed: "La última prueba falló. Se quitaron los chips anteriores.",
      capabilityUnknownProtocol: "Tipo de conexión desconocido. No se asumen capacidades hasta una prueba en vivo.",
      profileDetail: (profileCount) =>
        profileCount > 0
          ? `Hay ${profileCount} conexiones guardadas para cambiar entre ellas.`
          : "Aún no hay conexiones guardadas.",
    },
    "fr-FR": {
      protocol: "Protocole",
      capabilities: "Fonctionnalités",
      diagnostics: "Vérification de connexion",
      profiles: "Connexions enregistrées",
      modelHints: "Repères sur les capacités du modèle",
      diagnosticNotes: "Vérifications récentes",
      warnings: "Avertissements",
      blockedModels: "Modèles indisponibles",
      blockedTaskBindings: "Réglages de tâche indisponibles",
      saveFirst: "Enregistrez la connexion avant de vous fier à ses résultats de vérification.",
      draftNotTested: "Brouillon non testé",
      saveFirstStatus: "Enregistrer d'abord",
      needsLiveTest: "Test requis",
      protocolDraftDetail: (draftProtocol, draftEndpoint, liveProtocol, liveEndpoint) =>
        `Après enregistrement, cette connexion utilisera ${draftProtocol} · ${draftEndpoint}. Elle utilise actuellement ${liveProtocol} · ${liveEndpoint}.`,
      diagnosticsDraftDetail: "Cette vérification décrit encore la connexion actuelle. Enregistrez les modifications, puis testez à nouveau.",
      diagnosticsNeedsTest: "La connexion est enregistrée, mais elle n'a pas été testée récemment.",
      capabilityDraftDetail: (protocol) =>
        `Enregistrez la connexion ${protocol}, puis lancez un test réel. Les pastilles viennent uniquement de ce test.`,
      capabilityLiveDetail: (modelCount) =>
        modelCount > 0
          ? `${modelCount} modèles sont disponibles. Les pastilles montrent seulement la dernière observation réelle.`
          : "Les pastilles montrent seulement la dernière observation réelle.",
      capabilityNeverTested: "Pas encore de test réel. Les capacités par défaut du protocole ne sont pas affichées.",
      capabilityTestFailed: "Le dernier test a échoué. Les pastilles précédentes ont été effacées.",
      capabilityUnknownProtocol: "Type de connexion inconnu. Aucune capacité n'est supposée avant un test réel.",
      profileDetail: (profileCount) =>
        profileCount > 0
          ? `${profileCount} connexions enregistrées sont disponibles.`
          : "Aucune connexion n'est encore enregistrée.",
    },
    "de-DE": {
      protocol: "Protokoll",
      capabilities: "Funktionen",
      diagnostics: "Verbindungsprüfung",
      profiles: "Gespeicherte Verbindungen",
      modelHints: "Hinweise zu Modellfunktionen",
      diagnosticNotes: "Letzte Prüfungen",
      warnings: "Hinweise",
      blockedModels: "Nicht verfügbare Modelle",
      blockedTaskBindings: "Nicht verfügbare Aufgaben-Einstellungen",
      saveFirst: "Speichern Sie die Verbindung, bevor Sie sich auf Prüfergebnisse verlassen.",
      draftNotTested: "Entwurf nicht getestet",
      saveFirstStatus: "Zuerst speichern",
      needsLiveTest: "Test erforderlich",
      protocolDraftDetail: (draftProtocol, draftEndpoint, liveProtocol, liveEndpoint) =>
        `Nach dem Speichern verwendet diese Verbindung ${draftProtocol} · ${draftEndpoint}. Aktuell verwendet sie ${liveProtocol} · ${liveEndpoint}.`,
      diagnosticsDraftDetail: "Diese Prüfung beschreibt noch die aktuelle Verbindung. Änderungen speichern und erneut testen.",
      diagnosticsNeedsTest: "Die Verbindung ist gespeichert, wurde aber noch nicht kürzlich getestet.",
      capabilityDraftDetail: (protocol) =>
        `Speichern Sie die ${protocol}-Verbindung und führen Sie einen Live-Test aus. Chips kommen nur aus diesem Test.`,
      capabilityLiveDetail: (modelCount) =>
        modelCount > 0
          ? `${modelCount} Modelle sind verfügbar. Chips zeigen nur die letzte Live-Beobachtung.`
          : "Chips zeigen nur die letzte Live-Beobachtung.",
      capabilityNeverTested: "Noch kein Live-Test. Protokoll-Standardfähigkeiten werden nicht angezeigt.",
      capabilityTestFailed: "Der letzte Test ist fehlgeschlagen. Vorherige Chips wurden entfernt.",
      capabilityUnknownProtocol: "Unbekannter Verbindungstyp. Vor einem Live-Test werden keine Fähigkeiten angenommen.",
      profileDetail: (profileCount) =>
        profileCount > 0
          ? `${profileCount} gespeicherte Verbindungen stehen zum Wechseln bereit.`
          : "Es wurden noch keine Verbindungen gespeichert.",
    },
    "ja-JP": {
      protocol: "プロトコル",
      capabilities: "利用できる機能",
      diagnostics: "接続チェック",
      profiles: "保存済みの接続",
      modelHints: "モデル機能のメモ",
      diagnosticNotes: "最近の確認結果",
      warnings: "注意事項",
      blockedModels: "使えないモデル",
      blockedTaskBindings: "使えないタスク設定",
      saveFirst: "接続の確認結果を見る前に、まず保存してください。",
      draftNotTested: "下書きは未テスト",
      saveFirstStatus: "先に保存",
      needsLiveTest: "テストが必要",
      protocolDraftDetail: (draftProtocol, draftEndpoint, liveProtocol, liveEndpoint) =>
        `保存すると ${draftProtocol} · ${draftEndpoint} に切り替わります。現在は ${liveProtocol} · ${liveEndpoint} を使用しています。`,
      diagnosticsDraftDetail: "この確認結果は現在の接続についてのものです。変更を保存してから、もう一度テストしてください。",
      diagnosticsNeedsTest: "接続は保存されていますが、最近のテスト結果がありません。",
      capabilityDraftDetail: (protocol) =>
        `${protocol} の接続を保存してからライブテストしてください。チップはそのテストだけから出ます。`,
      capabilityLiveDetail: (modelCount) =>
        modelCount > 0
          ? `この接続で ${modelCount} 個のモデルを選べます。チップは最新のライブ観測だけを示します。`
          : "チップは最新のライブ観測だけを示します。",
      capabilityNeverTested: "まだライブテストがありません。プロトコルの既定機能は表示しません。",
      capabilityTestFailed: "最新のテストは失敗しました。以前のチップは消しました。",
      capabilityUnknownProtocol: "未知の接続方式です。ライブテストまで能力は仮定しません。",
      profileDetail: (profileCount) =>
        profileCount > 0
          ? `${profileCount} 件の保存済み接続を切り替えられます。`
          : "保存済みの接続はまだありません。",
    },
    "ko-KR": {
      protocol: "프로토콜",
      capabilities: "사용 가능한 기능",
      diagnostics: "연결 확인",
      profiles: "저장된 연결",
      modelHints: "모델 기능 참고",
      diagnosticNotes: "최근 확인 결과",
      warnings: "주의 사항",
      blockedModels: "사용할 수 없는 모델",
      blockedTaskBindings: "사용할 수 없는 작업 설정",
      saveFirst: "확인 결과를 보기 전에 먼저 연결을 저장하세요.",
      draftNotTested: "초안 미테스트",
      saveFirstStatus: "먼저 저장",
      needsLiveTest: "테스트 필요",
      protocolDraftDetail: (draftProtocol, draftEndpoint, liveProtocol, liveEndpoint) =>
        `저장하면 ${draftProtocol} · ${draftEndpoint}로 바뀝니다. 현재는 ${liveProtocol} · ${liveEndpoint}를 사용합니다.`,
      diagnosticsDraftDetail: "이 확인 결과는 현재 연결에 대한 것입니다. 변경 사항을 저장한 뒤 다시 테스트하세요.",
      diagnosticsNeedsTest: "연결은 저장되어 있지만 최근 테스트 결과가 없습니다.",
      capabilityDraftDetail: (protocol) =>
        `${protocol} 연결을 저장한 뒤 실제 테스트를 하세요. 칩은 그 테스트에서만 나옵니다.`,
      capabilityLiveDetail: (modelCount) =>
        modelCount > 0
          ? `이 연결에서 ${modelCount}개의 모델을 선택할 수 있습니다. 칩은 최근 실제 관찰만 보여 줍니다.`
          : "칩은 최근 실제 관찰만 보여 줍니다.",
      capabilityNeverTested: "아직 실제 테스트가 없습니다. 프로토콜 기본 기능은 표시하지 않습니다.",
      capabilityTestFailed: "최근 테스트가 실패했습니다. 이전 칩을 지웠습니다.",
      capabilityUnknownProtocol: "알 수 없는 연결 유형입니다. 실제 테스트 전까지 기능을 가정하지 않습니다.",
      profileDetail: (profileCount) =>
        profileCount > 0
          ? `${profileCount}개의 저장된 연결을 전환할 수 있습니다.`
          : "저장된 연결이 아직 없습니다.",
    },
    "pt-BR": {
      protocol: "Protocolo",
      capabilities: "Recursos disponíveis",
      diagnostics: "Verificação da conexão",
      profiles: "Conexões salvas",
      modelHints: "Notas sobre recursos do modelo",
      diagnosticNotes: "Verificações recentes",
      warnings: "Avisos",
      blockedModels: "Modelos indisponíveis",
      blockedTaskBindings: "Configurações de tarefa indisponíveis",
      saveFirst: "Salve a conexão antes de confiar nos resultados da verificação.",
      draftNotTested: "Rascunho não testado",
      saveFirstStatus: "Salvar primeiro",
      needsLiveTest: "Teste necessário",
      protocolDraftDetail: (draftProtocol, draftEndpoint, liveProtocol, liveEndpoint) =>
        `Depois de salvar, esta conexão usará ${draftProtocol} · ${draftEndpoint}. Agora ela usa ${liveProtocol} · ${liveEndpoint}.`,
      diagnosticsDraftDetail: "Esta verificação ainda descreve a conexão atual. Salve as alterações e teste novamente.",
      diagnosticsNeedsTest: "A conexão está salva, mas não foi testada recentemente.",
      capabilityDraftDetail: (protocol) =>
        `Salve a conexão ${protocol} e faça um teste ao vivo. Os chips vêm só desse teste.`,
      capabilityLiveDetail: (modelCount) =>
        modelCount > 0
          ? `${modelCount} modelos estão disponíveis. Os chips mostram só a última observação ao vivo.`
          : "Os chips mostram só a última observação ao vivo.",
      capabilityNeverTested: "Ainda não há teste ao vivo. Os recursos padrão do protocolo não são mostrados.",
      capabilityTestFailed: "O último teste falhou. Os chips anteriores foram removidos.",
      capabilityUnknownProtocol: "Tipo de conexão desconhecido. Nenhuma capacidade é assumida até um teste ao vivo.",
      profileDetail: (profileCount) =>
        profileCount > 0
          ? `${profileCount} conexões salvas estão disponíveis para alternar.`
          : "Ainda não há conexões salvas.",
    },
  };

  return copy[language] ?? copy["en-US"];
}

type ProviderDetailLabelKey =
  | "baseUrl"
  | "savedProfiles"
  | "savedProfilesAvailable"
  | "savedProfilesEmpty"
  | "refreshProfiles"
  | "reloadProfiles"
  | "saveProfile"
  | "saveProfileDetail"
  | "perModelLimits"
  | "modelCatalog";

function providerDetailLabel(language: ComposerLanguage, key: ProviderDetailLabelKey): string {
  const copy: Record<ComposerLanguage, Record<ProviderDetailLabelKey, string>> = {
    "zh-CN": {
      baseUrl: "服务根地址",
      savedProfiles: "已保存连接",
      savedProfilesAvailable: "下方可以直接启用已保存的连接。",
      savedProfilesEmpty: "先保存一组连接。",
      refreshProfiles: "刷新已保存连接",
      reloadProfiles: "重新加载连接列表",
      saveProfile: "另存为连接",
      saveProfileDetail: "把当前填写内容保存成可切换的连接",
      perModelLimits: "每个模型的限制",
      modelCatalog: "模型目录",
    },
    "en-US": {
      baseUrl: "Service root",
      savedProfiles: "Saved connections",
      savedProfilesAvailable: "Saved connections are available below.",
      savedProfilesEmpty: "Save a connection first.",
      refreshProfiles: "Refresh saved connections",
      reloadProfiles: "Reload connection list",
      saveProfile: "Save as connection",
      saveProfileDetail: "Save the current entries as a reusable connection",
      perModelLimits: "Limits by model",
      modelCatalog: "Model catalog",
    },
    "es-ES": {
      baseUrl: "Raíz del servicio",
      savedProfiles: "Conexiones guardadas",
      savedProfilesAvailable: "Las conexiones guardadas están disponibles abajo.",
      savedProfilesEmpty: "Guarda primero una conexión.",
      refreshProfiles: "Actualizar conexiones guardadas",
      reloadProfiles: "Recargar lista de conexiones",
      saveProfile: "Guardar como conexión",
      saveProfileDetail: "Guardar los datos actuales como una conexión reutilizable",
      perModelLimits: "Límites por modelo",
      modelCatalog: "Catálogo de modelos",
    },
    "fr-FR": {
      baseUrl: "Racine du service",
      savedProfiles: "Connexions enregistrées",
      savedProfilesAvailable: "Les connexions enregistrées sont disponibles ci-dessous.",
      savedProfilesEmpty: "Enregistrez d'abord une connexion.",
      refreshProfiles: "Actualiser les connexions enregistrées",
      reloadProfiles: "Recharger la liste des connexions",
      saveProfile: "Enregistrer comme connexion",
      saveProfileDetail: "Enregistrer les valeurs actuelles comme connexion réutilisable",
      perModelLimits: "Limites par modèle",
      modelCatalog: "Catalogue de modèles",
    },
    "de-DE": {
      baseUrl: "Service-Stammadresse",
      savedProfiles: "Gespeicherte Verbindungen",
      savedProfilesAvailable: "Gespeicherte Verbindungen stehen unten bereit.",
      savedProfilesEmpty: "Speichern Sie zuerst eine Verbindung.",
      refreshProfiles: "Gespeicherte Verbindungen aktualisieren",
      reloadProfiles: "Verbindungsliste neu laden",
      saveProfile: "Als Verbindung speichern",
      saveProfileDetail: "Aktuelle Eingaben als wiederverwendbare Verbindung speichern",
      perModelLimits: "Grenzen je Modell",
      modelCatalog: "Modellkatalog",
    },
    "ja-JP": {
      baseUrl: "サービスのルート URL",
      savedProfiles: "保存済みの接続",
      savedProfilesAvailable: "保存済みの接続は下で使えます。",
      savedProfilesEmpty: "先に接続を保存してください。",
      refreshProfiles: "保存済みの接続を更新",
      reloadProfiles: "接続一覧を再読み込み",
      saveProfile: "接続として保存",
      saveProfileDetail: "現在の入力を切り替え用の接続として保存",
      perModelLimits: "モデルごとの上限",
      modelCatalog: "モデル一覧",
    },
    "ko-KR": {
      baseUrl: "서비스 루트 주소",
      savedProfiles: "저장된 연결",
      savedProfilesAvailable: "저장된 연결을 아래에서 사용할 수 있습니다.",
      savedProfilesEmpty: "먼저 연결을 저장하세요.",
      refreshProfiles: "저장된 연결 새로 고침",
      reloadProfiles: "연결 목록 다시 불러오기",
      saveProfile: "연결로 저장",
      saveProfileDetail: "현재 입력을 전환할 수 있는 연결로 저장",
      perModelLimits: "모델별 한도",
      modelCatalog: "모델 목록",
    },
    "pt-BR": {
      baseUrl: "Raiz do serviço",
      savedProfiles: "Conexões salvas",
      savedProfilesAvailable: "As conexões salvas estão disponíveis abaixo.",
      savedProfilesEmpty: "Salve uma conexão primeiro.",
      refreshProfiles: "Atualizar conexões salvas",
      reloadProfiles: "Recarregar lista de conexões",
      saveProfile: "Salvar como conexão",
      saveProfileDetail: "Salvar os dados atuais como uma conexão reutilizável",
      perModelLimits: "Limites por modelo",
      modelCatalog: "Catálogo de modelos",
    },
  };

  return copy[language]?.[key] ?? copy["en-US"][key];
}

function providerBaseUrlGuidance(
  language: ComposerLanguage,
  protocol: ProviderProtocol | undefined,
  endpointHint: string,
): string {
  if (!protocol) {
    return language === "zh-CN"
      ? "先选择协议，再填写服务根地址。未知网关不会被默认成 OpenAI 兼容。"
      : "Select a protocol before entering the service root. Unknown gateways are not assumed OpenAI-compatible.";
  }
  if (protocol === "gemini_generate_content") {
    switch (language) {
      case "zh-CN":
        return "填写 API 根地址，不要粘贴某个模型专用的 generateContent 请求地址。";
      case "es-ES":
        return "Introduce la raíz de la API, no una URL generateContent específica de un modelo.";
      case "fr-FR":
        return "Saisissez la racine de l'API, pas une URL generateContent propre à un modèle.";
      case "de-DE":
        return "Geben Sie die API-Stammadresse ein, nicht eine modellspezifische generateContent-URL.";
      case "ja-JP":
        return "モデル専用の generateContent URL ではなく、API のルート URL を入力してください。";
      case "ko-KR":
        return "모델별 generateContent URL이 아니라 API 루트 주소를 입력하세요.";
      case "pt-BR":
        return "Informe a raiz da API, não uma URL generateContent específica de um modelo.";
      default:
        return "Enter the API root, not a model-specific generateContent request URL.";
    }
  }

  switch (language) {
    case "zh-CN":
      return `填写服务根地址，不要包含 ${endpointHint}。Trainer 会自动补全请求路径。`;
    case "es-ES":
      return `Introduce la raíz del servicio. No incluyas ${endpointHint}; Trainer añade la ruta de la solicitud.`;
    case "fr-FR":
      return `Saisissez la racine du service. N'incluez pas ${endpointHint} : Trainer ajoute le chemin de la requête.`;
    case "de-DE":
      return `Geben Sie die Service-Stammadresse ein. ${endpointHint} nicht einschließen; Trainer ergänzt den Anfragepfad.`;
    case "ja-JP":
      return `サービスのルート URL を入力してください。${endpointHint} は含めません。Trainer がリクエストのパスを追加します。`;
    case "ko-KR":
      return `서비스 루트 주소를 입력하세요. ${endpointHint}는 포함하지 마세요. Trainer가 요청 경로를 추가합니다.`;
    case "pt-BR":
      return `Informe a raiz do serviço. Não inclua ${endpointHint}; o Trainer adiciona o caminho da solicitação.`;
    default:
      return `Enter the service root. Do not include ${endpointHint}; Trainer adds the request path.`;
  }
}

function providerModelDiscoveryCopy(language: ComposerLanguage): {
  findModels: string;
  findModelsDetail: string;
  missingBaseUrl: string;
  missingApiKey: string;
  modelOptional: string;
  manualFallback: string;
} {
  const copy: Record<ComposerLanguage, ReturnType<typeof providerModelDiscoveryCopy>> = {
    "zh-CN": {
      findModels: "\u67e5\u627e\u6a21\u578b",
      findModelsDetail: "\u4f7f\u7528\u5f53\u524d\u5730\u5740\u548c\u5bc6\u94a5",
      missingBaseUrl: "\u5148\u586b\u5199\u670d\u52a1\u6839\u5730\u5740\uff0c\u518d\u67e5\u627e\u6a21\u578b\u3002",
      missingApiKey: "\u5148\u586b\u5199 API key\uff0c\u518d\u67e5\u627e\u6a21\u578b\u3002",
      modelOptional: "\u4e0d\u77e5\u9053\u6a21\u578b\u540d\u6ca1\u5173\u7cfb\uff0c\u5148\u67e5\u627e\u3002",
      manualFallback: "\u6ca1\u6709\u627e\u5230\u6a21\u578b\u65f6\uff0c\u518d\u624b\u52a8\u586b\u5199\u540d\u79f0\u3002",
    },
    "en-US": {
      findModels: "Find models",
      findModelsDetail: "Use the current address and key",
      missingBaseUrl: "Add the service root before finding models.",
      missingApiKey: "Add an API key before finding models.",
      modelOptional: "Do not know the model name? Find it first.",
      manualFallback: "Only enter a model name manually if no models are found.",
    },
    "es-ES": {
      findModels: "Buscar modelos",
      findModelsDetail: "Usa la dirección y la clave actuales",
      missingBaseUrl: "Añade la dirección del servicio antes de buscar modelos.",
      missingApiKey: "Añade una clave API antes de buscar modelos.",
      modelOptional: "¿No sabes el nombre del modelo? Búscalo primero.",
      manualFallback: "Escribe el nombre manualmente solo si no se encuentra ningún modelo.",
    },
    "fr-FR": {
      findModels: "Rechercher des modèles",
      findModelsDetail: "Utilisez l’adresse et la clé actuelles",
      missingBaseUrl: "Ajoutez l’adresse du service avant de rechercher des modèles.",
      missingApiKey: "Ajoutez une clé API avant de rechercher des modèles.",
      modelOptional: "Vous ne connaissez pas le nom du modèle ? Recherchez-le d’abord.",
      manualFallback: "Saisissez le nom manuellement seulement si aucun modele n'est trouve.",
    },
    "de-DE": {
      findModels: "Modelle suchen",
      findModelsDetail: "Aktuelle Adresse und Schlüssel verwenden",
      missingBaseUrl: "Füge erst die Dienstadresse hinzu und suche dann Modelle.",
      missingApiKey: "Füge erst einen API-Schlüssel hinzu und suche dann Modelle.",
      modelOptional: "Modellname unbekannt? Suche ihn zuerst.",
      manualFallback: "Gib den Modellnamen nur manuell ein, wenn keine Modelle gefunden werden.",
    },
    "ja-JP": {
      findModels: "モデルを探す",
      findModelsDetail: "現在のアドレスとキーを使います",
      missingBaseUrl: "先にサービスのアドレスを入力してからモデルを探してください。",
      missingApiKey: "先に API キーを入力してからモデルを探してください。",
      modelOptional: "モデル名が分からない場合は、先に探してください。",
      manualFallback: "モデルが見つからない場合だけ、名前を手入力してください。",
    },
    "ko-KR": {
      findModels: "모델 찾기",
      findModelsDetail: "현재 주소와 키를 사용합니다",
      missingBaseUrl: "서비스 주소를 입력한 뒤 모델을 찾으세요.",
      missingApiKey: "API 키를 입력한 뒤 모델을 찾으세요.",
      modelOptional: "모델 이름을 모르면 먼저 찾아보세요.",
      manualFallback: "모델을 찾지 못한 경우에만 이름을 직접 입력하세요.",
    },
    "pt-BR": {
      findModels: "Encontrar modelos",
      findModelsDetail: "Use o endereço e a chave atuais",
      missingBaseUrl: "Adicione o endereço do serviço antes de procurar modelos.",
      missingApiKey: "Adicione uma chave de API antes de procurar modelos.",
      modelOptional: "Não sabe o nome do modelo? Procure primeiro.",
      manualFallback: "Digite o nome manualmente somente se nenhum modelo for encontrado.",
    },
  };

  return copy[language] ?? copy["en-US"];
}

function providerModelPickerCopy(language: ComposerLanguage): {
  filterPlaceholder: string;
  filterLabel: string;
  noMatches: string;
  refreshListDetail: string;
  enterModelName: string;
  useTypedModel: (model: string) => string;
  moreMatchesHint: (count: number) => string;
  saveAndUse: (model: string) => string;
} {
  const copy: Record<ComposerLanguage, ReturnType<typeof providerModelPickerCopy>> = {
    "zh-CN": {
      filterPlaceholder: "输入模型名称筛选",
      filterLabel: "筛选模型",
      noMatches: "没有匹配的模型",
      refreshListDetail: "更新列表",
      enterModelName: "输入完整模型名",
      useTypedModel: (model) => `使用 ${model}`,
      moreMatchesHint: (count) => `还有 ${count} 个匹配项，请继续输入。`,
      saveAndUse: (model) => `保存并使用 ${model}`,
    },
    "en-US": {
      filterPlaceholder: "Filter by model name",
      filterLabel: "Filter models",
      noMatches: "No matching models",
      refreshListDetail: "Refresh list",
      enterModelName: "Enter a full model name",
      useTypedModel: (model) => `Use ${model}`,
      moreMatchesHint: (count) => `${count} more matches. Keep typing to narrow them down.`,
      saveAndUse: (model) => `Save and use ${model}`,
    },
    "es-ES": {
      filterPlaceholder: "Filtrar por nombre de modelo",
      filterLabel: "Filtrar modelos",
      noMatches: "No hay modelos coincidentes",
      refreshListDetail: "Actualizar lista",
      enterModelName: "Escribir el nombre completo del modelo",
      useTypedModel: (model) => `Usar ${model}`,
      moreMatchesHint: (count) => `${count} coincidencias mas. Sigue escribiendo para acotar.`,
      saveAndUse: (model) => `Guardar y usar ${model}`,
    },
    "fr-FR": {
      filterPlaceholder: "Filtrer par nom de modele",
      filterLabel: "Filtrer les modeles",
      noMatches: "Aucun modele correspondant",
      refreshListDetail: "Actualiser la liste",
      enterModelName: "Saisir le nom complet du modele",
      useTypedModel: (model) => `Utiliser ${model}`,
      moreMatchesHint: (count) => `${count} resultats supplementaires. Continuez a saisir le nom.`,
      saveAndUse: (model) => `Enregistrer et utiliser ${model}`,
    },
    "de-DE": {
      filterPlaceholder: "Nach Modellnamen filtern",
      filterLabel: "Modelle filtern",
      noMatches: "Keine passenden Modelle",
      refreshListDetail: "Liste aktualisieren",
      enterModelName: "Vollstandigen Modellnamen eingeben",
      useTypedModel: (model) => `${model} verwenden`,
      moreMatchesHint: (count) => `${count} weitere Treffer. Tippe weiter zum Eingrenzen.`,
      saveAndUse: (model) => `${model} speichern und verwenden`,
    },
    "ja-JP": {
      filterPlaceholder: "モデル名で絞り込む",
      filterLabel: "モデルを絞り込む",
      noMatches: "一致するモデルはありません",
      refreshListDetail: "一覧を更新",
      enterModelName: "モデル名を直接入力",
      useTypedModel: (model) => `${model} を使用`,
      moreMatchesHint: (count) => `他に ${count} 件あります。さらに入力して絞り込んでください。`,
      saveAndUse: (model) => `${model} を保存して使用`,
    },
    "ko-KR": {
      filterPlaceholder: "모델 이름으로 검색",
      filterLabel: "모델 검색",
      noMatches: "일치하는 모델이 없습니다",
      refreshListDetail: "목록 새로 고침",
      enterModelName: "전체 모델 이름 입력",
      useTypedModel: (model) => `${model} 사용`,
      moreMatchesHint: (count) => `${count}개 결과가 더 있습니다. 더 입력해 좁혀 보세요.`,
      saveAndUse: (model) => `${model} 저장 후 사용`,
    },
    "pt-BR": {
      filterPlaceholder: "Filtrar por nome do modelo",
      filterLabel: "Filtrar modelos",
      noMatches: "Nenhum modelo encontrado",
      refreshListDetail: "Atualizar lista",
      enterModelName: "Digite o nome completo do modelo",
      useTypedModel: (model) => `Usar ${model}`,
      moreMatchesHint: (count) => `Ha mais ${count} resultados. Continue digitando para filtrar.`,
      saveAndUse: (model) => `Salvar e usar ${model}`,
    },
  };

  return copy[language] ?? copy["en-US"];
}

function modelPolicyHint(
  language: ComposerLanguage,
  reason: "denied" | "not_allowed",
): string {
  const denied = reason === "denied";
  switch (language) {
    case "zh-CN":
      return denied
        ? "\u8fd9\u4e2a\u8fde\u63a5\u5df2\u505c\u7528\u8be5\u6a21\u578b\uff0c\u8bf7\u4ece\u5217\u8868\u91cc\u91cd\u65b0\u9009\u4e00\u4e2a\u3002"
        : "\u8be5\u6a21\u578b\u4e0d\u5728\u8fd9\u4e2a\u8fde\u63a5\u7684\u53ef\u7528\u8303\u56f4\u5185\uff0c\u8bf7\u4ece\u5217\u8868\u91cc\u91cd\u65b0\u9009\u4e00\u4e2a\u3002";
    case "es-ES":
      return denied
        ? "Este modelo esta desactivado para esta conexion. Elige uno de la lista."
        : "Este modelo no esta en la lista permitida de esta conexion. Elige uno de la lista.";
    case "fr-FR":
      return denied
        ? "Ce modele est desactive pour cette connexion. Choisissez-en un dans la liste."
        : "Ce modele ne fait pas partie de la liste autorisee pour cette connexion. Choisissez-en un dans la liste.";
    case "de-DE":
      return denied
        ? "Dieses Modell ist fuer diese Verbindung deaktiviert. Waehle eines aus der Liste."
        : "Dieses Modell ist fuer diese Verbindung nicht freigegeben. Waehle eines aus der Liste.";
    case "ja-JP":
      return denied
        ? "\u3053\u306e\u63a5\u7d9a\u3067\u306f\u3053\u306e\u30e2\u30c7\u30eb\u306f\u4f7f\u3048\u307e\u305b\u3093\u3002\u4e00\u89a7\u304b\u3089\u9078\u3073\u76f4\u3057\u3066\u304f\u3060\u3055\u3044\u3002"
        : "\u3053\u306e\u30e2\u30c7\u30eb\u306f\u3053\u306e\u63a5\u7d9a\u306e\u4f7f\u7528\u7bc4\u56f2\u306b\u542b\u307e\u308c\u3066\u3044\u307e\u305b\u3093\u3002\u4e00\u89a7\u304b\u3089\u9078\u3073\u76f4\u3057\u3066\u304f\u3060\u3055\u3044\u3002";
    case "ko-KR":
      return denied
        ? "\uc774 \uc5f0\uacb0\uc5d0\uc11c\ub294 \uc774 \ubaa8\ub378\uc744 \uc0ac\uc6a9\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4. \ubaa9\ub85d\uc5d0\uc11c \ub2e4\uc2dc \uc120\ud0dd\ud558\uc138\uc694."
        : "\uc774 \ubaa8\ub378\uc740 \uc774 \uc5f0\uacb0\uc758 \uc0ac\uc6a9 \ubc94\uc704\uc5d0 \ud3ec\ud568\ub418\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4. \ubaa9\ub85d\uc5d0\uc11c \ub2e4\uc2dc \uc120\ud0dd\ud558\uc138\uc694.";
    case "pt-BR":
      return denied
        ? "Este modelo esta desativado para esta conexao. Escolha um da lista."
        : "Este modelo nao esta na lista permitida desta conexao. Escolha um da lista.";
    default:
      return denied
        ? "This connection has turned off that model. Choose one from the list."
        : "That model is outside this connection's allowed list. Choose one from the list.";
  }
}

function providerModelCardCopy(language: ComposerLanguage): {
  live: string;
  manual: string;
  remove: string;
  liveFetch: string;
  cached: string;
  autoOn: string;
  cacheOnly: string;
} {
  const copy: Record<ComposerLanguage, ReturnType<typeof providerModelCardCopy>> = {
    "zh-CN": { live: "实时", manual: "手动添加", remove: "移除模型", liveFetch: "实时拉取", cached: "使用缓存", autoOn: "已开启", cacheOnly: "仅缓存" },
    "en-US": { live: "Live", manual: "Manual", remove: "Remove model", liveFetch: "Live fetch", cached: "Cached", autoOn: "On", cacheOnly: "Cache only" },
    "es-ES": { live: "En directo", manual: "Manual", remove: "Quitar modelo", liveFetch: "Consulta en directo", cached: "En caché", autoOn: "Activado", cacheOnly: "Solo caché" },
    "fr-FR": { live: "En direct", manual: "Manuel", remove: "Retirer le modèle", liveFetch: "Récupération en direct", cached: "En cache", autoOn: "Activé", cacheOnly: "Cache uniquement" },
    "de-DE": { live: "Live", manual: "Manuell", remove: "Modell entfernen", liveFetch: "Live abrufen", cached: "Zwischengespeichert", autoOn: "Aktiv", cacheOnly: "Nur Cache" },
    "ja-JP": { live: "取得済み", manual: "手動追加", remove: "モデルを削除", liveFetch: "最新の一覧を取得", cached: "キャッシュ", autoOn: "有効", cacheOnly: "キャッシュのみ" },
    "ko-KR": { live: "실시간", manual: "직접 추가", remove: "모델 제거", liveFetch: "실시간으로 가져오기", cached: "캐시됨", autoOn: "켜짐", cacheOnly: "캐시만 사용" },
    "pt-BR": { live: "Ao vivo", manual: "Manual", remove: "Remover modelo", liveFetch: "Buscar ao vivo", cached: "Em cache", autoOn: "Ativado", cacheOnly: "Somente cache" },
  };

  return copy[language] ?? copy["en-US"];
}

function normalizeComparablePath(value: string | undefined | null): string | undefined {
  const trimmed = typeof value === "string" ? value.trim() : "";
  if (!trimmed) {
    return undefined;
  }
  return trimmed.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
}

function memoryShareSourceLabel(sourceWorkspaceId: string): string {
  const segments = sourceWorkspaceId.replace(/\\/g, "/").split("/").filter(Boolean);
  return segments[segments.length - 1] || sourceWorkspaceId;
}

function normalizeProviderProfileView(
  value: unknown,
  activeProfileId?: string,
): ProviderProfileView | undefined {
  const record = asRecord(value);
  if (!record) {
    return undefined;
  }

  const id = asString(record.id);
  if (!id) {
    return undefined;
  }

  const label = asString(record.label) ?? asString(record.name) ?? id;
  const model = asString(record.model) ?? "";
  const protocol = asString(record.protocol);
  const mode = asString(record.mode);
  const baseUrl = asString(record.baseUrl);
  const credentialMode = asString(record.credentialMode);
  const availableModels = asStringArray(record.availableModels);
  const contextWindowTokens = asNumber(record.contextWindowTokens);
  const maxOutputTokens = asNumber(record.maxOutputTokens);
  const detail = compactSummaryValue(
    [
      protocol,
      mode,
      baseUrl,
      credentialMode,
      availableModels.length > 0 ? `${availableModels.length} models` : undefined,
      contextWindowTokens ? `ctx ${contextWindowTokens}` : undefined,
      maxOutputTokens ? `out ${maxOutputTokens}` : undefined,
    ].filter(Boolean) as string[],
    "",
  );

  return {
    id,
    label,
    model,
    mode,
    protocol,
    baseUrl,
    credentialMode,
    availableModelCount: availableModels.length,
    isActive: activeProfileId ? activeProfileId === id : false,
    detail: detail || undefined,
  };
}

function normalizeProviderProfileViews(provider: ProviderConfigView): ProviderProfileView[] {
  const activeProfileId = provider.configured ? provider.profileId?.trim() : undefined;
  const profileRecords = provider.providerProfiles ?? [];
  const normalized = profileRecords
    .map((profile) => normalizeProviderProfileView(profile, activeProfileId))
    .filter((profile): profile is ProviderProfileView => Boolean(profile));

  if (normalized.length > 0) {
    const activeIndex = normalized.findIndex((profile) => profile.isActive);
    if (activeIndex > 0) {
      const [activeProfile] = normalized.splice(activeIndex, 1);
      if (activeProfile) {
        normalized.unshift(activeProfile);
      }
    }
    return normalized;
  }

  if (!provider.configured) {
    return normalized;
  }

  const fallback = normalizeProviderProfileView(
    {
      id: activeProfileId ?? provider.name ?? "provider",
      label: provider.profileLabel ?? provider.name,
      model: provider.resolvedModel ?? provider.model,
      mode: provider.profileMode,
      protocol: provider.protocol,
      baseUrl: provider.baseUrl,
      credentialMode: provider.credentialMode,
      availableModels: provider.availableModels,
    },
    activeProfileId,
  );
  return fallback ? [fallback] : [];
}

export interface ProviderDraft {
  name: string;
  protocol: ProviderProtocol;
  baseUrl: string;
  model: string;
  contextWindowTokens?: number;
  maxOutputTokens?: number;
  modelTokenLimits?: Record<string, ProviderModelTokenLimit>;
  credentialMode?: ProviderConfigView["credentialMode"];
  catalogModels?: string[];
  allowedModels?: string[];
  deniedModels?: string[];
  embeddingModel?: string;
  catalogSource?: ProviderConfigView["catalogSource"];
  cacheTtlSeconds?: number;
  requestDefaults?: Record<string, unknown>;
  apiKey: string;
}

export interface SettingsActionFeedback {
  actionKind?: string;
  tone: "pass" | "fail" | "pending";
  title: string;
  detail?: string;
}

export interface SettingsSectionStatus {
  saveState: SaveState;
  effectiveValue: string;
  savedValue?: string;
  editingValue?: string;
  note?: string;
  feedback?: SettingsActionFeedback;
}

export interface CoachSettingsLabels {
  eyebrow: string;
  title: string;
  intro: string;
  setupSection: string;
  setupTitleReady: string;
  setupTitleBlocked: string;
  setupDetailReady: string;
  setupDetailBlocked: string;
  setupAction: string;
  interfaceSection: string;
  coachSection: string;
  modelSection: string;
  theme: string;
  language: string;
  answerMode: string;
  teachingStyle: string;
  followCurrentFile: string;
  contextMode: string;
  currentFile: string;
  selection: string;
  diagnostics: string;
  relatedFiles: string;
  provider: string;
  protocol: string;
  baseUrl: string;
  model: string;
  apiKey: string;
  apiKeySaved: string;
  apiKeyMissing: string;
  configured: string;
  notConfigured: string;
  save: string;
  saveCoachDefaults: string;
  test: string;
  clear: string;
  openConfig: string;
  system: string;
  light: string;
  dark: string;
  auto: string;
  coachFirst: string;
  balanced: string;
  direct: string;
  teachingGuided: string;
  teachingConceptFirst: string;
  teachingHandsOn: string;
  teachingChallenging: string;
  on: string;
  off: string;
  focused: string;
  balancedContext: string;
  fullContext: string;
  connectionDetails: string;
  longTermMemory: string;
  memoryScope: string;
  memoryScopeProject: string;
  memoryScopePersonal: string;
  memoryScopeSession: string;
  memorySharing: string;
  memorySharingDetail: string;
  memorySharingNone: string;
  memorySharingActive: string;
  memorySharingUnavailable: string;
  memoryShareGrant: string;
  memoryShareRevoke: string;
  memorySharePreferences: string;
  memoryShareMastery: string;
  rememberDecisions: string;
  rememberPatterns: string;
  rememberResources: string;
  workingSet: string;
  workingSetFocused: string;
  workingSetBalanced: string;
  workingSetBroad: string;
  memoryPreview: string;
  memoryPreviewEmpty: string;
  reviewRhythm: string;
  nextReview: string;
  coachState: string;
  teachingSignal: string;
  configFileNote: string;
  contextSection: string;
  memoryRuntime: string;
  memoryRuntimeDetail: string;
  advancedSection: string;
  advancedIntro: string;
  reviewRhythmPace: string;
  reviewRhythmReminder: string;
  reviewStrategy: string;
  systemActions: string;
  refreshMemory: string;
  resetDefaults: string;
  modelTools: string;
  defaultsHint: string;
  contextHint: string;
  modelHint: string;
  thinking: string;
  thinkingDetail: string;
  thinkingOff: string;
  thinkingAuto: string;
  thinkingOn: string;
  thinkingAdvanced: string;
  thinkingEffort: string;
  thinkingBudget: string;
  thinkingUnsupported: string;
  thinkingOpenAiEffort: string;
  thinkingAnthropicBudget: string;
  thinkingGeminiConfig: string;
  thinkingMiniMaxDisabled: string;
  availableModels: string;
  detectedModel: string;
  modelFetchLoading: string;
  modelFetchEmpty: string;
  refreshModels: string;
  modelCache: string;
  modelCacheSource: string;
  modelCacheFetchedAt: string;
  modelCacheExpiresAt: string;
  modelCacheStatus: string;
  modelCacheError: string;
  modelCacheSourceLive: string;
  modelCacheSourceCache: string;
  modelCacheStatusFresh: string;
  modelCacheStatusExpired: string;
  modelCacheStatusUnknown: string;
  modelCacheStatusLoading: string;
  modelCacheStatusError: string;
  runtimeSection: string;
  runtimeHint: string;
  memoryStrategy: string;
  memoryStrategyHint: string;
  reviewStrategyHint: string;
  contextCurrentFileHint: string;
  contextSelectionHint: string;
  contextDiagnosticsHint: string;
  contextRelatedFilesHint: string;
  memoryScopeRuntimeProject: string;
  memoryScopeRuntimePersonal: string;
  memoryScopeRuntimeSession: string;
  memoryScopeProjectHint: string;
  memoryScopePersonalHint: string;
  memoryScopeSessionHint: string;
  workingSetFocusedHint: string;
  workingSetBalancedHint: string;
  workingSetBroadHint: string;
  reviewCadenceLightHint: string;
  reviewCadenceSteadyHint: string;
  reviewCadenceActiveHint: string;
  reviewReminderDueHint: string;
  reviewReminderAheadHint: string;
  reviewReminderDigestHint: string;
  savedState: string;
  unsavedState: string;
  emptyState: string;
  effectiveNow: string;
  savedInWorkspace: string;
  editingDraft: string;
  currentWorkspace: string;
  refreshWorkspaceAuthority: string;
  workspaceAuthorityEmpty: string;
  managedDataFolder: string;
  managedDataFolderHint: string;
  managedDataFolderRecommended: string;
  managedDataFolderCustom: string;
  managedDataFolderChoose: string;
  managedDataFolderReset: string;
  managedDataFolderFallbackNote: string;
  localThemeNote: string;
  workspaceSaveNote: string;
  providerRuntimeNote: string;
  latestAction: string;
  lastTest: string;
  lastTestNever: string;
  lastTestPassed: string;
  lastTestFailed: string;
  lastTestNeedsSetup: string;
}

export interface CoachSettingsViewProps {
  provider: ProviderConfigView;
  workspaceId?: string;
  capabilityVerdict: TrainerCapabilityVerdict;
  providerImageInputState?: ProviderImageInputState;
  providerDraft: ProviderDraft;
  coachStateSummary?: ReactNode;
  coachSignal?: string;
  learnerName?: string;
  targetProject?: string;
  preferredRhythm?: string;
  preferredLearningMode?: string;
  onboardingRequest?: string;
  projectContext?: string;
  reviewRhythmSummary?: string;
  nextReviewDue?: string;
  longTermMemoryStateLabel?: string;
  memoryShareGrants?: MemoryShareGrant[];
  workspaceAuthority?: WorkspaceAuthority | null;
  /** Live host/sidecar trust; leftover-not-live must pass undefined → unknown, never invent Ready. */
  workspaceTrustState?: WorkspaceTrustState | string | null;
  resourceSandbox?: ManagedDataFolder | null;
  trainerWorkspace?: TrainerWorkspaceAdmission;
  themePreference: ThemePreference;
  learningSurfaceAlignment: LearningSurfaceAlignment;
  language: ComposerLanguage;
  answerMode: AnswerMode;
  teachingStyle: TeachingStyle;
  coachDefaults: CoachDefaults;
  followCurrentFile: boolean;
  contextDetail?: "focused" | "balanced" | "full";
  includeCurrentFile?: boolean;
  includeSelection?: boolean;
  includeDiagnostics?: boolean;
  includeRelatedFiles?: boolean;
  className?: string;
  labels?: Partial<CoachSettingsLabels>;
  onProviderDraftChange: (patch: Partial<ProviderDraft>) => void;
  providerStatus?: SettingsSectionStatus;
  coachDefaultsStatus?: SettingsSectionStatus;
  workspaceControlStatus?: SettingsSectionStatus;
  providerApiKeyFocusRequest?: number;
  onThemePreferenceChange?: (value: ThemePreference) => void;
  onLearningSurfaceAlignmentChange?: (value: LearningSurfaceAlignment) => void;
  onLanguageChange?: (value: ComposerLanguage) => void;
  onAnswerModeChange?: (value: AnswerMode) => void;
  onTeachingStyleChange?: (value: TeachingStyle) => void;
  onFollowCurrentFileChange?: (value: boolean) => void;
  onCoachDefaultsChange?: (value: Partial<CoachDefaults>) => void;
  onContextDetailChange?: (value: "focused" | "balanced" | "full") => void;
  onIncludeCurrentFileChange?: (value: boolean) => void;
  onIncludeSelectionChange?: (value: boolean) => void;
  onIncludeDiagnosticsChange?: (value: boolean) => void;
  onIncludeRelatedFilesChange?: (value: boolean) => void;
  onSaveCoachSettings?: () => void;
  onGrantMemoryShare?: () => void;
  onRevokeMemoryShare?: (sourceWorkspaceId: string) => void;
  onSaveProvider?: () => void;
  onSaveProviderProfile?: () => void;
  onUseProviderTemplate?: () => void;
  onRefreshProviderProfiles?: () => void;
  onSwitchProviderProfile?: (profileId: string) => void;
  onRefreshProviderModels?: () => void;
  onTestProvider?: () => void;
  onRestartSidecar?: () => void;
  onClearProvider?: () => void;
  onOpenConfig?: () => void;
  onRefreshWorkspaceAuthority?: () => void;
  onChooseTrainerWorkspaceRoot?: () => void;
  onMigrateTrainerWorkspaceRoot?: () => void;
  onBackupTrainerWorkspace?: () => void;
  onRestoreTrainerWorkspaceBackup?: () => void;
  onChooseManagedDataFolder?: () => void;
  onResetManagedDataFolder?: () => void;
  onRefreshMemory?: () => void;
  onResetDefaults?: () => void;
}

const defaultLabels: Partial<CoachSettingsLabels> = {
  eyebrow: "设置",
  title: "Trainer 设置",
  intro: "",
  setupSection: "模型连接",
  setupTitleReady: "模型已连接",
  setupTitleBlocked: "模型未连接",
  setupDetailReady: "对话、计划、训练可用。",
  setupDetailBlocked: "补全连接信息、模型和访问密钥。",
  setupAction: "保存连接",
  interfaceSection: "教练",
  coachSection: "这一轮带什么",
  modelSection: "连接模型",
  theme: "主题",
  language: "语言",
  answerMode: "反馈方式",
  teachingStyle: "教学风格",
  followCurrentFile: "实时跟随",
  contextMode: "上下文强度",
  currentFile: "当前文件",
  selection: "当前选区",
  diagnostics: "诊断信息",
  relatedFiles: "相关文件",
  provider: "连接服务",
  protocol: "连接方式",
  baseUrl: "服务地址",
  model: "默认模型",
  apiKey: "访问密钥",
  apiKeySaved: "已保存",
  apiKeyMissing: "未配置",
  configured: "已配置",
  notConfigured: "未配置",
  save: "保存",
  saveCoachDefaults: "保存教练默认",
  test: "测试",
  clear: "清空",
  openConfig: "打开配置",
  system: "跟随系统",
  light: "浅色",
  dark: "深色",
  coachFirst: "教练优先",
  balanced: "平衡",
  direct: "直接",
  teachingGuided: "引导式",
  teachingConceptFirst: "原理先行",
  teachingHandsOn: "实战优先",
  teachingChallenging: "挑战式",
  on: "开启",
  off: "关闭",
  focused: "聚焦",
  balancedContext: "标准",
  fullContext: "扩展",
  connectionDetails: "连接",
  longTermMemory: "长期记忆",
  memoryScope: "记忆范围",
  memoryScopeProject: "当前项目",
  memoryScopePersonal: "个人通用",
  memoryScopeSession: "仅本次会话",
  rememberDecisions: "架构决策",
  rememberPatterns: "常用模式",
  rememberResources: "参考资料",
  workingSet: "工作集范围",
  workingSetFocused: "只跟当前任务",
  workingSetBalanced: "兼顾邻近文件",
  workingSetBroad: "允许更宽引用",
  memoryPreview: "优先保留",
  memoryPreviewEmpty: "当前主要跟随文件、选区和诊断。",
  reviewRhythm: "复习节奏",
  nextReview: "下次提醒",
  coachState: "教练判断",
  teachingSignal: "学习信号",
  configFileNote: "更深的连接选项继续走配置文件。",
  contextSection: "附带上下文",
  memoryRuntime: "后台运行",
  memoryRuntimeDetail: "随发送更新。",
  advancedSection: "更多默认策略",
  advancedIntro: "记忆、复习、主题。",
  reviewRhythmPace: "提醒强度",
  reviewRhythmReminder: "提醒策略",
  reviewStrategy: "复习策略",
  systemActions: "整理当前状态",
  refreshMemory: "刷新当前记忆",
  resetDefaults: "恢复推荐默认",
  modelTools: "连接工具",
  defaultsHint: "语言、反馈、教学风格。",
  contextHint: "默认消息上下文。",
  modelHint: "连接服务、连接方式、模型和访问密钥。",
  availableModels: "可用模型",
  detectedModel: "实际使用",
  modelFetchLoading: "正在拉取模型列表…",
  modelFetchEmpty: "保存访问密钥后再拉取。",
  refreshModels: "刷新模型",
  modelCache: "模型列表状态",
  modelCacheSource: "来源",
  modelCacheFetchedAt: "最近拉取",
  modelCacheExpiresAt: "失效时间",
  modelCacheStatus: "状态",
  modelCacheError: "错误原因",
  modelCacheSourceLive: "实时拉取",
  modelCacheSourceCache: "缓存结果",
  modelCacheStatusFresh: "有效",
  modelCacheStatusExpired: "已过期",
  modelCacheStatusUnknown: "未知",
  modelCacheStatusLoading: "刷新中",
  modelCacheStatusError: "失败",
  runtimeSection: "当前教练运行",
  runtimeHint: "下一条消息使用。",
  memoryStrategy: "记忆策略",
  memoryStrategyHint: "记忆保存位置。",
  reviewStrategyHint: "复习频率和提醒。",
  contextCurrentFileHint: "附带当前文件。",
  contextSelectionHint: "附带当前选区。",
  contextDiagnosticsHint: "附带诊断。",
  contextRelatedFilesHint: "按需附带相关文件。",
  memoryScopeRuntimeProject: "当前项目计划、主线、资料。",
  memoryScopeRuntimePersonal: "跨项目偏好和训练历史。",
  memoryScopeRuntimeSession: "仅当前会话。",
  memoryScopeProjectHint: "仅当前项目。",
  memoryScopePersonalHint: "跨项目复用。",
  memoryScopeSessionHint: "仅当前会话。",
  workingSetFocusedHint: "当前切片和最近文件。",
  workingSetBalancedHint: "当前切片加邻近上下文。",
  workingSetBroadHint: "验证时扩大引用。",
  reviewCadenceLightHint: "少打断。",
  reviewCadenceSteadyHint: "标准节奏。",
  reviewCadenceActiveHint: "高频回看。",
  reviewReminderDueHint: "到期提醒。",
  reviewReminderAheadHint: "提前提醒。",
  reviewReminderDigestHint: "合并提醒。",
  savedState: "已保存",
  unsavedState: "未保存修改",
  emptyState: "当前工作区未写入",
  effectiveNow: "当前生效",
  savedInWorkspace: "工作区已保存",
  editingDraft: "正在编辑",
  currentWorkspace: "当前工作区",
  refreshWorkspaceAuthority: "刷新工作区边界",
  workspaceAuthorityEmpty: "还没有收到沙箱边界信息。",
  localThemeNote: "仅影响当前界面。",
  workspaceSaveNote: "保存后在当前工作区生效。",
  providerRuntimeNote: "测试使用当前工作区 provider。",
  latestAction: "最近动作",
  lastTest: "最近测试",
  lastTestNever: "还没有测试过",
  lastTestPassed: "已通过",
  lastTestFailed: "失败",
  lastTestNeedsSetup: "待补全",
  managedDataFolder: "受管数据目录",
  managedDataFolderHint: "Trainer 在这里保存后端数据和回退沙箱内容。切换后会重启后端，旧目录不会自动删除。",
  managedDataFolderRecommended: "推荐目录",
  managedDataFolderCustom: "自定义目录",
  managedDataFolderChoose: "选择目录",
  managedDataFolderReset: "使用推荐目录",
  managedDataFolderFallbackNote: "只有目标目录为空时，Trainer 才会自动复制现有数据。",
};

const englishLabels: Partial<CoachSettingsLabels> = {
  eyebrow: "Settings",
  title: "Trainer Settings",
  intro: "",
  setupSection: "Model service",
  setupTitleReady: "Model connected",
  setupTitleBlocked: "Model not connected",
  setupDetailReady: "Chat, plan, and training ready.",
  setupDetailBlocked: "Fill provider, protocol, base URL, model, and API key.",
  setupAction: "Save connection",
  interfaceSection: "Coach",
  coachSection: "This turn includes",
  modelSection: "Connect model",
  theme: "Theme",
  language: "Language",
  answerMode: "Response style",
  teachingStyle: "Teaching style",
  followCurrentFile: "Follow current file",
  contextMode: "Context depth",
  currentFile: "Current file",
  selection: "Selection",
  diagnostics: "Diagnostics",
  relatedFiles: "Related files",
  provider: "Provider",
  protocol: "Protocol",
  baseUrl: "Base URL",
  model: "Default model",
  apiKey: "API key",
  apiKeySaved: "Saved",
  apiKeyMissing: "Missing",
  configured: "Configured",
  notConfigured: "Not configured",
  save: "Save",
  saveCoachDefaults: "Save coach defaults",
  test: "Test",
  clear: "Clear",
  openConfig: "Open config",
  system: "System",
  light: "Light",
  dark: "Dark",
  coachFirst: "Coach-first",
  balanced: "Balanced",
  direct: "Direct",
  teachingGuided: "Guided",
  teachingConceptFirst: "Concept-first",
  teachingHandsOn: "Hands-on",
  teachingChallenging: "Challenging",
  on: "On",
  off: "Off",
  focused: "Focused",
  balancedContext: "Standard",
  fullContext: "Expanded",
  connectionDetails: "Connection",
  longTermMemory: "Long-term memory",
  memoryScope: "Memory scope",
  memoryScopeProject: "Current project",
  memoryScopePersonal: "Personal",
  memoryScopeSession: "This session only",
  rememberDecisions: "Architecture decisions",
  rememberPatterns: "Useful patterns",
  rememberResources: "Reference materials",
  workingSet: "Working set",
  workingSetFocused: "Current task only",
  workingSetBalanced: "Neighboring files",
  workingSetBroad: "Broader references",
  memoryPreview: "Keep first",
  memoryPreviewEmpty: "Currently follows files, selection, and diagnostics.",
  reviewRhythm: "Review rhythm",
  nextReview: "Next reminder",
  coachState: "Coach judgment",
  teachingSignal: "Learning signal",
  configFileNote: "Advanced provider options live in the config file.",
  contextSection: "Attached context",
  memoryRuntime: "Background runtime",
  memoryRuntimeDetail: "Updates as you send.",
  advancedSection: "More defaults",
  advancedIntro: "Memory, review, theme.",
  reviewRhythmPace: "Reminder pace",
  reviewRhythmReminder: "Reminder mode",
  reviewStrategy: "Review strategy",
  systemActions: "Current state actions",
  refreshMemory: "Refresh memory",
  resetDefaults: "Restore recommended defaults",
  modelTools: "Connection tools",
  defaultsHint: "Language, response, teaching style.",
  contextHint: "Default message context.",
  modelHint: "Provider, protocol, model, and API key.",
  availableModels: "Available models",
  detectedModel: "Resolved model",
  modelFetchLoading: "Fetching model list...",
  modelFetchEmpty: "Save an API key to fetch.",
  refreshModels: "Refresh model list",
  modelCache: "Model list status",
  modelCacheSource: "Source",
  modelCacheFetchedAt: "Last fetched",
  modelCacheExpiresAt: "Expires",
  modelCacheStatus: "Status",
  modelCacheError: "Error",
  modelCacheSourceLive: "Live fetch",
  modelCacheSourceCache: "Cached result",
  modelCacheStatusFresh: "Fresh",
  modelCacheStatusExpired: "Expired",
  modelCacheStatusUnknown: "Unknown",
  modelCacheStatusLoading: "Refreshing",
  modelCacheStatusError: "Failed",
  runtimeSection: "Current coach runtime",
  runtimeHint: "Used by the next message.",
  memoryStrategy: "Memory strategy",
  memoryStrategyHint: "Memory location.",
  reviewStrategyHint: "Review frequency and reminders.",
  contextCurrentFileHint: "Attach current file.",
  contextSelectionHint: "Attach selection.",
  contextDiagnosticsHint: "Attach diagnostics.",
  contextRelatedFilesHint: "Attach related files as needed.",
  memoryScopeRuntimeProject: "Current project plan, thread, materials.",
  memoryScopeRuntimePersonal: "Cross-project preferences and history.",
  memoryScopeRuntimeSession: "This conversation only.",
  memoryScopeProjectHint: "Current project only.",
  memoryScopePersonalHint: "Reuse across projects.",
  memoryScopeSessionHint: "Current conversation only.",
  workingSetFocusedHint: "Current slice and nearest files.",
  workingSetBalancedHint: "Current slice plus neighbors.",
  workingSetBroadHint: "Widen references for verification.",
  reviewCadenceLightHint: "Fewer interruptions.",
  reviewCadenceSteadyHint: "Standard rhythm.",
  reviewCadenceActiveHint: "Frequent review.",
  reviewReminderDueHint: "Due reminders.",
  reviewReminderAheadHint: "Early reminders.",
  reviewReminderDigestHint: "Digest reminders.",
  savedState: "Saved",
  unsavedState: "Unsaved changes",
  emptyState: "Not saved in workspace",
  effectiveNow: "Effective now",
  savedInWorkspace: "Saved in workspace",
  editingDraft: "Editing draft",
  currentWorkspace: "Current workspace",
  refreshWorkspaceAuthority: "Refresh workspace boundary",
  workspaceAuthorityEmpty: "No sandbox authority has been reported yet.",
  localThemeNote: "Only affects this UI.",
  workspaceSaveNote: "Saves for this workspace.",
  providerRuntimeNote: "Tests use the active workspace provider.",
  latestAction: "Latest action",
  lastTest: "Last test",
  lastTestNever: "Never tested",
  lastTestPassed: "Passed",
  lastTestFailed: "Failed",
  lastTestNeedsSetup: "Needs setup",
  managedDataFolder: "Managed data folder",
  managedDataFolderHint: "Trainer keeps backend data and fallback sandbox content here. Changing it restarts the backend and leaves the previous folder untouched.",
  managedDataFolderRecommended: "Recommended folder",
  managedDataFolderCustom: "Custom folder",
  managedDataFolderChoose: "Choose folder",
  managedDataFolderReset: "Use recommended",
  managedDataFolderFallbackNote: "Trainer only auto-copies existing data when the target folder is empty.",
};

const firstScreenRowLabels: Record<
  ComposerLanguage,
  Pick<CoachSettingsLabels, "interfaceSection" | "coachSection" | "connectionDetails">
> = {
  "zh-CN": {
    interfaceSection: "教练",
    coachSection: "这一轮带什么",
    connectionDetails: "连接",
  },
  "en-US": {
    interfaceSection: "Coach",
    coachSection: "This turn includes",
    connectionDetails: "Connection",
  },
  "es-ES": {
    interfaceSection: "Coach",
    coachSection: "Esta ronda incluye",
    connectionDetails: "Conexión",
  },
  "fr-FR": {
    interfaceSection: "Coach",
    coachSection: "Ce tour inclut",
    connectionDetails: "Connexion",
  },
  "de-DE": {
    interfaceSection: "Coach",
    coachSection: "Diese Runde enthält",
    connectionDetails: "Verbindung",
  },
  "ja-JP": {
    interfaceSection: "コーチ",
    coachSection: "このターンに含むもの",
    connectionDetails: "接続",
  },
  "ko-KR": {
    interfaceSection: "코치",
    coachSection: "이번 턴에 포함",
    connectionDetails: "연결",
  },
  "pt-BR": {
    interfaceSection: "Coach",
    coachSection: "Esta rodada inclui",
    connectionDetails: "Conexão",
  },
};

function localizedSettingsLabels(language: ComposerLanguage): Partial<CoachSettingsLabels> {
  const copy = resolveWorkbenchCopy(language);
  const firstScreenRows = firstScreenRowLabels[language] ?? firstScreenRowLabels["en-US"];
  return {
    eyebrow: copy.settings,
    title: `Trainer ${copy.settings}`,
    setupSection: copy.settingsSetupSection,
    setupTitleReady: copy.settingsSetupTitleReady,
    setupTitleBlocked: copy.settingsSetupTitleBlocked,
    setupDetailReady: copy.settingsSetupDetailReady,
    setupDetailBlocked: copy.settingsSetupDetailBlocked,
    setupAction: copy.settingsSetupAction,
    interfaceSection: firstScreenRows.interfaceSection,
    coachSection: firstScreenRows.coachSection,
    modelSection: copy.settingsModelSection,
    theme: copy.theme,
    language: copy.language,
    answerMode: copy.answerMode,
    teachingStyle: copy.teachingStyle,
    followCurrentFile: copy.settingsFollowCurrentFile,
    contextMode: copy.settingsContextMode,
    currentFile: copy.settingsCurrentFile,
    selection: copy.selection,
    diagnostics: copy.diagnostics,
    relatedFiles: copy.relatedFiles,
    provider: copy.provider,
    protocol: copy.protocol,
    baseUrl: copy.baseUrl,
    model: copy.chatModel,
    apiKey: copy.apiKey,
    apiKeySaved: copy.apiKeySaved,
    apiKeyMissing: copy.apiKeyMissing,
    configured: copy.configured,
    notConfigured: copy.notConfigured,
    save: copy.saveProvider,
    saveCoachDefaults: copy.settingsSaveCoachDefaults,
    test: copy.testProvider,
    clear: copy.clearProvider,
    openConfig: copy.openConfigFile,
    system: copy.system,
    light: copy.light,
    dark: copy.dark,
    coachFirst: copy.coachFirst,
    balanced: copy.balanced,
    direct: copy.direct,
    teachingGuided: copy.teachingGuided,
    teachingConceptFirst: copy.teachingConceptFirst,
    teachingHandsOn: copy.teachingHandsOn,
    teachingChallenging: copy.teachingChallenging,
    focused: copy.settingsFocused,
    balancedContext: copy.settingsBalancedContext,
    fullContext: copy.settingsFullContext,
    connectionDetails: firstScreenRows.connectionDetails,
    longTermMemory: copy.settingsLongTermMemory,
    memoryScope: copy.settingsMemoryScope,
    memoryScopeProject: copy.settingsMemoryScopeProject,
    memoryScopePersonal: copy.settingsMemoryScopePersonal,
    memoryScopeSession: copy.settingsMemoryScopeSession,
    memorySharing: copy.settingsMemorySharing,
    memorySharingDetail: copy.settingsMemorySharingDetail,
    memorySharingNone: copy.settingsMemorySharingNone,
    memorySharingActive: copy.settingsMemorySharingActive,
    memorySharingUnavailable: copy.settingsMemorySharingUnavailable,
    memoryShareGrant: copy.settingsMemoryShareGrant,
    memoryShareRevoke: copy.settingsMemoryShareRevoke,
    memorySharePreferences: copy.settingsMemorySharePreferences,
    memoryShareMastery: copy.settingsMemoryShareMastery,
    rememberDecisions: copy.settingsRememberDecisions,
    rememberPatterns: copy.settingsRememberPatterns,
    rememberResources: copy.settingsRememberResources,
    workingSet: copy.settingsWorkingSet,
    workingSetFocused: copy.settingsWorkingSetFocused,
    workingSetBalanced: copy.settingsWorkingSetBalanced,
    workingSetBroad: copy.settingsWorkingSetBroad,
    memoryPreview: copy.settingsMemoryPreview,
    memoryPreviewEmpty: copy.settingsMemoryPreviewEmpty,
    teachingSignal: copy.settingsTeachingSignal,
    configFileNote: copy.settingsConfigFileNote,
    contextSection: copy.settingsContextSection,
    memoryRuntime: copy.settingsMemoryRuntime,
    memoryRuntimeDetail: copy.settingsMemoryRuntimeDetail,
    advancedSection: copy.settingsAdvancedSection,
    advancedIntro: copy.settingsAdvancedIntro,
    reviewRhythmPace: copy.settingsReviewRhythmPace,
    reviewRhythmReminder: copy.settingsReviewRhythmReminder,
    reviewStrategy: copy.settingsReviewStrategy,
    systemActions: copy.settingsSystemActions,
    refreshMemory: copy.settingsRefreshMemory,
    resetDefaults: copy.settingsResetDefaults,
    modelTools: copy.settingsModelTools,
    defaultsHint: copy.settingsDefaultsHint,
    contextHint: copy.settingsContextHint,
    modelHint: copy.settingsModelHint,
    thinking: copy.settingsThinking,
    thinkingDetail: copy.settingsThinkingDetail,
    thinkingOff: copy.settingsThinkingOff,
    thinkingAuto: copy.settingsThinkingAuto,
    thinkingOn: copy.settingsThinkingOn,
    thinkingAdvanced: copy.settingsThinkingAdvanced,
    thinkingEffort: copy.settingsThinkingEffort,
    thinkingBudget: copy.settingsThinkingBudget,
    thinkingUnsupported: copy.settingsThinkingUnsupported,
    thinkingOpenAiEffort: copy.settingsThinkingOpenAiEffort,
    thinkingAnthropicBudget: copy.settingsThinkingAnthropicBudget,
    thinkingGeminiConfig: copy.settingsThinkingGeminiConfig,
    thinkingMiniMaxDisabled: copy.settingsThinkingMiniMaxDisabled,
    availableModels: copy.settingsAvailableModels,
    detectedModel: copy.settingsDetectedModel,
    modelFetchLoading: copy.settingsModelFetchLoading,
    modelFetchEmpty: copy.settingsModelFetchEmpty,
    refreshModels: copy.settingsRefreshModels,
    modelCache: copy.settingsModelCache,
    modelCacheSource: copy.settingsModelCacheSource,
    modelCacheFetchedAt: copy.settingsModelCacheFetchedAt,
    modelCacheExpiresAt: copy.settingsModelCacheExpiresAt,
    modelCacheStatus: copy.settingsModelCacheStatus,
    modelCacheError: copy.settingsModelCacheError,
    modelCacheSourceLive: copy.settingsModelCacheSourceLive,
    modelCacheSourceCache: copy.settingsModelCacheSourceCache,
    modelCacheStatusFresh: copy.settingsModelCacheStatusFresh,
    modelCacheStatusExpired: copy.settingsModelCacheStatusExpired,
    modelCacheStatusUnknown: copy.settingsModelCacheStatusUnknown,
    modelCacheStatusLoading: copy.settingsModelCacheStatusLoading,
    modelCacheStatusError: copy.settingsModelCacheStatusError,
    runtimeSection: copy.settingsRuntimeSection,
    runtimeHint: copy.settingsRuntimeHint,
    memoryStrategy: copy.settingsMemoryStrategy,
    memoryStrategyHint: copy.settingsMemoryStrategyHint,
    reviewStrategyHint: copy.settingsReviewStrategyHint,
    contextCurrentFileHint: copy.settingsContextCurrentFileHint,
    contextSelectionHint: copy.settingsContextSelectionHint,
    contextDiagnosticsHint: copy.settingsContextDiagnosticsHint,
    contextRelatedFilesHint: copy.settingsContextRelatedFilesHint,
    memoryScopeRuntimeProject: copy.settingsMemoryScopeRuntimeProject,
    memoryScopeRuntimePersonal: copy.settingsMemoryScopeRuntimePersonal,
    memoryScopeRuntimeSession: copy.settingsMemoryScopeRuntimeSession,
    memoryScopeProjectHint: copy.settingsMemoryScopeProjectHint,
    memoryScopePersonalHint: copy.settingsMemoryScopePersonalHint,
    memoryScopeSessionHint: copy.settingsMemoryScopeSessionHint,
    workingSetFocusedHint: copy.settingsWorkingSetFocusedHint,
    workingSetBalancedHint: copy.settingsWorkingSetBalancedHint,
    workingSetBroadHint: copy.settingsWorkingSetBroadHint,
    reviewCadenceLightHint: copy.settingsReviewCadenceLightHint,
    reviewCadenceSteadyHint: copy.settingsReviewCadenceSteadyHint,
    reviewCadenceActiveHint: copy.settingsReviewCadenceActiveHint,
    reviewReminderDueHint: copy.settingsReviewReminderDueHint,
    reviewReminderAheadHint: copy.settingsReviewReminderAheadHint,
    reviewReminderDigestHint: copy.settingsReviewReminderDigestHint,
    savedState: copy.settingsSavedState,
    unsavedState: copy.settingsUnsavedState,
    emptyState: copy.settingsEmptyState,
    effectiveNow: copy.settingsEffectiveNow,
    savedInWorkspace: copy.settingsSavedInWorkspace,
    editingDraft: copy.settingsEditingDraft,
    currentWorkspace: copy.settingsCurrentWorkspace,
    refreshWorkspaceAuthority: copy.refreshWorkspaceAuthority,
    localThemeNote: copy.settingsLocalThemeNote,
    workspaceSaveNote: copy.settingsWorkspaceSaveNote,
    providerRuntimeNote: copy.settingsProviderRuntimeNote,
    latestAction: copy.settingsLatestAction,
    lastTest: copy.settingsLastTest,
    lastTestNever: copy.settingsLastTestNever,
    lastTestPassed: copy.settingsLastTestPassed,
    lastTestFailed: copy.settingsLastTestFailed,
    lastTestNeedsSetup: copy.settingsLastTestNeedsSetup,
  };
}

type SettingsPhraseKey =
  | "notRecorded"
  | "saveDraft"
  | "chooseModel"
  | "chooseModelDetail"
  | "testDraftConnection"
  | "testDraftConnectionDetail"
  | "useMiniMaxDefaults"
  | "useMiniMaxDefaultsDetail"
  | "reenterMiniMaxKey"
  | "reenterMiniMaxKeyDetail"
  | "testAgain"
  | "testCurrentConnection"
  | "addApiKey"
  | "addApiKeyDetail"
  | "saveToApply"
  | "chat"
  | "images"
  | "notTested"
  | "connectionChecklist"
  | "connectionState"
  | "saveConnectionDetail"
  | "verifyConnectionDetail"
  | "connectionFieldsAndKey"
  | "defaultEndpoint"
  | "capabilitiesFromLiveTest"
  | "finalCapabilities"
  | "contextWindow"
  | "maxOutput"
  | "modelAndTestDetail"
  | "useMiniMaxProfile"
  | "useMiniMaxProfileDetail"
  | "workspaceFile"
  | "clearDraft"
  | "trainerRemembers"
  | "saveDefaults"
  | "currentDefaultsPrefix"
  | "defaultAttachmentsPrefix"
  | "name"
  | "project"
  | "coachingMode"
  | "rhythm"
  | "thisRound"
  | "context"
  | "currentConnectionPrefix";

const settingsPhraseTable: Record<ComposerLanguage, Record<SettingsPhraseKey, string>> = {
  "zh-CN": {
    notRecorded: "未记录",
    saveDraft: "保存草稿",
    chooseModel: "选择模型",
    chooseModelDetail: "从下方列表选择一个模型",
    testDraftConnection: "测试草稿连接",
    testDraftConnectionDetail: "只测试当前填写的内容，不会保存改动",
    useMiniMaxDefaults: "改用推荐默认配置",
    useMiniMaxDefaultsDetail: "切回推荐默认值，并重新测试",
    reenterMiniMaxKey: "重新录入 API key",
    reenterMiniMaxKeyDetail: "重新应用推荐连接，并提示你输入新的 API key",
    testAgain: "重新测试",
    testCurrentConnection: "测试当前连接",
    addApiKey: "补上 API key",
    addApiKeyDetail: "补上 key 后再保存",
    saveToApply: "保存后生效",
    chat: "对话",
    images: "图片",
    notTested: "未测试",
    connectionChecklist: "连接体检",
    connectionState: "连接状态",
    saveConnectionDetail: "保存连接",
    verifyConnectionDetail: "测试连接",
    connectionFieldsAndKey: "连接与密钥",
    defaultEndpoint: "默认端点",
    capabilitiesFromLiveTest: "能力只来自最近一次实测，不会用协议默认值冒充。",
    finalCapabilities: "最终能力",
    contextWindow: "上下文长度",
    maxOutput: "最大输出",
    modelAndTestDetail: "模型与测试",
    useMiniMaxProfile: "使用 MiniMax 模板",
    useMiniMaxProfileDetail: "先用模板，再补 API key",
    workspaceFile: "工作区文件",
    clearDraft: "清空草稿",
    trainerRemembers: "教练已记住",
    saveDefaults: "保存默认项",
    currentDefaultsPrefix: "当前默认",
    defaultAttachmentsPrefix: "默认附带",
    name: "称呼",
    project: "项目",
    coachingMode: "带法",
    rhythm: "节奏",
    thisRound: "这轮重点",
    context: "背景",
    currentConnectionPrefix: "当前连接",
  },
  "en-US": {
    notRecorded: "Not recorded",
    saveDraft: "Save draft",
    chooseModel: "Choose a model",
    chooseModelDetail: "Pick one from the list below",
    testDraftConnection: "Test draft connection",
    testDraftConnectionDetail: "Tests the current entries without saving changes",
    useMiniMaxDefaults: "Use recommended defaults",
    useMiniMaxDefaultsDetail: "Switch to the recommended defaults, then test again",
    reenterMiniMaxKey: "Re-enter API key",
    reenterMiniMaxKeyDetail: "Re-apply the recommended connection and prompt for a fresh key",
    testAgain: "Test again",
    testCurrentConnection: "Test current connection",
    addApiKey: "Add API key",
    addApiKeyDetail: "Add a key, then save",
    saveToApply: "Save to apply",
    chat: "Chat",
    images: "Images",
    notTested: "Not tested",
    connectionChecklist: "Connection checklist",
    connectionState: "Connection state",
    saveConnectionDetail: "Save connection",
    verifyConnectionDetail: "Verify connection",
    connectionFieldsAndKey: "Connection fields and key",
    defaultEndpoint: "Default endpoint",
    capabilitiesFromLiveTest: "Capabilities come only from the latest live test — not protocol defaults.",
    finalCapabilities: "Final capabilities",
    contextWindow: "Context window",
    maxOutput: "Max output",
    modelAndTestDetail: "Model and test detail",
    useMiniMaxProfile: "Use MiniMax template",
    useMiniMaxProfileDetail: "Use the template, then add an API key.",
    workspaceFile: "Workspace file",
    clearDraft: "Clear draft",
    trainerRemembers: "Trainer remembers",
    saveDefaults: "Save defaults",
    currentDefaultsPrefix: "Current defaults",
    defaultAttachmentsPrefix: "Default attachments",
    name: "Name",
    project: "Project",
    coachingMode: "Coaching mode",
    rhythm: "Rhythm",
    thisRound: "This round",
    context: "Context",
    currentConnectionPrefix: "Current connection",
  },
  "es-ES": {
    notRecorded: "Sin registro",
    saveDraft: "Guardar borrador",
    chooseModel: "Elegir un modelo",
    chooseModelDetail: "Elige uno de la lista de abajo",
    testDraftConnection: "Probar conexión de borrador",
    testDraftConnectionDetail: "Prueba los datos actuales sin guardar cambios",
    useMiniMaxDefaults: "Usar valores recomendados",
    useMiniMaxDefaultsDetail: "Volver a probar con los valores recomendados",
    reenterMiniMaxKey: "Volver a introducir la clave API",
    reenterMiniMaxKeyDetail: "Reaplicar la conexión recomendada y pedir una clave nueva",
    testAgain: "Probar de nuevo",
    testCurrentConnection: "Probar la conexión actual",
    addApiKey: "Añadir clave API",
    addApiKeyDetail: "Añade una clave y luego guarda",
    saveToApply: "Guardar para aplicar",
    chat: "Chat",
    images: "Imágenes",
    notTested: "Sin prueba",
    connectionChecklist: "Comprobación de conexión",
    connectionState: "Estado de conexión",
    saveConnectionDetail: "Guardar conexión",
    verifyConnectionDetail: "Verificar conexión",
    connectionFieldsAndKey: "Campos de conexión y clave",
    defaultEndpoint: "Endpoint predeterminado",
    capabilitiesFromLiveTest: "Las capacidades solo vienen de la última prueba en vivo, no de valores por defecto del protocolo.",
    finalCapabilities: "Capacidades finales",
    contextWindow: "Ventana de contexto",
    maxOutput: "Salida máxima",
    modelAndTestDetail: "Modelo y detalle de prueba",
    useMiniMaxProfile: "Usar plantilla de MiniMax",
    useMiniMaxProfileDetail: "Usa la plantilla y luego añade la clave API.",
    workspaceFile: "Archivo del workspace",
    clearDraft: "Limpiar borrador",
    trainerRemembers: "Trainer recuerda",
    saveDefaults: "Guardar valores",
    currentDefaultsPrefix: "Valores actuales",
    defaultAttachmentsPrefix: "Adjuntos predeterminados",
    name: "Nombre",
    project: "Proyecto",
    coachingMode: "Modo de guía",
    rhythm: "Ritmo",
    thisRound: "Esta ronda",
    context: "Contexto",
    currentConnectionPrefix: "Conexión actual",
  },
  "fr-FR": {
    notRecorded: "Non enregistré",
    saveDraft: "Enregistrer le brouillon",
    chooseModel: "Choisir un modèle",
    chooseModelDetail: "Choisissez-en un dans la liste ci-dessous",
    testDraftConnection: "Tester la connexion du brouillon",
    testDraftConnectionDetail: "Teste les informations actuelles sans enregistrer les modifications",
    useMiniMaxDefaults: "Utiliser les valeurs recommandées",
    useMiniMaxDefaultsDetail: "Revenir aux valeurs recommandées puis retester",
    reenterMiniMaxKey: "Saisir de nouveau la clé API",
    reenterMiniMaxKeyDetail: "Réappliquer la connexion recommandée et demander une nouvelle clé",
    testAgain: "Tester à nouveau",
    testCurrentConnection: "Tester la connexion actuelle",
    addApiKey: "Ajouter la clé API",
    addApiKeyDetail: "Ajouter une clé puis enregistrer",
    saveToApply: "Enregistrer pour appliquer",
    chat: "Chat",
    images: "Images",
    notTested: "Pas encore testé",
    connectionChecklist: "Vérification de connexion",
    connectionState: "État de la connexion",
    saveConnectionDetail: "Enregistrer la connexion",
    verifyConnectionDetail: "Vérifier la connexion",
    connectionFieldsAndKey: "Champs de connexion et clé",
    defaultEndpoint: "Point de terminaison par défaut",
    capabilitiesFromLiveTest: "Les capacités viennent uniquement du dernier test en direct — pas des valeurs par défaut du protocole.",
    finalCapabilities: "Capacités finales",
    contextWindow: "Fenêtre de contexte",
    maxOutput: "Sortie max",
    modelAndTestDetail: "Modèle et détails de test",
    useMiniMaxProfile: "Utiliser le modèle MiniMax",
    useMiniMaxProfileDetail: "Utilisez le modèle, puis ajoutez la clé API.",
    workspaceFile: "Fichier de l’espace de travail",
    clearDraft: "Effacer le brouillon",
    trainerRemembers: "Trainer retient",
    saveDefaults: "Enregistrer les valeurs",
    currentDefaultsPrefix: "Valeurs actuelles",
    defaultAttachmentsPrefix: "Pièces jointes par défaut",
    name: "Nom",
    project: "Projet",
    coachingMode: "Mode de coaching",
    rhythm: "Rythme",
    thisRound: "Ce tour",
    context: "Contexte",
    currentConnectionPrefix: "Connexion actuelle",
  },
  "de-DE": {
    notRecorded: "Nicht erfasst",
    saveDraft: "Entwurf speichern",
    chooseModel: "Modell auswählen",
    chooseModelDetail: "Wählen Sie eines aus der Liste unten",
    testDraftConnection: "Verbindungsentwurf testen",
    testDraftConnectionDetail: "Testet die aktuellen Angaben, ohne Änderungen zu speichern",
    useMiniMaxDefaults: "Empfohlene Standardwerte verwenden",
    useMiniMaxDefaultsDetail: "Zu den empfohlenen Standardwerten wechseln und erneut testen",
    reenterMiniMaxKey: "API-Schlüssel neu eingeben",
    reenterMiniMaxKeyDetail: "Die empfohlene Verbindung erneut anwenden und einen neuen Schlüssel anfordern",
    testAgain: "Erneut testen",
    testCurrentConnection: "Aktuelle Verbindung testen",
    addApiKey: "API-Schlüssel ergänzen",
    addApiKeyDetail: "Schlüssel ergänzen und dann speichern",
    saveToApply: "Speichern zum Anwenden",
    chat: "Chat",
    images: "Bilder",
    notTested: "Nicht getestet",
    connectionChecklist: "Verbindungscheck",
    connectionState: "Verbindungsstatus",
    saveConnectionDetail: "Verbindung speichern",
    verifyConnectionDetail: "Verbindung prüfen",
    connectionFieldsAndKey: "Verbindungsfelder und Schlüssel",
    defaultEndpoint: "Standard-Endpunkt",
    capabilitiesFromLiveTest: "Fähigkeiten kommen nur aus dem letzten Live-Test — nicht aus Protokoll-Standards.",
    finalCapabilities: "Endgültige Fähigkeiten",
    contextWindow: "Kontextfenster",
    maxOutput: "Max Ausgabe",
    modelAndTestDetail: "Modell- und Testdetails",
    useMiniMaxProfile: "MiniMax-Vorlage verwenden",
    useMiniMaxProfileDetail: "Vorlage nutzen, dann API-Schlüssel ergänzen.",
    workspaceFile: "Workspace-Datei",
    clearDraft: "Entwurf leeren",
    trainerRemembers: "Trainer merkt sich",
    saveDefaults: "Standards speichern",
    currentDefaultsPrefix: "Aktuelle Standards",
    defaultAttachmentsPrefix: "Standardanhänge",
    name: "Name",
    project: "Projekt",
    coachingMode: "Coach-Modus",
    rhythm: "Rhythmus",
    thisRound: "Diese Runde",
    context: "Kontext",
    currentConnectionPrefix: "Aktuelle Verbindung",
  },
  "ja-JP": {
    notRecorded: "記録なし",
    saveDraft: "下書きを保存",
    chooseModel: "モデルを選ぶ",
    chooseModelDetail: "下の一覧から1つ選んでください",
    testDraftConnection: "接続の下書きをテスト",
    testDraftConnectionDetail: "現在の入力だけをテストし、変更は保存しません",
    useMiniMaxDefaults: "推奨の既定値を使う",
    useMiniMaxDefaultsDetail: "推奨の既定値に戻して再テスト",
    reenterMiniMaxKey: "API キーを再入力",
    reenterMiniMaxKeyDetail: "推奨の接続を再適用し、新しいキーを求める",
    testAgain: "再テスト",
    testCurrentConnection: "現在の接続をテスト",
    addApiKey: "API キーを追加",
    addApiKeyDetail: "キーを追加してから保存",
    saveToApply: "保存して適用",
    chat: "対話",
    images: "画像",
    notTested: "未テスト",
    connectionChecklist: "接続チェック",
    connectionState: "接続状態",
    saveConnectionDetail: "接続を保存",
    verifyConnectionDetail: "接続を確認",
    connectionFieldsAndKey: "接続項目とキー",
    defaultEndpoint: "既定エンドポイント",
    capabilitiesFromLiveTest: "能力は直近のライブテストだけから。プロトコル既定値では表示しません。",
    finalCapabilities: "最終能力",
    contextWindow: "Context window",
    maxOutput: "Max output",
    modelAndTestDetail: "モデルとテスト詳細",
    useMiniMaxProfile: "MiniMax テンプレートを使う",
    useMiniMaxProfileDetail: "先にテンプレート、あとで API キー",
    workspaceFile: "ワークスペース設定",
    clearDraft: "下書きを消去",
    trainerRemembers: "Trainer が覚えていること",
    saveDefaults: "既定値を保存",
    currentDefaultsPrefix: "現在の既定値",
    defaultAttachmentsPrefix: "既定の添付",
    name: "名前",
    project: "プロジェクト",
    coachingMode: "コーチ方式",
    rhythm: "リズム",
    thisRound: "今回の重点",
    context: "背景",
    currentConnectionPrefix: "現在の接続",
  },
  "ko-KR": {
    notRecorded: "기록 없음",
    saveDraft: "초안 저장",
    chooseModel: "모델 선택",
    chooseModelDetail: "아래 목록에서 하나를 선택하세요",
    testDraftConnection: "연결 초안 테스트",
    testDraftConnectionDetail: "현재 입력만 테스트하며 변경 내용은 저장하지 않습니다",
    useMiniMaxDefaults: "권장 기본값 사용",
    useMiniMaxDefaultsDetail: "권장 기본값으로 되돌린 뒤 다시 테스트",
    reenterMiniMaxKey: "API 키 다시 입력",
    reenterMiniMaxKeyDetail: "권장 연결을 다시 적용하고 새 키를 요청",
    testAgain: "다시 테스트",
    testCurrentConnection: "현재 연결 테스트",
    addApiKey: "API 키 추가",
    addApiKeyDetail: "키를 추가한 뒤 저장",
    saveToApply: "저장 후 적용",
    chat: "대화",
    images: "이미지",
    notTested: "미테스트",
    connectionChecklist: "연결 점검",
    connectionState: "연결 상태",
    saveConnectionDetail: "연결 저장",
    verifyConnectionDetail: "연결 확인",
    connectionFieldsAndKey: "연결 필드와 키",
    defaultEndpoint: "기본 엔드포인트",
    capabilitiesFromLiveTest: "능력은 최근 라이브 테스트에서만 오며, 프로토콜 기본값으로 표시하지 않습니다.",
    finalCapabilities: "최종 능력",
    contextWindow: "Context window",
    maxOutput: "Max output",
    modelAndTestDetail: "모델 및 테스트 세부사항",
    useMiniMaxProfile: "MiniMax 템플릿 사용",
    useMiniMaxProfileDetail: "먼저 템플릿, 나중에 API 키",
    workspaceFile: "워크스페이스 파일",
    clearDraft: "초안 지우기",
    trainerRemembers: "Trainer가 기억함",
    saveDefaults: "기본값 저장",
    currentDefaultsPrefix: "현재 기본값",
    defaultAttachmentsPrefix: "기본 첨부",
    name: "이름",
    project: "프로젝트",
    coachingMode: "코칭 방식",
    rhythm: "리듬",
    thisRound: "이번 라운드",
    context: "맥락",
    currentConnectionPrefix: "현재 연결",
  },
  "pt-BR": {
    notRecorded: "Sem registro",
    saveDraft: "Salvar rascunho",
    chooseModel: "Escolher um modelo",
    chooseModelDetail: "Escolha um na lista abaixo",
    testDraftConnection: "Testar conexão em rascunho",
    testDraftConnectionDetail: "Testa os dados atuais sem salvar alterações",
    useMiniMaxDefaults: "Usar padrões recomendados",
    useMiniMaxDefaultsDetail: "Voltar aos padrões recomendados e testar de novo",
    reenterMiniMaxKey: "Inserir chave de API novamente",
    reenterMiniMaxKeyDetail: "Reaplicar a conexão recomendada e pedir uma nova chave",
    testAgain: "Testar de novo",
    testCurrentConnection: "Testar conexão atual",
    addApiKey: "Adicionar chave API",
    addApiKeyDetail: "Adicione a chave e depois salve",
    saveToApply: "Salvar para aplicar",
    chat: "Chat",
    images: "Imagens",
    notTested: "Não testado",
    connectionChecklist: "Checklist de conexão",
    connectionState: "Estado da conexão",
    saveConnectionDetail: "Salvar conexão",
    verifyConnectionDetail: "Verificar conexão",
    connectionFieldsAndKey: "Campos de conexão e chave",
    defaultEndpoint: "Endpoint padrão",
    capabilitiesFromLiveTest: "As capacidades vêm só do último teste ao vivo — não dos padrões do protocolo.",
    finalCapabilities: "Capacidades finais",
    contextWindow: "Janela de contexto",
    maxOutput: "Saída máxima",
    modelAndTestDetail: "Modelo e detalhe do teste",
    useMiniMaxProfile: "Usar modelo MiniMax",
    useMiniMaxProfileDetail: "Use o modelo e depois adicione a chave API.",
    workspaceFile: "Arquivo do workspace",
    clearDraft: "Limpar rascunho",
    trainerRemembers: "Trainer lembra",
    saveDefaults: "Salvar padrões",
    currentDefaultsPrefix: "Padrões atuais",
    defaultAttachmentsPrefix: "Anexos padrão",
    name: "Nome",
    project: "Projeto",
    coachingMode: "Modo de coaching",
    rhythm: "Ritmo",
    thisRound: "Esta rodada",
    context: "Contexto",
    currentConnectionPrefix: "Conexão atual",
  },
};

function settingsPhrase(language: ComposerLanguage, key: SettingsPhraseKey): string {
  return settingsPhraseTable[language][key] ?? settingsPhraseTable["en-US"][key];
}

type SettingsSupportPhraseKey = "protocol" | "connectionVerified" | "commonIntro";

const settingsSupportPhraseTable: Record<ComposerLanguage, Record<SettingsSupportPhraseKey, string>> = {
  "zh-CN": {
    protocol: "连接方式",
    connectionVerified: "连接、模型和访问密钥都已通过检查。",
    commonIntro: "连接与默认项。",
  },
  "en-US": {
    protocol: "Protocol",
    connectionVerified: "Connection, model, and API key all look usable.",
    commonIntro: "Only the most common coach settings here.",
  },
  "es-ES": {
    protocol: "Protocolo",
    connectionVerified: "La conexión, el modelo y la clave API ya se ven utilizables.",
    commonIntro: "Solo los ajustes más comunes aquí.",
  },
  "fr-FR": {
    protocol: "Protocole",
    connectionVerified: "La connexion, le modèle et la clé API semblent tous utilisables.",
    commonIntro: "Seuls les réglages du coach les plus courants apparaissent ici.",
  },
  "de-DE": {
    protocol: "Protokoll",
    connectionVerified: "Verbindung, Modell und API-Schlüssel wirken alle nutzbar.",
    commonIntro: "Hier erscheinen nur die häufigsten Coach-Einstellungen.",
  },
  "ja-JP": {
    protocol: "プロトコル",
    connectionVerified: "接続、モデル、API キーはすべて利用可能に見えます。",
    commonIntro: "ここにはよく使うコーチ設定だけを表示します。",
  },
  "ko-KR": {
    protocol: "프로토콜",
    connectionVerified: "연결, 모델, API 키가 모두 사용 가능한 상태로 보입니다.",
    commonIntro: "여기에는 자주 쓰는 코치 설정만 보여 줍니다.",
  },
  "pt-BR": {
    protocol: "Protocolo",
    connectionVerified: "Conexão, modelo e chave de API parecem utilizáveis.",
    commonIntro: "Só os ajustes de coach mais comuns aparecem aqui.",
  },
};

function settingsSupportPhrase(language: ComposerLanguage, key: SettingsSupportPhraseKey): string {
  return settingsSupportPhraseTable[language][key] ?? settingsSupportPhraseTable["en-US"][key];
}

type SettingsStatusPhraseKey =
  | "ready"
  | "unavailable"
  | "missingKey"
  | "needsAttention"
  | "setup"
  | "blocked"
  | "off"
  | "checking"
  | "refreshing"
  | "draftNotApplied"
  | "connectionDraftNotSaved"
  | "modelReady"
  | "apiKeyRequired"
  | "connectionNeedsTest"
  | "setupModelAccess"
  | "saveBeforeTesting"
  | "chatPlanTrainingUseThisConnection"
  | "connectionSavedApiKeyMissing"
  | "connectionSavedNeedsTest"
  | "fillProviderFields"
  | "sendEnabled"
  | "rereadSandboxBoundary"
  | "imageInputNotVerified"
  | "available";

const settingsStatusPhraseTable: Record<ComposerLanguage, Record<SettingsStatusPhraseKey, string>> = {
  "zh-CN": {
    ready: "已就绪",
    unavailable: "不可用",
    missingKey: "需要 API key",
    needsAttention: "需要检查",
    setup: "需要设置",
    blocked: "暂时不能用",
    off: "未开启",
    checking: "正在检查",
    refreshing: "正在刷新",
    draftNotApplied: "草稿还没生效",
    connectionDraftNotSaved: "这组连接还没保存",
    modelReady: "模型已就绪",
    apiKeyRequired: "需要 API key",
    connectionNeedsTest: "还没有验证",
    setupModelAccess: "设置模型连接",
    saveBeforeTesting: "先保存，再测试。",
    chatPlanTrainingUseThisConnection: "对话、计划和训练都会使用这组连接。",
    connectionSavedApiKeyMissing: "连接已保存，还需要 API key。",
    connectionSavedNeedsTest: "连接已保存，下一步请测试连接。",
    fillProviderFields: "填写连接信息和 API key 后即可测试。",
    sendEnabled: "可以发送",
    rereadSandboxBoundary: "重新确认可访问范围",
    imageInputNotVerified: "图片功能还没确认可用。",
    available: "可用",
  },
  "en-US": {
    ready: "Ready",
    unavailable: "Unavailable",
    missingKey: "Missing key",
    needsAttention: "Needs attention",
    setup: "Setup",
    blocked: "Blocked",
    off: "Off",
    checking: "Checking",
    refreshing: "Refreshing",
    draftNotApplied: "Draft not applied",
    connectionDraftNotSaved: "Connection draft not saved",
    modelReady: "Model ready",
    apiKeyRequired: "API key required",
    connectionNeedsTest: "Connection needs test",
    setupModelAccess: "Set up model access",
    saveBeforeTesting: "Save before testing.",
    chatPlanTrainingUseThisConnection: "Chat, plan, and training use this connection.",
    connectionSavedApiKeyMissing: "Connection saved; API key missing.",
    connectionSavedNeedsTest: "Connection saved; test still needs to pass.",
    fillProviderFields: "Fill provider, protocol, base URL, model, and API key.",
    sendEnabled: "Send enabled",
    rereadSandboxBoundary: "Re-read sandbox boundary",
    imageInputNotVerified: "Image input not verified.",
    available: "Available",
  },
  "es-ES": {
    ready: "Listo",
    unavailable: "No disponible",
    missingKey: "Falta clave",
    needsAttention: "Necesita atención",
    setup: "Configurar",
    blocked: "Bloqueado",
    off: "Desactivado",
    checking: "Comprobando",
    refreshing: "Actualizando",
    draftNotApplied: "Borrador sin aplicar",
    connectionDraftNotSaved: "Borrador de conexión sin guardar",
    modelReady: "Modelo listo",
    apiKeyRequired: "Se necesita clave API",
    connectionNeedsTest: "La conexión necesita prueba",
    setupModelAccess: "Configurar acceso al modelo",
    saveBeforeTesting: "Guarda antes de probar.",
    chatPlanTrainingUseThisConnection: "Chat, plan y entrenamiento usan esta conexión.",
    connectionSavedApiKeyMissing: "La conexión está guardada, pero falta la clave API.",
    connectionSavedNeedsTest: "La conexión está guardada, pero la prueba todavía debe pasar.",
    fillProviderFields: "Completa proveedor, protocolo, base URL, modelo y clave API.",
    sendEnabled: "Envío listo",
    rereadSandboxBoundary: "Volver a leer el límite del sandbox",
    imageInputNotVerified: "La entrada de imágenes todavía no está verificada.",
    available: "Disponible",
  },
  "fr-FR": {
    ready: "Prêt",
    unavailable: "Indisponible",
    missingKey: "Clé manquante",
    needsAttention: "À vérifier",
    setup: "Configurer",
    blocked: "Bloqué",
    off: "Désactivé",
    checking: "Vérification",
    refreshing: "Actualisation",
    draftNotApplied: "Brouillon non appliqué",
    connectionDraftNotSaved: "Brouillon de connexion non enregistré",
    modelReady: "Modèle prêt",
    apiKeyRequired: "Clé API requise",
    connectionNeedsTest: "Connexion à tester",
    setupModelAccess: "Configurer l'accès au modèle",
    saveBeforeTesting: "Enregistrez avant de tester.",
    chatPlanTrainingUseThisConnection: "Chat, plan et entraînement utilisent cette connexion.",
    connectionSavedApiKeyMissing: "Connexion enregistrée, mais clé API manquante.",
    connectionSavedNeedsTest: "Connexion enregistrée, mais le test doit encore réussir.",
    fillProviderFields: "Renseignez le fournisseur, le protocole, la base URL, le modèle et la clé API.",
    sendEnabled: "Envoi prêt",
    rereadSandboxBoundary: "Relire la limite du sandbox",
    imageInputNotVerified: "L'entrée image n'est pas encore vérifiée.",
    available: "Disponible",
  },
  "de-DE": {
    ready: "Bereit",
    unavailable: "Nicht verfügbar",
    missingKey: "Schlüssel fehlt",
    needsAttention: "Benötigt Prüfung",
    setup: "Einrichten",
    blocked: "Blockiert",
    off: "Aus",
    checking: "Wird geprüft",
    refreshing: "Wird aktualisiert",
    draftNotApplied: "Entwurf nicht angewendet",
    connectionDraftNotSaved: "Verbindungsentwurf nicht gespeichert",
    modelReady: "Modell bereit",
    apiKeyRequired: "API-Schlüssel erforderlich",
    connectionNeedsTest: "Verbindung muss getestet werden",
    setupModelAccess: "Modellzugang einrichten",
    saveBeforeTesting: "Vor dem Testen speichern.",
    chatPlanTrainingUseThisConnection: "Chat, Plan und Training verwenden diese Verbindung.",
    connectionSavedApiKeyMissing: "Verbindung gespeichert, aber API-Schlüssel fehlt.",
    connectionSavedNeedsTest: "Verbindung gespeichert, aber der Test muss noch bestehen.",
    fillProviderFields: "Anbieter, Protokoll, Base URL, Modell und API-Schlüssel ausfüllen.",
    sendEnabled: "Senden bereit",
    rereadSandboxBoundary: "Sandbox-Grenze neu einlesen",
    imageInputNotVerified: "Bildeingabe noch nicht verifiziert.",
    available: "Verfügbar",
  },
  "ja-JP": {
    ready: "準備完了",
    unavailable: "利用不可",
    missingKey: "キー不足",
    needsAttention: "確認が必要",
    setup: "設定",
    blocked: "ブロック中",
    off: "オフ",
    checking: "確認中",
    refreshing: "更新中",
    draftNotApplied: "下書き未反映",
    connectionDraftNotSaved: "接続の下書きが未保存",
    modelReady: "モデル準備完了",
    apiKeyRequired: "API キーが必要",
    connectionNeedsTest: "接続の確認が必要",
    setupModelAccess: "モデル接続を設定",
    saveBeforeTesting: "先に保存してからテストしてください。",
    chatPlanTrainingUseThisConnection: "対話、計画、訓練はこの接続を使います。",
    connectionSavedApiKeyMissing: "接続は保存されていますが、API キーがありません。",
    connectionSavedNeedsTest: "接続は保存されていますが、テストはまだ通っていません。",
    fillProviderFields: "provider、プロトコル、base URL、モデル、API キーを入力してください。",
    sendEnabled: "送信可能",
    rereadSandboxBoundary: "sandbox 境界を再読込",
    imageInputNotVerified: "画像入力はまだ未検証です。",
    available: "利用可能",
  },
  "ko-KR": {
    ready: "준비됨",
    unavailable: "사용 불가",
    missingKey: "키 없음",
    needsAttention: "확인 필요",
    setup: "설정",
    blocked: "차단됨",
    off: "꺼짐",
    checking: "확인 중",
    refreshing: "새로 고침 중",
    draftNotApplied: "초안 미적용",
    connectionDraftNotSaved: "연결 초안이 저장되지 않음",
    modelReady: "모델 준비됨",
    apiKeyRequired: "API 키 필요",
    connectionNeedsTest: "연결 테스트 필요",
    setupModelAccess: "모델 접근 설정",
    saveBeforeTesting: "먼저 저장한 뒤 테스트하세요.",
    chatPlanTrainingUseThisConnection: "대화, 계획, 훈련은 이 연결을 사용합니다.",
    connectionSavedApiKeyMissing: "연결은 저장됐지만 API 키가 없습니다.",
    connectionSavedNeedsTest: "연결은 저장됐지만 테스트를 아직 통과하지 못했습니다.",
    fillProviderFields: "provider, 프로토콜, base URL, 모델, API 키를 입력하세요.",
    sendEnabled: "전송 가능",
    rereadSandboxBoundary: "sandbox 경계 다시 읽기",
    imageInputNotVerified: "이미지 입력이 아직 검증되지 않았습니다.",
    available: "사용 가능",
  },
  "pt-BR": {
    ready: "Pronto",
    unavailable: "Indisponível",
    missingKey: "Chave ausente",
    needsAttention: "Precisa de atenção",
    setup: "Configurar",
    blocked: "Bloqueado",
    off: "Desligado",
    checking: "Verificando",
    refreshing: "Atualizando",
    draftNotApplied: "Rascunho não aplicado",
    connectionDraftNotSaved: "Rascunho de conexão não salvo",
    modelReady: "Modelo pronto",
    apiKeyRequired: "Chave de API obrigatória",
    connectionNeedsTest: "Conexão precisa de teste",
    setupModelAccess: "Configurar acesso ao modelo",
    saveBeforeTesting: "Salve antes de testar.",
    chatPlanTrainingUseThisConnection: "Chat, plano e treino usam esta conexão.",
    connectionSavedApiKeyMissing: "Conexão salva, mas falta a chave de API.",
    connectionSavedNeedsTest: "Conexão salva, mas o teste ainda precisa passar.",
    fillProviderFields: "Preencha provedor, protocolo, base URL, modelo e chave de API.",
    sendEnabled: "Envio pronto",
    rereadSandboxBoundary: "Reler limite do sandbox",
    imageInputNotVerified: "A entrada de imagem ainda não foi verificada.",
    available: "Disponível",
  },
};

function settingsStatusPhrase(language: ComposerLanguage, key: SettingsStatusPhraseKey): string {
  return settingsStatusPhraseTable[language][key] ?? settingsStatusPhraseTable["en-US"][key];
}

function ChoiceList<T extends string>({
  items,
  active,
  onChange,
}: {
  items: Array<{ label: string; value: T }>;
  active?: T;
  onChange?: (value: T) => void;
}) {
  return (
    <div className="settings-sheet__group">
      <div className="settings-sheet__choices">
        {items.map((item) => (
          <button
            key={item.value}
            className={`toolbar-button settings-sheet__choice-pill ${item.value === active ? "is-active" : ""}`}
            type="button"
            aria-pressed={item.value === active}
            onClick={() => onChange?.(item.value)}
          >
            <span>{item.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function SummaryCard({
  label,
  value,
  detail,
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
}) {
  return (
    <div className="settings-sheet__summary-card">
      <span className="settings-sheet__summary-card-label">{label}</span>
      <strong className="settings-sheet__summary-card-value">{value}</strong>
      {detail ? <p className="settings-sheet__note settings-sheet__note--compact">{detail}</p> : null}
    </div>
  );
}

function providerVerdictTone(
  tone: "pass" | "warn" | "fail",
): "connected" | "warn" | "offline" {
  if (tone === "pass") {
    return "connected";
  }
  if (tone === "warn") {
    return "warn";
  }
  return "offline";
}

function capabilityLabels(
  capabilities: CapabilityFlags | undefined,
  language: ComposerLanguage,
): string[] {
  const isZh = language === "zh-CN";
  const labels: string[] = [];

  if (capabilities?.chat) {
    labels.push(isZh ? "对话" : "Chat");
  }
  if (capabilities?.responses) {
    labels.push("Responses");
  }
  if (capabilities?.streaming) {
    labels.push(isZh ? "流式" : "Streaming");
  }
  if (capabilities?.tools) {
    labels.push(isZh ? "\u58f0\u660e\u5de5\u5177" : "Declared tools");
  }
  if (capabilities?.structuredOutput) {
    labels.push(isZh ? "结构化" : "Structured");
  }
  if (capabilities?.jsonSchema) {
    labels.push("JSON Schema");
  }
  if (capabilities?.vision) {
    labels.push("Vision");
  }
  if (capabilities?.embeddings) {
    labels.push("Embeddings");
  }

  return labels;
}

function capabilitySummaryText(
  capabilities: CapabilityFlags | undefined,
  language: ComposerLanguage,
): string {
  const labels = capabilityLabels(capabilities, language);
  if (labels.length === 0) {
    return language === "zh-CN" ? "未声明" : "Not declared";
  }
  return labels.join(" · ");
}

function SimpleInfoRow({
  label,
  value,
}: {
  label: string;
  value: ReactNode;
}) {
  return (
    <div className="settings-sheet__simple-row">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ContextList({
  rows,
  onLabel,
  offLabel,
}: {
  rows: Array<{ label: string; enabled: boolean; detail: string; onToggle: () => void }>;
  onLabel: string;
  offLabel: string;
}) {
  return (
    <div className="settings-sheet__workspace-list">
      {rows.map((row) => (
        <button
          key={row.label}
          className={`settings-sheet__workspace-list-item ${row.enabled ? "is-enabled" : ""}`}
          type="button"
          aria-pressed={row.enabled}
          onClick={row.onToggle}
        >
          <div className="settings-sheet__workspace-list-copy">
            <strong>{row.label}</strong>
            <span>{row.detail}</span>
          </div>
          <em>{row.enabled ? onLabel : offLabel}</em>
        </button>
      ))}
    </div>
  );
}

function stringifyNode(value: ReactNode): string | undefined {
  if (typeof value === "string" || typeof value === "number") {
    const text = `${value}`.trim();
    return text.length ? text : undefined;
  }
  return undefined;
}

function compactSummaryValue(rows: string[], fallback: string): string {
  const seen = new Set<string>();
  const normalizedRows = rows.filter((row) => {
    const key = row.trim().toLowerCase();
    if (!key || seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
  return normalizedRows.length > 0 ? normalizedRows.join(" · ") : fallback;
}

function shortenSummary(value: string, limit = 88): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= limit) {
    return normalized;
  }
  return `${normalized.slice(0, Math.max(0, limit - 1)).trimEnd()}…`;
}

function adaptiveBehaviorLabel(
  language: ComposerLanguage,
  kind: "both" | "answer" | "teaching",
): string {
  switch (language) {
    case "zh-CN":
      return kind === "both"
        ? "\u81EA\u9002\u5E94"
        : kind === "answer"
          ? "\u81EA\u9002\u5E94\u53CD\u9988"
          : "\u81EA\u9002\u5E94\u6559\u5B66";
    case "es-ES":
      return kind === "both"
        ? "Adaptativo"
        : kind === "answer"
          ? "Respuesta adaptativa"
          : "Ense\u00F1anza adaptativa";
    case "fr-FR":
      return kind === "both"
        ? "Adaptatif"
        : kind === "answer"
          ? "R\u00E9ponse adaptative"
          : "Enseignement adaptatif";
    case "de-DE":
      return kind === "both"
        ? "Adaptiv"
        : kind === "answer"
          ? "Adaptive Antwort"
          : "Adaptives Coaching";
    case "ja-JP":
      return kind === "both"
        ? "\u81EA\u52D5\u8ABF\u6574"
        : kind === "answer"
          ? "\u5FDC\u7B54\u3092\u81EA\u52D5\u8ABF\u6574"
          : "\u6559\u3048\u65B9\u3092\u81EA\u52D5\u8ABF\u6574";
    case "ko-KR":
      return kind === "both"
        ? "\uC790\uB3D9 \uC870\uC815"
        : kind === "answer"
          ? "\uC751\uB2F5 \uC790\uB3D9 \uC870\uC815"
          : "\uCF54\uCE6D \uBC29\uC2DD \uC790\uB3D9 \uC870\uC815";
    case "pt-BR":
      return kind === "both"
        ? "Adaptativo"
        : kind === "answer"
          ? "Resposta adaptativa"
          : "Ensino adaptativo";
    default:
      return kind === "both"
        ? "Adaptive"
        : kind === "answer"
          ? "Adaptive answer"
          : "Adaptive teaching";
  }
}

function formatTokenValue(value: number | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    return "-";
  }
  return new Intl.NumberFormat("en-US").format(Math.round(value));
}

function formatDurationSeconds(value: number | undefined): string | undefined {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    return undefined;
  }
  if (value % 86400 === 0) {
    return `${value / 86400}d`;
  }
  if (value % 3600 === 0) {
    return `${value / 3600}h`;
  }
  if (value % 60 === 0) {
    return `${value / 60}m`;
  }
  return `${value}s`;
}

function summarizeProviderRequestDefaults(value: unknown): string | undefined {
  const record = asRecord(value);
  if (!record) {
    return undefined;
  }

  const entries: string[] = [];
  const visit = (node: Record<string, unknown>, prefix = "") => {
    for (const [key, child] of Object.entries(node)) {
      if (entries.length >= 4) {
        return;
      }
      const nextKey = prefix ? `${prefix}.${key}` : key;
      if (Array.isArray(child)) {
        if (child.length > 0) {
          entries.push(`${nextKey}[]`);
        }
        continue;
      }
      if (child && typeof child === "object") {
        visit(child as Record<string, unknown>, nextKey);
        continue;
      }
      if (typeof child === "string" && child.trim()) {
        entries.push(`${nextKey}=${child.trim()}`);
        continue;
      }
      if (typeof child === "number" || typeof child === "boolean") {
        entries.push(`${nextKey}=${String(child)}`);
      }
    }
  };

  visit(record);
  return entries.length > 0 ? entries.join(" · ") : undefined;
}

function formatDraftStringList(value: string[] | undefined): string {
  return (value ?? []).join(", ");
}

function parseDraftStringList(value: string): string[] {
  const seen = new Set<string>();
  const normalized: string[] = [];
  for (const rawPart of value.split(/[\n,]+/g)) {
    const part = rawPart.trim();
    const key = part.toLowerCase();
    if (!part || seen.has(key)) {
      continue;
    }
    seen.add(key);
    normalized.push(part);
  }
  return normalized;
}

function mergeDraftStringList(...groups: Array<string[] | string | undefined>): string[] {
  const seen = new Set<string>();
  const normalized: string[] = [];

  for (const group of groups) {
    const values = Array.isArray(group) ? group : [group];
    for (const rawValue of values) {
      const value = typeof rawValue === "string" ? rawValue.trim() : "";
      const key = value.toLowerCase();
      if (!value || seen.has(key)) {
        continue;
      }
      seen.add(key);
      normalized.push(value);
    }
  }

  return normalized;
}

function stringArrayKey(value: string[] | undefined): string {
  return JSON.stringify(
    (value ?? [])
      .map((entry) => entry.trim())
      .filter(Boolean),
  );
}

function requestDefaultsKey(value: unknown): string {
  try {
    return JSON.stringify(asRecord(value) ?? {});
  } catch {
    return "{}";
  }
}

function formatRequestDefaultsDraft(value: unknown): string {
  return JSON.stringify(asRecord(value) ?? {}, null, 2);
}

function parsePositiveIntegerInput(value: string): number | undefined {
  const normalized = value.trim();
  const parsed = Number.parseInt(normalized, 10);
  return normalized.length > 0 && Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
}

function formatTimestamp(value: string | undefined, language: ComposerLanguage): string {
  if (!value) {
    return settingsPhrase(language, "notRecorded");
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat(language, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

type ToolsVerificationCopy = {
  label: string;
  declaredCapabilities: string;
  verified: string;
  notVerified: string;
  notSupported: string;
  needsVerification: string;
  verifiedDetail: string;
  unsupportedDetail: string;
  disabledDetail: string;
};

function toolsVerificationCopy(language: ComposerLanguage): ToolsVerificationCopy {
  const copies: Record<ComposerLanguage, ToolsVerificationCopy> = {
    "zh-CN": {
      label: "\u5de5\u5177",
      declaredCapabilities: "\u5df2\u58f0\u660e",
      verified: "\u5df2\u9a8c\u8bc1",
      notVerified: "\u672a\u9a8c\u8bc1",
      notSupported: "\u4e0d\u652f\u6301",
      needsVerification: "\u4fdd\u5b58\u6216\u91cd\u65b0\u6d4b\u8bd5\u5f53\u524d\u8fde\u63a5\uff0c\u624d\u80fd\u9a8c\u8bc1\u5de5\u5177\u8c03\u7528\u3002",
      verifiedDetail: "\u6700\u8fd1\u6d4b\u8bd5\u5df2\u89c2\u5bdf\u5230\u7ed3\u6784\u5316\u5de5\u5177\u8c03\u7528\u3002",
      unsupportedDetail: "\u6700\u8fd1\u6d4b\u8bd5\u89c2\u5bdf\u5230\u975e\u7ed3\u6784\u5316\u5907\u9009\u8f93\u51fa\u3002",
      disabledDetail: "\u5f53\u524d\u8fde\u63a5\u5df2\u7981\u7528\u5de5\u5177\u3002",
    },
    "en-US": {
      label: "Tools",
      declaredCapabilities: "Declared",
      verified: "Verified",
      notVerified: "Not verified",
      notSupported: "Not supported",
      needsVerification: "Save or retest this connection to verify tool use.",
      verifiedDetail: "The latest test observed a structured tool call.",
      unsupportedDetail: "The latest test observed a non-structured fallback instead.",
      disabledDetail: "Tool use is disabled for this connection.",
    },
    "es-ES": {
      label: "Herramientas",
      declaredCapabilities: "Declaradas",
      verified: "Verificado",
      notVerified: "Sin verificar",
      notSupported: "No compatible",
      needsVerification: "Guarda o vuelve a probar esta conexion para verificar el uso de herramientas.",
      verifiedDetail: "La ultima prueba observo una llamada de herramienta estructurada.",
      unsupportedDetail: "La ultima prueba observo una alternativa no estructurada.",
      disabledDetail: "El uso de herramientas esta desactivado en esta conexion.",
    },
    "fr-FR": {
      label: "Outils",
      declaredCapabilities: "Declarees",
      verified: "Verifie",
      notVerified: "Non verifie",
      notSupported: "Non pris en charge",
      needsVerification: "Enregistrez ou retestez cette connexion pour verifier les outils.",
      verifiedDetail: "Le dernier test a observe un appel d'outil structure.",
      unsupportedDetail: "Le dernier test a observe une reponse de secours non structuree.",
      disabledDetail: "Les outils sont desactives pour cette connexion.",
    },
    "de-DE": {
      label: "Werkzeuge",
      declaredCapabilities: "Deklariert",
      verified: "Verifiziert",
      notVerified: "Nicht verifiziert",
      notSupported: "Nicht unterstuetzt",
      needsVerification: "Speichere oder teste diese Verbindung erneut, um Werkzeuge zu verifizieren.",
      verifiedDetail: "Der letzte Test hat einen strukturierten Werkzeugaufruf beobachtet.",
      unsupportedDetail: "Der letzte Test hat stattdessen eine unstrukturierte Ausweichantwort beobachtet.",
      disabledDetail: "Werkzeugnutzung ist fuer diese Verbindung deaktiviert.",
    },
    "ja-JP": {
      label: "ツール",
      declaredCapabilities: "宣言済み",
      verified: "検証済み",
      notVerified: "未検証",
      notSupported: "非対応",
      needsVerification: "この接続を保存または再テストして、ツール使用を検証してください。",
      verifiedDetail: "最新のテストで構造化ツール呼び出しを観測しました。",
      unsupportedDetail: "最新のテストでは構造化されていない代替応答が観測されました。",
      disabledDetail: "この接続ではツール使用が無効です。",
    },
    "ko-KR": {
      label: "도구",
      declaredCapabilities: "선언됨",
      verified: "검증됨",
      notVerified: "검증되지 않음",
      notSupported: "지원되지 않음",
      needsVerification: "이 연결을 저장하거나 다시 테스트해 도구 사용을 검증하세요.",
      verifiedDetail: "최근 테스트에서 구조화된 도구 호출을 관찰했습니다.",
      unsupportedDetail: "최근 테스트에서 구조화되지 않은 대체 응답을 관찰했습니다.",
      disabledDetail: "이 연결에서는 도구 사용이 비활성화되어 있습니다.",
    },
    "pt-BR": {
      label: "Ferramentas",
      declaredCapabilities: "Declaradas",
      verified: "Verificado",
      notVerified: "Nao verificado",
      notSupported: "Nao compativel",
      needsVerification: "Salve ou teste esta conexao novamente para verificar o uso de ferramentas.",
      verifiedDetail: "O ultimo teste observou uma chamada de ferramenta estruturada.",
      unsupportedDetail: "O ultimo teste observou uma alternativa nao estruturada.",
      disabledDetail: "O uso de ferramentas esta desativado nesta conexao.",
    },
  };
  return copies[language] ?? copies["en-US"];
}

function describeToolsVerificationFact(input: {
  language: ComposerLanguage;
  configured: boolean;
  draftChanged: boolean;
  testReady: boolean;
  lastTest: ProviderConfigView["lastTestResult"] | undefined;
}): {
  value: string;
  tone: "connected" | "pending" | "warn" | "offline";
  detail: string;
} {
  const { language, configured, draftChanged, testReady, lastTest } = input;
  const copy = toolsVerificationCopy(language);

  if (draftChanged) {
    return {
      value: copy.notVerified,
      tone: "pending",
      detail: copy.needsVerification,
    };
  }

  if (!configured) {
    return {
      value: copy.notVerified,
      tone: "offline",
      detail: copy.needsVerification,
    };
  }

  if (!lastTest || !testReady || lastTest.ok !== true || (lastTest.protocol && !settingsProtocolIsKnown(lastTest.protocol))) {
    return {
      value: copy.notVerified,
      tone: "pending",
      detail: copy.needsVerification,
    };
  }

  const toolsEvidence = lastTest.capabilityEvidence?.find(
    (entry) => entry.name.trim().toLowerCase() === "tools",
  );
  const toolsVerified =
    lastTest.toolsReady === true &&
    lastTest.toolProbeStatus === "verified" &&
    toolsEvidence?.state === "verified" &&
    toolsEvidence.observed === true;

  if (toolsVerified) {
    return {
      value: copy.verified,
      tone: "connected",
      detail: copy.verifiedDetail,
    };
  }

  if (toolsEvidence?.state === "unsupported" && toolsEvidence.observed === false) {
    return {
      value: copy.notSupported,
      tone: "warn",
      detail: copy.unsupportedDetail,
    };
  }

  if (toolsEvidence?.state === "disabled") {
    return {
      value: copy.notVerified,
      tone: "pending",
      detail: copy.disabledDetail,
    };
  }

  return {
    value: copy.notVerified,
    tone: "pending",
    detail: copy.needsVerification,
  };
}

function streamingVerificationCopy(language: ComposerLanguage): ToolsVerificationCopy {
  const copies: Record<ComposerLanguage, ToolsVerificationCopy> = {
    "zh-CN": {
      label: "\u6d41\u5f0f",
      declaredCapabilities: "\u5df2\u58f0\u660e",
      verified: "\u5df2\u9a8c\u8bc1",
      notVerified: "\u672a\u9a8c\u8bc1",
      notSupported: "\u4e0d\u652f\u6301",
      needsVerification: "\u4fdd\u5b58\u6216\u91cd\u65b0\u6d4b\u8bd5\u5f53\u524d\u8fde\u63a5\uff0c\u624d\u80fd\u9a8c\u8bc1\u6d41\u5f0f\u8f93\u51fa\u3002",
      verifiedDetail: "\u6700\u8fd1\u6d4b\u8bd5\u5df2\u89c2\u5bdf\u5230\u53ef\u89c1\u7684\u589e\u91cf\u6d41\u5f0f\u7247\u6bb5\u3002",
      unsupportedDetail: "\u6700\u8fd1\u6d4b\u8bd5\u672a\u89c2\u5bdf\u5230\u53ef\u7528\u7684\u6d41\u5f0f\u7247\u6bb5\u3002",
      disabledDetail: "\u5f53\u524d\u8fde\u63a5\u5df2\u7981\u7528\u6d41\u5f0f\u8f93\u51fa\u3002",
    },
    "en-US": {
      label: "Streaming",
      declaredCapabilities: "Declared",
      verified: "Verified",
      notVerified: "Not verified",
      notSupported: "Not supported",
      needsVerification: "Save or retest this connection to verify incremental output.",
      verifiedDetail: "The latest test observed a visible incremental provider chunk.",
      unsupportedDetail: "The latest test did not observe usable incremental output.",
      disabledDetail: "Streaming output is disabled for this connection.",
    },
    "es-ES": {
      label: "Streaming",
      declaredCapabilities: "Declaradas",
      verified: "Verificado",
      notVerified: "Sin verificar",
      notSupported: "No compatible",
      needsVerification: "Guarda o vuelve a probar esta conexion para verificar la salida incremental.",
      verifiedDetail: "La ultima prueba observo un fragmento incremental visible.",
      unsupportedDetail: "La ultima prueba no observo una salida incremental utilizable.",
      disabledDetail: "La salida incremental esta desactivada para esta conexion.",
    },
    "fr-FR": {
      label: "Streaming",
      declaredCapabilities: "Declarees",
      verified: "Verifie",
      notVerified: "Non verifie",
      notSupported: "Non pris en charge",
      needsVerification: "Enregistrez ou retestez cette connexion pour verifier la sortie incrementale.",
      verifiedDetail: "Le dernier test a observe un fragment incremental visible.",
      unsupportedDetail: "Le dernier test n'a pas observe de sortie incrementale utilisable.",
      disabledDetail: "La sortie incrementale est desactivee pour cette connexion.",
    },
    "de-DE": {
      label: "Streaming",
      declaredCapabilities: "Deklariert",
      verified: "Verifiziert",
      notVerified: "Nicht verifiziert",
      notSupported: "Nicht unterstuetzt",
      needsVerification: "Speichere oder teste diese Verbindung erneut, um inkrementelle Ausgabe zu verifizieren.",
      verifiedDetail: "Der letzte Test hat einen sichtbaren inkrementellen Abschnitt beobachtet.",
      unsupportedDetail: "Der letzte Test hat keine nutzbare inkrementelle Ausgabe beobachtet.",
      disabledDetail: "Inkrementelle Ausgabe ist fuer diese Verbindung deaktiviert.",
    },
    "ja-JP": {
      label: "\u30b9\u30c8\u30ea\u30fc\u30df\u30f3\u30b0",
      declaredCapabilities: "\u5ba3\u8a00\u6e08\u307f",
      verified: "\u78ba\u8a8d\u6e08\u307f",
      notVerified: "\u672a\u78ba\u8a8d",
      notSupported: "\u975e\u5bfe\u5fdc",
      needsVerification: "\u3053\u306e\u63a5\u7d9a\u3092\u4fdd\u5b58\u307e\u305f\u306f\u518d\u30c6\u30b9\u30c8\u3057\u3001\u5897\u5206\u51fa\u529b\u3092\u78ba\u8a8d\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
      verifiedDetail: "\u6700\u65b0\u30c6\u30b9\u30c8\u3067\u53ef\u8996\u306e\u5897\u5206\u30c1\u30e3\u30f3\u30af\u3092\u78ba\u8a8d\u3057\u307e\u3057\u305f\u3002",
      unsupportedDetail: "\u6700\u65b0\u30c6\u30b9\u30c8\u3067\u5229\u7528\u53ef\u80fd\u306a\u5897\u5206\u51fa\u529b\u3092\u78ba\u8a8d\u3067\u304d\u307e\u305b\u3093\u3067\u3057\u305f\u3002",
      disabledDetail: "\u3053\u306e\u63a5\u7d9a\u3067\u306f\u30b9\u30c8\u30ea\u30fc\u30df\u30f3\u30b0\u304c\u7121\u52b9\u3067\u3059\u3002",
    },
    "ko-KR": {
      label: "\uc2a4\ud2b8\ub9ac\ubc0d",
      declaredCapabilities: "\uc120\uc5b8\ub428",
      verified: "\uac80\uc99d\ub428",
      notVerified: "\ubbf8\uac80\uc99d",
      notSupported: "\uc9c0\uc6d0\ub418\uc9c0 \uc54a\uc74c",
      needsVerification: "\uc774 \uc5f0\uacb0\uc744 \uc800\uc7a5\ud558\uac70\ub098 \ub2e4\uc2dc \ud14c\uc2a4\ud2b8\ud574 \uc99d\ubd84 \ucd9c\ub825\uc744 \uac80\uc99d\ud558\uc138\uc694.",
      verifiedDetail: "\ucd5c\uc2e0 \ud14c\uc2a4\ud2b8\uc5d0\uc11c \ud45c\uc2dc\ub418\ub294 \uc99d\ubd84 \ucc38\uc870\ub97c \uad00\ucc30\ud588\uc2b5\ub2c8\ub2e4.",
      unsupportedDetail: "\ucd5c\uc2e0 \ud14c\uc2a4\ud2b8\uc5d0\uc11c \uc0ac\uc6a9 \uac00\ub2a5\ud55c \uc99d\ubd84 \ucd9c\ub825\uc744 \uad00\ucc30\ud558\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4.",
      disabledDetail: "\uc774 \uc5f0\uacb0\uc5d0\uc11c \uc2a4\ud2b8\ub9ac\ubc0d \ucd9c\ub825\uc774 \ube44\ud65c\uc131\ud654\ub418\uc5c8\uc2b5\ub2c8\ub2e4.",
    },
    "pt-BR": {
      label: "Streaming",
      declaredCapabilities: "Declaradas",
      verified: "Verificado",
      notVerified: "Nao verificado",
      notSupported: "Nao compativel",
      needsVerification: "Salve ou teste esta conexao novamente para verificar a saida incremental.",
      verifiedDetail: "O ultimo teste observou um fragmento incremental visivel.",
      unsupportedDetail: "O ultimo teste nao observou uma saida incremental utilizavel.",
      disabledDetail: "A saida incremental esta desativada nesta conexao.",
    },
  };
  return copies[language] ?? copies["en-US"];
}

function describeStreamingVerificationFact(input: {
  language: ComposerLanguage;
  configured: boolean;
  draftChanged: boolean;
  testReady: boolean;
  lastTest: ProviderConfigView["lastTestResult"] | undefined;
}): {
  value: string;
  tone: "connected" | "pending" | "warn" | "offline";
  detail: string;
} {
  const { language, configured, draftChanged, testReady, lastTest } = input;
  const copy = streamingVerificationCopy(language);

  if (draftChanged || !configured || !lastTest || !testReady || lastTest.ok !== true || (lastTest.protocol && !settingsProtocolIsKnown(lastTest.protocol))) {
    return {
      value: copy.notVerified,
      tone: draftChanged || configured ? "pending" : "offline",
      detail: copy.needsVerification,
    };
  }

  const streamingEvidence = lastTest.capabilityEvidence?.find((entry) => {
    const name = entry.name.trim().toLowerCase();
    return name === "streaming" || name === "stream";
  });
  const streamingVerified = streamingProbeIsVerified(lastTest);

  if (streamingVerified) {
    return {
      value: copy.verified,
      tone: "connected",
      detail: copy.verifiedDetail,
    };
  }

  if (streamingEvidence?.state === "unsupported" && streamingEvidence.observed === false) {
    return {
      value: copy.notSupported,
      tone: "warn",
      detail: copy.unsupportedDetail,
    };
  }

  if (streamingEvidence?.state === "disabled") {
    return {
      value: copy.notVerified,
      tone: "pending",
      detail: copy.disabledDetail,
    };
  }

  return {
    value: copy.notVerified,
    tone: "pending",
    detail: copy.needsVerification,
  };
}

function streamingProbeIsVerified(
  lastTest: ProviderConfigView["lastTestResult"] | undefined,
): boolean {
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

function thinkingVerificationCopy(language: ComposerLanguage): {
  label: string;
  verified: string;
  notVerified: string;
  needsVerification: string;
  verifiedDetail: string;
  disabledDetail: string;
} {
  if (language === "zh-CN") {
    return {
      label: "思考",
      verified: "已验证",
      notVerified: "未验证",
      needsVerification: "先测试连接。MiniMax 只用 extra_body.thinking，未验证前不会发送 enabled。",
      verifiedDetail: "最近一次测试观察到了原生思考字段。",
      disabledDetail: "当前请求会发送 thinking.type=disabled，避免短回复被思考占满。",
    };
  }
  return {
    label: "Thinking",
    verified: "Verified",
    notVerified: "Not verified",
    needsVerification: "Test this connection first. MiniMax uses extra_body.thinking; enabled is not sent without live evidence.",
    verifiedDetail: "The last test observed the native thinking field.",
    disabledDetail: "Requests currently send thinking.type=disabled so short replies are not consumed by hidden thought.",
  };
}

function describeThinkingVerificationFact(input: {
  language: ComposerLanguage;
  configured: boolean;
  draftChanged: boolean;
  testReady: boolean;
  lastTest: ProviderConfigView["lastTestResult"] | undefined;
  minimax: boolean;
}): {
  value: string;
  tone: "connected" | "pending" | "warn" | "offline";
  detail: string;
} {
  const copy = thinkingVerificationCopy(input.language);
  if (input.draftChanged || !input.configured || !input.lastTest || !input.testReady || input.lastTest.ok !== true || (input.lastTest.protocol && !settingsProtocolIsKnown(input.lastTest.protocol))) {
    return {
      value: copy.notVerified,
      tone: input.draftChanged || input.configured ? "pending" : "offline",
      detail: copy.needsVerification,
    };
  }
  const thinkingEvidence = input.lastTest.capabilityEvidence?.find(
    (entry) => entry.name.trim().toLowerCase() === "thinking",
  );
  if (
    input.lastTest.thinkingReady === true &&
    input.lastTest.thinkingProbeStatus === "verified" &&
    thinkingEvidence?.state === "verified" &&
    thinkingEvidence.observed === true
  ) {
    return { value: copy.verified, tone: "connected", detail: copy.verifiedDetail };
  }
  if (input.minimax) {
    return { value: copy.notVerified, tone: "pending", detail: copy.disabledDetail };
  }
  return { value: copy.notVerified, tone: "pending", detail: copy.needsVerification };
}

function visionVerificationCopy(language: ComposerLanguage): {
  label: string;
  verified: string;
  notVerified: string;
  notSupported: string;
  needsVerification: string;
  verifiedDetail: string;
  unsupportedDetail: string;
} {
  if (language === "zh-CN") {
    return {
      label: "视觉",
      verified: "已验证",
      notVerified: "未验证",
      notSupported: "不支持",
      needsVerification: "先测试连接。声明或默认能力不会让视觉显示为就绪。",
      verifiedDetail: "最近一次测试观察到了可用的视觉输入。",
      unsupportedDetail: "最近一次测试没有观察到可用的视觉输入。",
    };
  }
  return {
    label: "Vision",
    verified: "Verified",
    notVerified: "Not verified",
    notSupported: "Not supported",
    needsVerification: "Test this connection first. Declared or default capabilities do not make vision ready.",
    verifiedDetail: "The latest test observed usable vision input.",
    unsupportedDetail: "The latest test did not observe usable vision input.",
  };
}

function describeVisionVerificationFact(input: {
  language: ComposerLanguage;
  configured: boolean;
  draftChanged: boolean;
  testReady: boolean;
  lastTest: ProviderConfigView["lastTestResult"] | undefined;
}): {
  value: string;
  tone: "connected" | "pending" | "warn" | "offline";
  detail: string;
} {
  const copy = visionVerificationCopy(input.language);
  if (input.draftChanged || !input.configured || !input.lastTest || !input.testReady || input.lastTest.ok !== true || (input.lastTest.protocol && !settingsProtocolIsKnown(input.lastTest.protocol))) {
    return {
      value: copy.notVerified,
      tone: input.draftChanged || input.configured ? "pending" : "offline",
      detail: copy.needsVerification,
    };
  }
  const visionEvidence = input.lastTest.capabilityEvidence?.find(
    (entry) => entry.name.trim().toLowerCase() === "vision",
  );
  if (
    input.lastTest.visionReady === true &&
    input.lastTest.visionProbeStatus === "verified" &&
    visionEvidence?.state === "verified" &&
    visionEvidence.observed === true
  ) {
    return { value: copy.verified, tone: "connected", detail: copy.verifiedDetail };
  }
  if (visionEvidence?.state === "unsupported" && visionEvidence.observed === false) {
    return { value: copy.notSupported, tone: "warn", detail: copy.unsupportedDetail };
  }
  return { value: copy.notVerified, tone: "pending", detail: copy.needsVerification };
}

function gatewayFingerprintNote(
  diagnostics: string[] | undefined,
  language: ComposerLanguage,
  connectionType?: string,
): string | undefined {
  const matched = diagnostics?.find((item) => /newapi_channel_conn|New API/i.test(item));
  if (!matched && !isNewApiConnectionType(connectionType)) {
    return undefined;
  }
  return language === "zh-CN"
    ? "已识别 New API 网关。目录里的 endpoint 类型只是声明，要以测试结果为准。"
    : "New API gateway identified. Catalog endpoint types are claims; use the live test.";
}

function saveStateTone(saveState: SaveState): "connected" | "pending" | "offline" {
  if (saveState === "saved") {
    return "connected";
  }
  if (saveState === "unsaved") {
    return "pending";
  }
  return "offline";
}

function saveStateLabel(copy: CoachSettingsLabels, saveState: SaveState): string {
  if (saveState === "saved") {
    return copy.savedState;
  }
  if (saveState === "unsaved") {
    return copy.unsavedState;
  }
  return copy.emptyState;
}

function protocolChoiceLabel(protocol: ProviderProtocol | undefined, language: ComposerLanguage): string {
  if (!protocol) {
    return language === "zh-CN" ? "未选择协议" : "Protocol unverified";
  }
  if (language === "zh-CN") {
    switch (protocol) {
      case "openai_responses":
        return "OpenAI 响应";
      case "openai_chat_completions":
        return "OpenAI 聊天";
      case "anthropic_messages":
        return "Anthropic";
      case "openai_chat_completions_compatible":
        return "OpenAI 兼容";
      case "gemini_generate_content":
        return "Gemini";
    }
  }

  switch (protocol) {
    case "openai_responses":
      return "OpenAI Responses";
    case "openai_chat_completions":
      return "OpenAI Chat";
    case "anthropic_messages":
      return "Anthropic";
    case "openai_chat_completions_compatible":
      return "OpenAI Compat";
    case "gemini_generate_content":
      return "Gemini";
  }

  return providerProtocolCompletionLabel(protocol);
}

function providerFailureCopy(
  category: string | undefined,
  language: ComposerLanguage,
): { statusLabel: string; headline: string } {
  const localized = (
    values: Record<ComposerLanguage, { statusLabel: string; headline: string }>,
  ): { statusLabel: string; headline: string } => values[language] ?? values["en-US"];

  switch (category) {
    case "test_failed":
      return localized({
        "zh-CN": { statusLabel: "\u6d4b\u8bd5\u5931\u8d25", headline: "\u8fde\u63a5\u6d4b\u8bd5\u5931\u8d25" },
        "en-US": { statusLabel: "Test failed", headline: "Connection test failed" },
        "es-ES": { statusLabel: "Prueba fallida", headline: "Falló la prueba de conexión" },
        "fr-FR": { statusLabel: "Test échoué", headline: "Le test de connexion a échoué" },
        "de-DE": { statusLabel: "Test fehlgeschlagen", headline: "Verbindungstest fehlgeschlagen" },
        "ja-JP": { statusLabel: "\u30c6\u30b9\u30c8\u5931\u6557", headline: "\u63a5\u7d9a\u30c6\u30b9\u30c8\u306b\u5931\u6557\u3057\u307e\u3057\u305f" },
        "ko-KR": { statusLabel: "\ud14c\uc2a4\ud2b8 \uc2e4\ud328", headline: "\uc5f0\uacb0 \ud14c\uc2a4\ud2b8\uac00 \uc2e4\ud328\ud588\uc2b5\ub2c8\ub2e4" },
        "pt-BR": { statusLabel: "Teste falhou", headline: "O teste de conexão falhou" },
      });
    case "invalid_key_or_permission":
    case "invalid_api_key":
    case "authentication_failed":
      return localized({
        "zh-CN": { statusLabel: "密钥被拒", headline: "API key 被拒绝" },
        "en-US": { statusLabel: "Key rejected", headline: "API key rejected" },
        "es-ES": { statusLabel: "Clave rechazada", headline: "La clave API fue rechazada" },
        "fr-FR": { statusLabel: "Clé refusée", headline: "La clé API a été refusée" },
        "de-DE": { statusLabel: "Schlüssel abgelehnt", headline: "API-Schlüssel wurde abgelehnt" },
        "ja-JP": { statusLabel: "キー拒否", headline: "API キーが拒否されました" },
        "ko-KR": { statusLabel: "키 거부", headline: "API 키가 거부되었습니다" },
        "pt-BR": { statusLabel: "Chave rejeitada", headline: "A chave de API foi rejeitada" },
      });
    case "model_unsupported":
    case "model_not_supported":
      return localized({
        "zh-CN": { statusLabel: "模型被拒", headline: "模型名不被接受" },
        "en-US": { statusLabel: "Model rejected", headline: "Model name rejected" },
        "es-ES": { statusLabel: "Modelo rechazado", headline: "El nombre del modelo fue rechazado" },
        "fr-FR": { statusLabel: "Modèle refusé", headline: "Le nom du modèle a été refusé" },
        "de-DE": { statusLabel: "Modell abgelehnt", headline: "Modellname wurde abgelehnt" },
        "ja-JP": { statusLabel: "モデル拒否", headline: "モデル名が受け付けられませんでした" },
        "ko-KR": { statusLabel: "모델 거부", headline: "모델 이름이 거부되었습니다" },
        "pt-BR": { statusLabel: "Modelo rejeitado", headline: "O nome do modelo foi rejeitado" },
      });
    case "model_not_found":
      return localized({
        "zh-CN": { statusLabel: "模型未就位", headline: "目标模型当前不可用" },
        "en-US": { statusLabel: "Model unavailable", headline: "Model is unavailable right now" },
        "es-ES": { statusLabel: "Modelo no disponible", headline: "El modelo no está disponible ahora mismo" },
        "fr-FR": { statusLabel: "Modèle indisponible", headline: "Le modèle est indisponible pour le moment" },
        "de-DE": { statusLabel: "Modell nicht verfügbar", headline: "Das Modell ist derzeit nicht verfügbar" },
        "ja-JP": { statusLabel: "モデル利用不可", headline: "このモデルは現在利用できません" },
        "ko-KR": { statusLabel: "모델 사용 불가", headline: "지금은 이 모델을 사용할 수 없습니다" },
        "pt-BR": { statusLabel: "Modelo indisponível", headline: "O modelo não está disponível agora" },
      });
    case "malformed_response":
      return localized({
        "zh-CN": { statusLabel: "暂时无法使用", headline: "请重试，仍失败可换一个模型" },
        "en-US": { statusLabel: "Reply unavailable", headline: "Try again, or choose another model" },
        "es-ES": { statusLabel: "Respuesta no disponible", headline: "Inténtalo de nuevo o elige otro modelo" },
        "fr-FR": { statusLabel: "Réponse indisponible", headline: "Réessayez ou choisissez un autre modèle" },
        "de-DE": { statusLabel: "Antwort nicht verfügbar", headline: "Erneut versuchen oder anderes Modell wählen" },
        "ja-JP": { statusLabel: "回答を利用できません", headline: "もう一度試すか、別のモデルを選んでください" },
        "ko-KR": { statusLabel: "응답을 사용할 수 없음", headline: "다시 시도하거나 다른 모델을 선택하세요" },
        "pt-BR": { statusLabel: "Resposta indisponível", headline: "Tente novamente ou escolha outro modelo" },
      });
    case "sidecar_unavailable":
      return localized({
        "zh-CN": { statusLabel: "正在准备", headline: "Trainer 正在启动，请稍后重试" },
        "en-US": { statusLabel: "Getting ready", headline: "Trainer is starting. Try again shortly" },
        "es-ES": { statusLabel: "Preparando", headline: "Trainer se está iniciando. Inténtalo de nuevo en un momento" },
        "fr-FR": { statusLabel: "Préparation", headline: "Trainer démarre. Réessayez dans un instant" },
        "de-DE": { statusLabel: "Wird vorbereitet", headline: "Trainer startet. Bitte gleich noch einmal versuchen" },
        "ja-JP": { statusLabel: "準備中", headline: "Trainer を起動しています。少し待って再試行してください" },
        "ko-KR": { statusLabel: "준비 중", headline: "Trainer를 시작하고 있습니다. 잠시 후 다시 시도하세요" },
        "pt-BR": { statusLabel: "Preparando", headline: "O Trainer está iniciando. Tente novamente em instantes" },
      });
    case "workspace_trust":
      return localized({
        "zh-CN": { statusLabel: "需要确认", headline: "请在 VS Code 中信任此文件夹后重试" },
        "en-US": { statusLabel: "Action needed", headline: "Trust this folder in VS Code, then try again" },
        "es-ES": { statusLabel: "Se requiere acción", headline: "Confía en esta carpeta en VS Code y vuelve a intentarlo" },
        "fr-FR": { statusLabel: "Action requise", headline: "Faites confiance à ce dossier dans VS Code, puis réessayez" },
        "de-DE": { statusLabel: "Aktion nötig", headline: "Vertrauen Sie diesem Ordner in VS Code und versuchen Sie es erneut" },
        "ja-JP": { statusLabel: "確認が必要", headline: "VS Code でこのフォルダーを信頼してから、もう一度試してください" },
        "ko-KR": { statusLabel: "확인이 필요함", headline: "VS Code에서 이 폴더를 신뢰한 뒤 다시 시도하세요" },
        "pt-BR": { statusLabel: "Ação necessária", headline: "Confie nesta pasta no VS Code e tente novamente" },
      });
    case "network":
    case "network_error":
      return localized({
        "zh-CN": { statusLabel: "无法连接", headline: "请检查网络后重试" },
        "en-US": { statusLabel: "Can't connect", headline: "Check your connection, then try again" },
        "es-ES": { statusLabel: "No se puede conectar", headline: "Revisa tu conexión y vuelve a intentarlo" },
        "fr-FR": { statusLabel: "Connexion impossible", headline: "Vérifiez votre connexion, puis réessayez" },
        "de-DE": { statusLabel: "Keine Verbindung", headline: "Verbindung prüfen und erneut versuchen" },
        "ja-JP": { statusLabel: "接続できません", headline: "接続を確認してから、もう一度試してください" },
        "ko-KR": { statusLabel: "연결할 수 없음", headline: "연결을 확인한 뒤 다시 시도하세요" },
        "pt-BR": { statusLabel: "Não foi possível conectar", headline: "Verifique a conexão e tente novamente" },
      });
    case "timeout":
      return localized({
        "zh-CN": { statusLabel: "等待超时", headline: "请稍后重试" },
        "en-US": { statusLabel: "Took too long", headline: "Try again in a moment" },
        "es-ES": { statusLabel: "Tardó demasiado", headline: "Vuelve a intentarlo en un momento" },
        "fr-FR": { statusLabel: "Trop long", headline: "Réessayez dans un instant" },
        "de-DE": { statusLabel: "Dauert zu lange", headline: "Bitte gleich noch einmal versuchen" },
        "ja-JP": { statusLabel: "時間がかかりすぎています", headline: "少し待って再試行してください" },
        "ko-KR": { statusLabel: "시간이 너무 오래 걸림", headline: "잠시 후 다시 시도하세요" },
        "pt-BR": { statusLabel: "Demorou demais", headline: "Tente novamente em instantes" },
      });
    case "rate_limit":
      return localized({
        "zh-CN": { statusLabel: "请稍后再试", headline: "现在请求太多，请稍后重试" },
        "en-US": { statusLabel: "Please wait", headline: "It is busy right now. Try again shortly" },
        "es-ES": { statusLabel: "Espera un momento", headline: "Hay mucha actividad. Inténtalo de nuevo en breve" },
        "fr-FR": { statusLabel: "Patientez un instant", headline: "Il y a beaucoup d’activité. Réessayez bientôt" },
        "de-DE": { statusLabel: "Bitte kurz warten", headline: "Gerade ist viel los. Bitte gleich erneut versuchen" },
        "ja-JP": { statusLabel: "しばらくお待ちください", headline: "ただいま混み合っています。少し待って再試行してください" },
        "ko-KR": { statusLabel: "잠시 기다려 주세요", headline: "현재 사용량이 많습니다. 잠시 후 다시 시도하세요" },
        "pt-BR": { statusLabel: "Aguarde um momento", headline: "Há muito movimento agora. Tente novamente em instantes" },
      });
    case "language_probe_inconclusive":
      return localized({
        "zh-CN": { statusLabel: "\u4ecd\u5f85\u9a8c\u8bc1", headline: "zh-CN \u5b8c\u6574\u6027\u4ecd\u5f85\u9a8c\u8bc1" },
        "en-US": { statusLabel: "Not fully verified", headline: "zh-CN integrity still needs verification" },
        "es-ES": { statusLabel: "Aun sin verificar", headline: "La integridad zh-CN a\u00fan necesita verificaci\u00f3n" },
        "fr-FR": { statusLabel: "Encore \u00e0 v\u00e9rifier", headline: "L'int\u00e9grit\u00e9 zh-CN doit encore \u00eatre v\u00e9rifi\u00e9e" },
        "de-DE": { statusLabel: "Noch unbest\u00e4tigt", headline: "Die zh-CN-Integrit\u00e4t muss noch gepr\u00fcft werden" },
        "ja-JP": { statusLabel: "\u672a\u691c\u8a3c", headline: "zh-CN \u306e\u5b8c\u6574\u6027\u306f\u307e\u3060\u691c\u8a3c\u4e2d\u3067\u3059" },
        "ko-KR": { statusLabel: "\ubbf8\uac80\uc99d", headline: "zh-CN \ubb34\uacb0\uc131\uc740 \uc544\uc9c1 \uac80\uc99d\uc774 \ud544\uc694\ud569\ub2c8\ub2e4" },
        "pt-BR": { statusLabel: "Ainda n\u00e3o verificado", headline: "A integridade zh-CN ainda precisa de verifica\u00e7\u00e3o" },
      });
    case "language_corruption":
      return localized({
        "zh-CN": { statusLabel: "中文未正常送达", headline: "中文内容没有正常送到模型" },
        "en-US": { statusLabel: "Input corrupted", headline: "Chinese input is being corrupted" },
        "es-ES": { statusLabel: "Entrada dañada", headline: "La entrada en chino se está corrompiendo" },
        "fr-FR": { statusLabel: "Entrée altérée", headline: "La saisie chinoise est altérée" },
        "de-DE": { statusLabel: "Eingabe beschädigt", headline: "Chinesische Eingaben werden beschädigt" },
        "ja-JP": { statusLabel: "入力破損", headline: "中国語入力が壊れています" },
        "ko-KR": { statusLabel: "입력 손상", headline: "중국어 입력이 손상되고 있습니다" },
        "pt-BR": { statusLabel: "Entrada corrompida", headline: "A entrada em chinês está sendo corrompida" },
      });
    case "reasoning_budget_exhausted":
      return localized({
        "zh-CN": { statusLabel: "思考耗尽预算", headline: "模型隐藏推理消耗了输出预算，可重试或换非思考模型" },
        "en-US": { statusLabel: "Reasoning consumed budget", headline: "Hidden reasoning consumed the output budget; retry or pick a non-reasoning model" },
        "es-ES": { statusLabel: "Razoning consumió presupuesto", headline: "El razonamiento oculto consumió el presupuesto; reintenta o elige otro modelo" },
        "fr-FR": { statusLabel: "Raisonnement épuisé", headline: "Le raisonnement caché a consommé le budget; réessayez ou changez de modèle" },
        "de-DE": { statusLabel: "Denkenbudget aufgebraucht", headline: "Verdecktes Reasoning hat das Budget verbraucht; wiederholen oder anderes Modell wählen" },
        "ja-JP": { statusLabel: "思考が予算を消費", headline: "隠れた推論が出力予算を消費しました。再試行または別のモデルを選択してください" },
        "ko-KR": { statusLabel: "추론이 예산 소진", headline: "숨은 추론이 출력 예산을 소비했습니다. 재시도하거나 다른 모델을 선택하세요" },
        "pt-BR": { statusLabel: "Raciocínio esgotou orçamento", headline: "O raciocínio oculto consumiu o orçamento; tente novamente ou escolha outro modelo" },
      });
    case "reasoning_leak":
    case "empty_response":
      return localized({
        "zh-CN": { statusLabel: "空回复", headline: "模型没有给出可用回复" },
        "en-US": { statusLabel: "Empty reply", headline: "Provider returned no usable reply" },
        "es-ES": { statusLabel: "Respuesta vacía", headline: "El proveedor no devolvió una respuesta usable" },
        "fr-FR": { statusLabel: "Réponse vide", headline: "Le fournisseur n'a renvoyé aucune réponse exploitable" },
        "de-DE": { statusLabel: "Leere Antwort", headline: "Der Anbieter lieferte keine brauchbare Antwort" },
        "ja-JP": { statusLabel: "空応答", headline: "利用可能な応答が返ってきませんでした" },
        "ko-KR": { statusLabel: "빈 응답", headline: "사용 가능한 응답이 돌아오지 않았습니다" },
        "pt-BR": { statusLabel: "Resposta vazia", headline: "O provedor não devolveu resposta utilizável" },
      });
    case "truncated_or_empty":
      return localized({
        "zh-CN": { statusLabel: "回复不可用", headline: "模型回复不可用" },
        "en-US": { statusLabel: "Reply unusable", headline: "Provider reply was unusable" },
        "es-ES": { statusLabel: "Respuesta inutilizable", headline: "La respuesta del proveedor no se pudo usar" },
        "fr-FR": { statusLabel: "Réponse inutilisable", headline: "La réponse du fournisseur était inutilisable" },
        "de-DE": { statusLabel: "Antwort unbrauchbar", headline: "Die Antwort des Anbieters war unbrauchbar" },
        "ja-JP": { statusLabel: "応答不可", headline: "プロバイダーの応答は利用できませんでした" },
        "ko-KR": { statusLabel: "응답 사용 불가", headline: "제공자 응답을 사용할 수 없었습니다" },
        "pt-BR": { statusLabel: "Resposta inutilizável", headline: "A resposta do provedor não pôde ser usada" },
      });
    case "context_length_exceeded":
      return localized({
        "zh-CN": { statusLabel: "内容太长", headline: "请缩短输入内容后重试" },
        "en-US": { statusLabel: "Too much content", headline: "Shorten your message, then try again" },
        "es-ES": { statusLabel: "Demasiado contenido", headline: "Acorta el mensaje y vuelve a intentarlo" },
        "fr-FR": { statusLabel: "Trop de contenu", headline: "Raccourcissez votre message, puis réessayez" },
        "de-DE": { statusLabel: "Zu viel Inhalt", headline: "Kürzen Sie Ihre Nachricht und versuchen Sie es erneut" },
        "ja-JP": { statusLabel: "内容が長すぎます", headline: "メッセージを短くして、もう一度試してください" },
        "ko-KR": { statusLabel: "내용이 너무 깁니다", headline: "메시지를 줄인 뒤 다시 시도하세요" },
        "pt-BR": { statusLabel: "Conteúdo demais", headline: "Encurte a mensagem e tente novamente" },
      });
    default:
      return localized({
        "zh-CN": { statusLabel: "需要处理", headline: "连接需要检查" },
        "en-US": { statusLabel: "Needs attention", headline: "Connection needs attention" },
        "es-ES": { statusLabel: "Necesita atención", headline: "La conexión necesita revisión" },
        "fr-FR": { statusLabel: "À vérifier", headline: "La connexion doit être vérifiée" },
        "de-DE": { statusLabel: "Benötigt Prüfung", headline: "Verbindung muss geprüft werden" },
        "ja-JP": { statusLabel: "確認が必要", headline: "接続の確認が必要です" },
        "ko-KR": { statusLabel: "확인 필요", headline: "연결을 확인해야 합니다" },
        "pt-BR": { statusLabel: "Precisa de atenção", headline: "A conexão precisa de revisão" },
      });
  }

  const zh = language === "zh-CN";
  switch (category) {
    case "invalid_key_or_permission":
    case "invalid_api_key":
    case "authentication_failed":
      return {
        statusLabel: zh ? "密钥被拒" : "Key rejected",
        headline: zh ? "API key 被拒绝" : "API key rejected",
      };
    case "model_unsupported":
    case "model_not_supported":
      return {
        statusLabel: zh ? "模型被拒" : "Model rejected",
        headline: zh ? "模型名称不可用" : "Model name rejected",
      };
    case "model_not_found":
      return {
        statusLabel: zh ? "模型未就位" : "Model unavailable",
        headline: zh ? "目标模型当前不可用" : "Model is unavailable right now",
      };
    case "malformed_response":
      return {
        statusLabel: zh ? "响应不兼容" : "Payload unsupported",
        headline: zh ? "接口响应不兼容" : "Endpoint payload unsupported",
      };
    case "sidecar_unavailable":
      return {
        statusLabel: zh ? "后端未就绪" : "Backend offline",
        headline: zh ? "Trainer 后端未就绪" : "Trainer backend not ready",
      };
    case "workspace_trust":
      return {
        statusLabel: zh ? "等待授信" : "Trust required",
        headline: zh ? "工作区尚未授信" : "Workspace trust required",
      };
    case "network":
    case "network_error":
      return {
        statusLabel: zh ? "无法连通" : "Unreachable",
        headline: zh ? "无法连接 provider" : "Provider unreachable",
      };
    case "timeout":
      return {
        statusLabel: zh ? "请求超时" : "Timed out",
        headline: zh ? "provider 响应超时" : "Provider timed out",
      };
    case "rate_limit":
      return {
        statusLabel: zh ? "限流中" : "Rate limited",
        headline: zh ? "provider 正在限流" : "Provider is rate limiting",
      };
    case "empty_response":
      return {
        statusLabel: zh ? "空回复" : "Empty reply",
        headline: zh ? "模型没有给出可用回复" : "Provider returned no usable reply",
      };
    case "truncated_or_empty":
      return {
        statusLabel: zh ? "回复不可用" : "Reply unusable",
        headline: zh ? "模型回复不完整" : "Provider reply was unusable",
      };
    case "context_length_exceeded":
      return {
        statusLabel: zh ? "上下文超限" : "Context limited",
        headline: zh ? "上下文长度超限" : "Context window exceeded",
      };
    default:
      return {
        statusLabel: zh ? "需检查" : "Needs attention",
        headline: zh ? "连接需要检查" : "Connection needs attention",
      };
  }
}

function isMiniMaxLikeProvider(provider: Pick<ProviderConfigView, "name" | "baseUrl" | "model">): boolean {
  return /minimax/i.test(`${provider.name} ${provider.baseUrl} ${provider.model}`);
}

function sidecarRestartCopy(
  language: ComposerLanguage,
): { label: string; detail: string } {
  const copy: Record<ComposerLanguage, { label: string; detail: string }> = {
    "zh-CN": {
      label: "重新启动 Trainer",
      detail: "重新启动本地后端，再继续检查连接。",
    },
    "en-US": {
      label: "Restart Trainer",
      detail: "Restart the local backend, then check the connection again.",
    },
    "es-ES": {
      label: "Reiniciar Trainer",
      detail: "Reinicia el backend local y vuelve a comprobar la conexión.",
    },
    "fr-FR": {
      label: "Redémarrer Trainer",
      detail: "Redémarrez le backend local, puis vérifiez à nouveau la connexion.",
    },
    "de-DE": {
      label: "Trainer neu starten",
      detail: "Starten Sie das lokale Backend neu und prüfen Sie die Verbindung erneut.",
    },
    "ja-JP": {
      label: "Trainer を再起動",
      detail: "ローカルバックエンドを再起動してから、接続をもう一度確認します。",
    },
    "ko-KR": {
      label: "Trainer 다시 시작",
      detail: "로컬 백엔드를 다시 시작한 다음 연결을 다시 확인합니다.",
    },
    "pt-BR": {
      label: "Reiniciar o Trainer",
      detail: "Reinicie o backend local e verifique a conexão novamente.",
    },
  };
  return copy[language] ?? copy["en-US"];
}

function SettingsStatePanel({
  copy,
  status,
  primaryLabel,
}: {
  copy: CoachSettingsLabels;
  status?: SettingsSectionStatus;
  primaryLabel: string;
}) {
  if (!status) {
    return null;
  }
  const savedValue = status.savedValue ?? saveStateLabel(copy, status.saveState);
  const showSavedRow = status.saveState !== "empty" && savedValue !== status.effectiveValue;
  const showEffectiveRow =
    status.saveState !== "empty" || showSavedRow || Boolean(status.editingValue);

  return (
    <section className="settings-sheet__state-panel">
      <div className="settings-sheet__state-rows">
        {showEffectiveRow ? (
          <div className="settings-sheet__state-row">
            <span>{primaryLabel}</span>
            <strong title={status.effectiveValue}>{shortenSummary(status.effectiveValue, 96)}</strong>
          </div>
        ) : null}
        {showSavedRow ? (
          <div className="settings-sheet__state-row">
            <span>{copy.savedInWorkspace}</span>
            <strong title={savedValue}>{shortenSummary(savedValue, 96)}</strong>
          </div>
        ) : null}
        {status.editingValue ? (
          <div className="settings-sheet__state-row">
            <span>{copy.editingDraft}</span>
            <strong title={status.editingValue}>{shortenSummary(status.editingValue, 96)}</strong>
          </div>
        ) : null}
      </div>
      {status.note ? <p className="settings-sheet__note settings-sheet__note--compact">{status.note}</p> : null}
      {status.feedback ? (
        <div className={`settings-sheet__feedback settings-sheet__feedback--${status.feedback.tone}`}>
          <div className="settings-sheet__feedback-head">
            <span>{copy.latestAction}</span>
            <StatusPill tone={status.feedback.tone}>{status.feedback.title}</StatusPill>
          </div>
          {status.feedback.detail ? (
            <p className="settings-sheet__note settings-sheet__note--compact">
              {sanitizeErrorSurfaceText(status.feedback.detail)}
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function describeLanguageIntegrityFact(input: {
  language: ComposerLanguage;
  provider: ProviderConfigView;
  coachSendState: ProviderSendState;
}): {
  value: string;
  tone: "connected" | "pending" | "warn" | "offline";
  detail: string;
} {
  const { language, provider, coachSendState } = input;
  const isZh = language === "zh-CN";
  const lastTest = provider.lastTestResult;
  const lastCategory = provider.modelErrorCategory ?? lastTest?.errorCategory ?? lastTest?.status;
  const lastTestWasZh = Boolean(lastTest?.responseLanguage?.toLowerCase().startsWith("zh"));

  if (!provider.configured) {
    return {
      value: isZh ? "\u5f85\u8bbe\u7f6e" : "Setup",
      tone: "offline",
      detail: isZh
        ? "\u5148\u4fdd\u5b58\u4e00\u7ec4 connection\uff0c\u7136\u540e\u518d\u8dd1 zh-CN \u8f93\u5165\u68c0\u67e5\u3002"
        : "Save a connection first, then run a zh-CN integrity check.",
    };
  }

  if (!provider.apiKeyConfigured) {
    return {
      value: isZh ? "\u7f3a API key" : "Add API key",
      tone: "offline",
      detail: isZh
        ? "\u8865\u4e0a API key \u540e\uff0c\u518d\u9a8c\u8bc1 zh-CN \u8f93\u5165\u662f\u5426\u5b8c\u6574\u3002"
        : "Add an API key before checking zh-CN input integrity.",
    };
  }

  if (lastCategory === "language_corruption") {
    return {
      value: isZh ? "请先换服务" : "Chinese blocked",
      tone: "warn",
      detail: isZh
        ? "这条连接在发送中文时出了问题。请更换模型服务或访问地址，或者暂时用英文继续。"
        : "This connection corrupts zh-CN input before the model sees it. Switch provider or gateway, or use English for now.",
    };
  }

  if (lastCategory === "language_probe_inconclusive") {
    return {
      value: isZh ? "\u5f85\u9a8c\u8bc1" : "Needs zh-CN test",
      tone: "warn",
      detail: isZh
        ? "连接可以使用，但中文内容还没有验证完成。请先重新测试；必要时可暂时用英文继续。"
        : "The connection is reachable, but zh-CN input is not fully verified yet. English fallback is safer until you retest.",
    };
  }

  if (lastTest?.ok && lastTestWasZh) {
    return {
      value: isZh ? "\u5df2\u9a8c\u8bc1" : "Verified",
      tone: "connected",
      detail: isZh
        ? "\u6700\u8fd1\u4e00\u6b21\u6d4b\u8bd5\u5df2\u7ecf\u786e\u8ba4 zh-CN \u8f93\u5165\u80fd\u5b8c\u6574\u5230\u8fbe\u6a21\u578b\u3002"
        : "The latest test confirmed zh-CN input reaches the model intact.",
    };
  }

  if (coachSendState.status === "warming" || coachSendState.status === "refreshing") {
    return {
      value: isZh ? "\u68c0\u67e5\u4e2d" : "Checking",
      tone: "pending",
      detail: isZh
        ? "\u7b49\u8fd9\u7ec4 provider \u5b8c\u6210 model \u786e\u8ba4\u540e\uff0c\u518d\u8dd1 zh-CN \u8f93\u5165\u68c0\u67e5\u3002"
        : "Wait for model discovery to finish, then rerun the zh-CN check.",
    };
  }

  if (coachSendState.blocked) {
    return {
      value: isZh ? "\u5f85\u6062\u590d" : "Unavailable",
      tone: "warn",
      detail: isZh
        ? "\u5148\u628a chat connection \u6062\u590d\u5230\u53ef\u7528\uff0c\u7136\u540e\u518d\u68c0\u67e5 zh-CN \u8f93\u5165\u5b8c\u6574\u6027\u3002"
        : "Recover the chat connection first, then verify zh-CN input integrity.",
    };
  }

  if (lastTest?.ok) {
    return {
      value: isZh ? "\u672a\u6d4b zh-CN" : "zh-CN not tested",
      tone: "pending",
      detail: isZh
        ? "\u8fd9\u6761 connection \u5df2\u901a\u8fc7\u6d4b\u8bd5\uff0c\u4f46\u6700\u8fd1\u4e00\u6b21\u8fd8\u4e0d\u662f zh-CN \u8f93\u5165\u3002\u5982\u679c\u4f60\u8981\u7528\u4e2d\u6587\u6559\u7ec3\uff0c\u8bf7\u518d\u8dd1\u4e00\u6b21 zh-CN \u6d4b\u8bd5\u3002"
        : "This connection passed a test, but not with zh-CN input. Run one zh-CN test before relying on Chinese coaching.",
    };
  }

  return {
    value: isZh ? "\u5f85\u6d4b\u8bd5" : "Run test",
    tone: "pending",
    detail: isZh
      ? "\u8fde\u63a5\u5df2\u53ef\u7528\uff0c\u4f46 zh-CN \u8f93\u5165\u8fd8\u6ca1\u6709\u771f\u6b63\u9a8c\u8bc1\u8fc7\u3002"
      : "The connection can work, but zh-CN input has not been verified yet.",
  };
}

export function CoachSettingsView({
  provider,
  workspaceId,
  capabilityVerdict,
  providerImageInputState,
  providerDraft,
  coachStateSummary,
  coachSignal,
  learnerName,
  targetProject,
  preferredRhythm,
  preferredLearningMode,
  onboardingRequest,
  projectContext,
  reviewRhythmSummary,
  nextReviewDue,
  longTermMemoryStateLabel,
  memoryShareGrants = [],
  workspaceAuthority,
  workspaceTrustState,
  resourceSandbox,
  trainerWorkspace,
  themePreference,
  learningSurfaceAlignment,
  language,
  answerMode,
  teachingStyle,
  coachDefaults,
  followCurrentFile,
  contextDetail = "balanced",
  includeCurrentFile = true,
  includeSelection = true,
  includeDiagnostics = true,
  includeRelatedFiles = true,
  className,
  labels,
  providerStatus,
  coachDefaultsStatus,
  workspaceControlStatus,
  providerApiKeyFocusRequest,
  onProviderDraftChange,
  onThemePreferenceChange,
  onLearningSurfaceAlignmentChange,
  onLanguageChange,
  onAnswerModeChange,
  onTeachingStyleChange,
  onFollowCurrentFileChange,
  onCoachDefaultsChange,
  onContextDetailChange,
  onIncludeCurrentFileChange,
  onIncludeSelectionChange,
  onIncludeDiagnosticsChange,
  onIncludeRelatedFilesChange,
  onSaveCoachSettings,
  onGrantMemoryShare,
  onRevokeMemoryShare,
  onSaveProvider,
  onSaveProviderProfile,
  onUseProviderTemplate,
  onRefreshProviderProfiles,
  onSwitchProviderProfile,
  onRefreshProviderModels,
  onTestProvider,
  onRestartSidecar,
  onClearProvider,
  onOpenConfig,
  onRefreshWorkspaceAuthority,
  onChooseTrainerWorkspaceRoot,
  onMigrateTrainerWorkspaceRoot,
  onBackupTrainerWorkspace,
  onRestoreTrainerWorkspaceBackup,
  onChooseManagedDataFolder,
  onResetManagedDataFolder,
  onRefreshMemory,
  onResetDefaults,
}: CoachSettingsViewProps) {
  const baseLabels = {
    ...(language === "zh-CN" ? defaultLabels : englishLabels),
    ...localizedSettingsLabels(language),
  };
  const copy: CoachSettingsLabels = {
    ...englishLabels,
    ...baseLabels,
    auto: adaptiveBehaviorLabel(language, "both"),
    ...labels,
  } as CoachSettingsLabels;
  const orientationMoreLabel = resolveWorkbenchCopy(language).orientationMore;
  const settingsGlobalCopy = resolveWorkbenchCopy(language);
  const surfaceAlignmentCopy = learningSurfaceAlignmentCopy(language);
  const classes = ["settings-sheet", "coach-settings-view", className].filter(Boolean).join(" ");
  const providerProfilesPanelRef = useRef<HTMLDetailsElement | null>(null);
  const apiKeyInputRef = useRef<HTMLInputElement | null>(null);
  const modelPickerRef = useRef<HTMLDetailsElement | null>(null);
  const modelSearchInputRef = useRef<HTMLInputElement | null>(null);
  const modelSelectRef = useRef<HTMLSelectElement | null>(null);
  const connectionAnchorRef = useRef<HTMLDivElement | null>(null);
  const teachingPrefsAnchorRef = useRef<HTMLDivElement | null>(null);
  const memoryPrivacyAnchorRef = useRef<HTMLDivElement | null>(null);
  const sectionFlashTimerRef = useRef<number | null>(null);
  const [modelPickerOpen, setModelPickerOpen] = useState(() => !providerDraft.model.trim());
  // Keep the language control reachable from the first Settings viewport;
  // users can still collapse the rest of the coach defaults after choosing it.
  const [coachDefaultsOpen, setCoachDefaultsOpen] = useState(true);
  const [memoryPrivacyOpen, setMemoryPrivacyOpen] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [advancedContextPinned, setAdvancedContextPinned] = useState(false);
  const [providerDetailRequested, setProviderDetailRequested] = useState(false);
  const [providerApiKeyFocusRequested, setProviderApiKeyFocusRequested] = useState(false);
  const [providerProfilesFocusRequested, setProviderProfilesFocusRequested] = useState(false);
  const [sectionFlash, setSectionFlash] = useState<"connection" | "teaching" | "memory" | null>(
    null,
  );
  const derivedAnswerStyle = useMemo(
    () =>
      deriveAnswerStylePreset({
        contextDetail,
        includeCurrentFile,
        includeSelection,
        includeDiagnostics,
        includeRelatedFiles,
      }),
    [contextDetail, includeCurrentFile, includeSelection, includeDiagnostics, includeRelatedFiles],
  );
  // 自定义 is user-declared: once a knob is hand-tuned (or 自定义 picked) the
  // radio stays on 自定义. Load-time still derives from the knob values so
  // every legacy field combination lands on the right preset.
  const [answerStyleCustomSelected, setAnswerStyleCustomSelected] = useState(
    () =>
      deriveAnswerStylePreset({
        contextDetail,
        includeCurrentFile,
        includeSelection,
        includeDiagnostics,
        includeRelatedFiles,
      }) === "custom" && readStoredAnswerStyle() === "custom",
  );
  const answerStyle: AnswerStylePreset = answerStyleCustomSelected ? "custom" : derivedAnswerStyle;
  useEffect(() => {
    if (coachDefaultsStatus?.saveState === "unsaved") {
      setCoachDefaultsOpen(true);
    }
  }, [coachDefaultsStatus?.saveState]);
  useEffect(() => {
    return () => {
      if (sectionFlashTimerRef.current !== null) {
        window.clearTimeout(sectionFlashTimerRef.current);
      }
    };
  }, []);
  /**
   * Status-bar anomaly jump: reveal the target section, smooth-scroll to it,
   * then flash its header once (skipped entirely under reduced motion).
   */
  const revealSettingsSection = (target: "connection" | "teaching" | "memory") => {
    if (target === "teaching") {
      setCoachDefaultsOpen(true);
    }
    if (target === "memory") {
      setMemoryPrivacyOpen(true);
    }
    window.requestAnimationFrame(() => {
      const node =
        target === "connection"
          ? connectionAnchorRef.current
          : target === "teaching"
            ? teachingPrefsAnchorRef.current
            : memoryPrivacyAnchorRef.current;
      if (!node) {
        return;
      }
      const reduced = prefersReducedMotion();
      node.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" });
      if (reduced) {
        return;
      }
      if (sectionFlashTimerRef.current !== null) {
        window.clearTimeout(sectionFlashTimerRef.current);
      }
      setSectionFlash(target);
      sectionFlashTimerRef.current = window.setTimeout(() => {
        setSectionFlash(null);
        sectionFlashTimerRef.current = null;
      }, SETTINGS_SECTION_FLASH_MS);
    });
  };
  const applyAnswerStylePreset = (preset: "simple" | "balanced" | "deep") => {
    const target = ANSWER_STYLE_PRESETS[preset];
    setAnswerStyleCustomSelected(false);
    writeStoredAnswerStyle(preset);
    if (contextDetail !== target.contextDetail) {
      onContextDetailChange?.(target.contextDetail);
    }
    if (includeCurrentFile !== target.includeCurrentFile) {
      onIncludeCurrentFileChange?.(target.includeCurrentFile);
    }
    if (includeSelection !== target.includeSelection) {
      onIncludeSelectionChange?.(target.includeSelection);
    }
    if (includeDiagnostics !== target.includeDiagnostics) {
      onIncludeDiagnosticsChange?.(target.includeDiagnostics);
    }
    if (includeRelatedFiles !== target.includeRelatedFiles) {
      onIncludeRelatedFilesChange?.(target.includeRelatedFiles);
    }
  };
  const selectAnswerStyle = (preset: AnswerStylePreset) => {
    if (preset === "custom") {
      setAnswerStyleCustomSelected(true);
      setAdvancedContextPinned(true);
      writeStoredAnswerStyle("custom");
      return;
    }
    applyAnswerStylePreset(preset);
  };
  /** Manual knob edits under a preset switch the radio to 自定义 without losing values. */
  const tuneAdvancedContextKnob = (apply: () => void) => {
    setAnswerStyleCustomSelected(true);
    writeStoredAnswerStyle("custom");
    apply();
  };
  useEffect(() => {
    if (!providerApiKeyFocusRequest) {
      return;
    }
    setProviderDetailRequested(true);
    setProviderApiKeyFocusRequested(true);
  }, [providerApiKeyFocusRequest]);
  const scopedLastTest = selectScopedSettingsLastTest(provider.lastTestResult, {
    workspaceId,
    providerProfileId: provider.profileId,
  });
  const scopedProvider = {
    ...provider,
    lastTestResult: scopedLastTest,
  };
  const providerTestCheckedAt = scopedLastTest?.checkedAt;
  const [providerTestClock, setProviderTestClock] = useState(() => Date.now());
  useEffect(() => {
    const checkedAtMs = Date.parse(providerTestCheckedAt ?? "");
    if (!Number.isFinite(checkedAtMs)) {
      return;
    }

    const now = Date.now();
    setProviderTestClock(now);
    const expiresAt = checkedAtMs + PROVIDER_TEST_FRESHNESS_WINDOW_MS;
    if (expiresAt <= now) {
      return;
    }

    const timeoutId = window.setTimeout(() => setProviderTestClock(Date.now()), expiresAt - now + 1);
    return () => window.clearTimeout(timeoutId);
  }, [providerTestCheckedAt]);
  const { memoryScope, workingSetMode, reviewCadence, reviewReminderMode, workspaceMemoryToggles } =
    coachDefaults;
  const managedDataSourceLabel =
    resourceSandbox?.source === "custom"
      ? copy.managedDataFolderCustom
      : copy.managedDataFolderRecommended;
  const managedDataEffectivePathKey = normalizeComparablePath(resourceSandbox?.effectivePath);
  const managedDataDefaultPathKey = normalizeComparablePath(resourceSandbox?.defaultPath);
  const managedDataConfiguredPathKey = normalizeComparablePath(resourceSandbox?.configuredPath);
  const showManagedDataRecommendedCard = Boolean(
    resourceSandbox?.defaultPath &&
      managedDataDefaultPathKey &&
      managedDataDefaultPathKey !== managedDataEffectivePathKey,
  );
  const showManagedDataCustomCard = Boolean(
    resourceSandbox?.configuredPath &&
      managedDataConfiguredPathKey &&
      managedDataConfiguredPathKey !== managedDataEffectivePathKey &&
      managedDataConfiguredPathKey !== managedDataDefaultPathKey,
  );
  const showManagedDataFallbackNote = Boolean(
    resourceSandbox?.configuredPath &&
      managedDataConfiguredPathKey &&
      managedDataConfiguredPathKey !== managedDataDefaultPathKey,
  );

  const memoryScopeLabel =
    memoryScope === "project"
      ? copy.memoryScopeProject
      : memoryScope === "personal"
        ? copy.memoryScopePersonal
        : copy.memoryScopeSession;
  const canManageMemoryShares =
    trainerWorkspace?.status === "managed" && Boolean(onGrantMemoryShare);
  const memorySharingSummary =
    memoryShareGrants.length > 0
      ? `${memoryShareGrants.length} ${copy.memorySharingActive}`
      : copy.memorySharingNone;
  const workingSetLabel =
    workingSetMode === "focused"
      ? copy.workingSetFocused
      : workingSetMode === "broad"
        ? copy.workingSetBroad
         : copy.workingSetBalanced;
  const lastTest = scopedLastTest;
  const providerTestReadiness = describeProviderTestReadiness(scopedProvider, language, providerTestClock);
  const providerTestFreshness = providerTestReadiness.freshness;
  const providerTestFeedback =
    providerStatus?.feedback?.actionKind === "test-provider" ? providerStatus.feedback : undefined;
  const providerTestPending = providerTestFeedback?.tone === "pending";
  const providerTestTransportFailed = providerTestFeedback?.tone === "fail";
  const providerTestPassed =
    providerTestReadiness.ready && !providerTestPending && !providerTestTransportFailed;
  const coachSendState = describeProviderSendState(scopedProvider, language, providerTestClock);
  const reportedImageInputState =
    providerImageInputState ?? describeProviderImageInputState(scopedProvider, language, providerTestClock);
  const imageInputState =
    reportedImageInputState.supported && !providerTestReadiness.ready
      ? {
          ...reportedImageInputState,
          supported: false,
          status: "setup_required" as const,
          detail: settingsStatusPhrase(language, "connectionSavedNeedsTest"),
        }
      : reportedImageInputState;
  // Keep the normalized catalog state alongside the provider facts so every
  // downstream readiness branch reads an initialized value.
  const modelListStatus = provider.modelListStatus ?? "idle";
  const languageIntegrityFact = describeLanguageIntegrityFact({
    language,
    provider: scopedProvider,
    coachSendState,
  });
  const resolvedWorkspaceTrustState = normalizeWorkspaceTrustState(workspaceTrustState);
  const workspaceTrustSentence = describeWorkspaceTrustState(resolvedWorkspaceTrustState, language);
  const providerSaved = provider.configured;
  const savedProviderProfilesAvailable = hasSavedProviderProfiles(provider);
  const providerStreamingReady = streamingProbeIsVerified(lastTest);
  const providerCoachReady = !coachSendState.blocked && providerTestPassed && providerStreamingReady;
  const providerNeedsApiKey = providerSaved && !provider.apiKeyConfigured;
  const providerCoachBlockReason =
    coachSendState.status === "missing_provider" || coachSendState.status === "missing_api_key"
      ? coachSendState.reason
      : undefined;
  const reviewSummary = reviewRhythmSummary ?? copy.off;
  const runtimeStatusLabel = providerCoachReady
    ? language === "zh-CN"
      ? "可发送"
      : "Ready"
    : providerNeedsApiKey
      ? language === "zh-CN"
        ? "需补密钥"
        : "Add API key"
    : providerSaved
      ? language === "zh-CN"
        ? "需检查"
        : "Needs attention"
    : language === "zh-CN"
      ? "待配置"
      : "Setup";
  const providerStatusLabel = providerCoachReady
    ? copy.configured
    : providerNeedsApiKey
      ? copy.apiKeyMissing
    : providerSaved
      ? language === "zh-CN"
        ? "需检查"
        : "Needs attention"
      : copy.notConfigured;
  const teachingStyleItems = [
    { label: copy.auto, value: "auto" as const },
    { label: copy.teachingGuided, value: "guided" as const },
    { label: copy.teachingConceptFirst, value: "concept-first" as const },
    { label: copy.teachingHandsOn, value: "hands-on" as const },
    { label: copy.teachingChallenging, value: "challenging" as const },
  ];
  const lastTestFailure =
    lastTest?.ok === false && providerTestFreshness === "fresh" ? lastTest : undefined;
  const providerFailureCategory =
    lastTestFailure?.errorCategory ??
    (lastTestFailure?.status === "failed" ? "test_failed" : lastTestFailure?.status) ??
    provider.modelErrorCategory ??
    (providerTestTransportFailed ? "test_failed" : undefined);
  const modelSelectionNeedsRecovery =
    provider.modelListStatus === "error" ||
    providerFailureCategory === "model_not_found" ||
    providerFailureCategory === "model_not_supported" ||
    providerFailureCategory === "model_unsupported";
  const providerCredentialsRejected =
    providerFailureCategory === "invalid_key_or_permission" ||
    providerFailureCategory === "invalid_api_key" ||
    providerFailureCategory === "authentication_failed";
  const providerFailureState = providerFailureCopy(providerFailureCategory, language);
  const miniMaxLikeProvider = isMiniMaxLikeProvider(provider);
  const safeProviderFailureHint =
    providerErrorHint({ modelErrorCategory: providerFailureCategory }, language) ??
    (language === "zh-CN" ? "请检查连接设置后重试。" : "Check the connection settings and try again.");
  const lastTestLabel = providerTestPending
    ? settingsStatusPhrase(language, "checking")
    : providerTestTransportFailed
      ? copy.lastTestFailed
      : lastTest
        ? providerTestPassed
          ? copy.lastTestPassed
          : lastTest.ok || providerTestFreshness !== "fresh"
            ? settingsStatusPhrase(language, "connectionNeedsTest")
            : lastTest.status === "missing_api_key" || lastTest.status === "incomplete"
              ? copy.lastTestNeedsSetup
              : copy.lastTestFailed
        : copy.lastTestNever;
  const lastTestDetail = lastTest
    ? `${formatTimestamp(lastTest.checkedAt, language)} · ${
        providerTestPassed
          ? settingsSupportPhrase(language, "connectionVerified")
          : lastTest.ok || providerTestFreshness !== "fresh"
            ? settingsStatusPhrase(language, "connectionSavedNeedsTest")
            : safeProviderFailureHint
      }`
    : undefined;
  const coachStateText =
    stringifyNode(coachStateSummary) ??
    (coachStateSummary ? (language === "zh-CN" ? "已生成" : "Available") : undefined);
  const localizedRuntimeStatusLabel = providerCoachReady
    ? settingsStatusPhrase(language, "ready")
    : providerNeedsApiKey
      ? settingsPhrase(language, "addApiKey")
      : providerSaved
        ? settingsStatusPhrase(language, "needsAttention")
        : settingsStatusPhrase(language, "setup");
  const localizedProviderStatusLabel = providerCoachReady
    ? copy.configured
    : providerNeedsApiKey
      ? copy.apiKeyMissing
      : providerSaved
        ? settingsStatusPhrase(language, "needsAttention")
        : copy.notConfigured;
  const localizedLastTestDetail = lastTestDetail;
  const localizedCoachStateText =
    stringifyNode(coachStateSummary) ??
    (coachStateSummary ? settingsStatusPhrase(language, "available") : undefined);
  const runtimeSummary = compactSummaryValue(
    [longTermMemoryStateLabel, reviewSummary !== copy.off ? reviewSummary : null, coachSignal].filter(
      Boolean,
    ) as string[],
    longTermMemoryStateLabel ?? copy.off,
  );
  const memoryPreviewRows = [
    workspaceMemoryToggles.decisions ? copy.rememberDecisions : null,
    workspaceMemoryToggles.patterns ? copy.rememberPatterns : null,
    workspaceMemoryToggles.resources ? copy.rememberResources : null,
  ].filter(Boolean) as string[];
  const memoryScopeRuntimeSummary =
    memoryScope === "personal"
      ? copy.memorySharingDetail
      : memoryScope === "session"
        ? copy.memoryScopeRuntimeSession
        : copy.memoryScopeRuntimeProject;
  const reviewCadenceItems =
    language === "zh-CN"
      ? [
          { label: "\u8f7b", value: "light" as const },
          { label: "\u6807\u51c6", value: "steady" as const },
          { label: "\u79ef\u6781", value: "active" as const },
        ]
      : [
          { label: "Light", value: "light" as const },
          { label: "Standard", value: "steady" as const },
          { label: "Active", value: "active" as const },
        ];
  const reviewReminderItems =
    language === "zh-CN"
      ? [
          { label: "\u5230\u671f\u65f6", value: "due" as const },
          { label: "\u63d0\u524d", value: "ahead" as const },
          { label: "\u5408\u5e76", value: "digest" as const },
        ]
      : [
          { label: "Due", value: "due" as const },
          { label: "Ahead", value: "ahead" as const },
          { label: "Digest", value: "digest" as const },
        ];

  const updateWorkspaceMemoryToggles = (patch: Partial<WorkspaceMemoryToggles>) => {
    onCoachDefaultsChange?.({
      workspaceMemoryToggles: {
        ...workspaceMemoryToggles,
        ...patch,
      },
    });
  };

  const contextRows = [
    {
      label: copy.currentFile,
      enabled: includeCurrentFile,
      detail: copy.contextCurrentFileHint,
      onToggle: () => tuneAdvancedContextKnob(() => onIncludeCurrentFileChange?.(!includeCurrentFile)),
    },
    {
      label: copy.selection,
      enabled: includeSelection,
      detail: copy.contextSelectionHint,
      onToggle: () => tuneAdvancedContextKnob(() => onIncludeSelectionChange?.(!includeSelection)),
    },
    {
      label: copy.diagnostics,
      enabled: includeDiagnostics,
      detail: copy.contextDiagnosticsHint,
      onToggle: () => tuneAdvancedContextKnob(() => onIncludeDiagnosticsChange?.(!includeDiagnostics)),
    },
    {
      label: copy.relatedFiles,
      enabled: includeRelatedFiles,
      detail: copy.contextRelatedFilesHint,
      onToggle: () => tuneAdvancedContextKnob(() => onIncludeRelatedFilesChange?.(!includeRelatedFiles)),
    },
  ];
  const attachedContextSummary = compactSummaryValue(
    contextRows.filter((row) => row.enabled).map((row) => row.label),
    copy.off,
  );
  const savedProtocol = normalizeProviderProtocol(provider.protocol);
  const draftProtocol = normalizeProviderProtocol(providerDraft.protocol);
  const selectedProtocol = draftProtocol;
  const selectedProtocolLabel = providerProtocolCompletionLabel(selectedProtocol);
  const localizedSelectedProtocolLabel = protocolChoiceLabel(selectedProtocol, language);
  const selectedProtocolEndpoint = providerProtocolEndpointHint(selectedProtocol);
  const providerBaseUrlLabel = providerDetailLabel(language, "baseUrl");
  const providerBaseUrlHint = providerBaseUrlGuidance(
    language,
    selectedProtocol,
    selectedProtocolEndpoint,
  );
  const protocolItems = SUPPORTED_PROVIDER_PROTOCOLS.map((protocol) => ({
    label: protocolChoiceLabel(protocol, language),
    value: protocol,
  }));
  const providerSummary = compactSummaryValue(
    [
      providerSaved ? provider.profileLabel || provider.name || provider.profileId || null : null,
      providerSaved ? protocolChoiceLabel(savedProtocol, language) : null,
      providerSaved ? provider.model || null : null,
      providerSaved && provider.contextWindowTokens ? `ctx ${formatTokenValue(provider.contextWindowTokens)}` : null,
      providerSaved && provider.maxOutputTokens ? `out ${formatTokenValue(provider.maxOutputTokens)}` : null,
    ].filter(Boolean) as string[],
    copy.notConfigured,
  );
  const advancedSummary = compactSummaryValue(
    [
      memoryScopeLabel,
      workingSetLabel,
      reviewCadenceItems.find((item) => item.value === reviewCadence)?.label,
      reviewReminderItems.find((item) => item.value === reviewReminderMode)?.label,
    ].filter(Boolean) as string[],
    copy.off,
  );
  const providerHasDraftChanges =
    providerDraft.name !== provider.name ||
    draftProtocol !== savedProtocol ||
    providerDraft.baseUrl !== provider.baseUrl ||
    providerDraft.model !== provider.model ||
    providerDraft.contextWindowTokens !== provider.contextWindowTokens ||
    providerDraft.maxOutputTokens !== provider.maxOutputTokens ||
    providerModelTokenLimitsKey(providerDraft.modelTokenLimits) !==
      providerModelTokenLimitsKey(provider.modelTokenLimits) ||
    (providerDraft.credentialMode ?? provider.credentialMode ?? "ui_proxy") !==
      (provider.credentialMode ?? "ui_proxy") ||
    stringArrayKey(providerDraft.catalogModels ?? provider.catalogModels) !==
      stringArrayKey(provider.catalogModels) ||
    stringArrayKey(providerDraft.allowedModels ?? provider.allowedModels) !==
      stringArrayKey(provider.allowedModels) ||
    stringArrayKey(providerDraft.deniedModels ?? provider.deniedModels) !==
      stringArrayKey(provider.deniedModels) ||
    (providerDraft.embeddingModel ?? provider.embeddingModel ?? "") !==
      (provider.embeddingModel ?? "") ||
    (providerDraft.catalogSource ?? provider.catalogSource ?? "provider_live") !==
      (provider.catalogSource ?? "provider_live") ||
    (providerDraft.cacheTtlSeconds ?? provider.cacheTtlSeconds) !== provider.cacheTtlSeconds ||
    requestDefaultsKey(providerDraft.requestDefaults ?? provider.requestDefaults) !==
      requestDefaultsKey(provider.requestDefaults) ||
    providerDraft.apiKey.trim().length > 0;
  const normalizedDraftBaseUrl = normalizeProviderBaseUrlDraft(providerDraft.baseUrl, draftProtocol);
  const normalizedSavedBaseUrl = normalizeProviderBaseUrlDraft(provider.baseUrl, savedProtocol);
  const providerDraftHasApiKey = providerDraft.apiKey.trim().length > 0;
  const providerDraftFieldsReady = Boolean(providerDraft.baseUrl.trim() && providerDraft.model.trim());
  const providerDraftCanReuseSavedApiKey =
    providerSaved &&
    provider.apiKeyConfigured &&
    draftProtocol === savedProtocol &&
    normalizedDraftBaseUrl === normalizedSavedBaseUrl;
  const providerApiKeyDraftStatus = providerDraftHasApiKey
    ? {
        value: language === "zh-CN" ? "新 API key" : "New API key",
        state: "warn" as const,
      }
    : providerDraftCanReuseSavedApiKey
      ? {
          value: copy.apiKeySaved,
          state: "ok" as const,
        }
      : provider.apiKeyConfigured
        ? {
            value: settingsStatusPhrase(language, "connectionSavedApiKeyMissing"),
            state: "warn" as const,
          }
        : {
            value: copy.apiKeyMissing,
            state: "missing" as const,
          };
  const providerDraftReadyForModelDiscovery = Boolean(
    normalizedDraftBaseUrl && (providerDraftHasApiKey || providerDraftCanReuseSavedApiKey),
  );
  const providerDraftReadyForTestBase =
    providerDraftFieldsReady && (providerDraftHasApiKey || providerDraftCanReuseSavedApiKey);
  const attachedContextSummaryText = shortenSummary(attachedContextSummary, 54);
  const providerSummaryText = shortenSummary(providerSummary, 62);
  const advancedSummaryText = shortenSummary(advancedSummary, 82);
  const runtimeSummaryText = shortenSummary(runtimeSummary, 72);
  const coachStateSummaryText = localizedCoachStateText ? shortenSummary(localizedCoachStateText, 88) : undefined;
  const providerRequirementNote = providerNeedsApiKey
    ? language === "zh-CN"
      ? "连接已保存，还需要 API key。"
      : "Connection saved; API key missing."
    : !providerSaved && savedProviderProfilesAvailable
      ? language === "zh-CN"
        ? "这个工作区还没有启用连接。下方有可以直接使用的连接配置。"
        : "There is no active provider applied yet. Reusable profiles are still available below."
      : providerCoachBlockReason ?? null;
  const modelListing = asRecord(provider.modelListing);
  const draftListingProtocol = asString(modelListing?.protocol);
  const draftListingBaseUrl = asString(modelListing?.baseUrl);
  const draftModelListingMatches =
    providerHasDraftChanges &&
    asString(modelListing?.source) === "draft" &&
    Boolean(draftListingProtocol) &&
    Boolean(draftListingBaseUrl) &&
    normalizeProviderProtocol(draftListingProtocol) === draftProtocol &&
    normalizeProviderBaseUrlDraft(draftListingBaseUrl ?? "", draftProtocol) === normalizedDraftBaseUrl;
  const sameDraftTransportAsSaved =
    draftProtocol === savedProtocol && normalizedDraftBaseUrl === normalizedSavedBaseUrl;
  const canUseSavedModelMetadata = !providerHasDraftChanges || sameDraftTransportAsSaved;
  const availableModels = providerHasDraftChanges
    ? draftModelListingMatches
      ? asStringArray(modelListing?.availableModels)
      : sameDraftTransportAsSaved
        ? provider.availableModels ?? []
        : []
    : provider.availableModels ?? [];
  const draftModelTokenLimits = providerDraft.modelTokenLimits;
  const liveModelTokenLimits = canUseSavedModelMetadata ? provider.modelTokenLimits : undefined;
  const draftCatalogModels =
    providerDraft.catalogModels ?? (canUseSavedModelMetadata ? provider.catalogModels ?? [] : []);
  const liveCatalogModels = canUseSavedModelMetadata ? provider.catalogModels ?? [] : [];
  const draftRequestDefaults =
    asRecord(providerDraft.requestDefaults) ?? asRecord(provider.requestDefaults) ?? {};
  const draftRequestDefaultsSignature = requestDefaultsKey(draftRequestDefaults);
  const thinkingDescriptor = describeProviderThinking(
    {
      protocol: draftProtocol,
      model: providerDraft.model,
      providerName: providerDraft.name,
      baseUrl: providerDraft.baseUrl,
      liveEvidence: lastTest?.capabilityEvidence?.some((entry) =>
        entry.name.trim().toLowerCase() === "thinking" &&
        entry.state === "verified" &&
        entry.observed === true,
      ) === true,
    },
    draftRequestDefaults,
  );
  const currentDraftModel = providerDraft.model.trim();
  const currentLiveModel = canUseSavedModelMetadata ? provider.model.trim() : "";
  const draftModelPolicy = {
    allowedModels: providerDraft.allowedModels ?? provider.allowedModels ?? [],
    deniedModels: providerDraft.deniedModels ?? provider.deniedModels ?? [],
  };
  const currentDraftModelPolicy = evaluateProviderModelPolicy(currentDraftModel, draftModelPolicy);
  const currentDraftModelPolicyMessage =
    currentDraftModel && !currentDraftModelPolicy.allowed
      ? modelPolicyHint(
          language,
          currentDraftModelPolicy.reason === "denied" ? "denied" : "not_allowed",
        )
      : undefined;
  const currentDraftModelBlockedByPolicy = Boolean(currentDraftModelPolicyMessage);
  const selectableModelOptions = filterProviderModelOptions(
    mergeDraftStringList(
      currentDraftModel,
      draftCatalogModels,
      liveCatalogModels,
      availableModels,
    ),
    draftModelPolicy,
    { retainModels: currentDraftModel ? [currentDraftModel] : [] },
  );
  const modelPickerDefaultOptionLimit =
    MODEL_PICKER_RECENT_OPTION_LIMIT + (currentDraftModel ? 1 : 0);
  const modelPickerHasOverflow = selectableModelOptions.length > modelPickerDefaultOptionLimit;
  const [modelSearchQuery, setModelSearchQuery] = useState("");
  const [manualModelEntryOpen, setManualModelEntryOpen] = useState(false);
  const resetModelPickerSearch = () => {
    setModelSearchQuery("");
    setManualModelEntryOpen(false);
  };
  useEffect(() => {
    setModelSearchQuery("");
    setManualModelEntryOpen(false);
  }, [provider.profileId]);
  const normalizedModelSearchQuery = modelSearchQuery.trim().toLowerCase();
  const matchingModelOptions = useMemo(
    () =>
      selectableModelOptions.filter((modelName) =>
        modelName.toLowerCase().includes(normalizedModelSearchQuery),
      ),
    [normalizedModelSearchQuery, selectableModelOptions],
  );
  const visibleModelOptions = useMemo(() => {
    if (normalizedModelSearchQuery) {
      return matchingModelOptions.slice(0, MODEL_PICKER_SEARCH_OPTION_LIMIT);
    }

    return selectableModelOptions.slice(0, modelPickerDefaultOptionLimit);
  }, [
    matchingModelOptions,
    modelPickerDefaultOptionLimit,
    normalizedModelSearchQuery,
    selectableModelOptions,
  ]);
  const currentDraftModelIsVisible = visibleModelOptions.some(
    (modelName) => modelName.toLowerCase() === currentDraftModel.toLowerCase(),
  );
  const visibleModelSelection =
    normalizedModelSearchQuery && !currentDraftModelIsVisible ? "" : providerDraft.model;
  const showModelSearchInput = modelPickerHasOverflow || manualModelEntryOpen;
  const showManualModelEntryAction =
    !showModelSearchInput &&
    (selectableModelOptions.length === 0 || modelSelectionNeedsRecovery);
  const exactMatchingModel = selectableModelOptions.find(
    (modelName) => modelName.toLowerCase() === normalizedModelSearchQuery,
  );
  const exactMatchingModelIsVisible = Boolean(
    exactMatchingModel &&
      visibleModelOptions.some(
        (modelName) => modelName.toLowerCase() === exactMatchingModel.toLowerCase(),
      ),
  );
  const typedModelPolicy = evaluateProviderModelPolicy(modelSearchQuery, draftModelPolicy);
  const hasMatchingModelOptions = matchingModelOptions.length > 0;
  const canUseTypedModel =
    Boolean(normalizedModelSearchQuery) &&
    typedModelPolicy.allowed &&
    (!hasMatchingModelOptions || Boolean(exactMatchingModel));
  const showTypedModelAction =
    canUseTypedModel && (!exactMatchingModel || !exactMatchingModelIsVisible);
  const hiddenMatchingModelCount = Math.max(
    0,
    matchingModelOptions.length - visibleModelOptions.length,
  );
  const modelLimitNames = filterProviderModelOptions(
    Array.from(
      new Set(
        [
          currentDraftModel,
          currentLiveModel,
          canUseSavedModelMetadata ? provider.resolvedModel?.trim() ?? "" : "",
          ...availableModels,
          ...draftCatalogModels,
          ...liveCatalogModels,
          ...Object.keys(draftModelTokenLimits ?? {}),
          ...Object.keys(liveModelTokenLimits ?? {}),
        ]
          .map((value) => value.trim())
          .filter(Boolean),
      ),
    ).sort((left, right) => {
      if (left === currentDraftModel) {
        return -1;
      }
      if (right === currentDraftModel) {
        return 1;
      }
      return left.localeCompare(right, undefined, { sensitivity: "base" });
    }),
    draftModelPolicy,
    { retainModels: currentDraftModel ? [currentDraftModel] : [] },
  );
  const [manualModelDraft, setManualModelDraft] = useState("");
  const [requestDefaultsText, setRequestDefaultsText] = useState(() =>
    formatRequestDefaultsDraft(draftRequestDefaults),
  );
  const [requestDefaultsError, setRequestDefaultsError] = useState<string>();
  useEffect(() => {
    setRequestDefaultsText(formatRequestDefaultsDraft(draftRequestDefaults));
    setRequestDefaultsError(undefined);
  }, [draftRequestDefaultsSignature]);
  const normalizedManualModelDraft = manualModelDraft.trim();
  const manualModelPolicy = evaluateProviderModelPolicy(
    normalizedManualModelDraft,
    draftModelPolicy,
  );
  const manualModelBlockedByPolicy =
    Boolean(normalizedManualModelDraft) && !manualModelPolicy.allowed;
  const modelPickerCopy = providerModelPickerCopy(language);
  const providerDraftEditorBlocked = Boolean(requestDefaultsError);
  const requestDefaultsTextHasDrift =
    requestDefaultsText.trim() !== formatRequestDefaultsDraft(draftRequestDefaults).trim();
  const providerDraftReadyForTest =
    providerDraftReadyForTestBase &&
    !currentDraftModelBlockedByPolicy &&
    !providerDraftEditorBlocked;
  const providerTestRecoveryDetail =
    providerTestFeedback?.actionKind === "test-provider" && providerTestFeedback.tone === "fail"
      ? !providerDraftFieldsReady
        ? settingsStatusPhrase(language, "fillProviderFields")
        : !providerDraftHasApiKey && !providerDraftCanReuseSavedApiKey
          ? settingsStatusPhrase(language, "connectionSavedApiKeyMissing")
          : providerHasDraftChanges
            ? settingsStatusPhrase(language, "saveBeforeTesting")
            : providerSaved
              ? safeProviderFailureHint
              : settingsPhrase(language, "verifyConnectionDetail")
      : undefined;
  const discoveredModelSet = useMemo(
    () => new Set(availableModels.map((value) => value.trim().toLowerCase()).filter(Boolean)),
    [availableModels],
  );
  const modelLimitKeySet = useMemo(
    () => new Set(modelLimitNames.map((value) => value.trim().toLowerCase()).filter(Boolean)),
    [modelLimitNames],
  );
  const canAddManualModel =
    normalizedManualModelDraft.length > 0 &&
    manualModelPolicy.allowed &&
    !modelLimitKeySet.has(normalizedManualModelDraft.toLowerCase());
  const liveContextWindowTokens = provider.contextWindowTokens;
  const liveMaxOutputTokens = provider.maxOutputTokens;
  const draftContextWindowTokens = providerDraft.contextWindowTokens;
  const draftMaxOutputTokens = providerDraft.maxOutputTokens;
  const availabilityFailureHint =
    providerTestRecoveryDetail ?? safeProviderFailureHint;
  const localizedLastTestDetailText = providerTestRecoveryDetail ?? localizedLastTestDetail;
  const cacheSourceLabel =
    provider.cacheSource === "live"
      ? copy.modelCacheSourceLive
      : provider.cacheSource === "cache"
        ? copy.modelCacheSourceCache
        : settingsPhrase(language, "notRecorded");
  const cacheExpiryMs = provider.cacheExpiresAt ? Date.parse(provider.cacheExpiresAt) : Number.NaN;
  const cacheIsExpired = Number.isFinite(cacheExpiryMs) ? cacheExpiryMs <= Date.now() : false;
  const modelCacheStatusLabel =
    modelListStatus === "loading"
      ? copy.modelCacheStatusLoading
      : modelListStatus === "error"
        ? copy.modelCacheStatusError
        : Number.isFinite(cacheExpiryMs)
          ? cacheIsExpired
            ? copy.modelCacheStatusExpired
            : copy.modelCacheStatusFresh
          : copy.modelCacheStatusUnknown;
  const modelCacheTone =
    modelListStatus === "loading"
      ? "pending"
      : modelListStatus === "error"
        ? "fail"
        : Number.isFinite(cacheExpiryMs)
          ? cacheIsExpired
            ? "warn"
            : "pass"
          : "pending";
  const providerProfiles = useMemo(() => normalizeProviderProfileViews(provider), [provider]);
  const providerProfileCount = countSavedProviderProfiles(provider);
  const [providerProfilesOpen, setProviderProfilesOpen] = useState(
    () => !provider.configured && providerProfiles.length === 0,
  );
  useEffect(() => {
    if (!provider.configured && providerProfiles.length === 0) {
      setProviderProfilesOpen(true);
    }
  }, [provider.configured, providerProfiles.length]);
  const liveProtocol = normalizeProviderProtocol(provider.protocol);
  const liveProtocolLabel = protocolChoiceLabel(liveProtocol, language);
  const liveProtocolEndpoint = providerProtocolEndpointHint(liveProtocol);
  const protocolVerdict = describeProviderProtocolSummary(
    {
      protocol: liveProtocol,
      protocolDiagnostic: provider.protocolDiagnostic,
    },
    language,
  );
  const diagnosticsVerdict = describeProviderDiagnosticVerdict(
    {
      protocolDiagnostic: provider.protocolDiagnostic,
      taskBindingDiagnostics: provider.taskBindingDiagnostics,
      modelDiagnostics: provider.modelDiagnostics,
      modelTest: provider.modelTest,
      modelListStatus,
    },
    language,
  );
  const profileVerdict = describeProviderProfileSummary(
    {
      profileId: provider.profileId,
      profileLabel: provider.profileLabel,
      profileMode: provider.profileMode,
      profileCount: providerProfileCount,
      profileHistory: provider.profileHistory,
    },
    language,
  );
  const providerTruthCopy = providerConnectionTruthCopy(language);
  const toolsCopy = toolsVerificationCopy(language);
  const settingsCapabilityScope = {
    workspaceId,
    providerProfileId: provider.profileId,
  };
  const capabilitySurfaceStatus = settingsCapabilitySurfaceStatus(
    lastTest,
    settingsCapabilityScope,
    liveProtocol ?? lastTest?.protocol,
  );
  const capabilityChipsAllowed =
    !providerHasDraftChanges &&
    settingsCapabilityChipsVisible(
      lastTest,
      settingsCapabilityScope,
      liveProtocol ?? lastTest?.protocol,
    );
  const capabilityHonestyStatus =
    providerHasDraftChanges
      ? providerTruthCopy.capabilityDraftDetail(localizedSelectedProtocolLabel)
      : capabilitySurfaceStatus === "failed"
        ? providerTruthCopy.capabilityTestFailed
        : capabilitySurfaceStatus === "unknown_protocol"
          ? providerTruthCopy.capabilityUnknownProtocol
          : capabilitySurfaceStatus === "never_tested"
            ? providerTruthCopy.capabilityNeverTested
            : providerTruthCopy.capabilityLiveDetail(availableModels.length);
  const toolsVerificationFact = describeToolsVerificationFact({
    language,
    configured: providerSaved,
    draftChanged: providerHasDraftChanges,
    testReady: providerTestReadiness.ready,
    lastTest,
  });
  const streamingCopy = streamingVerificationCopy(language);
  const streamingVerificationFact = describeStreamingVerificationFact({
    language,
    configured: providerSaved,
    draftChanged: providerHasDraftChanges,
    testReady: providerTestReadiness.ready,
    lastTest,
  });
  const thinkingCopy = thinkingVerificationCopy(language);
  const thinkingVerificationFact = describeThinkingVerificationFact({
    language,
    configured: providerSaved,
    draftChanged: providerHasDraftChanges,
    testReady: providerTestReadiness.ready,
    lastTest,
    minimax: isMiniMaxLikeProvider({
      name: providerDraft.name || provider.name,
      baseUrl: providerDraft.baseUrl || provider.baseUrl,
      model: providerDraft.model || provider.model,
    }),
  });
  const visionCopy = visionVerificationCopy(language);
  const visionVerificationFact = describeVisionVerificationFact({
    language,
    configured: providerSaved,
    draftChanged: providerHasDraftChanges,
    testReady: providerTestReadiness.ready,
    lastTest,
  });
  const gatewayNote = gatewayFingerprintNote(provider.diagnostics, language, provider.connectionType);
  const capabilitySummaryDetail = capabilityChipsAllowed
    ? `${capabilityHonestyStatus} ${toolsVerificationFact.detail} ${streamingVerificationFact.detail} ${thinkingVerificationFact.detail} ${visionVerificationFact.detail}${
    gatewayNote ? ` ${gatewayNote}` : ""
  }`
    : `${capabilityHonestyStatus}${gatewayNote ? ` ${gatewayNote}` : ""}`;
  const taskBindingDiagnostics = Array.isArray(provider.taskBindingDiagnostics)
    ? provider.taskBindingDiagnostics
    : [];
  const modelDiagnostics = Array.isArray(provider.modelDiagnostics) ? provider.modelDiagnostics : [];
  const blockedTaskBindingCount = taskBindingDiagnostics.filter((item) => item.supported === false).length;
  const blockedModelCount = modelDiagnostics.filter((item) => item.supported === false).length;
  const modelCapabilityRows = Object.entries(provider.modelCapabilities ?? {}).slice(0, 3).map(
    ([modelName, capabilities]) => ({
      label: modelName,
      value: capabilitySummaryText(capabilities, language),
    }),
  );
  const diagnosticNotes = (provider.diagnostics ?? [])
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 3);
  const warningNotes = (provider.warnings ?? [])
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 2);
  const protocolFactTone = providerHasDraftChanges
    ? "pending"
    : providerVerdictTone(protocolVerdict.tone);
  const protocolFactValue = providerHasDraftChanges
    ? localizedSelectedProtocolLabel
    : protocolVerdict.status;
  const protocolFactDetail = providerHasDraftChanges
    ? providerTruthCopy.protocolDraftDetail(
        localizedSelectedProtocolLabel,
        selectedProtocolEndpoint,
        liveProtocolLabel,
        liveProtocolEndpoint,
      )
    : protocolVerdict.detail;
  const diagnosticsFactTone =
    providerHasDraftChanges || !providerTestReadiness.ready
      ? "pending"
      : providerVerdictTone(diagnosticsVerdict.tone);
  const diagnosticsFactValue = providerHasDraftChanges
    ? providerTruthCopy.draftNotTested
    : !providerSaved
      ? providerTruthCopy.saveFirstStatus
      : !providerTestReadiness.ready
        ? providerTruthCopy.needsLiveTest
        : diagnosticsVerdict.status;
  const diagnosticsFactDetail = providerHasDraftChanges
    ? providerTruthCopy.diagnosticsDraftDetail
    : !providerSaved
      ? providerTruthCopy.saveFirst
      : !providerTestReadiness.ready
        ? providerTruthCopy.diagnosticsNeedsTest
        : diagnosticsVerdict.detail;
  const profileDraftReady = Boolean(
    providerDraft.name.trim() && providerDraft.baseUrl.trim() && providerDraft.model.trim(),
  );
  const canSaveProviderProfile = Boolean(
    onSaveProviderProfile && profileDraftReady && (providerHasDraftChanges || !provider.profileId),
  );
  const localizedProviderProfilesLabel = providerDetailLabel(language, "savedProfiles");
  const localizedSavedProfilesDetail =
    providerProfileCount > 0
      ? providerDetailLabel(language, "savedProfilesAvailable")
      : providerDetailLabel(language, "savedProfilesEmpty");
  const localizedRefreshProfilesLabel = providerDetailLabel(language, "refreshProfiles");
  const localizedRefreshProfilesDetail = providerDetailLabel(language, "reloadProfiles");
  const localizedSaveProfileLabel = providerDetailLabel(language, "saveProfile");
  const localizedSaveProfileDetail = providerDetailLabel(language, "saveProfileDetail");
  const localizedPerModelLimitsLabel = providerDetailLabel(language, "perModelLimits");
  const localizedPerModelLimitsDetail =
    language === "zh-CN"
      ? "Trainer \u4F1A\u6309 model \u8BB0\u4F4F Context window \u548C Max output\u3002\u5207\u5230\u67D0\u4E2A model \u65F6\uFF0C\u4F1A\u81EA\u52A8\u5E26\u56DE\u5B83\u81EA\u5DF1\u7684 limits\u3002"
      : "Trainer keeps Context window and Max output per model and restores them when you switch models.";
  const localizedUseModelLabel =
    language === "zh-CN" ? "\u7528\u8FD9\u4E2A model" : "Use model";
  const localizedCurrentModelLabel =
    language === "zh-CN" ? "\u5F53\u524D" : "Current";
  const localizedModelLimitEmpty =
    language === "zh-CN"
      ? "\u5148\u62C9\u53D6\u6A21\u578B\u5217\u8868\uFF0C\u6216\u8005\u76F4\u63A5\u8F93\u5165\u4E00\u4E2A model\u3002"
      : "Fetch models first, or type a model name directly.";
  const localizedCatalogPanelLabel = providerDetailLabel(language, "modelCatalog");
  const localizedCatalogPanelDetail =
    language === "zh-CN"
      ? "Trainer \u4F1A\u6309\u8FD9\u4E9B\u5DF2\u4FDD\u5B58\u7684 model \u7EC6\u8282\u6765\u505A\u81EA\u52A8\u5207\u6362\u3001profile \u5207\u6362\u548C live refresh\u3002"
      : "Trainer uses these saved model details when it switches models, swaps profiles, and refreshes live catalogs.";
  const localizedCatalogAliasesLabel =
    language === "zh-CN" ? "Model aliases" : "Model aliases";
  const localizedCatalogTaskBindingsLabel =
    language === "zh-CN" ? "Task bindings" : "Task bindings";
  const localizedCatalogAllowedModelsLabel =
    language === "zh-CN" ? "Allowed models" : "Allowed models";
  const localizedCatalogDeniedModelsLabel =
    language === "zh-CN" ? "Blocked models" : "Blocked models";
  const localizedCatalogEmbeddingModelLabel =
    language === "zh-CN" ? "Embedding model" : "Embedding model";
  const localizedCatalogRequestDefaultsLabel =
    language === "zh-CN" ? "Request defaults" : "Request defaults";
  const localizedCatalogSourceLabel =
    language === "zh-CN" ? "Catalog source" : "Catalog source";
  const localizedCatalogCacheTtlLabel =
    language === "zh-CN" ? "Cache TTL" : "Cache TTL";
  const localizedCatalogSavedModelsLabel: Record<ComposerLanguage, string> = {
    "zh-CN": "已保存模型",
    "en-US": "Saved models",
    "es-ES": "Modelos guardados",
    "fr-FR": "Modeles enregistres",
    "de-DE": "Gespeicherte Modelle",
    "ja-JP": "保存済みモデル",
    "ko-KR": "저장된 모델",
    "pt-BR": "Modelos salvos",
  };
  const localizedAdvancedRoutingLabel =
    language === "zh-CN" ? "\u8DEF\u7531\u89C4\u5219" : "Routing rules";
  const localizedAdvancedRoutingDetail =
    language === "zh-CN"
      ? "这里放会影响 provider profile 行为的高级字段。默认收起，不抢首屏。"
      : "These fields shape provider profile behavior. They stay collapsed by default so Settings keeps its first screen calm.";
  const localizedCredentialModeLabel =
    language === "zh-CN" ? "Credential mode" : "Credential mode";
  const localizedCredentialModeUiProxy =
    language === "zh-CN" ? "UI proxy" : "UI proxy";
  const localizedCredentialModeWorkspaceSecret =
    language === "zh-CN" ? "Workspace secret" : "Workspace secret";
  const localizedAllowedModelsInputDetail =
    language === "zh-CN"
      ? "用逗号或换行分隔。留空表示不限制。"
      : "Separate models with commas or new lines. Leave blank to allow any model.";
  const localizedDeniedModelsInputDetail =
    language === "zh-CN"
      ? "这些 model 会被 profile 直接挡住。"
      : "These models stay blocked for this profile.";
  const localizedEmbeddingModelPlaceholder =
    language === "zh-CN" ? "可选，例如 text-embedding-3-small" : "Optional, for example text-embedding-3-small";
  const localizedCacheTtlDetail =
    language === "zh-CN" ? "单位是秒。" : "Measured in seconds.";
  const localizedManualModelLabel =
    language === "zh-CN" ? "手动加入 model" : "Add model manually";
  const localizedManualModelPlaceholder =
    language === "zh-CN" ? "例如 MiniMax-M3" : "For example MiniMax-M3";
  const localizedManualModelButton =
    language === "zh-CN" ? "加入当前 catalog" : "Add to current catalog";
  const localizedManualModelHint =
    language === "zh-CN"
      ? "即使 provider 还没列出它，也可以先把 model 放进当前 catalog。至少填一个 limit 后，它就会被记住。"
      : "You can stage a model here even before the provider lists it. Save at least one limit to keep it in the catalog.";
  const localizedRequestDefaultsInputDetail =
    language === "zh-CN"
      ? "\u7528 JSON object \u7ec6\u5316 provider \u8bf7\u6c42\u3002Trainer \u4f1a\u5728\u53d1\u9001\u65f6\u5408\u5e76\u8fd9\u4e9b\u9ed8\u8ba4\u503c\u3002"
      : "Use a JSON object to refine provider requests. Trainer merges these defaults into outgoing requests.";
  const localizedRequestDefaultsInputHint =
    language === "zh-CN"
      ? "\u4fdd\u6301\u4e3a\u4e00\u4e2a JSON object\u3002\u9002\u5408\u8bbe\u7f6e reasoning\u3001temperature \u6216\u5176\u4ed6 provider \u5b57\u6bb5\u3002"
      : "Keep this as a JSON object. Use it for reasoning, temperature, or provider-specific request fields.";
  const localizedRequestDefaultsInvalidJson =
    language === "zh-CN"
      ? "Request defaults \u5fc5\u987b\u662f\u53ef\u89e3\u6790\u7684 JSON\u3002"
      : "Request defaults must be valid JSON.";
  const localizedRequestDefaultsInvalidShape =
    language === "zh-CN"
      ? "Request defaults \u5fc5\u987b\u662f JSON object\uff0c\u4e0d\u80fd\u662f array \u6216 string\u3002"
      : "Request defaults must stay a JSON object, not an array or string.";
  const modelCardCopy = providerModelCardCopy(language);
  const localizedModelOriginLive = modelCardCopy.live;
  const localizedModelOriginManual = modelCardCopy.manual;
  const localizedClearModelLimitsLabel =
    language === "zh-CN" ? "清除 limits" : "Clear limits";
  const providerCapabilityGroups = describeProviderCapabilityMatrixGroups(
    {
      modelAliases: provider.modelAliases,
      taskBindings: provider.taskBindings as
        | Record<
            string,
            {
              alias?: string;
              fallbackAliases?: string[];
              requiredCapabilities?: string[];
            }
          >
        | undefined,
      modelCapabilities: provider.modelCapabilities,
      capabilityFlags: provider.capabilities,
    },
    language,
  );
  const requestDefaultsSummary = summarizeProviderRequestDefaults(provider.requestDefaults);
  const cacheTtlSummary = formatDurationSeconds(provider.cacheTtlSeconds);
  const allowedModelsSummary =
    provider.allowedModels && provider.allowedModels.length > 0
      ? compactSummaryValue(provider.allowedModels.slice(0, 4), String(provider.allowedModels.length))
      : undefined;
  const deniedModelsSummary =
    provider.deniedModels && provider.deniedModels.length > 0
      ? compactSummaryValue(provider.deniedModels.slice(0, 4), String(provider.deniedModels.length))
      : undefined;
  const catalogModelsSummary =
    provider.catalogModels && provider.catalogModels.length > 0
      ? compactSummaryValue(provider.catalogModels.slice(0, 4), String(provider.catalogModels.length))
      : undefined;
  const providerCatalogRows = [
    provider.catalogSource
      ? {
          label: localizedCatalogSourceLabel,
          value: provider.catalogSource,
        }
      : null,
    cacheTtlSummary
      ? {
          label: localizedCatalogCacheTtlLabel,
          value: cacheTtlSummary,
        }
      : null,
    provider.embeddingModel
      ? {
          label: localizedCatalogEmbeddingModelLabel,
          value: provider.embeddingModel,
        }
      : null,
    requestDefaultsSummary
      ? {
          label: localizedCatalogRequestDefaultsLabel,
          value: shortenSummary(requestDefaultsSummary, 80),
        }
      : null,
    providerCapabilityGroups.aliases.length > 0
      ? {
          label: localizedCatalogAliasesLabel,
          value: shortenSummary(
            compactSummaryValue(
              providerCapabilityGroups.aliases
                .slice(0, 3)
                .map((entry) => `${entry.label}->${entry.detail}`),
              String(providerCapabilityGroups.aliases.length),
            ),
            80,
          ),
        }
      : null,
    providerCapabilityGroups.taskBindings.length > 0
      ? {
          label: localizedCatalogTaskBindingsLabel,
          value: shortenSummary(
            compactSummaryValue(
              providerCapabilityGroups.taskBindings
                .slice(0, 3)
                .map((entry) => `${entry.label}->${entry.detail}`),
              String(providerCapabilityGroups.taskBindings.length),
            ),
            80,
          ),
        }
      : null,
    allowedModelsSummary
      ? {
          label: localizedCatalogAllowedModelsLabel,
          value: shortenSummary(allowedModelsSummary, 80),
        }
      : null,
    deniedModelsSummary
      ? {
          label: localizedCatalogDeniedModelsLabel,
          value: shortenSummary(deniedModelsSummary, 80),
        }
      : null,
    catalogModelsSummary
      ? {
          label: localizedCatalogSavedModelsLabel[language],
          value: shortenSummary(catalogModelsSummary, 80),
        }
      : null,
  ].filter(
    (
      row,
    ): row is {
      label: string;
      value: string;
    } => Boolean(row),
  );
  const providerCatalogSummary = compactSummaryValue(
    [
      provider.catalogModels && provider.catalogModels.length > 0
        ? `${provider.catalogModels.length} saved models`
        : undefined,
      providerCapabilityGroups.aliases.length > 0
        ? `${providerCapabilityGroups.aliases.length} ${localizedCatalogAliasesLabel.toLowerCase()}`
        : undefined,
      providerCapabilityGroups.taskBindings.length > 0
        ? `${providerCapabilityGroups.taskBindings.length} ${localizedCatalogTaskBindingsLabel.toLowerCase()}`
        : undefined,
      cacheTtlSummary ? `${localizedCatalogCacheTtlLabel} ${cacheTtlSummary}` : undefined,
    ].filter(Boolean) as string[],
    localizedCatalogPanelLabel,
  );
  const draftCredentialMode = providerDraft.credentialMode ?? provider.credentialMode ?? "ui_proxy";
  const draftCatalogSource = providerDraft.catalogSource ?? provider.catalogSource ?? "provider_live";
  const draftCacheTtlSeconds = providerDraft.cacheTtlSeconds ?? provider.cacheTtlSeconds;
  const draftEmbeddingModel = providerDraft.embeddingModel ?? provider.embeddingModel ?? "";
  const draftAllowedModelsText = formatDraftStringList(providerDraft.allowedModels ?? provider.allowedModels);
  const draftDeniedModelsText = formatDraftStringList(providerDraft.deniedModels ?? provider.deniedModels);
  const updateThinkingConfig = (config: ProviderThinkingConfig) => {
    const next = updateProviderThinking(
      {
        protocol: draftProtocol,
        model: providerDraft.model,
        providerName: providerDraft.name,
        baseUrl: providerDraft.baseUrl,
        liveEvidence: lastTest?.capabilityEvidence?.some((entry) =>
          entry.name.trim().toLowerCase() === "thinking" &&
          entry.state === "verified" &&
          entry.observed === true,
        ) === true,
      },
      draftRequestDefaults,
      config,
    );
    onProviderDraftChange({ requestDefaults: next });
  };
  const thinkingFieldLabel = thinkingDescriptor?.kind === "reasoning_effort"
    ? labels?.thinkingEffort ?? copy.thinkingEffort
    : thinkingDescriptor?.kind === "thinking_budget"
      ? labels?.thinkingBudget ?? copy.thinkingBudget
      : thinkingDescriptor?.kind === "gemini_thinking"
        ? copy.thinkingBudget
        : copy.thinkingBudget;
  const thinkingControl = thinkingDescriptor ? (
    <details className="settings-sheet__minor-panel" data-testid="native-thinking-control">
      <summary>{labels?.thinking ?? copy.thinking} · {thinkingFieldLabel}</summary>
      <div className="settings-sheet__minor-body settings-sheet__stack settings-sheet__stack--tight">
        <p className="settings-sheet__note settings-sheet__note--compact">{labels?.thinkingDetail ?? copy.thinkingDetail}</p>
        {thinkingDescriptor.disabled ? (
          <p className="settings-sheet__note settings-sheet__note--compact">{labels?.thinkingUnsupported ?? copy.thinkingUnsupported}</p>
        ) : (
          <ChoiceList
            active={thinkingDescriptor.config.mode}
            items={[
            { label: labels?.thinkingOff ?? copy.thinkingOff, value: "disabled" },
            { label: labels?.thinkingAuto ?? copy.thinkingAuto, value: "auto" },
            { label: labels?.thinkingOn ?? copy.thinkingOn, value: "enabled" },
          ]}
          onChange={(value) => updateThinkingConfig({ ...thinkingDescriptor.config, mode: value as ProviderThinkingConfig["mode"] })}
          />
        )}
        <details>
          <summary>{labels?.thinkingAdvanced ?? copy.thinkingAdvanced}</summary>
          <div className="settings-grid settings-grid--form">
            {thinkingDescriptor.kind === "reasoning_effort" ? (
              <label className="settings-field">
                <span>{labels?.thinkingEffort ?? copy.thinkingEffort}</span>
                <select
                  value={thinkingDescriptor.config.reasoningEffort ?? "medium"}
                  onChange={(event) => updateThinkingConfig({ ...thinkingDescriptor.config, mode: "enabled", reasoningEffort: event.target.value as ProviderThinkingConfig["reasoningEffort"] })}
                >
                  {thinkingDescriptor.effortOptions?.map((option) => <option key={option} value={option}>{option}</option>)}
                </select>
              </label>
            ) : (
              <label className="settings-field">
                <span>{labels?.thinkingBudget ?? copy.thinkingBudget}</span>
                <input
                  type="number"
                  min={thinkingDescriptor.budgetMin}
                  max={thinkingDescriptor.budgetMax}
                  value={typeof thinkingDescriptor.config.budgetTokens === "number" ? thinkingDescriptor.config.budgetTokens : ""}
                  onChange={(event) => updateThinkingConfig({ ...thinkingDescriptor.config, mode: "enabled", budgetTokens: parsePositiveIntegerInput(event.target.value) })}
                />
              </label>
            )}
          </div>
        </details>
      </div>
    </details>
  ) : null;
  const handleRequestDefaultsTextChange = (value: string) => {
    setRequestDefaultsText(value);
    if (!value.trim()) {
      setRequestDefaultsError(undefined);
      onProviderDraftChange({ requestDefaults: {} });
      return;
    }

    try {
      const parsed = JSON.parse(value);
      const normalized = asRecord(parsed);
      if (!normalized) {
        setRequestDefaultsError(localizedRequestDefaultsInvalidShape);
        return;
      }
      setRequestDefaultsError(undefined);
      onProviderDraftChange({ requestDefaults: normalized });
    } catch {
      setRequestDefaultsError(localizedRequestDefaultsInvalidJson);
    }
  };
  const modelDiscoveryCopy = providerModelDiscoveryCopy(language);
  const modelListingCompletedForDraft = providerHasDraftChanges
    ? draftModelListingMatches && modelListStatus !== "loading"
    : modelListStatus === "ready" || modelListStatus === "error";
  const shouldShowManualModelFallback =
    availableModels.length === 0 &&
    providerDraftReadyForModelDiscovery &&
    (modelListingCompletedForDraft || modelSelectionNeedsRecovery);
  const shouldShowModelDiscoveryGuidance = !currentDraftModel && availableModels.length === 0;
  const modelDiscoveryGuidance = !shouldShowModelDiscoveryGuidance
    ? undefined
    : !normalizedDraftBaseUrl
      ? modelDiscoveryCopy.missingBaseUrl
      : !providerDraftHasApiKey && !providerDraftCanReuseSavedApiKey
        ? modelDiscoveryCopy.missingApiKey
        : modelListStatus === "loading"
          ? copy.modelFetchLoading
          : shouldShowManualModelFallback
            ? modelListStatus === "error"
              ? `${safeProviderFailureHint} ${modelDiscoveryCopy.manualFallback}`
              : modelDiscoveryCopy.manualFallback
            : modelDiscoveryCopy.modelOptional;
  const modelDiscoveryUsesSavedSelection = Boolean(currentDraftModel || availableModels.length > 0);
  const modelDiscoveryActionLabel = modelDiscoveryUsesSavedSelection
    ? copy.refreshModels
    : modelDiscoveryCopy.findModels;
  const modelDiscoveryActionDetail = modelDiscoveryUsesSavedSelection
    ? modelPickerCopy.refreshListDetail
    : modelDiscoveryCopy.findModelsDetail;
  const modelDiscoveryBlockedReason =
    currentDraftModelPolicyMessage ??
    (!normalizedDraftBaseUrl
      ? modelDiscoveryCopy.missingBaseUrl
      : !providerDraftHasApiKey && !providerDraftCanReuseSavedApiKey
        ? modelDiscoveryCopy.missingApiKey
        : modelListStatus === "loading"
          ? copy.modelFetchLoading
          : modelDiscoveryActionLabel);
  const canRefreshModels = providerDraftReadyForModelDiscovery && modelListStatus !== "loading";
  const canSaveProviderConnection = Boolean(
    onSaveProvider &&
    providerDraftFieldsReady &&
      !currentDraftModelBlockedByPolicy &&
      !providerDraftEditorBlocked &&
      !requestDefaultsTextHasDrift &&
      (providerHasDraftChanges || !providerSaved),
  );
  const saveProviderConnectionLabel = currentDraftModel
    ? modelPickerCopy.saveAndUse(shortenSummary(currentDraftModel, 32))
    : copy.setupAction;
  const saveProviderConnectionTitle = canSaveProviderConnection
    ? currentDraftModel
      ? modelPickerCopy.saveAndUse(currentDraftModel)
      : providerHasDraftChanges
        ? settingsPhrase(language, "saveToApply")
        : copy.setupAction
    : providerDraftEditorBlocked || requestDefaultsTextHasDrift
      ? localizedRequestDefaultsInvalidJson
    : currentDraftModelPolicyMessage
      ? currentDraftModelPolicyMessage
    : !providerDraftFieldsReady
      ? language === "zh-CN"
        ? "\u5148\u586b\u5199\u670d\u52a1\u6839\u5730\u5740\u548c\u6a21\u578b\uff0c\u518d\u4fdd\u5b58\u8fde\u63a5\u3002"
        : "Add the service root and model before saving the connection."
      : providerSaved
        ? language === "zh-CN"
          ? "\u5F53\u524D\u8FDE\u63A5\u5DF2\u4FDD\u5B58\u3002"
          : "This connection is already saved."
        : copy.setupAction;
  const shouldSurfaceRecentTestFailure =
    (providerTestTransportFailed || Boolean(lastTestFailure)) &&
    providerSaved &&
    !providerHasDraftChanges;
  const calmIntro =
    copy.intro ||
    (language === "zh-CN"
      ? "连接与默认项。"
      : "Connection and defaults.");
  const localizedCalmIntro =
    copy.intro && copy.intro !== "Only the most common coach settings here."
      ? copy.intro
      : settingsSupportPhrase(language, "commonIntro");
  const providerPrimaryAction = providerCoachReady
    ? (language === "zh-CN" ? "已可发送。" : "Ready to send.")
    : language === "zh-CN"
      ? providerNeedsApiKey
        ? "缺少 API key。"
        : providerSaved
          ? "连接已保存，等待测试通过。"
          : "填写 provider、protocol、模型和 API key。"
      : providerNeedsApiKey
        ? "Missing API key."
        : providerSaved
          ? "Connection saved; test still needs to pass."
          : savedProviderProfilesAvailable
            ? "Apply a saved profile first."
            : "Fill provider, protocol, base URL, model, and API key.";
  const providerSetupChecks = [
    {
      id: "provider",
      label: copy.provider,
      value: provider.name || providerDraft.name || copy.notConfigured,
      state: provider.name || providerDraft.name ? "ok" : "missing",
    },
    {
      id: "protocol",
      label: settingsSupportPhrase(language, "protocol"),
      value: localizedSelectedProtocolLabel,
      state: draftProtocol === savedProtocol ? "ok" : "warn",
    },
    {
      id: "model",
      label: copy.model,
      value: provider.model || providerDraft.model || copy.notConfigured,
      state: provider.model || providerDraft.model ? "ok" : "missing",
    },
    {
      id: "key",
      label: copy.apiKey,
      value: providerApiKeyDraftStatus.value,
      state: providerApiKeyDraftStatus.state,
    },
    {
      id: "test",
      label: copy.lastTest,
      value: lastTestLabel,
      state: providerTestPending ? "warn" : providerTestPassed ? "ok" : provider.configured ? "warn" : "missing",
    },
  ];
  const coachCapabilityLabel = providerCoachReady
    ? language === "zh-CN"
      ? "已就绪"
      : "Ready"
    : providerNeedsApiKey
      ? language === "zh-CN"
        ? "缺少密钥"
        : "Missing key"
      : providerSaved
        ? language === "zh-CN"
          ? "被阻塞"
          : "Blocked"
        : language === "zh-CN"
          ? "待配置"
          : "Setup";
  const coachCapabilityTone = providerCoachReady ? "connected" : providerNeedsApiKey ? "warn" : providerSaved ? "warn" : "offline";
  const imageCapabilityLabel = imageInputState.supported
    ? language === "zh-CN"
      ? "已就绪"
      : "Ready"
    : imageInputState.status === "setup_required"
      ? language === "zh-CN"
        ? "待配置"
        : "Setup"
      : language === "zh-CN"
        ? "未开启"
        : "Off";
  const imageCapabilityTone = imageInputState.supported
    ? "connected"
    : imageInputState.status === "setup_required"
      ? "pending"
      : "warn";
  const imageCapabilityDetail =
    imageInputState.detail ?? imageInputState.reason ?? (language === "zh-CN" ? "未验证图片输入。" : "Image input not verified.");
  const availabilityTone: "connected" | "pending" | "warn" | "offline" = providerHasDraftChanges
    ? currentDraftModelBlockedByPolicy
      ? "warn"
      : "pending"
    : providerCoachReady
      ? "connected"
      : providerSaved
        ? "warn"
        : "offline";
  const availabilityStatusLabel = providerHasDraftChanges
    ? language === "zh-CN"
      ? "草稿未生效"
      : "Draft not applied"
    : providerCoachReady
      ? runtimeStatusLabel
      : providerStatusLabel;
  const availabilityHeadline = providerHasDraftChanges && currentDraftModelPolicyMessage
    ? settingsPhrase(language, "chooseModel")
    : providerHasDraftChanges
      ? language === "zh-CN"
      ? "连接草稿未保存"
      : "Connection draft not saved"
    : providerCoachReady
      ? language === "zh-CN"
        ? "模型可用"
        : "Model ready"
      : providerNeedsApiKey
        ? language === "zh-CN"
          ? "缺少 API key"
          : "API key required"
        : providerSaved
          ? language === "zh-CN"
            ? "连接待验证"
            : "Connection needs test"
          : language === "zh-CN"
            ? "设置模型连接"
            : "Set up model access";
  const availabilityDetail = providerHasDraftChanges && currentDraftModelPolicyMessage
    ? currentDraftModelPolicyMessage
    : providerHasDraftChanges
      ? providerDraftReadyForTest
        ? language === "zh-CN"
          ? "当前草稿已经可以测试。保存后会成为当前连接。"
          : "This draft can be tested now. Save when you want to apply it."
        : language === "zh-CN"
          ? "保存后测试。"
          : "Save before testing."
      : providerCoachReady
      ? language === "zh-CN"
        ? "对话、计划、训练使用此连接。"
        : "Chat, plan, and training use this connection."
      : providerRequirementNote ?? providerPrimaryAction;
  const availabilityPrimaryLabel = providerHasDraftChanges
    ? language === "zh-CN"
      ? "保存草稿"
      : "Save draft"
    : providerCoachReady
      ? language === "zh-CN"
        ? "重新测试"
        : "Test again"
      : providerSaved && providerNeedsApiKey
        ? language === "zh-CN"
          ? "补上 API key"
          : "Add API key"
        : copy.setupAction;
  const availabilityPrimaryDetail = providerCoachReady && !providerHasDraftChanges
    ? language === "zh-CN"
      ? "测试当前连接"
      : "Test current connection"
    : language === "zh-CN"
      ? "保存后生效"
      : "Save to apply";
  const availabilityPrimaryIcon = providerCoachReady && !providerHasDraftChanges
    ? <DiagnosticsIcon size={14} />
    : <CheckMarkIcon size={14} />;
  const availabilityPrimaryAction = providerCoachReady && !providerHasDraftChanges
    ? onTestProvider
    : onSaveProvider;
  const canRetestProvider = providerDraftReadyForTest && !providerTestPending;
  const providerNeedsFirstTest =
    providerSaved && provider.apiKeyConfigured && !providerHasDraftChanges && !lastTest?.checkedAt;
  const providerNeedsRetest =
    providerSaved &&
    provider.apiKeyConfigured &&
    !providerHasDraftChanges &&
    !shouldSurfaceRecentTestFailure &&
    (providerNeedsFirstTest ||
      providerTestFreshness !== "fresh" ||
      (lastTest?.ok === true && (!providerTestReadiness.ready || !providerStreamingReady)));
  const resolvedCoachCapabilityLabel =
    shouldSurfaceRecentTestFailure ||
    coachSendState.status === "degraded_error" ||
    coachSendState.status === "blocked_error"
      ? providerFailureState.statusLabel
      : providerNeedsRetest
        ? settingsStatusPhrase(language, "needsAttention")
      : coachSendState.status === "warming"
        ? language === "zh-CN"
          ? "\u68C0\u67E5\u4E2D"
          : "Checking"
        : coachCapabilityLabel;
  const resolvedCoachCapabilityTone =
    shouldSurfaceRecentTestFailure ||
    coachSendState.status === "degraded_error" ||
    coachSendState.status === "blocked_error"
      ? "warn"
      : providerNeedsRetest
        ? "warn"
      : coachSendState.status === "warming"
        ? "pending"
        : coachCapabilityTone;
  const resolvedCoachCapabilityDetail =
    shouldSurfaceRecentTestFailure ||
    coachSendState.status === "degraded_error" ||
    coachSendState.status === "blocked_error"
      ? availabilityFailureHint ?? providerCoachBlockReason ?? providerPrimaryAction
      : providerNeedsRetest
        ? settingsStatusPhrase(language, "connectionSavedNeedsTest")
      : providerCoachReady
        ? language === "zh-CN"
          ? "\u53EF\u53D1\u9001"
          : "Send enabled"
        : coachSendState.status === "warming"
          ? settingsStatusPhrase(language, "checking")
          : providerCoachBlockReason ?? providerPrimaryAction;
  const availabilityMode: ProviderSendStateStatus | "draft" | "recent_failure" | "needs_test" = providerHasDraftChanges
    ? "draft"
    : providerTestPending
      ? "warming"
      : shouldSurfaceRecentTestFailure
        ? "recent_failure"
        : providerNeedsRetest
          ? "needs_test"
          : coachSendState.status;
  const resolvedAvailabilityTone: "connected" | "pending" | "warn" | "offline" =
    availabilityMode === "draft"
      ? currentDraftModelBlockedByPolicy
        ? "warn"
        : "pending"
      : availabilityMode === "needs_test"
        ? "warn"
      : availabilityMode === "ready"
        ? "connected"
        : availabilityMode === "warming" || availabilityMode === "refreshing"
          ? "pending"
          : availabilityMode === "missing_provider"
            ? "offline"
            : "warn";
  const resolvedAvailabilityStatusLabel =
    availabilityMode === "draft"
      ? language === "zh-CN"
        ? "草稿未生效"
        : "Draft not applied"
      : availabilityMode === "needs_test"
        ? settingsStatusPhrase(language, "needsAttention")
      : availabilityMode === "ready"
        ? language === "zh-CN"
          ? "可发送"
          : "Ready"
        : availabilityMode === "refreshing"
          ? language === "zh-CN"
            ? "刷新中"
            : "Refreshing"
          : availabilityMode === "warming"
            ? language === "zh-CN"
              ? "检查中"
              : "Checking"
            : availabilityMode === "missing_api_key"
              ? language === "zh-CN"
                ? "缺少密钥"
                : "Add API key"
              : availabilityMode === "missing_provider"
                ? language === "zh-CN"
                  ? "待配置"
                  : "Setup"
                : providerFailureState.statusLabel;
  const resolvedAvailabilityHeadline =
    availabilityMode === "draft" && currentDraftModelPolicyMessage
      ? settingsPhrase(language, "chooseModel")
      : availabilityMode === "draft"
        ? language === "zh-CN"
        ? "连接草稿尚未保存"
        : "Connection draft not saved"
      : availabilityMode === "needs_test"
        ? settingsStatusPhrase(language, "connectionNeedsTest")
      : availabilityMode === "ready"
        ? language === "zh-CN"
          ? "模型可用"
          : "Model ready"
        : availabilityMode === "refreshing"
          ? language === "zh-CN"
            ? "正在刷新模型列表"
            : "Refreshing model list"
          : availabilityMode === "warming"
            ? language === "zh-CN"
              ? "正在确认保存的连接"
              : "Checking saved connection"
            : availabilityMode === "missing_api_key"
              ? language === "zh-CN"
                ? "缺少 API key"
                : "API key required"
              : availabilityMode === "missing_provider"
                ? language === "zh-CN"
                  ? "设置模型连接"
                  : "Set up model access"
                : providerFailureState.headline;
  const resolvedAvailabilityDetail =
    availabilityMode === "draft" && currentDraftModelPolicyMessage
      ? currentDraftModelPolicyMessage
      : availabilityMode === "draft"
        ? providerDraftReadyForTest
          ? language === "zh-CN"
            ? "当前草稿已经可以测试。保存后会成为当前连接。"
            : "This draft can be tested now. Save when you want to apply it."
          : language === "zh-CN"
            ? "保存后再测试。"
            : "Save before testing."
        : availabilityMode === "needs_test"
        ? settingsStatusPhrase(language, "connectionSavedNeedsTest")
      : availabilityMode === "ready"
        ? language === "zh-CN"
          ? "对话、计划和训练都会使用这组连接。"
          : "Chat, plan, and training use this connection."
          : availabilityMode === "refreshing"
            ? settingsStatusPhrase(language, "refreshing")
            : availabilityMode === "warming"
              ? settingsStatusPhrase(language, "checking")
            : availabilityMode === "degraded_error"
              ? availabilityFailureHint ?? providerPrimaryAction
              : availabilityMode === "recent_failure"
                ? availabilityFailureHint ?? providerPrimaryAction
                : availabilityMode === "blocked_error"
                  ? availabilityFailureHint ?? providerRequirementNote ?? providerPrimaryAction
                  : providerRequirementNote ?? providerPrimaryAction;
  const localizedCoachCapabilityLabel =
    providerCoachReady
      ? settingsStatusPhrase(language, "ready")
      : providerNeedsRetest
        ? settingsStatusPhrase(language, "needsAttention")
      : providerNeedsApiKey
        ? settingsStatusPhrase(language, "missingKey")
        : providerSaved
          ? settingsStatusPhrase(language, "blocked")
          : settingsStatusPhrase(language, "setup");
  const localizedImageCapabilityLabel = imageInputState.supported
    ? settingsStatusPhrase(language, "ready")
    : imageInputState.status === "setup_required"
      ? settingsStatusPhrase(language, "setup")
      : settingsStatusPhrase(language, "off");
  const localizedImageCapabilityDetail =
    imageInputState.detail ?? imageInputState.reason ?? settingsStatusPhrase(language, "imageInputNotVerified");
  const localizedResolvedCoachCapabilityLabel =
    shouldSurfaceRecentTestFailure ||
    coachSendState.status === "degraded_error" ||
    coachSendState.status === "blocked_error"
      ? providerFailureState.statusLabel
      : providerNeedsRetest
        ? settingsStatusPhrase(language, "needsAttention")
      : coachSendState.status === "warming"
        ? settingsStatusPhrase(language, "checking")
        : localizedCoachCapabilityLabel;
  const localizedResolvedCoachCapabilityDetail =
    shouldSurfaceRecentTestFailure ||
    coachSendState.status === "degraded_error" ||
    coachSendState.status === "blocked_error"
      ? availabilityFailureHint ?? providerCoachBlockReason ?? providerPrimaryAction
      : providerNeedsRetest
        ? settingsStatusPhrase(language, "connectionSavedNeedsTest")
      : providerCoachReady
        ? settingsStatusPhrase(language, "sendEnabled")
        : coachSendState.status === "warming"
          ? settingsStatusPhrase(language, "checking")
          : providerCoachBlockReason ?? providerPrimaryAction;
  const localizedResolvedAvailabilityStatusLabel =
    availabilityMode === "draft"
      ? settingsStatusPhrase(language, "draftNotApplied")
      : availabilityMode === "needs_test"
        ? settingsStatusPhrase(language, "needsAttention")
      : availabilityMode === "ready"
        ? settingsStatusPhrase(language, "ready")
        : availabilityMode === "refreshing"
          ? settingsStatusPhrase(language, "refreshing")
          : availabilityMode === "warming"
            ? settingsStatusPhrase(language, "checking")
            : availabilityMode === "missing_api_key"
              ? settingsPhrase(language, "addApiKey")
              : availabilityMode === "missing_provider"
                ? settingsStatusPhrase(language, "setup")
                : providerFailureState.statusLabel;
  const localizedResolvedAvailabilityHeadline =
    availabilityMode === "draft" && currentDraftModelPolicyMessage
      ? settingsPhrase(language, "chooseModel")
      : availabilityMode === "draft"
        ? settingsStatusPhrase(language, "connectionDraftNotSaved")
      : availabilityMode === "needs_test"
        ? settingsStatusPhrase(language, "connectionNeedsTest")
      : availabilityMode === "ready"
        ? settingsStatusPhrase(language, "modelReady")
        : availabilityMode === "refreshing"
          ? settingsStatusPhrase(language, "refreshing")
          : availabilityMode === "warming"
            ? settingsStatusPhrase(language, "checking")
            : availabilityMode === "missing_api_key"
              ? settingsStatusPhrase(language, "apiKeyRequired")
              : availabilityMode === "missing_provider"
                ? settingsStatusPhrase(language, "setupModelAccess")
                : providerFailureState.headline;
  const readyAvailabilityScopeDetail = `${copy.currentWorkspace} \u00b7 ${settingsStatusPhrase(
    language,
    "chatPlanTrainingUseThisConnection",
  )}`;
  const localizedResolvedAvailabilityDetail =
    availabilityMode === "draft" && currentDraftModelPolicyMessage
      ? currentDraftModelPolicyMessage
      : availabilityMode === "draft"
        ? providerDraftReadyForTest
          ? language === "zh-CN"
            ? "当前草稿已经可以测试。保存后会成为当前连接。"
            : "This draft can be tested now. Save when you want to apply it."
          : settingsStatusPhrase(language, "saveBeforeTesting")
        : availabilityMode === "needs_test"
        ? settingsStatusPhrase(language, "connectionSavedNeedsTest")
      : availabilityMode === "ready"
        ? readyAvailabilityScopeDetail
          : availabilityMode === "refreshing"
          ? settingsStatusPhrase(language, "refreshing")
          : availabilityMode === "warming"
            ? settingsStatusPhrase(language, "checking")
            : availabilityMode === "degraded_error"
              ? availabilityFailureHint ?? providerPrimaryAction
              : availabilityMode === "recent_failure"
                ? availabilityFailureHint ?? providerPrimaryAction
                : availabilityMode === "blocked_error"
                  ? availabilityFailureHint ?? providerRequirementNote ?? providerPrimaryAction
                  : providerRequirementNote ??
                    (providerNeedsApiKey
                      ? settingsStatusPhrase(language, "connectionSavedApiKeyMissing")
                      : providerSaved
                        ? settingsStatusPhrase(language, "connectionSavedNeedsTest")
                        : settingsStatusPhrase(language, "fillProviderFields"));
  const canApplyMiniMaxRecovery =
    miniMaxLikeProvider && Boolean(onUseProviderTemplate) && !providerHasDraftChanges;
  const shouldOfferMiniMaxDefaults =
    canApplyMiniMaxRecovery &&
    (providerFailureCategory === "model_not_found" || providerFailureCategory === "model_unsupported" || providerFailureCategory === "model_not_supported");
  const shouldOfferMiniMaxKeyReset =
    canApplyMiniMaxRecovery &&
    (providerFailureCategory === "invalid_key_or_permission" ||
      providerFailureCategory === "invalid_api_key" ||
      providerFailureCategory === "authentication_failed");
  useEffect(() => {
    if (!providerProfilesFocusRequested) {
      return;
    }

    const frameId = window.requestAnimationFrame(() => {
      const panel = providerProfilesPanelRef.current;
      if (!panel) {
        return;
      }

      const providerDetails = panel.closest<HTMLDetailsElement>(
        ".coach-settings-view__provider-detail",
      );
      if (providerDetails) {
        providerDetails.open = true;
      }
      panel.open = true;
      panel.scrollIntoView({ block: "nearest" });
      const nextButton = panel.querySelector<HTMLButtonElement>(
        ".settings-provider-profile:not(:disabled)",
      );
      nextButton?.focus();
      setProviderProfilesFocusRequested(false);
    });

    return () => window.cancelAnimationFrame(frameId);
  }, [providerProfiles.length, providerProfilesFocusRequested]);

  const openSavedProviderProfiles = () => {
    setProviderDetailRequested(true);
    setProviderProfilesFocusRequested(true);
  };

  useEffect(() => {
    if (!providerApiKeyFocusRequested) {
      return;
    }

    const frameId = window.requestAnimationFrame(() => {
      const apiKeyInput = apiKeyInputRef.current;
      const providerDetails = apiKeyInput?.closest<HTMLDetailsElement>(
        ".coach-settings-view__provider-detail",
      );
      const connectionFields = apiKeyInput?.closest<HTMLDetailsElement>(
        ".settings-sheet__minor-panel",
      );
      if (providerDetails) {
        providerDetails.open = true;
      }
      if (connectionFields) {
        connectionFields.open = true;
      }
      apiKeyInput?.scrollIntoView({ block: "center" });
      apiKeyInput?.focus({ preventScroll: true });
      setProviderApiKeyFocusRequested(false);
    });

    return () => window.cancelAnimationFrame(frameId);
  }, [providerApiKeyFocusRequested, providerDetailRequested]);

  const openProviderDetails = (focusApiKey = false) => {
    setProviderDetailRequested(true);
    if (focusApiKey) {
      setProviderApiKeyFocusRequested(true);
    }
  };
  const openProviderApiKey = () => openProviderDetails(true);
  const focusDraftModelPicker = () => {
    setProviderDetailRequested(true);
    setModelPickerOpen(true);
    window.requestAnimationFrame(() => {
      const picker = modelPickerRef.current;
      if (!picker) {
        return;
      }
      picker.scrollIntoView({ block: "nearest" });
      if (showModelSearchInput) {
        modelSearchInputRef.current?.focus();
        return;
      }
      modelSelectRef.current?.focus();
    });
  };
  const shouldRoutePrimaryToSavedProfiles =
    !providerHasDraftChanges && !providerSaved && savedProviderProfilesAvailable;
  const shouldOfferRecommendedProviderTemplate =
    Boolean(onUseProviderTemplate) &&
    !providerSaved &&
    !providerHasDraftChanges &&
    !savedProviderProfilesAvailable;
  const shouldOpenProviderDetails =
    !providerHasDraftChanges &&
    !providerSaved &&
    !shouldRoutePrimaryToSavedProfiles &&
    !shouldOfferRecommendedProviderTemplate;
  const draftNeedsModelChoice = providerHasDraftChanges && !currentDraftModel;
  const hasDiscoveredDraftModels = draftNeedsModelChoice && availableModels.length > 0;
  const canFindDraftModels = draftNeedsModelChoice && !hasDiscoveredDraftModels && canRefreshModels;
  const modelDiscoveryGuidanceActive = canFindDraftModels || hasDiscoveredDraftModels;
  const showSecondaryModelDiscoveryAction = !canFindDraftModels;
  const showProviderDetailActions =
    !modelDiscoveryGuidanceActive || showSecondaryModelDiscoveryAction;
  const shouldRepairDraftModelPolicy =
    providerHasDraftChanges && currentDraftModelBlockedByPolicy;
  const shouldFocusDraftApiKey =
    providerHasDraftChanges &&
    providerDraftFieldsReady &&
    !providerDraftHasApiKey &&
    !providerDraftCanReuseSavedApiKey;
  const shouldCompleteDraftSetup =
    providerHasDraftChanges &&
    !providerDraftReadyForTest &&
    !canFindDraftModels &&
    !hasDiscoveredDraftModels;
  const shouldWaitForDraftTest = providerHasDraftChanges && providerTestPending;
  const shouldRepairProviderCredentials =
    providerCredentialsRejected && !providerHasDraftChanges && !providerTestPassed;
  const workspaceRootMissing =
    !trainerWorkspace?.rootPath?.trim() || trainerWorkspace?.status === "root-missing";
  const displayAvailabilityHeadline = workspaceRootMissing
    ? language === "zh-CN"
      ? "先选工作区根目录"
      : "Choose a workspace root"
    : shouldOfferRecommendedProviderTemplate
    ? settingsPhrase(language, "useMiniMaxProfile")
    : shouldRoutePrimaryToSavedProfiles
      ? language === "zh-CN"
        ? "先应用一个已保存的 profile"
        : "Apply a saved profile first"
      : localizedResolvedAvailabilityHeadline;
  const displayAvailabilityDetail = workspaceRootMissing
    ? language === "zh-CN"
      ? "没有根目录，对话和训练会空转。"
      : "Without a workspace root, Coach and Training cannot work."
    : shouldOfferRecommendedProviderTemplate
    ? settingsPhrase(language, "useMiniMaxProfileDetail")
    : shouldRoutePrimaryToSavedProfiles
      ? language === "zh-CN"
        ? "当前工作区还没有启用中的 provider，但下面已经有可复用的 profiles。"
        : "This workspace has no active provider yet, but reusable profiles are already available below."
      : localizedResolvedAvailabilityDetail;
  const showAvailabilityPrimaryAction =
    workspaceRootMissing || availabilityMode !== "ready" || Boolean(onTestProvider);
  const resolvedAvailabilityPrimaryLabel = canFindDraftModels
    ? modelDiscoveryActionLabel
    : hasDiscoveredDraftModels
      ? settingsPhrase(language, "chooseModel")
      : shouldRepairDraftModelPolicy
        ? settingsPhrase(language, "chooseModel")
      : shouldFocusDraftApiKey
        ? settingsPhrase(language, "addApiKey")
      : shouldCompleteDraftSetup
      ? settingsPhrase(language, "connectionFieldsAndKey")
      : shouldWaitForDraftTest
        ? settingsStatusPhrase(language, "checking")
        : shouldRepairProviderCredentials
          ? settingsPhrase(language, "reenterMiniMaxKey")
        : providerHasDraftChanges && canSaveProviderConnection
          ? saveProviderConnectionLabel
          : providerHasDraftChanges
          ? settingsPhrase(language, "testDraftConnection")
          : shouldOfferMiniMaxDefaults
            ? settingsPhrase(language, "useMiniMaxDefaults")
            : shouldOfferMiniMaxKeyReset
              ? settingsPhrase(language, "reenterMiniMaxKey")
              : providerNeedsRetest
                ? copy.test
                : shouldRoutePrimaryToSavedProfiles
                  ? language === "zh-CN"
                    ? "\u6253\u5F00 profiles"
                    : "Open profiles"
                  : canRetestProvider
                    ? settingsPhrase(language, "testAgain")
                    : providerSaved && providerNeedsApiKey
                      ? settingsPhrase(language, "addApiKey")
                      : shouldOpenProviderDetails
                        ? settingsPhrase(language, "connectionFieldsAndKey")
                        : copy.setupAction;
  const resolvedAvailabilityPrimaryDetail = canFindDraftModels
    ? modelDiscoveryActionDetail
    : hasDiscoveredDraftModels
      ? settingsPhrase(language, "chooseModelDetail")
      : shouldRepairDraftModelPolicy
        ? currentDraftModelPolicyMessage ?? modelDiscoveryBlockedReason
      : shouldFocusDraftApiKey
        ? settingsPhrase(language, "addApiKeyDetail")
      : shouldCompleteDraftSetup
      ? modelDiscoveryBlockedReason
      : shouldWaitForDraftTest
        ? settingsStatusPhrase(language, "checking")
        : shouldRepairProviderCredentials
          ? settingsPhrase(language, "addApiKeyDetail")
        : providerHasDraftChanges && canSaveProviderConnection
          ? settingsPhrase(language, "saveToApply")
          : providerHasDraftChanges
          ? settingsPhrase(language, "testDraftConnectionDetail")
          : providerNeedsRetest
            ? settingsPhrase(language, "verifyConnectionDetail")
            : canRetestProvider
              ? shouldOfferMiniMaxDefaults
                ? settingsPhrase(language, "useMiniMaxDefaultsDetail")
                : shouldOfferMiniMaxKeyReset
                  ? settingsPhrase(language, "reenterMiniMaxKeyDetail")
                  : settingsPhrase(language, "testCurrentConnection")
              : shouldRoutePrimaryToSavedProfiles
                ? language === "zh-CN"
                  ? "\u76F4\u63A5\u6253\u5F00\u4E0B\u65B9\u7684 profiles\u3002"
                  : "Open the saved profiles below."
                : shouldOpenProviderDetails
                  ? copy.modelHint
                  : settingsPhrase(language, "saveToApply");
  const resolvedAvailabilityPrimaryIcon =
    canFindDraftModels
      ? <RefreshIcon size={14} />
      : hasDiscoveredDraftModels
        ? <CheckMarkIcon size={14} />
        : shouldRepairDraftModelPolicy
          ? <GearIcon size={14} />
        : shouldFocusDraftApiKey
          ? <GearIcon size={14} />
        : shouldCompleteDraftSetup
        ? <GearIcon size={14} />
        : shouldWaitForDraftTest
          ? <RefreshIcon size={14} />
          : shouldRepairProviderCredentials
            ? <GearIcon size={14} />
          : shouldOfferMiniMaxDefaults || shouldOfferMiniMaxKeyReset
            ? <LightningIcon size={14} />
            : canRetestProvider
              ? <RefreshIcon size={14} />
              : shouldOpenProviderDetails
                ? <GearIcon size={14} />
                : <CheckMarkIcon size={14} />;
  const resolvedAvailabilityPrimaryAction =
    canFindDraftModels
      ? onRefreshProviderModels
      : hasDiscoveredDraftModels
        ? focusDraftModelPicker
        : shouldRepairDraftModelPolicy
          ? focusDraftModelPicker
        : shouldFocusDraftApiKey
          ? openProviderApiKey
        : shouldCompleteDraftSetup
        ? openProviderDetails
        : shouldWaitForDraftTest
          ? undefined
          : shouldRepairProviderCredentials
            ? openProviderApiKey
          : shouldOfferMiniMaxDefaults || shouldOfferMiniMaxKeyReset
            ? onUseProviderTemplate
            : shouldRoutePrimaryToSavedProfiles
              ? openSavedProviderProfiles
              : providerHasDraftChanges && canSaveProviderConnection
                ? onSaveProvider
              : canRetestProvider
                ? onTestProvider
                : shouldOpenProviderDetails
                  ? openProviderDetails
                  : onSaveProvider;
  const canOfferMiniMaxRecoveryAction =
    canRetestProvider && miniMaxLikeProvider && Boolean(onUseProviderTemplate);
  const canRestartSidecar =
    providerFailureCategory === "sidecar_unavailable" && Boolean(onRestartSidecar);
  const effectiveAvailabilityPrimaryCta: {
    label: string;
    detail: string;
    icon: ReactNode;
    action?: (() => void) | undefined;
  } =
    workspaceRootMissing && onChooseTrainerWorkspaceRoot
      ? {
          label: language === "zh-CN" ? "选择工作区根目录" : "Choose workspace root",
          detail:
            language === "zh-CN"
              ? "没有根目录，对话和训练会空转。"
              : "Without a workspace root, Coach and Training cannot work.",
          icon: <FolderIcon size={14} />,
          action: onChooseTrainerWorkspaceRoot,
        }
    : shouldOfferRecommendedProviderTemplate
      ? {
          label: settingsPhrase(language, "useMiniMaxProfile"),
          detail: settingsPhrase(language, "useMiniMaxProfileDetail"),
          icon: <LightningIcon size={14} />,
          action: onUseProviderTemplate,
        }
      : canRestartSidecar
        ? {
            ...sidecarRestartCopy(language),
            icon: <RefreshIcon size={14} />,
            action: onRestartSidecar,
          }
        : canOfferMiniMaxRecoveryAction && providerFailureCategory === "model_not_found"
          ? {
              label: settingsPhrase(language, "useMiniMaxDefaults"),
              detail: settingsPhrase(language, "useMiniMaxDefaultsDetail"),
              icon: <LightningIcon size={14} />,
              action: onUseProviderTemplate,
            }
          : canOfferMiniMaxRecoveryAction &&
              (providerFailureCategory === "model_unsupported" ||
                providerFailureCategory === "model_not_supported")
            ? {
                label: settingsPhrase(language, "useMiniMaxDefaults"),
                detail: settingsPhrase(language, "useMiniMaxDefaultsDetail"),
                icon: <LightningIcon size={14} />,
                action: onUseProviderTemplate,
              }
            : shouldRepairProviderCredentials
              ? {
                  label: settingsPhrase(language, "reenterMiniMaxKey"),
                  detail: settingsPhrase(language, "addApiKeyDetail"),
                  icon: <GearIcon size={14} />,
                  action: openProviderApiKey,
                }
              : canOfferMiniMaxRecoveryAction &&
                  (providerFailureCategory === "invalid_key_or_permission" ||
                    providerFailureCategory === "invalid_api_key" ||
                    providerFailureCategory === "authentication_failed")
                ? {
                    label: settingsPhrase(language, "reenterMiniMaxKey"),
                    detail: settingsPhrase(language, "reenterMiniMaxKeyDetail"),
                    icon: <LightningIcon size={14} />,
                    action: onUseProviderTemplate,
                  }
                : providerSaved && providerNeedsApiKey && !providerHasDraftChanges
                  ? {
                      label: settingsPhrase(language, "addApiKey"),
                      detail: settingsPhrase(language, "addApiKeyDetail"),
                      icon: <CheckMarkIcon size={14} />,
                      action: openProviderApiKey,
                    }
                  : {
                      label: resolvedAvailabilityPrimaryLabel,
                      detail: resolvedAvailabilityPrimaryDetail,
                      icon: resolvedAvailabilityPrimaryIcon,
                      action: resolvedAvailabilityPrimaryAction,
                    };
  const showProviderDetailTestAction =
    !canRetestProvider || effectiveAvailabilityPrimaryCta.action !== onTestProvider;
  const effectiveAvailabilityPrimaryTone =
    availabilityMode === "ready" && !providerHasDraftChanges ? "ghost" : "accent";
  const appliedProviderFactValue =
    (providerSaved
      ? provider.profileLabel?.trim() || provider.name?.trim()
      : providerHasDraftChanges
        ? providerDraft.name.trim()
        : undefined) ||
    copy.notConfigured;
  const appliedProviderFactDetail = compactSummaryValue(
    [
      providerSaved || providerHasDraftChanges ? localizedSelectedProtocolLabel : undefined,
      providerSaved ? provider.baseUrl?.trim() : providerHasDraftChanges ? providerDraft.baseUrl.trim() : undefined,
    ].filter(Boolean) as string[],
    providerSummaryText,
  );
  const appliedModelFactValue =
    (providerSaved
      ? provider.resolvedModel?.trim() || provider.model?.trim()
      : providerHasDraftChanges
        ? providerDraft.model.trim()
        : undefined) ||
    copy.notConfigured;
  const appliedModelLimit = readProviderModelTokenLimit(provider.modelTokenLimits, appliedModelFactValue);
  const appliedModelFactDetail = compactSummaryValue(
    [
      copy.detectedModel,
      appliedModelLimit?.contextWindowTokens ? `ctx ${appliedModelLimit.contextWindowTokens}` : undefined,
      appliedModelLimit?.maxOutputTokens ? `out ${appliedModelLimit.maxOutputTokens}` : undefined,
      provider.contextWindowTokens ? `ctx ${provider.contextWindowTokens}` : undefined,
      provider.maxOutputTokens ? `out ${provider.maxOutputTokens}` : undefined,
    ].filter(Boolean) as string[],
    providerSummaryText,
  );
  const providerPreviewSummaryText = shortenSummary(
    compactSummaryValue(
      [
        availabilityMode === "ready" ? copy.currentWorkspace : undefined,
        providerHasDraftChanges ? (language === "zh-CN" ? "草稿中" : "Draft") : undefined,
        appliedProviderFactValue !== copy.notConfigured ? appliedProviderFactValue : undefined,
        appliedModelFactValue !== copy.notConfigured ? appliedModelFactValue : undefined,
      ].filter(Boolean) as string[],
      providerSummaryText,
    ),
    44,
  );
  const shouldShowProviderConnectionSummary = providerSaved || providerHasDraftChanges;
  const availabilityFacts = [
    {
      id: "provider",
      label: copy.provider,
      value: appliedProviderFactValue,
      tone: providerHasDraftChanges ? "pending" : provider.configured ? "connected" : "offline",
      detail: appliedProviderFactDetail,
      presentation: "text" as const,
    },
    {
      id: "model",
      label: copy.model,
      value: appliedModelFactValue,
      tone:
        providerHasDraftChanges
          ? "pending"
          : provider.resolvedModel?.trim() || provider.model?.trim()
            ? "connected"
            : "offline",
      detail: appliedModelFactDetail,
      presentation: "text" as const,
    },
    {
      id: "test",
      label: copy.lastTest,
      value: lastTestLabel,
      tone: providerTestPassed ? "connected" : providerSaved ? "warn" : "offline",
      detail: localizedLastTestDetailText ?? settingsPhrase(language, "notTested"),
      presentation: "pill" as const,
    },
  ] as const;
  const shouldShowAvailabilityFacts = providerSaved;
  const showAvailabilityChecklist =
    providerHasDraftChanges || (!providerCoachReady && !shouldRoutePrimaryToSavedProfiles);
  const renderProviderSetupChecks = (className: string) => (
    <div
      className={`settings-setup-checks ${className}`.trim()}
      aria-label={settingsPhrase(language, "connectionChecklist")}
    >
      {providerSetupChecks.map((item) => (
        <div key={item.id} className={`settings-setup-check is-${item.state}`}>
          <span className="settings-setup-check__dot" aria-hidden="true" />
          <span className="settings-setup-check__label">{item.label}</span>
          <strong>{item.value}</strong>
        </div>
      ))}
    </div>
  );
  const showCoachDefaultsStatePill = coachDefaultsStatus?.saveState === "unsaved";
  const teachingPrefsDirty =
    coachDefaultsStatus?.saveState === "unsaved" || workspaceControlStatus?.saveState === "unsaved";
  const memoryPrivacyDirty = coachDefaultsStatus?.saveState === "unsaved";
  const connectionDirty = providerStatus?.saveState === "unsaved";
  const settingsStatusConnectionReady = providerCoachReady && !providerHasDraftChanges;
  // Status summary bar anomalies — same truth sources as the availability strip.
  const settingsStatusIssues: Array<{
    id: "key" | "test" | "trust" | "unsaved";
    label: string;
    target: "connection" | "teaching" | "memory";
  }> = [];
  if (providerNeedsApiKey || coachSendState.status === "missing_api_key") {
    settingsStatusIssues.push({
      id: "key",
      label: settingsGlobalCopy.settingsStatusNoApiKey,
      target: "connection",
    });
  } else if (providerSaved && !providerTestPassed) {
    settingsStatusIssues.push({
      id: "test",
      label: settingsGlobalCopy.settingsStatusNeedsTest,
      target: "connection",
    });
  }
  if (resolvedWorkspaceTrustState !== "trusted") {
    settingsStatusIssues.push({
      id: "trust",
      label: settingsGlobalCopy.settingsStatusTrust,
      target: "memory",
    });
  }
  if (connectionDirty || teachingPrefsDirty) {
    settingsStatusIssues.push({
      id: "unsaved",
      label: settingsGlobalCopy.settingsStatusUnsaved,
      target: "teaching",
    });
  }
  const providerConnectionSummary =
    `${settingsPhrase(language, "currentConnectionPrefix")}: ${providerSummary}`;
  const coachBehaviorSummary = shortenSummary(
    compactSummaryValue(
      answerMode === "auto" && teachingStyle === "auto"
        ? [LANGUAGE_LABELS[language], copy.auto]
        : [
            LANGUAGE_LABELS[language],
            answerMode === "auto"
              ? adaptiveBehaviorLabel(language, "answer")
              : answerMode === "coach-first"
                ? copy.coachFirst
                : answerMode === "balanced"
                  ? copy.balanced
                  : copy.direct,
            teachingStyle === "auto"
              ? adaptiveBehaviorLabel(language, "teaching")
              : teachingStyleItems.find((item) => item.value === teachingStyle)?.label ?? copy.auto,
          ],
      copy.off,
    ),
    36,
  );
  const contextBehaviorSummary = followCurrentFile ? copy.followCurrentFile : copy.currentFile;
  const runtimeFlowSummary =
    language === "zh-CN"
      ? `${runtimeSummaryText}${coachStateSummaryText ? ` · ${coachStateSummaryText}` : ""}`
      : `${runtimeSummaryText}${coachStateSummaryText ? ` · ${coachStateSummaryText}` : ""}`;
  const rememberedRows = [
    learnerName
      ? { label: settingsPhrase(language, "name"), value: learnerName }
      : null,
    targetProject
      ? { label: settingsPhrase(language, "project"), value: targetProject }
      : null,
    preferredLearningMode
      ? { label: settingsPhrase(language, "coachingMode"), value: preferredLearningMode }
      : null,
    preferredRhythm
      ? { label: settingsPhrase(language, "rhythm"), value: preferredRhythm }
      : null,
    onboardingRequest
      ? { label: settingsPhrase(language, "thisRound"), value: onboardingRequest }
      : null,
    projectContext && projectContext !== targetProject
      ? { label: settingsPhrase(language, "context"), value: projectContext }
      : null,
  ].filter(Boolean) as Array<{ label: string; value: string }>;
  const remembersSummary = rememberedRows.length
    ? shortenSummary(
        rememberedRows
          .slice(0, 2)
          .map((row) => `${row.label}: ${row.value}`)
          .join(" · "),
        72,
      )
    : undefined;
  const headerEyebrow = copy.eyebrow.trim();
  const rawHeaderSubtitle = copy.intro.trim();
  const headerSubtitle =
    rawHeaderSubtitle && rawHeaderSubtitle !== copy.title.trim() && rawHeaderSubtitle !== localizedCalmIntro.trim()
      ? rawHeaderSubtitle
      : "";
  const updateDraftModelTokenLimit = (
    modelName: string,
    patch: Partial<ProviderModelTokenLimit>,
  ) => {
    const normalizedModel = modelName.trim();
    if (!normalizedModel || !evaluateProviderModelPolicy(normalizedModel, draftModelPolicy).allowed) {
      return;
    }
    const currentLimit =
      normalizedModel === currentDraftModel
        ? {
            contextWindowTokens: draftContextWindowTokens,
            maxOutputTokens: draftMaxOutputTokens,
          }
        : readProviderModelTokenLimit(draftModelTokenLimits, normalizedModel);
    const nextModelTokenLimits = withProviderModelTokenLimit(draftModelTokenLimits, normalizedModel, {
      ...currentLimit,
      ...patch,
    });
    if (normalizedModel === currentDraftModel) {
      onProviderDraftChange({
        contextWindowTokens:
          "contextWindowTokens" in patch ? patch.contextWindowTokens : draftContextWindowTokens,
        maxOutputTokens: "maxOutputTokens" in patch ? patch.maxOutputTokens : draftMaxOutputTokens,
        modelTokenLimits: nextModelTokenLimits,
      });
      return;
    }
    onProviderDraftChange({ modelTokenLimits: nextModelTokenLimits });
  };
  const clearDraftModelTokenLimit = (modelName: string) => {
    const normalizedModel = modelName.trim();
    if (!normalizedModel || !evaluateProviderModelPolicy(normalizedModel, draftModelPolicy).allowed) {
      return;
    }
    const nextModelTokenLimits = withProviderModelTokenLimit(
      draftModelTokenLimits,
      normalizedModel,
      undefined,
    );
    if (normalizedModel === currentDraftModel) {
      onProviderDraftChange({
        contextWindowTokens: undefined,
        maxOutputTokens: undefined,
        modelTokenLimits: nextModelTokenLimits,
      });
      return;
    }
    onProviderDraftChange({
      modelTokenLimits: nextModelTokenLimits,
    });
  };
  const removeDraftCatalogModel = (modelName: string) => {
    const normalizedModel = modelName.trim().toLowerCase();
    if (!normalizedModel || !evaluateProviderModelPolicy(normalizedModel, draftModelPolicy).allowed) {
      return;
    }
    onProviderDraftChange({
      catalogModels: draftCatalogModels.filter((entry) => entry.trim().toLowerCase() !== normalizedModel),
    });
  };
  const handleAddManualModel = () => {
    const model = manualModelDraft.trim();
    const modelPolicy = evaluateProviderModelPolicy(model, draftModelPolicy);
    if (
      !model ||
      !modelPolicy.allowed ||
      modelLimitKeySet.has(model.toLowerCase())
    ) {
      return;
    }
    onProviderDraftChange({
      catalogModels: mergeDraftStringList(draftCatalogModels, model),
      model,
    });
    setManualModelDraft("");
  };
  const handleUseTypedModel = () => {
    const model = exactMatchingModel ?? modelSearchQuery.trim();
    if (!model || !canUseTypedModel) {
      return;
    }
    onProviderDraftChange({
      ...(exactMatchingModel
        ? {}
        : { catalogModels: mergeDraftStringList(draftCatalogModels, model) }),
      model,
    });
    resetModelPickerSearch();
    setModelPickerOpen(false);
  };
  const providerModelLimitsPanel = (
    <details className="settings-sheet__minor-panel settings-sheet__model-limits-panel">
      <summary>
        {localizedPerModelLimitsLabel} <span aria-hidden="true">·</span>{" "}
        <span className="settings-section-count">{modelLimitNames.length}</span>
      </summary>
      <div className="settings-sheet__minor-body settings-model-limits-panel">
        <p className="settings-sheet__note settings-sheet__note--compact">
          {localizedPerModelLimitsDetail}
        </p>
        <div className="settings-model-limit-toolbar">
          <label className="settings-field settings-field--dense settings-model-limit-toolbar__field">
            <span>{localizedManualModelLabel}</span>
            <input
              value={manualModelDraft}
              placeholder={localizedManualModelPlaceholder}
              onChange={(event) => setManualModelDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key !== "Enter") {
                  return;
                }
                event.preventDefault();
                handleAddManualModel();
              }}
            />
          </label>
          <button
            type="button"
            className="toolbar-button settings-model-limit-toolbar__button"
            disabled={!canAddManualModel}
            onClick={handleAddManualModel}
          >
            <span>{localizedManualModelButton}</span>
          </button>
        </div>
        <p className="settings-sheet__note settings-sheet__note--compact" role="status">
          {manualModelBlockedByPolicy
            ? modelPolicyHint(
                language,
                manualModelPolicy.reason === "denied" ? "denied" : "not_allowed",
              )
            : localizedManualModelHint}
        </p>
        {modelLimitNames.length > 0 ? (
          <div className="settings-model-limit-list" role="list" aria-label={localizedPerModelLimitsLabel}>
            {modelLimitNames.map((modelName) => {
              const isCurrentModel = modelName === currentDraftModel;
              const modelLimitPolicy = evaluateProviderModelPolicy(modelName, draftModelPolicy);
              const modelLimitBlockedByPolicy = !modelLimitPolicy.allowed;
              const isKnownLiveModel = discoveredModelSet.has(modelName.trim().toLowerCase());
              const isSavedCatalogModel = draftCatalogModels.some(
                (entry) => entry.trim().toLowerCase() === modelName.trim().toLowerCase(),
              );
              const draftLimit = readProviderModelTokenLimit(draftModelTokenLimits, modelName);
              const liveLimit = readProviderModelTokenLimit(liveModelTokenLimits, modelName);
              const draftRowContextWindowTokens = isCurrentModel
                ? draftContextWindowTokens
                : draftLimit?.contextWindowTokens;
              const draftRowMaxOutputTokens = isCurrentModel
                ? draftMaxOutputTokens
                : draftLimit?.maxOutputTokens;
              const liveRowContextWindowTokens =
                modelName === currentLiveModel ? liveContextWindowTokens : liveLimit?.contextWindowTokens;
              const liveRowMaxOutputTokens =
                modelName === currentLiveModel ? liveMaxOutputTokens : liveLimit?.maxOutputTokens;
              const hasDraftValues =
                typeof draftRowContextWindowTokens === "number" || typeof draftRowMaxOutputTokens === "number";
              const showCatalogRemoveAction = !hasDraftValues && isSavedCatalogModel;

              return (
                <div
                  key={modelName}
                  className={`settings-model-limit-row ${isCurrentModel ? "is-active" : ""} ${
                    modelLimitBlockedByPolicy ? "is-blocked" : ""
                  }`}
                  role="listitem"
                >
                  <div className="settings-model-limit-row__header">
                    <button
                      type="button"
                      className="settings-model-limit-row__model"
                      aria-pressed={isCurrentModel}
                      disabled={modelLimitBlockedByPolicy}
                      onClick={() => {
                        if (modelLimitBlockedByPolicy) {
                          return;
                        }
                        onProviderDraftChange({
                          model: modelName,
                          catalogModels: mergeDraftStringList(draftCatalogModels, modelName),
                        });
                      }}
                    >
                      <span className="settings-model-limit-row__model-name">{modelName}</span>
                      <span className="settings-model-limit-row__model-state">
                        {isCurrentModel ? localizedCurrentModelLabel : localizedUseModelLabel}
                      </span>
                    </button>
                    <div className="settings-model-limit-row__actions">
                      <span className="settings-model-limit-row__origin">
                        {isKnownLiveModel ? localizedModelOriginLive : localizedModelOriginManual}
                      </span>
                      {hasDraftValues || showCatalogRemoveAction ? (
                        <button
                          type="button"
                          className="toolbar-button settings-model-limit-row__clear"
                          disabled={modelLimitBlockedByPolicy}
                          onClick={() => {
                            if (modelLimitBlockedByPolicy) {
                              return;
                            }
                            if (hasDraftValues) {
                              clearDraftModelTokenLimit(modelName);
                              return;
                            }
                            removeDraftCatalogModel(modelName);
                          }}
                        >
                          <span>
                            {hasDraftValues ? localizedClearModelLimitsLabel : modelCardCopy.remove}
                          </span>
                        </button>
                      ) : null}
                    </div>
                  </div>
                  <div className="settings-model-limit-row__fields">
                    <label className="settings-field settings-field--dense">
                      <span>{settingsPhrase(language, "contextWindow")}</span>
                      <input
                        type="number"
                        min={1}
                        step={1}
                        disabled={modelLimitBlockedByPolicy}
                        value={draftRowContextWindowTokens ?? ""}
                        placeholder={
                          liveRowContextWindowTokens
                            ? formatTokenValue(liveRowContextWindowTokens)
                            : settingsPhrase(language, "notRecorded")
                        }
                        onChange={(event) =>
                          updateDraftModelTokenLimit(modelName, {
                            contextWindowTokens: parsePositiveIntegerInput(event.target.value),
                          })
                        }
                      />
                    </label>
                    <label className="settings-field settings-field--dense">
                      <span>{settingsPhrase(language, "maxOutput")}</span>
                      <input
                        type="number"
                        min={1}
                        step={1}
                        disabled={modelLimitBlockedByPolicy}
                        value={draftRowMaxOutputTokens ?? ""}
                        placeholder={
                          liveRowMaxOutputTokens
                            ? formatTokenValue(liveRowMaxOutputTokens)
                            : settingsPhrase(language, "notRecorded")
                        }
                        onChange={(event) =>
                          updateDraftModelTokenLimit(modelName, {
                            maxOutputTokens: parsePositiveIntegerInput(event.target.value),
                          })
                        }
                      />
                    </label>
                  </div>
                  {modelLimitBlockedByPolicy ? (
                    <p className="settings-sheet__note settings-sheet__note--compact" role="status">
                      {modelPolicyHint(
                        language,
                        modelLimitPolicy.reason === "denied" ? "denied" : "not_allowed",
                      )}
                    </p>
                  ) : null}
                </div>
              );
            })}
          </div>
        ) : (
          <p className="settings-sheet__note settings-sheet__note--compact">
            {localizedModelLimitEmpty}
          </p>
        )}
      </div>
    </details>
  );
  const canNestModelLimitsInCatalog =
    canUseSavedModelMetadata && providerCatalogRows.length > 0;
  const providerCatalogPanel =
    canNestModelLimitsInCatalog ? (
      <details className="settings-sheet__minor-panel settings-sheet__provider-catalog">
        <summary>
          {localizedCatalogPanelLabel} <span aria-hidden="true">·</span> {providerCatalogSummary}
        </summary>
        <div className="settings-sheet__minor-body settings-sheet__stack settings-sheet__stack--tight">
          <p className="settings-sheet__note settings-sheet__note--compact">
            {localizedCatalogPanelDetail}
          </p>
          <div className="settings-sheet__simple-list" aria-label={localizedCatalogPanelLabel}>
            {providerCatalogRows.map((row) => (
              <SimpleInfoRow key={row.label} label={row.label} value={row.value} />
            ))}
          </div>
          {providerModelLimitsPanel}
          <details className="settings-sheet__minor-panel">
            <summary>{localizedAdvancedRoutingLabel}</summary>
            <div className="settings-sheet__minor-body settings-sheet__stack settings-sheet__stack--tight">
              <p className="settings-sheet__note settings-sheet__note--compact">
                {localizedAdvancedRoutingDetail}
              </p>
              <div className="settings-grid settings-grid--form">
                <div className="settings-field">
                  <span>{localizedCredentialModeLabel}</span>
                  <ChoiceList
                    active={draftCredentialMode}
                    items={[
                      { label: localizedCredentialModeUiProxy, value: "ui_proxy" },
                      {
                        label: localizedCredentialModeWorkspaceSecret,
                        value: "workspace_secret",
                      },
                    ]}
                    onChange={(value) => onProviderDraftChange({ credentialMode: value })}
                  />
                </div>

                <div className="settings-field">
                  <span>{localizedCatalogSourceLabel}</span>
                  <ChoiceList
                    active={draftCatalogSource}
                    items={[
                      {
                        label: modelCardCopy.liveFetch,
                        value: "provider_live",
                      },
                      {
                        label: modelCardCopy.cached,
                        value: "cached",
                      },
                      {
                        label: modelCardCopy.manual,
                        value: "manual",
                      },
                    ]}
                    onChange={(value) => onProviderDraftChange({ catalogSource: value })}
                  />
                </div>

                <label className="settings-field">
                  <span>{localizedCatalogCacheTtlLabel}</span>
                  <input
                    type="number"
                    min={1}
                    step={1}
                    value={draftCacheTtlSeconds ?? ""}
                    placeholder={provider.cacheTtlSeconds ? String(provider.cacheTtlSeconds) : ""}
                    onChange={(event) =>
                      onProviderDraftChange({
                        cacheTtlSeconds: parsePositiveIntegerInput(event.target.value),
                      })
                    }
                  />
                  <p className="settings-sheet__note settings-sheet__note--compact">
                    {localizedCacheTtlDetail}
                  </p>
                </label>

                <label className="settings-field">
                  <span>{localizedCatalogEmbeddingModelLabel}</span>
                  <input
                    value={draftEmbeddingModel}
                    placeholder={localizedEmbeddingModelPlaceholder}
                    onChange={(event) =>
                      onProviderDraftChange({
                        embeddingModel: event.target.value,
                      })
                    }
                  />
                </label>

                <label className="settings-field">
                  <span>{localizedCatalogAllowedModelsLabel}</span>
                  <textarea
                    rows={2}
                    value={draftAllowedModelsText}
                    onChange={(event) =>
                      onProviderDraftChange({
                        allowedModels: parseDraftStringList(event.target.value),
                      })
                    }
                  />
                  <p className="settings-sheet__note settings-sheet__note--compact">
                    {localizedAllowedModelsInputDetail}
                  </p>
                </label>

                <label className="settings-field">
                  <span>{localizedCatalogDeniedModelsLabel}</span>
                  <textarea
                    rows={2}
                    value={draftDeniedModelsText}
                    onChange={(event) =>
                      onProviderDraftChange({
                        deniedModels: parseDraftStringList(event.target.value),
                      })
                    }
                  />
                  <p className="settings-sheet__note settings-sheet__note--compact">
                    {localizedDeniedModelsInputDetail}
                  </p>
                </label>

                <label className="settings-field">
                  <span>{localizedCatalogRequestDefaultsLabel}</span>
                  <textarea
                    rows={6}
                    spellCheck={false}
                    value={requestDefaultsText}
                    onChange={(event) => handleRequestDefaultsTextChange(event.target.value)}
                  />
                  <p className="settings-sheet__note settings-sheet__note--compact">
                    {localizedRequestDefaultsInputDetail}
                  </p>
                  <p
                    className={`settings-sheet__note settings-sheet__note--compact${
                      requestDefaultsError ? " settings-sheet__note--warning" : ""
                    }`}
                  >
                    {requestDefaultsError ?? localizedRequestDefaultsInputHint}
                  </p>
                </label>
              </div>
            </div>
          </details>
        </div>
      </details>
    ) : null;
  const providerProfilesPanel =
    providerProfiles.length > 0 || canSaveProviderProfile || Boolean(onUseProviderTemplate) ? (
      <details
        ref={providerProfilesPanelRef}
        className="settings-sheet__minor-panel settings-sheet__provider-profiles"
        open={providerProfilesOpen}
        onToggle={(event) => setProviderProfilesOpen(event.currentTarget.open)}
      >
        <summary>
          {localizedProviderProfilesLabel} <span aria-hidden="true">·</span>{" "}
          <span className="settings-section-count">
            {providerProfileCount > 0 ? providerProfileCount : providerProfiles.length}
          </span>
        </summary>
        <div className="settings-sheet__minor-body settings-provider-profile-panel">
          {!providerSaved || canSaveProviderProfile ? (
            <p className="settings-provider-profile-panel__note">
              {canSaveProviderProfile ? localizedSaveProfileDetail : localizedSavedProfilesDetail}
            </p>
          ) : null}

          {providerProfiles.length > 0 ? (
            <div className="settings-provider-profile-list" role="list" aria-label={providerSummaryText}>
              {providerProfiles.map((profile) => (
                <button
                  key={profile.id}
                  className={`settings-provider-profile ${profile.isActive ? "is-active" : ""}`}
                  type="button"
                  aria-pressed={profile.isActive}
                  title={profile.detail ?? profile.label}
                  disabled={!onSwitchProviderProfile || profile.isActive}
                  onClick={() => {
                    resetModelPickerSearch();
                    setModelPickerOpen(false);
                    onSwitchProviderProfile?.(profile.id);
                  }}
                >
                  <span className="settings-provider-profile__row">
                    <span className="settings-provider-profile__label">{profile.label}</span>
                    <span className="settings-provider-profile__meta">
                      <span className="settings-provider-profile__model">
                        {profile.model || provider.model}
                      </span>
                      {profile.isActive ? (
                        <span className="settings-provider-profile__state" aria-hidden="true">
                          <CheckMarkIcon size={12} />
                        </span>
                      ) : null}
                    </span>
                  </span>
                </button>
              ))}
            </div>
          ) : null}

          <div className="settings-actions settings-actions--compact">
            {canSaveProviderProfile ? (
              <ActionButton
                fullWidth={false}
                icon={<CheckMarkIcon size={14} />}
                label={localizedSaveProfileLabel}
                detail={localizedSaveProfileDetail}
                ariaLabel={localizedSaveProfileLabel}
                onClick={onSaveProviderProfile}
              />
            ) : null}
            <ActionButton
              fullWidth={false}
              icon={<RefreshIcon size={14} />}
              label={localizedRefreshProfilesLabel}
              detail={localizedRefreshProfilesDetail}
              onClick={onRefreshProviderProfiles}
            />
            <ActionButton
              fullWidth={false}
              icon={<LightningIcon size={14} />}
              label={settingsPhrase(language, "useMiniMaxProfile")}
              detail={settingsPhrase(language, "useMiniMaxProfileDetail")}
              onClick={onUseProviderTemplate}
            />
            <ActionButton
              fullWidth={false}
              icon={<GearIcon size={14} />}
              label={copy.openConfig}
              detail={settingsPhrase(language, "workspaceFile")}
              onClick={onOpenConfig}
            />
            <ActionButton
              fullWidth={false}
              icon={<TrashIcon size={14} />}
              label={copy.clear}
              detail={settingsPhrase(language, "clearDraft")}
              onClick={onClearProvider}
            />
          </div>
        </div>
      </details>
    ) : null;
  const showProviderDetailStatePill =
    shouldShowProviderConnectionSummary &&
    (providerHasDraftChanges || !providerCoachReady || providerNeedsRetest);
  const providerDetailRequirementNote = providerHasDraftChanges
    ? currentDraftModelPolicyMessage ??
      (!providerDraft.baseUrl.trim()
        ? settingsStatusPhrase(language, "fillProviderFields")
        : !providerDraft.model.trim()
          ? settingsPhrase(language, "chooseModelDetail")
          : !providerDraftHasApiKey && !providerDraftCanReuseSavedApiKey
            ? settingsStatusPhrase(language, "connectionSavedApiKeyMissing")
            : localizedResolvedAvailabilityDetail)
    : providerRequirementNote ?? localizedResolvedAvailabilityDetail;

  return (
    <section className={classes} aria-labelledby="coach-settings-view-title">
      <h2 id="coach-settings-view-title" className="sr-only">
        {copy.title}
      </h2>

      <div className="settings-sheet__body settings-sheet__body--hierarchical">
        <div
          className="settings-status-bar"
          role="region"
          aria-label={settingsGlobalCopy.settingsStatusRegionLabel}
          data-settings-status-bar="true"
        >
          <p className="settings-status-bar__line">
            <span
              className={`settings-status-bar__state is-${settingsStatusConnectionReady ? "ok" : "warn"}`}
              data-settings-status-connection={settingsStatusConnectionReady ? "ready" : "setup"}
            >
              {settingsStatusConnectionReady
                ? settingsGlobalCopy.settingsStatusConnected
                : settingsGlobalCopy.settingsStatusNotConnected}
            </span>
            <span
              className="settings-status-bar__value"
              title={`${appliedProviderFactValue} · ${appliedModelFactValue}`}
            >
              {appliedProviderFactValue} · {appliedModelFactValue}
            </span>
            <span className="settings-status-bar__sep" aria-hidden="true">
              ·
            </span>
            <span className="settings-status-bar__item">
              {settingsGlobalCopy.settingsStatusLanguage}{" "}
              <strong>{LANGUAGE_LABELS[language]}</strong>
            </span>
            <span className="settings-status-bar__sep" aria-hidden="true">
              ·
            </span>
            <span className="settings-status-bar__item">
              {settingsGlobalCopy.settingsStatusMemory} <strong>{memoryScopeLabel}</strong>
            </span>
          </p>
          {settingsStatusIssues.length > 0 ? (
            <div className="settings-status-bar__issues">
              {settingsStatusIssues.map((issue) => (
                <button
                  key={issue.id}
                  type="button"
                  className="settings-status-bar__issue"
                  data-settings-status-issue={issue.id}
                  onClick={() => revealSettingsSection(issue.target)}
                >
                  {issue.label}
                </button>
              ))}
            </div>
          ) : null}
        </div>

        <section className="settings-section settings-section--panel settings-section--setup settings-section--summary">
          <div
            className={`settings-availability-strip settings-availability-strip--${resolvedAvailabilityTone}`}
            data-view-identity="true"
          >
            <div className="settings-availability-strip__main">
              <div className="settings-availability-strip__copy">
                <strong data-view-object="">{displayAvailabilityHeadline}</strong>
                <span className="settings-availability-strip__state" data-view-state="">
                  <StatusPill tone={resolvedAvailabilityTone}>{localizedResolvedAvailabilityStatusLabel}</StatusPill>
                </span>
                {showAvailabilityPrimaryAction && displayAvailabilityDetail ? (
                  <p data-view-why="">{displayAvailabilityDetail}</p>
                ) : null}
                {resolvedWorkspaceTrustState !== "trusted" ? (
                  <p
                    className="settings-availability-strip__trust"
                    data-workspace-trust-state={resolvedWorkspaceTrustState}
                    data-settings-workspace-trust="true"
                    role="status"
                    aria-live="polite"
                  >
                    {workspaceTrustSentence}
                  </p>
                ) : null}
              </div>
              {showAvailabilityPrimaryAction ? (
                <ActionButton
                  className="settings-availability-strip__primary"
                  tone={effectiveAvailabilityPrimaryTone}
                  fullWidth={false}
                  icon={effectiveAvailabilityPrimaryCta.icon}
                  label={effectiveAvailabilityPrimaryCta.label}
                  detail={effectiveAvailabilityPrimaryCta.detail}
                  ariaLabel={effectiveAvailabilityPrimaryCta.label}
                  onClick={effectiveAvailabilityPrimaryCta.action}
                  disabled={!effectiveAvailabilityPrimaryCta.action}
                  title={effectiveAvailabilityPrimaryCta.detail}
                  data-view-primary=""
                />
              ) : null}
            </div>
            {false && (shouldShowProviderConnectionSummary || shouldShowAvailabilityFacts) ? (
              <details className="settings-availability-strip__more">
                <summary>{orientationMoreLabel}</summary>
                {shouldShowProviderConnectionSummary ? (
                  <span className="eyebrow">{copy.setupSection}</span>
                ) : null}
                {shouldShowProviderConnectionSummary ? (
                  <span
                    className="settings-availability-strip__meta"
                    title={providerConnectionSummary}
                    aria-label={providerConnectionSummary}
                    data-full-value={providerConnectionSummary}
                  >
                    {providerPreviewSummaryText}
                  </span>
                ) : null}
                {shouldShowAvailabilityFacts ? (
                  <div className="settings-availability-strip__facts" aria-label={settingsPhrase(language, "connectionState")}>
                    {availabilityFacts.map((fact) => (
                      <div
                        key={fact.id}
                        className="settings-availability-fact"
                        title={`${fact.label}: ${fact.value}. ${fact.detail}`}
                        aria-label={`${fact.label}: ${fact.value}. ${fact.detail}`}
                        data-availability-fact={fact.id}
                        data-availability-value={fact.value}
                        data-secret="false"
                      >
                        <span>{fact.label}</span>
                        <strong>
                          {fact.presentation === "text" ? (
                            <span
                              className={`settings-availability-fact__text is-${fact.tone}`}
                              title={fact.value}
                              data-availability-fact-value={fact.value}
                            >
                              {fact.value}
                            </span>
                          ) : (
                            <StatusPill tone={fact.tone}>{fact.value}</StatusPill>
                          )}
                        </strong>
                      </div>
                    ))}
                  </div>
                ) : null}
              </details>
            ) : null}
          </div>

          <div
            ref={connectionAnchorRef}
            className={`settings-anchor${sectionFlash === "connection" ? " settings-anchor--flash" : ""}`}
            data-settings-section="connection"
          >
            <div className="settings-section-head">
              <span className="eyebrow">{settingsGlobalCopy.settingsSectionConnection}</span>
              {connectionDirty ? (
                <span
                  className="settings-section-dot"
                  data-settings-dirty="connection"
                  title={settingsGlobalCopy.settingsStatusUnsaved}
                >
                  <span className="sr-only">{settingsGlobalCopy.settingsStatusUnsaved}</span>
                </span>
              ) : null}
            </div>
            {showProviderDetailActions ? (
                  <div className="settings-actions settings-actions--compact settings-actions--primary">
                    {!modelDiscoveryGuidanceActive ? (
                      <ActionButton
                        fullWidth={false}
                        icon={<CheckMarkIcon size={14} />}
                        label={saveProviderConnectionLabel}
                        ariaLabel={saveProviderConnectionLabel}
                        detail={
                          canSaveProviderConnection
                            ? settingsPhrase(language, "saveToApply")
                            : currentDraftModelPolicyMessage ??
                              settingsPhrase(language, "saveConnectionDetail")
                        }
                        disabled={!canSaveProviderConnection}
                        onClick={onSaveProvider}
                        title={saveProviderConnectionTitle}
                      />
                    ) : null}
                    {showSecondaryModelDiscoveryAction ? (
                      <ActionButton
                        fullWidth={false}
                        icon={<RefreshIcon size={14} />}
                        label={modelDiscoveryActionLabel}
                        detail={modelDiscoveryActionDetail}
                        disabled={!canRefreshModels}
                        onClick={onRefreshProviderModels}
                        title={canRefreshModels ? modelDiscoveryActionLabel : modelDiscoveryBlockedReason}
                      />
                    ) : null}
                    {!modelDiscoveryGuidanceActive && showProviderDetailTestAction ? (
                      <ActionButton
                        fullWidth={false}
                        icon={<DiagnosticsIcon size={14} />}
                        label={copy.test}
                        ariaLabel={copy.test}
                        detail={
                          currentDraftModelPolicyMessage ??
                          settingsPhrase(language, "verifyConnectionDetail")
                        }
                        disabled={!canRetestProvider}
                        onClick={onTestProvider}
                        title={
                          canRetestProvider
                            ? providerHasDraftChanges
                              ? settingsPhrase(language, "testDraftConnectionDetail")
                              : copy.test
                            : currentDraftModelPolicyMessage
                              ? currentDraftModelPolicyMessage
                            : !providerDraftFieldsReady
                              ? language === "zh-CN"
                                ? "先完成 provider、base URL 和 model，再测试连接。"
                                : "Finish the provider, base URL, and model before testing the connection."
                              : !providerDraftHasApiKey && !providerDraftCanReuseSavedApiKey
                                ? language === "zh-CN"
                                  ? "先补上 API key，再测试这组连接。"
                                  : "Add an API key before testing this connection."
                                : providerSaved
                                  ? language === "zh-CN"
                                    ? "先保存当前草稿，再测试这组连接。"
                                    : "Save the current draft before testing this connection."
                                  : savedProviderProfilesAvailable
                                    ? language === "zh-CN"
                                      ? "先启用一个已保存的 profile，再测试当前连接。"
                                      : "Apply a saved profile before testing the current connection."
                                    : language === "zh-CN"
                                      ? "先完成 provider 配置，再测试连接。"
                                      : "Finish the provider setup before testing the connection."
                        }
                      />
                    ) : null}
                  </div>
                ) : null}
            {!providerCoachReady ? (
              <p className="settings-sheet__note settings-sheet__note--warning">
                {providerDetailRequirementNote}
              </p>
            ) : null}
            {showAvailabilityChecklist ? renderProviderSetupChecks("settings-setup-checks--availability") : null}

            <form
              className="settings-sheet__minor-body"
              onSubmit={(event) => {
                event.preventDefault();
                if (canSaveProviderConnection) {
                  onSaveProvider?.();
                }
              }}
            >
              <div className="settings-grid settings-grid--form">
                <label className="settings-field">
                  <span>{providerConnectionNameLabel(language)}</span>
                  <input
                    value={providerDraft.name}
                    onChange={(event) => onProviderDraftChange({ name: event.target.value })}
                  />
                </label>

                <label className="settings-field">
                  <span>{providerBaseUrlLabel}</span>
                  <input
                    value={providerDraft.baseUrl}
                    onChange={(event) =>
                      onProviderDraftChange({
                        baseUrl: event.target.value,
                        ...(providerDraft.name.trim()
                          ? {}
                          : { name: DEFAULT_PROVIDER_CONNECTION_NAME }),
                      })
                    }
                  />
                  <p className="settings-sheet__note settings-sheet__note--compact">
                    {providerBaseUrlHint}
                  </p>
                </label>

                <label className="settings-field">
                  <span>{copy.apiKey}</span>
                  <input
                    ref={apiKeyInputRef}
                    type="password"
                    value={providerDraft.apiKey}
                    placeholder={
                      providerDraftCanReuseSavedApiKey ? copy.apiKeySaved : settingsStatusPhrase(language, "connectionSavedApiKeyMissing")
                    }
                    onChange={(event) => onProviderDraftChange({ apiKey: event.target.value })}
                  />
                </label>

                <div className="settings-field">
                  <span>{copy.model}</span>
                  <details
                    ref={modelPickerRef}
                    className="settings-model-picker"
                    open={modelPickerOpen}
                    onToggle={() => {
                      const picker = modelPickerRef.current;
                      if (!picker) {
                        return;
                      }
                      setModelPickerOpen(picker.open);
                      if (!picker.open) {
                        resetModelPickerSearch();
                        return;
                      }
                      if (!showModelSearchInput) {
                        return;
                      }
                      window.requestAnimationFrame(() => modelSearchInputRef.current?.focus());
                    }}
                  >
                    <summary
                      aria-label={`${copy.model}: ${currentDraftModel || copy.availableModels}`}
                      title={currentDraftModel || copy.availableModels}
                    >
                      <span>{currentDraftModel || copy.availableModels}</span>
                    </summary>
                    {showModelSearchInput ? (
                      <div className="settings-model-picker__filter">
                        <input
                          ref={modelSearchInputRef}
                          type="search"
                          aria-label={modelPickerCopy.filterLabel}
                          value={modelSearchQuery}
                          placeholder={modelPickerCopy.filterPlaceholder}
                          onChange={(event) => setModelSearchQuery(event.target.value)}
                          onKeyDown={(event) => {
                            if (event.key !== "Enter" || !canUseTypedModel) {
                              return;
                            }
                            event.preventDefault();
                            handleUseTypedModel();
                          }}
                        />
                        {normalizedModelSearchQuery && matchingModelOptions.length === 0 ? (
                          <p className="settings-model-picker__hint">{modelPickerCopy.noMatches}</p>
                        ) : null}
                        {normalizedModelSearchQuery && hiddenMatchingModelCount > 0 ? (
                          <p className="settings-model-picker__hint">
                            {modelPickerCopy.moreMatchesHint(hiddenMatchingModelCount)}
                          </p>
                        ) : null}
                        {showTypedModelAction ? (
                          <button
                            type="button"
                            className="toolbar-button"
                            onClick={handleUseTypedModel}
                          >
                            {modelPickerCopy.useTypedModel(modelSearchQuery.trim())}
                          </button>
                        ) : null}
                      </div>
                    ) : null}
                    {showModelSearchInput || visibleModelOptions.length > 0 ? (
                      <select
                        ref={modelSelectRef}
                        aria-label={copy.model}
                        value={visibleModelSelection}
                        onChange={(event) => {
                          const selectedModel = event.target.value;
                          if (!evaluateProviderModelPolicy(selectedModel, draftModelPolicy).allowed) {
                            return;
                          }
                          onProviderDraftChange({ model: selectedModel });
                          resetModelPickerSearch();
                          setModelPickerOpen(false);
                        }}
                      >
                        {!visibleModelSelection ? (
                          <option value="" disabled>
                            {normalizedModelSearchQuery && matchingModelOptions.length === 0
                              ? modelPickerCopy.noMatches
                              : copy.availableModels}
                          </option>
                        ) : null}
                        {visibleModelOptions.map((modelName) => (
                          <option key={modelName} value={modelName}>
                            {modelName}
                          </option>
                        ))}
                      </select>
                    ) : null}
                    {showManualModelEntryAction ? (
                      <div className="settings-model-picker__filter">
                        <button
                          type="button"
                          className="toolbar-button"
                          onClick={() => {
                            setManualModelEntryOpen(true);
                            window.requestAnimationFrame(() => modelSearchInputRef.current?.focus());
                          }}
                        >
                          {modelPickerCopy.enterModelName}
                        </button>
                      </div>
                    ) : null}
                  </details>
                  <div className="settings-sheet__stack settings-sheet__stack--tight">
                    {currentDraftModel && !currentDraftModelPolicy.allowed ? (
                      <p className="settings-sheet__note settings-sheet__note--compact" role="status">
                        {modelPolicyHint(
                          language,
                          currentDraftModelPolicy.reason === "denied" ? "denied" : "not_allowed",
                        )}
                      </p>
                    ) : null}
                    {modelDiscoveryGuidance ? (
                      <p className="settings-sheet__note settings-sheet__note--compact">
                        {modelDiscoveryGuidance}
                      </p>
                    ) : null}
                  </div>
                </div>
              </div>

              {copy.configFileNote ? (
                <p className="inline-note settings-sheet__note">{copy.configFileNote}</p>
              ) : null}
            </form>
          </div>

          <div className="settings-sheet__support coach-settings-view__provider-detail">
            <CollapseSection
              level={2}
              persistenceKey="settings-provider"
              open={providerDetailRequested}
              onToggle={setProviderDetailRequested}
              title={<span className="eyebrow">{settingsGlobalCopy.settingsConnectionDetails}</span>}
              subtitle={
                shouldShowProviderConnectionSummary ? (
                  <span
                    className="settings-sheet__defaults-preview"
                    title={providerConnectionSummary}
                    data-full-value={providerConnectionSummary}
                  >
                    {providerPreviewSummaryText}
                  </span>
                ) : undefined
              }
              badge={
                showProviderDetailStatePill ? (
                  <StatusPill tone={resolvedAvailabilityTone}>
                    {localizedResolvedAvailabilityStatusLabel}
                  </StatusPill>
                ) : undefined
              }
            >
              <div className="coach-settings-view__provider-detail-body">
                <div className="settings-grid settings-grid--form">
                  <div className="settings-field">
                    <span>{settingsSupportPhrase(language, "protocol")}</span>
                    <ChoiceList
                      active={draftProtocol}
                      items={protocolItems}
                      onChange={(value) => {
                        const protocol = normalizeProviderProtocol(value);
                        if (protocol) {
                          onProviderDraftChange({ protocol });
                        }
                      }}
                    />
                    <div className="settings-sheet__stack settings-sheet__stack--tight">
                      <p className="settings-sheet__note settings-sheet__note--compact">
                        {settingsPhrase(language, "defaultEndpoint")}: <strong>{selectedProtocolEndpoint}</strong>
                      </p>
                      <p className="settings-sheet__note settings-sheet__note--compact settings-capability-status">
                        {settingsPhrase(language, "capabilitiesFromLiveTest")}
                      </p>
                    </div>
                  </div>
                </div>

                {!canNestModelLimitsInCatalog ? providerModelLimitsPanel : null}

              <details className="settings-sheet__minor-panel">
                <summary>
                  {settingsPhrase(language, "modelAndTestDetail")}
                </summary>
                <div className="settings-sheet__minor-body">
                  <div className="settings-sheet__summary-grid">
                    <SummaryCard
                      label={copy.apiKey}
                      value={providerApiKeyDraftStatus.value}
                    />
                    <SummaryCard
                      label={settingsPhrase(language, "contextWindow")}
                      value={formatTokenValue(providerHasDraftChanges ? draftContextWindowTokens : liveContextWindowTokens)}
                    />
                    <SummaryCard
                      label={settingsPhrase(language, "maxOutput")}
                      value={formatTokenValue(providerHasDraftChanges ? draftMaxOutputTokens : liveMaxOutputTokens)}
                    />
                    <SummaryCard
                      label={copy.modelCache}
                      value={
                        <span className="settings-sheet__summary-inline">
                          <StatusPill tone={modelCacheTone}>{modelCacheStatusLabel}</StatusPill>
                        </span>
                      }
                      detail={
                        language === "zh-CN"
                          ? `${copy.modelCacheSource}: ${cacheSourceLabel}`
                          : `${copy.modelCacheSource}: ${cacheSourceLabel}`
                      }
                    />
                    <SummaryCard
                      label={copy.lastTest}
                      value={lastTestLabel}
                      detail={localizedLastTestDetailText}
                    />
                  </div>
                  <div className="settings-sheet__summary-grid">
                    <SummaryCard
                      label={providerTruthCopy.protocol}
                      value={protocolFactValue}
                      detail={protocolFactDetail}
                    />
                    <SummaryCard
                      label={providerTruthCopy.capabilities}
                      value={
                        capabilityChipsAllowed ? (
                        <span className="settings-sheet__summary-inline">
                          <span>{toolsCopy.label}</span>
                          <span data-settings-capability-chip="tools">
                            <StatusPill tone={toolsVerificationFact.tone}>
                              {toolsVerificationFact.value}
                            </StatusPill>
                          </span>
                          <span>{streamingCopy.label}</span>
                          <span data-settings-capability-chip="streaming">
                            <StatusPill tone={streamingVerificationFact.tone}>
                              {streamingVerificationFact.value}
                            </StatusPill>
                          </span>
                          <span>{thinkingCopy.label}</span>
                          <span data-settings-capability-chip="thinking">
                            <StatusPill tone={thinkingVerificationFact.tone}>
                              {thinkingVerificationFact.value}
                            </StatusPill>
                          </span>
                          <span>{visionCopy.label}</span>
                          <span data-settings-capability-chip="vision">
                            <StatusPill tone={visionVerificationFact.tone}>
                              {visionVerificationFact.value}
                            </StatusPill>
                          </span>
                        </span>
                        ) : (
                          <span
                            className="settings-capability-status"
                            data-settings-capability-status={
                              providerHasDraftChanges ? "draft" : capabilitySurfaceStatus
                            }
                          >
                            {capabilityHonestyStatus}
                          </span>
                        )
                      }
                      detail={capabilityChipsAllowed ? capabilitySummaryDetail : undefined}
                    />
                    <SummaryCard
                      label={settingsPhrase(language, "finalCapabilities")}
                      value={
                        capabilityChipsAllowed ? (
                        <span className="settings-sheet__summary-inline">
                          {([
                            ["chat", capabilityVerdict.chat],
                            ["streaming", capabilityVerdict.streaming],
                            ["tools", capabilityVerdict.verifiedTools],
                            ["image-input", capabilityVerdict.imageInput],
                            ["formal-plan", capabilityVerdict.formalPlan],
                            ["resource-write", capabilityVerdict.resourceWrite],
                          ] as const).map(([name, enabled]) => (
                            <span key={name} data-capability-verdict={name}>
                              <span>{name}</span>{" "}
                              <StatusPill tone={enabled ? "connected" : "warn"}>
                                {enabled
                                  ? settingsStatusPhrase(language, "ready")
                                  : settingsStatusPhrase(language, "unavailable")}
                              </StatusPill>
                            </span>
                          ))}
                        </span>
                        ) : (
                          <span
                            className="settings-capability-status"
                            data-settings-capability-status={
                              providerHasDraftChanges ? "draft" : capabilitySurfaceStatus
                            }
                            data-capability-verdict-status={
                              providerHasDraftChanges ? "draft" : capabilitySurfaceStatus
                            }
                          >
                            {capabilityHonestyStatus}
                          </span>
                        )
                      }
                      detail={
                        capabilityChipsAllowed
                          ? `${capabilityVerdict.reason} · ${
                        language === "zh-CN"
                          ? `图片：${capabilityVerdict.imageInput ? "已通过 vision probe 和协议附件支持验证" : imageInputState.detail ?? imageInputState.reason ?? "尚未验证"}`
                          : `Images: ${capabilityVerdict.imageInput ? "vision probe and protocol attachment support verified" : imageInputState.detail ?? imageInputState.reason ?? "not verified yet"}`} · ${
                        workspaceAuthority?.authorityScope === "trainer_sandbox"
                          ? language === "zh-CN" ? "Trainer 沙箱 artifact 写入" : "Trainer sandbox artifact writes"
                          : language === "zh-CN" ? "用户源码工作区只读" : "User source workspace is read-only"
                      } · ${workspaceAuthority?.resourceWriteEvidence?.reason ?? (language === "zh-CN" ? "等待真实写入证据" : "Awaiting verified write evidence")}`
                          : undefined
                      }
                    />
                    <SummaryCard
                      label={providerTruthCopy.diagnostics}
                      value={diagnosticsFactValue}
                      detail={diagnosticsFactDetail}
                    />
                    <SummaryCard
                      label={providerTruthCopy.profiles}
                      value={profileVerdict.status}
                      detail={profileVerdict.detail || providerTruthCopy.profileDetail(providerProfileCount)}
                    />
                  </div>

                  {blockedTaskBindingCount > 0 || blockedModelCount > 0 ? (
                    <div className="settings-sheet__stack settings-sheet__stack--tight">
                      {blockedTaskBindingCount > 0 ? (
                        <SimpleInfoRow
                          label={providerTruthCopy.blockedTaskBindings}
                          value={String(blockedTaskBindingCount)}
                        />
                      ) : null}
                      {blockedModelCount > 0 ? (
                        <SimpleInfoRow
                          label={providerTruthCopy.blockedModels}
                          value={String(blockedModelCount)}
                        />
                      ) : null}
                    </div>
                  ) : null}

                  {modelCapabilityRows.length > 0 ? (
                    <div className="settings-sheet__stack settings-sheet__stack--tight">
                      <p className="settings-sheet__note settings-sheet__note--compact">
                        {providerTruthCopy.modelHints}
                      </p>
                      {modelCapabilityRows.map((row) => (
                        <SimpleInfoRow key={row.label} label={row.label} value={row.value} />
                      ))}
                    </div>
                  ) : null}

                  {diagnosticNotes.length > 0 ? (
                    <div className="settings-sheet__stack settings-sheet__stack--tight">
                      <p className="settings-sheet__note settings-sheet__note--compact">
                        {providerTruthCopy.diagnosticNotes}
                      </p>
                      {diagnosticNotes.map((note, index) => (
                        <p key={`${index}-${note}`} className="settings-sheet__note settings-sheet__note--compact">
                          {note}
                        </p>
                      ))}
                    </div>
                  ) : null}

                  {warningNotes.length > 0 ? (
                    <div className="settings-sheet__stack settings-sheet__stack--tight">
                      <p className="settings-sheet__note settings-sheet__note--compact">
                        {providerTruthCopy.warnings}
                      </p>
                      {warningNotes.map((note, index) => (
                        <p
                          key={`${index}-${note}`}
                          className="settings-sheet__note settings-sheet__note--warning"
                        >
                          {note}
                        </p>
                      ))}
                    </div>
                  ) : null}
                </div>
              </details>

              {thinkingControl}
              {providerCatalogPanel}

              {providerProfilesPanel}
            </div>
            </CollapseSection>
          </div>

        </section>

        <WorkspaceRootRecoveryPanel
          trainerWorkspace={trainerWorkspace}
          onChooseRoot={onChooseTrainerWorkspaceRoot}
          onMigrateRoot={onMigrateTrainerWorkspaceRoot}
          onBackup={onBackupTrainerWorkspace}
          onRestore={onRestoreTrainerWorkspaceBackup}
        />

        <div
          ref={teachingPrefsAnchorRef}
          className={`settings-anchor${sectionFlash === "teaching" ? " settings-anchor--flash" : ""}`}
          data-settings-section="teaching"
        >
        <CollapseSection
          level={1}
          persistenceKey="settings-teaching-prefs"
          open={coachDefaultsOpen}
          onToggle={setCoachDefaultsOpen}
          title={
            <span className="eyebrow">
              {settingsGlobalCopy.settingsTeachingPrefs}
              {teachingPrefsDirty ? (
                <span
                  className="settings-section-dot"
                  data-settings-dirty="teaching"
                  title={settingsGlobalCopy.settingsStatusUnsaved}
                >
                  <span className="sr-only">{settingsGlobalCopy.settingsStatusUnsaved}</span>
                </span>
              ) : null}
            </span>
          }
          subtitle={<span className="settings-sheet__defaults-preview">{coachBehaviorSummary}</span>}
          badge={
            showCoachDefaultsStatePill ? (
              <StatusPill tone={saveStateTone(coachDefaultsStatus?.saveState ?? "empty")}>
                {saveStateLabel(copy, coachDefaultsStatus?.saveState ?? "empty")}
              </StatusPill>
            ) : undefined
          }
          actions={
            <ActionButton
              className={
                teachingPrefsDirty ? "settings-section-save is-dirty" : "settings-section-save"
              }
              tone="accent"
              fullWidth={false}
              icon={<CheckMarkIcon size={14} />}
              label={copy.save}
              ariaLabel={copy.saveCoachDefaults}
              detail={
                teachingPrefsDirty
                  ? settingsGlobalCopy.settingsStatusUnsaved
                  : settingsPhrase(language, "saveDefaults")
              }
              onClick={onSaveCoachSettings}
            />
          }
        >
            <div className="settings-sheet__minor-body settings-sheet__defaults-body">
              <SettingsStatePanel
                copy={copy}
                status={coachDefaultsStatus}
                primaryLabel={copy.effectiveNow}
              />

              <div
                className="settings-answer-style"
                role="radiogroup"
                aria-label={settingsGlobalCopy.settingsAnswerStyle}
                data-settings-answer-style={answerStyle}
              >
                <span className="eyebrow">{settingsGlobalCopy.settingsAnswerStyle}</span>
                <div className="settings-answer-style__options">
                  {([
                    { value: "simple", label: settingsGlobalCopy.answerStyleSimple },
                    { value: "balanced", label: settingsGlobalCopy.answerStyleBalanced },
                    { value: "deep", label: settingsGlobalCopy.answerStyleDeep },
                    { value: "custom", label: settingsGlobalCopy.answerStyleCustom },
                  ] as const).map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      role="radio"
                      aria-checked={answerStyle === option.value}
                      className={`toolbar-button settings-sheet__choice-pill settings-answer-style__option${
                        answerStyle === option.value ? " is-active" : ""
                      }`}
                      onClick={() => selectAnswerStyle(option.value)}
                    >
                      <span>{option.label}</span>
                    </button>
                  ))}
                </div>
                <p className="settings-sheet__note settings-sheet__note--compact">
                  {settingsGlobalCopy.settingsAnswerStyleHint}
                </p>
              </div>

              <div className="settings-grid settings-grid--compact settings-grid--tight">
                <div className="settings-row" data-settings-language="true">
                  <span className="eyebrow">{copy.language}</span>
                  <ChoiceList
                    active={language}
                    items={SUPPORTED_LANGUAGES.map((value) => ({
                      label: LANGUAGE_LABELS[value],
                      value,
                    }))}
                    onChange={onLanguageChange}
                  />
                </div>
              </div>

              <CollapseSection
                level={2}
                persistenceKey="settings-advanced-context"
                open={answerStyle === "custom" || advancedContextPinned}
                onToggle={setAdvancedContextPinned}
                title={<span className="eyebrow">{settingsGlobalCopy.settingsAdvancedContext}</span>}
                subtitle={<span className="settings-sheet__defaults-preview">{contextBehaviorSummary}</span>}
              >
                <div className="settings-sheet__minor-body">
                  <div className="settings-grid settings-grid--compact settings-grid--tight">
                    <div className="settings-row">
                      <span className="eyebrow">{copy.followCurrentFile}</span>
                      <ChoiceList
                        active={followCurrentFile ? "on" : "off"}
                        items={[
                          { label: copy.on, value: "on" },
                          { label: copy.off, value: "off" },
                        ]}
                        onChange={(value) =>
                          tuneAdvancedContextKnob(() => onFollowCurrentFileChange?.(value === "on"))
                        }
                      />
                    </div>
                    <div className="settings-row">
                      <span className="eyebrow">{copy.contextMode}</span>
                      <ChoiceList
                        active={contextDetail}
                        items={[
                          { label: copy.focused, value: "focused" },
                          { label: copy.balancedContext, value: "balanced" },
                          { label: copy.fullContext, value: "full" },
                        ]}
                        onChange={(value) =>
                          tuneAdvancedContextKnob(() => onContextDetailChange?.(value))
                        }
                      />
                    </div>
                  </div>

                  <ContextList rows={contextRows} onLabel={copy.on} offLabel={copy.off} />
                  {workspaceControlStatus?.saveState === "unsaved" ? (
                    <p className="settings-sheet__note settings-sheet__note--compact">
                      {attachedContextSummaryText}
                    </p>
                  ) : null}
                </div>
              </CollapseSection>
            </div>
        </CollapseSection>
        </div>

        <div
          ref={memoryPrivacyAnchorRef}
          className={`settings-anchor${sectionFlash === "memory" ? " settings-anchor--flash" : ""}`}
          data-settings-section="memory"
        >
        <CollapseSection
          level={1}
          persistenceKey="settings-memory-privacy"
          open={memoryPrivacyOpen}
          onToggle={setMemoryPrivacyOpen}
          title={
            <span className="eyebrow">
              {settingsGlobalCopy.settingsMemoryPrivacy}
              {memoryPrivacyDirty ? (
                <span
                  className="settings-section-dot"
                  data-settings-dirty="memory"
                  title={settingsGlobalCopy.settingsStatusUnsaved}
                >
                  <span className="sr-only">{settingsGlobalCopy.settingsStatusUnsaved}</span>
                </span>
              ) : null}
            </span>
          }
          subtitle={<span className="settings-sheet__defaults-preview">{memoryScopeLabel}</span>}
          actions={
            <ActionButton
              className={
                memoryPrivacyDirty ? "settings-section-save is-dirty" : "settings-section-save"
              }
              tone="accent"
              fullWidth={false}
              icon={<CheckMarkIcon size={14} />}
              label={copy.save}
              ariaLabel={copy.saveCoachDefaults}
              detail={settingsPhrase(language, "saveDefaults")}
              onClick={onSaveCoachSettings}
            />
          }
        >
            <div className="settings-sheet__minor-body settings-sheet__defaults-body">

              <div className="settings-grid settings-grid--compact settings-grid--tight">
                <div className="settings-row">
                  <span className="eyebrow">{copy.memoryScope}</span>
                  <ChoiceList
                    active={memoryScope}
                    items={[
                      { label: copy.memoryScopeProject, value: "project" },
                      { label: copy.memoryScopePersonal, value: "personal" },
                      { label: copy.memoryScopeSession, value: "session" },
                    ]}
                    onChange={(value) => onCoachDefaultsChange?.({ memoryScope: value })}
                  />
                </div>
              </div>

          {rememberedRows.length ? (
            <details className="settings-sheet__minor-panel settings-sheet__remembered-panel">
              <summary className="settings-sheet__remembered-summary">
                <span className="eyebrow">
                  {settingsPhrase(language, "trainerRemembers")}
                </span>
                {remembersSummary ? (
                  <span className="settings-sheet__remembered-preview">{remembersSummary}</span>
                ) : null}
              </summary>
              <div className="settings-sheet__simple-list" aria-label={settingsPhrase(language, "trainerRemembers")}>
                {rememberedRows.map((row) => (
                  <SimpleInfoRow key={row.label} label={row.label} value={row.value} />
                ))}
              </div>
            </details>
          ) : null}

          <div className="settings-sheet__utility-grid">
            <section className="settings-sheet__workspace-card">
              <span className="eyebrow">{copy.memoryStrategy}</span>
              <div className="settings-sheet__status settings-sheet__status--dense">
                <button
                  className={`context-chip ${workspaceMemoryToggles.decisions ? "is-enabled" : ""}`}
                  type="button"
                  onClick={() =>
                    updateWorkspaceMemoryToggles({ decisions: !workspaceMemoryToggles.decisions })
                  }
                >
                  <span>{copy.rememberDecisions}</span>
                  <strong>{workspaceMemoryToggles.decisions ? copy.on : copy.off}</strong>
                </button>
                <button
                  className={`context-chip ${workspaceMemoryToggles.patterns ? "is-enabled" : ""}`}
                  type="button"
                  onClick={() =>
                    updateWorkspaceMemoryToggles({ patterns: !workspaceMemoryToggles.patterns })
                  }
                >
                  <span>{copy.rememberPatterns}</span>
                  <strong>{workspaceMemoryToggles.patterns ? copy.on : copy.off}</strong>
                </button>
                <button
                  className={`context-chip ${workspaceMemoryToggles.resources ? "is-enabled" : ""}`}
                  type="button"
                  onClick={() =>
                    updateWorkspaceMemoryToggles({ resources: !workspaceMemoryToggles.resources })
                  }
                >
                  <span>{copy.rememberResources}</span>
                  <strong>{workspaceMemoryToggles.resources ? copy.on : copy.off}</strong>
                </button>
              </div>
            </section>
          </div>

          <details className="settings-sheet__minor-panel settings-memory-sharing">
            <summary className="settings-memory-sharing__summary">
              <span className="eyebrow">{copy.memorySharing}</span>
              <span className="settings-sheet__remembered-preview">{memorySharingSummary}</span>
            </summary>
            <div className="settings-sheet__minor-body settings-memory-sharing__body">
              <p className="settings-sheet__note settings-sheet__note--compact">
                {canManageMemoryShares ? copy.memorySharingDetail : copy.memorySharingUnavailable}
              </p>
              {memoryShareGrants.length > 0 ? (
                <ul className="settings-memory-sharing__list">
                  {memoryShareGrants.map((grant) => (
                    <li
                      key={`${grant.sourceWorkspaceId}:${grant.targetWorkspaceId}`}
                      className="settings-memory-sharing__item"
                    >
                      <span className="settings-memory-sharing__source">
                        <strong>{memoryShareSourceLabel(grant.sourceWorkspaceId)}</strong>
                        <small>
                          {grant.categories
                            .map((category) =>
                              category === "preferences"
                                ? copy.memorySharePreferences
                                : copy.memoryShareMastery,
                            )
                            .join(" · ")}
                        </small>
                      </span>
                      <button
                        className="settings-memory-sharing__revoke"
                        type="button"
                        disabled={!onRevokeMemoryShare}
                        title={copy.memoryShareRevoke}
                        aria-label={`${copy.memoryShareRevoke}: ${memoryShareSourceLabel(
                          grant.sourceWorkspaceId,
                        )}`}
                        onClick={() => onRevokeMemoryShare?.(grant.sourceWorkspaceId)}
                      >
                        <TrashIcon size={14} />
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="empty-state settings-memory-sharing__empty">
                  <span className="empty-state__icon" aria-hidden="true">
                    <FolderIcon size={16} />
                  </span>
                  <span className="empty-state__title">{copy.memorySharingNone}</span>
                  {canManageMemoryShares ? (
                    <span className="empty-state__action">
                      <ActionButton
                        fullWidth={false}
                        icon={<FolderIcon size={14} />}
                        label={copy.memoryShareGrant}
                        detail={copy.memorySharingDetail}
                        onClick={onGrantMemoryShare}
                      />
                    </span>
                  ) : null}
                </div>
              )}
              {memoryShareGrants.length > 0 && canManageMemoryShares ? (
                <div className="settings-actions settings-actions--compact">
                  <ActionButton
                    fullWidth={false}
                    icon={<FolderIcon size={14} />}
                    label={copy.memoryShareGrant}
                    detail={copy.memorySharingDetail}
                    onClick={onGrantMemoryShare}
                  />
                </div>
              ) : null}
            </div>
          </details>

          <details className="settings-sheet__minor-panel">
            <summary>
              {language === "zh-CN"
                ? "续接状态"
                : "Continuation state"}
            </summary>
            <div className="settings-sheet__minor-body">
              <div className="settings-sheet__summary-grid">
                <SummaryCard
                  label={copy.runtimeSection}
                  value={runtimeSummaryText}
                  detail={memoryScopeRuntimeSummary}
                />
                {localizedCoachStateText ? (
                  <SummaryCard
                    label={copy.coachState}
                    value={<span title={localizedCoachStateText}>{coachStateSummaryText}</span>}
                  />
                ) : null}
                {nextReviewDue ? <SummaryCard label={copy.nextReview} value={nextReviewDue} /> : null}
              </div>
              <p className="settings-sheet__note settings-sheet__note--compact">{runtimeFlowSummary}</p>
            </div>
          </details>

          {resourceSandbox ? (
            <section className="settings-sheet__workspace-card">
              <div className="settings-sheet__authority-block-head">
                <span className="eyebrow">{copy.managedDataFolder}</span>
                <div className="settings-actions settings-actions--compact">
                  <ActionButton
                    fullWidth={false}
                    icon={<FolderIcon size={14} />}
                    label={copy.managedDataFolderChoose}
                    detail={language === "zh-CN" ? "切换并重启后端" : "Switch and restart"}
                    onClick={onChooseManagedDataFolder}
                  />
                  <ActionButton
                    fullWidth={false}
                    icon={<RefreshIcon size={14} />}
                    label={copy.managedDataFolderReset}
                    detail={language === "zh-CN" ? "回到推荐目录" : "Return to recommended"}
                    onClick={onResetManagedDataFolder}
                  />
                </div>
              </div>
              <div className="settings-sheet__summary-grid">
                <SummaryCard
                  label={copy.effectiveNow}
                  value={
                    <span
                      className="settings-sheet__path-value"
                      title={resourceSandbox.effectivePath}
                    >
                      {resourceSandbox.effectivePath}
                    </span>
                  }
                  detail={managedDataSourceLabel}
                />
                {showManagedDataRecommendedCard ? (
                  <SummaryCard
                    label={copy.managedDataFolderRecommended}
                    value={
                      <span
                        className="settings-sheet__path-value"
                        title={resourceSandbox.defaultPath}
                      >
                        {resourceSandbox.defaultPath}
                      </span>
                    }
                  />
                ) : null}
                {showManagedDataCustomCard ? (
                  <SummaryCard
                    label={copy.managedDataFolderCustom}
                    value={
                      <span
                        className="settings-sheet__path-value"
                        title={resourceSandbox.configuredPath}
                      >
                        {resourceSandbox.configuredPath}
                      </span>
                    }
                  />
                ) : null}
              </div>
              {showManagedDataFallbackNote ? (
                <p className="settings-sheet__note settings-sheet__note--compact">
                  {copy.managedDataFolderFallbackNote}
                </p>
              ) : null}
            </section>
          ) : null}

          <div className="settings-sheet__authority-block">
            <div className="settings-sheet__authority-block-head">
              <span className="eyebrow">{copy.currentWorkspace}</span>
              <ActionButton
                fullWidth={false}
                icon={<RefreshIcon size={14} />}
                label={copy.refreshWorkspaceAuthority}
                detail={settingsStatusPhrase(language, "rereadSandboxBoundary")}
                onClick={onRefreshWorkspaceAuthority}
              />
            </div>
            {workspaceAuthority ? (
              <WorkspaceAuthoritySummary
                language={language}
                authority={workspaceAuthority}
                className="workspace-authority-summary--compact"
              />
            ) : (
              <div className="empty-state settings-sheet__authority-empty">
                <span className="empty-state__icon" aria-hidden="true">
                  <GearIcon size={16} />
                </span>
                <span className="empty-state__title">{copy.workspaceAuthorityEmpty}</span>
              </div>
            )}
          </div>

            </div>
        </CollapseSection>
        </div>

        <CollapseSection
          level={1}
          persistenceKey="settings-advanced"
          open={advancedOpen}
          onToggle={setAdvancedOpen}
          title={<span className="eyebrow">{settingsGlobalCopy.settingsAdvanced}</span>}
          subtitle={<span className="settings-sheet__defaults-preview">{advancedSummaryText}</span>}
        >
            <div className="settings-sheet__minor-body settings-sheet__defaults-body">
              <div className="settings-grid settings-grid--compact settings-grid--tight">
                <div className="settings-row">
                  <span className="eyebrow">{copy.answerMode}</span>
                  <ChoiceList
                    active={answerMode}
                    items={[
                      { label: copy.auto, value: "auto" },
                      { label: copy.coachFirst, value: "coach-first" },
                      { label: copy.balanced, value: "balanced" },
                      { label: copy.direct, value: "direct" },
                    ]}
                    onChange={onAnswerModeChange}
                  />
                </div>
                <div className="settings-row">
                  <span className="eyebrow">{copy.teachingStyle}</span>
                  <ChoiceList
                    active={teachingStyle}
                    items={teachingStyleItems}
                    onChange={onTeachingStyleChange}
                  />
                </div>
                <div className="settings-row">
                  <span className="eyebrow">{copy.workingSet}</span>
                  <ChoiceList
                    active={workingSetMode}
                    items={[
                      { label: copy.workingSetFocused, value: "focused" },
                      { label: copy.workingSetBalanced, value: "balanced" },
                      { label: copy.workingSetBroad, value: "broad" },
                    ]}
                    onChange={(value) => onCoachDefaultsChange?.({ workingSetMode: value })}
                  />
                </div>
                <div className="settings-row">
                  <span className="eyebrow">{copy.theme}</span>
                  <ChoiceList
                    active={themePreference}
                    items={[
                      { label: copy.system, value: "system" },
                      { label: copy.light, value: "light" },
                      { label: copy.dark, value: "dark" },
                    ]}
                    onChange={onThemePreferenceChange}
                  />
                </div>
                <div className="settings-row">
                  <span className="eyebrow">{surfaceAlignmentCopy.label}</span>
                  <ChoiceList
                    active={learningSurfaceAlignment}
                    items={[
                      { label: surfaceAlignmentCopy.left, value: "left" },
                      { label: surfaceAlignmentCopy.right, value: "right" },
                    ]}
                    onChange={onLearningSurfaceAlignmentChange}
                  />
                </div>
              </div>

              <div className="settings-sheet__utility-grid">
                <section className="settings-sheet__workspace-card">
                  <span className="eyebrow">{copy.reviewStrategy}</span>
                  <div className="settings-sheet__stack">
                    <div className="settings-sheet__compact-row">
                      <span>{copy.reviewRhythmPace}</span>
                      <ChoiceList
                        active={reviewCadence}
                        items={reviewCadenceItems}
                        onChange={(value) => onCoachDefaultsChange?.({ reviewCadence: value })}
                      />
                    </div>
                    <div className="settings-sheet__compact-row">
                      <span>{copy.reviewRhythmReminder}</span>
                      <ChoiceList
                        active={reviewReminderMode}
                        items={reviewReminderItems}
                        onChange={(value) => onCoachDefaultsChange?.({ reviewReminderMode: value })}
                      />
                    </div>
                  </div>
                </section>

                <section className="settings-sheet__workspace-card">
                  <span className="eyebrow">{copy.systemActions}</span>
                  <div className="settings-actions settings-actions--compact">
                    <ActionButton
                      fullWidth={false}
                      icon={<RefreshIcon size={14} />}
                      label={copy.refreshMemory}
                      detail={language === "zh-CN" ? "重建摘要" : "Rebuild summary"}
                      onClick={onRefreshMemory}
                    />
                    <ActionButton
                      fullWidth={false}
                      icon={<LightningIcon size={14} />}
                      label={copy.resetDefaults}
                      detail={language === "zh-CN" ? "推荐值" : "Recommended"}
                      onClick={onResetDefaults}
                    />
                  </div>
                </section>
              </div>
            </div>
        </CollapseSection>
      </div>
    </section>
  );
}
