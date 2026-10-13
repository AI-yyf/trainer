/**
 * §十五: coach-domain inline copy tables migrated verbatim from their
 * components (AgentActivityStrip-era helpers excluded — they live in the
 * per-domain segment files). The zh-CN/en-US locale keys are the record
 * shape each table historically used; see the source components for usage.
 */

import type { ComposerLanguage } from "../../types";

/** In-message typing label: text carries the state, the dots only decorate it. */
export const COACH_TYPING_LABELS: Record<ComposerLanguage, string> = {
  "zh-CN": "教练正在输入…",
  "en-US": "Coach is typing…",
  "es-ES": "El entrenador está escribiendo…",
  "fr-FR": "Le coach écrit…",
  "de-DE": "Coach schreibt…",
  "ja-JP": "コーチが入力中…",
  "ko-KR": "코치가 입력 중…",
  "pt-BR": "O coach está digitando…",
};

export const HISTORY_COPY: Record<ComposerLanguage, Record<"title" | "newChat" | "refresh" | "search" | "untitled" | "messages" | "loading" | "error" | "empty" | "noMatches" | "current" | "today" | "yesterday" | "last7" | "earlier", string>> = {
  "zh-CN": {
    "title": "历史会话",
    "newChat": "+ 新对话",
    "refresh": "刷新会话列表",
    "search": "搜索会话",
    "untitled": "未命名会话",
    "messages": "{n} 条消息",
    "loading": "正在读取会话…",
    "error": "暂时读不到会话，稍后再试。",
    "empty": "还没有历史会话。新的对话会出现在这里。",
    "noMatches": "没有匹配的会话。",
    "current": "当前会话",
    "today": "今天",
    "yesterday": "昨天",
    "last7": "过去 7 天",
    "earlier": "更早"
  },
  "en-US": {
    "title": "Conversations",
    "newChat": "+ New chat",
    "refresh": "Refresh conversation list",
    "search": "Search chats",
    "untitled": "Untitled conversation",
    "messages": "{n} messages",
    "loading": "Loading conversations…",
    "error": "Couldn’t load conversations. Try again.",
    "empty": "No past conversations yet. New chats will appear here.",
    "noMatches": "No matching conversations.",
    "current": "Current",
    "today": "Today",
    "yesterday": "Yesterday",
    "last7": "Last 7 Days",
    "earlier": "Earlier"
  },
  "es-ES": {
    "title": "Conversaciones",
    "newChat": "+ Nuevo chat",
    "refresh": "Actualizar conversaciones",
    "search": "Buscar chats",
    "untitled": "Conversación sin título",
    "messages": "{n} mensajes",
    "loading": "Cargando conversaciones…",
    "error": "No se pudieron cargar las conversaciones. Inténtalo de nuevo.",
    "empty": "Todavía no hay conversaciones anteriores.",
    "noMatches": "No hay conversaciones coincidentes.",
    "current": "Actual",
    "today": "Hoy",
    "yesterday": "Ayer",
    "last7": "Últimos 7 días",
    "earlier": "Anterior"
  },
  "fr-FR": {
    "title": "Conversations",
    "newChat": "+ Nouvelle discussion",
    "refresh": "Actualiser les conversations",
    "search": "Rechercher des discussions",
    "untitled": "Conversation sans titre",
    "messages": "{n} messages",
    "loading": "Chargement des conversations…",
    "error": "Impossible de charger les conversations. Réessayez.",
    "empty": "Aucune conversation précédente.",
    "noMatches": "Aucune conversation correspondante.",
    "current": "Actuelle",
    "today": "Aujourd’hui",
    "yesterday": "Hier",
    "last7": "7 derniers jours",
    "earlier": "Plus anciennes"
  },
  "de-DE": {
    "title": "Unterhaltungen",
    "newChat": "+ Neuer Chat",
    "refresh": "Unterhaltungen aktualisieren",
    "search": "Chats suchen",
    "untitled": "Unbenannte Unterhaltung",
    "messages": "{n} Nachrichten",
    "loading": "Unterhaltungen werden geladen…",
    "error": "Unterhaltungen konnten nicht geladen werden. Erneut versuchen.",
    "empty": "Noch keine früheren Unterhaltungen.",
    "noMatches": "Keine passenden Unterhaltungen.",
    "current": "Aktuell",
    "today": "Heute",
    "yesterday": "Gestern",
    "last7": "Letzte 7 Tage",
    "earlier": "Früher"
  },
  "ja-JP": {
    "title": "会話履歴",
    "newChat": "+ 新しい対話",
    "refresh": "会話一覧を更新",
    "search": "会話を検索",
    "untitled": "無題の会話",
    "messages": "{n} 件のメッセージ",
    "loading": "会話を読み込み中…",
    "error": "会話を読み込めません。再試行してください。",
    "empty": "過去の会話はまだありません。",
    "noMatches": "一致する会話はありません。",
    "current": "現在の会話",
    "today": "今日",
    "yesterday": "昨日",
    "last7": "過去7日間",
    "earlier": "それ以前"
  },
  "ko-KR": {
    "title": "대화 기록",
    "newChat": "+ 새 대화",
    "refresh": "대화 목록 새로고침",
    "search": "대화 검색",
    "untitled": "제목 없는 대화",
    "messages": "메시지 {n}개",
    "loading": "대화 불러오는 중…",
    "error": "대화를 불러올 수 없습니다. 다시 시도하세요.",
    "empty": "이전 대화가 없습니다.",
    "noMatches": "일치하는 대화가 없습니다.",
    "current": "현재 대화",
    "today": "오늘",
    "yesterday": "어제",
    "last7": "최근 7일",
    "earlier": "이전"
  },
  "pt-BR": {
    "title": "Conversas",
    "newChat": "+ Nova conversa",
    "refresh": "Atualizar conversas",
    "search": "Buscar conversas",
    "untitled": "Conversa sem título",
    "messages": "{n} mensagens",
    "loading": "Carregando conversas…",
    "error": "Não foi possível carregar as conversas. Tente novamente.",
    "empty": "Ainda não há conversas anteriores.",
    "noMatches": "Nenhuma conversa correspondente.",
    "current": "Atual",
    "today": "Hoje",
    "yesterday": "Ontem",
    "last7": "Últimos 7 dias",
    "earlier": "Anteriores"
  }
};

export const workspaceAuthoritySummaryCopy: Record<
  ComposerLanguage,
  {
    unconfigured: string;
    unknownSource: string;
    eyebrow: string;
    lede: string;
    root: string;
    source: string;
    ledger: string;
    mountedSources: string;
    trash: string;
    nextSafeMove: string;
  }
> = {
  "zh-CN": {
    unconfigured: "未配置",
    unknownSource: "未知来源",
    eyebrow: "工作区边界",
    lede: "显式打开的工作区根目录，就是读取、修改和整理的边界。",
    root: "根目录",
    source: "来源",
    ledger: "台账 / 检查点",
    mountedSources: "挂载来源",
    trash: "Trash",
    nextSafeMove: "下一步安全动作",
  },
  "en-US": {
    unconfigured: "Unconfigured",
    unknownSource: "Unknown source",
    eyebrow: "Workspace boundary",
    lede: "The explicitly opened workspace root is the boundary for reads, edits, and reorganization.",
    root: "Root",
    source: "Source",
    ledger: "Ledger / checkpoints",
    mountedSources: "Mounted sources",
    trash: "Trash",
    nextSafeMove: "Next safe move",
  },
  "es-ES": {
    unconfigured: "Sin configurar",
    unknownSource: "Origen desconocido",
    eyebrow: "Límite del workspace",
    lede: "La raíz del workspace abierta de forma explícita marca el límite para leer, editar y reorganizar.",
    root: "Raíz",
    source: "Origen",
    ledger: "Registro / checkpoints",
    mountedSources: "Fuentes montadas",
    trash: "Trash",
    nextSafeMove: "Siguiente movimiento seguro",
  },
  "fr-FR": {
    unconfigured: "Non configuré",
    unknownSource: "Source inconnue",
    eyebrow: "Limite du workspace",
    lede: "La racine du workspace ouverte explicitement définit la limite pour lire, modifier et réorganiser.",
    root: "Racine",
    source: "Source",
    ledger: "Journal / checkpoints",
    mountedSources: "Sources montées",
    trash: "Trash",
    nextSafeMove: "Prochain mouvement sûr",
  },
  "de-DE": {
    unconfigured: "Nicht konfiguriert",
    unknownSource: "Unbekannte Quelle",
    eyebrow: "Workspace-Grenze",
    lede: "Der ausdrücklich geöffnete Workspace-Stamm ist die Grenze für Lesen, Bearbeiten und Neuordnen.",
    root: "Wurzelpfad",
    source: "Quelle",
    ledger: "Protokoll / Checkpoints",
    mountedSources: "Eingebundene Quellen",
    trash: "Trash",
    nextSafeMove: "Nächster sicherer Schritt",
  },
  "ja-JP": {
    unconfigured: "未設定",
    unknownSource: "不明なソース",
    eyebrow: "workspace の境界",
    lede: "明示的に開いた workspace ルートが、読み取り・編集・再整理の境界になります。",
    root: "ルート",
    source: "ソース",
    ledger: "台帳 / チェックポイント",
    mountedSources: "マウント元",
    trash: "Trash",
    nextSafeMove: "次の安全な一手",
  },
  "ko-KR": {
    unconfigured: "미설정",
    unknownSource: "알 수 없는 출처",
    eyebrow: "workspace 경계",
    lede: "명시적으로 연 workspace 루트가 읽기, 편집, 재구성의 경계입니다.",
    root: "루트",
    source: "출처",
    ledger: "기록 / 체크포인트",
    mountedSources: "마운트된 소스",
    trash: "Trash",
    nextSafeMove: "다음 안전한 움직임",
  },
  "pt-BR": {
    unconfigured: "Não configurado",
    unknownSource: "Origem desconhecida",
    eyebrow: "Limite do workspace",
    lede: "A raiz do workspace aberta de forma explícita define o limite para leitura, edição e reorganização.",
    root: "Raiz",
    source: "Origem",
    ledger: "Registro / checkpoints",
    mountedSources: "Fontes montadas",
    trash: "Trash",
    nextSafeMove: "Próximo movimento seguro",
  },
};

export const MAX_STAGED_ATTACHMENTS = 4;

type ComposerLocaleCopy = {
  placeholder: string;
  busyLabel: string;
  accessibilityLabel: string;
  submitLabel: string;
  cancelLabel: string;
  emptySubmitLabel: string;
  blockedSubmitLabel: string;
  attachmentCount: (count: number) => string;
  attachmentCapability: string;
  dropToAttach: string;
  imageUnavailable: string;
  image: string;
  removeAttachment: string;
  clear: string;
  plusMenu: string;
};

export const composerLocaleCopy: Record<ComposerLanguage, ComposerLocaleCopy> = {
  "zh-CN": {
    placeholder: "问教练",
    busyLabel: "教练正在思考",
    accessibilityLabel: "向教练发送消息",
    submitLabel: "发送消息",
    cancelLabel: "取消回复",
    emptySubmitLabel: "输入消息或拖入图片后发送",
    blockedSubmitLabel: "当前无法发送",
    attachmentCount: (count) => `已附加 ${count}/${MAX_STAGED_ATTACHMENTS} 张图片`,
    attachmentCapability: "当前连接暂不支持图片输入。",
    dropToAttach: "松开以附加图片",
    imageUnavailable: "当前连接暂不支持图片输入",
    image: "图片",
    removeAttachment: "移除附件",
    clear: "清空",
    plusMenu: "给这一条加点东西",
  },
  "en-US": {
    placeholder: "Ask the coach",
    busyLabel: "Trainer is thinking",
    accessibilityLabel: "Send a message to the coach",
    submitLabel: "Send message",
    cancelLabel: "Cancel reply",
    emptySubmitLabel: "Write a message or drop an image to send",
    blockedSubmitLabel: "Sending is unavailable",
    attachmentCount: (count) => `${count} of ${MAX_STAGED_ATTACHMENTS} images attached`,
    attachmentCapability: "Image input is not available for this connection yet.",
    dropToAttach: "Drop to attach image",
    imageUnavailable: "Image input is unavailable for this connection",
    image: "image",
    removeAttachment: "Remove attachment",
    clear: "Clear",
    plusMenu: "Add to this message",
  },
  "es-ES": {
    placeholder: "Dile al entrenador qué quieres construir o dónde te has atascado.",
    busyLabel: "El entrenador está pensando",
    accessibilityLabel: "Enviar un mensaje al entrenador",
    submitLabel: "Enviar mensaje",
    cancelLabel: "Cancelar respuesta",
    emptySubmitLabel: "Escribe un mensaje o suelta una imagen para enviarlo",
    blockedSubmitLabel: "Ahora no se puede enviar",
    attachmentCount: (count) => `${count} de ${MAX_STAGED_ATTACHMENTS} imágenes adjuntas`,
    attachmentCapability: "Esta conexión todavía no admite imágenes.",
    dropToAttach: "Suelta para adjuntar una imagen",
    imageUnavailable: "Las imágenes no están disponibles para esta conexión",
    image: "imagen",
    removeAttachment: "Quitar archivo adjunto",
    clear: "Limpiar",
    plusMenu: "Añadir a este mensaje",
  },
  "fr-FR": {
    placeholder: "Dites au coach ce que vous voulez créer ou où vous êtes bloqué.",
    busyLabel: "Le coach réfléchit",
    accessibilityLabel: "Envoyer un message au coach",
    submitLabel: "Envoyer le message",
    cancelLabel: "Annuler la réponse",
    emptySubmitLabel: "Écrivez un message ou déposez une image pour l’envoyer",
    blockedSubmitLabel: "L’envoi est indisponible pour le moment",
    attachmentCount: (count) => `${count}/${MAX_STAGED_ATTACHMENTS} images jointes`,
    attachmentCapability: "Cette connexion ne prend pas encore en charge les images.",
    dropToAttach: "Déposez pour joindre une image",
    imageUnavailable: "Les images ne sont pas disponibles avec cette connexion",
    image: "image",
    removeAttachment: "Retirer la pièce jointe",
    clear: "Effacer",
    plusMenu: "Ajouter à ce message",
  },
  "de-DE": {
    placeholder: "Sag dem Coach, was du bauen möchtest oder wo du festhängst.",
    busyLabel: "Coach denkt nach",
    accessibilityLabel: "Nachricht an den Coach senden",
    submitLabel: "Nachricht senden",
    cancelLabel: "Antwort abbrechen",
    emptySubmitLabel: "Schreibe eine Nachricht oder ziehe ein Bild hierher, um es zu senden",
    blockedSubmitLabel: "Senden ist derzeit nicht möglich",
    attachmentCount: (count) => `${count} von ${MAX_STAGED_ATTACHMENTS} Bildern angehängt`,
    attachmentCapability: "Diese Verbindung unterstützt noch keine Bildeingaben.",
    dropToAttach: "Loslassen, um ein Bild anzuhängen",
    imageUnavailable: "Bildeingaben sind für diese Verbindung nicht verfügbar",
    image: "Bild",
    removeAttachment: "Anhang entfernen",
    clear: "Leeren",
    plusMenu: "Dieser Nachricht hinzufügen",
  },
  "ja-JP": {
    placeholder: "作りたいものや、行き詰まっている箇所をコーチに伝えてください。",
    busyLabel: "コーチが考えています",
    accessibilityLabel: "コーチにメッセージを送信",
    submitLabel: "メッセージを送信",
    cancelLabel: "返信をキャンセル",
    emptySubmitLabel: "メッセージを入力するか、画像をドロップして送信",
    blockedSubmitLabel: "現在は送信できません",
    attachmentCount: (count) => `${count}/${MAX_STAGED_ATTACHMENTS} 枚の画像を添付済み`,
    attachmentCapability: "この接続ではまだ画像を入力できません。",
    dropToAttach: "画像をドロップして添付",
    imageUnavailable: "この接続では画像を入力できません",
    image: "画像",
    removeAttachment: "添付を削除",
    clear: "消去",
    plusMenu: "このメッセージに追加",
  },
  "ko-KR": {
    placeholder: "만들고 싶은 것 또는 막힌 지점을 코치에게 알려 주세요.",
    busyLabel: "코치가 생각 중입니다",
    accessibilityLabel: "코치에게 메시지 보내기",
    submitLabel: "메시지 보내기",
    cancelLabel: "답변 취소",
    emptySubmitLabel: "메시지를 입력하거나 이미지를 놓아 보내세요",
    blockedSubmitLabel: "현재 보낼 수 없습니다",
    attachmentCount: (count) => `${count}/${MAX_STAGED_ATTACHMENTS}개 이미지 첨부됨`,
    attachmentCapability: "이 연결에서는 아직 이미지를 입력할 수 없습니다.",
    dropToAttach: "이미지를 놓아 첨부",
    imageUnavailable: "이 연결에서는 이미지 입력을 사용할 수 없습니다",
    image: "이미지",
    removeAttachment: "첨부 파일 제거",
    clear: "지우기",
    plusMenu: "이 메시지에 추가",
  },
  "pt-BR": {
    placeholder: "Diga ao coach o que você quer criar ou onde está com dificuldade.",
    busyLabel: "O coach está pensando",
    accessibilityLabel: "Enviar uma mensagem ao coach",
    submitLabel: "Enviar mensagem",
    cancelLabel: "Cancelar resposta",
    emptySubmitLabel: "Escreva uma mensagem ou solte uma imagem para enviar",
    blockedSubmitLabel: "Não é possível enviar agora",
    attachmentCount: (count) => `${count}/${MAX_STAGED_ATTACHMENTS} imagens anexadas`,
    attachmentCapability: "Esta conexão ainda não aceita imagens.",
    dropToAttach: "Solte para anexar uma imagem",
    imageUnavailable: "As imagens não estão disponíveis nesta conexão",
    image: "imagem",
    removeAttachment: "Remover anexo",
    clear: "Limpar",
    plusMenu: "Adicionar a esta mensagem",
  },
};
