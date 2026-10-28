/**
 * Trainer 核心国际化翻译表
 * 支持 8 种语言：zh-CN, en-US, es-ES, fr-FR, de-DE, ja-JP, ko-KR, pt-BR
 */

import type { ComposerLanguage } from "../types";
import { deDE } from "./locales/de-DE";
import { enUS } from "./locales/en-US";
import { esES } from "./locales/es-ES";
import { frFR } from "./locales/fr-FR";
import { jaJP } from "./locales/ja-JP";
import { koKR } from "./locales/ko-KR";
import { ptBR } from "./locales/pt-BR";
import { zhCN } from "./locales/zh-CN";
import type { Copy, CopyTable } from "./copyTypes";

export type { Copy, CopyKey } from "./copyTypes";

// =============================================================================
// 翻译表
// =============================================================================

export const copyTable = {
  "zh-CN": zhCN,
  "en-US": enUS,
  "es-ES": esES,
  "fr-FR": frFR,
  "de-DE": deDE,
  "ja-JP": jaJP,
  "ko-KR": koKR,
  "pt-BR": ptBR,
} satisfies CopyTable;

const defaultCopy = copyTable["en-US"];

const resourceViewLocaleOverrides: Partial<Record<ComposerLanguage, Partial<Copy>>> = {
  "es-ES": {
    settingsMemorySharing: "Memoria entre proyectos",
    settingsMemorySharingDetail: "Los proyectos permanecen aislados por defecto. Solo se leen preferencias y señales de dominio autorizadas explícitamente.",
    settingsMemorySharingNone: "No hay otros proyectos autorizados.",
    settingsMemorySharingActive: "fuentes autorizadas",
    settingsMemorySharingUnavailable: "Agrega el proyecto actual a Trainer antes de autorizar memoria entre proyectos.",
    settingsMemoryShareGrant: "Autorizar proyecto",
    settingsMemoryShareRevoke: "Revocar",
    settingsMemorySharePreferences: "Preferencias",
    settingsMemoryShareMastery: "Señales de dominio",
    addFiles: "Agregar archivos",
    addFolder: "Agregar carpeta",
    addUrl: "Agregar URL",
    resourcesEmpty: "La biblioteca está vacía. Empieza importando aquí",
    resourcesMenu: "Menú de recursos",
    resourcesSummary: "Resumen de recursos",
  },
  "fr-FR": {
    settingsMemorySharing: "Mémoire inter-projets",
    settingsMemorySharingDetail: "Les projets restent isolés par défaut. Seules les préférences et signaux de maîtrise explicitement autorisés sont lus.",
    settingsMemorySharingNone: "Aucun autre projet n'est autorisé.",
    settingsMemorySharingActive: "sources autorisées",
    settingsMemorySharingUnavailable: "Ajoutez le projet actuel à Trainer avant d'autoriser la mémoire inter-projets.",
    settingsMemoryShareGrant: "Autoriser un projet",
    settingsMemoryShareRevoke: "Révoquer",
    settingsMemorySharePreferences: "Préférences",
    settingsMemoryShareMastery: "Signaux de maîtrise",
    addFiles: "Ajouter des fichiers",
    addFolder: "Ajouter un dossier",
    addUrl: "Ajouter une URL",
    resourcesEmpty: "La bibliothèque est vide. Commencez l'import ici",
    resourcesMenu: "Menu des ressources",
    resourcesSummary: "Résumé des ressources",
  },
  "de-DE": {
    settingsMemorySharing: "Projektübergreifender Speicher",
    settingsMemorySharingDetail: "Projekte bleiben standardmäßig getrennt. Nur ausdrücklich erlaubte Präferenzen und Kompetenzsignale werden gelesen.",
    settingsMemorySharingNone: "Es sind keine anderen Projekte autorisiert.",
    settingsMemorySharingActive: "autorisierte Quellen",
    settingsMemorySharingUnavailable: "Fügen Sie das aktuelle Projekt zu Trainer hinzu, bevor Sie projektübergreifenden Speicher erlauben.",
    settingsMemoryShareGrant: "Projekt erlauben",
    settingsMemoryShareRevoke: "Widerrufen",
    settingsMemorySharePreferences: "Präferenzen",
    settingsMemoryShareMastery: "Kompetenzsignale",
    addFiles: "Dateien hinzufügen",
    addFolder: "Ordner hinzufügen",
    addUrl: "URL hinzufügen",
    resourcesEmpty: "Die Bibliothek ist leer. Hier mit dem Import beginnen",
    resourcesMenu: "Ressourcenmenü",
    resourcesSummary: "Ressourcenübersicht",
  },
  "ja-JP": {
    settingsMemorySharing: "プロジェクト間メモリ",
    settingsMemorySharingDetail: "プロジェクトは既定で分離されます。明示的に許可した設定と習熟シグナルだけを読み取ります。",
    settingsMemorySharingNone: "許可した別プロジェクトはありません。",
    settingsMemorySharingActive: "件の許可済みソース",
    settingsMemorySharingUnavailable: "プロジェクト間メモリを許可する前に、現在のプロジェクトを Trainer に追加してください。",
    settingsMemoryShareGrant: "プロジェクトを許可",
    settingsMemoryShareRevoke: "取り消す",
    settingsMemorySharePreferences: "設定",
    settingsMemoryShareMastery: "習熟シグナル",
    addFiles: "ファイルを追加",
    addFolder: "フォルダを追加",
    addUrl: "URL を追加",
    resourcesEmpty: "ライブラリは空です。ここから取り込みを始めてください",
    resourcesMenu: "リソースメニュー",
    resourcesSummary: "リソース概要",
  },
  "ko-KR": {
    settingsMemorySharing: "프로젝트 간 메모리",
    settingsMemorySharingDetail: "프로젝트는 기본적으로 분리됩니다. 명시적으로 허용한 환경설정과 숙련 신호만 읽습니다.",
    settingsMemorySharingNone: "허용된 다른 프로젝트가 없습니다.",
    settingsMemorySharingActive: "개의 허용된 소스",
    settingsMemorySharingUnavailable: "프로젝트 간 메모리를 허용하기 전에 현재 프로젝트를 Trainer에 추가하세요.",
    settingsMemoryShareGrant: "프로젝트 허용",
    settingsMemoryShareRevoke: "취소",
    settingsMemorySharePreferences: "환경설정",
    settingsMemoryShareMastery: "숙련 신호",
    addFiles: "파일 추가",
    addFolder: "폴더 추가",
    addUrl: "URL 추가",
    resourcesEmpty: "라이브러리가 비어 있습니다. 여기서 가져오기를 시작하세요",
    resourcesMenu: "리소스 메뉴",
    resourcesSummary: "리소스 요약",
  },
  "pt-BR": {
    settingsMemorySharing: "Memória entre projetos",
    settingsMemorySharingDetail: "Os projetos permanecem isolados por padrão. Apenas preferências e sinais de domínio autorizados explicitamente são lidos.",
    settingsMemorySharingNone: "Nenhum outro projeto está autorizado.",
    settingsMemorySharingActive: "fontes autorizadas",
    settingsMemorySharingUnavailable: "Adicione o projeto atual ao Trainer antes de autorizar memória entre projetos.",
    settingsMemoryShareGrant: "Autorizar projeto",
    settingsMemoryShareRevoke: "Revogar",
    settingsMemorySharePreferences: "Preferências",
    settingsMemoryShareMastery: "Sinais de domínio",
    addFiles: "Adicionar arquivos",
    addFolder: "Adicionar pasta",
    addUrl: "Adicionar URL",
    resourcesEmpty: "A biblioteca está vazia. Comece a importar aqui",
    resourcesMenu: "Menu de recursos",
    resourcesSummary: "Resumo dos recursos",
  },
};

type ContextRailCopy = Pick<
  Copy,
  | "openCoach"
  | "openSettings"
  | "composerPlaceholder"
  | "composerPlaceholderPlan"
  | "streaming"
  | "viewContextWorking"
  | "viewContextBlocker"
  | "viewContextLatest"
  | "viewContextCoach"
>;

const contextRailLocaleOverrides: Record<ComposerLanguage, ContextRailCopy> = {
  "zh-CN": {
    openSettings: "打开设置",
    composerPlaceholder: "问教练",
    composerPlaceholderPlan: "写下这一步",
    streaming: "教练正在思考…",
    openCoach: "\u6253\u5f00\u6559\u7ec3",
    viewContextWorking: "\u6b63\u5728\u5904\u7406",
    viewContextBlocker: "\u53d7\u963b",
    viewContextLatest: "\u6700\u8fd1\u7ed3\u679c",
    viewContextCoach: "\u6559\u7ec3\u4e0a\u4e0b\u6587",
  },
  "en-US": {
    openSettings: "Open Settings",
    composerPlaceholder: "Ask the coach",
    composerPlaceholderPlan: "Write the next step",
    streaming: "Coach thinking…",
    openCoach: "Open Coach",
    viewContextWorking: "Working",
    viewContextBlocker: "Blocker",
    viewContextLatest: "Latest",
    viewContextCoach: "Coach context",
  },
  "es-ES": {
    openSettings: "Abrir Ajustes",
    composerPlaceholder: "Dile al entrenador qué quieres construir o dónde estás bloqueado.",
    composerPlaceholderPlan: "Explica cómo ajustar este plan o cuál debería ser el siguiente paso.",
    streaming: "El entrenador está pensando…",
    openCoach: "Abrir Coach",
    viewContextWorking: "En curso",
    viewContextBlocker: "Bloqueado",
    viewContextLatest: "\u00daltimo resultado",
    viewContextCoach: "Contexto del coach",
  },
  "fr-FR": {
    openSettings: "Ouvrir les réglages",
    composerPlaceholder: "Dites au coach ce que vous voulez construire ou où vous êtes bloqué.",
    composerPlaceholderPlan: "Expliquez comment ajuster ce plan ou clarifiez la prochaine étape.",
    streaming: "Le coach réfléchit…",
    openCoach: "Ouvrir le coach",
    viewContextWorking: "En cours",
    viewContextBlocker: "Bloqu\u00e9",
    viewContextLatest: "Dernier r\u00e9sultat",
    viewContextCoach: "Contexte du coach",
  },
  "de-DE": {
    openSettings: "Einstellungen öffnen",
    composerPlaceholder: "Sag dem Coach, was du bauen möchtest oder wo du festhängst.",
    composerPlaceholderPlan: "Besprich, wie dieser Plan angepasst werden soll, oder kläre den nächsten Schritt.",
    streaming: "Coach denkt nach…",
    openCoach: "Coach \u00f6ffnen",
    viewContextWorking: "Wird verarbeitet",
    viewContextBlocker: "Blockiert",
    viewContextLatest: "Neuestes Ergebnis",
    viewContextCoach: "Coach-Kontext",
  },
  "ja-JP": {
    openSettings: "設定を開く",
    composerPlaceholder: "作りたいものや、行き詰まっている箇所をコーチに伝えてください。",
    composerPlaceholderPlan: "この計画の調整方法や次の一歩をコーチと整理してください。",
    streaming: "コーチが考えています…",
    openCoach: "\u30b3\u30fc\u30c1\u3092\u958b\u304f",
    viewContextWorking: "\u51e6\u7406\u4e2d",
    viewContextBlocker: "\u30d6\u30ed\u30c3\u30af\u4e2d",
    viewContextLatest: "\u6700\u65b0\u306e\u7d50\u679c",
    viewContextCoach: "\u30b3\u30fc\u30c1\u306e\u30b3\u30f3\u30c6\u30ad\u30b9\u30c8",
  },
  "ko-KR": {
    openSettings: "설정 열기",
    composerPlaceholder: "만들고 싶은 것 또는 막힌 지점을 코치에게 알려 주세요.",
    composerPlaceholderPlan: "이 계획을 어떻게 조정할지 또는 다음 단계를 코치와 정리하세요.",
    streaming: "코치가 생각 중입니다…",
    openCoach: "\ucf54\uce58 \uc5f4\uae30",
    viewContextWorking: "\ucc98\ub9ac \uc911",
    viewContextBlocker: "\ucc28\ub2e8\ub428",
    viewContextLatest: "\ucd5c\uadfc \uacb0\uacfc",
    viewContextCoach: "\ucf54\uce58 \ucee8\ud14d\uc2a4\ud2b8",
  },
  "pt-BR": {
    openSettings: "Abrir configurações",
    composerPlaceholder: "Diga ao coach o que você quer construir ou onde está bloqueado.",
    composerPlaceholderPlan: "Explique como ajustar este plano ou esclareça o próximo passo.",
    streaming: "O coach está pensando…",
    openCoach: "Abrir coach",
    viewContextWorking: "Em andamento",
    viewContextBlocker: "Bloqueado",
    viewContextLatest: "Resultado recente",
    viewContextCoach: "Contexto do coach",
  },
};

type TrainingUiCopy = Pick<
  Copy,
  | "nextCard"
  | "trainingOpenCurrentCard"
  | "trainingReturnToCoach"
  | "trainingAnswerNow"
  | "trainingRecordStep"
  | "trainingStartStep"
  | "trainingEmptyTitle"
  | "trainingEmptyDescription"
>;

const trainingUiLocaleOverrides: Record<ComposerLanguage, TrainingUiCopy> = {
  "zh-CN": {
    nextCard: "下一张",
    trainingOpenCurrentCard: "\u7ee7\u7eed\uff1a\u6253\u5f00\u5f53\u524d\u5361\u7247",
    trainingReturnToCoach: "\u5e26\u7ed3\u679c\u56de\u5230\u6559\u7ec3",
    trainingAnswerNow: "\u73b0\u5728\u4f5c\u7b54",
    trainingRecordStep: "\u8bb0\u5f55\u8fd9\u4e00\u6b65",
    trainingStartStep: "\u5f00\u59cb\u8fd9\u4e00\u6b65",
    trainingEmptyTitle: "\u8fd8\u6ca1\u6709\u660e\u786e\u7684\u8bad\u7ec3\u5361\u7247",
    trainingEmptyDescription:
      "\u5f00\u59cb\u8bad\u7ec3\u540e\uff0c\u4f1a\u6309\u5f53\u524d\u91cd\u70b9\u751f\u6210\u4e00\u5f20\u5c0f\u800c\u53ef\u9a8c\u8bc1\u7684\u4efb\u52a1\u3002",
  },
  "en-US": {
    nextCard: "Next card",
    trainingOpenCurrentCard: "Continue: Open current card",
    trainingReturnToCoach: "Return result to Coach",
    trainingAnswerNow: "Answer now",
    trainingRecordStep: "Record this step",
    trainingStartStep: "Start this step",
    trainingEmptyTitle: "No training card yet",
    trainingEmptyDescription: "Start training to create one small, verifiable task from your current focus.",
  },
  "es-ES": {
    nextCard: "Siguiente tarjeta",
    trainingOpenCurrentCard: "Continuar: abrir la tarjeta actual",
    trainingReturnToCoach: "Volver al coach con el resultado",
    trainingAnswerNow: "Responder ahora",
    trainingRecordStep: "Registrar este paso",
    trainingStartStep: "Empezar este paso",
    trainingEmptyTitle: "A\u00fan no hay una tarjeta de entrenamiento",
    trainingEmptyDescription:
      "Inicia el entrenamiento para crear una tarea peque\u00f1a y verificable a partir de tu enfoque actual.",
  },
  "fr-FR": {
    nextCard: "Carte suivante",
    trainingOpenCurrentCard: "Continuer : ouvrir la carte actuelle",
    trainingReturnToCoach: "Ramener le r\u00e9sultat au coach",
    trainingAnswerNow: "R\u00e9pondre maintenant",
    trainingRecordStep: "Noter cette \u00e9tape",
    trainingStartStep: "Commencer cette \u00e9tape",
    trainingEmptyTitle: "Aucune carte d'entra\u00eenement pour le moment",
    trainingEmptyDescription:
      "Commencez l'entra\u00eenement pour cr\u00e9er une petite t\u00e2che v\u00e9rifiable depuis votre objectif actuel.",
  },
  "de-DE": {
    nextCard: "Nächste Karte",
    trainingOpenCurrentCard: "Weiter: Aktuelle Karte \u00f6ffnen",
    trainingReturnToCoach: "Ergebnis zum Coach zur\u00fcckbringen",
    trainingAnswerNow: "Jetzt antworten",
    trainingRecordStep: "Diesen Schritt festhalten",
    trainingStartStep: "Diesen Schritt beginnen",
    trainingEmptyTitle: "Noch keine Trainingskarte",
    trainingEmptyDescription:
      "Starte das Training, um aus deinem aktuellen Fokus eine kleine, \u00fcberpr\u00fcfbare Aufgabe zu erstellen.",
  },
  "ja-JP": {
    nextCard: "次のカード",
    trainingOpenCurrentCard: "\u7d9a\u3051\u308b\uff1a\u73fe\u5728\u306e\u30ab\u30fc\u30c9\u3092\u958b\u304f",
    trainingReturnToCoach: "\u7d50\u679c\u3092\u30b3\u30fc\u30c1\u306b\u623b\u3059",
    trainingAnswerNow: "\u4eca\u3059\u3050\u56de\u7b54\u3059\u308b",
    trainingRecordStep: "\u3053\u306e\u30b9\u30c6\u30c3\u30d7\u3092\u8a18\u9332\u3059\u308b",
    trainingStartStep: "\u3053\u306e\u30b9\u30c6\u30c3\u30d7\u3092\u59cb\u3081\u308b",
    trainingEmptyTitle: "\u307e\u3060\u30c8\u30ec\u30fc\u30cb\u30f3\u30b0\u30ab\u30fc\u30c9\u304c\u3042\u308a\u307e\u305b\u3093",
    trainingEmptyDescription:
      "\u958b\u59cb\u3059\u308b\u3068\u3001\u73fe\u5728\u306e\u5b66\u7fd2\u306e\u7126\u70b9\u304b\u3089\u5c0f\u3055\u304f\u78ba\u8a8d\u3067\u304d\u308b\u8ab2\u984c\u3092\u4e00\u3064\u4f5c\u308a\u307e\u3059\u3002",
  },
  "ko-KR": {
    nextCard: "다음 카드",
    trainingOpenCurrentCard: "\uacc4\uc18d: \ud604\uc7ac \uce74\ub4dc \uc5f4\uae30",
    trainingReturnToCoach: "\uacb0\uacfc\ub97c \ucf54\uce58\uc5d0\uac8c \uac00\uc838\uac00\uae30",
    trainingAnswerNow: "\uc9c0\uae08 \ub2f5\ud558\uae30",
    trainingRecordStep: "\uc774 \ub2e8\uacc4 \uae30\ub85d\ud558\uae30",
    trainingStartStep: "\uc774 \ub2e8\uacc4 \uc2dc\uc791\ud558\uae30",
    trainingEmptyTitle: "\uc544\uc9c1 \ud6c8\ub828 \uce74\ub4dc\uac00 \uc5c6\uc2b5\ub2c8\ub2e4",
    trainingEmptyDescription:
      "\uc2dc\uc791\ud558\uba74 \ud604\uc7ac \ud559\uc2b5 \ucd08\uc810\uc5d0\uc11c \uc791\uace0 \ud655\uc778 \uac00\ub2a5\ud55c \uacfc\uc81c \ud558\ub098\ub97c \ub9cc\ub4ed\ub2c8\ub2e4.",
  },
  "pt-BR": {
    nextCard: "Próximo cartão",
    trainingOpenCurrentCard: "Continuar: abrir o cart\u00e3o atual",
    trainingReturnToCoach: "Levar o resultado ao coach",
    trainingAnswerNow: "Responder agora",
    trainingRecordStep: "Registrar esta etapa",
    trainingStartStep: "Come\u00e7ar esta etapa",
    trainingEmptyTitle: "Ainda n\u00e3o h\u00e1 um cart\u00e3o de treinamento",
    trainingEmptyDescription:
      "Inicie o treino para criar uma tarefa pequena e verific\u00e1vel a partir do seu foco atual.",
  },
};

type ComposerAccessibilityCopy = Pick<Copy, "composerAccessibility">;

type OrientationRailCopy = Pick<
  Copy,
  | "orientationStateNeedsSetup"
  | "orientationStateWaiting"
  | "orientationStateWorking"
  | "orientationStateBlocked"
  | "orientationStateReady"
  | "orientationStateInterrupted"
>;

const orientationRailLocaleOverrides: Record<ComposerLanguage, OrientationRailCopy> = {
  "zh-CN": {
    orientationStateNeedsSetup: "待设置",
    orientationStateWaiting: "等待",
    orientationStateWorking: "进行中",
    orientationStateBlocked: "受阻",
    orientationStateReady: "就绪",
    orientationStateInterrupted: "中断",
  },
  "en-US": {
    orientationStateNeedsSetup: "Needs setup",
    orientationStateWaiting: "Waiting",
    orientationStateWorking: "Working",
    orientationStateBlocked: "Blocked",
    orientationStateReady: "Ready",
    orientationStateInterrupted: "Interrupted",
  },
  "es-ES": {
    orientationStateNeedsSetup: "Falta configurar",
    orientationStateWaiting: "Esperando",
    orientationStateWorking: "En curso",
    orientationStateBlocked: "Bloqueado",
    orientationStateReady: "Listo",
    orientationStateInterrupted: "Interrumpido",
  },
  "fr-FR": {
    orientationStateNeedsSetup: "À configurer",
    orientationStateWaiting: "En attente",
    orientationStateWorking: "En cours",
    orientationStateBlocked: "Bloqué",
    orientationStateReady: "Prêt",
    orientationStateInterrupted: "Interrompu",
  },
  "de-DE": {
    orientationStateNeedsSetup: "Einrichtung nötig",
    orientationStateWaiting: "Warten",
    orientationStateWorking: "Läuft",
    orientationStateBlocked: "Blockiert",
    orientationStateReady: "Bereit",
    orientationStateInterrupted: "Unterbrochen",
  },
  "ja-JP": {
    orientationStateNeedsSetup: "要設定",
    orientationStateWaiting: "待機",
    orientationStateWorking: "進行中",
    orientationStateBlocked: "停止",
    orientationStateReady: "準備完了",
    orientationStateInterrupted: "中断",
  },
  "ko-KR": {
    orientationStateNeedsSetup: "설정 필요",
    orientationStateWaiting: "대기",
    orientationStateWorking: "진행 중",
    orientationStateBlocked: "차단됨",
    orientationStateReady: "준비됨",
    orientationStateInterrupted: "중단됨",
  },
  "pt-BR": {
    orientationStateNeedsSetup: "Precisa configurar",
    orientationStateWaiting: "Aguardando",
    orientationStateWorking: "Em andamento",
    orientationStateBlocked: "Bloqueado",
    orientationStateReady: "Pronto",
    orientationStateInterrupted: "Interrompido",
  },
};

const composerAccessibilityLocaleOverrides: Record<ComposerLanguage, ComposerAccessibilityCopy> = {
  "zh-CN": { composerAccessibility: "\u6d88\u606f\u8f93\u5165\u6846" },
  "en-US": { composerAccessibility: "Message composer" },
  "es-ES": { composerAccessibility: "Campo de mensaje" },
  "fr-FR": { composerAccessibility: "Zone de message" },
  "de-DE": { composerAccessibility: "Nachrichtenfeld" },
  "ja-JP": { composerAccessibility: "\u30e1\u30c3\u30bb\u30fc\u30b8\u5165\u529b\u6b04" },
  "ko-KR": { composerAccessibility: "\uba54\uc2dc\uc9c0 \uc785\ub825\ub780" },
  "pt-BR": { composerAccessibility: "Campo de mensagem" },
};

type LeftoverHonestyCopy = Pick<Copy, "leftoverNotLive" | "leftoverNotLiveHint">;

const leftoverHonestyLocaleOverrides: Record<ComposerLanguage, LeftoverHonestyCopy> = {
  "zh-CN": {
    leftoverNotLive: "这是此工作区里存下的旧痕迹，不是当前正式计划。",
    leftoverNotLiveHint: "这些只是提示，不会生成计划或任务。",
  },
  "en-US": {
    leftoverNotLive: "This is stored leftover on this workspace, not the live plan.",
    leftoverNotLiveHint: "These chips are hints only. They do not create a plan or task.",
  },
  "es-ES": {
    leftoverNotLive: "Esto es un resto guardado en este espacio, no el plan en vivo.",
    leftoverNotLiveHint: "Estas son solo pistas. No crean un plan ni una tarea.",
  },
  "fr-FR": {
    leftoverNotLive: "Ceci est un reste enregistré sur cet espace, pas le plan actuel.",
    leftoverNotLiveHint: "Ce sont seulement des indices. Ils ne créent ni plan ni tâche.",
  },
  "de-DE": {
    leftoverNotLive: "Das ist ein gespeicherter Rest in diesem Arbeitsbereich, nicht der aktuelle Plan.",
    leftoverNotLiveHint: "Das sind nur Hinweise. Sie erzeugen keinen Plan und keine Aufgabe.",
  },
  "ja-JP": {
    leftoverNotLive: "これはこのワークスペースに残った記録であり、現在の正式な計画ではありません。",
    leftoverNotLiveHint: "これは手がかりだけです。計画やタスクは作りません。",
  },
  "ko-KR": {
    leftoverNotLive: "이건 이 작업 공간에 남은 기록이지, 현재 공식 계획이 아닙니다.",
    leftoverNotLiveHint: "이건 힌트일 뿐입니다. 계획이나 과제를 만들지 않습니다.",
  },
  "pt-BR": {
    leftoverNotLive: "Isto é um resto guardado neste espaço, não o plano ao vivo.",
    leftoverNotLiveHint: "Isto são só dicas. Não criam plano nem tarefa.",
  },
};

// Resolved copies are treated as immutable, so cache one object per language.
// Callers (and useMemo deps) rely on reference stability across renders.
const resolveCopyCache = new Map<ComposerLanguage, Copy>();

export function resolveCopy(language: ComposerLanguage): Copy {
  const cached = resolveCopyCache.get(language);
  if (cached) {
    return cached;
  }
  const resolved: Copy = {
    ...defaultCopy,
    ...(copyTable[language] ?? {}),
    ...(resourceViewLocaleOverrides[language] ?? {}),
    ...contextRailLocaleOverrides[language],
    ...trainingUiLocaleOverrides[language],
    ...composerAccessibilityLocaleOverrides[language],
    ...orientationRailLocaleOverrides[language],
    ...leftoverHonestyLocaleOverrides[language],
  };
  resolveCopyCache.set(language, resolved);
  return resolved;
}
