import { SystemState } from "../../templates/SystemState";
import { Library } from "../../templates/Library";
import { ResourceReader } from "../../templates/ResourceReader";
import { templateCopy } from "../../templates/templateCopy";
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";

import { useTranslation } from "../../lib/i18n/useTranslation";
import { resolveCopy } from "../../lib/i18n/copy";
import { resolveResourceOrganizationConfirmCopy } from "../../lib/i18n/resourceComposerCopy";
import { resolveResourceOpenTarget } from "../../../../../shared/src/resourceOpen";
import {
  coachOrientationTone,
  type CoachOrientationState,
} from "../../../../../shared/src/coachOrientationGovernance";
import type { ResourcesOrientationRecord } from "../../../../../shared/src/resourcesOrientationGovernance";
import type {
  ComposerLanguage,
  DebugVisibleResourcesFacts,
  DeletedResource,
  ResourceRecord,
  ResourceSearchState,
  ResourceTrainingHandoffResult,
  SandboxPreview,
  SandboxState,
} from "../../lib/types";
import {
  ArrowRightIcon,
  ChevronDownIcon,
  FileIcon,
  FolderIcon,
  LinkIcon,
  PageIcon,
  PlusIcon,
  RefreshIcon,
  SearchIcon,
  TrashIcon,
  UploadIcon,
} from "../icons";
import { CollapseSection } from "../common/CollapseSection";
import { WorkbenchSurfaceButton } from "../common/WorkbenchSurfaceButton";
import { MessageRichContent } from "../coach/MessageRichContent";
import {
  addLibraryFolderPath,
  flattenLibraryFolders,
  libraryFolderName,
  libraryFolderParentPath,
  libraryFolderTreeFromResources,
  mergeLibraryFolderTrees,
  normalizeLibraryFolderPath,
  removeLibraryFolderPath,
  renameLibraryFolderPath,
  type LibraryFolderFlatEntry,
  type LibraryFolderListResult,
  type LibraryFolderNode,
} from "../../lib/libraryFolders";

import {
  compactResourceSearchPlaceholder,
  englishSingularResourceMutationText,
  resourceText,
  resourceTextLocaleOverrides,
  resourceTrainingReadinessCopy,
  type ResourceTextKey,
} from "../../lib/i18n/segments/resourcesInlineText";
export type { DeletedResource } from "../../lib/types";

export interface ResourceWriteAccess {
  allowed: boolean;
  reason?: string;
}

export interface ResourcesWorkbenchViewProps {
  language: ComposerLanguage;
  resources: ResourceRecord[];
  resourceSearch?: ResourceSearchState;
  deletedResources?: DeletedResource[];
  sandboxState?: SandboxState;
  sandboxPreview?: SandboxPreview;
  restoreContext?: ResourceRestoreContext;
  isBrowserPreview?: boolean;
  isLiveBrowserPreview?: boolean;
  onSearchResources?: (request: ResourceSearchRequest) => void | Promise<void>;
  onSearchQueryChange?: (query: string) => void;
  onImportFiles?: () => void;
  onImportFolder?: () => void;
  onImportUrl?: () => void;
  /**
   * In-library "add by URL": paste a link and file it through the capture
   * pipeline (fetch → clean → Markdown snapshot → index). When provided, the
   * add menu opens this form instead of the plain URL import prompt.
   */
  onCaptureResource?: (input: ResourceCaptureInput) => Promise<ResourceMutationOutcome>;
  /** Learning-focus options (plan stages) offered as the optional binding. */
  captureFocusOptions?: ResourceCaptureFocusOption[];
  /** User-driven organization of one library resource (rename/tags/group). */
  onOrganizeResource?: (
    resourceId: string,
    request: ResourceOrganizeInput,
  ) => Promise<ResourceMutationOutcome>;
  /** Byte-for-byte export of the resource's owned snapshot to this machine. */
  onExportResource?: (resourceId: string) => Promise<ResourceMutationOutcome>;
  /**
   * Real library folders (`GET /library/groups`): the tree the Library's
   * folder section renders and the pickers offer as a target. Absent means
   * the folders section falls back to the folders the resources already
   * describe.
   */
  onListLibraryFolders?: () => Promise<LibraryFolderListResult>;
  /** Create one real folder (`POST /library/groups`). */
  onCreateLibraryFolder?: (path: string) => Promise<ResourceMutationOutcome>;
  /** Rename/move one real folder (`POST /library/groups/rename`). */
  onRenameLibraryFolder?: (path: string, nextPath: string) => Promise<ResourceMutationOutcome>;
  /** Move one real folder to Trash (`DELETE /library/groups`). */
  onDeleteLibraryFolder?: (path: string) => Promise<ResourceMutationOutcome>;
  /** Reveal a downloaded file path through the host's existing file-manager action. */
  onRevealSavedPath?: (path: string) => void;
  onOpenResource?: (resourceId: string) => void;
  onPreviewResource?: (resourceId: string) => void;
  onStartTrainingFromResource?: (resourceId: string) => Promise<ResourceTrainingHandoffResult>;
  onOpenTraining?: () => void;
  onAskCoach?: (resourceIds: string[]) => void;
  onJoinLearning?: (resourceIds: string[]) => void;
  onRefreshResources?: () => void | Promise<void>;
  onDeleteResources?: (resourceIds: string[]) => void | Promise<void>;
  onRestoreResources?: (resourceIds: string[]) => void | Promise<void>;
  onRefreshDeletedResources?: () => void | Promise<void>;
  onChooseWorkspaceRoot?: () => void;
  /**
   * The App owns the cross-view conversation context.  The library reports the
   * resource currently open in the reader (explicit selection only, empty when
   * nothing is open) so switching views does not silently discard context.
   */
  initialResourceContextIds?: string[];
  onResourceSelectionChange?: (
    resourceIds: string[],
    reason?: "selection" | "unmount",
  ) => void;
  onRestoreContextChange?: (context?: ResourceRestoreContext) => void;
  resourceWriteAccess?: ResourceWriteAccess;
  deleteUnavailableReason?: string;
  restoreUnavailableReason?: string;
  orientation?: ResourcesOrientationRecord;
  leftoverNote?: string;
  onOrientationAction?: (action: string) => void;
  onDebugVisibleFacts?: (facts: DebugVisibleResourcesFacts) => void;
  organizationConfirm?: {
    operationCount?: number;
    onConfirm: () => void;
    onCancel: () => void;
  };
  /**
   * Host surface control: when provided (and the host can open editor tabs),
   * the library toolbar renders the "open full width in an editor tab" button.
   */
  onExpandToEditor?: () => void;
  expandToEditorLabel?: string;
}

export interface ResourceRestoreContext {
  surface: "detail" | "sandbox";
  resourceId?: string;
  focusArea?: string;
  sandboxPath?: string;
  previewPath?: string;
  summary?: string;
}

export interface ResourceCaptureInput {
  url: string;
  title?: string;
  focusId?: string;
  /**
   * Also download the original bytes into the library's folder space
   * (`download` + `target_dir` in the capture contract): a PDF lands as the
   * original `.pdf`, a GitHub link lands as the repository directory.
   */
  download?: boolean;
  /** Target folder path inside the library ("" = library root). */
  targetDir?: string;
}

export interface ResourceCaptureFocusOption {
  id: string;
  label: string;
}

export interface ResourceOrganizeInput {
  action: "rename" | "set_tags" | "set_group";
  title?: string;
  tags?: string[];
  group?: string;
}

export interface ResourceMutationOutcome {
  ok: boolean;
  message: string;
  resourceId?: string;
  deduped?: boolean;
  /**
   * Path the requested download landed on (`saved_path` in the capture
   * contract); only set when the pipeline reported one.
   */
  savedPath?: string;
  /**
   * The request was handed to the host, but the workbench could not confirm
   * the result inside its bounded window — reported honestly, never as a
   * silent success.
   */
  unconfirmed?: boolean;
  /**
   * The host owns the remaining interaction (an OS save flow): the message
   * states the request, not a completed write.
   */
  requested?: boolean;
}

export type ResourceSearchRequest = {
  query: string;
  requestId: string;
};

type ResourceTrainingStartPhase = "loading" | ResourceTrainingHandoffResult["outcome"];

type ResourceTrainingStartState = {
  resourceId: string;
  phase: ResourceTrainingStartPhase;
  reason?: ResourceTrainingHandoffResult["reason"];
};

type ResourceTrainingReadiness = {
  tone: "ready" | "unavailable";
  message: string;
  canRefresh: boolean;
};

function localize(language: ComposerLanguage, key: ResourceTextKey): string {
  if (language === "zh-CN") {
    return resourceText[key].zh;
  }
  if (language === "en-US") {
    return resourceText[key].en;
  }
  return resourceTextLocaleOverrides[language][key] ?? resourceText[key].en;
}

function resourceReadOnlyNotice(language: ComposerLanguage): string {
  return localize(language, "readOnlyNotice");
}

function chooseWorkspaceRootLabel(language: ComposerLanguage): string {
  const labels: Record<ComposerLanguage, string> = {
    "zh-CN": "选择 Trainer 工作区",
    "en-US": "Choose Trainer workspace",
    "es-ES": "Elegir espacio de trabajo de Trainer",
    "fr-FR": "Choisir l'espace de travail Trainer",
    "de-DE": "Trainer-Arbeitsbereich auswählen",
    "ja-JP": "Trainer のワークスペースを選択",
    "ko-KR": "Trainer 작업 공간 선택",
    "pt-BR": "Escolher espaço de trabalho do Trainer",
  };
  return labels[language];
}

function restoredSandboxContextTitle(language: ComposerLanguage): string {
  const labels: Record<ComposerLanguage, string> = {
    "zh-CN": "\u6c99\u7bb1\u9884\u89c8\u5df2\u6062\u590d",
    "en-US": "Sandbox preview restored",
    "es-ES": "Vista previa del sandbox restaurada",
    "fr-FR": "Apercu du sandbox restaure",
    "de-DE": "Sandbox-Vorschau wiederhergestellt",
    "ja-JP": "\u30b5\u30f3\u30c9\u30dc\u30c3\u30af\u30b9\u306e\u30d7\u30ec\u30d3\u30e5\u30fc\u3092\u5fa9\u5143",
    "ko-KR": "\uc0cc\ub4dc\ubc15\uc2a4 \ubbf8\ub9ac \ubcf4\uae30\uac00 \ubcf5\uc6d0\ub428",
    "pt-BR": "Previa do sandbox restaurada",
  };
  return labels[language];
}

function localizeCount(language: ComposerLanguage, key: ResourceTextKey, count: number): string {
  const text =
    language === "en-US" && count === 1
      ? englishSingularResourceMutationText[key] ?? localize(language, key)
      : localize(language, key);
  return text.replace("{count}", String(count));
}

/** Fill the `{v}` slot used by the URL/organize/export feedback copy. */
function localizeValue(language: ComposerLanguage, key: ResourceTextKey, value: string): string {
  return localize(language, key).replace("{v}", value);
}

/** Display-safe reason from a thrown value (library write feedback only). */
function thrownReasonText(value: unknown): string {
  return value instanceof Error ? value.message : String(value);
}

const collapseStoragePrefix = "trainer.collapse.";
const resourceCollectionStoragePrefix = `${collapseStoragePrefix}resources.collection.`;

function resourceCollectionPersistenceKey(collectionId: string): string {
  return `${collapseStoragePrefix}resources.collection.${collectionId}`;
}

function readPersistedExpandedCollectionIds(): Set<string> {
  const expanded = new Set<string>();
  try {
    const length = window.localStorage.length;
    for (let index = 0; index < length; index += 1) {
      const key = window.localStorage.key(index);
      if (
        key &&
        key.startsWith(resourceCollectionStoragePrefix) &&
        window.localStorage.getItem(key) === "1"
      ) {
        expanded.add(key.slice(resourceCollectionStoragePrefix.length));
      }
    }
  } catch {
    // Webview localStorage can be unavailable; collections then start collapsed.
  }
  return expanded;
}

function normalizeSearchText(value: string | undefined): string {
  return (value ?? "").trim().toLocaleLowerCase();
}

function sourceChain(resource: ResourceRecord): string[] {
  return Array.from(
    new Set(
      [resource.sourceType, resource.canonicalSource, resource.source]
        .map((value) => value?.trim())
        .filter((value): value is string => Boolean(value)),
    ),
  );
}

/**
 * Internal layout vocabulary must never become user-visible copy: the
 * `local:`/`capture:` scheme tokens and the sandbox intake folders
 * (`sources`, `inbox`, hash context folders, per-resource id folders) are
 * storage facts, not names a learner chose.
 */
const INTERNAL_SOURCE_TOKEN_PATTERN = /^[a-z][a-z\d+.-]*:[a-z][\w.-]*$/i;
const INTERNAL_LAYOUT_SEGMENT_PATTERN =
  /^(sources|inbox|context-[0-9a-f]{8,}|resource-[0-9a-f]{6,})$/i;

function compactSourceLabel(value: string): string {
  const source = value.trim();
  if (!source) {
    return source;
  }

  // A scheme token like `local:pdf` is an internal kind tag, not a source.
  if (INTERNAL_SOURCE_TOKEN_PATTERN.test(source) && !isUrl(source)) {
    return "";
  }

  if (isUrl(source)) {
    try {
      const url = new URL(source);
      const segments = pathSegments(url.pathname);
      return [url.hostname, ...segments.slice(-2)].join("/");
    } catch {
      return source.replace(/^https?:\/\//i, "");
    }
  }

  const segments = pathSegments(source);
  if (segments.length > 1) {
    // A path inside the managed intake layout reduces to the file itself.
    if (segments.slice(0, -1).some((segment) => INTERNAL_LAYOUT_SEGMENT_PATTERN.test(segment))) {
      return segments[segments.length - 1];
    }
    return segments.slice(-2).join("/");
  }
  return source;
}

type ResourceIndexNotice = {
  label: string;
  tone: "pending" | "indexing" | "failed";
};

function resourceIndexNotice(
  resource: ResourceRecord,
  language: ComposerLanguage,
): ResourceIndexNotice | undefined {
  if (resource.indexState === "pending") {
    return { label: localize(language, "pendingIndex"), tone: "pending" };
  }
  if (resource.status === "indexing" || resource.indexState === "indexing") {
    return { label: localize(language, "indexing"), tone: "indexing" };
  }
  if (resource.status === "attention" || resource.indexState === "failed") {
    return { label: localize(language, "indexFailed"), tone: "failed" };
  }
  return undefined;
}

function describeFreshness(freshness: ResourceRecord["freshness"], language: ComposerLanguage): string {
  if (freshness === "fresh") {
    return localize(language, "fresh");
  }
  if (freshness === "stale") {
    return localize(language, "stale");
  }
  return localize(language, "unknown");
}

/** Localized trust wording — the raw `trusted` state value is internal vocabulary. */
function resourceTrust(resource: ResourceRecord, language: ComposerLanguage): string | undefined {
  const trustState = resource.trustState?.trim().toLowerCase();
  if (trustState === "trusted") {
    return localize(language, "trustTrusted");
  }
  if (trustState) {
    return localize(language, "trustUnverified");
  }
  return typeof resource.trustScore === "number"
    ? `${Math.round(resource.trustScore * 100)}%`
    : undefined;
}

const resourceTrainingBlockingFlags = new Set([
  "network_disabled",
  "fetch_failed",
  "blocked_source",
  "no_content",
  "source_conflict",
]);

function resourceTrainingReadiness(
  resource: ResourceRecord,
  language: ComposerLanguage,
  input: {
    canStartTraining: boolean;
    canWriteResources: boolean;
    isBrowserPreview: boolean;
    hasTrainingAction: boolean;
    hasRefreshAction: boolean;
  },
): ResourceTrainingReadiness {
  const canRefresh =
    !resourceCanStartTraining(resource) &&
    input.canWriteResources &&
    !input.isBrowserPreview &&
    input.hasRefreshAction;

  if (resourceCanStartTraining(resource)) {
    if (input.canStartTraining) {
      return { tone: "ready", message: localize(language, "trainingEligible"), canRefresh: false };
    }
    if (!input.canWriteResources) {
      return { tone: "unavailable", message: localize(language, "readOnlyNotice"), canRefresh: false };
    }
    if (input.isBrowserPreview) {
      return {
        tone: "unavailable",
        message: localize(language, "browserPreviewMutationNotice"),
        canRefresh: false,
      };
    }
    if (!input.hasTrainingAction) {
      return { tone: "unavailable", message: localize(language, "unavailable"), canRefresh: false };
    }
    return {
      tone: "unavailable",
      message: resourceTrainingReadinessCopy[language]?.unavailable ?? resourceTrainingReadinessCopy["en-US"].unavailable,
      canRefresh: false,
    };
  }

  const flags = new Set((resource.qualityFlags ?? []).map((flag) => flag.trim().toLowerCase()));
  const reason =
    resource.status === "indexing" || resource.indexState !== "indexed"
      ? "indexing"
      : resource.freshness === "stale"
        ? "stale"
        : flags.has("fetch_failed") || flags.has("blocked_source") || flags.has("no_content")
          ? "source"
          : !resourceHasTrainingTrust(resource)
            ? "trust"
            : "unavailable";
  return {
    tone: "unavailable",
    message: resourceTrainingReadinessCopy[language]?.[reason] ?? resourceTrainingReadinessCopy["en-US"][reason],
    canRefresh,
  };
}

function resourceTrainingHandoffFailureMessage(
  language: ComposerLanguage,
  reason: ResourceTrainingHandoffResult["reason"],
): string | undefined {
  const copy: Record<ComposerLanguage, Partial<Record<NonNullable<ResourceTrainingHandoffResult["reason"]>, string>>> = {
    "zh-CN": {
      resource_missing: "\u8fd9\u4efd\u8d44\u6599\u5df2\u4e0d\u5728\u5f53\u524d\u8d44\u6599\u5e93\u4e2d\u3002\u5237\u65b0\u8d44\u6599\u5e93\u540e\u91cd\u65b0\u9009\u62e9\u5b83\u3002",
      resource_needs_refresh: "\u8fd9\u4efd\u8d44\u6599\u8fd8\u9700\u8981\u5b8c\u6210\u7d22\u5f15\u6216\u66f4\u65b0\u3002\u5237\u65b0\u7d22\u5f15\u540e\u518d\u8bd5\u3002",
      connection: "\u6a21\u578b\u8fde\u63a5\u6682\u65f6\u4e0d\u53ef\u7528\u3002\u5230\u201c\u8bbe\u7f6e\u201d\u68c0\u67e5\u8fde\u63a5\u540e\u518d\u8bd5\u3002",
      unavailable: "\u8bad\u7ec3\u5361\u6682\u65f6\u6ca1\u80fd\u51c6\u5907\u597d\u3002\u5237\u65b0\u8d44\u6599\u540e\u518d\u8bd5\u3002",
    },
    "en-US": {
      resource_missing: "This resource is no longer in the library. Refresh Resources, then select it again.",
      resource_needs_refresh: "This resource still needs indexing or an update. Refresh the index and try again.",
      connection: "The model connection is unavailable right now. Check it in Settings, then try again.",
      unavailable: "The training card could not be prepared yet. Refresh Resources and try again.",
    },
    "es-ES": {
      resource_missing: "Este recurso ya no está en la biblioteca. Actualiza Recursos y vuelve a seleccionarlo.",
      resource_needs_refresh: "Este recurso todavía necesita indexarse o actualizarse. Actualiza el índice e inténtalo de nuevo.",
      connection: "La conexión con el modelo no está disponible ahora. Revísala en Ajustes e inténtalo de nuevo.",
      unavailable: "La tarjeta de práctica aún no se pudo preparar. Actualiza Recursos e inténtalo de nuevo.",
    },
    "fr-FR": {
      resource_missing: "Cette ressource n'est plus dans la bibliothèque. Actualisez Ressources, puis resélectionnez-la.",
      resource_needs_refresh: "Cette ressource doit encore être indexée ou mise à jour. Actualisez l'index et réessayez.",
      connection: "La connexion au modèle est indisponible pour le moment. Vérifiez-la dans Paramètres, puis réessayez.",
      unavailable: "La carte d'exercice n'a pas encore pu être préparée. Actualisez Ressources et réessayez.",
    },
    "de-DE": {
      resource_missing: "Diese Ressource ist nicht mehr in der Bibliothek. Aktualisiere Ressourcen und wähle sie erneut.",
      resource_needs_refresh: "Diese Ressource muss noch indiziert oder aktualisiert werden. Aktualisiere den Index und versuche es erneut.",
      connection: "Die Modellverbindung ist gerade nicht verfügbar. Prüfe sie in den Einstellungen und versuche es erneut.",
      unavailable: "Die Übungskarte konnte noch nicht vorbereitet werden. Aktualisiere Ressourcen und versuche es erneut.",
    },
    "ja-JP": {
      resource_missing: "この資料はもう資料ライブラリにありません。資料を更新してから、もう一度選んでください。",
      resource_needs_refresh: "この資料はまだインデックスまたは更新が必要です。インデックスを更新してからもう一度お試しください。",
      connection: "モデル接続が現在使用できません。設定で確認してからもう一度お試しください。",
      unavailable: "トレーニングカードをまだ準備できませんでした。資料を更新してもう一度お試しください。",
    },
    "ko-KR": {
      resource_missing: "이 자료는 더 이상 자료 라이브러리에 없습니다. 자료를 새로 고친 후 다시 선택해 주세요.",
      resource_needs_refresh: "이 자료는 아직 인덱싱 또는 업데이트가 필요합니다. 인덱스를 새로 고친 후 다시 시도해 주세요.",
      connection: "모델 연결을 지금 사용할 수 없습니다. 설정에서 확인한 후 다시 시도해 주세요.",
      unavailable: "훈련 카드를 아직 준비하지 못했습니다. 자료를 새로 고친 후 다시 시도해 주세요.",
    },
    "pt-BR": {
      resource_missing: "Este recurso não está mais na biblioteca. Atualize Recursos e selecione-o novamente.",
      resource_needs_refresh: "Este recurso ainda precisa ser indexado ou atualizado. Atualize o índice e tente novamente.",
      connection: "A conexão com o modelo está indisponível no momento. Verifique em Configurações e tente novamente.",
      unavailable: "Não foi possível preparar o cartão de prática ainda. Atualize Recursos e tente novamente.",
    },
  };
  return reason ? copy[language]?.[reason] ?? copy["en-US"][reason] : undefined;
}

function resourceHasTrainingTrust(resource: ResourceRecord): boolean {
  const trustState = resource.trustState?.trim().toLowerCase();
  if (trustState && trustState !== "trusted") {
    return false;
  }
  const qualityFlags = (resource.qualityFlags ?? []).filter((flag) => flag.trim().length > 0);
  if (qualityFlags.length > 0) {
    return false;
  }
  return typeof resource.trustScore === "number" && resource.trustScore >= 0.75;
}

function resourceCanStartTraining(resource: ResourceRecord): boolean {
  const hasBlockingFlag = (resource.qualityFlags ?? []).some((flag) =>
    resourceTrainingBlockingFlags.has(flag.trim().toLowerCase()),
  );
  return (
    resource.status === "ready" &&
    resource.indexState === "indexed" &&
    resourceHasTrainingTrust(resource) &&
    resource.freshness === "fresh" &&
    !hasBlockingFlag
  );
}

function resourceTrainingStartCopy(
  language: ComposerLanguage,
  phase?: ResourceTrainingStartPhase,
): string {
  const copy: Record<ComposerLanguage, Record<ResourceTrainingStartPhase, string>> = {
    "zh-CN": {
      loading: "正在准备训练卡...",
      ready: "训练卡已准备好。",
      blocked: "这份资料暂时还不能生成训练卡。请先完成整理或更新。",
      "not-current": "训练卡已准备好，但现在有更优先的训练。先完成当前训练即可。",
      failed: "暂时无法准备训练卡，请稍后再试。",
    },
    "en-US": {
      loading: "Preparing a training card...",
      ready: "The training card is ready.",
      blocked: "This resource is not ready for a training card yet. Finish processing or refresh it first.",
      "not-current": "The card is ready, but another training card needs attention first.",
      failed: "The training card could not be prepared. Try again shortly.",
    },
    "es-ES": {
      loading: "Preparando una tarjeta de entrenamiento...",
      ready: "La tarjeta de entrenamiento esta lista.",
      blocked: "Este recurso aun no esta listo para una tarjeta. Termina de procesarlo o actualizalo primero.",
      "not-current": "La tarjeta esta lista, pero primero hay otra practica pendiente.",
      failed: "No se pudo preparar la tarjeta. Intentalo de nuevo en un momento.",
    },
    "fr-FR": {
      loading: "Preparation de la carte d'entrainement...",
      ready: "La carte d'entrainement est prete.",
      blocked: "Cette ressource n'est pas encore prete pour une carte. Terminez son traitement ou actualisez-la.",
      "not-current": "La carte est prete, mais une autre pratique est prioritaire.",
      failed: "La carte n'a pas pu etre preparee. Reessayez dans un instant.",
    },
    "de-DE": {
      loading: "Trainingskarte wird vorbereitet...",
      ready: "Die Trainingskarte ist bereit.",
      blocked: "Dieses Material ist noch nicht bereit fur eine Trainingskarte. Bitte erst verarbeiten oder aktualisieren.",
      "not-current": "Die Karte ist bereit, aber eine andere Ubung hat zuerst Vorrang.",
      failed: "Die Trainingskarte konnte nicht vorbereitet werden. Bitte gleich noch einmal versuchen.",
    },
    "ja-JP": {
      loading: "トレーニングカードを準備しています...",
      ready: "トレーニングカードの準備ができました。",
      blocked: "この資料はまだトレーニングカードに使えません。処理または更新を先に完了してください。",
      "not-current": "カードは準備できましたが、先に取り組む練習があります。",
      failed: "トレーニングカードを準備できませんでした。しばらくしてからもう一度お試しください。",
    },
    "ko-KR": {
      loading: "훈련 카드를 준비하고 있습니다...",
      ready: "훈련 카드가 준비되었습니다.",
      blocked: "이 자료는 아직 훈련 카드에 사용할 수 없습니다. 처리하거나 새로 고친 뒤 다시 시도하세요.",
      "not-current": "카드는 준비되었지만 먼저 진행할 훈련이 있습니다.",
      failed: "훈련 카드를 준비하지 못했습니다. 잠시 후 다시 시도하세요.",
    },
    "pt-BR": {
      loading: "Preparando um cartao de treinamento...",
      ready: "O cartao de treinamento esta pronto.",
      blocked: "Este recurso ainda nao esta pronto para um cartao. Conclua o processamento ou atualize primeiro.",
      "not-current": "O cartao esta pronto, mas ha outro treino mais urgente primeiro.",
      failed: "Nao foi possivel preparar o cartao. Tente novamente em instantes.",
    },
  };
  if (!phase) {
    return localize(language, "createReviewCard");
  }
  return copy[language][phase];
}

function resourcePreviewHeading(language: ComposerLanguage): string {
  const labels: Record<ComposerLanguage, string> = {
    "zh-CN": "\u9884\u89c8",
    "en-US": "Preview",
    "es-ES": "Vista previa",
    "fr-FR": "Apercu",
    "de-DE": "Vorschau",
    "ja-JP": "\u30d7\u30ec\u30d3\u30e5\u30fc",
    "ko-KR": "\ubbf8\ub9ac \ubcf4\uae30",
    "pt-BR": "Previa",
  };
  return labels[language];
}

function resourcePreviewTierLabel(
  tier: NonNullable<ResourceRecord["previewTier"]>,
  language: ComposerLanguage,
): string {
  const labels: Record<ComposerLanguage, Record<NonNullable<ResourceRecord["previewTier"]>, string>> = {
    "zh-CN": {
      rich: "Tier A \u00b7 \u5bcc\u9884\u89c8",
      converted: "Tier B \u00b7 \u8f6c\u6362\u9884\u89c8",
      metadata: "Tier C \u00b7 \u5143\u6570\u636e\u56de\u9000",
    },
    "en-US": {
      rich: "Tier A \u00b7 Rich preview",
      converted: "Tier B \u00b7 Converted preview",
      metadata: "Tier C \u00b7 Metadata fallback",
    },
    "es-ES": {
      rich: "Nivel A \u00b7 Vista enriquecida",
      converted: "Nivel B \u00b7 Vista convertida",
      metadata: "Nivel C \u00b7 Metadatos",
    },
    "fr-FR": {
      rich: "Niveau A \u00b7 Apercu enrichi",
      converted: "Niveau B \u00b7 Apercu converti",
      metadata: "Niveau C \u00b7 Metadonnees",
    },
    "de-DE": {
      rich: "Stufe A \u00b7 Umfangreiche Vorschau",
      converted: "Stufe B \u00b7 Konvertierte Vorschau",
      metadata: "Stufe C \u00b7 Metadaten",
    },
    "ja-JP": {
      rich: "Tier A \u00b7 \u30ea\u30c3\u30c1\u30d7\u30ec\u30d3\u30e5\u30fc",
      converted: "Tier B \u00b7 \u5909\u63db\u30d7\u30ec\u30d3\u30e5\u30fc",
      metadata: "Tier C \u00b7 \u30e1\u30bf\u30c7\u30fc\u30bf",
    },
    "ko-KR": {
      rich: "Tier A \u00b7 \ud48d\ubd80\ud55c \ubbf8\ub9ac \ubcf4\uae30",
      converted: "Tier B \u00b7 \ubcc0\ud658 \ubbf8\ub9ac \ubcf4\uae30",
      metadata: "Tier C \u00b7 \uba54\ud0c0\ub370\uc774\ud130",
    },
    "pt-BR": {
      rich: "Nivel A \u00b7 Previa rica",
      converted: "Nivel B \u00b7 Previa convertida",
      metadata: "Nivel C \u00b7 Metadados",
    },
  };
  return labels[language][tier];
}

function resourcePreviewMode(resource: ResourceRecord, language: ComposerLanguage): string | undefined {
  const tier = resource.previewTier ? resourcePreviewTierLabel(resource.previewTier, language) : undefined;
  const kind = resource.previewKind?.trim();
  const details = [tier, kind].filter((value): value is string => Boolean(value));
  return details.length > 0 ? details.join(" \u00b7 ") : undefined;
}

function resourcePreviewSummary(resource: ResourceRecord): string | undefined {
  const source = resource.status === "attention"
    ? resource.summary?.trim() || resource.matchSummary?.trim()
    : resource.matchSummary?.trim() || resource.summary?.trim();
  if (!source) {
    return undefined;
  }
  return source.replace(/\s+/g, " ").slice(0, 480);
}

function resourceReuseSummary(language: ComposerLanguage): string {
  const labels: Record<ComposerLanguage, string> = {
    "zh-CN": "可作为 Coach 上下文、Plan 证据或 Training 学习素材。",
    "en-US": "Use it as Coach context, Plan evidence, or Training material.",
    "es-ES": "Sirve como contexto de Coach, evidencia de Plan o material de Training.",
    "fr-FR": "Utilisez-le comme contexte Coach, preuve de Plan ou materiel de Training.",
    "de-DE": "Nutze es als Coach-Kontext, Plan-Beleg oder Training-Material.",
    "ja-JP": "Coach の文脈、Plan の証拠、Training の素材として使えます。",
    "ko-KR": "Coach 맥락, Plan 증거, Training 자료로 사용할 수 있습니다.",
    "pt-BR": "Use como contexto do Coach, evidencia do Plan ou material de Training.",
  };

  return labels[language];
}

function deletedResourceId(resource: DeletedResource): string | undefined {
  return resource.resourceId.trim() || undefined;
}

function isDeletedResourceRecoverable(resource: DeletedResource): boolean {
  return Boolean(deletedResourceId(resource)) && resource.recoverable;
}

type ResourceTreeNode = {
  id: string;
  label: string;
  kind: "collection" | "resource";
  collectionKind?: "directory" | "logical";
  resource?: ResourceRecord;
  children: ResourceTreeNode[];
};

type ResourceMutationKind = "delete" | "restore";

type ResourceMutationResult = {
  kind: ResourceMutationKind;
  resourceIds: string[];
  status: "failed" | "succeeded";
};

type ResourceSearchRequestState =
  | { phase: "idle"; requestId?: undefined }
  | { phase: "debouncing" | "loading"; requestId?: string }
  | { phase: "failed"; requestId?: string };

type SandboxNodePath = {
  normalizedPaths: string[];
  relativeSegments: string[];
};

const collectionSegmentPrefix = "__collection__:";
const hiddenCollectionRootSegments = new Set(["trainer", ".trainer", ".trainer-sandbox", "sandbox"]);

function normalizePath(value: string | undefined): string {
  return String(value ?? "")
    .trim()
    .replace(/\\/g, "/")
    .replace(/\/+$/g, "");
}

function pathSegments(value: string | undefined): string[] {
  return String(value ?? "")
    .trim()
    .replace(/\\/g, "/")
    .replace(/^[a-z]:\//i, "")
    .replace(/^\/+/, "")
    .split("/")
    .map((segment) => segment.trim())
    .filter((segment) => segment && segment !== "." && segment !== "..");
}

function isRelativeFilePath(value: string | undefined): boolean {
  const path = String(value ?? "").trim().replace(/\\/g, "/");
  return Boolean(path) && !/^(?:[a-z]:\/|\/|[a-z][a-z\d+.-]*:\/\/)/i.test(path);
}

function collectionPathSegments(
  value: string | undefined,
  collectionRoot: string | undefined,
): string[] {
  const collectionPath = String(value ?? "").trim().replace(/\\/g, "/");
  if (
    !String(collectionRoot ?? "").trim() ||
    !isRelativeFilePath(collectionPath) ||
    collectionPath.split("/").some((segment) => {
      const trimmedSegment = segment.trim();
      return trimmedSegment === "." || trimmedSegment === "..";
    })
  ) {
    return [];
  }
  // The intake layout (`sources/inbox/<resource-id>`, hash context folders) is
  // storage, not filing; it never becomes a visible group on any surface.
  return visibleCollectionSegments(pathSegments(collectionPath));
}

function trimHiddenCollectionRoots(segments: string[]): string[] {
  const privateRootIndex = segments.findIndex((segment) => {
    const normalized = normalizePath(segment);
    return normalized === ".trainer" || normalized === ".trainer-sandbox";
  });
  const candidateSegments = privateRootIndex >= 0 ? segments.slice(privateRootIndex + 1) : segments;
  let firstVisibleSegment = 0;
  while (
    firstVisibleSegment < candidateSegments.length &&
    hiddenCollectionRootSegments.has(normalizePath(candidateSegments[firstVisibleSegment]))
  ) {
    firstVisibleSegment += 1;
  }
  return candidateSegments.slice(firstVisibleSegment);
}

function relativeSandboxPath(value: string | undefined, sandboxRoot: string | undefined): string | undefined {
  const normalizedValue = normalizePath(value);
  const normalizedRoot = normalizePath(sandboxRoot);
  if (!normalizedValue || !normalizedRoot) {
    return undefined;
  }
  if (normalizedValue === normalizedRoot) {
    return "";
  }
  if (normalizedValue.startsWith(`${normalizedRoot}/`)) {
    return normalizedValue.slice(normalizedRoot.length + 1);
  }
  return undefined;
}

function compactSandboxPath(value: string | undefined, sandboxRoot: string | undefined): string | undefined {
  const normalizedValue = normalizePath(value);
  if (!normalizedValue) {
    return undefined;
  }

  const relativePath = relativeSandboxPath(normalizedValue, sandboxRoot);
  const candidate = relativePath ?? pathSegments(normalizedValue).slice(-3).join("/");
  if (!candidate) {
    return undefined;
  }

  const segments = candidate.split("/").filter(Boolean);
  const shortened = segments.length > 3 ? `.../${segments.slice(-3).join("/")}` : segments.join("/");
  return shortened.length > 64 ? `...${shortened.slice(-61)}` : shortened;
}

function toSandboxNodePaths(
  nodes: SandboxState["nodes"] | undefined,
  sandboxRoot: string | undefined,
): SandboxNodePath[] {
  if (!Array.isArray(nodes)) {
    return [];
  }

  return nodes.flatMap((node) => {
    const path = typeof node.path === "string" ? node.path : undefined;
    const relativePath = typeof node.relativePath === "string" ? node.relativePath : undefined;
    const name = typeof node.name === "string" ? node.name : undefined;
    const nodeKind = typeof node.nodeKind === "string" ? node.nodeKind : undefined;
    const type = typeof node.type === "string" ? node.type : undefined;
    const isDirectory = nodeKind === "directory" || type === "folder";
    const explicitRelativePath = isRelativeFilePath(relativePath) ? relativePath : undefined;
    const derivedRelativePath = relativeSandboxPath(path, sandboxRoot);
    const nodeRelativePath = explicitRelativePath ?? derivedRelativePath;
    const relativeSegments = trimHiddenCollectionRoots(pathSegments(nodeRelativePath));
    const normalizedPaths = [normalizePath(path), normalizePath(relativePath), normalizePath(nodeRelativePath)]
      .filter((candidate): candidate is string => Boolean(candidate));

    if (isDirectory || !nodeRelativePath || relativeSegments.length === 0 || normalizedPaths.length === 0) {
      return [];
    }

    return [{ normalizedPaths, relativeSegments }];
  });
}

function isUrl(value: string | undefined): boolean {
  return /^https?:\/\//i.test(String(value ?? "").trim());
}

function sourcePathSegments(value: string | undefined, sandboxRoot: string | undefined): string[] {
  const sandboxRelative = relativeSandboxPath(value, sandboxRoot);
  if (sandboxRelative !== undefined) {
    return pathSegments(sandboxRelative);
  }

  const source = String(value ?? "").trim();
  if (isUrl(source)) {
    try {
      const url = new URL(source);
      return [url.hostname, ...pathSegments(url.pathname)];
    } catch {
      return pathSegments(source.replace(/^https?:\/\//i, ""));
    }
  }

  return pathSegments(source);
}

function fallbackCollectionSegments(
  resource: ResourceRecord,
  sandboxRoot: string | undefined,
): string[] {
  const sandboxPath = resource.sandboxPath?.trim();
  const source = sandboxPath ?? resource.canonicalSource ?? resource.source;
  const sourceSegments = sourcePathSegments(source, sandboxRoot);
  const isSandboxResource = relativeSandboxPath(source, sandboxRoot) !== undefined;

  if (isSandboxResource && sourceSegments.length > 1) {
    return sourceSegments.slice(0, -1);
  }

  if (sandboxPath) {
    return [`${collectionSegmentPrefix}imported`];
  }

  if (isUrl(source)) {
    return [
      `${collectionSegmentPrefix}web-snapshots`,
      ...sourceSegments.slice(0, Math.max(0, sourceSegments.length - 1)),
    ];
  }

  if (sourceSegments.length > 1) {
    return [
      `${collectionSegmentPrefix}references`,
      ...sourceSegments.slice(Math.max(0, sourceSegments.length - 3), -1),
    ];
  }

  return [
    resource.kind === "url"
      ? `${collectionSegmentPrefix}web-snapshots`
      : `${collectionSegmentPrefix}imported`,
  ];
}

function collectionLabel(segment: string, language: ComposerLanguage): string {
  if (segment === `${collectionSegmentPrefix}web-snapshots`) {
    return localize(language, "webSnapshots");
  }
  if (segment === `${collectionSegmentPrefix}references`) {
    return localize(language, "references");
  }
  if (segment === `${collectionSegmentPrefix}imported`) {
    return localize(language, "imported");
  }
  // r1-g2-1: one casing rule for folder-named groups — "Docs"/"docs"/"knowledge"
  // all display with a single leading capital instead of three rival styles.
  const trimmed = segment.trim().replace(/\s+/g, " ");
  return trimmed.length > 0
    ? trimmed.charAt(0).toLocaleUpperCase() + trimmed.slice(1)
    : trimmed;
}

function resourcePathCandidates(resource: ResourceRecord, sandboxRoot: string | undefined): string[] {
  const values = [resource.sandboxPath, resource.canonicalSource, resource.source];
  return Array.from(
    new Set(
      values.flatMap((value) => {
        const normalized = normalizePath(value);
        const sandboxRelative = relativeSandboxPath(value, sandboxRoot);
        return [normalized, normalizePath(sandboxRelative)].filter(Boolean);
      }),
    ),
  );
}

function resourceTreeSegments(
  resource: ResourceRecord,
  sandboxRoot: string | undefined,
  sandboxNodes: SandboxNodePath[],
): string[] {
  const logicalCollectionSegments = collectionPathSegments(
    resource.collectionPath,
    resource.collectionRoot,
  );
  if (logicalCollectionSegments.length > 0) {
    return visibleCollectionSegments(logicalCollectionSegments.slice(0, -1));
  }

  const candidates = new Set(resourcePathCandidates(resource, sandboxRoot));
  const matchingNode = sandboxNodes.find((node) => node.normalizedPaths.some((path) => candidates.has(path)));
  if (matchingNode) {
    return visibleCollectionSegments(matchingNode.relativeSegments.slice(0, -1));
  }
  return visibleCollectionSegments(fallbackCollectionSegments(resource, sandboxRoot));
}

/**
 * Internal intake layout (`sources/inbox/<resource-id>`, hash context
 * folders) describes where the bytes live, not how the learner filed the
 * material; those segments never become user-visible groups.
 */
function visibleCollectionSegments(segments: string[]): string[] {
  return segments.filter((segment) => !INTERNAL_LAYOUT_SEGMENT_PATTERN.test(segment.trim()));
}

function resourceTreeCollectionKind(
  resource: ResourceRecord,
  sandboxRoot: string | undefined,
  sandboxNodes: SandboxNodePath[],
): "directory" | "logical" {
  if (collectionPathSegments(resource.collectionPath, resource.collectionRoot).length > 0) {
    return "logical";
  }

  const candidates = new Set(resourcePathCandidates(resource, sandboxRoot));
  return sandboxNodes.some((node) => node.normalizedPaths.some((path) => candidates.has(path)))
    ? "directory"
    : "logical";
}

function sortResourceTree(nodes: ResourceTreeNode[]): ResourceTreeNode[] {
  return nodes
    .map((node) => ({ ...node, children: sortResourceTree(node.children) }))
    .sort((left, right) => {
      if (left.kind !== right.kind) {
        return left.kind === "collection" ? -1 : 1;
      }
      return left.label.localeCompare(right.label, undefined, { sensitivity: "base" });
    });
}

function buildResourceTree(
  resources: ResourceRecord[],
  sandboxState: SandboxState | undefined,
  language: ComposerLanguage,
): ResourceTreeNode[] {
  const root: ResourceTreeNode = { id: "root", label: "", kind: "collection", children: [] };
  const sandboxRoot = sandboxState?.sandboxRootPath ?? sandboxState?.rootPath;
  const sandboxNodes = toSandboxNodePaths(sandboxState?.nodes, sandboxRoot);
  // r1-g2-1: one leaf per resource id — the same resource arriving twice must
  // not inflate a group badge above the header total.
  const seenResourceIds = new Set<string>();

  for (const resource of resources) {
    if (seenResourceIds.has(resource.id)) {
      continue;
    }
    seenResourceIds.add(resource.id);
    const segments = resourceTreeSegments(resource, sandboxRoot, sandboxNodes);
    const collectionKind = resourceTreeCollectionKind(resource, sandboxRoot, sandboxNodes);
    let parent = root;
    const idSegments: string[] = [];

    for (const segment of segments) {
      const collectionSegment = segment.trim();
      if (!collectionSegment) {
        continue;
      }
      idSegments.push(encodeURIComponent(collectionSegment));
      const id = `collection:${collectionKind}:${idSegments.join("/")}`;
      let child = parent.children.find((node) => node.id === id);
      if (!child) {
        child = {
          id,
          label: collectionLabel(segment, language),
          kind: "collection",
          collectionKind,
          children: [],
        };
        parent.children.push(child);
      }
      parent = child;
    }

    parent.children.push({
      id: `resource:${resource.id}`,
      label: resource.title,
      kind: "resource",
      resource,
      children: [],
    });
  }

  return compactUnaryCollections(pruneEmptyCollections(sortResourceTree(root.children)));
}

/** r1-g2-1: groups that expand to nothing are removed, not rendered empty. */
function pruneEmptyCollections(nodes: ResourceTreeNode[]): ResourceTreeNode[] {
  return nodes.flatMap((node) => {
    if (node.kind !== "collection") {
      return [node];
    }
    const children = pruneEmptyCollections(node.children);
    return children.length > 0 ? [{ ...node, children }] : [];
  });
}

function compactUnaryCollections(nodes: ResourceTreeNode[]): ResourceTreeNode[] {
  return nodes.map((node) => compactUnaryCollection(node));
}

function compactUnaryCollection(node: ResourceTreeNode): ResourceTreeNode {
  if (node.kind !== "collection") {
    return node;
  }
  let compacted: ResourceTreeNode = {
    ...node,
    children: compactUnaryCollections(node.children),
  };
  while (
    compacted.kind === "collection" &&
    compacted.children.length === 1 &&
    compacted.children[0].kind === "collection"
  ) {
    const only = compacted.children[0];
    compacted = {
      ...only,
      id: compacted.id,
      label: `${compacted.label} / ${only.label}`,
      children: only.children,
    };
  }
  return compacted;
}

function filterResourceTree(
  nodes: ResourceTreeNode[],
  visibleResourceIds: Set<string>,
): ResourceTreeNode[] {
  return nodes.flatMap((node) => {
    if (node.kind === "resource") {
      return node.resource && visibleResourceIds.has(node.resource.id) ? [node] : [];
    }

    const children = filterResourceTree(node.children, visibleResourceIds);
    return children.length > 0 ? [{ ...node, children }] : [];
  });
}

function findResourceAncestorCollectionIds(
  nodes: ResourceTreeNode[],
  resourceId: string,
  ancestors: string[] = [],
): string[] | undefined {
  for (const node of nodes) {
    if (node.kind === "resource" && node.resource?.id === resourceId) {
      return ancestors;
    }
    if (node.kind === "collection") {
      const match = findResourceAncestorCollectionIds(node.children, resourceId, [...ancestors, node.id]);
      if (match) {
        return match;
      }
    }
  }
  return undefined;
}

function firstResourceAncestorCollectionIds(
  nodes: ResourceTreeNode[],
  ancestors: string[] = [],
): string[] | undefined {
  for (const node of nodes) {
    if (node.kind === "resource") {
      return ancestors;
    }
    const match = firstResourceAncestorCollectionIds(node.children, [...ancestors, node.id]);
    if (match) {
      return match;
    }
  }
  return undefined;
}

function collectionIds(nodes: ResourceTreeNode[]): string[] {
  return nodes.flatMap((node) =>
    node.kind === "collection" ? [node.id, ...collectionIds(node.children)] : [],
  );
}

function resourceIdsInTreeNode(node: ResourceTreeNode): string[] {
  if (node.kind === "resource") {
    return node.resource ? [node.resource.id] : [];
  }
  // r1-g2-1: badges count distinct resources, so the sum of the group badges
  // equals the header total even if a resource id appears in two subtrees.
  return Array.from(new Set(node.children.flatMap(resourceIdsInTreeNode)));
}

function visibleTreeItemIds(nodes: ResourceTreeNode[], expandedIds: Set<string>): string[] {
  return nodes.flatMap((node) => {
    if (node.kind !== "collection" || !expandedIds.has(node.id)) {
      return [node.id];
    }
    return [node.id, ...visibleTreeItemIds(node.children, expandedIds)];
  });
}

function ResourceKindIcon({ kind }: { kind: ResourceRecord["kind"] | undefined }) {
  const Icon =
    kind === "url" ? LinkIcon : kind === "pdf" || kind === "image" || kind === "video" ? PageIcon : FileIcon;
  return <Icon size={12} aria-hidden="true" />;
}

interface ResourceTreeItemProps {
  node: ResourceTreeNode;
  depth: number;
  parentId?: string;
  language: ComposerLanguage;
  expandedIds: Set<string>;
  selectedResourceId: string | null;
  activeTreeItemId: string | null;
  onToggle: (id: string) => void;
  onSelect: (resource: ResourceRecord) => void;
  onOpen: (resource: ResourceRecord) => void;
  onActiveTreeItemChange: (id: string) => void;
  onMoveTreeFocus: (id: string) => void;
}

function ResourceTreeItem({
  node,
  depth,
  parentId,
  language,
  expandedIds,
  selectedResourceId,
  activeTreeItemId,
  onToggle,
  onSelect,
  onOpen,
  onActiveTreeItemChange,
  onMoveTreeFocus,
}: ResourceTreeItemProps) {
  if (node.kind === "resource" && node.resource) {
    const isSelected = selectedResourceId === node.resource.id;
    return (
      <div
        className={`resources-library-tree__node resources-library-tree__node--resource resources-row ${
          isSelected ? "is-selected" : ""
        }`}
        role="treeitem"
        aria-level={depth + 1}
        aria-label={node.resource.title}
        aria-current={isSelected ? "true" : undefined}
        data-resource-tree-item-id={node.id}
        tabIndex={activeTreeItemId === node.id ? 0 : -1}
        style={{
          paddingInlineStart: `calc(var(--trainer-space-2) + ${depth} * var(--trainer-space-4))`,
        }}
        title={node.resource.title}
        onFocus={() => onActiveTreeItemChange(node.id)}
        onClick={() => onSelect(node.resource!)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            onOpen(node.resource!);
          }
          if (event.key === "ArrowLeft" && parentId) {
            event.preventDefault();
            onMoveTreeFocus(parentId);
          }
        }}
        aria-keyshortcuts="Enter"
      >
        <span className="resources-library-tree__indent" aria-hidden="true" />
        <span className="resources-library-tree__kind" aria-hidden="true">
          <ResourceKindIcon kind={node.resource.kind} />
        </span>
        <span className="resources-library-tree__copy">
          <strong>{node.resource.title}</strong>
        </span>
      </div>
    );
  }

  const isExpanded = expandedIds.has(node.id);
  const descendantResourceIds = resourceIdsInTreeNode(node);
  const firstChildId = node.children[0]?.id;
  const isLogicalCollection = node.collectionKind === "logical";
  // r2-g2-0: a group whose count lives entirely in nested subgroups must not
  // read as empty once expanded — say where the items are.
  const directResourceCount = node.children.filter((child) => child.kind === "resource").length;
  const nestedResourceCount = descendantResourceIds.length - directResourceCount;
  const showNestedItemsNote =
    isExpanded && directResourceCount === 0 && nestedResourceCount > 0;
  const collectionDescription = isLogicalCollection
    ? `${localize(language, "logicalCollection")}: ${node.label}`
    : node.label;
  return (
    <div
      className="resources-library-tree__item"
      role="group"
      aria-label={node.label}
      aria-description={isLogicalCollection ? localize(language, "logicalCollection") : undefined}
      data-resource-tree-item-id={node.id}
      tabIndex={-1}
      onKeyDown={(event) => {
        if (event.key === "ArrowRight") {
          event.preventDefault();
          event.stopPropagation();
          if (!isExpanded) {
            onToggle(node.id);
          } else if (firstChildId) {
            onMoveTreeFocus(firstChildId);
          }
        }
        if (event.key === "ArrowLeft") {
          event.preventDefault();
          event.stopPropagation();
          if (isExpanded) {
            onToggle(node.id);
          } else if (parentId) {
            onMoveTreeFocus(parentId);
          }
        }
      }}
    >
      <CollapseSection
        level={depth === 0 ? 1 : depth === 1 ? 2 : 3}
        persistenceKey={resourceCollectionPersistenceKey(node.id)}
        title={
          <span className="resources-library-tree__collection-label" title={collectionDescription}>
            <FolderIcon size={12} aria-hidden="true" />
            <span>{node.label}</span>
          </span>
        }
        subtitle={undefined}
        badge={
          <span className="resources-library-tree__count">{descendantResourceIds.length}</span>
        }
        open={isExpanded}
        onToggle={() => onToggle(node.id)}
      >
        {showNestedItemsNote ? (
          <p className="resources-library-tree__nested-note" data-resource-nested-note="true">
            {localizeCount(language, "nestedInSubgroups", nestedResourceCount)}
          </p>
        ) : null}
        {isExpanded
          ? node.children.map((child) => (
              <ResourceTreeItem
                key={child.id}
                node={child}
                depth={depth + 1}
                parentId={node.id}
                language={language}
                expandedIds={expandedIds}
                selectedResourceId={selectedResourceId}
                activeTreeItemId={activeTreeItemId}
                onToggle={onToggle}
                onSelect={onSelect}
                onOpen={onOpen}
                onActiveTreeItemChange={onActiveTreeItemChange}
                onMoveTreeFocus={onMoveTreeFocus}
              />
            ))
          : null}
      </CollapseSection>
    </div>
  );
}

/**
 * A captured snapshot stores its metadata as YAML-style front matter; the
 * reader renders the body, and the envelope belongs to the source line.
 */
function previewBodyWithoutCaptureFrontmatter(body: string): string {
  const lines = body.replace(/^\uFEFF/, "").split(/\r?\n/);
  let index = 0;
  while (index < lines.length && !lines[index]?.trim()) {
    index += 1;
  }
  if (lines[index]?.trim() !== "---") {
    return body;
  }
  const openFence = index;
  for (let cursor = openFence + 1; cursor < Math.min(lines.length, openFence + 64); cursor += 1) {
    if (lines[cursor]?.trim() === "---") {
      return lines.slice(cursor + 1).join("\n").replace(/^\r?\n+/, "");
    }
  }
  return body;
}

function previewBodyWithoutDuplicateTitle(body: string, title: string): string {
  const withoutFrontmatter = previewBodyWithoutCaptureFrontmatter(body);
  const trimmed = withoutFrontmatter.trim();
  const heading = trimmed.match(/^#\s+(.+?)(?:\r?\n|$)/);
  if (!heading) {
    return withoutFrontmatter;
  }
  if (heading[1].trim() !== title.trim()) {
    return withoutFrontmatter;
  }
  return trimmed.slice(heading[0].length).trimStart();
}

function pickInitialResourceId(
  resources: ResourceRecord[],
  initialIds: string[],
  _sandboxPreview?: SandboxPreview,
): string | null {
  const known = new Set(resources.map((resource) => resource.id));
  return initialIds.find((id) => known.has(id)) ?? null;
}

function orientationStateLabel(state: CoachOrientationState, language: ComposerLanguage): string {
  const copy = resolveCopy(language);
  switch (state) {
    case "needs_setup":
      // For the resources pane this state means "the library is empty", not
      // "the workspace needs configuring" — say exactly that.
      return localize(language, "emptyTitle");
    case "waiting":
      return copy.orientationStateWaiting;
    case "working":
      return copy.orientationStateWorking;
    case "blocked":
      return copy.orientationStateBlocked;
    case "ready":
      return copy.orientationStateReady;
    case "interrupted":
      return copy.orientationStateInterrupted;
  }
}

export function ResourcesWorkbenchView({
  language,
  resources,
  resourceSearch,
  deletedResources,
  sandboxState,
  sandboxPreview: sandboxPreviewInput,
  restoreContext,
  isBrowserPreview = false,
  isLiveBrowserPreview = false,
  onSearchResources,
  onSearchQueryChange,
  onImportFiles,
  onImportFolder,
  onImportUrl: onImportUrlAction,
  onCaptureResource,
  captureFocusOptions,
  onOrganizeResource,
  onExportResource,
  onListLibraryFolders,
  onCreateLibraryFolder,
  onRenameLibraryFolder,
  onDeleteLibraryFolder,
  onRevealSavedPath,
  onOpenResource,
  onPreviewResource,
  onStartTrainingFromResource,
  onOpenTraining,
  onRefreshResources,
  onDeleteResources,
  onRestoreResources,
  onRefreshDeletedResources,
  onChooseWorkspaceRoot,
  onResourceSelectionChange,
  onRestoreContextChange,
  resourceWriteAccess,
  deleteUnavailableReason,
  restoreUnavailableReason,
  orientation,
  leftoverNote,
  onOrientationAction,
  onAskCoach,
  onJoinLearning,
  onDebugVisibleFacts,
  organizationConfirm,
  onExpandToEditor,
  expandToEditorLabel,
}: ResourcesWorkbenchViewProps) {
  const { t } = useTranslation();
  const treeRef = useRef<HTMLDivElement>(null);
  const deleteConfirmationFocusRef = useRef<HTMLButtonElement>(null);
  const importMenuTriggerRef = useRef<HTMLButtonElement>(null);
  const importMenuRef = useRef<HTMLDivElement>(null);
  const importMenuId = useId();
  const [query, setQuery] = useState("");
  useEffect(() => { onSearchQueryChange?.(query); }, [onSearchQueryChange, query]);
  const [isImportMenuOpen, setIsImportMenuOpen] = useState(false);
  const [urlImportOpen, setUrlImportOpen] = useState(false);
  const [urlImportValue, setUrlImportValue] = useState("");
  const [urlImportFocusId, setUrlImportFocusId] = useState("");
  const [urlImportDownload, setUrlImportDownload] = useState(false);
  const [urlImportTargetDir, setUrlImportTargetDir] = useState("");
  const [urlImportState, setUrlImportState] = useState<
    {
      phase: "idle" | "busy" | "ok" | "failed";
      message?: string;
      /** Capture succeeded but the download target could not be confirmed. */
      downloadUnconfirmed?: boolean;
      /** A concrete `saved_path` the pipeline reported. */
      savedPath?: string;
      /** Resource the capture landed on, for "open file". */
      resourceId?: string;
    } | undefined
  >(undefined);
  const [organizeState, setOrganizeState] = useState<
    { phase: "busy" | "ok" | "failed"; message: string } | undefined
  >(undefined);
  const [organizeRenameValue, setOrganizeRenameValue] = useState("");
  const [organizeTagsValue, setOrganizeTagsValue] = useState("");
  const [organizeGroupValue, setOrganizeGroupValue] = useState("");
  const [exportState, setExportState] = useState<
    { phase: "busy" | "ok" | "failed"; message: string } | undefined
  >(undefined);
  const [libraryFolders, setLibraryFolders] = useState<LibraryFolderNode[] | undefined>(undefined);
  const [libraryFoldersState, setLibraryFoldersState] = useState<
    { phase: "idle" | "loading" | "ready" | "failed"; message?: string }
  >({ phase: "idle" });
  const [libraryFoldersOpen, setLibraryFoldersOpen] = useState(false);
  const [expandedFolderPaths, setExpandedFolderPaths] = useState<string[]>([]);
  const [selectedFolderPath, setSelectedFolderPath] = useState<string | null>(null);
  const [folderPrompt, setFolderPrompt] = useState<
    | {
        mode: "create" | "subfolder" | "rename";
        parentPath: string;
        path?: string;
        value: string;
        /** When set, a successful create also moves this resource into the new folder. */
        moveResourceId?: string;
        /** When set, a successful create becomes the pending capture's target folder. */
        assignCaptureTarget?: boolean;
      }
    | undefined
  >(undefined);
  const [folderPromptState, setFolderPromptState] = useState<
    { phase: "busy" | "failed"; message: string } | undefined
  >(undefined);
  const [folderDeletePath, setFolderDeletePath] = useState<string | null>(null);
  const [folderDeleteBusy, setFolderDeleteBusy] = useState(false);
  const [folderMutationState, setFolderMutationState] = useState<
    { phase: "ok" | "failed"; message: string } | undefined
  >(undefined);
  const folderListInFlightRef = useRef(false);
  const [selectedResourceId, setSelectedResourceId] = useState<string | null>(
    () => restoreContext?.surface === "detail" ? restoreContext.resourceId ?? null : null,
  );
  const [deleteConfirmationResourceIds, setDeleteConfirmationResourceIds] = useState<string[] | null>(
    null,
  );
  const [pendingDeletedResourceIds, setPendingDeletedResourceIds] = useState<string[]>([]);
  const [pendingRestoredResourceIds, setPendingRestoredResourceIds] = useState<string[]>([]);
  const [isIndexRefreshing, setIsIndexRefreshing] = useState(false);
  const [trainingStartState, setTrainingStartState] = useState<ResourceTrainingStartState | null>(null);
  const [mutationResult, setMutationResult] = useState<ResourceMutationResult | null>(null);
  const [trashOpen, setTrashOpen] = useState(false);
  const [expandedCollectionIds, setExpandedCollectionIds] = useState<Set<string>>(
    readPersistedExpandedCollectionIds,
  );
  const [searchCollapsedCollectionIds, setSearchCollapsedCollectionIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [activeTreeItemId, setActiveTreeItemId] = useState<string | null>(null);
  const [pendingTreeFocusId, setPendingTreeFocusId] = useState<string | null>(null);
  const [searchRequestState, setSearchRequestState] = useState<ResourceSearchRequestState>({
    phase: "idle",
  });
  const [searchRefreshRevision, setSearchRefreshRevision] = useState(0);
  const didRevealFirstResourcePath = useRef(false);
  const searchRequestSequenceRef = useRef(0);
  const indexRefreshInFlightRef = useRef(false);
  const canWriteResources = resourceWriteAccess?.allowed !== false;
  const resourceWriteBlockedReason = !canWriteResources
    ? resourceWriteAccess?.reason?.trim() || resourceReadOnlyNotice(language)
    : undefined;

  const setResourceDetail = (resourceId: string | null) => {
    setSelectedResourceId(resourceId);
    onRestoreContextChange?.(
      resourceId
        ? {
            surface: "detail",
            resourceId,
          }
        : undefined,
    );
  };

  const trimmedQuery = query.trim();
  const normalizedQuery = normalizeSearchText(trimmedQuery);
  const hasSearchQuery = Boolean(normalizedQuery);
  const trashSnapshotAvailable = deletedResources !== undefined;
  const trashedResources = deletedResources ?? [];
  const activeSearchRequestId = searchRequestState.requestId;
  const usesRemoteSearch = !isBrowserPreview || Boolean(onSearchResources);
  const currentServerSearch = useMemo(() => {
    if (
      !usesRemoteSearch ||
      !activeSearchRequestId ||
      !resourceSearch ||
      resourceSearch.requestId !== activeSearchRequestId ||
      normalizeSearchText(resourceSearch.query) !== normalizedQuery
    ) {
      return undefined;
    }
    return resourceSearch;
  }, [activeSearchRequestId, normalizedQuery, resourceSearch, usesRemoteSearch]);

  const visibleResources = useMemo(() => {
    if (!hasSearchQuery) {
      return resources;
    }
    if (usesRemoteSearch) {
      return currentServerSearch?.hits ?? [];
    }
    return resources.filter((resource) =>
      [resource.title, resource.summary, ...sourceChain(resource), ...(resource.qualityFlags ?? [])]
        .map(normalizeSearchText)
        .some((value) => value.includes(normalizedQuery)),
    );
  }, [currentServerSearch, hasSearchQuery, normalizedQuery, resources, usesRemoteSearch]);

  const resourceTreeResources = useMemo(() => {
    if (!hasSearchQuery || !usesRemoteSearch) {
      return resources;
    }
    return currentServerSearch?.hits ?? [];
  }, [currentServerSearch, hasSearchQuery, resources, usesRemoteSearch]);

  const resourceTree = useMemo(
    () => buildResourceTree(resourceTreeResources, sandboxState, language),
    [language, resourceTreeResources, sandboxState],
  );

  const selectedResource = useMemo(
    () => resources.find((resource) => resource.id === selectedResourceId),
    [resources, selectedResourceId],
  );
  const selectedResourceCanStartTraining = Boolean(
    selectedResource &&
      resourceCanStartTraining(selectedResource) &&
      onStartTrainingFromResource &&
      !isBrowserPreview &&
      resourceWriteAccess?.allowed === true,
  );
  const selectedResourceTrainingState =
    selectedResource && trainingStartState?.resourceId === selectedResource.id
      ? trainingStartState
      : undefined;
  const selectedResourceTrainingReadiness = selectedResource
    ? resourceTrainingReadiness(selectedResource, language, {
        canStartTraining: selectedResourceCanStartTraining,
        canWriteResources,
        isBrowserPreview,
        hasTrainingAction: Boolean(onStartTrainingFromResource),
        hasRefreshAction: Boolean(onRefreshResources),
      })
    : undefined;
  const selectedResourceTrainingStatusMessage = selectedResourceTrainingState
    ? resourceTrainingHandoffFailureMessage(language, selectedResourceTrainingState.reason) ??
      resourceTrainingStartCopy(language, selectedResourceTrainingState.phase)
    : undefined;
  const selectedResourceTrainingIsAvailable =
    selectedResourceTrainingState?.phase === "ready" ||
    selectedResourceTrainingState?.phase === "not-current";
  const startTrainingFromSelectedResource = () => {
    if (
      !selectedResource ||
      !selectedResourceCanStartTraining ||
      !onStartTrainingFromResource ||
      selectedResourceTrainingIsAvailable
    ) {
      return;
    }
    setTrainingStartState({ resourceId: selectedResource.id, phase: "loading" });
    void onStartTrainingFromResource(selectedResource.id)
      .then((result) =>
        setTrainingStartState({
          resourceId: selectedResource.id,
          phase: result.outcome,
          reason: result.reason,
        }),
      )
      .catch(() =>
        setTrainingStartState({
          resourceId: selectedResource.id,
          phase: "failed",
          reason: "unavailable",
        }),
      );
  };
  const selectedResourceContextIds = useMemo(
    () => (selectedResourceId ? [selectedResourceId] : []),
    [selectedResourceId],
  );

  useEffect(() => {
    onResourceSelectionChange?.(selectedResourceContextIds, "selection");
  }, [onResourceSelectionChange, selectedResourceContextIds]);

  useEffect(() => {
    setTrainingStartState((current) =>
      current?.resourceId === selectedResourceId ? current : null,
    );
  }, [selectedResourceId]);

  useEffect(
    () => () => {
      onResourceSelectionChange?.([], "unmount");
    },
    [onResourceSelectionChange],
  );

  useEffect(() => {
    if (!isImportMenuOpen) {
      return;
    }
    const closeWhenPointerLeavesMenu = (event: PointerEvent) => {
      if (!(event.target instanceof Node)) {
        return;
      }
      if (
        importMenuRef.current?.contains(event.target) ||
        importMenuTriggerRef.current?.contains(event.target)
      ) {
        return;
      }
      setIsImportMenuOpen(false);
    };
    document.addEventListener("pointerdown", closeWhenPointerLeavesMenu);
    return () => document.removeEventListener("pointerdown", closeWhenPointerLeavesMenu);
  }, [isImportMenuOpen]);

  const trashedResourceIds = useMemo(
    () => new Set(trashedResources.map(deletedResourceId).filter((resourceId): resourceId is string => Boolean(resourceId))),
    [trashedResources],
  );
  const isDeletePending = pendingDeletedResourceIds.length > 0;
  const isRestorePending = pendingRestoredResourceIds.length > 0;

  useEffect(() => {
    if (canWriteResources) {
      return;
    }
    setIsImportMenuOpen(false);
    setDeleteConfirmationResourceIds(null);
  }, [canWriteResources]);
  const deleteActionDisabled =
    !canWriteResources || isBrowserPreview || !onDeleteResources || isDeletePending || isRestorePending;
  const indexActionDisabled = !canWriteResources || !onRefreshResources || isIndexRefreshing;
  const refreshResourcesLabel = !canWriteResources
    ? resourceWriteBlockedReason ?? localize(language, "refresh")
    : isIndexRefreshing
      ? localize(language, "indexing")
      : localize(language, "refresh");
  const mutationStatus = isDeletePending
    ? { tone: "pending", label: localizeCount(language, "deletePending", pendingDeletedResourceIds.length) }
    : isRestorePending
      ? { tone: "pending", label: localizeCount(language, "restorePending", pendingRestoredResourceIds.length) }
      : mutationResult
        ? {
            tone: mutationResult.status,
            label:
              mutationResult.status === "succeeded"
                ? localizeCount(
                    language,
                    mutationResult.kind === "delete" ? "deleteSucceeded" : "restoreSucceeded",
                    mutationResult.resourceIds.length,
                  )
                : localize(language, "mutationFailed"),
          }
        : undefined;
  const searchFailure = searchRequestState.phase === "failed" ? searchRequestState : undefined;
  const isServerSearchPending =
    hasSearchQuery && usesRemoteSearch && !currentServerSearch && !searchFailure;
  const searchStatus = !hasSearchQuery
    ? undefined
    : !usesRemoteSearch
      ? undefined
      : searchFailure
        ? {
            tone: "failed",
            label: localize(language, "searchFailed"),
          }
        : isServerSearchPending
          ? { tone: "pending", label: localize(language, "searching") }
          : undefined;
  const shouldShowNoMatches =
    hasSearchQuery && !isServerSearchPending && !searchFailure && visibleResources.length === 0;
  const isResourceListLoading = isServerSearchPending;
  const visibleResourceIds = useMemo(
    () => new Set(visibleResources.map((resource) => resource.id)),
    [visibleResources],
  );
  const visibleResourceTree = useMemo(
    () => filterResourceTree(resourceTree, visibleResourceIds),
    [resourceTree, visibleResourceIds],
  );
  const selectedResourceAncestorIds = useMemo(
    () =>
      selectedResourceId
        ? findResourceAncestorCollectionIds(resourceTree, selectedResourceId) ?? []
        : [],
    [resourceTree, selectedResourceId],
  );
  const firstVisibleResourceAncestorIds = useMemo(
    () => firstResourceAncestorCollectionIds(visibleResourceTree) ?? [],
    [visibleResourceTree],
  );
  const renderedExpandedCollectionIds = useMemo(() => {
    if (!hasSearchQuery) {
      return expandedCollectionIds;
    }
    return new Set(
      collectionIds(visibleResourceTree).filter((id) => !searchCollapsedCollectionIds.has(id)),
    );
  }, [expandedCollectionIds, hasSearchQuery, searchCollapsedCollectionIds, visibleResourceTree]);
  const renderedTreeItemIds = useMemo(
    () => visibleTreeItemIds(visibleResourceTree, renderedExpandedCollectionIds),
    [renderedExpandedCollectionIds, visibleResourceTree],
  );
  const renderedResourceRowIds = useMemo(
    () => renderedTreeItemIds.filter((id) => id.startsWith("resource:")),
    [renderedTreeItemIds],
  );
  const resolvedActiveTreeItemId =
    activeTreeItemId && renderedResourceRowIds.includes(activeTreeItemId)
      ? activeTreeItemId
      : renderedResourceRowIds[0] ?? null;

  useEffect(() => {
    const sequence = ++searchRequestSequenceRef.current;
    if (!hasSearchQuery || !onSearchResources) {
      setSearchRequestState({ phase: "idle" });
      return;
    }
    if (!onSearchResources) {
      return;
    }

    setSearchRequestState({ phase: "debouncing" });
    const requestId = `resource-search-${Date.now().toString(36)}-${sequence}`;
    const timer = window.setTimeout(() => {
      if (sequence !== searchRequestSequenceRef.current) {
        return;
      }
      setSearchRequestState({ phase: "loading", requestId });
      try {
        void Promise.resolve(onSearchResources({ query: trimmedQuery, requestId })).catch(() => {
          if (sequence !== searchRequestSequenceRef.current) {
            return;
          }
          setSearchRequestState({ phase: "failed", requestId });
        });
      } catch {
        setSearchRequestState({ phase: "failed", requestId });
      }
    }, 200);

    return () => window.clearTimeout(timer);
  }, [hasSearchQuery, onSearchResources, searchRefreshRevision, trimmedQuery]);

  useEffect(() => {
    setSearchCollapsedCollectionIds(new Set());
  }, [normalizedQuery]);

  useEffect(() => {
    if (selectedResourceId && !resources.some((resource) => resource.id === selectedResourceId)) {
      setResourceDetail(null);
    }
  }, [onRestoreContextChange, resources, selectedResourceId]);

  useEffect(() => {
    if (restoreContext?.surface !== "detail" || !restoreContext.resourceId) {
      return;
    }
    if (resources.some((resource) => resource.id === restoreContext.resourceId)) {
      setSelectedResourceId(restoreContext.resourceId);
    }
  }, [resources, restoreContext]);

  useEffect(() => {
    if (restoreContext?.surface !== "sandbox") {
      return;
    }
    const path = restoreContext.previewPath ?? restoreContext.sandboxPath;
    const resource = resources.find((item) => item.sandboxPath === path);
    setSelectedResourceId(resource?.id ?? null);
  }, [resources, restoreContext]);

  useEffect(() => {
    if (!deleteConfirmationResourceIds) {
      return;
    }
    const availableIds = new Set(resources.map((resource) => resource.id));
    const remainingResourceIds = deleteConfirmationResourceIds.filter((resourceId) =>
      availableIds.has(resourceId),
    );
    if (remainingResourceIds.length === 0) {
      setDeleteConfirmationResourceIds(null);
    } else if (remainingResourceIds.length !== deleteConfirmationResourceIds.length) {
      setDeleteConfirmationResourceIds(remainingResourceIds);
    }
  }, [deleteConfirmationResourceIds, resources]);

  useEffect(() => {
    if (!deleteConfirmationResourceIds) {
      return;
    }
    const focusFrame = window.requestAnimationFrame(() => deleteConfirmationFocusRef.current?.focus());
    return () => window.cancelAnimationFrame(focusFrame);
  }, [deleteConfirmationResourceIds]);

  useEffect(() => {
    if (didRevealFirstResourcePath.current || visibleResourceTree.length === 0) {
      return;
    }
    setExpandedCollectionIds((current) => {
      const next = new Set(current);
      firstVisibleResourceAncestorIds.forEach((id) => next.add(id));
      return next;
    });
    didRevealFirstResourcePath.current = true;
  }, [firstVisibleResourceAncestorIds, visibleResourceTree.length]);

  useEffect(() => {
    if (!isDeletePending || !trashSnapshotAvailable) {
      return;
    }
    const activeResourceIds = new Set(resources.map((resource) => resource.id));
    const deletionConfirmed = pendingDeletedResourceIds.every(
      (resourceId) => !activeResourceIds.has(resourceId) && trashedResourceIds.has(resourceId),
    );
    if (!deletionConfirmed) {
      return;
    }
    setSelectedResourceId((current) =>
      current && pendingDeletedResourceIds.includes(current) ? null : current,
    );
    setPendingDeletedResourceIds([]);
    setMutationResult({
      kind: "delete",
      resourceIds: pendingDeletedResourceIds,
      status: "succeeded",
    });
    setTrashOpen(true);
  }, [
    isDeletePending,
    pendingDeletedResourceIds,
    resources,
    trashedResourceIds,
    trashSnapshotAvailable,
  ]);

  useEffect(() => {
    if (!isRestorePending || !trashSnapshotAvailable) {
      return;
    }
    const activeResourceIds = new Set(resources.map((resource) => resource.id));
    const restorationConfirmed = pendingRestoredResourceIds.every(
      (resourceId) => activeResourceIds.has(resourceId) && !trashedResourceIds.has(resourceId),
    );
    if (!restorationConfirmed) {
      return;
    }
    setPendingRestoredResourceIds([]);
    setMutationResult({
      kind: "restore",
      resourceIds: pendingRestoredResourceIds,
      status: "succeeded",
    });
  }, [
    isRestorePending,
    pendingRestoredResourceIds,
    resources,
    trashedResourceIds,
    trashSnapshotAvailable,
  ]);

  useEffect(() => {
    if (!selectedResourceId || selectedResourceAncestorIds.length === 0) {
      return;
    }
    setExpandedCollectionIds((current) => {
      const next = new Set(current);
      selectedResourceAncestorIds.forEach((id) => next.add(id));
      return next.size === current.size ? current : next;
    });
  }, [selectedResourceAncestorIds, selectedResourceId]);

  useEffect(() => {
    if (!pendingTreeFocusId) {
      return;
    }
    const treeItems = Array.from(
      treeRef.current?.querySelectorAll<HTMLElement>('[data-resource-tree-item-id]') ?? [],
    );
    const pendingTreeItem = treeItems.find(
      (item) => item.dataset.resourceTreeItemId === pendingTreeFocusId,
    );
    if (pendingTreeItem) {
      pendingTreeItem.focus();
    }
    if (pendingTreeItem || !renderedTreeItemIds.includes(pendingTreeFocusId)) {
      setPendingTreeFocusId(null);
    }
  }, [pendingTreeFocusId, renderedTreeItemIds]);

  /** One click opens the resource in the reader; the reader replaces the list. */
  const selectResource = (resource: ResourceRecord) => {
    setResourceDetail(resource.id);
  };

  const reportMutationFailure = (kind: ResourceMutationKind, resourceIds: string[]) => {
    if (kind === "delete") {
      setPendingDeletedResourceIds([]);
    } else {
      setPendingRestoredResourceIds([]);
    }
    setMutationResult({ kind, resourceIds, status: "failed" });
  };

  /** Per-resource delete: opens the existing confirm dialog for this one resource. */
  const requestResourceDelete = (resourceId: string) => {
    if (!canWriteResources || deleteActionDisabled || !onDeleteResources) {
      return;
    }
    setDeleteConfirmationResourceIds([resourceId]);
  };

  const confirmDeleteSelectedResources = () => {
    const resourceIds = deleteConfirmationResourceIds ?? [];
    if (resourceIds.length === 0 || !canWriteResources || deleteActionDisabled || !onDeleteResources) {
      setDeleteConfirmationResourceIds(null);
      return;
    }
    setDeleteConfirmationResourceIds(null);
    setPendingDeletedResourceIds(resourceIds);
    setMutationResult(null);
    try {
      const deleteRequest = onDeleteResources(resourceIds);
      if (hasSearchQuery && !isBrowserPreview) {
        void Promise.resolve(deleteRequest).then(() => {
          setSearchRefreshRevision((current) => current + 1);
        });
      }
      void Promise.resolve(deleteRequest).catch(() => reportMutationFailure("delete", resourceIds));
    } catch {
      reportMutationFailure("delete", resourceIds);
    }
  };

  const cancelDeleteSelectedResources = () => {
    setDeleteConfirmationResourceIds(null);
  };

  const restoreDeletedResource = (resourceId: string) => {
    if (!canWriteResources || isBrowserPreview || !onRestoreResources || isDeletePending || isRestorePending) {
      return;
    }
    const resourceIds = [resourceId];
    setPendingRestoredResourceIds(resourceIds);
    setMutationResult(null);
    try {
      const restoreRequest = onRestoreResources(resourceIds);
      if (hasSearchQuery && !isBrowserPreview) {
        void Promise.resolve(restoreRequest).then(() => {
          setSearchRefreshRevision((current) => current + 1);
        });
      }
      void Promise.resolve(restoreRequest).catch(() => reportMutationFailure("restore", resourceIds));
    } catch {
      reportMutationFailure("restore", resourceIds);
    }
  };

  const openResourceInVsCode = (resource: ResourceRecord) => {
    setSelectedResourceId(resource.id);
    onOpenResource?.(resource.id);
  };

  const focusFirstImportMenuItem = () => {
    window.requestAnimationFrame(() => {
      importMenuRef.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus();
    });
  };

  const openImportMenu = (focusFirstItem = false) => {
    if (!canWriteResources) {
      return;
    }
    setIsImportMenuOpen(true);
    if (focusFirstItem) {
      focusFirstImportMenuItem();
    }
  };

  const toggleImportMenu = () => {
    if (!canWriteResources) {
      return;
    }
    setIsImportMenuOpen((open) => !open);
  };

  const closeImportMenu = (returnFocus = false) => {
    setIsImportMenuOpen(false);
    if (returnFocus) {
      window.requestAnimationFrame(() => importMenuTriggerRef.current?.focus());
    }
  };

  const handleImportMenuKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Escape") {
      return;
    }
    event.preventDefault();
    closeImportMenu(true);
  };

  const runImportAction = (action: (() => void) | undefined) => {
    closeImportMenu();
    if (!canWriteResources) {
      return;
    }
    action?.();
  };

  const openUrlImportForm = () => {
    if (!canWriteResources) {
      return;
    }
    setUrlImportState(undefined);
    setUrlImportOpen(true);
  };

  /**
   * The menu's URL action: with a capture lane it opens the paste-and-file form
   * (fetch → clean → Markdown snapshot → index); without one (a fixture
   * preview) it keeps the legacy host prompt. Shadowing the prop keeps the
   * menu's single URL entry point intact for keyboard/name guards.
   */
  const onImportUrl = onCaptureResource ? openUrlImportForm : onImportUrlAction;

  const closeUrlImportForm = () => {
    setUrlImportOpen(false);
    setUrlImportState(undefined);
    setUrlImportValue("");
    setUrlImportFocusId("");
    setUrlImportDownload(false);
    setUrlImportTargetDir("");
  };

  const submitUrlImport = () => {
    if (!onCaptureResource || urlImportState?.phase === "busy") {
      return;
    }
    const url = urlImportValue.trim();
    if (!/^https?:\/\/\S+$/i.test(url)) {
      setUrlImportState({ phase: "failed", message: localize(language, "addUrlInvalid") });
      return;
    }
    const download = urlImportDownload;
    const targetDir = download ? normalizeLibraryFolderPath(urlImportTargetDir) : "";
    setUrlImportState({
      phase: "busy",
      message: localize(language, download ? "addUrlDownloadBusy" : "addUrlBusy"),
    });
    void Promise.resolve()
      .then(() =>
        onCaptureResource({
          url,
          focusId: urlImportFocusId || undefined,
          download,
          targetDir: download ? targetDir : undefined,
        }),
      )
      .then((outcome) => {
        if (outcome.ok) {
          const captured = outcome.deduped
            ? localizeValue(language, "addUrlDeduped", outcome.message)
            : localizeValue(language, "addUrlSucceeded", outcome.message);
          const savedPath = outcome.savedPath?.trim() || "";
          setUrlImportState({
            phase: "ok",
            message: savedPath
              ? `${captured} ${localizeValue(language, "addUrlSavedPath", savedPath)}`
              : captured,
            // A requested download with no reported path is stated honestly
            // instead of claiming the file landed somewhere.
            downloadUnconfirmed: download && !savedPath,
            savedPath: savedPath || undefined,
            resourceId: outcome.resourceId,
          });
          setUrlImportValue("");
          setUrlImportFocusId("");
          return;
        }
        setUrlImportState({
          phase: "failed",
          message: outcome.unconfirmed
            ? download
              ? localize(language, "addUrlUnconfirmedDownload")
              : localize(language, "addUrlUnconfirmed")
            : localizeValue(language, "addUrlFailed", outcome.message),
        });
      })
      .catch((error: unknown) => {
        setUrlImportState({
          phase: "failed",
          message: localizeValue(
            language,
            "addUrlFailed",
            thrownReasonText(error),
          ),
        });
      });
  };

  // ------------------------------------------------------ real library folders
  // The folder section is the Library's organizational space: it lists the
  // real folders (`/library/groups`), merged with the folders the current
  // resources already describe, so a folder is visible with a count even
  // before a listing answers, and an empty new folder appears the moment it
  // is created.
  const derivedLibraryFolders = useMemo(
    () => libraryFolderTreeFromResources(resources),
    [resources],
  );
  const libraryFolderTree = useMemo(
    () => mergeLibraryFolderTrees(libraryFolders ?? [], derivedLibraryFolders),
    [derivedLibraryFolders, libraryFolders],
  );
  const libraryFolderEntries = useMemo(
    () => flattenLibraryFolders(libraryFolderTree),
    [libraryFolderTree],
  );
  const selectedFolderEntry = useMemo(
    () => libraryFolderEntries.find((entry) => entry.path === selectedFolderPath) ?? null,
    [libraryFolderEntries, selectedFolderPath],
  );
  // A row is visible when every ancestor folder is expanded.
  const visibleFolderEntries = useMemo(
    () =>
      libraryFolderEntries.filter((entry) => {
        const segments = entry.path.split("/");
        for (let index = 1; index < segments.length; index += 1) {
          if (!expandedFolderPaths.includes(segments.slice(0, index).join("/"))) {
            return false;
          }
        }
        return true;
      }),
    [expandedFolderPaths, libraryFolderEntries],
  );
  const folderPathsWithChildren = useMemo(() => {
    const withChildren = new Set<string>();
    for (const entry of libraryFolderEntries) {
      const parentPath = libraryFolderParentPath(entry.path);
      if (parentPath) {
        withChildren.add(parentPath);
      }
    }
    return withChildren;
  }, [libraryFolderEntries]);

  const loadLibraryFolders = (options?: { quiet?: boolean }) => {
    if (!onListLibraryFolders || folderListInFlightRef.current) {
      return;
    }
    const quiet = options?.quiet === true;
    folderListInFlightRef.current = true;
    if (!quiet) {
      setLibraryFoldersState({ phase: "loading" });
    }
    void Promise.resolve()
      .then(() => onListLibraryFolders())
      .then((result) => {
        if (result.ok) {
          setLibraryFolders(result.folders);
          setLibraryFoldersState({ phase: "ready" });
          return;
        }
        // The resources' own folders stay visible; the listing is reported
        // as unavailable rather than as an empty library.
        if (quiet) {
          // A background confirmation never downgrades a readable state.
          setLibraryFoldersState((current) =>
            current.phase === "ready"
              ? current
              : { phase: result.folders.length > 0 ? "ready" : "failed", message: result.message },
          );
          return;
        }
        setLibraryFoldersState({
          phase: result.folders.length > 0 ? "ready" : "failed",
          message: result.message,
        });
      })
      .catch((error: unknown) => {
        if (quiet) {
          return;
        }
        setLibraryFoldersState({ phase: "failed", message: thrownReasonText(error) });
      })
      .finally(() => {
        folderListInFlightRef.current = false;
      });
  };

  useEffect(() => {
    if (libraryFoldersOpen && libraryFoldersState.phase === "idle") {
      loadLibraryFolders();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- one load per open
  }, [libraryFoldersOpen]);

  const openFolderCreatePrompt = (
    parentPath = "",
    moveResourceId?: string,
    assignCaptureTarget = false,
  ) => {
    if (!canWriteResources || !onCreateLibraryFolder) {
      return;
    }
    setFolderPromptState(undefined);
    setFolderPrompt({
      mode: parentPath ? "subfolder" : "create",
      parentPath: normalizeLibraryFolderPath(parentPath),
      value: "",
      moveResourceId,
      assignCaptureTarget,
    });
  };

  const submitFolderPrompt = () => {
    const prompt = folderPrompt;
    if (!prompt || folderPromptState?.phase === "busy") {
      return;
    }
    const name = prompt.value.trim().replace(/^\/+|\/+$/g, "");
    if (!name || name.includes("..")) {
      setFolderPromptState({ phase: "failed", message: localize(language, "folderPromptInvalid") });
      return;
    }
    const normalizedParent = normalizeLibraryFolderPath(prompt.parentPath);
    const targetPath =
      prompt.mode === "rename"
        ? normalizeLibraryFolderPath(`${libraryFolderParentPath(prompt.path ?? "")}/${name}`)
        : normalizeLibraryFolderPath(`${normalizedParent}/${name}`);
    if (!targetPath) {
      setFolderPromptState({ phase: "failed", message: localize(language, "folderPromptInvalid") });
      return;
    }
    const rename = prompt.mode === "rename";
    if (rename ? !onRenameLibraryFolder : !onCreateLibraryFolder) {
      setFolderPromptState({
        phase: "failed",
        message: localizeValue(
          language,
          "folderFailed",
          localize(language, "foldersUnavailable"),
        ),
      });
      return;
    }
    setFolderPromptState({ phase: "busy", message: localize(language, rename ? "folderRenameBusy" : "folderCreateBusy") });
    const previousFolders = libraryFolders;
    const rollback = () => setLibraryFolders(previousFolders);
    const runFolderWrite = (): Promise<ResourceMutationOutcome> => {
      if (rename) {
        return onRenameLibraryFolder
          ? onRenameLibraryFolder(prompt.path ?? "", targetPath)
          : Promise.resolve({ ok: false, message: "" });
      }
      return onCreateLibraryFolder
        ? onCreateLibraryFolder(targetPath)
        : Promise.resolve({ ok: false, message: "" });
    };
  void Promise.resolve()
    .then(() => runFolderWrite())
    .then((outcome) => {
      if (!outcome.ok) {
        if (outcome.unconfirmed) {
          // The write may still have landed: reconcile with the host instead
          // of leaving a tree the user must refresh by hand.
          loadLibraryFolders({ quiet: true });
        } else {
          rollback();
        }
        setFolderPromptState({
          phase: "failed",
          message: outcome.unconfirmed
            ? localize(language, "folderUnconfirmed")
            : localizeValue(language, "folderFailed", outcome.message),
        });
        return;
      }
        // Immediate, local application: the folder is in the tree before any
        // refresh — a refresh only confirms the same fact.
        setLibraryFolders((current) =>
          prompt.mode === "rename"
            ? renameLibraryFolderPath(current ?? libraryFolderTree, prompt.path ?? "", targetPath)
            : addLibraryFolderPath(current ?? libraryFolderTree, targetPath),
        );
        if (prompt.mode === "rename") {
          setSelectedFolderPath(targetPath);
          setExpandedFolderPaths((current) =>
            current.map((path) =>
              path === prompt.path || path.startsWith(`${prompt.path}/`)
                ? `${targetPath}${path.slice((prompt.path ?? "").length)}`
                : path,
            ),
          );
        } else {
          setSelectedFolderPath(targetPath);
          if (normalizedParent) {
            setExpandedFolderPaths((current) =>
              current.includes(normalizedParent) ? current : [...current, normalizedParent],
            );
          }
        }
        setFolderMutationState({
          phase: "ok",
          message: localizeValue(
            language,
            prompt.mode === "rename" ? "folderRenamed" : "folderCreated",
            targetPath,
          ),
        });
        setFolderPrompt(undefined);
        setFolderPromptState(undefined);
        if (prompt.mode === "rename") {
          // A rename moves the resources inside the folder: refresh through the
          // Library's existing index action so their paths follow, and confirm
          // the folder listing in the background.
          refreshResources();
          loadLibraryFolders({ quiet: true });
        }
        if (prompt.assignCaptureTarget) {
          setUrlImportDownload(true);
          setUrlImportTargetDir(targetPath);
        }
        if (prompt.moveResourceId) {
          runOrganizeAction({ action: "set_group", group: targetPath }, prompt.moveResourceId);
        }
      })
      .catch((error: unknown) => {
        rollback();
        setFolderPromptState({
          phase: "failed",
          message: localizeValue(language, "folderFailed", thrownReasonText(error)),
        });
      });
  };

  const toggleFolderPath = (path: string) => {
    setSelectedFolderPath(path);
    setExpandedFolderPaths((current) =>
      current.includes(path) ? current.filter((entry) => entry !== path) : [...current, path],
    );
  };

  const requestFolderDelete = (path: string) => {
    if (!canWriteResources || !onDeleteLibraryFolder) {
      return;
    }
    setFolderDeletePath(path);
  };

  const confirmFolderDelete = () => {
    const path = folderDeletePath;
    if (!path || !onDeleteLibraryFolder || folderDeleteBusy) {
      return;
    }
    setFolderDeleteBusy(true);
    const previousFolders = libraryFolders;
    void Promise.resolve()
      .then(() => onDeleteLibraryFolder(path))
      .then((outcome) => {
        if (!outcome.ok) {
          setFolderMutationState({
            phase: "failed",
            message: outcome.unconfirmed
              ? localize(language, "folderUnconfirmed")
              : localizeValue(language, "folderFailed", outcome.message),
          });
          return;
        }
        // Trash semantics: the folder (and the resources inside it) left the
        // library; the local tree drops the subtree immediately and the
        // existing index refresh brings the moved records into the snapshot.
        setLibraryFolders((current) => removeLibraryFolderPath(current ?? libraryFolderTree, path));
        setSelectedFolderPath((current) => (current === path ? null : current));
        setExpandedFolderPaths((current) => current.filter((entry) => entry !== path));
        setFolderMutationState({
          phase: "ok",
          message: localizeValue(language, "folderDeleted", path),
        });
        setFolderDeletePath(null);
        onRefreshDeletedResources?.();
        loadLibraryFolders({ quiet: true });
      })
      .catch((error: unknown) => {
        setFolderMutationState({
          phase: "failed",
          message: localizeValue(language, "folderFailed", thrownReasonText(error)),
        });
      })
      .finally(() => {
        setFolderDeleteBusy(false);
      });
  };

  const renderLibraryFolderRow = (entry: LibraryFolderFlatEntry, hasChildren: boolean) => {
    const isExpanded = expandedFolderPaths.includes(entry.path);
    const isSelected = selectedFolderPath === entry.path;
    return (
      <li key={entry.path} className="resources-knowledge__folder-row">
        <button
          className={`resources-knowledge__folder-toggle${isSelected ? " is-selected" : ""}`}
          type="button"
          style={{ paddingLeft: `${4 + entry.depth * 12}px` }}
          aria-expanded={hasChildren ? isExpanded : undefined}
          aria-current={isSelected ? "true" : undefined}
          aria-label={`${entry.name} (${entry.resourceCount})`}
          title={entry.path}
          onClick={() => toggleFolderPath(entry.path)}
        >
          <span className="resources-knowledge__folder-chevron" aria-hidden="true">
            {hasChildren ? <ChevronDownIcon size={11} /> : <span className="resources-knowledge__folder-dot" />}
          </span>
          <FolderIcon size={13} aria-hidden="true" />
          <span className="resources-knowledge__folder-name">{entry.name}</span>
          <span className="resources-knowledge__folder-count">{entry.resourceCount}</span>
        </button>
      </li>
    );
  };

  const runOrganizeAction = (
    action: ResourceOrganizeInput,
    resourceId = selectedResourceId,
  ) => {
    if (!onOrganizeResource || !resourceId) {
      return;
    }
    setOrganizeState({ phase: "busy", message: localize(language, "organizeTitle") });
    void Promise.resolve()
      .then(() => onOrganizeResource(resourceId, action))
      .then((outcome) => {
        setOrganizeState({
          phase: outcome.ok ? "ok" : "failed",
          message: outcome.ok
            ? outcome.message || localize(language, "organizeSucceeded")
            : outcome.unconfirmed
              ? localize(language, "organizeUnconfirmed")
              : localizeValue(language, "organizeFailed", outcome.message),
        });
      })
      .catch((error: unknown) => {
        setOrganizeState({
          phase: "failed",
          message: localizeValue(
            language,
            "organizeFailed",
            thrownReasonText(error),
          ),
        });
      });
  };

  const exportSelectedResource = (resourceId: string) => {
    if (!onExportResource || exportState?.phase === "busy") {
      return;
    }
    setExportState({ phase: "busy", message: localize(language, "exportBusy") });
    void Promise.resolve()
      .then(() => onExportResource(resourceId))
      .then((outcome) => {
        setExportState({
          phase: outcome.ok ? "ok" : "failed",
          message: outcome.ok
            ? outcome.requested
              ? outcome.message ||
                localizeValue(
                  language,
                  "exportRequested",
                  selectedResource?.title ?? resourceId,
                )
              : localizeValue(language, "exportSucceeded", outcome.message)
            : localizeValue(language, "exportFailed", outcome.message),
        });
      })
      .catch((error: unknown) => {
        setExportState({
          phase: "failed",
          message: localizeValue(
            language,
            "exportFailed",
            thrownReasonText(error),
          ),
        });
      });
  };

  const refreshResources = () => {
    if (!canWriteResources || !onRefreshResources || indexRefreshInFlightRef.current) {
      return;
    }
    indexRefreshInFlightRef.current = true;
    setIsIndexRefreshing(true);
    void Promise.resolve()
      .then(() => onRefreshResources())
      .catch(() => undefined)
      .finally(() => {
        indexRefreshInFlightRef.current = false;
        setIsIndexRefreshing(false);
      });
  };

  useEffect(() => {
    // Organize inputs follow the selected resource (title + tags are its
    // current values); the group field starts empty because the current
    // collection is shown as a path, not as an editable name.
    setOrganizeRenameValue(selectedResource?.title ?? "");
    setOrganizeTagsValue((selectedResource?.tags ?? []).join(", "));
    setOrganizeGroupValue("");
    setOrganizeState(undefined);
    setExportState(undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- identity change is the trigger
  }, [selectedResource?.id, selectedResource?.title]);

  const toggleCollection = (id: string) => {
    if (hasSearchQuery) {
      setSearchCollapsedCollectionIds((current) => {
        const next = new Set(current);
        if (next.has(id)) {
          next.delete(id);
        } else {
          next.add(id);
        }
        return next;
      });
      return;
    }

    setExpandedCollectionIds((current) => {
      const next = new Set(current);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const moveTreeFocus = (id: string) => {
    setActiveTreeItemId(id);
    setPendingTreeFocusId(id);
  };

  const handleTreeKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape" && selectedResourceId) {
      event.preventDefault();
      setResourceDetail(null);
      return;
    }

    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
      return;
    }

    const items = Array.from(
      event.currentTarget.querySelectorAll<HTMLElement>('[data-resource-tree-item-id]'),
    );
    if (items.length === 0) {
      return;
    }
    event.preventDefault();
    if (event.key === "Home") {
      items[0]?.focus();
      return;
    }
    if (event.key === "End") {
      items[items.length - 1]?.focus();
      return;
    }
    const currentItem = (event.target as HTMLElement).closest<HTMLElement>(
      '[data-resource-tree-item-id]',
    );
    const currentIndex = currentItem ? items.indexOf(currentItem) : -1;
    if (currentIndex < 0 || items.length < 2) {
      return;
    }
    const delta = event.key === "ArrowDown" ? 1 : -1;
    const nextIndex = Math.min(Math.max(currentIndex + delta, 0), items.length - 1);
    items[nextIndex]?.focus();
  };

  const sandboxRoot = sandboxState?.sandboxRootPath ?? sandboxState?.rootPath;
  const sandboxReady = Boolean(sandboxState?.ready);
  const linkedResources = sandboxState?.linkedResourceCount ?? 0;
  const sandboxFileCount = sandboxState?.totalFiles ?? 0;
  const selectedResourceSource = selectedResource ? sourceChain(selectedResource) : [];
  const selectedResourceSourceLabel = Array.from(
    new Set(selectedResourceSource.map(compactSourceLabel).filter(Boolean)),
  ).join(" / ");
  const selectedResourceOpenTarget = selectedResource
    ? resolveResourceOpenTarget(selectedResource)
    : { kind: "unavailable" as const, reason: "missing_source" as const };
  const selectedResourceOpenLabel =
    selectedResourceOpenTarget.kind === "browser"
      ? localize(language, "openInBrowser")
      : selectedResourceOpenTarget.kind === "vscode"
        ? localize(language, "openInVsCode")
        : localize(language, "openUnavailable");
  const selectedResourceIndexNotice = selectedResource
    ? resourceIndexNotice(selectedResource, language)
    : undefined;
  const selectedResourceTrust = selectedResource ? resourceTrust(selectedResource, language) : undefined;
  const selectedResourceFreshness = selectedResource?.freshness;
  const selectedResourcePreviewMode = selectedResource
    ? resourcePreviewMode(selectedResource, language)
    : undefined;
  // Facts trim: one Source line plus ONE merged status line (index · trust ·
  // freshness · preview). Unindexed resources surface the index notice (or
  // "not indexed") and the reader keeps the existing refresh action.
  const selectedResourceStatusSegments = selectedResource
    ? [
        selectedResourceIndexNotice
          ? selectedResourceIndexNotice.label
          : selectedResource.indexState === "indexed"
            ? localize(language, "indexed")
            : localize(language, "notIndexed"),
        selectedResourceTrust,
        selectedResourceFreshness && selectedResourceFreshness !== "unknown"
          ? describeFreshness(selectedResourceFreshness, language)
          : undefined,
        selectedResourcePreviewMode,
      ].filter((value): value is string => Boolean(value))
    : [];
  const selectedResourcePreviewSummary = selectedResource
    ? resourcePreviewSummary(selectedResource)
    : undefined;
  const sandboxPreview =
    selectedResource && sandboxPreviewInput?.path === selectedResource.sandboxPath
      ? sandboxPreviewInput
      : undefined;
  const standaloneSandboxPreview = !selectedResource && restoreContext?.surface === "sandbox" &&
    sandboxPreviewInput?.path === (restoreContext.previewPath ?? restoreContext.sandboxPath)
      ? sandboxPreviewInput : undefined;
  const selectedResourceReuseSummary = selectedResource ? resourceReuseSummary(language) : undefined;
  const hasSelectedResourceFacts = Boolean(
    selectedResourceSource.length || selectedResourceStatusSegments.length || selectedResourceTrainingReadiness,
  );
  const selectedResourceStateLabel =
    selectedResourceIndexNotice?.label
    ?? selectedResourceTrust
    ?? (selectedResourceFreshness && selectedResourceFreshness !== "unknown"
      ? describeFreshness(selectedResourceFreshness, language)
      : undefined);
  const selectedResourceWhy =
    selectedResourceIndexNotice
      ? selectedResourceIndexNotice.label
      : selectedResourcePreviewSummary
        ?? (selectedResourceSourceLabel || undefined);
  const restoreContextPath = restoreContext?.sandboxPath?.trim() || undefined;
  const restoreContextPreviewPath = restoreContext?.previewPath?.trim() || undefined;
  const restoreContextMeta = restoreContext
    ? [restoreContext.focusArea, restoreContextPath]
        .map((value) => value?.trim())
        .filter((value): value is string => Boolean(value))
        .join(" | ")
    : "";
  const leftoverStoredNote = leftoverNote?.trim() || "";
  const omitLeftoverLibrary = Boolean(leftoverStoredNote) && resources.length === 0
    && resourceWriteAccess?.allowed !== true;
  // The folder section is part of the live Library, so a leftover-only
  // placeholder does not render it.
  const showLibraryFolders = !omitLeftoverLibrary;
  const orientationTone = orientation ? coachOrientationTone(orientation.state) : undefined;
  const orientationState = leftoverStoredNote
    ? undefined
    : orientation
      ? orientationStateLabel(orientation.state, language)
      : undefined;
  const orientationCanAct = Boolean(
    orientation &&
      onOrientationAction &&
      orientation.primaryActionLabel &&
      orientation.primaryAction !== "wait" &&
      orientation.primaryAction !== "wait_index" &&
      orientation.primaryAction !== "select_resource",
  );

  useEffect(() => {
    const activeSurface =
      restoreContext?.surface === "sandbox"
        ? "sandbox"
        : selectedResource
          ? "detail"
          : "library";
    onDebugVisibleFacts?.({
      surface: "resources",
      activeView: "resources",
      activeSurface,
      visibleTitle: orientation?.objectLabel ?? selectedResource?.title ?? localize(language, "title"),
      visibleSummary: orientation?.why ?? selectedResource?.summary,
      resourceDetailVisible: Boolean(selectedResource),
      resourceDetailId: selectedResource?.id,
      resourceDetailTitle: selectedResource?.title,
      selectedResourceId: selectedResource?.id,
      sandboxPreviewEmbedded: Boolean(sandboxPreview || standaloneSandboxPreview),
      sandboxPreviewVisible: Boolean(sandboxPreview || standaloneSandboxPreview),
      sandboxPreviewPath: (sandboxPreview ?? standaloneSandboxPreview)?.path,
      selectedSandboxPath: restoreContext?.sandboxPath ?? sandboxRoot,
      previewPath: restoreContext?.previewPath,
      singleWorkbenchSurface: true,
      compactMode: true,
      modebarHiddenInCompact: true,
      detailPaneVisible: Boolean(selectedResource || standaloneSandboxPreview),
      // Sandbox restore is a logical scope; its content uses ResourceReader.
      // No separate sandbox pane is rendered by this template.
      sandboxPaneVisible: false,
      previewPaneVisible: false,
    });
  }, [language, onDebugVisibleFacts, orientation, restoreContext, sandboxRoot, selectedResource, sandboxPreview, standaloneSandboxPreview]);

  return (
    <section
      className={`workbench-pane resources-pane resources-pane--library resources-knowledge resources-knowledge--workspace-tree${selectedResource ? " is-detail-open" : ""}`}
      data-resource-library-container="true"
      aria-label={localize(language, "title")}
      data-resources-leftover-not-live={leftoverStoredNote ? "true" : undefined}
    >
      <div className="workbench-pane__heading resources-knowledge__heading sr-only">
        <h2>{localize(language, "title")}</h2>
      </div>
      <Library hidden={Boolean(selectedResource || standaloneSandboxPreview)} toolbar={omitLeftoverLibrary ? null : (
      <div className="resources-knowledge__toolbar">
        <label className="resources-search resources-search--hero resources-knowledge__search">
          <span className="sr-only">{localize(language, "searchPlaceholder")}</span>
          <SearchIcon size={13} aria-hidden="true" />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={compactResourceSearchPlaceholder[language]}
          />
        </label>

        <div className="resources-knowledge__actions" aria-label={localize(language, "title")}>
          {onExpandToEditor && expandToEditorLabel ? (
            <WorkbenchSurfaceButton
              mode="expand"
              label={expandToEditorLabel}
              onClick={onExpandToEditor}
            />
          ) : null}
          <div className="resources-knowledge__import-menu-wrap">
            <button
              ref={importMenuTriggerRef}
              className={`button ${orientationCanAct ? "button--ghost" : "button--accent"} button--compact resources-knowledge__add-resource${canWriteResources && isImportMenuOpen ? " is-open" : ""}`}
              type="button"
              aria-haspopup="menu"
              aria-expanded={canWriteResources && isImportMenuOpen}
              aria-controls={canWriteResources && isImportMenuOpen ? importMenuId : undefined}
              disabled={!canWriteResources}
              aria-label={localize(language, "addResource")}
              title={resourceWriteBlockedReason ?? localize(language, "addResource")}
              onClick={toggleImportMenu}
              onKeyDown={(event) => {
                if (event.key === "ArrowDown") {
                  event.preventDefault();
                  openImportMenu(true);
                } else if (event.key === "Escape" && isImportMenuOpen) {
                  event.preventDefault();
                  closeImportMenu();
                }
              }}
            >
              <UploadIcon size={14} aria-hidden="true" />
              <span>{localize(language, "addResource")}</span>
              <ChevronDownIcon size={12} aria-hidden="true" />
            </button>
          </div>
        </div>
      </div>
      )}>


      {leftoverStoredNote ? (
        <p
          className="coach-plan-view__leftover-note"
          data-resources-leftover-note="true"
          role="status"
          aria-live="polite"
        >
          {leftoverStoredNote}
        </p>
      ) : null}

      {orientationState && (orientation?.state === "needs_setup" || orientationTone === "blocker" || !canWriteResources) ? (
        <SystemState kind={orientation?.state === "needs_setup" ? "empty" : orientationTone === "blocker" ? "recoverable-error" : "read-only"}
          title={orientationState} detail={orientation?.why}
          action={orientation && orientationCanAct ? { label: orientation.primaryActionLabel, onClick: () => onOrientationAction?.(orientation.primaryAction) } : undefined} />
      ) : orientation?.why && resources.length > 0 ? <p className="template-metadata">{orientation.why}</p> : null}

      {isImportMenuOpen && canWriteResources ? (
        <div
          ref={importMenuRef}
          id={importMenuId}
          className="resources-knowledge__import-menu menu-list is-compact"
          role="menu"
          aria-label={localize(language, "addResource")}
          onKeyDown={handleImportMenuKeyDown}
        >
          <button
            className="menu-list__item"
            type="button"
            role="menuitem"
            onClick={() => runImportAction(onImportFiles)}
          >
            <span className="menu-list__icon" aria-hidden="true">
              <UploadIcon size={13} />
            </span>
            <span className="menu-list__body">
              <strong>{t("addFiles")}</strong>
            </span>
          </button>
          <button
            className="menu-list__item"
            type="button"
            role="menuitem"
            onClick={() => runImportAction(onImportFolder)}
          >
            <span className="menu-list__icon" aria-hidden="true">
              <FolderIcon size={13} />
            </span>
            <span className="menu-list__body">
              <strong>{t("addFolder")}</strong>
            </span>
          </button>
          <button
            className="menu-list__item"
            type="button"
            role="menuitem"
            onClick={() => runImportAction(onImportUrl)}
            disabled={isBrowserPreview && !isLiveBrowserPreview}
            aria-label={
              isBrowserPreview && !isLiveBrowserPreview
                ? localize(language, "browserPreviewMutationNotice")
                : localize(language, "captureWebSnapshot")
            }
            title={
              isBrowserPreview && !isLiveBrowserPreview
                ? localize(language, "browserPreviewMutationNotice")
                : localize(language, "captureWebSnapshot")
            }
          >
            <span className="menu-list__icon" aria-hidden="true">
              <LinkIcon size={13} />
            </span>
            <span className="menu-list__body">
              <strong>{localize(language, "captureWebSnapshot")}</strong>
            </span>
          </button>
        </div>
      ) : null}

      {urlImportOpen && onCaptureResource && canWriteResources ? (
        <form
          className="resources-knowledge__url-import"
          role="group"
          aria-label={localize(language, "addUrlTitle")}
          onSubmit={(event) => {
            event.preventDefault();
            submitUrlImport();
          }}
        >
          <label className="resources-knowledge__url-import-field">
            <span>{localize(language, "addUrlTitle")}</span>
            <input
              type="url"
              inputMode="url"
              autoFocus
              value={urlImportValue}
              onChange={(event) => setUrlImportValue(event.target.value)}
              placeholder={localize(language, "addUrlPlaceholder")}
              aria-label={localize(language, "addUrlPlaceholder")}
              disabled={urlImportState?.phase === "busy"}
            />
          </label>
          {captureFocusOptions && captureFocusOptions.length > 0 ? (
            <label className="resources-knowledge__url-import-field">
              <span>{localize(language, "addUrlFocusLabel")}</span>
              <select
                value={urlImportFocusId}
                onChange={(event) => setUrlImportFocusId(event.target.value)}
                aria-label={localize(language, "addUrlFocusLabel")}
                disabled={urlImportState?.phase === "busy"}
              >
                <option value="">{localize(language, "addUrlFocusNone")}</option>
                {captureFocusOptions.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <div className="resources-knowledge__url-import-check">
            <button
              className="button button--ghost button--compact"
              type="button"
              role="switch"
              aria-checked={urlImportDownload}
              onClick={() => setUrlImportDownload((current) => !current)}
              disabled={urlImportState?.phase === "busy"}
            >
              <span>{localize(language, "addUrlDownloadLabel")}</span>
            </button>
          </div>
          {urlImportDownload ? (
            libraryFolderEntries.length > 0 ? (
              <label className="resources-knowledge__url-import-field">
                <span>{localize(language, "addUrlTargetFolderLabel")}</span>
                <select
                  value={urlImportTargetDir}
                  onChange={(event) => {
                    if (event.target.value === "__new-library-folder__") {
                      openFolderCreatePrompt("", undefined, true);
                      return;
                    }
                    setUrlImportTargetDir(event.target.value);
                  }}
                  aria-label={localize(language, "addUrlTargetFolderLabel")}
                  disabled={urlImportState?.phase === "busy"}
                >
                  <option value="">{localize(language, "addUrlTargetFolderRoot")}</option>
                  {libraryFolderEntries.map((entry) => (
                    <option key={entry.path} value={entry.path}>
                      {`${"  ".repeat(entry.depth + 1)}${entry.name} (${entry.resourceCount})`}
                    </option>
                  ))}
                  <option value="__new-library-folder__">
                    {localize(language, "addUrlTargetFolderNew")}
                  </option>
                </select>
              </label>
            ) : (
              <label className="resources-knowledge__url-import-field">
                <span>{localize(language, "addUrlTargetFolderLabel")}</span>
                <input
                  type="text"
                  value={urlImportTargetDir}
                  onChange={(event) => setUrlImportTargetDir(event.target.value)}
                  placeholder={localize(language, "addUrlTargetFolderPlaceholder")}
                  aria-label={localize(language, "addUrlTargetFolderLabel")}
                  disabled={urlImportState?.phase === "busy"}
                />
              </label>
            )
          ) : null}
          <div className="resources-knowledge__url-import-actions">
            <button
              className="button button--accent button--compact"
              type="submit"
              disabled={urlImportState?.phase === "busy" || !urlImportValue.trim()}
              aria-busy={urlImportState?.phase === "busy"}
            >
              {localize(language, "addUrlSubmit")}
            </button>
            <button
              className="button button--ghost button--compact"
              type="button"
              onClick={closeUrlImportForm}
              disabled={urlImportState?.phase === "busy"}
            >
              {t("cancel")}
            </button>
            {urlImportState?.message ? (
              <span
                className="resources-knowledge__url-import-status"
                data-url-import-phase={urlImportState.phase}
                role="status"
                aria-live="polite"
              >
                {urlImportState.phase === "busy" ? (
                  <span className="trainer-spinner" aria-hidden="true" />
                ) : null}
                {urlImportState.message}
                {/* A requested download with no reported path states that
                    honestly instead of pointing at a guess. */}
                {urlImportState.downloadUnconfirmed ? (
                  <em className="resources-knowledge__url-import-note">
                    {localize(language, "addUrlDownloadPending")}
                  </em>
                ) : null}
              </span>
            ) : null}
            {/* A confirmed download offers the host's existing open/reveal
                actions outside the live region, so the status stays text. */}
            {urlImportState?.savedPath ? (
              <>
                {urlImportState.resourceId && onOpenResource ? (
                  <button
                    className="button button--ghost button--compact"
                    type="button"
                    onClick={() => onOpenResource(urlImportState.resourceId!)}
                  >
                    {localize(language, "addUrlOpenFile")}
                  </button>
                ) : null}
                {onRevealSavedPath ? (
                  <button
                    className="button button--ghost button--compact"
                    type="button"
                    onClick={() => onRevealSavedPath(urlImportState.savedPath!)}
                  >
                    {localize(language, "addUrlRevealFile")}
                  </button>
                ) : null}
              </>
            ) : null}
          </div>
        </form>
      ) : null}

      {null}

      {omitLeftoverLibrary ? null : restoreContext?.surface === "sandbox" ? (
        <div className="resources-inline-context" role="status">
          <strong className="resources-inline-context__title">
            {restoredSandboxContextTitle(language)}
          </strong>
          {restoreContextPreviewPath ? <p>{restoreContextPreviewPath}</p> : null}
          {!restoreContextPreviewPath && restoreContext.summary?.trim() ? (
            <p>{restoreContext.summary}</p>
          ) : null}
          {restoreContextMeta ? (
            <p className="resources-inline-context__meta">{restoreContextMeta}</p>
          ) : null}
        </div>
      ) : null}

      {searchStatus ? <SystemState kind={searchStatus.tone === "failed" ? "recoverable-error" : searchStatus.tone === "pending" ? "processing" : "information"} title={searchStatus.label} /> : null}

      {organizationConfirm ? (
        <div
          className="resources-knowledge__organization-confirmation"
          role="group"
          aria-labelledby="resources-organization-confirmation-message"
        >
          {(() => {
            const organizationCopy = resolveResourceOrganizationConfirmCopy(language);
            const message =
              typeof organizationConfirm.operationCount === "number" &&
              organizationConfirm.operationCount > 0
                ? organizationCopy.messageWithCount.replace(
                    "{count}",
                    String(organizationConfirm.operationCount),
                  )
                : organizationCopy.message;
            return (
              <>
                <span id="resources-organization-confirmation-message">{message}</span>
                <div className="resources-knowledge__organization-confirmation-actions">
                  <button
                    className="button button--compact"
                    type="button"
                    aria-label={organizationCopy.cancel}
                    onClick={organizationConfirm.onCancel}
                  >
                    <span>{organizationCopy.cancel}</span>
                  </button>
                  <button
                    className="button button--primary button--compact resources-knowledge__confirm-organization-action"
                    type="button"
                    autoFocus
                    aria-label={organizationCopy.confirm}
                    onClick={organizationConfirm.onConfirm}
                  >
                    <span>{organizationCopy.confirm}</span>
                  </button>
                </div>
              </>
            );
          })()}
        </div>
      ) : null}

      {mutationStatus ? <SystemState kind={mutationStatus.tone === "failed" ? "recoverable-error" : mutationStatus.tone === "pending" ? "processing" : "success"} title={mutationStatus.label}
        action={mutationStatus.tone === "failed" && onRefreshDeletedResources ? { label: localize(language, "refreshTrash"), onClick: onRefreshDeletedResources } : undefined} /> : null}

      {omitLeftoverLibrary ? null : (
      <div
        className="resources-knowledge__tree"
        ref={treeRef}
        role="tree"
        aria-label={localize(language, "title")}
        onKeyDown={handleTreeKeyDown}
      >
        {isResourceListLoading ? (
          <div className="resources-skeleton-list" aria-hidden="true">
            <div className="skeleton resources-skeleton-row" />
            <div className="skeleton resources-skeleton-row" />
            <div className="skeleton resources-skeleton-row" />
          </div>
        ) : (
          <>
            {visibleResourceTree.map((node) => (
              <ResourceTreeItem
                key={node.id}
                node={node}
                depth={0}
                language={language}
                expandedIds={renderedExpandedCollectionIds}
                selectedResourceId={selectedResourceId}
                activeTreeItemId={resolvedActiveTreeItemId}
                onToggle={toggleCollection}
                onSelect={selectResource}
                onOpen={openResourceInVsCode}
                onActiveTreeItemChange={(id) => setActiveTreeItemId(id)}
                onMoveTreeFocus={moveTreeFocus}
              />
            ))}

            {/* The orientation card already covers the zero-resource guidance
                ("needs setup / library is empty" + import action); rendering
                this generic empty block too duplicated the same message. */}
            {resources.length === 0 && !hasSearchQuery && orientation?.state !== "needs_setup" ? (
              <SystemState kind="empty" title={localize(language, "emptyTitle")} detail={localize(language, "emptyBody")} />
            ) : null}

            {shouldShowNoMatches ? (
              <SystemState kind="empty" title={localize(language, "noMatches")} />
            ) : null}
          </>
        )}

      {showLibraryFolders ? (
        <details
          className="resources-knowledge__folders"
          data-library-folders="true"
          open={libraryFoldersOpen}
          onToggle={(event) => setLibraryFoldersOpen(event.currentTarget.open)}
          aria-busy={libraryFoldersState.phase === "loading"}
        >
          <summary>
            <span>
              <FolderIcon size={13} aria-hidden="true" />
              <strong>
                {localize(language, "foldersTitle")}
                {libraryFolderEntries.length > 0 ? ` (${libraryFolderEntries.length})` : ""}
              </strong>
            </span>
          </summary>
          <div className="resources-knowledge__folders-body">
            <div className="resources-knowledge__folders-actions">
              {canWriteResources && onCreateLibraryFolder ? (
                <button
                  className="button button--ghost button--compact"
                  type="button"
                  onClick={() => openFolderCreatePrompt()}
                >
                  <PlusIcon size={12} aria-hidden="true" />
                  <span>{localize(language, "foldersNew")}</span>
                </button>
              ) : null}
              {onListLibraryFolders ? (
                <button
                  className="button button--ghost button--compact"
                  type="button"
                  onClick={() => loadLibraryFolders()}
                  disabled={libraryFoldersState.phase === "loading"}
                  aria-busy={libraryFoldersState.phase === "loading"}
                >
                  <RefreshIcon size={12} aria-hidden="true" />
                  <span>{localize(language, "foldersRefresh")}</span>
                </button>
              ) : null}
            </div>
            {libraryFoldersState.phase === "loading" ? (
              <p className="resources-knowledge__folders-status" role="status" aria-live="polite">
                <span className="trainer-spinner" aria-hidden="true" />
                {localize(language, "foldersLoading")}
              </p>
            ) : null}
            {libraryFoldersState.phase === "failed" ? (
              <p
                className="resources-knowledge__folders-status"
                role="status"
                aria-live="polite"
                data-folders-phase="failed"
              >
                {libraryFoldersState.message
                  ? localizeValue(language, "foldersFailed", libraryFoldersState.message)
                  : localize(language, "foldersUnavailable")}
              </p>
            ) : libraryFolderEntries.length === 0 ? (
              // One honest line at a time: when reading folders failed, the
              // "no folders yet" hint must not claim the same list is empty.
              <p className="resources-empty resources-empty--compact">
                {localize(
                  language,
                  canWriteResources ? "foldersEmpty" : "foldersEmptyReadOnly",
                )}
              </p>
            ) : (
              <ul className="resources-knowledge__folders-tree">
                {visibleFolderEntries.map((entry) =>
                  renderLibraryFolderRow(entry, folderPathsWithChildren.has(entry.path)),
                )}
              </ul>
            )}
            {selectedFolderEntry ? (
              <div
                className="resources-knowledge__folder-actions"
                role="group"
                aria-label={selectedFolderEntry.path}
              >
                <span className="resources-knowledge__folder-actions-path" title={selectedFolderEntry.path}>
                  {selectedFolderEntry.path}
                </span>
                {canWriteResources && onRenameLibraryFolder ? (
                  <button
                    className="button button--ghost button--compact"
                    type="button"
                    onClick={() => {
                      setFolderPromptState(undefined);
                      setFolderPrompt({
                        mode: "rename",
                        parentPath: libraryFolderParentPath(selectedFolderEntry.path),
                        path: selectedFolderEntry.path,
                        value: libraryFolderName(selectedFolderEntry.path),
                      });
                    }}
                  >
                    {localize(language, "folderRenameAction")}
                  </button>
                ) : null}
                {canWriteResources && onCreateLibraryFolder ? (
                  <button
                    className="button button--ghost button--compact"
                    type="button"
                    onClick={() => openFolderCreatePrompt(selectedFolderEntry.path)}
                  >
                    {localize(language, "folderSubfolderAction")}
                  </button>
                ) : null}
                {canWriteResources && onDeleteLibraryFolder ? (
                  <button
                    className="button button--ghost button--compact resources-knowledge__folder-delete-action"
                    type="button"
                    onClick={() => requestFolderDelete(selectedFolderEntry.path)}
                  >
                    <TrashIcon size={12} aria-hidden="true" />
                    <span>{localize(language, "folderDeleteAction")}</span>
                  </button>
                ) : null}
              </div>
            ) : null}
            {folderMutationState?.message ? (
              <p
                className="resources-knowledge__folders-status"
                role="status"
                aria-live="polite"
                data-folder-mutation-phase={folderMutationState.phase}
              >
                {folderMutationState.message}
              </p>
            ) : null}
          </div>
        </details>
      ) : null}

      {omitLeftoverLibrary || trashedResources.length === 0 ? null : (
      <details
        className="resources-knowledge__trash resources-library-tree__trash"
        open={trashOpen}
        onToggle={(event) => setTrashOpen(event.currentTarget.open)}
        aria-busy={isRestorePending}
      >
        <summary>
          <span>
            <TrashIcon size={13} aria-hidden="true" />
            {/* r1-g2-1: one expression — "回收站 (1)" — instead of a title row
                plus a second count sentence on the far edge. */}
            <strong>
              {localize(language, "trashTitle")}
              {trashSnapshotAvailable ? ` (${trashedResources.length})` : ""}
            </strong>
          </span>
        </summary>
        <div className="resources-knowledge__trash-body">
          {!trashSnapshotAvailable ? (
            <p className="resources-empty resources-empty--compact">
              {localize(language, "trashLoading")}
            </p>
          ) : null}
          {trashSnapshotAvailable && trashedResources.length === 0 ? (
            <p className="resources-empty resources-empty--compact">
              {localize(language, "trashEmpty")}
            </p>
          ) : null}
          {trashSnapshotAvailable && trashedResources.length > 0 ? (
            <ul className="resources-knowledge__trash-list">
              {trashedResources.map((resource, index) => {
                const resourceId = deletedResourceId(resource);
                const canRestore = isDeletedResourceRecoverable(resource);
                const restorePendingForItem =
                  resourceId !== undefined && pendingRestoredResourceIds.includes(resourceId);
                const restoreLabel = localize(language, "restoreResource");
                const restoreTitle = `${restoreLabel}: ${resource.title}`;
                const restoreDisabledReason = !canWriteResources
                  ? resourceWriteBlockedReason ?? resourceReadOnlyNotice(language)
                  : isBrowserPreview
                    ? localize(language, "browserPreviewMutationNotice")
                    : restoreUnavailableReason;
                return (
                  <li key={resourceId ?? `unknown-deleted-resource-${index}`}>
                    <span className="resources-knowledge__trash-item-title" title={resource.title}>
                      {resource.title}
                    </span>
                    {resource.collectionPath ? (
                      <span className="resources-knowledge__trash-item-path" title={resource.collectionPath}>
                        {resource.collectionPath}
                      </span>
                    ) : null}
                    {!canRestore ? (
                      <span className="resources-knowledge__trash-item-status">
                        {localize(language, "notRestorable")}
                      </span>
                    ) : null}
                    {canRestore && onRestoreResources && resourceId ? (
                      <button
                        className="button button--compact resources-knowledge__restore-action"
                        type="button"
                        onClick={() => restoreDeletedResource(resourceId)}
                        disabled={!canWriteResources || isBrowserPreview || !onRestoreResources || isDeletePending || isRestorePending}
                        aria-busy={restorePendingForItem}
                        aria-label={restoreTitle}
                        title={restoreDisabledReason ?? restoreTitle}
                      >
                        <RefreshIcon size={12} />
                        <span>{restoreLabel}</span>
                      </button>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          ) : null}
        </div>
      </details>
      )}
      </div>
      )}

      </Library>

      {/* Delete confirmation lives at the root so it stays reachable while the
          reader is open — the Library container is hidden behind the reader. */}
      {deleteConfirmationResourceIds ? (
        <div
          className="resources-knowledge__delete-confirmation"
          role="alertdialog"
          aria-modal="false"
          aria-labelledby="resources-delete-confirmation-message"
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              cancelDeleteSelectedResources();
            }
          }}
        >
          <span id="resources-delete-confirmation-message">
            {deleteConfirmationResourceIds.length === 1
              ? localize(language, "deleteResourceConfirmation")
              : localizeCount(language, "deleteConfirmation", deleteConfirmationResourceIds.length)}
          </span>
          <div className="resources-knowledge__delete-confirmation-actions">
            <button
              ref={deleteConfirmationFocusRef}
              className="button button--compact"
              type="button"
              onClick={cancelDeleteSelectedResources}
            >
              <span>{t("cancel")}</span>
            </button>
            <button
              className="button button--compact resources-knowledge__confirm-delete-action"
              type="button"
              onClick={confirmDeleteSelectedResources}
            >
              <TrashIcon size={13} />
              <span>{t("confirm")}</span>
            </button>
          </div>
        </div>
      ) : null}

      {/* Folder name prompt and folder deletion confirmation live at the root
          for the same reason as the resource delete confirmation: the Library
          container can be hidden behind the reader. */}
      {folderPrompt ? (
        <div
          className="resources-knowledge__folder-prompt"
          role="dialog"
          aria-modal="false"
          aria-labelledby="resources-folder-prompt-title"
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              setFolderPrompt(undefined);
              setFolderPromptState(undefined);
            }
          }}
        >
          <form
            className="resources-knowledge__folder-prompt-body"
            onSubmit={(event) => {
              event.preventDefault();
              submitFolderPrompt();
            }}
          >
            <label className="resources-knowledge__folder-prompt-field">
              <span id="resources-folder-prompt-title">
                {folderPrompt.mode === "rename"
                  ? localize(language, "folderPromptRenameTitle")
                  : folderPrompt.mode === "subfolder"
                    ? localizeValue(language, "folderPromptSubfolderTitle", folderPrompt.parentPath)
                    : localize(language, "folderPromptCreateTitle")}
              </span>
              <input
                type="text"
                autoFocus
                value={folderPrompt.value}
                onChange={(event) =>
                  setFolderPrompt((current) =>
                    current ? { ...current, value: event.target.value } : current,
                  )
                }
                placeholder={localize(language, "folderNamePlaceholder")}
                aria-label={localize(language, "folderNamePlaceholder")}
                disabled={folderPromptState?.phase === "busy"}
              />
            </label>
            {folderPromptState?.message ? (
              <p
                className="resources-knowledge__folders-status"
                role="status"
                aria-live="polite"
                data-folder-prompt-phase={folderPromptState.phase}
              >
                {folderPromptState.message}
              </p>
            ) : null}
            <div className="resources-knowledge__folder-prompt-actions">
              <button
                className="button button--compact"
                type="button"
                onClick={() => {
                  setFolderPrompt(undefined);
                  setFolderPromptState(undefined);
                }}
                disabled={folderPromptState?.phase === "busy"}
              >
                <span>{t("cancel")}</span>
              </button>
              <button
                className="button button--primary button--compact"
                type="submit"
                disabled={folderPromptState?.phase === "busy" || !folderPrompt.value.trim()}
                aria-busy={folderPromptState?.phase === "busy"}
              >
                <span>
                  {folderPrompt.mode === "rename"
                    ? localize(language, "folderRenameConfirm")
                    : localize(language, "folderCreateConfirm")}
                </span>
              </button>
            </div>
          </form>
        </div>
      ) : null}

      {folderDeletePath ? (
        <div
          className="resources-knowledge__folder-delete-confirmation"
          role="alertdialog"
          aria-modal="false"
          aria-labelledby="resources-folder-delete-confirmation-message"
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              setFolderDeletePath(null);
            }
          }}
        >
          <span id="resources-folder-delete-confirmation-message">
            {localizeValue(language, "folderDeleteConfirmation", folderDeletePath)}
          </span>
          <div className="resources-knowledge__delete-confirmation-actions">
            <button
              className="button button--compact"
              type="button"
              autoFocus
              onClick={() => setFolderDeletePath(null)}
              disabled={folderDeleteBusy}
            >
              <span>{t("cancel")}</span>
            </button>
            <button
              className="button button--compact resources-knowledge__confirm-delete-action"
              type="button"
              onClick={confirmFolderDelete}
              disabled={folderDeleteBusy}
              aria-busy={folderDeleteBusy}
            >
              <TrashIcon size={13} />
              <span>{t("confirm")}</span>
            </button>
          </div>
        </div>
      ) : null}

      {standaloneSandboxPreview ? (
        <ResourceReader parent={localize(language, "title")} title={(standaloneSandboxPreview.relativePath ?? standaloneSandboxPreview.path ?? "").split(/[\\/]/).pop() ?? resourcePreviewHeading(language)} source={standaloneSandboxPreview.path} onBack={() => { setResourceDetail(null); onRestoreContextChange?.(undefined); }}>
          {standaloneSandboxPreview.previewKind === "markdown" ? <MessageRichContent body={previewBodyWithoutCaptureFrontmatter(standaloneSandboxPreview.content ?? standaloneSandboxPreview.excerpt ?? "")} language={language} /> : <pre className="resources-knowledge__content-preview-body">{standaloneSandboxPreview.content ?? standaloneSandboxPreview.excerpt ?? standaloneSandboxPreview.html ?? ""}</pre>}
        </ResourceReader>
      ) : null}

      {selectedResource ? (
        <ResourceReader
          parent={localize(language, "title")}
          title={selectedResource.title}
          source={selectedResourceSourceLabel}
          updatedAt={selectedResource.updatedAt}
          onBack={() => setResourceDetail(null)}
          askCoach={onAskCoach ? { label: templateCopy[language].askCoach, onClick: () => onAskCoach([selectedResource.id]) } : undefined}
          joinLearning={onJoinLearning ? { label: templateCopy[language].joinLearning, onClick: () => onJoinLearning([selectedResource.id]) } : undefined}
          generatePractice={!sandboxPreview && selectedResourceCanStartTraining ? {
            label: selectedResourceTrainingIsAvailable ? localize(language, "openCurrentTraining") : templateCopy[language].generatePractice,
            onClick: selectedResourceTrainingIsAvailable ? () => onOpenTraining?.() : startTrainingFromSelectedResource,
            disabled: selectedResourceTrainingIsAvailable ? !onOpenTraining : !onStartTrainingFromResource,
            busy: selectedResourceTrainingState?.phase === "loading",
          } : undefined}
        >
          <section className="resources-knowledge__detail-object" aria-label={selectedResource.title}>
          {sandboxPreview ? (
            <div className="resources-knowledge__content-preview" aria-label={resourcePreviewHeading(language)}>
              {sandboxPreview.previewKind === "markdown" ||
              /\.md(?:own|own)?$/i.test(sandboxPreview.path ?? sandboxPreview.relativePath ?? "") ? (
                <div className="resources-knowledge__content-preview-body resources-knowledge__content-preview-body--markdown">
                  <MessageRichContent
                    body={previewBodyWithoutDuplicateTitle(
                      sandboxPreview.content ?? sandboxPreview.excerpt ?? "",
                      selectedResource.title,
                    )}
                    language={language}
                  />
                </div>
              ) : sandboxPreview.html ? (
                <pre className="resources-knowledge__content-preview-body">{sandboxPreview.html}</pre>
              ) : sandboxPreview.content || sandboxPreview.excerpt ? (
                <pre className="resources-knowledge__content-preview-body">
                  {sandboxPreview.content ?? sandboxPreview.excerpt}
                </pre>
              ) : (
                <div className="resources-knowledge__content-preview-empty">
                  {selectedResourcePreviewMode ?? resourcePreviewHeading(language)}
                </div>
              )}
            </div>
          ) : selectedResourceWhy || selectedResourcePreviewSummary ? (
            <div className="resources-knowledge__sentence">
              {selectedResourceWhy ? (
                <p className="resources-knowledge__why">{selectedResourceWhy}</p>
              ) : (
                <p className="resources-knowledge__preview-summary">{selectedResourcePreviewSummary}</p>
              )}
            </div>
          ) : null}

          {!sandboxPreview && (hasSelectedResourceFacts || selectedResourceTrainingState || selectedResourceCanStartTraining) ? (
            <>
            <dl className="resources-knowledge__facts">
              {selectedResourceSource.length > 0 ? (
                <div className="resources-knowledge__fact resources-knowledge__fact--source">
                  <dt>{localize(language, "source")}</dt>
                  <dd title={selectedResourceSource.join(" / ")}>{selectedResourceSourceLabel}</dd>
                </div>
              ) : null}
              {selectedResourceStatusSegments.length > 0 ? (
                <div className="resources-knowledge__fact resources-knowledge__fact--status">
                  <dt>{localize(language, "status")}</dt>
                  <dd title={selectedResourceStatusSegments.join(" \u00b7 ")}>
                    {selectedResourceStatusSegments.join(" \u00b7 ")}
                    {selectedResourceTrainingReadiness?.tone === "unavailable" &&
                    selectedResourceTrainingReadiness.message ? (
                      <small className="resources-knowledge__fact-note">
                        {selectedResourceTrainingReadiness.message}
                      </small>
                    ) : null}
                  </dd>
                </div>
              ) : null}
            </dl>
          {selectedResourceReuseSummary ? (
            <p className="resources-knowledge__reuse-summary">{selectedResourceReuseSummary}</p>
          ) : null}

          {selectedResourceTrainingState || selectedResourceCanStartTraining ? (
            <details className="resources-knowledge__training-handoff">
              <summary><strong>{localize(language, "training")}</strong></summary>
              {selectedResourceTrainingState ? <SystemState kind={selectedResourceTrainingState.phase === "loading" ? "processing" : selectedResourceTrainingState.phase === "failed" ? "recoverable-error" : "information"} title={selectedResourceTrainingStatusMessage ?? localize(language, "training")} /> : null}
            </details>
          ) : null}
          </>
          ) : null}
          {!sandboxPreview ? (
          <>
            {/* The obvious "read this" action stays visible; everything that
                manages the file hides behind one clearly-owned section, so
                the reader shows a single primary row plus collapsed groups. */}
            {onPreviewResource && selectedResource.sandboxPath ? (
              <div className="resources-knowledge__detail-actions resources-knowledge__detail-actions--preview">
                <button
                  className="button button--primary button--compact"
                  type="button"
                  onClick={() => onPreviewResource(selectedResource.id)}
                  disabled={isBrowserPreview && !isLiveBrowserPreview}
                >
                  <ArrowRightIcon size={12} />
                  <span>{resourcePreviewHeading(language)}</span>
                </button>
              </div>
            ) : null}
          <details
            className="resources-knowledge__file-actions"
            open={exportState?.message ? true : undefined}
          >
            <summary>
              <strong>{localize(language, "fileActionsTitle")}</strong>
            </summary>
            <div className="resources-knowledge__detail-actions">
            {selectedResourceTrainingReadiness?.canRefresh ? (
              <button
                className="button button--ghost button--compact"
                type="button"
                onClick={refreshResources}
                disabled={indexActionDisabled}
                aria-busy={isIndexRefreshing}
              >
                <RefreshIcon size={12} />
                <span>{refreshResourcesLabel}</span>
              </button>
            ) : null}
            <button
              className="button button--ghost button--compact resources-knowledge__open-action"
              type="button"
              onClick={() => openResourceInVsCode(selectedResource)}
              disabled={selectedResourceOpenTarget.kind === "unavailable"}
              aria-label={`${selectedResourceOpenLabel}: ${selectedResource.title}`}
              title={selectedResourceOpenLabel}
            >
              <ArrowRightIcon size={12} />
              <span>{selectedResourceOpenLabel}</span>
            </button>
            {onExportResource && canWriteResources ? (
              <button
                className="button button--ghost button--compact resources-knowledge__export-action"
                type="button"
                onClick={() => exportSelectedResource(selectedResource.id)}
                disabled={exportState?.phase === "busy"}
                aria-busy={exportState?.phase === "busy"}
                aria-label={`${localize(language, "exportAction")}: ${selectedResource.title}`}
                title={localize(language, "exportAction")}
              >
                <span>{localize(language, "exportAction")}</span>
              </button>
            ) : null}
            {onDeleteResources ? (
              <button
                className="button button--ghost button--compact resources-knowledge__delete-action"
                type="button"
                onClick={() => requestResourceDelete(selectedResource.id)}
                disabled={deleteActionDisabled}
                aria-busy={pendingDeletedResourceIds.includes(selectedResource.id)}
                aria-label={`${localize(language, "deleteResource")}: ${selectedResource.title}`}
                title={
                  deleteActionDisabled
                    ? resourceWriteBlockedReason
                      ?? deleteUnavailableReason
                      ?? localize(language, "deleteResource")
                    : `${localize(language, "deleteResource")}: ${selectedResource.title}`
                }
              >
                <TrashIcon size={12} />
                <span>{localize(language, "deleteResource")}</span>
              </button>
            ) : null}
            {exportState?.message ? (
              <p
                className="resources-knowledge__organize-status"
                data-export-phase={exportState.phase}
                role="status"
                aria-live="polite"
              >
                {exportState.message}
              </p>
            ) : null}
            {organizeState?.message ? (
              <p
                className="resources-knowledge__organize-status"
                data-organize-phase={organizeState.phase}
                role="status"
                aria-live="polite"
              >
                {organizeState.message}
              </p>
            ) : null}
            </div>
          </details>
          </>
          ) : null}

          {!sandboxPreview && onOrganizeResource && canWriteResources ? (
            <details className="resources-knowledge__organize" data-resource-organize="true">
              <summary>
                <strong>{localize(language, "organizeTitle")}</strong>
              </summary>
              <div className="resources-knowledge__organize-body">
                <div
                  className="resources-knowledge__organize-field"
                  role="group"
                  aria-label={localize(language, "organizeRenameLabel")}
                >
                  <span>{localize(language, "organizeRenameLabel")}</span>
                  <input
                    type="text"
                    value={organizeRenameValue}
                    onChange={(event) => setOrganizeRenameValue(event.target.value)}
                    aria-label={localize(language, "organizeRenameLabel")}
                    disabled={organizeState?.phase === "busy"}
                  />
                  <button
                    className="button button--ghost button--compact"
                    type="button"
                    onClick={() =>
                      runOrganizeAction({ action: "rename", title: organizeRenameValue.trim() })
                    }
                    disabled={organizeState?.phase === "busy" || !organizeRenameValue.trim()}
                  >
                    {localize(language, "organizeRenameAction")}
                  </button>
                </div>
                <div
                  className="resources-knowledge__organize-field"
                  role="group"
                  aria-label={localize(language, "organizeTagsLabel")}
                >
                  <span>{localize(language, "organizeTagsLabel")}</span>
                  <input
                    type="text"
                    value={organizeTagsValue}
                    onChange={(event) => setOrganizeTagsValue(event.target.value)}
                    placeholder={localize(language, "organizeTagsLabel")}
                    aria-label={localize(language, "organizeTagsLabel")}
                    disabled={organizeState?.phase === "busy"}
                  />
                  <button
                    className="button button--ghost button--compact"
                    type="button"
                    onClick={() =>
                      runOrganizeAction({
                        action: "set_tags",
                        tags: organizeTagsValue
                          .split(/[,，]/)
                          .map((tag) => tag.trim())
                          .filter(Boolean),
                      })
                    }
                    disabled={organizeState?.phase === "busy"}
                  >
                    {localize(language, "organizeTagsAction")}
                  </button>
                </div>
                <div
                  className="resources-knowledge__organize-field"
                  role="group"
                  aria-label={localize(language, "organizeGroupLabel")}
                >
                  <span>{localize(language, "organizeGroupLabel")}</span>
                  {libraryFolderEntries.length > 0 ? (
                    <select
                      value={organizeGroupValue}
                      onChange={(event) => setOrganizeGroupValue(event.target.value)}
                      aria-label={localize(language, "organizeGroupLabel")}
                      disabled={organizeState?.phase === "busy"}
                    >
                      <option value="">{localize(language, "addUrlTargetFolderRoot")}</option>
                      {libraryFolderEntries.map((entry) => (
                        <option key={entry.path} value={entry.path}>
                          {`${"  ".repeat(entry.depth + 1)}${entry.name} (${entry.resourceCount})`}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type="text"
                      value={organizeGroupValue}
                      onChange={(event) => setOrganizeGroupValue(event.target.value)}
                      placeholder={localize(language, "organizeGroupPlaceholder")}
                      aria-label={localize(language, "organizeGroupPlaceholder")}
                      disabled={organizeState?.phase === "busy"}
                    />
                  )}
                  <button
                    className="button button--ghost button--compact"
                    type="button"
                    onClick={() =>
                      runOrganizeAction({ action: "set_group", group: organizeGroupValue.trim() })
                    }
                    disabled={
                      organizeState?.phase === "busy" ||
                      // In select mode the root option is a real target; the
                      // free-text lane still needs a non-empty group name.
                      (!organizeGroupValue.trim() && libraryFolderEntries.length === 0)
                    }
                  >
                    {localize(language, "organizeGroupAction")}
                  </button>
                  {canWriteResources && onCreateLibraryFolder ? (
                    <button
                      className="button button--ghost button--compact"
                      type="button"
                      onClick={() => openFolderCreatePrompt("", selectedResource.id)}
                      disabled={organizeState?.phase === "busy"}
                    >
                      {localize(language, "folderMoveToNew")}
                    </button>
                  ) : null}
                  {selectedResource.collectionPath && libraryFolderEntries.length === 0 ? (
                    <button
                      className="button button--ghost button--compact"
                      type="button"
                      onClick={() => runOrganizeAction({ action: "set_group", group: "" })}
                      disabled={organizeState?.phase === "busy"}
                    >
                      {localize(language, "organizeGroupClear")}
                    </button>
                  ) : null}
                </div>
                {selectedResource.collectionPath ? (
                  <p className="template-metadata" data-resource-group-path="true">
                    {selectedResource.collectionPath}
                  </p>
                ) : null}
                {organizeState?.message ? (
                  <p
                    className="resources-knowledge__organize-status"
                    data-organize-phase={organizeState.phase}
                    role="status"
                    aria-live="polite"
                  >
                    {organizeState.message}
                  </p>
                ) : null}
              </div>
            </details>
          ) : null}
          </section>
        </ResourceReader>
      ) : null}
    </section>
  );
}

export { localize as resourceLibraryText, compactResourceSearchPlaceholder };
