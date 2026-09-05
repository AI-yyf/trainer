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
  CheckIcon,
  ChevronDownIcon,
  CloseIcon,
  FolderIcon,
  LinkIcon,
  RefreshIcon,
  SearchIcon,
  TrashIcon,
  UploadIcon,
} from "../icons";
import { CollapseSection } from "../common/CollapseSection";
import { MessageRichContent } from "../coach/MessageRichContent";

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
  onImportFiles?: () => void;
  onImportFolder?: () => void;
  onImportUrl?: () => void;
  onOpenResource?: (resourceId: string) => void;
  onPreviewResource?: (resourceId: string) => void;
  onStartTrainingFromResource?: (resourceId: string) => Promise<ResourceTrainingHandoffResult>;
  onOpenTraining?: () => void;
  onRefreshResources?: () => void | Promise<void>;
  onDeleteResources?: (resourceIds: string[]) => void | Promise<void>;
  onRestoreResources?: (resourceIds: string[]) => void | Promise<void>;
  onRefreshDeletedResources?: () => void | Promise<void>;
  onChooseWorkspaceRoot?: () => void;
  /**
   * The App owns the cross-view conversation context.  The library keeps its
   * local selection UI, but reports whether this is a deliberate selection or
   * merely an unmount so switching views does not silently discard context.
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
}

export interface ResourceRestoreContext {
  surface: "detail" | "sandbox";
  resourceId?: string;
  focusArea?: string;
  sandboxPath?: string;
  previewPath?: string;
  summary?: string;
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

type ResourceTextKey =
  | "title"
  | "addResource"
  | "searchPlaceholder"
  | "webSnapshots"
  | "references"
  | "imported"
  | "captureWebSnapshot"
  | "index"
  | "pendingIndex"
  | "indexing"
  | "indexFailed"
  | "refresh"
  | "emptyTitle"
  | "emptyBody"
  | "noMatches"
  | "searching"
  | "searchPreview"
  | "searchFailed"
  | "searchIncomplete"
  | "readOnlyNotice"
  | "browserPreviewMutationNotice"
  | "source"
  | "trust"
  | "freshness"
  | "fresh"
  | "stale"
  | "unknown"
  | "openInVsCode"
  | "openInBrowser"
  | "openUnavailable"
  | "sandboxTitle"
  | "sandboxReady"
  | "sandboxUnavailable"
  | "sandboxBoundary"
  | "sandboxPath"
  | "sandboxLinked"
  | "sandboxFiles"
  | "closeDetails"
  | "training"
  | "trainingEligible"
  | "createReviewCard"
  | "openCurrentTraining"
  | "selectResource"
  | "selectFolder"
  | "selectAllVisible"
  | "clearSelection"
  | "deleteSelected"
  | "restoreDeleted"
  | "recoveryAvailable"
  | "selectedResources"
  | "deleteConfirmation"
  | "logicalCollection"
  | "storageRoots"
  | "workspaceRoot"
  | "sandboxRoot"
  | "trashRoot"
  | "unavailable"
  | "trashTitle"
  | "trashEmpty"
  | "trashLoading"
  | "notRestorable"
  | "refreshTrash"
  | "deletePending"
  | "restorePending"
  | "deleteSucceeded"
  | "restoreSucceeded"
  | "mutationFailed"
  | "currentObject"
  | "resourceDetail";

const resourceText: Record<ResourceTextKey, { zh: string; en: string }> = {
  title: { zh: "\u8d44\u6599\u5e93", en: "Unified library" },
  addResource: { zh: "\u6dfb\u52a0\u8d44\u6599", en: "Add resource" },
  searchPlaceholder: { zh: "\u641c\u7d22\u6807\u9898\u3001\u6765\u6e90\u6216\u6458\u8981", en: "Search title, source, or summary" },
  webSnapshots: { zh: "\u7f51\u9875\u5feb\u7167", en: "Web snapshots" },
  references: { zh: "\u53c2\u8003\u8d44\u6599", en: "References" },
  imported: { zh: "\u5df2\u5bfc\u5165", en: "Imported" },
  captureWebSnapshot: { zh: "\u5bfc\u5165\u7f51\u9875\u5feb\u7167", en: "Capture webpage snapshot" },
  index: { zh: "\u7d22\u5f15", en: "Index" },
  pendingIndex: { zh: "\u5f85\u7d22\u5f15", en: "Waiting to be indexed" },
  indexing: { zh: "\u7d22\u5f15\u4e2d", en: "Indexing" },
  indexFailed: { zh: "\u5931\u8d25", en: "Failed" },
  refresh: { zh: "\u5237\u65b0\u7d22\u5f15", en: "Refresh index" },
  emptyTitle: { zh: "\u8fd8\u6ca1\u6709\u8d44\u6599", en: "No resources yet" },
  emptyBody: { zh: "\u5bfc\u5165\u6587\u4ef6\u3001\u6587\u4ef6\u5939\u6216\u7f51\u9875\u5feb\u7167\uff0c\u5b83\u4eec\u4f1a\u51fa\u73b0\u5728\u8fd9\u91cc\u4f9b\u641c\u7d22\u548c\u590d\u7528\u3002", en: "Add a file, folder, or webpage snapshot to make it available for search and reuse." },
  noMatches: { zh: "\u6ca1\u6709\u5339\u914d\u7684\u8d44\u6599", en: "No matching resources" },
  searching: { zh: "\u6b63\u5728\u641c\u7d22\u8d44\u6599...", en: "Searching resources..." },
  searchPreview: { zh: "\u4ec5\u5728\u5f53\u524d\u9884\u89c8\u4e2d\u7b5b\u9009\u3002", en: "Filtering preview resources only." },
  searchFailed: { zh: "\u6682\u65f6\u65e0\u6cd5\u641c\u7d22\u8d44\u6599\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002", en: "Couldn't search resources. Try again." },
  searchIncomplete: { zh: "\u641c\u7d22\u6ca1\u6709\u5b8c\u6210\u3002", en: "Search did not complete." },
  readOnlyNotice: { zh: "\u5f53\u524d\u9879\u76ee\u4e3a\u53ea\u8bfb\u72b6\u6001\uff1a\u53ef\u641c\u7d22\u548c\u6253\u5f00\u8d44\u6599\u3002", en: "This project is read-only. You can search and open resources." },
  browserPreviewMutationNotice: { zh: "\u6d4f\u89c8\u5668\u9884\u89c8\u4e0d\u4f1a\u66f4\u6539\u771f\u5b9e\u8d44\u6599\u3002\u8bf7\u5728 VS Code \u4fa7\u680f\u4e2d\u64cd\u4f5c\u3002", en: "Browser preview cannot change real resources. Use the VS Code sidebar." },
  source: { zh: "\u6765\u6e90", en: "Source" },
  trust: { zh: "\u4fe1\u4efb", en: "Trust" },
  freshness: { zh: "\u65b0\u9c9c\u5ea6", en: "Freshness" },
  fresh: { zh: "\u65b0\u9c9c", en: "Fresh" },
  stale: { zh: "\u5f85\u66f4\u65b0", en: "Stale" },
  unknown: { zh: "\u672a\u77e5", en: "Unknown" },
  openInVsCode: { zh: "\u5728 VS Code \u4e2d\u6253\u5f00", en: "Open in VS Code" },
  openInBrowser: { zh: "\u5728\u6d4f\u89c8\u5668\u4e2d\u6253\u5f00", en: "Open in browser" },
  openUnavailable: { zh: "\u6ca1\u6709\u53ef\u6253\u5f00\u7684\u6765\u6e90", en: "No openable source" },
  sandboxTitle: { zh: "\u53d7\u63a7\u6c99\u7bb1", en: "Guarded sandbox" },
  sandboxReady: { zh: "\u6c99\u7bb1\u53ef\u7528", en: "Sandbox available" },
  sandboxUnavailable: { zh: "\u5f85\u8fde\u63a5", en: "Waiting for connection" },
  sandboxBoundary: { zh: "\u6c99\u7bb1\u53ea\u7528\u4e8e\u8d44\u6599\u5904\u7406\u548c\u6253\u5f00\uff0c\u4e0d\u4ee3\u8868\u4f60\u7684\u9879\u76ee\u5de5\u4f5c\u533a\u3002", en: "The sandbox is for resource processing and native opening only. It is not your project workspace." },
  sandboxPath: { zh: "\u6839\u76ee\u5f55", en: "Root" },
  sandboxLinked: { zh: "\u5df2\u5173\u8054", en: "Linked" },
  sandboxFiles: { zh: "\u6587\u4ef6", en: "files" },
  closeDetails: { zh: "\u6536\u8d77\u8be6\u60c5", en: "Close details" },
  training: { zh: "\u8bad\u7ec3", en: "Training" },
  trainingEligible: { zh: "\u53ef\u8fdb\u5165\u8bad\u7ec3\u4e0e\u8ba1\u5212\u8bc1\u636e", en: "Ready for training and plan evidence" },
  createReviewCard: { zh: "\u751f\u6210\u590d\u4e60\u5361", en: "Create review card" },
  openCurrentTraining: { zh: "\u67e5\u770b\u5f53\u524d\u8bad\u7ec3", en: "Open current training" },
  selectResource: { zh: "\u9009\u62e9\u8d44\u6599", en: "Select resource" },
  selectFolder: { zh: "\u9009\u62e9\u76ee\u5f55", en: "Select folder" },
  selectAllVisible: { zh: "\u5168\u9009\u5f53\u524d\u8d44\u6599", en: "Select all visible resources" },
  clearSelection: { zh: "\u6e05\u7a7a\u9009\u62e9", en: "Clear selection" },
  deleteSelected: { zh: "\u5220\u9664\u9009\u4e2d\u8d44\u6599", en: "Delete selected resources" },
  restoreDeleted: { zh: "\u6062\u590d\u53ef\u6062\u590d\u7684\u8d44\u6599", en: "Restore available resources" },
  recoveryAvailable: { zh: "\u56de\u6536\u7ad9\u4e2d\u7684\u8d44\u6599\uff1a{count}", en: "Resources in Trash: {count}" },
  selectedResources: { zh: "\u5df2\u9009\u62e9\u8d44\u6599", en: "Selected resources" },
  deleteConfirmation: {
    zh: "\u5c06\u9009\u4e2d\u7684 {count} \u9879\u8d44\u6599\u79fb\u5165\u56de\u6536\u7ad9\uff1f\u53ef\u4ece\u53d7\u63a7\u6c99\u7bb1\u6062\u590d\u3002",
    en: "Move {count} selected resources to Trash? You can restore them from the guarded sandbox.",
  },
  logicalCollection: { zh: "\u903b\u8f91\u96c6\u5408", en: "Collection" },
  storageRoots: { zh: "\u5b58\u50a8\u4f4d\u7f6e", en: "Storage locations" },
  workspaceRoot: { zh: "\u5de5\u4f5c\u533a\u6839\u76ee\u5f55", en: "Workspace root" },
  sandboxRoot: { zh: "\u6c99\u7bb1\u6839\u76ee\u5f55", en: "Sandbox root" },
  trashRoot: { zh: "\u56de\u6536\u7ad9\u6839\u76ee\u5f55", en: "Trash root" },
  unavailable: { zh: "\u6682\u4e0d\u53ef\u7528", en: "Not available" },
  trashTitle: { zh: "\u56de\u6536\u7ad9", en: "Trash" },
  trashEmpty: { zh: "\u56de\u6536\u7ad9\u4e3a\u7a7a\u3002", en: "Trash is empty." },
  trashLoading: { zh: "\u6b63\u5728\u7b49\u5f85\u56de\u6536\u7ad9\u72b6\u6001\u3002", en: "Waiting for Trash status." },
  notRestorable: { zh: "\u8be5\u8d44\u6599\u6682\u65f6\u65e0\u6cd5\u6062\u590d", en: "This resource cannot be restored." },
  refreshTrash: { zh: "\u5237\u65b0\u56de\u6536\u7ad9", en: "Refresh Trash" },
  deletePending: { zh: "\u6b63\u5728\u5c06 {count} \u9879\u8d44\u6599\u79fb\u5165\u56de\u6536\u7ad9...", en: "Moving {count} resources to Trash..." },
  restorePending: { zh: "\u6b63\u5728\u6062\u590d {count} \u9879\u8d44\u6599...", en: "Restoring {count} resources..." },
  deleteSucceeded: { zh: "\u5df2\u5c06 {count} \u9879\u8d44\u6599\u79fb\u5165\u56de\u6536\u7ad9\u3002", en: "Moved {count} resources to Trash." },
  restoreSucceeded: { zh: "\u5df2\u6062\u590d {count} \u9879\u8d44\u6599\u3002", en: "Restored {count} resources." },
  mutationFailed: { zh: "\u672a\u80fd\u786e\u8ba4\u6b64\u66f4\u6539\u3002\u8bf7\u5237\u65b0\u56de\u6536\u7ad9\u540e\u91cd\u8bd5\u3002", en: "The change was not confirmed. Refresh Trash and try again." },
  currentObject: { zh: "\u5f53\u524d\u5bf9\u8c61", en: "Current object" },
  resourceDetail: { zh: "\u8d44\u6599\u8be6\u60c5", en: "Resource detail" },
};

const resourceTextLocaleOverrides: Record<
  Exclude<ComposerLanguage, "zh-CN" | "en-US">,
  Partial<Record<ResourceTextKey, string>>
> = {
  "es-ES": {
    title: "Biblioteca de conocimientos",
    addResource: "Agregar recurso",
    searchPlaceholder: "Buscar por titulo, fuente o resumen",
    webSnapshots: "Instantaneas web",
    references: "Referencias",
    imported: "Importados",
    captureWebSnapshot: "Capturar instantanea de pagina web",
    index: "Indice",
    indexing: "Indexando",
    indexFailed: "Error de indexacion",
    refresh: "Actualizar indice",
    emptyTitle: "Aun no hay recursos",
    emptyBody: "Agrega un archivo, carpeta o instantanea web para buscar y reutilizar.",
    noMatches: "No hay recursos coincidentes",
    searching: "Buscando recursos...",
    searchPreview: "Solo se filtran recursos de la vista previa.",
    searchFailed: "No se pudieron buscar los recursos. Int\u00e9ntalo de nuevo.",
    searchIncomplete: "La busqueda no se completo.",
    readOnlyNotice: "Este proyecto es de solo lectura. Puedes buscar y abrir recursos.",
    browserPreviewMutationNotice: "La vista previa del navegador no puede cambiar recursos reales. Usa la barra lateral de VS Code.",
    source: "Fuente",
    trust: "Confianza",
    freshness: "Vigencia",
    fresh: "Actualizado",
    stale: "Pendiente de actualizar",
    unknown: "Desconocido",
    openInVsCode: "Abrir en VS Code",
    sandboxTitle: "Sandbox protegido",
    sandboxReady: "Sandbox disponible",
    sandboxUnavailable: "Esperando conexion",
    sandboxBoundary: "El sandbox solo procesa y abre recursos; no es tu espacio de trabajo del proyecto.",
    sandboxPath: "Raiz",
    sandboxLinked: "Vinculados",
    sandboxFiles: "archivos",
    closeDetails: "Cerrar detalles",
    training: "Entrenamiento",
    trainingEligible: "Listo para entrenamiento y evidencia del plan",
    createReviewCard: "Crear tarjeta de repaso",
    openCurrentTraining: "Abrir entrenamiento actual",
    selectResource: "Seleccionar recurso",
    selectFolder: "Seleccionar carpeta",
    selectAllVisible: "Seleccionar todos los recursos visibles",
    clearSelection: "Borrar seleccion",
    deleteSelected: "Eliminar recursos seleccionados",
    restoreDeleted: "Restaurar recursos disponibles",
    recoveryAvailable: "Recursos en la Papelera: {count}",
    selectedResources: "Recursos seleccionados",
    deleteConfirmation: "Mover los recursos seleccionados ({count}) a la Papelera? Se pueden restaurar desde el sandbox protegido.",
    logicalCollection: "Coleccion",
    storageRoots: "Ubicaciones de almacenamiento",
    workspaceRoot: "Raiz del espacio de trabajo",
    sandboxRoot: "Raiz del sandbox",
    trashRoot: "Raiz de la Papelera",
    unavailable: "No disponible",
    trashTitle: "Papelera",
    trashEmpty: "La Papelera esta vacia.",
    trashLoading: "Esperando el estado de la Papelera.",
    notRestorable: "Este recurso no se puede restaurar.",
    refreshTrash: "Actualizar Papelera",
    deletePending: "Moviendo {count} recursos a la Papelera...",
    restorePending: "Restaurando {count} recursos...",
    deleteSucceeded: "Se movieron {count} recursos a la Papelera.",
    restoreSucceeded: "Se restauraron {count} recursos.",
    mutationFailed: "No se confirmo el cambio. Actualiza la Papelera e intentalo de nuevo.",
  },
  "fr-FR": {
    title: "Bibliotheque de connaissances",
    addResource: "Ajouter une ressource",
    searchPlaceholder: "Rechercher par titre, source ou resume",
    webSnapshots: "Captures web",
    references: "References",
    imported: "Importes",
    captureWebSnapshot: "Capturer une page web",
    index: "Index",
    indexing: "Indexation en cours",
    indexFailed: "Echec de l'indexation",
    refresh: "Actualiser l'index",
    emptyTitle: "Aucune ressource pour le moment",
    emptyBody: "Ajoutez un fichier, dossier ou une capture web pour rechercher et reutiliser.",
    noMatches: "Aucune ressource correspondante",
    searching: "Recherche des ressources...",
    searchPreview: "Filtrage des ressources de l'apercu uniquement.",
    searchFailed: "Impossible de rechercher les ressources. R\u00e9essayez.",
    searchIncomplete: "La recherche n'a pas abouti.",
    readOnlyNotice: "Ce projet est en lecture seule. Vous pouvez rechercher et ouvrir des ressources.",
    browserPreviewMutationNotice: "L'apercu dans le navigateur ne peut pas modifier les ressources reelles. Utilisez la barre laterale de VS Code.",
    source: "Source",
    trust: "Confiance",
    freshness: "Actualite",
    fresh: "A jour",
    stale: "A actualiser",
    unknown: "Inconnue",
    openInVsCode: "Ouvrir dans VS Code",
    sandboxTitle: "Sandbox protege",
    sandboxReady: "Sandbox disponible",
    sandboxUnavailable: "En attente de connexion",
    sandboxBoundary: "Le sandbox sert seulement a traiter et ouvrir des ressources. Ce n'est pas votre espace de travail de projet.",
    sandboxPath: "Racine",
    sandboxLinked: "Associees",
    sandboxFiles: "fichiers",
    closeDetails: "Fermer les details",
    training: "Entrainement",
    trainingEligible: "Pret pour l'entrainement et les preuves du plan",
    createReviewCard: "Creer une carte de revision",
    openCurrentTraining: "Ouvrir l'entrainement en cours",
    selectResource: "Selectionner la ressource",
    selectFolder: "Selectionner le dossier",
    selectAllVisible: "Selectionner toutes les ressources visibles",
    clearSelection: "Effacer la selection",
    deleteSelected: "Supprimer les ressources selectionnees",
    restoreDeleted: "Restaurer les ressources disponibles",
    recoveryAvailable: "Ressources dans la corbeille : {count}",
    selectedResources: "Ressources selectionnees",
    deleteConfirmation: "Deplacer les ressources selectionnees ({count}) dans la corbeille ? Elles peuvent etre restaurees depuis le sandbox protege.",
    logicalCollection: "Collection",
    storageRoots: "Emplacements de stockage",
    workspaceRoot: "Racine de l'espace de travail",
    sandboxRoot: "Racine du sandbox",
    trashRoot: "Racine de la corbeille",
    unavailable: "Indisponible",
    trashTitle: "Corbeille",
    trashEmpty: "La corbeille est vide.",
    trashLoading: "En attente de l'etat de la corbeille.",
    notRestorable: "Cette ressource ne peut pas etre restauree.",
    refreshTrash: "Actualiser la corbeille",
    deletePending: "Deplacement de {count} ressources vers la corbeille...",
    restorePending: "Restauration de {count} ressources...",
    deleteSucceeded: "{count} ressources ont ete placees dans la corbeille.",
    restoreSucceeded: "{count} ressources ont ete restaurees.",
    mutationFailed: "La modification n'a pas ete confirmee. Actualisez la corbeille et reessayez.",
  },
  "de-DE": {
    title: "Wissensbibliothek",
    addResource: "Ressource hinzufugen",
    searchPlaceholder: "Titel, Quelle oder Zusammenfassung suchen",
    webSnapshots: "Web-Schnappschuesse",
    references: "Referenzen",
    imported: "Importiert",
    captureWebSnapshot: "Webseite erfassen",
    index: "Index",
    indexing: "Wird indexiert",
    indexFailed: "Indexierung fehlgeschlagen",
    refresh: "Index aktualisieren",
    emptyTitle: "Noch keine Materialien",
    emptyBody: "Datei, Ordner oder Web-Schnappschuss hinzufuegen, um sie zu suchen und wiederzuverwenden.",
    noMatches: "Keine passenden Materialien",
    searching: "Materialien werden gesucht...",
    searchPreview: "Nur Vorschau-Materialien werden gefiltert.",
    searchFailed: "Materialien konnten nicht gesucht werden. Versuchen Sie es erneut.",
    searchIncomplete: "Die Suche wurde nicht abgeschlossen.",
    readOnlyNotice: "Dieses Projekt ist schreibgeschuetzt. Sie koennen Materialien suchen und oeffnen.",
    browserPreviewMutationNotice: "Die Browser-Vorschau kann keine echten Materialien aendern. Verwenden Sie die VS Code-Seitenleiste.",
    source: "Quelle",
    trust: "Vertrauen",
    freshness: "Aktualitaet",
    fresh: "Aktuell",
    stale: "Veraltet",
    unknown: "Unbekannt",
    openInVsCode: "In VS Code oeffnen",
    sandboxTitle: "Geschuetzte Sandbox",
    sandboxReady: "Sandbox verfuegbar",
    sandboxUnavailable: "Warte auf Verbindung",
    sandboxBoundary: "Die Sandbox verarbeitet und oeffnet nur Materialien. Sie ist nicht Ihr Projektarbeitsbereich.",
    sandboxPath: "Stamm",
    sandboxLinked: "Verknuepft",
    sandboxFiles: "Dateien",
    closeDetails: "Details schliessen",
    training: "Training",
    trainingEligible: "Fuer Training und Planevidenz bereit",
    createReviewCard: "Wiederholungskarte erstellen",
    openCurrentTraining: "Aktuelles Training oeffnen",
    selectResource: "Material auswaehlen",
    selectFolder: "Ordner auswaehlen",
    selectAllVisible: "Alle sichtbaren Materialien auswaehlen",
    clearSelection: "Auswahl aufheben",
    deleteSelected: "Ausgewaehlte Materialien loeschen",
    restoreDeleted: "Verfuegbare Materialien wiederherstellen",
    recoveryAvailable: "Materialien im Papierkorb: {count}",
    selectedResources: "Ausgewaehlte Materialien",
    deleteConfirmation: "Ausgewaehlte Materialien ({count}) in den Papierkorb verschieben? Sie koennen im geschuetzten Sandbox-Bereich wiederhergestellt werden.",
    logicalCollection: "Sammlung",
    storageRoots: "Speicherorte",
    workspaceRoot: "Arbeitsbereich-Stammordner",
    sandboxRoot: "Sandbox-Stammordner",
    trashRoot: "Papierkorb-Stammordner",
    unavailable: "Nicht verfuegbar",
    trashTitle: "Papierkorb",
    trashEmpty: "Der Papierkorb ist leer.",
    trashLoading: "Warte auf den Papierkorbstatus.",
    notRestorable: "Dieses Material kann nicht wiederhergestellt werden.",
    refreshTrash: "Papierkorb aktualisieren",
    deletePending: "{count} Materialien werden in den Papierkorb verschoben...",
    restorePending: "{count} Materialien werden wiederhergestellt...",
    deleteSucceeded: "{count} Materialien wurden in den Papierkorb verschoben.",
    restoreSucceeded: "{count} Materialien wurden wiederhergestellt.",
    mutationFailed: "Die Aenderung wurde nicht bestaetigt. Papierkorb aktualisieren und erneut versuchen.",
  },
  "ja-JP": {
    title: "ナレッジライブラリ",
    addResource: "資料を追加",
    searchPlaceholder: "タイトル、ソース、要約を検索",
    webSnapshots: "Web スナップショット",
    references: "参考資料",
    imported: "インポート済み",
    captureWebSnapshot: "Web ページを保存",
    index: "索引",
    indexing: "索引作成中",
    indexFailed: "索引に失敗",
    refresh: "索引を更新",
    emptyTitle: "資料はまだありません",
    emptyBody: "ファイル、フォルダー、または Web スナップショットを追加すると、検索と再利用に使えます。",
    noMatches: "一致する資料はありません",
    searching: "資料を検索中...",
    searchPreview: "プレビュー内の資料のみ絞り込みます。",
    searchFailed: "\u8cc7\u6599\u3092\u691c\u7d22\u3067\u304d\u307e\u305b\u3093\u3002\u3082\u3046\u4e00\u5ea6\u8a66\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
    searchIncomplete: "検索が完了しませんでした。",
    readOnlyNotice: "このプロジェクトは読み取り専用です。資料の検索と閲覧はできます。",
    browserPreviewMutationNotice: "ブラウザープレビューでは実際の資料を変更できません。VS Code のサイドバーで操作してください。",
    source: "ソース",
    trust: "信頼度",
    freshness: "鮮度",
    fresh: "新鮮",
    stale: "更新待ち",
    unknown: "不明",
    openInVsCode: "VS Code で開く",
    sandboxTitle: "保護されたサンドボックス",
    sandboxReady: "サンドボックスを利用できます",
    sandboxUnavailable: "接続待ち",
    sandboxBoundary: "サンドボックスは資料の処理とネイティブでの表示だけに使います。プロジェクトの作業領域ではありません。",
    sandboxPath: "ルート",
    sandboxLinked: "関連済み",
    sandboxFiles: "ファイル",
    closeDetails: "詳細を閉じる",
    training: "トレーニング",
    trainingEligible: "トレーニングと計画の証拠に利用できます",
    createReviewCard: "復習カードを作る",
    openCurrentTraining: "現在のトレーニングを開く",
    selectResource: "資料を選択",
    selectFolder: "フォルダーを選択",
    selectAllVisible: "表示中の資料をすべて選択",
    clearSelection: "選択を解除",
    deleteSelected: "選択した資料を削除",
    restoreDeleted: "最近削除した資料を復元",
    recoveryAvailable: "ごみ箱内の資料: {count}",
    selectedResources: "選択した資料",
    deleteConfirmation: "選択した資料 {count} 件をごみ箱に移動しますか？保護されたサンドボックスから復元できます。",
    logicalCollection: "\u8ad6\u7406\u30b3\u30ec\u30af\u30b7\u30e7\u30f3",
    storageRoots: "\u4fdd\u5b58\u5148",
    workspaceRoot: "\u30ef\u30fc\u30af\u30b9\u30da\u30fc\u30b9\u30eb\u30fc\u30c8",
    sandboxRoot: "\u30b5\u30f3\u30c9\u30dc\u30c3\u30af\u30b9\u30eb\u30fc\u30c8",
    trashRoot: "\u3054\u307f\u7bb1\u30eb\u30fc\u30c8",
    unavailable: "\u5229\u7528\u4e0d\u53ef",
    trashTitle: "\u3054\u307f\u7bb1",
    trashEmpty: "\u3054\u307f\u7bb1\u306f\u7a7a\u3067\u3059\u3002",
    trashLoading: "\u3054\u307f\u7bb1\u306e\u72b6\u614b\u3092\u5f85\u6a5f\u4e2d\u3067\u3059\u3002",
    notRestorable: "\u3053\u306e\u8cc7\u6599\u306f\u5fa9\u5143\u3067\u304d\u307e\u305b\u3093\u3002",
    refreshTrash: "\u3054\u307f\u7bb1\u3092\u66f4\u65b0",
    deletePending: "{count} \u4ef6\u306e\u8cc7\u6599\u3092\u3054\u307f\u7bb1\u306b\u79fb\u52d5\u4e2d...",
    restorePending: "{count} \u4ef6\u306e\u8cc7\u6599\u3092\u5fa9\u5143\u4e2d...",
    deleteSucceeded: "{count} \u4ef6\u306e\u8cc7\u6599\u3092\u3054\u307f\u7bb1\u306b\u79fb\u52d5\u3057\u307e\u3057\u305f\u3002",
    restoreSucceeded: "{count} \u4ef6\u306e\u8cc7\u6599\u3092\u5fa9\u5143\u3057\u307e\u3057\u305f\u3002",
    mutationFailed: "\u5909\u66f4\u3092\u78ba\u8a8d\u3067\u304d\u307e\u305b\u3093\u3002\u3054\u307f\u7bb1\u3092\u66f4\u65b0\u3057\u3066\u518d\u8a66\u884c\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
  },
  "ko-KR": {
    title: "지식 라이브러리",
    addResource: "자료 추가",
    searchPlaceholder: "제목, 출처 또는 요약 검색",
    webSnapshots: "웹 스냅샷",
    references: "참고 자료",
    imported: "가져옴",
    captureWebSnapshot: "웹페이지 스냅샷 가져오기",
    index: "색인",
    indexing: "색인 중",
    indexFailed: "색인 실패",
    refresh: "색인 새로 고침",
    emptyTitle: "아직 자료가 없습니다",
    emptyBody: "파일, 폴더 또는 웹 스냅샷을 추가하면 검색하고 재사용할 수 있습니다.",
    noMatches: "일치하는 자료가 없습니다",
    searching: "자료를 검색 중...",
    searchPreview: "미리 보기의 자료만 필터링합니다.",
    searchFailed: "\uc790\ub8cc\ub97c \uac80\uc0c9\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4. \ub2e4\uc2dc \uc2dc\ub3c4\ud558\uc138\uc694.",
    searchIncomplete: "검색을 완료하지 못했습니다.",
    readOnlyNotice: "이 프로젝트는 읽기 전용입니다. 자료를 검색하고 열 수 있습니다.",
    browserPreviewMutationNotice: "브라우저 미리 보기에서는 실제 자료를 변경할 수 없습니다. VS Code 사이드바에서 작업하세요.",
    source: "출처",
    trust: "신뢰도",
    freshness: "최신성",
    fresh: "최신",
    stale: "업데이트 필요",
    unknown: "알 수 없음",
    openInVsCode: "VS Code에서 열기",
    sandboxTitle: "보호된 샌드박스",
    sandboxReady: "샌드박스를 사용할 수 있습니다",
    sandboxUnavailable: "연결 대기 중",
    sandboxBoundary: "샌드박스는 자료를 처리하고 기본 앱으로 여는 데만 사용합니다. 프로젝트 작업 영역이 아닙니다.",
    sandboxPath: "루트",
    sandboxLinked: "연결됨",
    sandboxFiles: "파일",
    closeDetails: "세부 정보 닫기",
    training: "훈련",
    trainingEligible: "훈련과 계획 증거에 사용할 수 있습니다",
    createReviewCard: "복습 카드 만들기",
    openCurrentTraining: "현재 훈련 열기",
    selectResource: "자료 선택",
    selectFolder: "폴더 선택",
    selectAllVisible: "표시된 자료 모두 선택",
    clearSelection: "선택 해제",
    deleteSelected: "선택한 자료 삭제",
    restoreDeleted: "최근 삭제한 자료 복원",
    recoveryAvailable: "휴지통의 자료: {count}",
    selectedResources: "선택한 자료",
    deleteConfirmation: "선택한 자료 {count}개를 휴지통으로 옮길까요? 보호된 샌드박스에서 복원할 수 있습니다.",
    logicalCollection: "\ub17c\ub9ac \uceec\ub809\uc158",
    storageRoots: "\uc800\uc7a5 \uc704\uce58",
    workspaceRoot: "\uc791\uc5c5 \uc601\uc5ed \ub8e8\ud2b8",
    sandboxRoot: "\uc0cc\ub4dc\ubc15\uc2a4 \ub8e8\ud2b8",
    trashRoot: "\ud734\uc9c0\ud1b5 \ub8e8\ud2b8",
    unavailable: "\uc0ac\uc6a9\ud560 \uc218 \uc5c6\uc74c",
    trashTitle: "\ud734\uc9c0\ud1b5",
    trashEmpty: "\ud734\uc9c0\ud1b5\uc774 \ube44\uc5b4 \uc788\uc2b5\ub2c8\ub2e4.",
    trashLoading: "\ud734\uc9c0\ud1b5 \uc0c1\ud0dc\ub97c \uae30\ub2e4\ub9ac\uace0 \uc788\uc2b5\ub2c8\ub2e4.",
    notRestorable: "\uc774 \uc790\ub8cc\ub294 \ubcf5\uc6d0\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4.",
    refreshTrash: "\ud734\uc9c0\ud1b5 \uc0c8\ub85c \uace0\uce68",
    deletePending: "{count}\uac1c \uc790\ub8cc\ub97c \ud734\uc9c0\ud1b5\uc73c\ub85c \uc774\ub3d9 \uc911...",
    restorePending: "{count}\uac1c \uc790\ub8cc\ub97c \ubcf5\uc6d0 \uc911...",
    deleteSucceeded: "{count}\uac1c \uc790\ub8cc\ub97c \ud734\uc9c0\ud1b5\uc73c\ub85c \uc774\ub3d9\ud588\uc2b5\ub2c8\ub2e4.",
    restoreSucceeded: "{count}\uac1c \uc790\ub8cc\ub97c \ubcf5\uc6d0\ud588\uc2b5\ub2c8\ub2e4.",
    mutationFailed: "\ubcc0\uacbd\uc744 \ud655\uc778\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4. \ud734\uc9c0\ud1b5\uc744 \uc0c8\ub85c \uace0\uce68\ud558\uace0 \ub2e4\uc2dc \uc2dc\ub3c4\ud558\uc138\uc694.",
  },
  "pt-BR": {
    title: "Biblioteca de conhecimento",
    addResource: "Adicionar recurso",
    searchPlaceholder: "Pesquisar titulo, fonte ou resumo",
    webSnapshots: "Capturas da web",
    references: "Referencias",
    imported: "Importados",
    captureWebSnapshot: "Capturar pagina da web",
    index: "Indice",
    indexing: "Indexando",
    indexFailed: "Falha na indexacao",
    refresh: "Atualizar indice",
    emptyTitle: "Ainda nao ha recursos",
    emptyBody: "Adicione um arquivo, pasta ou captura da web para pesquisar e reutilizar.",
    noMatches: "Nenhum recurso correspondente",
    searching: "Pesquisando recursos...",
    searchPreview: "Filtrando somente os recursos da visualizacao.",
    searchFailed: "N\u00e3o foi poss\u00edvel pesquisar os recursos. Tente novamente.",
    searchIncomplete: "A pesquisa nao foi concluida.",
    readOnlyNotice: "Este projeto esta somente para leitura. Voce pode pesquisar e abrir recursos.",
    browserPreviewMutationNotice: "A visualizacao no navegador nao pode alterar recursos reais. Use a barra lateral do VS Code.",
    source: "Fonte",
    trust: "Confianca",
    freshness: "Atualidade",
    fresh: "Atual",
    stale: "Desatualizado",
    unknown: "Desconhecido",
    openInVsCode: "Abrir no VS Code",
    sandboxTitle: "Sandbox protegido",
    sandboxReady: "Sandbox disponivel",
    sandboxUnavailable: "Aguardando conexao",
    sandboxBoundary: "O sandbox serve somente para processar e abrir recursos; nao e o espaco de trabalho do projeto.",
    sandboxPath: "Raiz",
    sandboxLinked: "Vinculados",
    sandboxFiles: "arquivos",
    closeDetails: "Fechar detalhes",
    training: "Treinamento",
    trainingEligible: "Pronto para treinamento e evidencia do plano",
    createReviewCard: "Criar cartao de revisao",
    openCurrentTraining: "Abrir treinamento atual",
    selectResource: "Selecionar recurso",
    selectFolder: "Selecionar pasta",
    selectAllVisible: "Selecionar todos os recursos visiveis",
    clearSelection: "Limpar selecao",
    deleteSelected: "Excluir recursos selecionados",
    restoreDeleted: "Restaurar recursos disponiveis",
    recoveryAvailable: "Recursos na Lixeira: {count}",
    selectedResources: "Recursos selecionados",
    deleteConfirmation: "Mover os recursos selecionados ({count}) para a Lixeira? Eles podem ser restaurados no sandbox protegido.",
    logicalCollection: "Colecao",
    storageRoots: "Locais de armazenamento",
    workspaceRoot: "Raiz do espaco de trabalho",
    sandboxRoot: "Raiz do sandbox",
    trashRoot: "Raiz da Lixeira",
    unavailable: "Indisponivel",
    trashTitle: "Lixeira",
    trashEmpty: "A Lixeira esta vazia.",
    trashLoading: "Aguardando o estado da Lixeira.",
    notRestorable: "Este recurso nao pode ser restaurado.",
    refreshTrash: "Atualizar Lixeira",
    deletePending: "Movendo {count} recursos para a Lixeira...",
    restorePending: "Restaurando {count} recursos...",
    deleteSucceeded: "{count} recursos foram movidos para a Lixeira.",
    restoreSucceeded: "{count} recursos foram restaurados.",
    mutationFailed: "A alteracao nao foi confirmada. Atualize a Lixeira e tente novamente.",
  },
};

const compactResourceSearchPlaceholder: Record<ComposerLanguage, string> = {
  "zh-CN": "\u641c\u7d22\u8d44\u6599",
  "en-US": "Search",
  "es-ES": "Buscar recursos",
  "fr-FR": "Rechercher",
  "de-DE": "Suchen",
  "ja-JP": "\u8cc7\u6599\u3092\u691c\u7d22",
  "ko-KR": "\uc790\ub8cc \uac80\uc0c9",
  "pt-BR": "Pesquisar",
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

const englishSingularResourceMutationText: Partial<Record<ResourceTextKey, string>> = {
  deletePending: "Moving {count} resource to Trash...",
  restorePending: "Restoring {count} resource...",
  deleteSucceeded: "Moved {count} resource to Trash.",
  restoreSucceeded: "Restored {count} resource.",
};

function localizeCount(language: ComposerLanguage, key: ResourceTextKey, count: number): string {
  const text =
    language === "en-US" && count === 1
      ? englishSingularResourceMutationText[key] ?? localize(language, key)
      : localize(language, key);
  return text.replace("{count}", String(count));
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

function compactSourceLabel(value: string): string {
  const source = value.trim();
  if (!source) {
    return source;
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
  return segments.length > 1 ? segments.slice(-2).join("/") : source;
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

function resourceTrust(resource: ResourceRecord): string | undefined {
  return resource.trustState?.trim() ||
    (typeof resource.trustScore === "number" ? `${Math.round(resource.trustScore * 100)}%` : undefined);
}

const resourceTrainingBlockingFlags = new Set([
  "network_disabled",
  "fetch_failed",
  "blocked_source",
  "no_content",
  "source_conflict",
]);

const resourceTrainingReadinessCopy: Record<
  ComposerLanguage,
  Record<"indexing" | "stale" | "source" | "trust" | "unavailable", string>
> = {
  "zh-CN": {
    indexing: "\u8d44\u6599\u8fd8\u5728\u6574\u7406\uff0c\u5b8c\u6210\u7d22\u5f15\u540e\u624d\u80fd\u751f\u6210\u8bad\u7ec3\u5361\u3002",
    stale: "\u8fd9\u4efd\u8d44\u6599\u9700\u8981\u66f4\u65b0\u3002\u5237\u65b0\u7d22\u5f15\u540e\u518d\u751f\u6210\u8bad\u7ec3\u5361\u3002",
    source: "\u8fd9\u4efd\u8d44\u6599\u8fd8\u6ca1\u6709\u53d6\u5f97\u53ef\u7528\u5185\u5bb9\u3002\u5148\u6253\u5f00\u6765\u6e90\u68c0\u67e5\uff0c\u6216\u5237\u65b0\u7d22\u5f15\u540e\u91cd\u8bd5\u3002",
    trust: "\u8fd9\u4efd\u8d44\u6599\u7684\u6765\u6e90\u8fd8\u6ca1\u6709\u901a\u8fc7\u786e\u8ba4\u3002\u5237\u65b0\u7d22\u5f15\u540e\u518d\u8bd5\u3002",
    unavailable: "\u8fd9\u4efd\u8d44\u6599\u6682\u65f6\u8fd8\u4e0d\u80fd\u751f\u6210\u8bad\u7ec3\u5361\u3002\u5237\u65b0\u7d22\u5f15\u540e\u91cd\u8bd5\u3002",
  },
  "en-US": {
    indexing: "This resource is still being processed. Finish indexing it before creating a training card.",
    stale: "This resource needs an update. Refresh its index before creating a training card.",
    source: "Trainer could not get usable content from this resource yet. Open the source to check it, or refresh the index and try again.",
    trust: "This resource's source has not been confirmed yet. Refresh the index and try again.",
    unavailable: "This resource is not ready for a training card yet. Refresh the index and try again.",
  },
  "es-ES": {
    indexing: "Este recurso aun se esta procesando. Termina de indexarlo antes de crear una tarjeta.",
    stale: "Este recurso necesita actualizarse. Actualiza el indice antes de crear una tarjeta.",
    source: "Trainer aun no encontro contenido util en este recurso. Abre la fuente o actualiza el indice e intentalo de nuevo.",
    trust: "La fuente de este recurso aun no se ha confirmado. Actualiza el indice e intentalo de nuevo.",
    unavailable: "Este recurso aun no esta listo para una tarjeta. Actualiza el indice e intentalo de nuevo.",
  },
  "fr-FR": {
    indexing: "Cette ressource est encore en cours de traitement. Terminez son indexation avant de creer une carte.",
    stale: "Cette ressource doit etre mise a jour. Actualisez son index avant de creer une carte.",
    source: "Trainer n'a pas encore trouve de contenu utilisable dans cette ressource. Ouvrez la source ou actualisez l'index, puis reessayez.",
    trust: "La source de cette ressource n'est pas encore confirmee. Actualisez l'index puis reessayez.",
    unavailable: "Cette ressource n'est pas encore prete pour une carte. Actualisez l'index puis reessayez.",
  },
  "de-DE": {
    indexing: "Dieses Material wird noch verarbeitet. Schließe die Indexierung ab, bevor du eine Karte erstellst.",
    stale: "Dieses Material muss aktualisiert werden. Aktualisiere den Index, bevor du eine Karte erstellst.",
    source: "Trainer konnte hier noch keinen nutzbaren Inhalt finden. Offne die Quelle oder aktualisiere den Index und versuche es erneut.",
    trust: "Die Quelle dieses Materials wurde noch nicht bestatigt. Aktualisiere den Index und versuche es erneut.",
    unavailable: "Dieses Material ist noch nicht fur eine Karte bereit. Aktualisiere den Index und versuche es erneut.",
  },
  "ja-JP": {
    indexing: "\u3053\u306e\u8cc7\u6599\u306f\u307e\u3060\u51e6\u7406\u4e2d\u3067\u3059\u3002\u30c8\u30ec\u30fc\u30cb\u30f3\u30b0\u30ab\u30fc\u30c9\u306e\u524d\u306b\u30a4\u30f3\u30c7\u30c3\u30af\u30b9\u3092\u5b8c\u4e86\u3055\u305b\u3066\u304f\u3060\u3055\u3044\u3002",
    stale: "\u3053\u306e\u8cc7\u6599\u306f\u66f4\u65b0\u304c\u5fc5\u8981\u3067\u3059\u3002\u30ab\u30fc\u30c9\u3092\u4f5c\u308b\u524d\u306b\u30a4\u30f3\u30c7\u30c3\u30af\u30b9\u3092\u66f4\u65b0\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
    source: "\u3053\u306e\u8cc7\u6599\u304b\u3089\u307e\u3060\u4f7f\u3048\u308b\u5185\u5bb9\u3092\u53d6\u308a\u51fa\u305b\u3066\u3044\u307e\u305b\u3093\u3002\u5143\u306e\u8cc7\u6599\u3092\u958b\u304f\u304b\u3001\u30a4\u30f3\u30c7\u30c3\u30af\u30b9\u3092\u66f4\u65b0\u3057\u3066\u518d\u5ea6\u8a66\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
    trust: "\u3053\u306e\u8cc7\u6599\u306e\u51fa\u6240\u306f\u307e\u3060\u78ba\u8a8d\u3055\u308c\u3066\u3044\u307e\u305b\u3093\u3002\u30a4\u30f3\u30c7\u30c3\u30af\u30b9\u3092\u66f4\u65b0\u3057\u3066\u518d\u5ea6\u8a66\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
    unavailable: "\u3053\u306e\u8cc7\u6599\u306f\u307e\u3060\u30c8\u30ec\u30fc\u30cb\u30f3\u30b0\u30ab\u30fc\u30c9\u306e\u6e96\u5099\u304c\u3067\u304d\u3066\u3044\u307e\u305b\u3093\u3002\u30a4\u30f3\u30c7\u30c3\u30af\u30b9\u3092\u66f4\u65b0\u3057\u3066\u518d\u5ea6\u8a66\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
  },
  "ko-KR": {
    indexing: "\uc774 \uc790\ub8cc\ub294 \uc544\uc9c1 \ucc98\ub9ac \uc911\uc785\ub2c8\ub2e4. \uce74\ub4dc\ub97c \ub9cc\ub4e4\uae30 \uc804\uc5d0 \uc0c9\uc778\uc744 \uc644\ub8cc\ud558\uc138\uc694.",
    stale: "\uc774 \uc790\ub8cc\ub294 \uc5c5\ub370\uc774\ud2b8\uac00 \ud544\uc694\ud569\ub2c8\ub2e4. \uce74\ub4dc\ub97c \ub9cc\ub4e4\uae30 \uc804\uc5d0 \uc0c9\uc778\uc744 \uc0c8\ub85c \uace0\uce68\ud558\uc138\uc694.",
    source: "Trainer\uac00 \uc774 \uc790\ub8cc\uc5d0\uc11c \uc544\uc9c1 \uc0ac\uc6a9\ud560 \uc218 \uc788\ub294 \ub0b4\uc6a9\uc744 \ucc3e\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4. \uc6d0\ubcf8\uc744 \uc5f4\uac70\ub098 \uc0c9\uc778\uc744 \uc0c8\ub85c \uace0\uce68\ud574 \ub2e4\uc2dc \uc2dc\ub3c4\ud558\uc138\uc694.",
    trust: "\uc774 \uc790\ub8cc\uc758 \ucd9c\ucc98\uac00 \uc544\uc9c1 \ud655\uc778\ub418\uc9c0 \uc54a\uc558\uc2b5\ub2c8\ub2e4. \uc0c9\uc778\uc744 \uc0c8\ub85c \uace0\uce68\ud574 \ub2e4\uc2dc \uc2dc\ub3c4\ud558\uc138\uc694.",
    unavailable: "\uc774 \uc790\ub8cc\ub294 \uc544\uc9c1 \ud559\uc2b5 \uce74\ub4dc\uc5d0 \uc900\ube44\ub418\uc9c0 \uc54a\uc558\uc2b5\ub2c8\ub2e4. \uc0c9\uc778\uc744 \uc0c8\ub85c \uace0\uce68\ud574 \ub2e4\uc2dc \uc2dc\ub3c4\ud558\uc138\uc694.",
  },
  "pt-BR": {
    indexing: "Este recurso ainda esta sendo processado. Termine a indexacao antes de criar um cartao.",
    stale: "Este recurso precisa ser atualizado. Atualize o indice antes de criar um cartao.",
    source: "O Trainer ainda nao encontrou conteudo utilizavel neste recurso. Abra a fonte ou atualize o indice e tente novamente.",
    trust: "A fonte deste recurso ainda nao foi confirmada. Atualize o indice e tente novamente.",
    unavailable: "Este recurso ainda nao esta pronto para um cartao. Atualize o indice e tente novamente.",
  },
};

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
    "es-ES": {},
    "fr-FR": {},
    "de-DE": {},
    "ja-JP": {},
    "ko-KR": {},
    "pt-BR": {},
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
  return pathSegments(collectionPath);
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
  return segment;
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
    return logicalCollectionSegments.slice(0, -1);
  }

  const candidates = new Set(resourcePathCandidates(resource, sandboxRoot));
  const matchingNode = sandboxNodes.find((node) => node.normalizedPaths.some((path) => candidates.has(path)));
  if (matchingNode) {
    return matchingNode.relativeSegments.slice(0, -1);
  }
  return fallbackCollectionSegments(resource, sandboxRoot);
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

  for (const resource of resources) {
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

  return compactUnaryCollections(sortResourceTree(root.children));
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
  return node.children.flatMap(resourceIdsInTreeNode);
}

function visibleTreeItemIds(nodes: ResourceTreeNode[], expandedIds: Set<string>): string[] {
  return nodes.flatMap((node) => {
    if (node.kind !== "collection" || !expandedIds.has(node.id)) {
      return [node.id];
    }
    return [node.id, ...visibleTreeItemIds(node.children, expandedIds)];
  });
}

interface ResourceTreeItemProps {
  node: ResourceTreeNode;
  depth: number;
  parentId?: string;
  language: ComposerLanguage;
  expandedIds: Set<string>;
  selectedResourceId: string | null;
  selectedResourceIds: Set<string>;
  activeTreeItemId: string | null;
  onToggle: (id: string) => void;
  onSelect: (resource: ResourceRecord) => void;
  onToggleSelection: (resourceId: string) => void;
  onSetSelection: (resourceIds: string[], selected: boolean) => void;
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
  selectedResourceIds,
  activeTreeItemId,
  onToggle,
  onSelect,
  onToggleSelection,
  onSetSelection,
  onOpen,
  onActiveTreeItemChange,
  onMoveTreeFocus,
}: ResourceTreeItemProps) {
  if (node.kind === "resource" && node.resource) {
    const isSelected = selectedResourceId === node.resource.id;
    const isMarked = selectedResourceIds.has(node.resource.id);
    const indexNotice = resourceIndexNotice(node.resource, language);
    return (
      <div
        className={`resources-library-tree__node resources-library-tree__node--resource resources-row ${
          isSelected ? "is-selected" : ""
        } ${isMarked ? "is-marked" : ""}`}
        role="treeitem"
        aria-level={depth + 1}
        aria-label={node.resource.title}
        aria-checked={isMarked}
        aria-current={isSelected ? "true" : undefined}
        data-resource-tree-item-id={node.id}
        tabIndex={activeTreeItemId === node.id ? 0 : -1}
        style={{
          paddingInlineStart: `calc(var(--trainer-space-2) + ${depth} * var(--trainer-space-4))`,
        }}
        title={node.resource.title}
        onFocus={() => onActiveTreeItemChange(node.id)}
        onClick={() => onSelect(node.resource!)}
        onDoubleClick={() => onOpen(node.resource!)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            onOpen(node.resource!);
          }
          if (event.key === " ") {
            event.preventDefault();
            onToggleSelection(node.resource!.id);
          }
          if (event.key === "ArrowLeft" && parentId) {
            event.preventDefault();
            onMoveTreeFocus(parentId);
          }
        }}
        aria-keyshortcuts="Enter Space"
      >
        <span className="resources-library-tree__indent" aria-hidden="true" />
        <label
          className="resources-library-tree__selection"
          onClick={(event) => event.stopPropagation()}
        >
          <input
            type="checkbox"
            checked={isMarked}
            tabIndex={-1}
            onChange={() => onToggleSelection(node.resource!.id)}
            onKeyDown={(event) => {
              if (event.key === " ") {
                event.stopPropagation();
              }
            }}
            aria-label={`${localize(language, "selectResource")}: ${node.resource.title}`}
          />
        </label>
        <span className="resources-library-tree__copy">
          <strong>{node.resource.title}</strong>
          {node.resource.summary?.trim() &&
          node.resource.summary.trim() !== node.resource.title ? (
            <span className="resources-library-tree__summary">{node.resource.summary.trim()}</span>
          ) : null}
        </span>
        {indexNotice ? (
          <span className={`resources-library-tree__status is-${indexNotice.tone}`}>
            {indexNotice.label}
          </span>
        ) : null}
      </div>
    );
  }

  const isExpanded = expandedIds.has(node.id);
  const descendantResourceIds = resourceIdsInTreeNode(node);
  const markedDescendantCount = descendantResourceIds.filter((resourceId) =>
    selectedResourceIds.has(resourceId),
  ).length;
  const isMarked = descendantResourceIds.length > 0 && markedDescendantCount === descendantResourceIds.length;
  const isPartiallyMarked = markedDescendantCount > 0 && !isMarked;
  const firstChildId = node.children[0]?.id;
  const isLogicalCollection = node.collectionKind === "logical";
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
          if (!isExpanded) {
            onToggle(node.id);
          } else if (firstChildId) {
            onMoveTreeFocus(firstChildId);
          }
        }
        if (event.key === "ArrowLeft") {
          event.preventDefault();
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
        title={<span title={collectionDescription}>{node.label}</span>}
        subtitle={isLogicalCollection ? localize(language, "logicalCollection") : undefined}
        badge={
          <span className="resources-library-tree__count">{descendantResourceIds.length}</span>
        }
        open={isExpanded}
        onToggle={() => onToggle(node.id)}
        actions={
          <label
            className="resources-library-tree__selection"
            onClick={(event) => event.stopPropagation()}
          >
            <input
              type="checkbox"
              checked={isMarked}
              aria-checked={isPartiallyMarked ? "mixed" : isMarked}
              ref={(input) => {
                if (input) {
                  input.indeterminate = isPartiallyMarked;
                }
              }}
              onChange={() => onSetSelection(descendantResourceIds, !isMarked)}
              onKeyDown={(event) => {
                if (event.key === " ") {
                  event.stopPropagation();
                }
              }}
              aria-label={`${localize(language, "selectFolder")}: ${node.label}`}
            />
          </label>
        }
      >
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
                selectedResourceIds={selectedResourceIds}
                activeTreeItemId={activeTreeItemId}
                onToggle={onToggle}
                onSelect={onSelect}
                onToggleSelection={onToggleSelection}
                onSetSelection={onSetSelection}
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

function previewBodyWithoutDuplicateTitle(body: string, title: string): string {
  const trimmed = body.trim();
  const heading = trimmed.match(/^#\s+(.+?)(?:\r?\n|$)/);
  if (!heading) {
    return body;
  }
  if (heading[1].trim() !== title.trim()) {
    return body;
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
      return copy.orientationStateNeedsSetup;
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
  onImportFiles,
  onImportFolder,
  onImportUrl,
  onOpenResource,
  onPreviewResource,
  onStartTrainingFromResource,
  onOpenTraining,
  onRefreshResources,
  onDeleteResources,
  onRestoreResources,
  onRefreshDeletedResources,
  onChooseWorkspaceRoot,
  initialResourceContextIds = [],
  onResourceSelectionChange,
  onRestoreContextChange,
  resourceWriteAccess,
  deleteUnavailableReason,
  restoreUnavailableReason,
  orientation,
  leftoverNote,
  onOrientationAction,
  onDebugVisibleFacts,
  organizationConfirm,
}: ResourcesWorkbenchViewProps) {
  const { t } = useTranslation();
  const treeRef = useRef<HTMLDivElement>(null);
  const deleteConfirmationFocusRef = useRef<HTMLButtonElement>(null);
  const importMenuTriggerRef = useRef<HTMLButtonElement>(null);
  const importMenuRef = useRef<HTMLDivElement>(null);
  const importMenuId = useId();
  const [query, setQuery] = useState("");
  const [isImportMenuOpen, setIsImportMenuOpen] = useState(false);
  const [selectedResourceId, setSelectedResourceId] = useState<string | null>(
    () => pickInitialResourceId(resources, initialResourceContextIds, sandboxPreviewInput),
  );
  const didAutoSelectResource = useRef(false);
  const [selectedResourceIds, setSelectedResourceIds] = useState<Set<string>>(
    () => new Set(initialResourceContextIds),
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
  const selectedResourceContextIds = useMemo(() => {
    if (selectedResourceIds.size > 0) {
      return [...selectedResourceIds];
    }
    return selectedResourceId ? [selectedResourceId] : [];
  }, [selectedResourceId, selectedResourceIds]);

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

  const visibleResourceIds = useMemo(
    () => new Set(visibleResources.map((resource) => resource.id)),
    [visibleResources],
  );
  const trashedResourceIds = useMemo(
    () => new Set(trashedResources.map(deletedResourceId).filter((resourceId): resourceId is string => Boolean(resourceId))),
    [trashedResources],
  );
  const restorableDeletedResources = useMemo(
    () => trashedResources.filter(isDeletedResourceRecoverable),
    [trashedResources],
  );
  const isDeletePending = pendingDeletedResourceIds.length > 0;
  const isRestorePending = pendingRestoredResourceIds.length > 0;
  const hasResourceSelection = selectedResourceIds.size > 0;

  useEffect(() => {
    if (hasResourceSelection) {
      setIsImportMenuOpen(false);
    }
  }, [hasResourceSelection]);
  useEffect(() => {
    if (canWriteResources) {
      return;
    }
    setIsImportMenuOpen(false);
    setDeleteConfirmationResourceIds(null);
  }, [canWriteResources]);
  const deleteSelectedLabel = isDeletePending
    ? localizeCount(language, "deletePending", pendingDeletedResourceIds.length)
    : !canWriteResources
      ? resourceWriteBlockedReason ?? resourceReadOnlyNotice(language)
      : isBrowserPreview
        ? localize(language, "browserPreviewMutationNotice")
        : onDeleteResources
          ? localize(language, "deleteSelected")
          : deleteUnavailableReason ?? localize(language, "deleteSelected");
  const restoreDeletedLabel = isRestorePending
    ? localizeCount(language, "restorePending", pendingRestoredResourceIds.length)
    : !canWriteResources
      ? resourceWriteBlockedReason ?? resourceReadOnlyNotice(language)
      : isBrowserPreview
        ? localize(language, "browserPreviewMutationNotice")
        : onRestoreResources
          ? localize(language, "restoreDeleted")
          : restoreUnavailableReason ?? localize(language, "restoreDeleted");
  const deleteActionDisabled =
    !canWriteResources || isBrowserPreview || !onDeleteResources || isDeletePending || isRestorePending;
  const restoreActionDisabled =
    !canWriteResources ||
    isBrowserPreview ||
    !onRestoreResources ||
    !trashSnapshotAvailable ||
    restorableDeletedResources.length === 0 ||
    isDeletePending ||
    isRestorePending;
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
  const allVisibleResourcesSelected =
    visibleResources.length > 0 && visibleResources.every((resource) => selectedResourceIds.has(resource.id));
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
    setSelectedResourceId((current) => (current ? null : current));
  }, [restoreContext]);

  useEffect(() => {
    setSelectedResourceIds((current) => {
      const next = new Set([...current].filter((resourceId) => visibleResourceIds.has(resourceId)));
      return next.size === current.size ? current : next;
    });
  }, [visibleResourceIds]);

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
    if (didAutoSelectResource.current || selectedResourceId) {
      return;
    }
    const nextId = pickInitialResourceId(resources, initialResourceContextIds, sandboxPreviewInput);
    if (!nextId) {
      return;
    }
    didAutoSelectResource.current = true;
    setSelectedResourceId(nextId);
  }, [initialResourceContextIds, resources, sandboxPreviewInput, selectedResourceId]);

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
    setSelectedResourceIds((current) => {
      const next = new Set(current);
      pendingDeletedResourceIds.forEach((resourceId) => next.delete(resourceId));
      return next;
    });
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

  const selectResource = (resource: ResourceRecord) => {
    setResourceDetail(resource.id);
  };

  const toggleResourceSelection = (resourceId: string) => {
    setSelectedResourceIds((current) => {
      const next = new Set(current);
      if (next.has(resourceId)) {
        next.delete(resourceId);
      } else {
        next.add(resourceId);
      }
      return next;
    });
  };

  const setResourceSelection = (resourceIds: string[], selected: boolean) => {
    setSelectedResourceIds((current) => {
      const next = new Set(current);
      resourceIds.forEach((resourceId) => {
        if (selected) {
          next.add(resourceId);
        } else {
          next.delete(resourceId);
        }
      });
      return next;
    });
  };

  const selectAllVisibleResources = () => {
    setSelectedResourceIds((current) => {
      const next = new Set(current);
      visibleResources.forEach((resource) => next.add(resource.id));
      return next;
    });
  };

  const clearResourceSelection = () => {
    setSelectedResourceIds(new Set<string>());
  };

  const reportMutationFailure = (kind: ResourceMutationKind, resourceIds: string[]) => {
    if (kind === "delete") {
      setPendingDeletedResourceIds([]);
    } else {
      setPendingRestoredResourceIds([]);
    }
    setMutationResult({ kind, resourceIds, status: "failed" });
  };

  const deleteSelectedResources = () => {
    const resourceIds = [...selectedResourceIds].filter((resourceId) => visibleResourceIds.has(resourceId));
    if (resourceIds.length === 0 || !canWriteResources || deleteActionDisabled || !onDeleteResources) {
      return;
    }
    setDeleteConfirmationResourceIds(resourceIds);
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

  const restoreDeletedResources = () => {
    const resourceIds = restorableDeletedResources
      .map(deletedResourceId)
      .filter((resourceId): resourceId is string => Boolean(resourceId));
    if (resourceIds.length === 0 || !canWriteResources || restoreActionDisabled || !onRestoreResources) {
      return;
    }
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
    if (event.key === "Escape" && selectedResourceIds.size > 0) {
      event.preventDefault();
      clearResourceSelection();
      return;
    }

    if (event.key === "Escape" && selectedResourceId) {
      event.preventDefault();
      setResourceDetail(null);
      return;
    }

    if (event.target instanceof HTMLInputElement && event.key === " ") {
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
    new Set(selectedResourceSource.map(compactSourceLabel)),
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
  const selectedResourceTrust = selectedResource ? resourceTrust(selectedResource) : undefined;
  const selectedResourceFreshness = selectedResource?.freshness;
  const selectedResourcePreviewMode = selectedResource
    ? resourcePreviewMode(selectedResource, language)
    : undefined;
  const selectedResourcePreviewSummary = selectedResource
    ? resourcePreviewSummary(selectedResource)
    : undefined;
  const sandboxPreview =
    selectedResource && sandboxPreviewInput?.path === selectedResource.sandboxPath
      ? sandboxPreviewInput
      : undefined;
  const selectedResourceReuseSummary = selectedResource ? resourceReuseSummary(language) : undefined;
  const hasSelectedResourceFacts = Boolean(
    selectedResourceSource.length ||
    selectedResourceIndexNotice ||
    selectedResourceTrust ||
    (selectedResourceFreshness && selectedResourceFreshness !== "unknown") ||
    selectedResourcePreviewMode ||
    selectedResourceTrainingReadiness,
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
      sandboxPreviewEmbedded: false,
      sandboxPreviewVisible: false,
      selectedSandboxPath: restoreContext?.sandboxPath ?? sandboxRoot,
      previewPath: restoreContext?.previewPath,
      singleWorkbenchSurface: true,
      compactMode: true,
      modebarHiddenInCompact: true,
      detailPaneVisible: Boolean(selectedResource),
      sandboxPaneVisible: activeSurface === "sandbox",
      previewPaneVisible: false,
    });
  }, [language, onDebugVisibleFacts, orientation, restoreContext, sandboxRoot, selectedResource]);

  return (
    <section
      className={`workbench-pane resources-pane resources-pane--library resources-knowledge resources-knowledge--workspace-tree${selectedResource ? " is-detail-open" : ""}`}
      aria-label={localize(language, "title")}
      data-resources-leftover-not-live={leftoverStoredNote ? "true" : undefined}
    >
      <div className="workbench-pane__heading resources-knowledge__heading sr-only">
        <h2>{localize(language, "title")}</h2>
      </div>
      {leftoverStoredNote ? null : (
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
          {hasResourceSelection ? (
            <details className="resources-knowledge__batch-actions">
              <summary>
                <span
                  className="resources-knowledge__selection-count"
                  aria-live="polite"
                  aria-label={`${localize(language, "selectedResources")}: ${selectedResourceIds.size}`}
                >
                  {selectedResourceIds.size}
                </span>
                <strong>{localize(language, "selectedResources")}</strong>
              </summary>
              <div className="resources-knowledge__batch-actions-body">
                <button
                  className="resources-knowledge__icon-button"
                  type="button"
                  onClick={selectAllVisibleResources}
                  disabled={allVisibleResourcesSelected}
                  aria-label={localize(language, "selectAllVisible")}
                  title={localize(language, "selectAllVisible")}
                >
                  <CheckIcon size={16} />
                </button>
                <button
                  className="resources-knowledge__icon-button"
                  type="button"
                  onClick={clearResourceSelection}
                  aria-label={localize(language, "clearSelection")}
                  title={localize(language, "clearSelection")}
                >
                  <CloseIcon size={15} />
                </button>
                <button
                  className="resources-knowledge__icon-button resources-knowledge__delete-button"
                  type="button"
                  onClick={deleteSelectedResources}
                  disabled={deleteActionDisabled}
                  aria-busy={isDeletePending}
                  aria-label={deleteSelectedLabel}
                  title={deleteSelectedLabel}
                >
                  <TrashIcon size={16} />
                </button>
              </div>
            </details>
          ) : (
            <>
              <div className="resources-knowledge__import-menu-wrap">
                <button
                  ref={importMenuTriggerRef}
                  className={`button button--primary button--compact resources-knowledge__add-resource${canWriteResources && isImportMenuOpen ? " is-open" : ""}`}
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
              <button
                className="resources-knowledge__icon-button resources-knowledge__refresh-button"
                type="button"
                onClick={refreshResources}
                disabled={indexActionDisabled}
                aria-busy={isIndexRefreshing}
                aria-label={refreshResourcesLabel}
                title={refreshResourcesLabel}
              >
                <RefreshIcon size={16} />
              </button>
            </>
          )}
        </div>
      </div>
      )}

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

      {orientationState ? (
        <div
          className={`resources-knowledge__orientation is-${orientationTone ?? "neutral"}`}
          role={mutationStatus ? undefined : "status"}
          aria-live="polite"
        >
          <strong>{orientationState}</strong>
          {orientation?.why ? <span>{orientation.why}</span> : null}
          {orientation && orientationCanAct ? (
            <button
              className="button button--primary button--compact"
              type="button"
              aria-label={orientation.primaryActionLabel}
              onClick={() => onOrientationAction?.(orientation.primaryAction)}
            >
              {orientation.primaryActionLabel}
            </button>
          ) : null}
        </div>
      ) : null}

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

      {null}

      {leftoverStoredNote ? null : restoreContext?.surface === "sandbox" ? (
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

      {searchStatus ? (
        <div
          className={`resources-knowledge__mutation is-${searchStatus.tone}`}
          role="status"
          aria-live="polite"
        >
          <span>{searchStatus.label}</span>
        </div>
      ) : null}

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
            {localizeCount(language, "deleteConfirmation", deleteConfirmationResourceIds.length)}
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

      {mutationStatus ? (
        <div
          className={`resources-knowledge__mutation is-${mutationStatus.tone}`}
          role="status"
          aria-live="polite"
        >
          <span>{mutationStatus.label}</span>
          {mutationStatus.tone === "failed" && onRefreshDeletedResources ? (
            <button
              className="resources-knowledge__icon-button"
              type="button"
              onClick={onRefreshDeletedResources}
              aria-label={localize(language, "refreshTrash")}
              title={localize(language, "refreshTrash")}
            >
              <RefreshIcon size={14} />
            </button>
          ) : null}
        </div>
      ) : null}

      {leftoverStoredNote ? null : (
      <div
        className="resources-knowledge__tree"
        ref={treeRef}
        role="tree"
        aria-label={localize(language, "title")}
        aria-multiselectable="true"
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
                selectedResourceIds={selectedResourceIds}
                activeTreeItemId={resolvedActiveTreeItemId}
                onToggle={toggleCollection}
                onSelect={selectResource}
                onToggleSelection={toggleResourceSelection}
                onSetSelection={setResourceSelection}
                onOpen={openResourceInVsCode}
                onActiveTreeItemChange={(id) => setActiveTreeItemId(id)}
                onMoveTreeFocus={moveTreeFocus}
              />
            ))}

            {resources.length === 0 && !hasSearchQuery ? (
              <div className="empty-state resources-empty">
                <span className="empty-state__icon" aria-hidden="true">
                  <FolderIcon size={20} />
                </span>
                <strong className="empty-state__title">{localize(language, "emptyTitle")}</strong>
                <p>{localize(language, "emptyBody")}</p>
                <p className="resources-knowledge__empty-hint">{resourceReuseSummary(language)}</p>
                {canWriteResources && onImportFiles ? (
                  <button
                    className="button button--primary button--compact empty-state__action"
                    type="button"
                    onClick={() => runImportAction(onImportFiles)}
                  >
                    <UploadIcon size={13} aria-hidden="true" />
                    <span>{localize(language, "addResource")}</span>
                  </button>
                ) : null}
              </div>
            ) : null}

            {shouldShowNoMatches ? (
              <div className="empty-state resources-empty">
                <span className="empty-state__icon" aria-hidden="true">
                  <SearchIcon size={20} />
                </span>
                <strong className="empty-state__title">{localize(language, "noMatches")}</strong>
                <p className="resources-knowledge__empty-hint">{resourceReuseSummary(language)}</p>
              </div>
            ) : null}
          </>
        )}

      {leftoverStoredNote ? null : (
      <details
        className="resources-knowledge__trash resources-library-tree__trash"
        open={trashOpen}
        onToggle={(event) => setTrashOpen(event.currentTarget.open)}
        aria-busy={isRestorePending}
      >
        <summary>
          <span>
            <TrashIcon size={13} aria-hidden="true" />
            <strong>{localize(language, "trashTitle")}</strong>
          </span>
          <em>
            {trashSnapshotAvailable
              ? localizeCount(language, "recoveryAvailable", trashedResources.length)
              : localize(language, "unavailable")}
          </em>
        </summary>
        <div className="resources-knowledge__trash-body">
          {!trashSnapshotAvailable ? (
            <div className="empty-state resources-empty">
              <span className="empty-state__icon" aria-hidden="true">
                <TrashIcon size={18} />
              </span>
              <p>{localize(language, "trashLoading")}</p>
            </div>
          ) : null}
          {trashSnapshotAvailable && trashedResources.length === 0 ? (
            <div className="empty-state resources-empty">
              <span className="empty-state__icon" aria-hidden="true">
                <TrashIcon size={18} />
              </span>
              <p>{localize(language, "trashEmpty")}</p>
            </div>
          ) : null}
          {trashSnapshotAvailable && trashedResources.length > 0 ? (
            <>
              <ul className="resources-knowledge__trash-list">
                {trashedResources.map((resource, index) => {
                  const resourceId = deletedResourceId(resource);
                  const canRestore = isDeletedResourceRecoverable(resource);
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
                    </li>
                  );
                })}
              </ul>
              <div className="resources-knowledge__trash-actions">
                <button
                  className="button button--compact resources-knowledge__restore-action"
                  type="button"
                  onClick={restoreDeletedResources}
                  disabled={restoreActionDisabled}
                  aria-busy={isRestorePending}
                  aria-label={restoreDeletedLabel}
                  title={restoreDeletedLabel}
                >
                  <RefreshIcon size={13} />
                  <span>{restoreDeletedLabel}</span>
                </button>
                {onRefreshDeletedResources ? (
                  <button
                    className="resources-knowledge__icon-button"
                    type="button"
                    onClick={onRefreshDeletedResources}
                    aria-label={localize(language, "refreshTrash")}
                    title={localize(language, "refreshTrash")}
                  >
                    <RefreshIcon size={14} />
                  </button>
                ) : null}
              </div>
            </>
          ) : null}
        </div>
      </details>
      )}
      </div>
      )}

      {selectedResource ? (
        <section
          className="resources-knowledge__detail"
          aria-label={[localize(language, "resourceDetail"), selectedResource.title]
            .filter(Boolean)
            .join(". ")}
          aria-live="polite"
        >
          <section
            className="resources-knowledge__detail-object"
            role="region"
            aria-label={selectedResource.title}
          >
          <header
            className="resources-knowledge__current resources-knowledge__detail-header"
            data-view-identity="true"
          >
            <strong className="resources-knowledge__current-object" data-view-object="">
              {selectedResource.title}
            </strong>
            <button
              className="resources-knowledge__icon-button"
              type="button"
              onClick={() => setResourceDetail(null)}
              aria-label={localize(language, "closeDetails")}
              title={localize(language, "closeDetails")}
            >
              <CloseIcon size={13} />
            </button>
          </header>
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
            <details className="resources-knowledge__governance">
            <summary>{localize(language, "resourceDetail")}</summary>
            <dl className="resources-knowledge__facts">
              {selectedResourceSource.length > 0 ? (
                <div className="resources-knowledge__fact resources-knowledge__fact--source">
                  <dt>{localize(language, "source")}</dt>
                  <dd title={selectedResourceSource.join(" / ")}>{selectedResourceSourceLabel}</dd>
                </div>
              ) : null}
              {selectedResourceIndexNotice ? (
                <div className={`resources-knowledge__fact resources-knowledge__fact--index ${selectedResourceIndexNotice.tone}`}>
                  <dt>{localize(language, "index")}</dt>
                  <dd>{selectedResourceIndexNotice.label}</dd>
                </div>
              ) : null}
              {selectedResourceTrust ? (
                <div className="resources-knowledge__fact">
                  <dt>{localize(language, "trust")}</dt>
                  <dd>{selectedResourceTrust}</dd>
                </div>
              ) : null}
              {selectedResourceFreshness && selectedResourceFreshness !== "unknown" ? (
                <div className="resources-knowledge__fact">
                  <dt>{localize(language, "freshness")}</dt>
                  <dd>{describeFreshness(selectedResourceFreshness, language)}</dd>
                </div>
              ) : null}
              {selectedResourcePreviewMode ? (
                <div className="resources-knowledge__fact resources-knowledge__fact--preview">
                  <dt>{resourcePreviewHeading(language)}</dt>
                  <dd title={selectedResourcePreviewMode}>{selectedResourcePreviewMode}</dd>
                </div>
              ) : null}
              {selectedResourceTrainingReadiness ? (
                <div
                  className={`resources-knowledge__fact resources-knowledge__fact--training is-${
                    selectedResourceTrainingReadiness.tone
                  }`}
                >
                  <dt>{localize(language, "training")}</dt>
                  <dd>{selectedResourceTrainingReadiness.message}</dd>
                </div>
              ) : null}
            </dl>
          {selectedResourceReuseSummary ? (
            <p className="resources-knowledge__reuse-summary">{selectedResourceReuseSummary}</p>
          ) : null}

          {selectedResourceTrainingState || selectedResourceCanStartTraining ? (
            <details className="resources-knowledge__training-handoff">
              <summary><strong>{localize(language, "training")}</strong></summary>
              {selectedResourceTrainingState ? (
                <div
                  className={`resources-knowledge__mutation is-${
                    selectedResourceTrainingState.phase === "loading"
                      ? "pending"
                      : selectedResourceTrainingState.phase === "failed"
                        ? "failed"
                        : "info"
                  }`}
                  role="status"
                  aria-live="polite"
                >
                  <span>{selectedResourceTrainingStatusMessage}</span>
                </div>
              ) : null}
              {selectedResourceCanStartTraining ? (
                selectedResourceTrainingIsAvailable ? (
                  <button className="button button--primary button--compact" type="button" onClick={onOpenTraining} disabled={!onOpenTraining}>
                    <ArrowRightIcon size={12} />
                    <span>{localize(language, "openCurrentTraining")}</span>
                  </button>
                ) : (
                  <button className="button button--primary button--compact" type="button" onClick={startTrainingFromSelectedResource} disabled={selectedResourceTrainingState?.phase === "loading"} aria-busy={selectedResourceTrainingState?.phase === "loading"}>
                    <ArrowRightIcon size={12} />
                    <span>{resourceTrainingStartCopy(language, selectedResourceTrainingState?.phase === "loading" ? "loading" : undefined)}</span>
                  </button>
                )
              ) : null}
            </details>
          ) : null}
          </details>
          ) : null}
          {!sandboxPreview ? (
          <div className="resources-knowledge__detail-actions">
            {onPreviewResource && selectedResource.sandboxPath ? (
              <button
                className="button button--ghost button--compact"
                type="button"
                onClick={() => onPreviewResource(selectedResource.id)}
                disabled={isBrowserPreview && !isLiveBrowserPreview}
              >
                <ArrowRightIcon size={12} />
                <span>{resourcePreviewHeading(language)}</span>
              </button>
            ) : null}
            {selectedResourceTrainingReadiness?.canRefresh ? (
              <button
                className="button button--primary button--compact"
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
              className="button button--primary button--compact resources-knowledge__open-action"
              type="button"
              onClick={() => openResourceInVsCode(selectedResource)}
              disabled={selectedResourceOpenTarget.kind === "unavailable"}
              aria-label={`${selectedResourceOpenLabel}: ${selectedResource.title}`}
              title={selectedResourceOpenLabel}
            >
              <ArrowRightIcon size={12} />
              <span>{selectedResourceOpenLabel}</span>
            </button>
          </div>
          ) : null}
          </section>
        </section>
      ) : null}
    </section>
  );
}
