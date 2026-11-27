import {
  type ReactNode
} from "react";
import type { TrainerCapabilityVerdict } from "../../../../../shared/src/capabilityVerdict";
import type { ProviderModelTokenLimit,ProviderProtocol } from "../../../../../shared/src/models";
import {
  isNewApiConnectionType,
  parseProviderConnectionPaste,
} from "../../../../../shared/src/providerGateway";
import {
  looksLikeSchemelessProviderUrl,
  normalizeProviderBaseUrl,
  providerProtocolCompletionLabel
} from "../../../../../shared/src/providerProtocols";
import {
  type ProviderImageInputState,
  type ProviderSendState
} from "../../../../../shared/src/providerStatus";
import {
  type ProviderTemplateGroup
} from "../../../../../shared/src/providerTemplateCatalog";
import type { ProviderThinkingConfig } from "../../../../../shared/src/providerThinking";
import {
  settingsProtocolIsKnown
} from "../../../../../shared/src/settingsCapabilityGovernance";
import {
  type WorkspaceTrustState
} from "../../../../../shared/src/workspaceTrustState";
import type { ProviderEndpointSpeedTestResult } from "../../lib/types";
import { type SettingsSectionId } from "../../templates/SettingsIndex";

import { resolveCopy as resolveWorkbenchCopy } from "../../lib/i18n/copy";
import {
  extraLocalizedSettingsLabels,
  firstScreenRowLabels,
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
  type ToolsVerificationCopy
} from "../../lib/i18n/segments/settingsInlineText";
import type {
  CapabilityFlags,
  CoachAnswerMode,
  ComposerLanguage,
  ProviderConfigView,
  ProviderProbeUsage,
  WorkspaceAuthority
} from "../../lib/types";
import { languageIntegrityText } from "./languageIntegrityCopy";
import { settingsText } from "./settingsText";

export type AnswerMode = CoachAnswerMode;
export type SaveState = "saved" | "unsaved" | "empty";

export type CapabilityVerdictKey =
  | "chat"
  | "streaming"
  | "tools"
  | "image-input"
  | "formal-plan"
  | "resource-write";

export const CAPABILITY_VERDICT_LABELS: Record<ComposerLanguage, Record<CapabilityVerdictKey, string>> = {
  "zh-CN": {
    chat: "对话",
    streaming: "流式输出",
    tools: "工具调用",
    "image-input": "图像理解",
    "formal-plan": "学习计划",
    "resource-write": "资料写入",
  },
  "en-US": {
    chat: "Chat",
    streaming: "Streaming",
    tools: "Tools",
    "image-input": "Image input",
    "formal-plan": "Learning plan",
    "resource-write": "Library write",
  },
  "es-ES": {
    chat: "Chat",
    streaming: "Streaming",
    tools: "Herramientas",
    "image-input": "Imagen",
    "formal-plan": "Plan formal",
    "resource-write": "Escritura",
  },
  "fr-FR": {
    chat: "Chat",
    streaming: "Streaming",
    tools: "Outils",
    "image-input": "Image",
    "formal-plan": "Plan formel",
    "resource-write": "Écriture",
  },
  "de-DE": {
    chat: "Chat",
    streaming: "Streaming",
    tools: "Werkzeuge",
    "image-input": "Bildeingabe",
    "formal-plan": "Lernplan",
    "resource-write": "Schreibzugriff",
  },
  "ja-JP": {
    chat: "チャット",
    streaming: "ストリーミング",
    tools: "ツール",
    "image-input": "画像入力",
    "formal-plan": "学習プラン",
    "resource-write": "資料書込",
  },
  "ko-KR": {
    chat: "대화",
    streaming: "스트리밍",
    tools: "도구",
    "image-input": "이미지 입력",
    "formal-plan": "학습 계획",
    "resource-write": "자료 쓰기",
  },
  "pt-BR": {
    chat: "Chat",
    streaming: "Streaming",
    tools: "Ferramentas",
    "image-input": "Imagem",
    "formal-plan": "Plano formal",
    "resource-write": "Escrita",
  },
};
export type AnswerStylePreset = "simple" | "balanced" | "deep" | "custom";
export const DEFAULT_PROVIDER_CONNECTION_NAME = "custom-openai-compatible";
// P0: the model picker renders the full known list — search still filters, the
// select scrolls. The only remaining cap is a defensive guard against an
// absurd catalog (>= 200 entries), never a UI truncation of real data.
export const MODEL_PICKER_DEFENSIVE_OPTION_LIMIT = 200;
export const ANSWER_STYLE_STORAGE_KEY = "trainer.settings.answerStyle";
/** Flash highlight lifetime for status-bar jumps (ms). Skipped under reduced motion. */
export const SETTINGS_SECTION_FLASH_MS = 600;

export interface AnswerStyleValues {
  contextDetail: "focused" | "balanced" | "full";
  includeCurrentFile: boolean;
  includeSelection: boolean;
  includeDiagnostics: boolean;
  includeRelatedFiles: boolean;
}

export const ANSWER_STYLE_PRESETS: Record<"simple" | "balanced" | "deep", AnswerStyleValues> = {
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
export function deriveAnswerStylePreset(values: AnswerStyleValues): AnswerStylePreset {
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

export function readStoredAnswerStyle(): AnswerStylePreset | undefined {
  try {
    const stored = window.localStorage.getItem(ANSWER_STYLE_STORAGE_KEY);
    return stored === "simple" || stored === "balanced" || stored === "deep" || stored === "custom"
      ? stored
      : undefined;
  } catch {
    return undefined;
  }
}

export function writeStoredAnswerStyle(preset: AnswerStylePreset): void {
  try {
    window.localStorage.setItem(ANSWER_STYLE_STORAGE_KEY, preset);
  } catch {
    // Best-effort persistence; derivation from knob values stays authoritative.
  }
}

export function prefersReducedMotion(): boolean {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

export function learningSurfaceAlignmentCopy(language: ComposerLanguage): {
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

export function browserCaptureSettingsCopy(language: ComposerLanguage): {
  title: string;
  body: string;
  launch: string;
  install: string;
  open: string;
  hint: string;
} {
  switch (language) {
    case "zh-CN":
      return {
        title: "浏览器伴随侧边栏与采集",
        body: "在浏览器侧边栏直接复用完整的 Trainer 对话、学习计划、训练与网页/PDF 采集能力。支持 Chrome、Edge、Brave、Arc、Opera、Vivaldi 等 Chromium 浏览器。",
        launch: "一键启动适配浏览器",
        install: "安装到常用浏览器",
        open: "打开扩展页",
        hint: "点击“一键启动适配浏览器”可直接拉起预装好扩展的专属浏览器窗口；若安装到常用浏览器，只需在扩展页开启开发者模式并拖入自动打开的目录。单次握手凭据已自动预置，全程无需输入配对码。",
      };
    case "es-ES":
      return {
        title: "Panel lateral y captura del navegador",
        body: "Usa la barra lateral completa de Trainer (chat, plan, práctica y captura de páginas o PDF) directamente en Chrome, Edge, Brave, Arc, Opera o Vivaldi.",
        launch: "Iniciar navegador adaptado",
        install: "Instalar en tu navegador",
        open: "Abrir página de extensiones",
        hint: "«Iniciar navegador adaptado» abre una ventana con la extensión ya cargada; para tu perfil habitual, activa el modo desarrollador y arrastra la carpeta abierta. La conexión es automática y sin código.",
      };
    case "fr-FR":
      return {
        title: "Panneau latéral et capture navigateur",
        body: "Retrouvez toute la barre latérale Trainer (discussion, plan, entraînement et capture web/PDF) directement dans Chrome, Edge, Brave, Arc, Opera ou Vivaldi.",
        launch: "Lancer le navigateur adapté",
        install: "Installer dans le navigateur",
        open: "Ouvrir la page des extensions",
        hint: "« Lancer le navigateur adapté » ouvre une fenêtre avec l’extension préchargée ; pour votre profil habituel, activez le mode développeur et glissez le dossier ouvert. Connexion automatique sans code.",
      };
    case "de-DE":
      return {
        title: "Browser-Seitenleiste und Erfassung",
        body: "Nutze die komplette Trainer-Seitenleiste (Chat, Lernplan, Training sowie Webseiten- und PDF-Erfassung) direkt in Chrome, Edge, Brave, Arc, Opera oder Vivaldi.",
        launch: "Trainer-Browser starten",
        install: "Im Browser installieren",
        open: "Erweiterungsseite öffnen",
        hint: "„Trainer-Browser starten“ öffnet sofort ein Fenster mit geladener Erweiterung; für dein Hauptprofil aktiviere den Entwicklermodus und ziehe den geöffneten Ordner hinein. Automatische Verbindung ohne Code.",
      };
    case "ja-JP":
      return {
        title: "ブラウザーサイドパネルと取り込み",
        body: "Chrome、Edge、Brave、Arc、Opera、Vivaldi のサイドパネルで Trainer の対話・学習プラン・トレーニング・Web/PDF 取り込みをそのまま利用できます。",
        launch: "専用ブラウザーを起動",
        install: "通常ブラウザーに導入",
        open: "拡張機能ページを開く",
        hint: "「専用ブラウザーを起動」で拡張機能組み込み済みのウィンドウを即座に開けます。既存のブラウザーに導入する場合はデベロッパーモードをオンにして開いたフォルダーをドロップするだけです（コード不要で自動接続）。",
      };
    case "ko-KR":
      return {
        title: "브라우저 사이드 패널 및 캡처",
        body: "Chrome, Edge, Brave, Arc, Opera, Vivaldi 사이드 패널에서 Trainer 대화, 학습 계획, 훈련, 웹/PDF 캡처를 그대로 사용합니다.",
        launch: "전용 브라우저 실행",
        install: "기존 브라우저에 설치",
        open: "확장 프로그램 페이지 열기",
        hint: "'전용 브라우저 실행'을 누르면 확장이 미리 로드된 브라우저가 바로 열립니다. 기존 프로필에 설치하려면 개발자 모드를 켜고 열린 폴더를 끌어놓으세요. 사전 핸드셰이크로 코드 없이 자동 연결됩니다.",
      };
    case "pt-BR":
      return {
        title: "Painel lateral e captura no navegador",
        body: "Use toda a barra lateral do Trainer (chat, plano, prática e captura de páginas/PDF) diretamente no Chrome, Edge, Brave, Arc, Opera ou Vivaldi.",
        launch: "Iniciar navegador adaptado",
        install: "Instalar no navegador",
        open: "Abrir página de extensões",
        hint: "“Iniciar navegador adaptado” abre uma janela já com a extensão carregada; no seu perfil habitual, ative o modo desenvolvedor e arraste a pasta aberta. Conexão automática e sem código.",
      };
    default:
      return {
        title: "Browser side panel and capture",
        body: "Use the full Trainer sidebar — chat, learning plan, practice, and web/PDF capture — directly inside Chrome, Edge, Brave, Arc, Opera, or Vivaldi.",
        launch: "Launch Trainer browser",
        install: "Install to browser",
        open: "Open extensions page",
        hint: "Click “Launch Trainer browser” to open a ready-to-use browser window with the extension pre-loaded, or install once to your regular profile via Developer mode. A pre-seeded handshake connects automatically with zero pairing code.",
      };
  }
}

export interface ProviderProfileView {
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

export function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined;
}

export function asString(value: unknown): string | undefined {
  if (typeof value !== "string") {
    return undefined;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

export function asStringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
    : [];
}

export function asNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

export function normalizeProviderBaseUrlDraft(value: string, protocol: ProviderProtocol | undefined): string {
  // Shared canonicalizer keeps the webview draft on the same base URL the host
  // will test and save (scheme defaults, paste-full endpoint collapsing).
  return normalizeProviderBaseUrl(value, protocol);
}

export function looksLikeProviderServiceAddress(value: string): boolean {
  return /^https?:\/\//i.test(value.trim()) || looksLikeSchemelessProviderUrl(value);
}

export function looksLikeProviderApiKeyToken(value: string): boolean {
  const trimmed = value.trim();
  if (!trimmed || /\s|[/.:]/.test(trimmed)) {
    return false;
  }
  if (/^(?:sk|rk|pk|csk|gsk|xai|ghp|gho|key)[-_][A-Za-z0-9._-]{8,}$/i.test(trimmed)) {
    return true;
  }
  return /^[A-Za-z0-9_-]{20,}$/.test(trimmed);
}

export function providerConnectionLabelFromPaste(
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


export function providerConnectionTruthCopy(language: ComposerLanguage): ProviderConnectionTruthCopy {
  return providerConnectionTruthCopyTable[language] ?? providerConnectionTruthCopyTable["en-US"];
}

export function providerTemplateGroupLabel(
  language: ComposerLanguage,
  group: ProviderTemplateGroup,
): string {
  return providerTemplateGroupLabelTable[language][group];
}

export function providerDetailLabel(language: ComposerLanguage, key: ProviderDetailLabelKey): string {
  return providerDetailLabelTable[language]?.[key] ?? providerDetailLabelTable["en-US"][key];
}

export function providerBaseUrlGuidance(
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

export function providerModelDiscoveryCopy(language: ComposerLanguage): {
  findModels: string;
  findModelsDetail: string;
  missingBaseUrl: string;
  missingApiKey: string;
  modelOptional: string;
  manualFallback: string;
} {
  return providerModelDiscoveryCopyTable[language] ?? providerModelDiscoveryCopyTable["en-US"];
}

export function providerModelPickerCopy(language: ComposerLanguage): {
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

export function modelPolicyHint(
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


export function normalizeComparablePath(value: string | undefined | null): string | undefined {
  const trimmed = typeof value === "string" ? value.trim() : "";
  if (!trimmed) {
    return undefined;
  }
  return trimmed.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
}

export function memoryShareSourceLabel(sourceWorkspaceId: string): string {
  const segments = sourceWorkspaceId.replace(/\\/g, "/").split("/").filter(Boolean);
  return segments[segments.length - 1] || sourceWorkspaceId;
}

export function normalizeProviderProfileView(
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

export function normalizeProviderProfileViews(provider: ProviderConfigView): ProviderProfileView[] {
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
  ignoreSystemProxy?: boolean;
  catalogModels?: string[];
  allowedModels?: string[];
  deniedModels?: string[];
  embeddingModel?: string;
  catalogSource?: ProviderConfigView["catalogSource"];
  cacheTtlSeconds?: number;
  requestDefaults?: Record<string, unknown>;
  thinkingConfig?: ProviderThinkingConfig;
  capabilities?: CapabilityFlags;
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
  onCancelProviderTest?: () => void;
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
export interface CoachSettingsViewSheetProps {
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
  onResetProviderDraft?: () => void;
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
  onCancelProviderTest?: () => void;
  onRestartSidecar?: () => void;
  onClearProvider?: () => void;
  onOpenConfig?: () => void;
  onResetDefaults?: () => void;
}

export function localizedSettingsLabels(language: ComposerLanguage): Partial<CoachSettingsLabels> {
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

export function settingsPhrase(language: ComposerLanguage, key: SettingsPhraseKey): string {
  return settingsPhraseTable[language][key] ?? settingsPhraseTable["en-US"][key];
}

export function settingsSupportPhrase(language: ComposerLanguage, key: SettingsSupportPhraseKey): string {
  return settingsSupportPhraseTable[language][key] ?? settingsSupportPhraseTable["en-US"][key];
}

export function settingsStatusPhrase(language: ComposerLanguage, key: SettingsStatusPhraseKey): string {
  return settingsStatusPhraseTable[language][key] ?? settingsStatusPhraseTable["en-US"][key];
}



export function providerVerdictTone(
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

export function capabilityLabels(
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

export function capabilitySummaryText(
  capabilities: CapabilityFlags | undefined,
  language: ComposerLanguage,
): string {
  const labels = capabilityLabels(capabilities, language);
  if (labels.length === 0) {
    return settingsText(language, "未声明", "Not declared");
  }
  return labels.join(" · ");
}



export function stringifyNode(value: ReactNode): string | undefined {
  if (typeof value === "string" || typeof value === "number") {
    const text = `${value}`.trim();
    return text.length ? text : undefined;
  }
  return undefined;
}

export function compactSummaryValue(rows: string[], fallback: string): string {
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

export function shortenSummary(value: string, limit = 88): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= limit) {
    return normalized;
  }
  return `${normalized.slice(0, Math.max(0, limit - 1)).trimEnd()}…`;
}

export function adaptiveBehaviorLabel(
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

export function formatTokenValue(value: number | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    return "-";
  }
  return new Intl.NumberFormat("en-US").format(Math.round(value));
}

export function formatProbeCostValue(value: number | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "-";
  }
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 8 }).format(value);
}

/**
 * §二十一: probe usage detail from provider-reported numbers only. Each part
 * stays hidden when the provider did not report it — nothing is estimated.
 */
export function describeProbeUsageDetail(
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

export function formatDurationSeconds(value: number | undefined): string | undefined {
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

export function summarizeProviderRequestDefaults(value: unknown): string | undefined {
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

export function formatDraftStringList(value: string[] | undefined): string {
  return (value ?? []).join(", ");
}

export function parseDraftStringList(value: string): string[] {
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

export function mergeDraftStringList(...groups: Array<string[] | string | undefined>): string[] {
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

export function stringArrayKey(value: string[] | undefined): string {
  return JSON.stringify(
    (value ?? [])
      .map((entry) => entry.trim())
      .filter(Boolean),
  );
}

export function canonicalJsonValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(canonicalJsonValue);
  }
  if (value && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, item]) => item !== undefined)
      .sort(([left], [right]) => left.localeCompare(right));
    const sorted: Record<string, unknown> = {};
    for (const [key, item] of entries) {
      sorted[key] = canonicalJsonValue(item);
    }
    return sorted;
  }
  return value;
}

export function requestDefaultsKey(value: unknown): string {
  try {
    return JSON.stringify(canonicalJsonValue(asRecord(value) ?? {}));
  } catch {
    return "{}";
  }
}

export function providerCapabilitiesKey(value: Partial<CapabilityFlags> | undefined): string {
  return JSON.stringify([
    Boolean(value?.chat),
    Boolean(value?.responses),
    Boolean(value?.vision),
    Boolean(value?.embeddings),
    Boolean(value?.tools),
    Boolean(value?.jsonSchema),
    Boolean(value?.streaming),
    Boolean(value?.structuredOutput),
    Boolean(value?.thinking),
  ]);
}

export function formatRequestDefaultsDraft(value: unknown): string {
  return JSON.stringify(asRecord(value) ?? {}, null, 2);
}

export function parsePositiveIntegerInput(value: string): number | undefined {
  const normalized = value.trim();
  const parsed = Number.parseInt(normalized, 10);
  return normalized.length > 0 && Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
}

export function formatTimestamp(value: string | undefined, language: ComposerLanguage): string {
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

export function toolsVerificationCopy(language: ComposerLanguage): ToolsVerificationCopy {
  return toolsVerificationCopyTable[language] ?? toolsVerificationCopyTable["en-US"];
}

export function describeToolsVerificationFact(input: {
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

export function streamingVerificationCopy(language: ComposerLanguage): ToolsVerificationCopy {
  return streamingVerificationCopyTable[language] ?? streamingVerificationCopyTable["en-US"];
}

export function describeStreamingVerificationFact(input: {
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

export function streamingProbeIsVerified(
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

export function thinkingVerificationCopy(language: ComposerLanguage): {
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

export function describeThinkingVerificationFact(input: {
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

export function visionVerificationCopy(language: ComposerLanguage): {
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

export function describeVisionVerificationFact(input: {
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

export function gatewayFingerprintNote(
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

export function protocolChoiceLabel(protocol: ProviderProtocol | undefined, language: ComposerLanguage): string {
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


export function isMiniMaxLikeProvider(provider: Pick<ProviderConfigView, "name" | "baseUrl" | "model">): boolean {
  return /minimax/i.test(`${provider.name} ${provider.baseUrl} ${provider.model}`);
}


export function describeLanguageIntegrityFact(input: {
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
