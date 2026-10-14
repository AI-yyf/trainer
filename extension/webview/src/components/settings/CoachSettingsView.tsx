import { templateCopy } from "../../templates/templateCopy";
import { SettingsIndex, type SettingsSectionId } from "../../templates/SettingsIndex";
import { SettingsDetail } from "../../templates/SettingsDetail";
import { SystemState } from "../../templates/SystemState";
import { useWorkbenchState } from "../../app/useWorkbenchState";
import {
  type ReactNode,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
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
  normalizeProviderBaseUrl,
  normalizeProviderProtocol,
  providerProtocolCompletionLabel,
  providerProtocolEndpointHint,
  looksLikeSchemelessProviderUrl,
  SUPPORTED_PROVIDER_PROTOCOLS,
} from "../../../../../shared/src/providerProtocols";
import {
  providerModelTokenLimitsKey,
  readProviderModelTokenLimit,
  resolveProviderModelTokenState,
  withProviderModelTokenLimit,
} from "../../../../../shared/src/providerModelTokenLimits";
import {
  evaluateProviderModelPolicy,
  filterProviderModelOptions,
} from "../../../../../shared/src/providerModelPolicy";
import type { ProviderModelTokenLimit, ProviderProtocol } from "../../../../../shared/src/models";
import {
  providerConnectionNameLabel,
  providerFailureCopy,
  providerModelCardCopy,
  sidecarRestartCopy,
} from "../../lib/i18n/segments/providerSettingsCopy";
import { MemorySharingPanel } from "./MemorySharingPanel";
import { providerRecoveryLocale } from "../../app/providerRecoveryCopy";
import {
  deriveProviderSetupState,
  type ProviderSetupReason,
} from "../../../../../shared/src/providerSetupState";
import type { ProviderEndpointSpeedTestResult } from "../../lib/types";
import {
  isNewApiConnectionType,
  parseProviderConnectionPaste,
} from "../../../../../shared/src/providerGateway";
import {
  PROVIDER_TEMPLATE_GROUPS,
  type ProviderTemplateGroup,
  PROVIDER_TEMPLATE_GROUP_ORDER,
  PROVIDER_TEMPLATE_LABELS,
} from "../../../../../shared/src/providerTemplateCatalog";
import { describeProviderThinking, normalizeProviderThinkingConfig, synthesizeProviderThinkingDescriptor, thinkingProtocolSupportsWire, updateProviderThinking } from "../../../../../shared/src/providerThinking";
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
import { ProviderEndpointSpeedTest } from "./ProviderEndpointSpeedTest";
import { ProviderQuickSetup } from "./ProviderQuickSetup";
import { WorkspaceRootRecoveryPanel } from "./WorkspaceRootRecoveryPanel";
import { WorkspaceAuthoritySummary } from "../coach/parts/WorkspaceAuthoritySummary";
import { CollapseSection } from "../common/CollapseSection";
import { StatusPill } from "../StatusPill";
import { ChevronDownIcon, ChevronLeftIcon, ChevronRightIcon, FileIcon, PlusIcon, RefreshIcon, TrashIcon, UploadIcon } from "../icons";
import { AlertTriangleIcon, DataFolderIcon, DoneIcon, ReloadIcon, SettingsShareIcon } from "../icons/inline";
import { RemoteIcon } from "../icons/brand/trainerBrand";
import { ResourcesNavIcon, TrainingNavIcon } from "../icons/navigation/coreNav";
import { SettingsAdvancedIcon, SettingsConnectionIcon, SettingsPreferencesIcon, SettingsSkillsIcon, SettingsTeachingIcon, SettingsWorkspaceIcon } from "../icons/navigation/settingsNav";
import { LANGUAGE_LABELS, SUPPORTED_LANGUAGES } from "../../../../../shared/src";
import { trainerCommands } from "../../../../../shared/src/commands";
import { remoteSupportStateView, REMOTE_SUPPORT_COPY } from "../../lib/i18n/segments/remoteSupportCopy";
import { settingsText } from "./settingsText";
import { languageIntegrityText } from "./languageIntegrityCopy";
import { useCoachSettingsViewState, useCoachSettingsHostFacts } from "./useCoachSettingsViewState";
import { useProviderConnection } from "../../app/providerConnectionContext";
import { postMessage as postWebviewMessage } from "../../lib/vscode";
import {
  trainerSkillCatalog,
  normalizeCustomSkillTrigger,
  resolveTrainerSkillText,
  trainerSkillSectionLabel,
  type TrainerCustomSkill,
  type TrainerSkillSection,
} from "../../../../../shared/src/skillCatalog";
import { resolveCopy as resolveWorkbenchCopy } from "../../lib/i18n/copy";
import {
  SETTINGS_FALLBACK_LABELS,
  englishLabels,
  extraLocalizedSettingsLabels,
  firstScreenRowLabels,
  localizedCatalogSavedModelsLabel,
  providerConnectionTruthCopyTable,
  providerDetailLabelTable,
  providerModelDiscoveryCopyTable,
  providerModelPickerCopyTable,
  providerTemplateGroupLabelTable,
  settingsPhraseTable,
  settingsStatusPhraseTable,
  settingsSupportPhraseTable,
  streamingVerificationCopyTable,
  toolsVerificationCopyTable,
  type ProviderConnectionTruthCopy,
  type ProviderDetailLabelKey,
  type SettingsPhraseKey,
  type SettingsStatusPhraseKey,
  type SettingsSupportPhraseKey,
  type ToolsVerificationCopy,
} from "../../lib/i18n/segments/settingsInlineText";
import type {
  CapabilityFlags,
  CoachAnswerMode,
  ComposerLanguage,
  ProviderConfigView,
  ProviderProbeUsage,
  TeachingStyle,
  WorkspaceMemoryToggles,
  WorkspaceAuthority,
} from "../../lib/types";

type AnswerMode = CoachAnswerMode;
type SaveState = "saved" | "unsaved" | "empty";
type AnswerStylePreset = "simple" | "balanced" | "deep" | "custom";
const DEFAULT_PROVIDER_CONNECTION_NAME = "custom-openai-compatible";
// P0: the model picker renders the full known list — search still filters, the
// select scrolls. The only remaining cap is a defensive guard against an
// absurd catalog (>= 200 entries), never a UI truncation of real data.
const MODEL_PICKER_DEFENSIVE_OPTION_LIMIT = 200;
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
  // Shared canonicalizer keeps the webview draft on the same base URL the host
  // will test and save (scheme defaults, paste-full endpoint collapsing).
  return normalizeProviderBaseUrl(value, protocol);
}

function looksLikeProviderServiceAddress(value: string): boolean {
  return /^https?:\/\//i.test(value.trim()) || looksLikeSchemelessProviderUrl(value);
}

function looksLikeProviderApiKeyToken(value: string): boolean {
  const trimmed = value.trim();
  if (!trimmed || /\s|[/.:]/.test(trimmed)) {
    return false;
  }
  if (/^(?:sk|rk|pk|csk|gsk|xai|ghp|gho|key)[-_][A-Za-z0-9._-]{8,}$/i.test(trimmed)) {
    return true;
  }
  return /^[A-Za-z0-9_-]{20,}$/.test(trimmed);
}

function providerConnectionLabelFromPaste(
  paste: ReturnType<typeof parseProviderConnectionPaste>,
): string {
  if (paste && isNewApiConnectionType(paste.connectionType)) {
    return "New API";
  }
  if (paste) {
    const host = paste.baseUrl.replace(/^https?:\/\//i, "").split(/[/:]/)[0];
    const label = host.replace(/^api\./i, "").split(".")[0].trim();
    if (label) {
      return `${label.charAt(0).toUpperCase()}${label.slice(1)} relay`;
    }
  }
  return "custom-openai-compatible";
}


function providerConnectionTruthCopy(language: ComposerLanguage): ProviderConnectionTruthCopy {
  return providerConnectionTruthCopyTable[language] ?? providerConnectionTruthCopyTable["en-US"];
}

function providerTemplateGroupLabel(
  language: ComposerLanguage,
  group: ProviderTemplateGroup,
): string {
  return providerTemplateGroupLabelTable[language][group];
}

function providerDetailLabel(language: ComposerLanguage, key: ProviderDetailLabelKey): string {
  return providerDetailLabelTable[language]?.[key] ?? providerDetailLabelTable["en-US"][key];
}

function providerBaseUrlGuidance(
  language: ComposerLanguage,
  protocol: ProviderProtocol | undefined,
  endpointHint: string,
): string {
  if (!protocol) {
    return settingsText(language, "先选择协议，再填写服务根地址。未知网关不会被默认成 OpenAI 兼容。", "Select a protocol before entering the service root. Unknown gateways are not assumed OpenAI-compatible.");
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
  return providerModelDiscoveryCopyTable[language] ?? providerModelDiscoveryCopyTable["en-US"];
}

function providerModelPickerCopy(language: ComposerLanguage): {
  filterPlaceholder: string;
  filterLabel: string;
  noMatches: string;
  refreshListDetail: string;
  enterModelName: string;
  useTypedModel: (model: string) => string;
  moreMatchesHint: (count: number) => string;
  saveAndUseConnection: string;
  directModelPlaceholder: string;
  directModelHint: string;
  modelRequiredNote: string;
} {
  return providerModelPickerCopyTable[language] ?? providerModelPickerCopyTable["en-US"];
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
  thinkingConfig?: ProviderThinkingConfig;
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
  memoryPersonalTrustTitle: string;
  memoryPersonalTrustDetail: string;
  memoryPersonalTrustEnable: string;
  memoryPersonalTrustDisable: string;
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
  workspaceDataArea: string;
  workspaceDataUnderRoot: string;
  workspaceDataInAppFolder: string;
  workspaceDataMoveUnderRoot: string;
  workspaceAdvanced: string;
  addedProjects: string;
  addedProjectsEmpty: string;
  addedProjectsCurrent: string;
  addedProjectsBrowse: string;
  projectRemove: string;
  projectRemoveNote: string;
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

/**
 * App-facing Settings boundary (props-debt round: settings shell).
 *
 * App keeps only what it genuinely owns at this boundary: the session chrome
 * it renders itself (`skillSharing`, `sectionRequest`), the capability verdict
 * and image-input state scoped to App's provider-test clock, the per-section
 * action status derived from App's settings action state, and the callbacks
 * closing over App-local state (preview session, settings actions, the
 * debounced coach-settings persist).
 *
 * Everything else this view used to receive as props is now derived inside the
 * shell below: workspace/session facts (`workspaceId`, `workspaceAuthority`,
 * `workspaceTrustState`) through `useCoachSettingsHostFacts` — the same pure
 * expressions App applies — the coach-chrome summary strings through the same
 * shared label helpers, and the connection draft/speed-test/focus state through
 * the App-published provider-connection context (one controller instance, so
 * the unsaved draft survives Settings unmounts exactly as before).
 */
export interface CoachSettingsViewProps {
  /** Deep-linked section request (App-owned settings state). */
  sectionRequest?: { category: SettingsSectionId; requestId: number; skillTrigger?: string };
  /** App-rendered skill-sharing chrome (App JSX, guard-pinned). */
  skillSharing?: ReactNode;
  /** Capability verdict scoped to App's provider-test clock (App-shared). */
  capabilityVerdict: TrainerCapabilityVerdict;
  providerImageInputState?: ProviderImageInputState;
  /** App-derived coach state summary (shared with App's own rail). */
  coachStateSummary?: ReactNode;
  /** App-derived review rhythm summary (shared with App's plan rail). */
  reviewRhythmSummary?: string;
  /** Per-section action status derived from App's settings action state. */
  providerStatus?: SettingsSectionStatus;
  coachDefaultsStatus?: SettingsSectionStatus;
  workspaceControlStatus?: SettingsSectionStatus;
  providerSaveBusy?: boolean;
  companionInstallState?: import("../../../../../shared/src/companionInstallState").CompanionInstallState;
  /**
   * App-owned debounced persist trigger for the layout knobs the view flips
   * through useCoachSettingsViewState (the old `autosaving(...)` wrappers).
   */
  onCoachSettingsMutated?: () => void;
  onSaveCoachSettings?: () => void;
  onSaveProvider?: () => void;
  onSaveProviderProfile?: () => void;
  onUseProviderTemplateLabel?: (templateLabel: string) => void;
  onRefreshProviderProfiles?: () => void;
  onSwitchProviderProfile?: (profileId: string) => void;
  onRefreshProviderModels?: () => void;
  onTestProvider?: () => void;
  onRestartSidecar?: () => void;
  onClearProvider?: () => void;
  onOpenConfig?: () => void;
  onResetDefaults?: () => void;
}

/**
 * Full sheet contract (renamed from the former single `CoachSettingsViewProps`):
 * the shell below resolves the sunk values and hands the sheet the exact same
 * fields as before, so the sheet body is untouched.
 */
interface CoachSettingsViewSheetProps {
  workspaceId?: string;
  capabilityVerdict: TrainerCapabilityVerdict;
  providerImageInputState?: ProviderImageInputState;
  providerDraft: ProviderDraft;
  coachStateSummary?: ReactNode;
  coachSignal?: string;
  reviewRhythmSummary?: string;
  nextReviewDue?: string;
  workspaceAuthority?: WorkspaceAuthority | null;
  /** Live host/sidecar trust; leftover-not-live must pass undefined → unknown, never invent Ready. */
  workspaceTrustState?: WorkspaceTrustState | string | null;
  className?: string;
  labels?: Partial<CoachSettingsLabels>;
  onProviderDraftChange: (patch: Partial<ProviderDraft>) => void;
  providerStatus?: SettingsSectionStatus;
  coachDefaultsStatus?: SettingsSectionStatus;
  workspaceControlStatus?: SettingsSectionStatus;
  companionInstallState?: import("../../../../../shared/src/companionInstallState").CompanionInstallState;
  providerApiKeyFocusRequest?: number;
  sectionRequest?: { category: SettingsSectionId; requestId: number; skillTrigger?: string };
  skillSharing?: ReactNode;
  /**
   * App-owned debounced persist trigger for the layout knobs the view flips
   * through useCoachSettingsViewState (the old `autosaving(...)` wrappers).
   */
  onCoachSettingsMutated?: () => void;
  onSaveCoachSettings?: () => void;
  onSaveProvider?: () => void;
  onSaveProviderProfile?: () => void;
  providerSpeedTestResults?: ProviderEndpointSpeedTestResult[];
  providerSpeedTestPending?: boolean;
  providerSaveBusy?: boolean;
  onSpeedTestEndpoints?: (urls: string[]) => void;
  onUseProviderTemplateLabel?: (templateLabel: string) => void;
  onRefreshProviderProfiles?: () => void;
  onSwitchProviderProfile?: (profileId: string) => void;
  onRefreshProviderModels?: () => void;
  onTestProvider?: () => void;
  onRestartSidecar?: () => void;
  onClearProvider?: () => void;
  onOpenConfig?: () => void;
  onResetDefaults?: () => void;
}

function localizedSettingsLabels(language: ComposerLanguage): Partial<CoachSettingsLabels> {
  const copy = resolveWorkbenchCopy(language);
  const firstScreenRows = firstScreenRowLabels[language] ?? firstScreenRowLabels["en-US"];
  return {
    // §十五: labels the shared workbench copy does not cover, in eight languages.
    ...extraLocalizedSettingsLabels[language],
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
    memoryPersonalTrustTitle: copy.settingsMemoryPersonalTrustTitle,
    memoryPersonalTrustDetail: copy.settingsMemoryPersonalTrustDetail,
    memoryPersonalTrustEnable: copy.settingsMemoryPersonalTrustEnable,
    memoryPersonalTrustDisable: copy.settingsMemoryPersonalTrustDisable,
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

function settingsPhrase(language: ComposerLanguage, key: SettingsPhraseKey): string {
  return settingsPhraseTable[language][key] ?? settingsPhraseTable["en-US"][key];
}

function settingsSupportPhrase(language: ComposerLanguage, key: SettingsSupportPhraseKey): string {
  return settingsSupportPhraseTable[language][key] ?? settingsSupportPhraseTable["en-US"][key];
}

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
  // One themed pull-down per row: trigger shows the current choice, the
  // listbox opens below, closes on outside click or on pick.
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const focusChoiceOnOpenRef = useRef(false);
  useEffect(() => {
    if (!open) {
      return;
    }
    if (focusChoiceOnOpenRef.current) {
      rootRef.current?.querySelector<HTMLButtonElement>('[role="option"][aria-selected="true"]')?.focus();
      focusChoiceOnOpenRef.current = false;
    }
    const onDocMouseDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [open]);
  const effective = active ?? items[0]?.value;
  const current = items.find((item) => item.value === effective) ?? items[0];
  return (
    <div className="settings-sheet__group settings-choice" ref={rootRef} onKeyDown={(event) => {
      if (event.key === "Escape" && open) {
        event.preventDefault();
        setOpen(false);
        triggerRef.current?.focus();
        return;
      }
      if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      if (!open) {
        focusChoiceOnOpenRef.current = true;
        setOpen(true);
        return;
      }
      const options = Array.from(rootRef.current?.querySelectorAll<HTMLButtonElement>('[role="option"]') ?? []);
      if (!options.length) return;
      const focusedIndex = options.findIndex((option) => option === document.activeElement);
      const index = focusedIndex >= 0 ? focusedIndex
        : options.findIndex((option) => option.getAttribute("aria-selected") === "true");
      const next = event.key === "Home" ? 0 : event.key === "End" ? options.length - 1
        : (index + (event.key === "ArrowDown" ? 1 : -1) + options.length) % options.length;
      options[next]?.focus();
    }}>
      <button
        ref={triggerRef}
        type="button"
        className="settings-choice__trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="settings-choice__trigger-label">{current?.label}</span>
        <ChevronDownIcon size={12} aria-hidden="true" />
      </button>
      {open ? (
        <div className="settings-choice__list" role="listbox">
          {items.map((item) => (
            <button
              key={item.value}
              type="button"
              role="option"
              aria-selected={item.value === effective}
              className={`settings-choice__option ${item.value === effective ? "is-active" : ""}`}
              onClick={() => {
                onChange?.(item.value);
                setOpen(false);
                triggerRef.current?.focus();
              }}
            >
              {item.label}
            </button>
          ))}
        </div>
      ) : null}
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
  const labels: string[] = [];

  if (capabilities?.chat) {
    labels.push(settingsText(language, "对话", "Chat"));
  }
  if (capabilities?.responses) {
    labels.push("Responses");
  }
  if (capabilities?.streaming) {
    labels.push(settingsText(language, "流式", "Streaming"));
  }
  if (capabilities?.tools) {
    labels.push(settingsText(language, "声明工具", "Declared tools"));
  }
  if (capabilities?.structuredOutput) {
    labels.push(settingsText(language, "结构化", "Structured"));
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
    return settingsText(language, "未声明", "Not declared");
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
          title={row.detail}
          onClick={row.onToggle}
        >
          <strong>{row.label}</strong>
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

function formatProbeCostValue(value: number | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "-";
  }
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 8 }).format(value);
}

/**
 * §二十一: probe usage detail from provider-reported numbers only. Each part
 * stays hidden when the provider did not report it — nothing is estimated.
 */
function describeProbeUsageDetail(
  usage: ProviderProbeUsage | undefined,
  language: ComposerLanguage,
): string | undefined {
  if (!usage) {
    return undefined;
  }
  const parts: string[] = [];
  if (
    typeof usage.totalTokens === "number" &&
    Number.isFinite(usage.totalTokens) &&
    usage.totalTokens > 0
  ) {
    parts.push(`${formatTokenValue(usage.totalTokens)} tokens`);
  }
  if (typeof usage.totalCost === "number" && Number.isFinite(usage.totalCost)) {
    parts.push(`${settingsPhrase(language, "probeCost")} ${formatProbeCostValue(usage.totalCost)}`);
  }
  return parts.length > 0 ? parts.join(" · ") : undefined;
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

function toolsVerificationCopy(language: ComposerLanguage): ToolsVerificationCopy {
  return toolsVerificationCopyTable[language] ?? toolsVerificationCopyTable["en-US"];
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
  return streamingVerificationCopyTable[language] ?? streamingVerificationCopyTable["en-US"];
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
    return {
    label: settingsText(language, "思考", "Thinking"),
    verified: settingsText(language, "已验证", "Verified"),
    notVerified: settingsText(language, "未验证", "Not verified"),
    needsVerification: settingsText(language, "先测试连接。MiniMax 只用 extra_body.thinking，未验证前不会发送 enabled。", "Test this connection first. MiniMax uses extra_body.thinking; enabled is not sent without live evidence."),
    verifiedDetail: settingsText(language, "最近一次测试观察到了原生思考字段。", "The last test observed the native thinking field."),
    disabledDetail: settingsText(language, "当前请求会发送 thinking.type=disabled，避免短回复被思考占满。", "Requests currently send thinking.type=disabled so short replies are not consumed by hidden thought."),
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
    return {
    label: settingsText(language, "视觉", "Vision"),
    verified: settingsText(language, "已验证", "Verified"),
    notVerified: settingsText(language, "未验证", "Not verified"),
    notSupported: settingsText(language, "不支持", "Not supported"),
    needsVerification: settingsText(language, "先测试连接。声明或默认能力不会让视觉显示为就绪。", "Test this connection first. Declared or default capabilities do not make vision ready."),
    verifiedDetail: settingsText(language, "最近一次测试观察到了可用的视觉输入。", "The latest test observed usable vision input."),
    unsupportedDetail: settingsText(language, "最近一次测试没有观察到可用的视觉输入。", "The latest test did not observe usable vision input."),
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
  return settingsText(language, "已识别 New API 网关。目录里的 endpoint 类型只是声明，要以测试结果为准。", "New API gateway identified. Catalog endpoint types are claims; use the live test.");
}

function protocolChoiceLabel(protocol: ProviderProtocol | undefined, language: ComposerLanguage): string {
  if (!protocol) {
    return settingsText(language, "未选择协议", "Protocol unverified");
  }
  switch (protocol) {
    case "openai_responses":
      return settingsText(language, "OpenAI 响应", "OpenAI Responses");
    case "openai_chat_completions":
      return settingsText(language, "OpenAI 聊天", "OpenAI Chat");
    case "anthropic_messages":
      return settingsText(language, "Anthropic", "Anthropic");
    case "openai_chat_completions_compatible":
      return settingsText(language, "OpenAI 兼容", "OpenAI Compat");
    case "gemini_generate_content":
      return settingsText(language, "Gemini", "Gemini");
  }

  return providerProtocolCompletionLabel(protocol);
}


function isMiniMaxLikeProvider(provider: Pick<ProviderConfigView, "name" | "baseUrl" | "model">): boolean {
  return /minimax/i.test(`${provider.name} ${provider.baseUrl} ${provider.model}`);
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
  const integrity = (zh: string, en: string) => languageIntegrityText(language, zh, en);
  const lastTest = provider.lastTestResult;
  const lastCategory = provider.modelErrorCategory ?? lastTest?.errorCategory ?? lastTest?.status;
  const lastTestWasZh = Boolean(lastTest?.responseLanguage?.toLowerCase().startsWith("zh"));

  if (!provider.configured) {
    return {
      value: integrity("待设置", "Setup"),
      tone: "offline",
      detail: integrity("先保存一组 connection，然后再跑 zh-CN 输入检查。", "Save a connection first, then run a zh-CN integrity check."),
    };
  }

  if (!provider.apiKeyConfigured) {
    return {
      value: integrity("缺 API key", "Add API key"),
      tone: "offline",
      detail: integrity("补上 API key 后，再验证 zh-CN 输入是否完整。", "Add an API key before checking zh-CN input integrity."),
    };
  }

  if (lastCategory === "language_corruption") {
    return {
      value: integrity("请先换服务", "Chinese blocked"),
      tone: "warn",
      detail: integrity("这条连接在发送中文时出了问题。请更换模型服务或访问地址，或者暂时用英文继续。", "This connection corrupts zh-CN input before the model sees it. Switch provider or gateway, or use English for now."),
    };
  }

  if (lastCategory === "language_probe_inconclusive") {
    return {
      value: integrity("待验证", "Needs zh-CN test"),
      tone: "warn",
      detail: integrity("连接可以使用，但中文内容还没有验证完成。请先重新测试；必要时可暂时用英文继续。", "The connection is reachable, but zh-CN input is not fully verified yet. English fallback is safer until you retest."),
    };
  }

  if (lastTest?.ok && lastTestWasZh) {
    return {
      value: integrity("已验证", "Verified"),
      tone: "connected",
      detail: integrity("最近一次测试已经确认 zh-CN 输入能完整到达模型。", "The latest test confirmed zh-CN input reaches the model intact."),
    };
  }

  if (coachSendState.blocked) {
    return {
      value: integrity("待恢复", "Unavailable"),
      tone: "warn",
      detail: integrity("先把 chat connection 恢复到可用，然后再检查 zh-CN 输入完整性。", "Recover the chat connection first, then verify zh-CN input integrity."),
    };
  }

  if (lastTest?.ok) {
    return {
      value: integrity("未测 zh-CN", "zh-CN not tested"),
      tone: "pending",
      detail: integrity("这条 connection 已通过测试，但最近一次还不是 zh-CN 输入。如果你要用中文教练，请再跑一次 zh-CN 测试。", "This connection passed a test, but not with zh-CN input. Run one zh-CN test before relying on Chinese coaching."),
    };
  }

  return {
    value: integrity("待测试", "Run test"),
    tone: "pending",
    detail: integrity("连接已可用，但 zh-CN 输入还没有真正验证过。", "The connection can work, but zh-CN input has not been verified yet."),
  };
}

/**
 * Settings shell (the exported, lazily loaded view). Derives the sunk values
 * from the store and App's published connection instance, then renders the
 * sheet with the exact same fields it always received.
 */
export function CoachSettingsView({
  sectionRequest,
  skillSharing,
  capabilityVerdict,
  providerImageInputState,
  coachStateSummary,
  reviewRhythmSummary,
  providerStatus,
  coachDefaultsStatus,
  workspaceControlStatus,
  providerSaveBusy,
  companionInstallState,
  onCoachSettingsMutated,
  onSaveCoachSettings,
  onSaveProvider,
  onSaveProviderProfile,
  onUseProviderTemplateLabel,
  onRefreshProviderProfiles,
  onSwitchProviderProfile,
  onRefreshProviderModels,
  onTestProvider,
  onRestartSidecar,
  onClearProvider,
  onOpenConfig,
  onResetDefaults,
}: CoachSettingsViewProps) {
  // App's single provider-connection controller instance (draft, speed test,
  // API-key focus): the same instance App's composer and deep links use.
  const {
    providerDraft,
    setProviderDraft,
    providerApiKeyFocusRequest,
    providerSpeedTestResults,
    providerSpeedTestPending,
    runProviderSpeedTest,
  } = useProviderConnection();
  // Host-owned workspace/session facts, derived with App's exact expressions.
  const {
    settingsWorkspaceId,
    liveSandboxState,
    effectiveWorkspaceTrustState,
    coachSignal,
    nextReviewDue,
  } = useCoachSettingsHostFacts();
  return (
    <CoachSettingsViewSheet
      sectionRequest={sectionRequest}
      skillSharing={skillSharing}
      capabilityVerdict={capabilityVerdict}
      providerImageInputState={providerImageInputState}
      coachStateSummary={coachStateSummary}
      reviewRhythmSummary={reviewRhythmSummary}
      providerStatus={providerStatus}
      coachDefaultsStatus={coachDefaultsStatus}
      workspaceControlStatus={workspaceControlStatus}
      providerSaveBusy={providerSaveBusy}
      companionInstallState={companionInstallState}
      onCoachSettingsMutated={onCoachSettingsMutated}
      onSaveCoachSettings={onSaveCoachSettings}
      onSaveProvider={onSaveProvider}
      onSaveProviderProfile={onSaveProviderProfile}
      onUseProviderTemplateLabel={onUseProviderTemplateLabel}
      onRefreshProviderProfiles={onRefreshProviderProfiles}
      onSwitchProviderProfile={onSwitchProviderProfile}
      onRefreshProviderModels={onRefreshProviderModels}
      onTestProvider={onTestProvider}
      onRestartSidecar={onRestartSidecar}
      onClearProvider={onClearProvider}
      onOpenConfig={onOpenConfig}
      onResetDefaults={onResetDefaults}
      workspaceId={settingsWorkspaceId}
      workspaceAuthority={liveSandboxState?.authority}
      workspaceTrustState={effectiveWorkspaceTrustState}
      className="settings-pane"
      coachSignal={coachSignal}
      nextReviewDue={nextReviewDue}
      providerDraft={providerDraft}
      providerApiKeyFocusRequest={providerApiKeyFocusRequest}
      providerSpeedTestResults={providerSpeedTestResults}
      providerSpeedTestPending={providerSpeedTestPending}
      onSpeedTestEndpoints={runProviderSpeedTest}
      onProviderDraftChange={(patch) => {
        setProviderDraft((current) => {
          const hasProtocol = Object.prototype.hasOwnProperty.call(patch, "protocol");
          const hasBaseUrl = Object.prototype.hasOwnProperty.call(patch, "baseUrl");
          const hasModel = Object.prototype.hasOwnProperty.call(patch, "model");
          const hasModelTokenLimits = Object.prototype.hasOwnProperty.call(patch, "modelTokenLimits");
          const hasContextWindowTokens = Object.prototype.hasOwnProperty.call(
            patch,
            "contextWindowTokens",
          );
          const hasMaxOutputTokens = Object.prototype.hasOwnProperty.call(patch, "maxOutputTokens");
          const nextProtocol = hasProtocol
            ? normalizeProviderProtocol(patch.protocol) ?? current.protocol
            : current.protocol;
          const nextBaseUrl =
            hasBaseUrl && typeof patch.baseUrl === "string" ? patch.baseUrl : current.baseUrl;
          const normalizedCurrentBaseUrl = current.baseUrl.trim().replace(/\/+$/, "");
          const normalizedNextBaseUrl = nextBaseUrl.trim().replace(/\/+$/, "");
          const transportChanged =
            (hasProtocol && normalizeProviderProtocol(current.protocol) !== nextProtocol) ||
            (hasBaseUrl && normalizedCurrentBaseUrl !== normalizedNextBaseUrl);

          if (transportChanged) {
            return {
              ...current,
              ...patch,
              protocol: nextProtocol,
              model: "",
              contextWindowTokens: undefined,
              maxOutputTokens: undefined,
              modelTokenLimits: undefined,
              catalogModels: [],
            };
          }

          if (!hasModel && !hasModelTokenLimits && !hasContextWindowTokens && !hasMaxOutputTokens) {
            return {
              ...current,
              ...patch,
            };
          }

          const nextModel =
            hasModel && typeof patch.model === "string" ? patch.model : current.model;
          const tokenState = resolveProviderModelTokenState(current, nextModel, {
            modelTokenLimits: hasModelTokenLimits ? patch.modelTokenLimits : current.modelTokenLimits,
            hasModelTokenLimits,
            contextWindowTokens: patch.contextWindowTokens,
            maxOutputTokens: patch.maxOutputTokens,
            hasContextWindowTokens,
            hasMaxOutputTokens,
          });

          return {
            ...current,
            ...patch,
            model: nextModel,
            contextWindowTokens: tokenState.contextWindowTokens,
            maxOutputTokens: tokenState.maxOutputTokens,
            modelTokenLimits: tokenState.modelTokenLimits,
          };
        });
      }}
    />
  );
}

function CoachSettingsViewSheet({
  workspaceId,
  capabilityVerdict,
  providerImageInputState,
  providerDraft,
  coachStateSummary,
  coachSignal,
  reviewRhythmSummary,
  nextReviewDue,
  workspaceAuthority,
  workspaceTrustState,
  className,
  labels,
  onProviderDraftChange,
  providerStatus,
  coachDefaultsStatus,
  workspaceControlStatus,
  companionInstallState,
  providerApiKeyFocusRequest,
  sectionRequest,
  skillSharing,
  onCoachSettingsMutated,
  onSaveCoachSettings,
  onSaveProvider,
  onSaveProviderProfile,
  providerSpeedTestResults = [],
  providerSpeedTestPending = false,
  providerSaveBusy = false,
  onSpeedTestEndpoints,
  onUseProviderTemplateLabel,
  onRefreshProviderProfiles,
  onSwitchProviderProfile,
  onRefreshProviderModels,
  onTestProvider,
  onRestartSidecar,
  onClearProvider,
  onOpenConfig,
  onResetDefaults,
}: CoachSettingsViewSheetProps) {
  // §props-debt: store-resident facts, layout knobs, leftover-gated profile
  // fields and pure command relays resolve through the selector hook instead
  // of props; the identifiers below keep their historical names so the rest
  // of this view is untouched.
  const {
    provider,
    backendConnectionState,
    memoryShareGrants,
    resourceSandbox,
    trainerWorkspace,
    trainerProjects,
    remoteWorkspaceName,
    personalAccountTrusted,
    themePreference,
    learningSurfaceAlignment,
    language,
    answerMode,
    teachingStyle,
    coachDefaults,
    followCurrentFile,
    contextDetail,
    includeCurrentFile,
    includeSelection,
    includeDiagnostics,
    includeRelatedFiles,
    learnerName,
    targetProject,
    preferredRhythm,
    preferredLearningMode,
    onboardingRequest,
    projectContext,
    longTermMemoryStateLabel,
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
    onNavigateToView,
    onGenerateSkillDraft,
    onGrantMemoryShare,
    onRevokeMemoryShare,
    onSetPersonalAccountTrust,
    onTrustWindow,
    onRefreshWorkspaceAuthority,
    onChooseTrainerWorkspaceRoot,
    onMigrateTrainerWorkspaceRoot,
    onBackupTrainerWorkspace,
    onRestoreTrainerWorkspaceBackup,
    onChooseManagedDataFolder,
    onResetManagedDataFolder,
    onRemoveTrainerProject,
    onMoveManagedDataUnderRoot,
    onRefreshMemory,
    onShareSession,
  } = useCoachSettingsViewState({ onCoachSettingsMutated });
  // §十五: user-visible labels for all eight languages resolve through
  // localizedSettingsLabels (shared workbench copy + extraLocalizedSettingsLabels).
  // This base only guarantees full label coverage per language; it never
  // decides user-visible copy.
  const baseLabels = {
    ...SETTINGS_FALLBACK_LABELS[language],
    ...localizedSettingsLabels(language),
  };
  const copy: CoachSettingsLabels = {
    ...englishLabels,
    ...baseLabels,
    auto: adaptiveBehaviorLabel(language, "both"),
    ...labels,
  } as CoachSettingsLabels;
  const settingsGlobalCopy = resolveWorkbenchCopy(language);
  const surfaceAlignmentCopy = learningSurfaceAlignmentCopy(language);
  const classes = ["settings-sheet", "coach-settings-view", className].filter(Boolean).join(" ");
  const providerDirectoryRef = useRef<HTMLDivElement | null>(null);
  const providerTemplatesRef = useRef<HTMLDivElement | null>(null);
  const [connectionView, setConnectionView] = useState<"auto" | "edit" | "add" | "advanced">("auto");
  const [advancedReturnView, setAdvancedReturnView] = useState<"auto" | "edit">("auto");
  const apiKeyInputRef = useRef<HTMLInputElement | null>(null);
  const modelPickerRef = useRef<HTMLDetailsElement | null>(null);

  const modelSearchInputRef = useRef<HTMLInputElement | null>(null);
  const modelSelectRef = useRef<HTMLSelectElement | null>(null);
  const connectionAnchorRef = useRef<HTMLDivElement | null>(null);
  const teachingPrefsAnchorRef = useRef<HTMLDivElement | null>(null);
  const workspaceAnchorRef = useRef<HTMLDivElement | null>(null);
  const preferencesAnchorRef = useRef<HTMLDivElement | null>(null);
  const sectionFlashTimerRef = useRef<number | null>(null);
  const [modelPickerOpen, setModelPickerOpen] = useState(() => !providerDraft.model.trim());
  type SettingsCategory = SettingsSectionId;
  // 已配置过的连接回访时直接落在连接详情;只有冷启动(未配置)才先看 Index。
  const [settingsIndexOpen, setSettingsIndexOpen] = useState(
    !providerApiKeyFocusRequest && !(provider.configured && Boolean(provider.model.trim())),
  );
  const [activeSettingsCategory, setActiveSettingsCategory] =
    useState<SettingsCategory>("connection");
  const openSettingsCategorySection = (id: SettingsCategory) => {
    setSettingsIndexOpen(false);
    setActiveSettingsCategory(id);
  };
  const [advancedContextPinned, setAdvancedContextPinned] = useState<boolean | undefined>();
  const [customSkillDraft, setCustomSkillDraft] = useState({
    trigger: "",
    title: "",
    prompt: "",
    detail: "",
  });
  const [customSkillDescription, setCustomSkillDescription] = useState("");
  const [customSkillGenerating, setCustomSkillGenerating] = useState(false);
  // r1-g2-5: the empty state shows ONE "添加技能" primary; the creation form
  // expands on click so the create CTA is reachable in the first screenful.
  const [customSkillFormOpen, setCustomSkillFormOpen] = useState(false);
  const [customSkillSource, setCustomSkillSource] = useState<"model" | "template" | null>(null);
  const [customSkillError, setCustomSkillError] = useState<string | null>(null);
  useEffect(() => {
    if (!sectionRequest) return;
    setSettingsIndexOpen(false);
    setActiveSettingsCategory(sectionRequest.category);
    if (sectionRequest.skillTrigger) setCustomSkillDraft((draft) => ({ ...draft, trigger: sectionRequest.skillTrigger ?? "" }));
  }, [sectionRequest]);
  // Deep-link contract: another surface calls
  // `useWorkbenchState.getState().requestSettingsCategory(category)` right
  // before `setActiveView("settings")`. Open the requested section once (the
  // four SettingsSectionId values; anything unknown falls back to the index),
  // then consume the request so it never re-fires.
  const settingsCategoryRequest = useWorkbenchState((state) => state.settingsCategoryRequest);
  useEffect(() => {
    if (!settingsCategoryRequest) {
      return;
    }
    const category = settingsCategoryRequest;
    useWorkbenchState.getState().consumeSettingsCategoryRequest();
    if (
      category === "connection" ||
      category === "workspace" ||
      category === "teaching" ||
      category === "preferences"
    ) {
      setSettingsIndexOpen(false);
      setActiveSettingsCategory(category);
    } else {
      setSettingsIndexOpen(true);
    }
  }, [settingsCategoryRequest]);
  const [providerApiKeyFocusRequested, setProviderApiKeyFocusRequested] = useState(false);
  const [providerProfilesFocusRequested, setProviderProfilesFocusRequested] = useState(false);
  const [providerTemplatesFocusRequested, setProviderTemplatesFocusRequested] = useState(false);
  const [providerPasteHint, setProviderPasteHint] = useState<string | null>(null);
  const [sectionFlash, setSectionFlash] = useState<SettingsCategory | null>(null);
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
  const revealSettingsSection = (target: SettingsCategory) => {
    setSettingsIndexOpen(false);
    setActiveSettingsCategory(target);
    // The anchor node mounts only after the category pane swaps in, so wait
    // two frames before scrolling/flashing.
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        const node =
          target === "connection"
            ? connectionAnchorRef.current
            : target === "teaching"
              ? teachingPrefsAnchorRef.current
              : target === "workspace"
                ? workspaceAnchorRef.current
                : preferencesAnchorRef.current;
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
    setSettingsIndexOpen(false);
    setActiveSettingsCategory("connection");
    setConnectionView("edit");
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
  // Unified-root model (P0): data "at home" means the effective data directory
  // lives inside the workspace root (its .trainer/ data area). Anything else —
  // the app (globalStorage) default or an arbitrary custom folder — surfaces
  // the one-click move-under-root action.
  const managedDataUnderRoot = Boolean(
    resourceSandbox?.effectivePath &&
      trainerWorkspace?.rootPath &&
      managedDataEffectivePathKey?.startsWith(
        normalizeComparablePath(trainerWorkspace.rootPath) ?? "\u0000",
      ),
  );
  // Settings "added projects" rows (reference-only removal; host confirms).
  const addedProjectRows = trainerProjects?.projects ?? [];

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
  // Send readiness is configuration completeness only (P0 save-and-go): a
  // passing test and a verified streaming probe stay as diagnostic facts below,
  // never as a send gate.
  const providerCoachReady = !coachSendState.blocked;
  const providerNeedsApiKey = providerSaved && !provider.apiKeyConfigured;
  const providerCoachBlockReason = coachSendState.blocked
    ? coachSendState.reason
    : undefined;
  const reviewSummary = reviewRhythmSummary ?? copy.off;
  const runtimeStatusLabel = providerCoachReady
    ? settingsText(language, "可发送", "Ready")
    : providerNeedsApiKey
      ? settingsText(language, "需补密钥", "Add API key")
    : providerSaved
      ? settingsText(language, "需检查", "Needs attention")
    : settingsText(language, "待配置", "Setup");
  const providerStatusLabel = providerCoachReady
    ? copy.configured
    : providerNeedsApiKey
      ? copy.apiKeyMissing
    : providerSaved
      ? settingsText(language, "需检查", "Needs attention")
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
  const backendStarting = backendConnectionState === "starting";
  const backendUnavailable = backendConnectionState === "offline" ||
    (backendConnectionState === undefined && providerFailureCategory === "sidecar_unavailable");
  const backendRecovery = backendStarting || backendUnavailable
    ? providerRecoveryLocale(language).summary[backendStarting ? "starting" : "offline"]
    : undefined;
  const canRestartSidecar = backendUnavailable && Boolean(onRestartSidecar);
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

  const safeProviderFailureHint =
    providerErrorHint({ modelErrorCategory: providerFailureCategory }, language) ??
    (settingsText(language, "请检查连接设置后重试。", "Check the connection settings and try again."));
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
  const probeUsageDetail = describeProbeUsageDetail(lastTest?.probeUsage, language);
  const lastTestDetail = lastTest
    ? `${formatTimestamp(lastTest.checkedAt, language)} · ${
        providerTestPassed
          ? settingsSupportPhrase(language, "connectionVerified")
          : lastTest.ok || providerTestFreshness !== "fresh"
            ? settingsStatusPhrase(language, "connectionSavedNeedsTest")
            : safeProviderFailureHint
      }${probeUsageDetail ? ` · ${probeUsageDetail}` : ""}`
    : undefined;
  const coachStateText =
    stringifyNode(coachStateSummary) ??
    (coachStateSummary ? (settingsText(language, "已生成", "Available")) : undefined);
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
  const reviewCadenceItems = [
    { label: settingsText(language, "轻", "Light"), value: "light" as const },
    { label: settingsText(language, "标准", "Standard"), value: "steady" as const },
    { label: settingsText(language, "积极", "Active"), value: "active" as const },
  ];
  const reviewReminderItems = [
    { label: settingsText(language, "到期时", "Due"), value: "due" as const },
    { label: settingsText(language, "提前", "Ahead"), value: "ahead" as const },
    { label: settingsText(language, "合并", "Digest"), value: "digest" as const },
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
    // thinkingConfig is durable intent: on wires that cannot emit thinking
    // markers a mode change leaves requestDefaults untouched, so it must count
    // as dirty on its own or the save action stays unreachable. Compare the
    // normalized forms so key order and protocol-inapplicable fields (budget on
    // OpenAI, effort on Anthropic) never register as phantom changes.
    JSON.stringify(
      normalizeProviderThinkingConfig(providerDraft.thinkingConfig, draftProtocol) ?? null,
    ) !==
      JSON.stringify(
        normalizeProviderThinkingConfig(provider.thinkingConfig, savedProtocol) ?? null,
      ) ||
    providerDraft.apiKey.trim().length > 0;
  const normalizedDraftBaseUrl = normalizeProviderBaseUrlDraft(providerDraft.baseUrl, draftProtocol);
  const normalizedSavedBaseUrl = normalizeProviderBaseUrlDraft(provider.baseUrl, savedProtocol);
  const providerDraftHasApiKey = providerDraft.apiKey.trim().length > 0;
  // Saving no longer requires a model: the host auto-adopts a live model from
  // the fetched list when the draft names none (CC-Switch-style one-shot).
  const providerDraftFieldsReady = Boolean(providerDraft.baseUrl.trim());
  // The draft connection test still probes a concrete model.
  const providerDraftTestReady = Boolean(
    providerDraft.baseUrl.trim() && providerDraft.model.trim(),
  );
  const providerDraftCanReuseSavedApiKey =
    providerSaved &&
    provider.apiKeyConfigured &&
    draftProtocol === savedProtocol &&
    normalizedDraftBaseUrl === normalizedSavedBaseUrl;
  const providerApiKeyDraftStatus = providerDraftHasApiKey
    ? {
        value: settingsText(language, "新 API key", "New API key"),
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
    providerDraftTestReady && (providerDraftHasApiKey || providerDraftCanReuseSavedApiKey);
  const attachedContextSummaryText = shortenSummary(attachedContextSummary, 54);
  const providerSummaryText = shortenSummary(providerSummary, 62);
  const advancedSummaryText = shortenSummary(advancedSummary, 82);
  const runtimeSummaryText = shortenSummary(runtimeSummary, 72);
  const coachStateSummaryText = localizedCoachStateText ? shortenSummary(localizedCoachStateText, 88) : undefined;
  const providerRequirementNote = providerNeedsApiKey
    ? settingsText(language, "连接已保存，还需要 API key。", "Connection saved; API key missing.")
    : !providerSaved && savedProviderProfilesAvailable
      ? settingsText(language, "这个工作区还没有启用连接。下方有可以直接使用的连接配置。", "There is no active provider applied yet. Reusable profiles are still available below.")
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
  const draftThinkingLiveEvidence = lastTest?.capabilityEvidence?.some((entry) =>
    entry.name.trim().toLowerCase() === "thinking" &&
    entry.state === "verified" &&
    entry.observed === true,
  ) === true;
  const draftThinkingModelCapabilities =
    canUseSavedModelMetadata && providerDraft.model.trim()
      ? provider.modelCapabilities?.[providerDraft.model.trim()]
      : undefined;
  const draftThinkingContext = {
    protocol: draftProtocol,
    model: providerDraft.model,
    providerName: providerDraft.name,
    baseUrl: providerDraft.baseUrl,
    liveEvidence: draftThinkingLiveEvidence,
    modelCapabilities: draftThinkingModelCapabilities,
    profileCapabilities: provider.capabilities,
  };
  // The durable draft intent is the source of truth for the displayed mode:
  // wire markers only exist when capability evidence allowed an emit, so an
  // explicit choice must still render (and stay editable) before that.
  const draftThinkingConfig = normalizeProviderThinkingConfig(
    providerDraft.thinkingConfig,
    draftProtocol,
  );
  const describedThinking = describeProviderThinking(
    draftThinkingContext,
    draftRequestDefaults,
  );
  const thinkingSupported =
    draftThinkingLiveEvidence ||
    draftThinkingModelCapabilities?.thinking === true ||
    provider.capabilities?.thinking === true;
  const thinkingDescriptor = describedThinking
    ? { ...describedThinking, config: draftThinkingConfig ?? describedThinking.config }
    : (thinkingSupported || draftThinkingConfig) && thinkingProtocolSupportsWire(draftProtocol)
      ? synthesizeProviderThinkingDescriptor(draftThinkingContext, draftThinkingConfig ?? { mode: "auto" })
      : undefined;
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
  const modelPickerHasOverflow = selectableModelOptions.length > MODEL_PICKER_DEFENSIVE_OPTION_LIMIT;
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
      // Search filters but never truncates the matching data.
      return matchingModelOptions;
    }

    return selectableModelOptions.slice(0, MODEL_PICKER_DEFENSIVE_OPTION_LIMIT);
  }, [
    matchingModelOptions,
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
  // Nothing discovered yet: a plain always-visible model input beats the
  // disclosure picker (first-run users cannot pick from an empty list).
  const modelCatalogIsEmpty =
    availableModels.length === 0 &&
    draftCatalogModels.length === 0 &&
    liveCatalogModels.length === 0;
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
  const customSkills = coachDefaults.customSkills ?? [];
  const providerProfileCount = countSavedProviderProfiles(provider);

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
  const localizedProviderDirectoryLabel = settingsPhrase(language, "providerDirectoryLabel");
  const localizedRefreshProfilesLabel = providerDetailLabel(language, "refreshProfiles");
  const localizedRefreshProfilesDetail = providerDetailLabel(language, "reloadProfiles");
  const localizedSaveProfileLabel = providerDetailLabel(language, "saveProfile");
  const localizedSaveProfileDetail = providerDetailLabel(language, "saveProfileDetail");
  const localizedPerModelLimitsLabel = providerDetailLabel(language, "perModelLimits");
  const localizedPerModelLimitsDetail =
    settingsText(language, "Trainer \u4F1A\u6309 model \u8BB0\u4F4F Context window \u548C Max output\u3002\u5207\u5230\u67D0\u4E2A model \u65F6\uFF0C\u4F1A\u81EA\u52A8\u5E26\u56DE\u5B83\u81EA\u5DF1\u7684 limits\u3002", "Trainer keeps Context window and Max output per model and restores them when you switch models.");
  const localizedUseModelLabel =
    settingsText(language, "\u7528\u8FD9\u4E2A model", "Use model");
  const localizedCurrentModelLabel =
    settingsText(language, "\u5F53\u524D", "Current");
  const localizedModelLimitEmpty =
    settingsText(language, "\u5148\u62C9\u53D6\u6A21\u578B\u5217\u8868\uFF0C\u6216\u8005\u76F4\u63A5\u8F93\u5165\u4E00\u4E2A model\u3002", "Fetch models first, or type a model name directly.");
  const localizedCatalogPanelLabel = providerDetailLabel(language, "modelCatalog");
  const localizedCatalogPanelDetail =
    settingsText(language, "Trainer \u4F1A\u6309\u8FD9\u4E9B\u5DF2\u4FDD\u5B58\u7684 model \u7EC6\u8282\u6765\u505A\u81EA\u52A8\u5207\u6362\u3001profile \u5207\u6362\u548C live refresh\u3002", "Trainer uses these saved model details when it switches models, swaps profiles, and refreshes live catalogs.");
  const localizedCatalogAliasesLabel =
    settingsText(language, "Model aliases", "Model aliases");
  const localizedCatalogTaskBindingsLabel =
    settingsText(language, "Task bindings", "Task bindings");
  const localizedCatalogAllowedModelsLabel =
    settingsText(language, "Allowed models", "Allowed models");
  const localizedCatalogDeniedModelsLabel =
    settingsText(language, "Blocked models", "Blocked models");
  const localizedCatalogEmbeddingModelLabel =
    settingsText(language, "Embedding model", "Embedding model");
  const localizedCatalogRequestDefaultsLabel =
    settingsText(language, "Request defaults", "Request defaults");
  const localizedCatalogSourceLabel =
    settingsText(language, "Catalog source", "Catalog source");
  const localizedCatalogCacheTtlLabel =
    settingsText(language, "Cache TTL", "Cache TTL");
  const localizedAdvancedRoutingLabel =
    settingsText(language, "\u8DEF\u7531\u89C4\u5219", "Routing rules");
  const localizedAdvancedRoutingDetail =
    settingsText(language, "这里放会影响 provider profile 行为的高级字段。默认收起，不抢首屏。", "These fields shape provider profile behavior. They stay collapsed by default so Settings keeps its first screen calm.");
  const localizedCredentialModeLabel =
    settingsText(language, "Credential mode", "Credential mode");
  const localizedCredentialModeUiProxy =
    settingsText(language, "UI proxy", "UI proxy");
  const localizedCredentialModeWorkspaceSecret =
    settingsText(language, "Workspace secret", "Workspace secret");
  const localizedAllowedModelsInputDetail =
    settingsText(language, "用逗号或换行分隔。留空表示不限制。", "Separate models with commas or new lines. Leave blank to allow any model.");
  const localizedDeniedModelsInputDetail =
    settingsText(language, "这些 model 会被 profile 直接挡住。", "These models stay blocked for this profile.");
  const localizedEmbeddingModelPlaceholder =
    settingsText(language, "可选，例如 text-embedding-3-small", "Optional, for example text-embedding-3-small");
  const localizedCacheTtlDetail =
    settingsText(language, "单位是秒。", "Measured in seconds.");
  const localizedManualModelLabel =
    settingsText(language, "手动加入 model", "Add model manually");
  const localizedManualModelPlaceholder =
    settingsText(language, "例如 kimi-k3", "For example kimi-k3");
  const localizedManualModelButton =
    settingsText(language, "加入当前 catalog", "Add to current catalog");
  const localizedManualModelHint =
    settingsText(language, "即使 provider 还没列出它，也可以先把 model 放进当前 catalog。至少填一个 limit 后，它就会被记住。", "You can stage a model here even before the provider lists it. Save at least one limit to keep it in the catalog.");
  const localizedRequestDefaultsInputDetail =
    settingsText(language, "\u7528 JSON object \u7ec6\u5316 provider \u8bf7\u6c42\u3002Trainer \u4f1a\u5728\u53d1\u9001\u65f6\u5408\u5e76\u8fd9\u4e9b\u9ed8\u8ba4\u503c\u3002", "Use a JSON object to refine provider requests. Trainer merges these defaults into outgoing requests.");
  const localizedRequestDefaultsInputHint =
    settingsText(language, "\u4fdd\u6301\u4e3a\u4e00\u4e2a JSON object\u3002\u9002\u5408\u8bbe\u7f6e reasoning\u3001temperature \u6216\u5176\u4ed6 provider \u5b57\u6bb5\u3002", "Keep this as a JSON object. Use it for reasoning, temperature, or provider-specific request fields.");
  const localizedRequestDefaultsInvalidJson =
    settingsText(language, "Request defaults \u5fc5\u987b\u662f\u53ef\u89e3\u6790\u7684 JSON\u3002", "Request defaults must be valid JSON.");
  const localizedRequestDefaultsInvalidShape =
    settingsText(language, "Request defaults \u5fc5\u987b\u662f JSON object\uff0c\u4e0d\u80fd\u662f array \u6216 string\u3002", "Request defaults must stay a JSON object, not an array or string.");
  const modelCardCopy = providerModelCardCopy(language);
  const localizedModelOriginLive = modelCardCopy.live;
  const localizedModelOriginManual = modelCardCopy.manual;
  const localizedClearModelLimitsLabel =
    settingsText(language, "清除 limits", "Clear limits");
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
      draftThinkingContext,
      draftRequestDefaults,
      config,
    );
    onProviderDraftChange({ requestDefaults: next, thinkingConfig: config });
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
          onChange={(value) => updateThinkingConfig({
            ...thinkingDescriptor.config,
            mode: value as ProviderThinkingConfig["mode"],
            // "On" must carry a concrete effort or nothing is emitted and the
            // choice falls back to "auto".
            ...(value === "enabled" &&
            thinkingDescriptor.kind === "reasoning_effort" &&
            !thinkingDescriptor.config.reasoningEffort
              ? { reasoningEffort: "medium" as const }
              : {}),
          })}
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
    // Thinking intent only clears when the edit removes markers that were
    // actually there — a marker-free draft (nothing emitted yet) must keep its
    // stored choice instead of snapping back to "auto" on unrelated edits.
    const previousHadMarkers =
      normalizeProviderThinkingConfig(draftRequestDefaults, draftProtocol) !== undefined;
    if (!value.trim()) {
      setRequestDefaultsError(undefined);
      onProviderDraftChange({
        requestDefaults: {},
        ...(previousHadMarkers ? { thinkingConfig: { mode: "auto" } } : {}),
      });
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
      // Raw edits are the intent: thinking fields are re-derived from the
      // edited defaults; deleting markers that existed means "auto".
      const editedThinking = normalizeProviderThinkingConfig(normalized, draftProtocol);
      onProviderDraftChange({
        requestDefaults: normalized,
        ...(editedThinking
          ? { thinkingConfig: editedThinking }
          : previousHadMarkers
            ? { thinkingConfig: { mode: "auto" } }
            : {}),
      });
    } catch {
      setRequestDefaultsError(localizedRequestDefaultsInvalidJson);
    }
  };
  // 中转站/网关的"复制连接信息"是一整段 JSON。粘贴进任一输入框时识别并
  // 自动拆填到对应字段,而不是把整段 JSON 塞进一个框。
  const applyProviderSmartPaste = (
    value: string,
    field: "baseUrl" | "apiKey",
  ): "blob" | "moved-url" | "moved-key" | null => {
    const text = value.trim();
    if (!text || text === providerDraft[field].trim()) {
      return null;
    }
    const paste = parseProviderConnectionPaste(text);
    if (paste) {
      onProviderDraftChange({
        baseUrl: paste.baseUrl,
        apiKey: paste.apiKey,
        ...(providerDraft.name.trim() || providerDraft.baseUrl.trim()
          ? {}
          : { name: providerConnectionLabelFromPaste(paste) }),
      });
      return "blob";
    }
    if (field === "apiKey" && looksLikeProviderServiceAddress(text)) {
      onProviderDraftChange({ baseUrl: text });
      return "moved-url";
    }
    if (field === "baseUrl" && looksLikeProviderApiKeyToken(text)) {
      onProviderDraftChange({ apiKey: text });
      return "moved-key";
    }
    return null;
  };
  const providerPasteHintCopy = (outcome: ReturnType<typeof applyProviderSmartPaste>): string => {
    if (outcome === "blob") {
      return settingsText(language, "已识别连接信息:服务地址和密钥已自动填入。接下来点「获取模型」选一个模型,然后保存即可。", "Recognized the connection info: base URL and API key are filled in. Next, fetch models, pick one, and save.");
    }
    if (outcome === "moved-url") {
      return settingsText(language, "这里粘贴的是服务地址,已帮你移到「服务根地址」。密钥请粘到「API 密钥」。", "That looks like a service address — moved it to Base URL. Paste the key into API key.");
    }
    if (outcome === "moved-key") {
      return settingsText(language, "这里粘贴的是密钥,已帮你移到「API 密钥」。服务地址请粘到「服务根地址」。", "That looks like an API key — moved it to API key. Paste the address into Base URL.");
    }
    return "";
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
    !providerSaveBusy &&
    providerDraftFieldsReady &&
      !currentDraftModelBlockedByPolicy &&
      !providerDraftEditorBlocked &&
      !requestDefaultsTextHasDrift &&
      (providerHasDraftChanges || !providerSaved),
  );
  // r3 settings dedup: the model name already shows in the chip and the
  // picker; the save button states the connection-level action instead of
  // repeating the model string a third and fourth time on one screen.
  const saveProviderConnectionLabel = modelPickerCopy.saveAndUseConnection;
  const saveProviderConnectionTitle = canSaveProviderConnection
    ? modelPickerCopy.saveAndUseConnection
    : providerDraftEditorBlocked || requestDefaultsTextHasDrift
      ? localizedRequestDefaultsInvalidJson
    : currentDraftModelPolicyMessage
      ? currentDraftModelPolicyMessage
    : !providerDraftFieldsReady
      ? settingsText(language, "\u5148\u586b\u5199\u670d\u52a1\u6839\u5730\u5740\u548c\u6a21\u578b\uff0c\u518d\u4fdd\u5b58\u8fde\u63a5\u3002", "Add the service root and model before saving the connection.")
      : providerSaved
        ? settingsText(language, "\u5F53\u524D\u8FDE\u63A5\u5DF2\u4FDD\u5B58\u3002", "This connection is already saved.")
        : copy.setupAction;
  const shouldSurfaceRecentTestFailure =
    (providerTestTransportFailed || Boolean(lastTestFailure)) &&
    providerSaved &&
    !providerHasDraftChanges;
  const calmIntro =
    copy.intro ||
    (settingsText(language, "连接与默认项。", "Connection and defaults."));
  const localizedCalmIntro =
    copy.intro && copy.intro !== "Only the most common coach settings here."
      ? copy.intro
      : settingsSupportPhrase(language, "commonIntro");
  const providerPrimaryAction = providerCoachReady
    ? settingsText(language, "已可发送。", "Ready to send.")
    : providerNeedsApiKey
      ? settingsText(language, "缺少 API key。", "Missing API key.")
      : providerSaved
        ? settingsText(language, "连接已保存，等待测试通过。", "Connection saved; test still needs to pass.")
        : savedProviderProfilesAvailable
          ? settingsText(language, "先应用一个保存的连接。", "Apply a saved profile first.")
          : settingsText(language, "填写 provider、protocol、模型和 API key。", "Fill provider, protocol, base URL, model, and API key.");
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
    ? settingsText(language, "已就绪", "Ready")
    : providerNeedsApiKey
      ? settingsText(language, "缺少密钥", "Missing key")
      : providerSaved
        ? settingsText(language, "被阻塞", "Blocked")
        : settingsText(language, "待配置", "Setup");
  const coachCapabilityTone = providerCoachReady ? "connected" : providerNeedsApiKey ? "warn" : providerSaved ? "warn" : "offline";
  const imageCapabilityLabel = imageInputState.supported
    ? settingsText(language, "已就绪", "Ready")
    : imageInputState.status === "setup_required"
      ? settingsText(language, "待配置", "Setup")
      : settingsText(language, "未开启", "Off");
  const imageCapabilityTone = imageInputState.supported
    ? "connected"
    : imageInputState.status === "setup_required"
      ? "pending"
      : "warn";
  const imageCapabilityDetail =
    imageInputState.detail ?? imageInputState.reason ?? (settingsText(language, "未验证图片输入。", "Image input not verified."));
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
    ? settingsText(language, "草稿未生效", "Draft not applied")
    : providerCoachReady
      ? runtimeStatusLabel
      : providerStatusLabel;
  const availabilityHeadline = providerHasDraftChanges && currentDraftModelPolicyMessage
    ? settingsPhrase(language, "chooseModel")
    : providerHasDraftChanges
      ? settingsText(language, "连接草稿未保存", "Connection draft not saved")
    : providerCoachReady
      ? settingsText(language, "模型可用", "Model ready")
      : providerNeedsApiKey
        ? settingsText(language, "缺少 API key", "API key required")
        : providerSaved
          ? settingsText(language, "连接待验证", "Connection needs test")
          : settingsText(language, "设置模型连接", "Set up model access");
  const availabilityDetail = providerHasDraftChanges && currentDraftModelPolicyMessage
    ? currentDraftModelPolicyMessage
    : providerHasDraftChanges
      ? providerDraftReadyForTest
        ? settingsText(language, "当前草稿已经可以测试。保存后会成为当前连接。", "This draft can be tested now. Save when you want to apply it.")
        : settingsText(language, "保存后测试。", "Save before testing.")
      : providerCoachReady
      ? settingsText(language, "对话、计划、训练使用此连接。", "Chat, plan, and training use this connection.")
      : providerRequirementNote ?? providerPrimaryAction;
  const availabilityPrimaryLabel = providerHasDraftChanges
    ? settingsText(language, "保存草稿", "Save draft")
    : providerCoachReady
      ? settingsText(language, "重新测试", "Test again")
      : providerSaved && providerNeedsApiKey
        ? settingsText(language, "补上 API key", "Add API key")
        : copy.setupAction;
  const availabilityPrimaryDetail = providerCoachReady && !providerHasDraftChanges
    ? settingsText(language, "测试当前连接", "Test current connection")
    : settingsText(language, "保存后生效", "Save to apply");
  const availabilityPrimaryIcon = providerCoachReady && !providerHasDraftChanges
    ? <AlertTriangleIcon size={14} />
    : <DoneIcon size={14} />;
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
    shouldSurfaceRecentTestFailure || coachSendState.blocked
      ? providerFailureState.statusLabel
      : providerNeedsRetest
        ? settingsStatusPhrase(language, "needsAttention")
        : coachCapabilityLabel;
  const resolvedCoachCapabilityTone =
    shouldSurfaceRecentTestFailure || coachSendState.blocked
      ? "warn"
      : providerNeedsRetest
        ? "warn"
        : coachCapabilityTone;
  const resolvedCoachCapabilityDetail =
    shouldSurfaceRecentTestFailure || coachSendState.blocked
      ? availabilityFailureHint ?? providerCoachBlockReason ?? providerPrimaryAction
      : providerNeedsRetest
        ? settingsStatusPhrase(language, "connectionSavedNeedsTest")
        : providerCoachReady
          ? settingsText(language, "\u53EF\u53D1\u9001", "Send enabled")
          : providerCoachBlockReason ?? providerPrimaryAction;
  const availabilityMode: ProviderSendStateStatus | "draft" | "recent_failure" | "needs_test" | "warming" = providerHasDraftChanges
    ? "draft"
    : providerTestPending
      ? "warming"
      : shouldSurfaceRecentTestFailure
        ? "recent_failure"
        : providerNeedsRetest
          ? "needs_test"
          : coachSendState.status;
  const shouldRoutePrimaryToSavedProfiles =
    !providerHasDraftChanges && !providerSaved && savedProviderProfilesAvailable;
  const shouldOfferRecommendedProviderTemplate =
    Boolean(onUseProviderTemplateLabel) &&
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
  const shouldWaitForProviderTest = providerTestPending;
  const shouldRepairProviderCredentials =
    providerCredentialsRejected && !providerHasDraftChanges && !providerTestPassed;
  const workspaceRootMissing =
    !trainerWorkspace?.rootPath?.trim() || trainerWorkspace?.status === "root-missing";

  // Explicit provider setup state machine (replaces the nested availability
  // ternaries). `providerConnectionSetup` ignores the workspace gates so the
  // connection-specific copy survives under a root/trust headline.
  const providerConnectionSetup = deriveProviderSetupState({
    workspaceRootMissing: false,
    workspaceTrusted: true,
    availabilityMode,
    draftNeedsModelChoice,
    draftModelDiscoveryPossible: canFindDraftModels,
    draftHasDiscoveredModels: hasDiscoveredDraftModels,
    draftModelBlockedByPolicy: shouldRepairDraftModelPolicy,
    draftNeedsApiKey: shouldFocusDraftApiKey,
    draftReadyForTest: providerDraftReadyForTest,
    draftTestPending: providerTestPending,
    savedNeedsKey: providerNeedsApiKey,
    savedCredentialsRejected: providerCredentialsRejected,
    savedNeedsTest: providerNeedsRetest,
  });
  const providerSetupStateInfo = deriveProviderSetupState({
    workspaceRootMissing,
    // Trust keeps its dedicated always-visible row below (workspace trust
    // sentence), so the availability verdict stays on the connection state.
    workspaceTrusted: true,
    availabilityMode,
    draftNeedsModelChoice,
    draftModelDiscoveryPossible: canFindDraftModels,
    draftHasDiscoveredModels: hasDiscoveredDraftModels,
    draftModelBlockedByPolicy: shouldRepairDraftModelPolicy,
    draftNeedsApiKey: shouldFocusDraftApiKey,
    draftReadyForTest: providerDraftReadyForTest,
    draftTestPending: providerTestPending,
    savedNeedsKey: providerNeedsApiKey,
    savedCredentialsRejected: providerCredentialsRejected,
    savedNeedsTest: providerNeedsRetest,
  });
  const providerSetupReason = providerSetupStateInfo.reason;
  const providerConnectionReason = providerConnectionSetup.reason;
  const PROVIDER_SETUP_STRIP_TONE: Record<ProviderSetupReason, "connected" | "pending" | "warn" | "offline"> = {
    workspace_root_missing: "warn",
    workspace_untrusted: "warn",
    draft_model_search: "pending",
    draft_model_pick: "pending",
    draft_model_policy: "warn",
    draft_needs_key: "pending",
    draft_incomplete: "pending",
    draft_await_test: "pending",
    draft_ready: "pending",
    saved_needs_key: "warn",
    credentials_rejected: "warn",
    saved_needs_test: "warn",
    provider_failure: "warn",
    checking: "pending",
    refreshing: "pending",
    fresh_setup: "offline",
    ready: "connected",
  };
  const resolvedAvailabilityTone: "connected" | "pending" | "warn" | "offline" =
    backendStarting ? "pending" : backendUnavailable ? "offline" : PROVIDER_SETUP_STRIP_TONE[providerSetupReason];
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
    shouldSurfaceRecentTestFailure || coachSendState.blocked
      ? providerFailureState.statusLabel
      : providerNeedsRetest
        ? settingsStatusPhrase(language, "needsAttention")
        : localizedCoachCapabilityLabel;
  const localizedResolvedCoachCapabilityDetail =
    shouldSurfaceRecentTestFailure || coachSendState.blocked
      ? availabilityFailureHint ?? providerCoachBlockReason ?? providerPrimaryAction
      : providerNeedsRetest
        ? settingsStatusPhrase(language, "connectionSavedNeedsTest")
      : providerCoachReady
        ? settingsStatusPhrase(language, "sendEnabled")
        : providerCoachBlockReason ?? providerPrimaryAction;
  const PROVIDER_SETUP_STATUS_COPY: Record<ProviderSetupReason, string> = {
    workspace_root_missing: settingsText(language, "待选目录", "No folder yet"),
    workspace_untrusted: settingsText(language, "待信任", "Trust needed"),
    draft_model_search: settingsStatusPhrase(language, "draftNotApplied"),
    draft_model_pick: settingsStatusPhrase(language, "draftNotApplied"),
    draft_model_policy: settingsStatusPhrase(language, "draftNotApplied"),
    draft_needs_key: settingsStatusPhrase(language, "draftNotApplied"),
    draft_incomplete: settingsStatusPhrase(language, "draftNotApplied"),
    draft_await_test: settingsStatusPhrase(language, "draftNotApplied"),
    draft_ready: settingsStatusPhrase(language, "draftNotApplied"),
    saved_needs_key: settingsPhrase(language, "addApiKey"),
    credentials_rejected: providerFailureState.statusLabel,
    saved_needs_test: settingsStatusPhrase(language, "needsAttention"),
    provider_failure: providerFailureState.statusLabel,
    checking: settingsStatusPhrase(language, "checking"),
    refreshing: settingsStatusPhrase(language, "refreshing"),
    fresh_setup: settingsStatusPhrase(language, "setup"),
    ready: settingsStatusPhrase(language, "ready"),
  };
  const PROVIDER_SETUP_HEADLINE_COPY: Record<ProviderSetupReason, string> = {
    workspace_root_missing: settingsText(language, "先选择工作区根目录", "Choose a workspace root first"),
    workspace_untrusted: settingsText(language, "先信任此窗口", "Trust this window first"),
    draft_model_search: settingsStatusPhrase(language, "connectionDraftNotSaved"),
    draft_model_pick: settingsStatusPhrase(language, "connectionDraftNotSaved"),
    draft_model_policy: settingsPhrase(language, "chooseModel"),
    draft_needs_key: settingsStatusPhrase(language, "connectionDraftNotSaved"),
    draft_incomplete: settingsStatusPhrase(language, "connectionDraftNotSaved"),
    draft_await_test: settingsStatusPhrase(language, "connectionDraftNotSaved"),
    draft_ready: settingsStatusPhrase(language, "connectionDraftNotSaved"),
    saved_needs_key: settingsStatusPhrase(language, "apiKeyRequired"),
    credentials_rejected: providerFailureState.headline,
    saved_needs_test: settingsStatusPhrase(language, "connectionNeedsTest"),
    provider_failure: providerFailureState.headline,
    checking: settingsStatusPhrase(language, "checking"),
    refreshing: settingsStatusPhrase(language, "refreshing"),
    fresh_setup: settingsStatusPhrase(language, "setupModelAccess"),
    ready: settingsStatusPhrase(language, "modelReady"),
  };
  const localizedResolvedAvailabilityStatusLabel =
    backendRecovery
      ? providerRecoveryLocale(language).status[backendStarting ? "starting" : "offline"]
      : PROVIDER_SETUP_STATUS_COPY[providerSetupReason];
  const localizedResolvedAvailabilityHeadline =
    PROVIDER_SETUP_HEADLINE_COPY[providerSetupReason];
  const readyAvailabilityScopeDetail = `${copy.currentWorkspace} \u00b7 ${settingsStatusPhrase(
    language,
    "chatPlanTrainingUseThisConnection",
  )}`;
  const PROVIDER_CONNECTION_DETAIL: Record<ProviderSetupReason, string> = {
    workspace_root_missing: "",
    workspace_untrusted: "",
    draft_model_search: providerDraftReadyForTest
      ? settingsText(language, "当前草稿已经可以测试。保存后会成为当前连接。", "This draft can be tested now. Save when you want to apply it.")
      : settingsStatusPhrase(language, "saveBeforeTesting"),
    draft_model_pick: providerDraftReadyForTest
      ? settingsText(language, "当前草稿已经可以测试。保存后会成为当前连接。", "This draft can be tested now. Save when you want to apply it.")
      : settingsStatusPhrase(language, "saveBeforeTesting"),
    draft_model_policy: currentDraftModelPolicyMessage ?? modelDiscoveryBlockedReason,
    draft_needs_key: providerDraftReadyForTest
      ? settingsText(language, "当前草稿已经可以测试。保存后会成为当前连接。", "This draft can be tested now. Save when you want to apply it.")
      : settingsStatusPhrase(language, "saveBeforeTesting"),
    draft_incomplete: providerDraftReadyForTest
      ? settingsText(language, "当前草稿已经可以测试。保存后会成为当前连接。", "This draft can be tested now. Save when you want to apply it.")
      : settingsStatusPhrase(language, "saveBeforeTesting"),
    draft_await_test: providerDraftReadyForTest
      ? settingsText(language, "当前草稿已经可以测试。保存后会成为当前连接。", "This draft can be tested now. Save when you want to apply it.")
      : settingsStatusPhrase(language, "saveBeforeTesting"),
    draft_ready: providerDraftReadyForTest
      ? settingsText(language, "当前草稿已经可以测试。保存后会成为当前连接。", "This draft can be tested now. Save when you want to apply it.")
      : settingsStatusPhrase(language, "saveBeforeTesting"),
    saved_needs_key: providerRequirementNote ?? settingsStatusPhrase(language, "connectionSavedApiKeyMissing"),
    credentials_rejected: availabilityFailureHint ?? providerPrimaryAction,
    saved_needs_test: settingsStatusPhrase(language, "connectionSavedNeedsTest"),
    provider_failure:
      availabilityFailureHint
      ?? providerPrimaryAction,
    checking: settingsStatusPhrase(language, "checking"),
    refreshing: settingsStatusPhrase(language, "refreshing"),
    fresh_setup: providerRequirementNote ?? settingsStatusPhrase(language, "fillProviderFields"),
    ready: readyAvailabilityScopeDetail,
  };
  const PROVIDER_SETUP_DETAIL_COPY: Record<ProviderSetupReason, string> = {
    ...PROVIDER_CONNECTION_DETAIL,
    workspace_root_missing: PROVIDER_CONNECTION_DETAIL[providerConnectionReason],
    workspace_untrusted: PROVIDER_CONNECTION_DETAIL[providerConnectionReason],
  };
  const localizedResolvedAvailabilityDetail = PROVIDER_SETUP_DETAIL_COPY[providerSetupReason];
  useEffect(() => {
    if (!providerProfilesFocusRequested) {
      return;
    }

    const frameId = window.requestAnimationFrame(() => {
      const directory = providerDirectoryRef.current;
      if (!directory) {
        return;
      }

      directory.scrollIntoView({ block: "nearest" });
      const nextButton = directory.querySelector<HTMLButtonElement>(
        ".settings-provider-profile:not(:disabled)",
      );
      nextButton?.focus();
      setProviderProfilesFocusRequested(false);
    });

    return () => window.cancelAnimationFrame(frameId);
  }, [providerProfiles.length, providerProfilesFocusRequested]);

  useEffect(() => {
    if (!providerTemplatesFocusRequested) {
      return;
    }

    const frameId = window.requestAnimationFrame(() => {
      const templates = providerTemplatesRef.current;
      if (!templates) {
        return;
      }

      templates.scrollIntoView({ block: "nearest" });
      templates
        .querySelector<HTMLButtonElement>(".settings-provider-directory__item")
        ?.focus();
      setProviderTemplatesFocusRequested(false);
    });

    return () => window.cancelAnimationFrame(frameId);
  }, [providerTemplatesFocusRequested]);

  const openSavedProviderProfiles = () => {
    setProviderProfilesFocusRequested(true);
  };

  useEffect(() => {
    if (!providerApiKeyFocusRequested) {
      return;
    }

    const frameId = window.requestAnimationFrame(() => {
      const apiKeyInput = apiKeyInputRef.current;
      apiKeyInput?.scrollIntoView({ block: "center" });
      apiKeyInput?.focus({ preventScroll: true });
      setProviderApiKeyFocusRequested(false);
    });

    return () => window.cancelAnimationFrame(frameId);
  }, [providerApiKeyFocusRequested]);

  const openProviderDetails = () => {
    setAdvancedReturnView(connectionView === "edit" ? "edit" : "auto");
    setConnectionView("advanced");
  };
  const openProviderApiKey = () => {
    setConnectionView("edit");
    setProviderApiKeyFocusRequested(true);
  };
  // r1-g2-4: one connection identity summary per screen. When the saved-profile
  // selector renders, its active row already carries the identity (name · model
  // · state) and the "连接详情" row expands to the full truth — so the big
  // summary card stands down and the selector stays the single summary.
  const providerIdentityListVisible =
    providerProfiles.length > 0 ||
    canSaveProviderProfile ||
    (providerSaved && (onRefreshProviderProfiles || onUseProviderTemplateLabel));
  const showConnectionSummary =
    providerSaved && !providerHasDraftChanges && connectionView === "auto" && !providerIdentityListVisible;
  const showProviderTemplates = Boolean(onUseProviderTemplateLabel) && connectionView === "add";
  // Empty state stays a single-purpose screen: the paste card plus one entry
  // into the template directory. The full form only appears once the user
  // drills into edit (directly or via a template).
  const showConnectionForm = providerSaved
    ? providerHasDraftChanges || connectionView === "edit"
    : connectionView === "edit";
  const showQuickSetup = !providerSaved && connectionView === "auto";
  const showAvailabilityStrip =
    providerSetupReason !== "workspace_untrusted" &&
    (Boolean(backendRecovery) || (showConnectionForm && connectionView !== "advanced") ||
      (showConnectionSummary && resolvedAvailabilityTone !== "connected"));
  const connectionHost = (provider.baseUrl || providerDraft.baseUrl || "")
    .replace(/^https?:\/\//i, "")
    .split("/")[0];
  const focusProviderTemplatePicker = () => {
    setConnectionView("add");
    setProviderTemplatesFocusRequested(true);
  };
  const focusDraftModelPicker = () => {
    setConnectionView("edit");
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
  const displayAvailabilityHeadline = backendRecovery ? backendRecovery.title : shouldOfferRecommendedProviderTemplate
    ? settingsPhrase(language, "chooseProviderTemplate")
    : shouldRoutePrimaryToSavedProfiles
      ? settingsText(language, "先应用一个已保存的 profile", "Apply a saved profile first")
      : localizedResolvedAvailabilityHeadline;
  const workspaceRootReminder = settingsText(language, "先在上方选择工作区根目录，否则对话和训练无法使用。", "Choose a workspace root above first — Coach and Training cannot work without it.");
  const displayAvailabilityDetail = (
    workspaceRootMissing
      ? `${workspaceRootReminder} `
      : ""
  ) + (backendRecovery
    ? backendStarting ? backendRecovery.detail : sidecarRestartCopy(language).detail
    : shouldOfferRecommendedProviderTemplate
    ? settingsPhrase(language, "chooseProviderTemplateDetail")
    : shouldRoutePrimaryToSavedProfiles
      ? settingsText(language, "当前工作区还没有启用中的 provider，但下面已经有可复用的 profiles。", "This workspace has no active provider yet, but reusable profiles are already available below.")
      : localizedResolvedAvailabilityDetail);
  const showAvailabilityPrimaryAction =
    Boolean(backendRecovery) || workspaceRootMissing || availabilityMode !== "ready" || Boolean(onTestProvider);
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
      : shouldWaitForProviderTest
        ? settingsStatusPhrase(language, "checking")
        : shouldRepairProviderCredentials
          ? settingsPhrase(language, "addApiKey")
        : providerHasDraftChanges && canSaveProviderConnection
          ? saveProviderConnectionLabel
          : providerHasDraftChanges
          ? settingsPhrase(language, "testDraftConnection")
          : providerNeedsRetest
                ? copy.test
                : shouldRoutePrimaryToSavedProfiles
                  ? settingsText(language, "\u6253\u5F00 profiles", "Open profiles")
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
      : shouldWaitForProviderTest
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
              ? settingsPhrase(language, "testCurrentConnection")
              : shouldRoutePrimaryToSavedProfiles
                ? settingsText(language, "\u76F4\u63A5\u6253\u5F00\u4E0B\u65B9\u7684 profiles\u3002", "Open the saved profiles below.")
                : shouldOpenProviderDetails
                  ? copy.modelHint
                  : settingsPhrase(language, "saveToApply");
  const resolvedAvailabilityPrimaryIcon =
    canFindDraftModels
      ? <ReloadIcon size={14} />
      : hasDiscoveredDraftModels
        ? <DoneIcon size={14} />
        : shouldRepairDraftModelPolicy
          ? <SettingsPreferencesIcon size={14} />
        : shouldFocusDraftApiKey
          ? <SettingsPreferencesIcon size={14} />
        : shouldCompleteDraftSetup
        ? <SettingsPreferencesIcon size={14} />
        : shouldWaitForProviderTest
          ? <ReloadIcon size={14} />
          : shouldRepairProviderCredentials
            ? <SettingsPreferencesIcon size={14} />
          : canRetestProvider
              ? <ReloadIcon size={14} />
              : shouldOpenProviderDetails
                ? <SettingsPreferencesIcon size={14} />
                : <DoneIcon size={14} />;
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
        ? () => setConnectionView("edit")
        : shouldWaitForProviderTest
          ? undefined
          : shouldRepairProviderCredentials
            ? openProviderApiKey
          : shouldRoutePrimaryToSavedProfiles
              ? openSavedProviderProfiles
              : providerHasDraftChanges && canSaveProviderConnection
                ? onSaveProvider
              : canRetestProvider
                ? onTestProvider
                : shouldOpenProviderDetails
                  ? () => openProviderDetails()
                  : onSaveProvider;
  const effectiveAvailabilityPrimaryCta: {
    label: string;
    detail: string;
    icon: ReactNode;
    action?: (() => void) | undefined;
  } =
    backendStarting
      ? { label: backendRecovery?.title ?? "", detail: backendRecovery?.detail ?? "", icon: <ReloadIcon size={14} /> }
      : canRestartSidecar
        ? {
            ...sidecarRestartCopy(language),
            icon: <ReloadIcon size={14} />,
            action: onRestartSidecar,
          }
      : shouldOfferRecommendedProviderTemplate
      ? {
          label: settingsPhrase(language, "chooseProviderTemplate"),
          detail: settingsPhrase(language, "chooseProviderTemplateDetail"),
          icon: <SettingsSkillsIcon size={14} />,
          action: focusProviderTemplatePicker,
        }
        : shouldRepairProviderCredentials
              ? {
                  label: settingsPhrase(language, "addApiKey"),
                  detail: settingsPhrase(language, "addApiKeyDetail"),
                  icon: <SettingsPreferencesIcon size={14} />,
                  action: openProviderApiKey,
                }
              : providerSaved && providerNeedsApiKey && !providerHasDraftChanges
                  ? {
                      label: settingsPhrase(language, "addApiKey"),
                      detail: settingsPhrase(language, "addApiKeyDetail"),
                      icon: <DoneIcon size={14} />,
                      action: openProviderApiKey,
                    }
                  : {
                      label: resolvedAvailabilityPrimaryLabel,
                      detail: resolvedAvailabilityPrimaryDetail,
                      icon: resolvedAvailabilityPrimaryIcon,
                      action: resolvedAvailabilityPrimaryAction,
                    };
  const effectiveAvailabilityPrimaryTone =
    availabilityMode === "ready" && !providerHasDraftChanges ? "ghost" : "accent";
  const connectionSummaryCard = showConnectionSummary ? (
    <div className="settings-connection-summary">
      <div className="settings-connection-summary__main">
        <div className="settings-connection-summary__identity">
          <span
            className="settings-connection-summary__dot"
            data-state={resolvedAvailabilityTone}
            aria-hidden="true"
          />
          <strong className="settings-connection-summary__name">
            {provider.profileLabel || provider.name || providerDraft.name || provider.profileId ||
              settingsPhrase(language, "currentConnectionPrefix")}
          </strong>
          <StatusPill tone={resolvedAvailabilityTone}>{lastTestLabel}</StatusPill>
        </div>
        <div className="settings-connection-summary__meta">
          <span className="settings-connection-summary__model" title={provider.model || ""}>
            {provider.model || providerDraft.model || copy.notConfigured}
          </span>
          <span aria-hidden="true">·</span>
          <span>{liveProtocolLabel}</span>
          {connectionHost ? (
            <>
              <span aria-hidden="true">·</span>
              <span className="settings-connection-summary__host" title={provider.baseUrl}>
                {connectionHost}
              </span>
            </>
          ) : null}
        </div>
        {lastTestDetail ? (
          <p className="settings-sheet__note settings-sheet__note--compact">{lastTestDetail}</p>
        ) : null}
      </div>
      <div className="settings-actions settings-actions--compact">
        {showAvailabilityPrimaryAction && !showAvailabilityStrip ? (
          <ActionButton
            fullWidth={false}
            icon={effectiveAvailabilityPrimaryCta.icon}
            label={effectiveAvailabilityPrimaryCta.label}
            detail={effectiveAvailabilityPrimaryCta.detail}
            ariaLabel={effectiveAvailabilityPrimaryCta.label}
            onClick={effectiveAvailabilityPrimaryCta.action}
            disabled={!effectiveAvailabilityPrimaryCta.action}
            title={effectiveAvailabilityPrimaryCta.detail}
          />
        ) : null}
        <ActionButton
          fullWidth={false}
          icon={<SettingsPreferencesIcon size={14} />}
          label={settingsPhrase(language, "editConfiguration")}
          ariaLabel={settingsPhrase(language, "editConfiguration")}
          detail={settingsPhrase(language, "editConfigurationDetail")}
          onClick={() => setConnectionView("edit")}
        />
      </div>
    </div>
  ) : null;
  const appliedProviderFactValue =
    (providerSaved
      ? provider.profileLabel?.trim() || provider.name?.trim()
      : providerHasDraftChanges
        ? providerDraft.name.trim()
        : undefined) ||
    copy.notConfigured;
  const appliedModelFactValue =
    (providerSaved
      ? provider.resolvedModel?.trim() || provider.model?.trim()
      : providerHasDraftChanges
        ? providerDraft.model.trim()
        : undefined) ||
    copy.notConfigured;
  const providerPreviewSummaryText = shortenSummary(
    compactSummaryValue(
      [
        availabilityMode === "ready" ? copy.currentWorkspace : undefined,
        providerHasDraftChanges ? (settingsText(language, "草稿中", "Draft")) : undefined,
        appliedProviderFactValue !== copy.notConfigured ? appliedProviderFactValue : undefined,
        appliedModelFactValue !== copy.notConfigured ? appliedModelFactValue : undefined,
      ].filter(Boolean) as string[],
      providerSummaryText,
    ),
    44,
  );
  // A configured connection always shows its summary card in the detail —
  // returning users must see name/model/state at a glance, not an empty pane
  // between tests.
  const shouldShowProviderConnectionSummary =
    providerSaved || providerHasDraftChanges || (provider.configured && Boolean(provider.baseUrl.trim()));
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
  const coachSettingsSaving = coachDefaultsStatus?.feedback?.tone === "pending";
  const coachSettingsSavedRecently = coachDefaultsStatus?.feedback?.tone === "pass";
  const coachSettingsSaveFailure =
    coachDefaultsStatus?.feedback?.tone === "fail" ? coachDefaultsStatus.feedback : undefined;
  // Save-on-change has no Save button to hang feedback on, so the header
  // carries a live status: saving → saved, or the sanitized failure detail.
  const coachSettingsAutosaveNode = (
    <span
      className={`settings-autosave${
        coachSettingsSaving
          ? " is-saving"
          : coachSettingsSaveFailure
            ? " is-failed"
            : coachSettingsSavedRecently
              ? " is-saved"
              : ""
      }`}
      role="status"
      aria-live="polite"
      data-settings-autosave={
        coachSettingsSaving
          ? "saving"
          : coachSettingsSaveFailure
            ? "failed"
            : coachSettingsSavedRecently
              ? "saved"
              : "idle"
      }
    >
      {coachSettingsSaving
        ? settingsGlobalCopy.settingsAutosaving
        : coachSettingsSaveFailure
          ? `${coachSettingsSaveFailure.title}${
              coachSettingsSaveFailure.detail
                ? ` · ${sanitizeErrorSurfaceText(coachSettingsSaveFailure.detail)}`
                : ""
            }`
          : coachSettingsSavedRecently
            ? settingsGlobalCopy.settingsAutosaved
            : ""}
    </span>
  );
  // An unsaved *empty* draft differs from the empty config only in defaults;
  // only count it as dirty once the user has actually typed something.
  const connectionDirty =
    providerStatus?.saveState === "unsaved" &&
    (providerSaved ||
      Boolean(providerDraft.baseUrl.trim() || providerDraft.apiKey.trim() || providerDraft.model.trim()));
  const settingsNavItems = [
    {
      id: "connection",
      label: settingsGlobalCopy.settingsSectionConnection,
      dirty: connectionDirty,
      icon: <SettingsConnectionIcon size={16} active={activeSettingsCategory === "connection"} />,
    },
    {
      id: "workspace",
      label: settingsPhrase(language, "navWorkspace"),
      dirty: false,
      icon: <SettingsWorkspaceIcon size={16} active={activeSettingsCategory === "workspace"} />,
    },
    {
      id: "teaching",
      label: templateCopy[language].coach,
      dirty: false,
      icon: <SettingsTeachingIcon size={16} active={activeSettingsCategory === "teaching"} />,
    },
    {
      id: "preferences",
      label: settingsGlobalCopy.settingsPreferences,
      dirty: false,
      icon: <SettingsPreferencesIcon size={16} active={activeSettingsCategory === "preferences"} />,
    },
  ] as const;
  const settingsStatusConnectionReady = providerCoachReady && !providerHasDraftChanges;
  // Blocker banner — one row per real problem, each with the action that
  // clears it. Same truth sources as the availability strip; hidden when
  // nothing is wrong so healthy Settings opens straight on the content.
  const settingsStatusIssues: Array<{
    id: "key" | "test" | "trust" | "unsaved";
    label: string;
    target: SettingsCategory;
    action?: () => void;
  }> = [];
  if (providerNeedsApiKey || coachSendState.reasonKind === "missing_api_key") {
    settingsStatusIssues.push({
      id: "key",
      label: settingsGlobalCopy.settingsStatusNoApiKey,
      target: "connection",
      action: openProviderApiKey,
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
      target: "workspace",
      action: onTrustWindow,
    });
  }
  if (connectionDirty) {
    const keyIssue = settingsStatusIssues.find(issue => issue.id === "key");
    if (keyIssue) {
      keyIssue.label = `${keyIssue.label} · ${settingsGlobalCopy.settingsStatusUnsaved}`;
    } else {
      settingsStatusIssues.push({
        id: "unsaved",
        label: settingsGlobalCopy.settingsStatusUnsaved,
        target: "connection",
        action: () => setConnectionView("edit"),
      });
    }
  }
  // De-duplication: the blocker bar at the top of the detail body is the
  // single actionable issue list. When it is visible alongside the strip
  // (detail pane only — the index hides the bar), the strip drops its action
  // button so it repeats none of the per-issue actions; the form-level Test
  // button renders instead (showProviderDetailTestAction below). The strip
  // keeps the full connection explanation. Backend recovery keeps its full
  // strip: the blocker bar has no row for it.
  const availabilityStripReduced =
    !settingsIndexOpen &&
    !backendRecovery &&
    settingsStatusIssues.some((issue) => issue.target === "connection");
  const showProviderDetailTestAction =
    availabilityStripReduced ||
    !canRetestProvider ||
    effectiveAvailabilityPrimaryCta.action !== onTestProvider;
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
  const runtimeFlowSummary = `${runtimeSummaryText}${coachStateSummaryText ? ` · ${coachStateSummaryText}` : ""}`;
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
  const providerListBar =
    providerProfiles.length > 0 ||
    canSaveProviderProfile ||
    (providerSaved && (onRefreshProviderProfiles || onUseProviderTemplateLabel)) ? (
      <div
        ref={providerDirectoryRef}
        className="settings-provider-bar"
        role="group"
        aria-label={localizedProviderProfilesLabel}
      >
        <div
          className="settings-sheet__provider-profiles settings-provider-bar__content"
          aria-label={providerSummaryText}
        >
          <div className="settings-provider-bar__list" role="list">
          {providerProfiles.map((profile) => (
            <button
              key={profile.id}
              className={`settings-provider-profile settings-provider-profile--bar ${
                profile.isActive ? "is-active" : ""
              }`}
              type="button"
              role="listitem"
              aria-pressed={profile.isActive}
              title={profile.detail ?? profile.label}
              disabled={!onSwitchProviderProfile || profile.isActive}
              onClick={() => {
                resetModelPickerSearch();
                setModelPickerOpen(false);
                setConnectionView("auto");
                onSwitchProviderProfile?.(profile.id);
              }}
            >
              <span className="settings-provider-profile__row">
                <span
                  className="settings-provider-profile__dot"
                  data-state={profile.isActive ? "active" : "idle"}
                  aria-hidden="true"
                />
                <span className="settings-provider-profile__label">{profile.label}</span>
                <span className="settings-provider-profile__meta">
                  <span className="settings-provider-profile__model">
                    {profile.model || provider.model}
                  </span>
                  {profile.isActive ? (
                    <span className="settings-provider-profile__state" aria-hidden="true">
                      <DoneIcon size={12} />
                    </span>
                  ) : null}
                </span>
              </span>
            </button>
          ))}
          </div>
          <div className="settings-provider-bar__actions">
            {providerSaved && !showConnectionSummary ? (
              <button
                type="button"
                className="settings-provider-bar__icon-button"
                title={settingsPhrase(language, "editConfiguration")}
                aria-label={settingsPhrase(language, "editConfiguration")}
                onClick={() => setConnectionView("edit")}
              >
                <SettingsPreferencesIcon size={14} />
              </button>
            ) : null}
            {canSaveProviderProfile && !showConnectionSummary ? (
              <button
                type="button"
                className="settings-provider-bar__add"
                title={localizedSaveProfileDetail}
                aria-label={localizedSaveProfileLabel}
                onClick={onSaveProviderProfile}
              >
                <DoneIcon size={13} />
                <span>{localizedSaveProfileLabel}</span>
              </button>
            ) : null}
            {onRefreshProviderProfiles ? (
              <button
                type="button"
                className="settings-provider-bar__icon-button"
                title={localizedRefreshProfilesLabel}
                aria-label={localizedRefreshProfilesLabel}
                onClick={onRefreshProviderProfiles}
              >
                <ReloadIcon size={14} />
              </button>
            ) : null}
            {providerSaved && onUseProviderTemplateLabel && connectionView !== "add" ? (
              <button
                type="button"
                className="settings-provider-bar__add"
                onClick={() => setConnectionView("add")}
              >
                <PlusIcon size={13} />
                <span>{settingsPhrase(language, "addProvider")}</span>
              </button>
            ) : null}
          </div>
        </div>
      </div>
    ) : null;
  const providerDirectory =
    showProviderTemplates ? (
    <div className="settings-provider-directory-wrap">
      <div
        ref={providerTemplatesRef}
        className="settings-provider-directory"
        role="group"
        aria-label={localizedProviderDirectoryLabel}
      >
        {PROVIDER_TEMPLATE_GROUP_ORDER.map((group) => {
          const groupLabels = PROVIDER_TEMPLATE_LABELS.filter(
            (templateLabel) => PROVIDER_TEMPLATE_GROUPS[templateLabel] === group,
          );
          if (groupLabels.length === 0) {
            return null;
          }
          return (
            <div className="settings-provider-directory__group" key={group}>
              <div className="settings-provider-directory__heading">
                {providerTemplateGroupLabel(language, group)}
                <span className="settings-section-count" aria-hidden="true">
                  {groupLabels.length}
                </span>
              </div>
              <div role="list">
                {groupLabels.map((templateLabel) => (
                  <button
                    key={templateLabel}
                    type="button"
                    className="settings-provider-directory__item"
                    onClick={() => {
                      setConnectionView("edit");
                      onUseProviderTemplateLabel?.(templateLabel);
                    }}
                  >
                    {templateLabel}
                  </button>
                ))}
              </div>
            </div>
          );
        })}
      </div>
      <p className="settings-sheet__note settings-sheet__note--compact">
        {settingsPhrase(language, "providerDirectoryNote")}
      </p>
    </div>
  ) : null;
  const providerSecondaryActions = (
    <div className="settings-actions settings-actions--compact">
      <ActionButton
        fullWidth={false}
        icon={<SettingsPreferencesIcon size={14} />}
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
  );
  const showProviderDetailStatePill =
    shouldShowProviderConnectionSummary &&
    (providerHasDraftChanges || !providerCoachReady || providerNeedsRetest);
  // r1-g2-4: the duplicate "连接" eyebrow and the mid-level "‹ 连接" back were
  // removed — SettingsDetail already owns the section title and the single
  // back affordance, and the provider bar row carries the identity summary.
  const providerAdvancedEntry = (
    <div className="settings-sheet__support coach-settings-view__provider-detail collapse-section collapse-section--level-2">
      <div className="collapse-section__header-row">
        <button
          type="button"
          className="collapse-section__header"
          aria-expanded="false"
          onClick={openProviderDetails}
        >
          <ChevronRightIcon size={12} aria-hidden />
          <span className="collapse-section__title">
            <span className="eyebrow">{settingsGlobalCopy.settingsConnectionDetails}</span>
          </span>
          {showProviderDetailStatePill ? (
            <span className="collapse-section__badge">
              <StatusPill tone={resolvedAvailabilityTone}>
                {localizedResolvedAvailabilityStatusLabel}
              </StatusPill>
            </span>
          ) : null}
          {shouldShowProviderConnectionSummary ? (
            <span className="collapse-section__subtitle">
              <span
                className="settings-sheet__defaults-preview"
                title={providerConnectionSummary}
                data-full-value={providerConnectionSummary}
              >
                {providerPreviewSummaryText}
              </span>
            </span>
          ) : null}
        </button>
      </div>
    </div>
  );
  const providerPrimaryActions = showProviderDetailActions ? (
    <div className="settings-actions settings-actions--compact settings-actions--primary">
      {!modelDiscoveryGuidanceActive ? (
        <ActionButton
          fullWidth={false}
          icon={
            providerSaveBusy ? (
              <span aria-hidden="true" className="trainer-spinner trainer-spinner--sm" />
            ) : (
              <DoneIcon size={14} />
            )
          }
          label={saveProviderConnectionLabel}
          ariaLabel={saveProviderConnectionLabel}
          // r1-g2-4: 保存并使用 is this screen's single solid primary; retest
          // and model-list refresh stay quiet secondary actions below it.
          tone="accent"
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
          icon={<ReloadIcon size={14} />}
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
          icon={<AlertTriangleIcon size={14} />}
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
                ? settingsText(language, "先完成 provider、base URL 和 model，再测试连接。", "Finish the provider, base URL, and model before testing the connection.")
                : !providerDraftHasApiKey && !providerDraftCanReuseSavedApiKey
                  ? settingsText(language, "先补上 API key，再测试这组连接。", "Add an API key before testing this connection.")
                  : providerSaved
                    ? settingsText(language, "先保存当前草稿，再测试这组连接。", "Save the current draft before testing this connection.")
                    : savedProviderProfilesAvailable
                      ? settingsText(language, "先启用一个已保存的 profile，再测试当前连接。", "Apply a saved profile before testing the current connection.")
                      : settingsText(language, "先完成 provider 配置，再测试连接。", "Finish the provider setup before testing the connection.")
          }
        />
      ) : null}
    </div>
  ) : null;
  const providerDetailRequirementNote = providerHasDraftChanges
    ? currentDraftModelPolicyMessage ??
      (!providerDraft.baseUrl.trim()
        ? settingsStatusPhrase(language, "fillProviderFields")
        : !providerDraft.model.trim()
          ? providerDraftHasApiKey || providerDraftCanReuseSavedApiKey
            ? settingsText(language, "保存时将自动获取并选择可用模型。", "A model will be fetched and selected automatically when you save.")
            : modelPickerCopy.modelRequiredNote
          : !providerDraftHasApiKey && !providerDraftCanReuseSavedApiKey
            ? settingsStatusPhrase(language, "connectionSavedApiKeyMissing")
            : localizedResolvedAvailabilityDetail)
    : providerRequirementNote ?? localizedResolvedAvailabilityDetail;

  const availabilityState = <div data-settings-availability="true">
    <SystemState
      kind={backendStarting || providerTestPending ? "processing" : backendUnavailable ? "disconnected" : workspaceRootMissing ? "workspace-required" : providerCredentialsRejected ? "recoverable-error" : availabilityMode !== "ready" ? "provider-required" : "success"}
      title={displayAvailabilityHeadline}
      detail={showAvailabilityPrimaryAction ? displayAvailabilityDetail : localizedResolvedAvailabilityStatusLabel}
      action={availabilityStripReduced ? undefined : showAvailabilityPrimaryAction && !backendStarting && !providerTestPending ? {
        label: effectiveAvailabilityPrimaryCta.label,
        onClick: () => effectiveAvailabilityPrimaryCta.action?.(),
        disabled: !effectiveAvailabilityPrimaryCta.action,
      } : undefined}
      actionTone={effectiveAvailabilityPrimaryTone}
    />
  </div>;

  return (
    <section className={classes} aria-labelledby="coach-settings-view-title">
      <h2 id="coach-settings-view-title" className="sr-only">
        {copy.title}
      </h2>

      {settingsIndexOpen && backendRecovery ? availabilityState : null}
      {settingsIndexOpen ? (
        <SettingsIndex
          title={copy.title}
          items={(["connection", "teaching", "workspace", "preferences"] as const).map((id) => {
            const item = settingsNavItems.find((item) => item.id === id)!;
            return { ...item, summary: id === "connection"
              ? [provider.model, providerRequirementNote].filter(Boolean).join(" · ")
              : id === "workspace" ? remoteWorkspaceName || resourceSandbox?.effectivePath || trainerWorkspace?.rootPath
              : id === "teaching" ? teachingStyleItems.find((item) => item.value === teachingStyle)?.label ?? copy.auto
              : `${language} · ${themePreference}` };
          })}
          onSelect={openSettingsCategorySection}
        />
      ) : null}
      <div hidden={settingsIndexOpen}>
      <SettingsDetail
        parent={copy.title}
        section={activeSettingsCategory}
        title={settingsNavItems.find((item) => item.id === activeSettingsCategory)?.label ?? copy.title}
        onBack={() => setSettingsIndexOpen(true)}
      >
      <div className="settings-sheet__body settings-sheet__body--hierarchical">
        {settingsStatusIssues.length > 0 ? (
        <div
          className="settings-status-bar settings-status-bar--blockers"
          role="region"
          aria-label={settingsGlobalCopy.settingsStatusRegionLabel}
          data-settings-status-bar="true"
          data-settings-status-connection={settingsStatusConnectionReady ? "ready" : "setup"}
        >
          {settingsStatusIssues.map((issue) => (
            <div
              key={issue.id}
              className={`settings-status-bar__row is-${issue.id}`}
              data-settings-status-issue={issue.id}
            >
              <div
                data-workspace-trust-state={issue.id === "trust" ? resolvedWorkspaceTrustState : undefined}
                data-settings-workspace-trust={issue.id === "trust" ? "true" : undefined}
              >
                <SystemState
                  kind={issue.id === "trust" ? "permission-required" : issue.id === "unsaved" ? "information" : "provider-required"}
                  title={issue.id === "trust" ? workspaceTrustSentence : issue.label}
                >
              <button
                type="button"
                className={`button button--ghost button--compact settings-trust-action${
                  issue.id === "trust" && resolvedWorkspaceTrustState === "trusted"
                    ? " is-trusted"
                    : ""
                }`}
                data-settings-trust-action={issue.id === "trust" ? "true" : undefined}
                onClick={() => {
                  if (issue.action) {
                    issue.action();
                    if (issue.target !== activeSettingsCategory && issue.id !== "trust") {
                      revealSettingsSection(issue.target);
                    }
                    return;
                  }
                  revealSettingsSection(issue.target);
                }}
              >
                <span
                  className="settings-trust-action__state"
                  data-trust-state={issue.id === "trust" ? resolvedWorkspaceTrustState : undefined}
                  aria-hidden="true"
                />
                {issue.id === "trust"
                  ? settingsText(language, "信任此窗口", "Trust this window")
                  : issue.id === "key" || issue.id === "unsaved"
                    ? settingsPhrase(language, "editConfiguration")
                    : settingsGlobalCopy.settingsSectionConnection}
              </button>
                </SystemState>
              </div>
            </div>
          ))}
        </div>
        ) : null}

        <div className="settings-sheet__layout">
          <div className="settings-sheet__pane">
        {activeSettingsCategory === "connection" ? (
        <section className="settings-section settings-section--panel settings-section--setup settings-section--summary">
          {showQuickSetup ? (
          <ProviderQuickSetup
            language={language}
            draft={providerDraft}
            savedBaseUrl={provider.baseUrl}
            savedModel={provider.model}
            connected={providerCoachReady}
            hasStoredApiKey={providerDraftCanReuseSavedApiKey}
            trusted={resolvedWorkspaceTrustState === "trusted"}
            busy={providerSaveBusy || providerTestPending}
            onTrustWindow={onTrustWindow}
            onDraftChange={onProviderDraftChange}
            onSave={() => {
              if (onSaveProvider) {
                onSaveProvider();
              }
            }}
          />
          ) : null}
          {showQuickSetup && onUseProviderTemplateLabel ? (
            <button
              type="button"
              className="settings-template-entry"
              data-settings-template-entry="true"
              onClick={() => setConnectionView("add")}
            >
              <span className="settings-template-entry__copy">
                <strong>{settingsPhrase(language, "startFromTemplate")}</strong>
                <span>{settingsPhrase(language, "startFromTemplateDetail")}</span>
              </span>
              <ChevronRightIcon size={14} aria-hidden />
            </button>
          ) : null}
          {showAvailabilityStrip ? availabilityState : null}

          <div
            ref={connectionAnchorRef}
            className={`settings-anchor${sectionFlash === "connection" ? " settings-anchor--flash" : ""}`}
            data-settings-section="connection"
          >
            {providerListBar}

            {connectionSummaryCard}

            {providerDirectory}

            {showConnectionForm && connectionView !== "advanced" ? (
            <>
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
                  <span>{providerBaseUrlLabel}</span>
                  <input
                    value={providerDraft.baseUrl}
                    placeholder={
                      settingsText(language, "例如 localhost:1234/v1 或 api.deepseek.com/v1", "e.g. localhost:1234/v1 or api.deepseek.com/v1")
                    }
                    onChange={(event) => {
                      const smartPaste = applyProviderSmartPaste(event.target.value, "baseUrl");
                      setProviderPasteHint(smartPaste ? providerPasteHintCopy(smartPaste) : null);
                      if (smartPaste) {
                        return;
                      }
                      onProviderDraftChange({
                        baseUrl: event.target.value,
                        ...(providerDraft.name.trim()
                          ? {}
                          : { name: DEFAULT_PROVIDER_CONNECTION_NAME }),
                      });
                    }}
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
                    onChange={(event) => {
                      const smartPaste = applyProviderSmartPaste(event.target.value, "apiKey");
                      setProviderPasteHint(smartPaste ? providerPasteHintCopy(smartPaste) : null);
                      if (smartPaste) {
                        return;
                      }
                      onProviderDraftChange({ apiKey: event.target.value });
                    }}
                  />
                </label>

                {providerPasteHint ? (
                  <p className="settings-sheet__note settings-sheet__note--compact settings-sheet__note--warning">
                    {providerPasteHint}
                  </p>
                ) : null}

                {modelCatalogIsEmpty ? (
                  <label className="settings-field">
                    <span>{copy.model}</span>
                    <input
                      value={currentDraftModel}
                      placeholder={modelPickerCopy.directModelPlaceholder}
                      onChange={(event) => onProviderDraftChange({ model: event.target.value })}
                    />
                    <p className="settings-sheet__note settings-sheet__note--compact">
                      {modelPickerCopy.directModelHint}
                    </p>
                  </label>
                ) : (
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
                  {/*
                    model catalog present: keep the disclosure picker
                  */}
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
                )}
              </div>

            </form>

            {providerPrimaryActions}
            {!providerCoachReady ? (
              <p className="settings-sheet__note settings-sheet__note--warning">
                {providerDetailRequirementNote}
              </p>
            ) : null}
            {showAvailabilityChecklist ? renderProviderSetupChecks("settings-setup-checks--availability") : null}
            {providerAdvancedEntry}
            </>
            ) : null}
          </div>

          {connectionView === "advanced" ? (
          <div className="settings-sheet__support coach-settings-view__provider-detail collapse-section collapse-section--level-2 is-open">
            <div className="collapse-section__header-row">
              <button
                type="button"
                className="collapse-section__header"
                aria-expanded="true"
                onClick={() => setConnectionView(advancedReturnView)}
              >
                <ChevronLeftIcon size={12} aria-hidden />
                <span className="collapse-section__title">
                  <span className="eyebrow">{settingsGlobalCopy.settingsConnectionDetails}</span>
                </span>
                {showProviderDetailStatePill ? (
                  <span className="collapse-section__badge">
                    <StatusPill tone={resolvedAvailabilityTone}>
                      {localizedResolvedAvailabilityStatusLabel}
                    </StatusPill>
                  </span>
                ) : null}
                <span className="collapse-section__subtitle">
                  {displayAvailabilityHeadline}
                </span>
              </button>
            </div>
            <div className="collapse-section__body-wrap">
              <div className="collapse-section__body">
              <div className="coach-settings-view__provider-detail-body">
                <div className="settings-grid settings-grid--form">
                  <label className="settings-field">
                    <span>{providerConnectionNameLabel(language)}</span>
                    <input
                      value={providerDraft.name}
                      placeholder={settingsText(language, "给这组连接起个名字(可不填)", "Name this connection (optional)")}
                      onChange={(event) => onProviderDraftChange({ name: event.target.value })}
                    />
                  </label>
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

                <ProviderEndpointSpeedTest
                  language={language}
                  baseUrl={normalizedDraftBaseUrl || providerDraft.baseUrl}
                  results={providerSpeedTestResults}
                  pending={providerSpeedTestPending}
                  onRun={(urls) => onSpeedTestEndpoints?.(urls)}
                  onAdopt={(url) => onProviderDraftChange({ baseUrl: url })}
                />

                {providerSecondaryActions}

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
                      detail={`${copy.modelCacheSource}: ${cacheSourceLabel}`}
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
                        settingsText(
                          language,
                          `图片：${capabilityVerdict.imageInput ? "已通过 vision probe 和协议附件支持验证" : imageInputState.detail ?? imageInputState.reason ?? "尚未验证"}`,
                          `Images: ${capabilityVerdict.imageInput ? "vision probe and protocol attachment support verified" : imageInputState.detail ?? imageInputState.reason ?? "not verified yet"}`,
                        )} · ${
                        workspaceAuthority?.authorityScope === "trainer_sandbox"
                          ? settingsText(language, "Trainer 沙箱 artifact 写入", "Trainer sandbox artifact writes")
                          : settingsText(language, "用户源码工作区只读", "User source workspace is read-only")
                      } · ${workspaceAuthority?.resourceWriteEvidence?.reason ?? (settingsText(language, "等待真实写入证据", "Awaiting verified write evidence"))}`
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
            </div>
            {providerPrimaryActions}
              </div>
            </div>
          </div>
          ) : null}

        </section>
        ) : null}

        {activeSettingsCategory === "workspace" ? (
        <section
          ref={workspaceAnchorRef}
          className={`settings-section settings-section--flat settings-anchor${sectionFlash === "workspace" ? " settings-anchor--flash" : ""}`}
          data-settings-section="workspace"
          aria-labelledby="settings-section-workspace-title"
        >
          <header className="settings-section-head">
            <span id="settings-section-workspace-title" className="eyebrow">
              {resolveWorkbenchCopy(language).workspaceRootControl}
            </span>
          </header>
          <div className="settings-sheet__minor-body">
            <WorkspaceRootRecoveryPanel
              trainerWorkspace={trainerWorkspace}
              onChooseRoot={onChooseTrainerWorkspaceRoot}
            />
            {resourceSandbox ? (
              <section className="settings-sheet__workspace-card" data-settings-subsection="data-area">
                <div className="settings-sheet__authority-block-head">
                  <span className="eyebrow">{copy.workspaceDataArea}</span>
                </div>
                <p className="settings-sheet__note settings-sheet__note--compact">
                  {managedDataUnderRoot
                    ? copy.workspaceDataUnderRoot
                    : copy.workspaceDataInAppFolder}
                </p>
                {!managedDataUnderRoot ? (
                  <div className="settings-actions settings-actions--compact">
                    <ActionButton
                      fullWidth={false}
                      icon={<DataFolderIcon size={14} />}
                      label={copy.workspaceDataMoveUnderRoot}
                      detail={settingsText(language, "移动数据并重启后端", "Move data and restart")}
                      onClick={onMoveManagedDataUnderRoot}
                    />
                  </div>
                ) : null}
              </section>
            ) : null}

            <section className="settings-sheet__workspace-card" data-settings-subsection="added-projects">
              <div className="settings-sheet__authority-block-head">
                <span className="eyebrow">{copy.addedProjects}</span>
              </div>
              {addedProjectRows.length === 0 ? (
                <p className="settings-sheet__note settings-sheet__note--compact">
                  {copy.addedProjectsEmpty}
                </p>
              ) : (
                <ul className="settings-added-projects" role="list">
                  {addedProjectRows.map((project) => (
                    <li
                      key={project.projectPath}
                      className="settings-added-projects__row"
                      data-added-project-current={project.isCurrent ? "true" : undefined}
                    >
                      <div className="settings-added-projects__copy">
                        <span className="settings-added-projects__name" title={project.projectPath}>
                          {project.projectName}
                          {project.isCurrent ? (
                            <span className="settings-added-projects__badge">
                              {copy.addedProjectsCurrent}
                            </span>
                          ) : project.adoptionMode === "browse" ? (
                            <span className="settings-added-projects__badge settings-added-projects__badge--browse">
                              {copy.addedProjectsBrowse}
                            </span>
                          ) : null}
                        </span>
                        <span
                          className="settings-sheet__path-value settings-added-projects__path"
                          title={project.projectPath}
                        >
                          {project.projectPath}
                        </span>
                      </div>
                      {onRemoveTrainerProject ? (
                        <button
                          type="button"
                          className="toolbar-button settings-added-projects__remove"
                          onClick={() => onRemoveTrainerProject(project.projectPath)}
                        >
                          {copy.projectRemove}
                        </button>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
              <p className="settings-sheet__note settings-sheet__note--compact">
                {copy.projectRemoveNote}
              </p>
            </section>
            {remoteWorkspaceName ? <section className="settings-sheet__workspace-card" data-settings-subsection="remote-support">
                {(() => {
                  const remoteSupportCopy = REMOTE_SUPPORT_COPY[language];
                  const view = remoteSupportStateView(language, companionInstallState);
                  return (
                    <>
                <div className="settings-sheet__authority-block-head">
                  <span className="eyebrow">
                    <RemoteIcon size={12} />
                    {remoteSupportCopy.sectionTitle}
                  </span>
                </div>
                <div className="settings-sheet__summary-grid">
                  <SummaryCard
                    label={remoteSupportCopy.remoteHost}
                    value={remoteWorkspaceName}
                  />
                </div>
                <p className="settings-sheet__note settings-sheet__note--compact">
                  {remoteSupportCopy.intro}
                </p>
                                      {view.note ? (
                        <p className="settings-sheet__note settings-sheet__note--compact">{view.note}</p>
                      ) : null}
                      <button
                        type="button"
                        className="toolbar-button"
                        disabled={view.disabled}
                        onClick={() =>
                          postWebviewMessage({
                            type: "command/execute",
                            payload: { commandId: trainerCommands.remoteInstallCompanion },
                          })
                        }
                      >
                        {view.button}
                      </button>
                    </>
                  );
                })()}
            </section> : null}

            <details className="settings-sheet__workspace-card settings-workspace-advanced" data-settings-subsection="workspace-advanced">
              <summary>{copy.workspaceAdvanced}</summary>
              <div className="settings-sheet__stack settings-sheet__stack--tight">
                {resourceSandbox ? (
                  <>
                    <div className="settings-actions settings-actions--compact">
                      <ActionButton
                        fullWidth={false}
                        icon={<DataFolderIcon size={14} />}
                        label={copy.managedDataFolderChoose}
                        detail={settingsText(language, "切换并重启后端", "Switch and restart")}
                        onClick={onChooseManagedDataFolder}
                      />
                      <ActionButton
                        fullWidth={false}
                        icon={<ReloadIcon size={14} />}
                        label={copy.managedDataFolderReset}
                        detail={settingsText(language, "回到推荐目录", "Return to recommended")}
                        onClick={onResetManagedDataFolder}
                      />
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
                  </>
                ) : null}
                <div className="settings-actions settings-actions--compact">
                  <ActionButton
                    fullWidth={false}
                    icon={<RefreshIcon size={14} />}
                    label={settingsGlobalCopy.workspaceRootMigrate}
                    detail={settingsGlobalCopy.workspaceRootMigrateDetail}
                    onClick={onMigrateTrainerWorkspaceRoot}
                  />
                  <ActionButton
                    fullWidth={false}
                    icon={<FileIcon size={14} />}
                    label={settingsGlobalCopy.workspaceRootBackup}
                    detail={settingsGlobalCopy.workspaceRootBackupDetail}
                    onClick={onBackupTrainerWorkspace}
                  />
                  <ActionButton
                    fullWidth={false}
                    icon={<UploadIcon size={14} />}
                    label={settingsGlobalCopy.workspaceRootRestore}
                    detail={settingsGlobalCopy.workspaceRootRestoreDetail}
                    onClick={onRestoreTrainerWorkspaceBackup}
                  />
                </div>
                <div className="settings-sheet__authority-block">
                  <div className="settings-sheet__authority-block-head">
                    <span className="eyebrow">{copy.currentWorkspace}</span>
                    <ActionButton
                      fullWidth={false}
                      icon={<ReloadIcon size={14} />}
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
                        <SettingsPreferencesIcon size={16} />
                      </span>
                      <span className="empty-state__title">{copy.workspaceAuthorityEmpty}</span>
                    </div>
                  )}
                </div>
              </div>
            </details>
          </div>
        </section>
        ) : null}

        {activeSettingsCategory === "teaching" ? (
        <section
          ref={teachingPrefsAnchorRef}
          className={`settings-section settings-section--flat settings-anchor${sectionFlash === "teaching" ? " settings-anchor--flash" : ""}`}
          data-settings-section="teaching"
          aria-labelledby="settings-section-teaching-title"
        >
          <header className="settings-section-head">
            <span id="settings-section-teaching-title" className="eyebrow">
              {settingsGlobalCopy.settingsTeachingPrefs}
            </span>
            <span className="settings-section-head__summary">{coachBehaviorSummary}</span>
            {coachSettingsAutosaveNode}
          </header>
          <div className="settings-sheet__minor-body settings-sheet__defaults-body">
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
              </div>



          </div>
        </section>
        ) : null}

        {activeSettingsCategory === "preferences" ? (
        <section
          ref={preferencesAnchorRef}
          className={`settings-section settings-section--flat settings-anchor${sectionFlash === "preferences" ? " settings-anchor--flash" : ""}`}
          data-settings-section="preferences"
          aria-labelledby="settings-section-preferences-title"
        >
          <header className="settings-section-head">
            <span id="settings-section-preferences-title" className="eyebrow">
              {settingsGlobalCopy.settingsPreferences}
            </span>
            <span className="settings-section-head__summary">{advancedSummaryText}</span>
            {coachSettingsAutosaveNode}
          </header>
          <div className="settings-sheet__minor-body settings-sheet__defaults-body">
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
            <div className="settings-subsection" data-settings-subsection="appearance">
              <span className="eyebrow settings-subsection__title">{settingsGlobalCopy.settingsAppearance}</span>
              <div className="settings-grid settings-grid--compact settings-grid--tight">
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
            </div>

            <div className="settings-subsection" data-settings-subsection="memory">
              <span className="eyebrow settings-subsection__title">{settingsGlobalCopy.settingsMemoryPrivacy}</span>
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
              </div>
          {rememberedRows.length ? (
            <div className="settings-sheet__remembered-panel">
              <div className="settings-sheet__remembered-summary">
                <span className="eyebrow">
                  {settingsPhrase(language, "trainerRemembers")}
                </span>
                {remembersSummary ? (
                  <span className="settings-sheet__remembered-preview">{remembersSummary}</span>
                ) : null}
              </div>
              <div className="settings-sheet__simple-list" aria-label={settingsPhrase(language, "trainerRemembers")}>
                {rememberedRows.map((row) => (
                  <SimpleInfoRow key={row.label} label={row.label} value={row.value} />
                ))}
              </div>
            </div>
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

          <MemorySharingPanel
            copy={copy}
            canManageMemoryShares={canManageMemoryShares}
            memorySharingSummary={memorySharingSummary}
            memoryShareGrants={memoryShareGrants}
            memoryShareSourceLabel={memoryShareSourceLabel}
            personalAccountTrusted={personalAccountTrusted === true}
            onSetPersonalAccountTrust={onSetPersonalAccountTrust}
            onGrantMemoryShare={onGrantMemoryShare}
            onRevokeMemoryShare={onRevokeMemoryShare}
          />
            </div>

            <div className="settings-subsection" data-settings-subsection="review">
              <div className="settings-sheet__utility-grid">
                <section className="settings-sheet__workspace-card">
                  <span className="eyebrow settings-subsection__title">{copy.reviewStrategy}</span>
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
              </div>
            </div>

            <div className="settings-subsection" data-settings-subsection="maintenance">
              <div className="settings-sheet__utility-grid">
                <section className="settings-sheet__workspace-card">
                  <span className="eyebrow">{copy.systemActions}</span>
                  <div className="settings-actions settings-actions--compact">
                    <ActionButton
                      fullWidth={false}
                      icon={<ReloadIcon size={14} />}
                      label={copy.refreshMemory}
                      detail={settingsText(language, "重建摘要", "Rebuild summary")}
                      onClick={onRefreshMemory}
                    />
                    <ActionButton
                      fullWidth={false}
                      icon={<SettingsSkillsIcon size={14} />}
                      label={copy.resetDefaults}
                      detail={settingsText(language, "推荐值", "Recommended")}
                      onClick={onResetDefaults}
                    />
                  </div>
                </section>
              </div>
          <div className="settings-sheet__minor-body settings-sheet__minor-body--flat">
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
            </div>
          </div>
        </section>
        ) : null}

        {activeSettingsCategory === "teaching" ? (
        <section
          className="settings-section settings-section--flat settings-anchor"
          data-settings-section="skills"
          aria-labelledby="settings-section-skills-title"
        >
          <header className="settings-section-head">
            <span id="settings-section-skills-title" className="eyebrow">
              {settingsGlobalCopy.settingsSectionSkills}
            </span>
            <span className="settings-section-head__summary">
              {settingsText(language, "Trainer 按你的问题自动选用；输入 $ 可手动触发。", "Trainer picks these automatically; type $ to trigger one manually.")}
            </span>
          </header>
          <div className="settings-sheet__minor-body settings-sheet__defaults-body">
            <details className="template-disclosure" data-skill-catalog="true"><summary>{templateCopy[language].builtinSkills}</summary><div className="settings-skill-groups">
              {(
                ["Coach", "Plan", "Training", "Resources", "Workspace", "Provider"] as TrainerSkillSection[]
              ).map((section) => {
                const items = trainerSkillCatalog.filter((skill) => skill.section === section);
                if (items.length === 0) {
                  return null;
                }
                return (
                  <div key={section} className="settings-subsection" data-settings-subsection={`skills-${section.toLowerCase()}`}>
                    <span className="eyebrow settings-subsection__title">
                      {trainerSkillSectionLabel(section, language)}
                    </span>
                    <div className="settings-sheet__simple-list" role="list">
                      {items.map((skill) => {
                        const title = resolveTrainerSkillText(skill.title, language);
                        const detail = resolveTrainerSkillText(skill.detail, language);
                        return (
                          <div key={skill.id} className="settings-skill-row" role="listitem">
                            <span className="settings-skill-row__trigger">{skill.trigger}</span>
                            <span className="settings-skill-row__body">
                              <span className="settings-skill-row__title">{title}</span>
                              {detail ? (
                                <span className="settings-skill-row__detail">{detail}</span>
                              ) : null}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div></details>

            {skillSharing}
            <div className="settings-subsection" data-settings-subsection="skills-custom">
              <span className="eyebrow settings-subsection__title">
                {settingsText(language, "我的技能", "My skills")}
              </span>
              {customSkills.length > 0 ? (
                <div className="settings-sheet__simple-list" role="list">
                  {customSkills.map((skill) => (
                    <div key={skill.id} className="settings-skill-row" role="listitem">
                      <span className="settings-skill-row__trigger">{skill.trigger}</span>
                      <span className="settings-skill-row__body">
                        <span className="settings-skill-row__title">{skill.title}</span>
                        {skill.detail ? (
                          <span className="settings-skill-row__detail">{skill.detail}</span>
                        ) : null}
                      </span>
                      <button
                        type="button"
                        className="settings-skill-row__remove"
                        aria-label={settingsText(language, "删除技能", "Remove skill")}
                        title={settingsText(language, "删除技能", "Remove skill")}
                        onClick={() =>
                          onCoachDefaultsChange?.({
                            customSkills: customSkills.filter((item) => item.id !== skill.id),
                          })
                        }
                      >
                        ✕
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="settings-sheet__note settings-sheet__note--compact">
                  {settingsText(
                    language,
                    "还没有自定义技能。添加一个，用 $触发器 在输入框里调用。",
                    "No custom skills yet. Add one and call it with its $trigger in the composer.",
                  )}
                </p>
              )}

              <div className="settings-skill-form-wrap">
              {customSkillFormOpen ? (
              <div className="settings-skill-form">
                <div className="settings-skill-form__field">
                  <span className="eyebrow">
                    {settingsText(language, "用一句话描述这个技能", "Describe the skill in one line")}
                  </span>
                  <textarea
                    value={customSkillDescription}
                    rows={2}
                    placeholder={settingsText(
                      language,
                      "例如:每周五把学习记录整理成周报,按完成/卡住/下一步输出",
                      "e.g. every Friday, tidy my learning log into done/stuck/next",
                    )}
                    onChange={(event) => {
                      setCustomSkillDescription(event.target.value);
                      setCustomSkillError(null);
                    }}
                  />
                </div>
                <button
                  type="button"
                  className="button button--accent settings-skill-form__generate"
                  disabled={
                    customSkillGenerating ||
                    customSkillDescription.trim().length < 2 ||
                    !onGenerateSkillDraft
                  }
                  onClick={async () => {
                    if (customSkillGenerating) return;
                    setCustomSkillGenerating(true);
                    setCustomSkillError(null);
                    try {
                      const draft = await onGenerateSkillDraft?.(customSkillDescription);
                      if (!draft) {
                        setCustomSkillError(
                          settingsText(
                            language,
                            "先描述一下这个技能要做什么。",
                            "Describe what the skill should do first.",
                          ),
                        );
                        return;
                      }
                      setCustomSkillDraft({
                        trigger: draft.trigger,
                        title: draft.title,
                        prompt: draft.prompt,
                        detail: draft.detail,
                      });
                      setCustomSkillSource(draft.source);
                      setCustomSkillError(null);
                    } catch {
                      setCustomSkillError(settingsText(language,
                        "技能生成失败。请检查连接后重试，也可以直接填写下方内容。",
                        "Skill generation failed. Check your connection and retry, or enter the skill below."));
                    } finally {
                      setCustomSkillGenerating(false);
                    }
                  }}
                >
                  {customSkillGenerating
                    ? settingsText(language, "生成中…", "Drafting…")
                    : settingsText(language, "✨ 智能生成", "✨ Draft with AI")}
                </button>
                {customSkillSource ? (
                  <p className="settings-sheet__note settings-sheet__note--compact">
                    {customSkillSource === "model"
                      ? settingsText(language, "已用当前模型生成,可直接修改后保存。", "Drafted with your model — tweak anything before saving.")
                      : settingsText(language, "已生成草稿(未连接模型),可修改后保存。", "Drafted without a model — tweak anything before saving.")}
                  </p>
                ) : null}

                <div className="settings-skill-form__field">
                  <span className="eyebrow">{settingsText(language, "触发器", "Trigger")}</span>
                  <input
                    type="text"
                    value={customSkillDraft.trigger}
                    placeholder="$my-skill"
                    onChange={(event) => {
                      setCustomSkillDraft((draft) => ({ ...draft, trigger: event.target.value }));
                      setCustomSkillError(null);
                    }}
                  />
                </div>
                <div className="settings-skill-form__field">
                  <span className="eyebrow">{settingsText(language, "名称", "Name")}</span>
                  <input
                    type="text"
                    value={customSkillDraft.title}
                    placeholder={settingsText(language, "例如:整理周报", "e.g. Tidy my weekly report")}
                    onChange={(event) => {
                      setCustomSkillDraft((draft) => ({ ...draft, title: event.target.value }));
                      setCustomSkillError(null);
                    }}
                  />
                </div>
                <div className="settings-skill-form__field">
                  <span className="eyebrow">{settingsText(language, "提示词", "Prompt")}</span>
                  <textarea
                    value={customSkillDraft.prompt}
                    rows={3}
                    onChange={(event) => {
                      setCustomSkillDraft((draft) => ({ ...draft, prompt: event.target.value }));
                      setCustomSkillError(null);
                    }}
                  />
                </div>
                {customSkillError ? (
                  <p className="settings-sheet__note settings-sheet__note--compact" role="alert">
                    {customSkillError}
                  </p>
                ) : null}
                <button
                  type="button"
                  className="button button--accent settings-skill-form__add"
                  disabled={
                    !customSkillDraft.trigger.trim() ||
                    !customSkillDraft.title.trim() ||
                    !customSkillDraft.prompt.trim() ||
                    customSkills.length >= 24
                  }
                  onClick={() => {
                    const normalized = normalizeCustomSkillTrigger(customSkillDraft.trigger);
                    if (!normalized) {
                      setCustomSkillError(
                        settingsText(
                          language,
                          "触发器需要是 $ 开头、无空格的短词(例如 $weekly-report)。",
                          "The trigger must be a short $word without spaces (e.g. $weekly-report).",
                        ),
                      );
                      return;
                    }
                    if (
                      customSkills.some(
                        (item) => item.trigger.toLowerCase() === normalized.toLowerCase(),
                      )
                    ) {
                      setCustomSkillError(
                        settingsText(language, "这个触发器已经被使用了。", "That trigger is already in use."),
                      );
                      return;
                    }
                    const prompt = customSkillDraft.prompt.trim();
                    const title = customSkillDraft.title.trim();
                    const detail =
                      customSkillDraft.detail.trim() ||
                      (prompt.length > 140 ? `${prompt.slice(0, 137)}...` : prompt);
                    onCoachDefaultsChange?.({
                      customSkills: [
                        ...customSkills,
                        {
                          id: `custom-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`,
                          trigger: normalized,
                          title,
                          detail,
                          prompt,
                          keywords: [],
                          createdAt: new Date().toISOString(),
                        } satisfies TrainerCustomSkill,
                      ],
                    });
                    setCustomSkillDraft({ trigger: "", title: "", prompt: "", detail: "" });
                    setCustomSkillDescription("");
                    setCustomSkillSource(null);
                    setCustomSkillError(null);
                    setCustomSkillFormOpen(false);
                  }}
                >
                  {settingsText(language, "添加技能", "Add skill")}
                </button>
              </div>
            ) : (
              <button
                type="button"
                className="button button--accent settings-skill-form__toggle"
                onClick={() => setCustomSkillFormOpen(true)}
              >
                {settingsText(language, "添加技能", "Add skill")}
              </button>
            )}
              </div>
            </div>
          </div>
        </section>
        ) : null}

        {activeSettingsCategory === "preferences" ? (
        <section
          className="settings-section settings-section--flat settings-anchor"
          data-settings-section="advanced"
          aria-labelledby="settings-section-advanced-title"
        >
          <header className="settings-section-head">
            <span id="settings-section-advanced-title" className="eyebrow">
              {settingsGlobalCopy.settingsAdvancedContext}
            </span>
          </header>
          <div className="settings-sheet__minor-body settings-sheet__defaults-body">
            <div className="settings-subsection">
              <span className="eyebrow settings-subsection__title">
                {settingsText(language, "内部标识", "Internal identifiers")}
              </span>
              <div className="settings-sheet__simple-list" role="list">
                <SimpleInfoRow
                  label={settingsText(language, "工作区 ID", "Workspace ID")}
                  value={workspaceId || "—"}
                />
                {provider.profileId?.trim() ? (
                  <SimpleInfoRow
                    label={settingsText(language, "配置 ID", "Profile ID")}
                    value={provider.profileId.trim()}
                  />
                ) : null}
              </div>
              <p className="settings-sheet__note settings-sheet__note--compact">
                {settingsText(language, "这些标识用于问题排查；连接诊断在“连接”页。", "Use these identifiers when reporting issues; connection diagnostics live under Connection.")}
              </p>
            </div>

            <CollapseSection
              level={2}
              persistenceKey="settings-advanced-context"
              open={advancedContextPinned ?? answerStyle === "custom"}
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
        </section>
        ) : null}
          </div>
        </div>
      </div>
      </SettingsDetail>
      </div>
    </section>
  );
}
