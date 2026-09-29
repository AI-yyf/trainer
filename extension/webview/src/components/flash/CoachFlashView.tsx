import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  ArrowRightIcon,
  BooksIcon,
  CheckMarkIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  LightBulbIcon,
  RadioButtonEmptyIcon,
  RadioButtonIcon,
  SquareIcon,
  TrophyIcon,
  WarningIcon,
  XMarkIcon,
} from "../icons";
import { MessageRichContent } from "../coach/MessageRichContent";
import { CollapseSection } from "../common/CollapseSection";
import { resolveCopy } from "../../lib/i18n/copy";
import type { TrainingCardStatus } from "../../../../../shared/src/trainingCardRouting";
import type {
  ComposerLanguage,
  DependencyMastery,
  FlashcardAttempt,
  FlashcardDeck,
} from "../../lib/types";

type FlashcardAnswerMode = "text" | "single_choice" | "multiple_choice" | "fill_blank" | "sorting" | "true_false";
type FlashStudyPhase = "learn" | "check" | "review";

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export interface FlashPracticeBridge {
  cardId: string;
  cardTitle: string;
  focusArea: string;
  prompt: string;
}

export interface CoachFlashViewProps {
  language: ComposerLanguage;
  deck?: FlashcardDeck;
  deckError?: boolean;
  dependencyMastery: DependencyMastery[];
  recentAttempts: FlashcardAttempt[];
  busy?: boolean;
  practiceBridge?: FlashPracticeBridge;
  cardStatus?: TrainingCardStatus;
  cardStatusBusy?: boolean;
  onCardStatusTransition?: (cardId: string, newStatus: TrainingCardStatus, reason?: string) => void;
  onRefreshDeck: () => void;
  onSubmitAnswer: (payload: {
    cardId: string;
    learnerAnswer?: string;
    selectedOptionIndex?: number;
    selectedOptionIndices?: number[];
    fillBlankAnswers?: Record<number, string>;
    sortOrder?: number[];
  }) => void;
  onOpenCoach: () => void;
  onOpenPractice?: (bridge: FlashPracticeBridge) => void;
  onCreateFlashcard?: (payload: {
    question: string;
    answerMode: FlashcardAnswerMode;
    options?: string[];
    expectedAnswer?: string;
    correctOptionIndex?: number;
    correctOptionIndices?: number[];
    correctSortOrder?: number[];
    fillBlankAnswers?: Record<number, string>;
    hintLadder?: string[];
    context?: string;
  }) => void;
  compact?: boolean;
  cardOnly?: boolean;
  sourceChain?: string[];
  whyNow?: string;
  targetSkill?: string;
  scenarioPackLabel?: string;
  feedbackTargets?: string[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * §十五: flash copy in eight languages — the zh-CN string is the record key,
 * so zh-CN output stays byte-identical and there is no zh/en binary left.
 */
type FlashTextLanguages = Exclude<ComposerLanguage, "zh-CN">;

const FLASH_TEXT: Record<string, Record<FlashTextLanguages, string>> = {
  "从几个选项里选出最稳的一项。": {
    "en-US": "Pick the most solid option from the set.",
    "es-ES": "Elige la opción más sólida del conjunto.",
    "fr-FR": "Choisis l'option la plus solide de la série.",
    "de-DE": "Wähle die solideste Option aus der Auswahl.",
    "ja-JP": "選択肢の中から最も確かなものを一つ選びます。",
    "ko-KR": "몇 개의 선택지 중 가장 확실한 하나를 고르세요.",
    "pt-BR": "Escolha a opção mais sólida do conjunto.",
  },
  "把所有成立的选项一起找出来。": {
    "en-US": "Find every option that still holds.",
    "es-ES": "Encuentra todas las opciones que sigan siendo válidas.",
    "fr-FR": "Trouvez toutes les options qui restent valables.",
    "de-DE": "Finde alle Optionen, die weiterhin zutreffen.",
    "ja-JP": "成り立つ選択肢をすべて見つけます。",
    "ko-KR": "여전히 성립하는 선택지를 모두 찾아내세요.",
    "pt-BR": "Encontre todas as opções que continuam válidas.",
  },
  "补上缺失的 keyword 或 concept。": {
    "en-US": "Fill in the missing keyword or concept.",
    "es-ES": "Completa la palabra clave o el concepto que falta.",
    "fr-FR": "Complète le mot-clé ou le concept manquant.",
    "de-DE": "Ergänze das fehlende Keyword oder Konzept.",
    "ja-JP": "欠けている keyword か concept を補います。",
    "ko-KR": "빠진 keyword나 concept를 채우세요.",
    "pt-BR": "Preencha a palavra-chave ou o conceito que falta.",
  },
  "按正确顺序排好这些步骤。": {
    "en-US": "Put the steps back into the right order.",
    "es-ES": "Ordena estos pasos en la secuencia correcta.",
    "fr-FR": "Remets ces étapes dans le bon ordre.",
    "de-DE": "Bringe diese Schritte in die richtige Reihenfolge.",
    "ja-JP": "これらのステップを正しい順番に並べます。",
    "ko-KR": "이 단계들을 올바른 순서로 나열하세요.",
    "pt-BR": "Coloque estes passos na ordem correta.",
  },
  "先判断对错，再确认理由。": {
    "en-US": "Decide whether it is true, then confirm why.",
    "es-ES": "Decide si es verdadero y luego confirma por qué.",
    "fr-FR": "Décidez si c'est vrai, puis confirmez pourquoi.",
    "de-DE": "Entscheide, ob es stimmt, und bestätige dann warum.",
    "ja-JP": "まず正誤を判断し、その理由を確認します。",
    "ko-KR": "먼저 참/거짓을 판단하고 이유를 확인하세요.",
    "pt-BR": "Decida se é verdadeiro e depois confirme o porquê.",
  },
  "先用你自己的话给出简短答案。": {
    "en-US": "Answer in your own words first.",
    "es-ES": "Responde primero con tus propias palabras.",
    "fr-FR": "Répondez d'abord avec vos propres mots.",
    "de-DE": "Antworte zuerst in deinen eigenen Worten.",
    "ja-JP": "まず自分の言葉で短く答えます。",
    "ko-KR": "먼저 자신의 말로 간단히 답하세요.",
    "pt-BR": "Responda primeiro com suas próprias palavras.",
  },
  "掌握": {
    "en-US": "Know well",
    "es-ES": "Lo domino",
    "fr-FR": "Je maîtrise",
    "de-DE": "Sicher gewusst",
    "ja-JP": "把握できた",
    "ko-KR": "알고 있음",
    "pt-BR": "Sei bem",
  },
  "模糊": {
    "en-US": "Fuzzy",
    "es-ES": "Confuso",
    "fr-FR": "Flou",
    "de-DE": "Unklar",
    "ja-JP": "あやふや",
    "ko-KR": "애매함",
    "pt-BR": "Confuso",
  },
  "不会": {
    "en-US": "Don\u2019t know",
    "es-ES": "No lo sé",
    "fr-FR": "Je ne sais pas",
    "de-DE": "Nicht gewusst",
    "ja-JP": "わからない",
    "ko-KR": "모름",
    "pt-BR": "Não sei",
  },
  "创建闪记卡": {
    "en-US": "Create flashcard",
    "es-ES": "Crear tarjeta flash",
    "fr-FR": "Créer une flashcard",
    "de-DE": "Flashcard erstellen",
    "ja-JP": "フラッシュカードを作成",
    "ko-KR": "플래시카드 만들기",
    "pt-BR": "Criar flashcard",
  },
  "问题": {
    "en-US": "Question",
    "es-ES": "Pregunta",
    "fr-FR": "Question",
    "de-DE": "Frage",
    "ja-JP": "問題",
    "ko-KR": "질문",
    "pt-BR": "Pergunta",
  },
  "输入问题... 填空用 {{1}} 占位": {
    "en-US": "Enter question... Use {{1}} for blanks",
    "es-ES": "Escribe la pregunta... Usa {{1}} para los huecos",
    "fr-FR": "Saisissez la question... Utilisez {{1}} pour les trous",
    "de-DE": "Frage eingeben ... Verwende {{1}} für Lücken",
    "ja-JP": "問題を入力... 穴埋めには {{1}} を使います",
    "ko-KR": "질문을 입력하세요... 빈칸은 {{1}}로 표시",
    "pt-BR": "Digite a pergunta... Use {{1}} para as lacunas",
  },
  "答题模式": {
    "en-US": "Answer mode",
    "es-ES": "Modo de respuesta",
    "fr-FR": "Mode de réponse",
    "de-DE": "Antwortmodus",
    "ja-JP": "解答モード",
    "ko-KR": "답변 방식",
    "pt-BR": "Modo de resposta",
  },
  "文本回答": {
    "en-US": "Text answer",
    "es-ES": "Respuesta de texto",
    "fr-FR": "Réponse texte",
    "de-DE": "Textantwort",
    "ja-JP": "テキスト回答",
    "ko-KR": "텍스트 답변",
    "pt-BR": "Resposta em texto",
  },
  "单选题": {
    "en-US": "Single choice",
    "es-ES": "Opción única",
    "fr-FR": "Choix unique",
    "de-DE": "Einfachauswahl",
    "ja-JP": "単一選択",
    "ko-KR": "단일 선택",
    "pt-BR": "Escolha única",
  },
  "多选题": {
    "en-US": "Multiple choice",
    "es-ES": "Opción múltiple",
    "fr-FR": "Choix multiple",
    "de-DE": "Mehrfachauswahl",
    "ja-JP": "複数選択",
    "ko-KR": "복수 선택",
    "pt-BR": "Escolha múltipla",
  },
  "排序题": {
    "en-US": "Sorting",
    "es-ES": "Ordenar",
    "fr-FR": "Tri",
    "de-DE": "Sortieren",
    "ja-JP": "並べ替え",
    "ko-KR": "순서 정렬",
    "pt-BR": "Ordenação",
  },
  "填空题": {
    "en-US": "Fill in blank",
    "es-ES": "Completar huecos",
    "fr-FR": "Texte à trous",
    "de-DE": "Lückentext",
    "ja-JP": "穴埋め",
    "ko-KR": "빈칸 채우기",
    "pt-BR": "Preencher lacuna",
  },
  "选项": {
    "en-US": "Options",
    "es-ES": "Opciones",
    "fr-FR": "Options",
    "de-DE": "Optionen",
    "ja-JP": "選択肢",
    "ko-KR": "선택지",
    "pt-BR": "Opções",
  },
  "选项 {index}": {
    "en-US": "Option {index}",
    "es-ES": "Opción {index}",
    "fr-FR": "Option {index}",
    "de-DE": "Option {index}",
    "ja-JP": "選択肢 {index}",
    "ko-KR": "선택지 {index}",
    "pt-BR": "Opção {index}",
  },
  "+ 添加选项": {
    "en-US": "+ Add option",
    "es-ES": "+ Añadir opción",
    "fr-FR": "+ Ajouter une option",
    "de-DE": "+ Option hinzufügen",
    "ja-JP": "+ 選択肢を追加",
    "ko-KR": "+ 선택지 추가",
    "pt-BR": "+ Adicionar opção",
  },
  "正确答案": {
    "en-US": "Correct answer",
    "es-ES": "Respuesta correcta",
    "fr-FR": "Bonne réponse",
    "de-DE": "Richtige Antwort",
    "ja-JP": "正解",
    "ko-KR": "정답",
    "pt-BR": "Resposta correta",
  },
  "选择正确答案": {
    "en-US": "Select correct answer",
    "es-ES": "Selecciona la respuesta correcta",
    "fr-FR": "Sélectionnez la bonne réponse",
    "de-DE": "Richtige Antwort auswählen",
    "ja-JP": "正解を選択",
    "ko-KR": "정답을 선택하세요",
    "pt-BR": "Selecione a resposta correta",
  },
  "参考答案": {
    "en-US": "Expected answer",
    "es-ES": "Respuesta de referencia",
    "fr-FR": "Réponse attendue",
    "de-DE": "Erwartete Antwort",
    "ja-JP": "参考解答",
    "ko-KR": "참고 답안",
    "pt-BR": "Resposta esperada",
  },
  "输入参考答案...": {
    "en-US": "Enter expected answer...",
    "es-ES": "Escribe la respuesta de referencia...",
    "fr-FR": "Saisissez la réponse attendue...",
    "de-DE": "Erwartete Antwort eingeben ...",
    "ja-JP": "参考解答を入力...",
    "ko-KR": "참고 답안을 입력하세요...",
    "pt-BR": "Digite a resposta esperada...",
  },
  "在问题中使用 {{1}}、{{2}} 等标记填空位置，然后在下方输入每个空的正确答案。": {
    "en-US": "Use {{1}}, {{2}} etc. in question to mark blanks, then enter correct answers below.",
    "es-ES": "Usa {{1}}, {{2}} etc. en la pregunta para marcar los huecos y escribe abajo la respuesta correcta de cada uno.",
    "fr-FR": "Utilisez {{1}}, {{2}} etc. dans la question pour marquer les trous, puis saisissez ci-dessous la bonne réponse de chacun.",
    "de-DE": "Verwende {{1}}, {{2}} usw. in der Frage, um Lücken zu markieren, und gib unten die richtige Antwort für jede ein.",
    "ja-JP": "問題内に {{1}}、{{2}} などの印で空欄位置を示し、その下に各空欄の正解を入力します。",
    "ko-KR": "질문에 {{1}}, {{2}} 등의 표시로 빈칸 위치를 정하고, 아래에 각 빈칸의 정답을 입력하세요.",
    "pt-BR": "Use {{1}}, {{2}} etc. na pergunta para marcar as lacunas e digite abaixo a resposta correta de cada uma.",
  },
  "尚未在问题中检测到填空标记": {
    "en-US": "No blank markers detected in question",
    "es-ES": "No se detectaron marcas de huecos en la pregunta",
    "fr-FR": "Aucune marque de trou détectée dans la question",
    "de-DE": "Keine Lücken-Markierungen in der Frage erkannt",
    "ja-JP": "問題に穴埋め印が検出されていません",
    "ko-KR": "질문에서 빈칸 표시가 감지되지 않았습니다",
    "pt-BR": "Nenhuma marca de lacuna detectada na pergunta",
  },
  "空 {count}": {
    "en-US": "Blank {count}",
    "es-ES": "Hueco {count}",
    "fr-FR": "Trou {count}",
    "de-DE": "Lücke {count}",
    "ja-JP": "空欄 {count}",
    "ko-KR": "빈칸 {count}",
    "pt-BR": "Lacuna {count}",
  },
  "填空 {count}": {
    "en-US": "Blank {count}",
    "es-ES": "Hueco {count}",
    "fr-FR": "Trou {count}",
    "de-DE": "Lücke {count}",
    "ja-JP": "穴埋め {count}",
    "ko-KR": "빈칸 {count}",
    "pt-BR": "Lacuna {count}",
  },
  "提示（可选）": {
    "en-US": "Hints (optional)",
    "es-ES": "Pistas (opcional)",
    "fr-FR": "Indices (facultatif)",
    "de-DE": "Hinweise (optional)",
    "ja-JP": "ヒント（任意）",
    "ko-KR": "힌트(선택)",
    "pt-BR": "Dicas (opcional)",
  },
  "提示 {index}": {
    "en-US": "Hint {index}",
    "es-ES": "Pista {index}",
    "fr-FR": "Indice {index}",
    "de-DE": "Hinweis {index}",
    "ja-JP": "ヒント {index}",
    "ko-KR": "힌트 {index}",
    "pt-BR": "Dica {index}",
  },
  "+ 添加提示": {
    "en-US": "+ Add hint",
    "es-ES": "+ Añadir pista",
    "fr-FR": "+ Ajouter un indice",
    "de-DE": "+ Hinweis hinzufügen",
    "ja-JP": "+ ヒントを追加",
    "ko-KR": "+ 힌트 추가",
    "pt-BR": "+ Adicionar dica",
  },
  "背景上下文（可选）": {
    "en-US": "Context (optional)",
    "es-ES": "Contexto (opcional)",
    "fr-FR": "Contexte (facultatif)",
    "de-DE": "Kontext (optional)",
    "ja-JP": "背景コンテキスト（任意）",
    "ko-KR": "배경 맥락(선택)",
    "pt-BR": "Contexto (opcional)",
  },
  "输入背景上下文...": {
    "en-US": "Enter context...",
    "es-ES": "Escribe el contexto...",
    "fr-FR": "Saisissez le contexte...",
    "de-DE": "Kontext eingeben ...",
    "ja-JP": "背景コンテキストを入力...",
    "ko-KR": "배경 맥락을 입력하세요...",
    "pt-BR": "Digite o contexto...",
  },
  "取消": {
    "en-US": "Cancel",
    "es-ES": "Cancelar",
    "fr-FR": "Annuler",
    "de-DE": "Abbrechen",
    "ja-JP": "キャンセル",
    "ko-KR": "취소",
    "pt-BR": "Cancelar",
  },
  "闪卡复习": {
    "en-US": "Flash review",
    "es-ES": "Repaso flash",
    "fr-FR": "Révision flash",
    "de-DE": "Flash-Wiederholung",
    "ja-JP": "フラッシュ復習",
    "ko-KR": "플래시 복습",
    "pt-BR": "Revisão flash",
  },
  "你的闪记卡库还是空的": {
    "en-US": "Your flashcard deck is empty",
    "es-ES": "Tu mazo de flashcards está vacío",
    "fr-FR": "Votre paquet de flashcards est vide",
    "de-DE": "Dein Flashcard-Deck ist leer",
    "ja-JP": "フラッシュカードデッキは空です",
    "ko-KR": "플래시카드 덱이 비어 있습니다",
    "pt-BR": "Seu baralho de flashcards está vazio",
  },
  "暂无闪卡。完成实战卡，或从对话生成闪记。": {
    "en-US": "No flashcards yet. Finish a practice card or generate flashcards from chat.",
    "es-ES": "Aún no hay flashcards. Termina una tarjeta de práctica o genéralas desde el chat.",
    "fr-FR": "Pas encore de flashcards. Terminez une carte de pratique ou générez-en depuis le chat.",
    "de-DE": "Noch keine Flashcards. Schließe eine Übungskarte ab oder erzeuge welche aus dem Chat.",
    "ja-JP": "フラッシュカードはまだありません。実戦カードを終えるか、チャットから生成してください。",
    "ko-KR": "아직 플래시카드가 없습니다. 실전 카드를 끝내거나 대화에서 생성하세요.",
    "pt-BR": "Ainda não há flashcards. Conclua um cartão de prática ou gere-os a partir da conversa.",
  },
  "去找教练聊聊": {
    "en-US": "Chat with coach",
    "es-ES": "Hablar con el coach",
    "fr-FR": "Discuter avec le coach",
    "de-DE": "Mit dem Coach sprechen",
    "ja-JP": "コーチに相談",
    "ko-KR": "코치와 대화",
    "pt-BR": "Conversar com o coach",
  },
  "手动创建闪记卡": {
    "en-US": "Create flashcard manually",
    "es-ES": "Crear flashcard manualmente",
    "fr-FR": "Créer une flashcard manuellement",
    "de-DE": "Flashcard manuell erstellen",
    "ja-JP": "フラッシュカードを手動作成",
    "ko-KR": "플래시카드 직접 만들기",
    "pt-BR": "Criar flashcard manualmente",
  },
  "刷新卡组": {
    "en-US": "Refresh deck",
    "es-ES": "Actualizar mazo",
    "fr-FR": "Actualiser le paquet",
    "de-DE": "Deck aktualisieren",
    "ja-JP": "デッキを更新",
    "ko-KR": "덱 새로고침",
    "pt-BR": "Atualizar baralho",
  },
  "加载中": {
    "en-US": "Loading",
    "es-ES": "Cargando",
    "fr-FR": "Chargement",
    "de-DE": "Wird geladen",
    "ja-JP": "読み込み中",
    "ko-KR": "불러오는 중",
    "pt-BR": "Carregando",
  },
  "提交中\u2026": {
    "en-US": "Submitting\u2026",
    "es-ES": "Enviando…",
    "fr-FR": "Envoi…",
    "de-DE": "Wird gesendet …",
    "ja-JP": "送信中…",
    "ko-KR": "제출 중…",
    "pt-BR": "Enviando…",
  },
  "当前闪卡": {
    "en-US": "Current flashcard",
    "es-ES": "Flashcard actual",
    "fr-FR": "Flashcard actuelle",
    "de-DE": "Aktuelle Flashcard",
    "ja-JP": "現在のフラッシュカード",
    "ko-KR": "현재 플래시카드",
    "pt-BR": "Flashcard atual",
  },
  "加载闪记卡失败": {
    "en-US": "Failed to load flashcards",
    "es-ES": "No se pudieron cargar las flashcards",
    "fr-FR": "Échec du chargement des flashcards",
    "de-DE": "Flashcards konnten nicht geladen werden",
    "ja-JP": "フラッシュカードの読み込みに失敗しました",
    "ko-KR": "플래시카드를 불러오지 못했습니다",
    "pt-BR": "Falha ao carregar os flashcards",
  },
  "请检查连接后重试。": {
    "en-US": "Please check your connection and try again.",
    "es-ES": "Comprueba la conexión e inténtalo de nuevo.",
    "fr-FR": "Vérifiez votre connexion puis réessayez.",
    "de-DE": "Bitte Verbindung prüfen und erneut versuchen.",
    "ja-JP": "接続を確認してから再試行してください。",
    "ko-KR": "연결을 확인한 후 다시 시도하세요.",
    "pt-BR": "Verifique sua conexão e tente novamente.",
  },
  "开始你的闪记训练": {
    "en-US": "Start your flash training",
    "es-ES": "Comienza tu entrenamiento flash",
    "fr-FR": "Commencez votre entraînement flash",
    "de-DE": "Starten Sie Ihr Flash-Training",
    "ja-JP": "フラッシュトレーニングを始めましょう",
    "ko-KR": "플래시 트레이닝을 시작하세요",
    "pt-BR": "Comece seu treinamento flash",
  },
  "从对话中学习新知识，或创建自定义闪记卡来强化记忆。": {
    "en-US": "Learn from conversations or create custom flashcards to strengthen your memory.",
    "es-ES": "Aprende de las conversaciones o crea flashcards personalizadas para reforzar tu memoria.",
    "fr-FR": "Apprenez des conversations ou créez des flashcards personnalisées pour renforcer votre mémoire.",
    "de-DE": "Lernen Sie aus Gesprächen oder erstellen Sie eigene Flashcards, um Ihr Gedächtnis zu stärken.",
    "ja-JP": "会話から学ぶか、カスタム フラッシュカードを作って記憶を強化しましょう。",
    "ko-KR": "대화에서 배우거나 직접 만든 플래시카드로 기억을 강화하세요.",
    "pt-BR": "Aprenda com conversas ou crie flashcards personalizados para fortalecer sua memória.",
  },
  "开始学习": {
    "en-US": "Start learning",
    "es-ES": "Empezar a aprender",
    "fr-FR": "Commencer à apprendre",
    "de-DE": "Lernen beginnen",
    "ja-JP": "学習を始める",
    "ko-KR": "학습 시작",
    "pt-BR": "Começar a aprender",
  },
  "来源": {
    "en-US": "Sources",
    "es-ES": "Fuentes",
    "fr-FR": "Sources",
    "de-DE": "Quellen",
    "ja-JP": "ソース",
    "ko-KR": "출처",
    "pt-BR": "Fontes",
  },
  "→ 对话生成": {
    "en-US": "→ From coach chat",
    "es-ES": "→ Desde el chat del coach",
    "fr-FR": "→ Depuis le chat du coach",
    "de-DE": "→ Aus dem Coach-Chat",
    "ja-JP": "→ コーチチャットから",
    "ko-KR": "→ 코치 채팅에서 생성",
    "pt-BR": "→ Da conversa com o coach",
  },
  "→ 训练后生成": {
    "en-US": "→ From training",
    "es-ES": "→ Desde el entrenamiento",
    "fr-FR": "→ Depuis l'entraînement",
    "de-DE": "→ Aus dem Training",
    "ja-JP": "→ 訓練から生成",
    "ko-KR": "→ 훈련에서 생성",
    "pt-BR": "→ Do treinamento",
  },
  "→ 资料抽取": {
    "en-US": "→ From resources",
    "es-ES": "→ Desde los recursos",
    "fr-FR": "→ Depuis les ressources",
    "de-DE": "→ Aus den Ressourcen",
    "ja-JP": "→ 資料から抽出",
    "ko-KR": "→ 자료에서 추출",
    "pt-BR": "→ Dos recursos",
  },
  "卡组已清空": {
    "en-US": "Deck cleared",
    "es-ES": "Mazo completado",
    "fr-FR": "Paquet terminé",
    "de-DE": "Deck abgearbeitet",
    "ja-JP": "デッキを完遂",
    "ko-KR": "덱 완료",
    "pt-BR": "Baralho concluído",
  },
  "本轮完成": {
    "en-US": "Round complete",
    "es-ES": "Ronda completada",
    "fr-FR": "Manche terminée",
    "de-DE": "Runde abgeschlossen",
    "ja-JP": "ラウンド完了",
    "ko-KR": "라운드 완료",
    "pt-BR": "Rodada concluída",
  },
  "本次复习 {count} 张 · 正确率 {percent}%": {
    "en-US": "{count} cards reviewed · {percent}% accuracy",
    "es-ES": "{count} flashcards repasadas · {percent}% de acierto",
    "fr-FR": "{count} flashcards révisées · {percent}% de réussite",
    "de-DE": "{count} Flashcards wiederholt · {percent}% Trefferquote",
    "ja-JP": "今回 {count} 枚を復習 · 正答率 {percent}%",
    "ko-KR": "이번에 {count}장 복습 · 정확도 {percent}%",
    "pt-BR": "{count} flashcards revisadas · {percent}% de acerto",
  },
  "连续 {count} 天": {
    "en-US": "{count} day streak",
    "es-ES": "{count} días seguidos",
    "fr-FR": "{count} jours d'affilée",
    "de-DE": "{count} Tage in Folge",
    "ja-JP": "{count} 日連続",
    "ko-KR": "{count}일 연속",
    "pt-BR": "{count} dias seguidos",
  },
  "再来一轮": {
    "en-US": "Practice again",
    "es-ES": "Practicar de nuevo",
    "fr-FR": "S'entraîner à nouveau",
    "de-DE": "Nochmal üben",
    "ja-JP": "もう一周",
    "ko-KR": "다시 연습",
    "pt-BR": "Praticar de novo",
  },
  "去找教练": {
    "en-US": "Chat with coach",
    "es-ES": "Hablar con el coach",
    "fr-FR": "Discuter avec le coach",
    "de-DE": "Zum Coach gehen",
    "ja-JP": "コーチに相談",
    "ko-KR": "코치에게 가기",
    "pt-BR": "Falar com o coach",
  },
  "闪记卡": {
    "en-US": "Flash",
    "es-ES": "Flash",
    "fr-FR": "Flash",
    "de-DE": "Flash",
    "ja-JP": "フラッシュ",
    "ko-KR": "플래시",
    "pt-BR": "Flash",
  },
  "快速回忆 · 即时反馈": {
    "en-US": "Recall · Instant feedback",
    "es-ES": "Recuerdo · Feedback instantáneo",
    "fr-FR": "Rappel · Feedback immédiat",
    "de-DE": "Abruf · Sofortiges Feedback",
    "ja-JP": "思い出し · 即時フィードバック",
    "ko-KR": "회상 · 즉시 피드백",
    "pt-BR": "Memorização · Feedback instantâneo",
  },
  "场景包 · {label}": {
    "en-US": "Scenario pack · {label}",
    "es-ES": "Paquete de escenarios · {label}",
    "fr-FR": "Pack de scénarios · {label}",
    "de-DE": "Szenariopaket · {label}",
    "ja-JP": "シナリオパック · {label}",
    "ko-KR": "시나리오 팩 · {label}",
    "pt-BR": "Pacote de cenários · {label}",
  },
  "来自训练主线和薄弱点": {
    "en-US": "From training & weak spots",
    "es-ES": "Del entrenamiento y puntos débiles",
    "fr-FR": "De l'entraînement et des points faibles",
    "de-DE": "Aus Training und Schwachstellen",
    "ja-JP": "訓練の流れと弱点から",
    "ko-KR": "훈련 흐름과 취약점에서",
    "pt-BR": "Do treinamento e pontos fracos",
  },
  "创建新闪记卡": {
    "en-US": "Create new flashcard",
    "es-ES": "Crear nueva flashcard",
    "fr-FR": "Créer une nouvelle flashcard",
    "de-DE": "Neue Flashcard erstellen",
    "ja-JP": "新しいフラッシュカードを作成",
    "ko-KR": "새 플래시카드 만들기",
    "pt-BR": "Criar novo flashcard",
  },
  "+ 新建": {
    "en-US": "+ New",
    "es-ES": "+ Nuevo",
    "fr-FR": "+ Nouveau",
    "de-DE": "+ Neu",
    "ja-JP": "+ 新規",
    "ko-KR": "+ 새로 만들기",
    "pt-BR": "+ Novo",
  },
  "待复习 {count}": {
    "en-US": "Due: {count}",
    "es-ES": "Pendientes: {count}",
    "fr-FR": "À revoir : {count}",
    "de-DE": "Fällig: {count}",
    "ja-JP": "復習待ち {count}",
    "ko-KR": "복습 대기 {count}",
    "pt-BR": "Pendentes: {count}",
  },
  "剩余 {count}": {
    "en-US": "{count} left",
    "es-ES": "{count} restantes",
    "fr-FR": "{count} restantes",
    "de-DE": "{count} übrig",
    "ja-JP": "残り {count}",
    "ko-KR": "{count} 남음",
    "pt-BR": "{count} restantes",
  },
  "先学习": {
    "en-US": "Learn first",
    "es-ES": "Primero estudiar",
    "fr-FR": "Apprendre d'abord",
    "de-DE": "Zuerst lernen",
    "ja-JP": "まず学習",
    "ko-KR": "먼저 학습",
    "pt-BR": "Primeiro estudar",
  },
  "先看线索：{cue}": {
    "en-US": "Study cue: {cue}",
    "es-ES": "Pista de estudio: {cue}",
    "fr-FR": "Indice d'étude : {cue}",
    "de-DE": "Lernhinweis: {cue}",
    "ja-JP": "手がかりを先に: {cue}",
    "ko-KR": "단서 먼저 보기: {cue}",
    "pt-BR": "Dica de estudo: {cue}",
  },
  "开始检查后：{summary}": {
    "en-US": "Once you start the check: {summary}",
    "es-ES": "Al iniciar la comprobación: {summary}",
    "fr-FR": "Une fois la vérification lancée : {summary}",
    "de-DE": "Nach Start der Prüfung: {summary}",
    "ja-JP": "チェック開始後: {summary}",
    "ko-KR": "검사 시작 후: {summary}",
    "pt-BR": "Ao iniciar a verificação: {summary}",
  },
  "常见误区：{mistake}": {
    "en-US": "Common miss: {mistake}",
    "es-ES": "Error común: {mistake}",
    "fr-FR": "Erreur fréquente : {mistake}",
    "de-DE": "Häufiger Fehler: {mistake}",
    "ja-JP": "よくある誤解: {mistake}",
    "ko-KR": "흔한 실수: {mistake}",
    "pt-BR": "Erro comum: {mistake}",
  },
  "带回 Coach：{cue}": {
    "en-US": "Bring back to Coach: {cue}",
    "es-ES": "De vuelta al coach: {cue}",
    "fr-FR": "À rapporter au coach : {cue}",
    "de-DE": "Zum Coach zurückbringen: {cue}",
    "ja-JP": "Coach に持ち帰る: {cue}",
    "ko-KR": "Coach에게 가져가기: {cue}",
    "pt-BR": "De volta ao coach: {cue}",
  },
  "先把 {skill} 对齐，再开始检查。": {
    "en-US": "Review {skill} first, then start the check.",
    "es-ES": "Repasa primero {skill} y luego inicia la comprobación.",
    "fr-FR": "Revoyez d'abord {skill}, puis lancez la vérification.",
    "de-DE": "Wiederholen Sie zuerst {skill} und starten Sie dann die Prüfung.",
    "ja-JP": "まず {skill} を整理してからチェックを始めます。",
    "ko-KR": "먼저 {skill}을(를) 정리한 뒤 검사를 시작하세요.",
    "pt-BR": "Revise primeiro {skill} e depois inicie a verificação.",
  },
  "先把 {pack} 这组场景读顺，再开始检查。": {
    "en-US": "Read through the {pack} scenario family first, then start the check.",
    "es-ES": "Repasa primero la familia de escenarios {pack} y luego inicia la comprobación.",
    "fr-FR": "Parcourez d'abord la famille de scénarios {pack}, puis lancez la vérification.",
    "de-DE": "Gehen Sie zuerst die Szenariofamilie {pack} durch und starten Sie dann die Prüfung.",
    "ja-JP": "まず {pack} のシナリオ群を一通り読んでからチェックを始めます。",
    "ko-KR": "먼저 {pack} 시나리오군을 훑고 난 뒤 검사를 시작하세요.",
    "pt-BR": "Percorra primeiro a família de cenários {pack} e depois inicie a verificação.",
  },
  "先把这张卡想让你锁住的判断点对齐，再开始检查。": {
    "en-US": "Get the judgment this card is trying to lock in clear before you start the check.",
    "es-ES": "Ten claro el juicio que esta tarjeta quiere fijar antes de iniciar la comprobación.",
    "fr-FR": "Ayez claire en tête le jugement que cette carte cherche à ancrer avant de lancer la vérification.",
    "de-DE": "Machen Sie sich das Urteil klar, das diese Karte festigen will, bevor Sie die Prüfung starten.",
    "ja-JP": "チェックを始める前に、このカードが固定しようとする判断をはっきりさせておきます。",
    "ko-KR": "검사를 시작하기 전에 이 카드가 고정하려는 판단을 분명히 하세요.",
    "pt-BR": "Entenda o julgamento que este cartão quer fixar antes de iniciar a verificação.",
  },
  "先把下一步想清楚，再进入检查。这样更像真实工作流，不像突然考试。": {
    "en-US": "Get the next step clear before you enter the check. It should feel like real work, not a surprise exam.",
    "es-ES": "Ten claro el siguiente paso antes de entrar en la comprobación. Debe sentirse como trabajo real, no como un examen sorpresa.",
    "fr-FR": "Clarifiez la prochaine étape avant d'entrer dans la vérification. Cela doit ressembler à un vrai travail, pas à un examen surprise.",
    "de-DE": "Machen Sie sich den nächsten Schritt klar, bevor Sie in die Prüfung gehen. Es soll sich wie echte Arbeit anfühlen, nicht wie eine Überraschungsprüfung.",
    "ja-JP": "次の一手をはっきりさせてからチェックに入ります。突然の試験ではなく、実際の作業のように進めます。",
    "ko-KR": "검사에 들어가기 전에 다음 단계를 분명히 하세요. 갑작스러운 시험이 아니라 실제 작업처럼 진행되어야 합니다.",
    "pt-BR": "Tenha claro o próximo passo antes de entrar na verificação. Deve parecer trabalho real, não uma prova surpresa.",
  },
  "先用自己的话回忆：这张卡在帮你避免什么错误，或者在帮你确认哪个关键动作。": {
    "en-US": "First say to yourself which mistake this card is helping you avoid, or which move it is helping you confirm.",
    "es-ES": "Recuerda primero para ti: qué error te ayuda a evitar esta tarjeta o qué movimiento clave te ayuda a confirmar.",
    "fr-FR": "Rappelez-vous d'abord : quelle erreur cette carte vous aide à éviter, ou quelle action clé elle vous aide à confirmer.",
    "de-DE": "Erinnern Sie zuerst für sich: Welchen Fehler hilft diese Karte zu vermeiden, welche wichtige Handlung zu bestätigen?",
    "ja-JP": "まず自分の言葉で思い出します。このカードはどのミスを避けさせ、どの重要な行動を確認させようとしているか。",
    "ko-KR": "먼저 자신의 말로 떠올려 보세요. 이 카드는 어떤 실수를 피하게 하고, 어떤 핵심 행동을 확인하게 도와줍니까?",
    "pt-BR": "Primeiro lembre para si mesmo: qual erro este cartão ajuda a evitar ou qual movimento chave ajuda a confirmar.",
  },
  "做完后带着你的答案和一个还不确定的点回到 Coach。": {
    "en-US": "After the check, bring back your answer and one thing you are still unsure about.",
    "es-ES": "Tras la comprobación, vuelve con tu respuesta y un punto que aún te genere dudas.",
    "fr-FR": "Après la vérification, revenez avec votre réponse et un point qui reste incertain.",
    "de-DE": "Kehren Sie nach der Prüfung mit Ihrer Antwort und einem unsicheren Punkt zum Coach zurück.",
    "ja-JP": "チェックの後、自分の答えとまだ確信できない点を一つ持って Coach に戻ります。",
    "ko-KR": "검사 후에는 답과 아직 확신하지 못한 점 하나를 가지고 Coach에게 돌아갑니다.",
    "pt-BR": "Depois da verificação, volte com sua resposta e um ponto sobre o qual ainda tenha dúvidas.",
  },
  "更多上下文": {
    "en-US": "More context",
    "es-ES": "Más contexto",
    "fr-FR": "Plus de contexte",
    "de-DE": "Mehr Kontext",
    "ja-JP": "詳細なコンテキスト",
    "ko-KR": "더 많은 맥락",
    "pt-BR": "Mais contexto",
  },
  "开始检查": {
    "en-US": "Start check",
    "es-ES": "Iniciar comprobación",
    "fr-FR": "Lancer la vérification",
    "de-DE": "Prüfung starten",
    "ja-JP": "チェックを開始",
    "ko-KR": "검사 시작",
    "pt-BR": "Iniciar verificação",
  },
  "问 Coach": {
    "en-US": "Ask coach",
    "es-ES": "Preguntar al coach",
    "fr-FR": "Demander au coach",
    "de-DE": "Coach fragen",
    "ja-JP": "Coach に聞く",
    "ko-KR": "Coach에게 묻기",
    "pt-BR": "Perguntar ao coach",
  },
  "更多细节": {
    "en-US": "Details",
    "es-ES": "Detalles",
    "fr-FR": "Détails",
    "de-DE": "Details",
    "ja-JP": "詳細",
    "ko-KR": "상세 정보",
    "pt-BR": "Detalhes",
  },
  "来源: {chain}": {
    "en-US": "Source: {chain}",
    "es-ES": "Fuente: {chain}",
    "fr-FR": "Source : {chain}",
    "de-DE": "Quelle: {chain}",
    "ja-JP": "ソース: {chain}",
    "ko-KR": "출처: {chain}",
    "pt-BR": "Fonte: {chain}",
  },
  "已完成检查": {
    "en-US": "Check complete",
    "es-ES": "Comprobación completada",
    "fr-FR": "Vérification terminée",
    "de-DE": "Prüfung abgeschlossen",
    "ja-JP": "チェック完了",
    "ko-KR": "검사 완료",
    "pt-BR": "Verificação concluída",
  },
  "现在检查": {
    "en-US": "Check now",
    "es-ES": "Comprobar ahora",
    "fr-FR": "Vérifier maintenant",
    "de-DE": "Jetzt prüfen",
    "ja-JP": "今すぐチェック",
    "ko-KR": "지금 검사",
    "pt-BR": "Verificar agora",
  },
  "（无问题）": {
    "en-US": "(No question)",
    "es-ES": "(Sin pregunta)",
    "fr-FR": "(Aucune question)",
    "de-DE": "(Keine Frage)",
    "ja-JP": "(問題なし)",
    "ko-KR": "(질문 없음)",
    "pt-BR": "(Sem pergunta)",
  },
  "{count} 个提示可用": {
    "en-US": "{count} hint{s} available",
    "es-ES": "{count} pistas disponibles",
    "fr-FR": "{count} indices disponibles",
    "de-DE": "{count} Hinweise verfügbar",
    "ja-JP": "{count} 件のヒントが利用可能",
    "ko-KR": "힌트 {count}개 사용 가능",
    "pt-BR": "{count} dicas disponíveis",
  },
  "显示下一条提示": {
    "en-US": "Show next hint",
    "es-ES": "Mostrar la siguiente pista",
    "fr-FR": "Afficher l'indice suivant",
    "de-DE": "Nächsten Hinweis anzeigen",
    "ja-JP": "次のヒントを表示",
    "ko-KR": "다음 힌트 표시",
    "pt-BR": "Mostrar a próxima dica",
  },
  "背景上下文": {
    "en-US": "Context",
    "es-ES": "Contexto",
    "fr-FR": "Contexte",
    "de-DE": "Kontext",
    "ja-JP": "背景コンテキスト",
    "ko-KR": "배경 맥락",
    "pt-BR": "Contexto",
  },
  "选择答案": {
    "en-US": "Choose an answer",
    "es-ES": "Elige una respuesta",
    "fr-FR": "Choisissez une réponse",
    "de-DE": "Antwort auswählen",
    "ja-JP": "答えを選択",
    "ko-KR": "답을 선택하세요",
    "pt-BR": "Escolha uma resposta",
  },
  "多选项": {
    "en-US": "Multiple options",
    "es-ES": "Múltiples opciones",
    "fr-FR": "Options multiples",
    "de-DE": "Mehrere Optionen",
    "ja-JP": "複数の選択肢",
    "ko-KR": "여러 선택지",
    "pt-BR": "Múltiplas opções",
  },
  "选择所有符合的选项": {
    "en-US": "Select all that apply",
    "es-ES": "Selecciona todas las que correspondan",
    "fr-FR": "Sélectionnez toutes les réponses applicables",
    "de-DE": "Alle zutreffenden auswählen",
    "ja-JP": "当てはまるものをすべて選択",
    "ko-KR": "해당하는 항목을 모두 선택하세요",
    "pt-BR": "Selecione todas as aplicáveis",
  },
  "排序选项": {
    "en-US": "Sort options",
    "es-ES": "Ordenar opciones",
    "fr-FR": "Trier les options",
    "de-DE": "Optionen sortieren",
    "ja-JP": "選択肢を並べ替え",
    "ko-KR": "선택지 정렬",
    "pt-BR": "Ordenar opções",
  },
  "上移": {
    "en-US": "Move up",
    "es-ES": "Subir",
    "fr-FR": "Monter",
    "de-DE": "Nach oben",
    "ja-JP": "上へ移動",
    "ko-KR": "위로 이동",
    "pt-BR": "Mover para cima",
  },
  "下移": {
    "en-US": "Move down",
    "es-ES": "Bajar",
    "fr-FR": "Descendre",
    "de-DE": "Nach unten",
    "ja-JP": "下へ移動",
    "ko-KR": "아래로 이동",
    "pt-BR": "Mover para baixo",
  },
  "输入你的答案": {
    "en-US": "Type your answer",
    "es-ES": "Escribe tu respuesta",
    "fr-FR": "Tapez votre réponse",
    "de-DE": "Antwort eingeben",
    "ja-JP": "答えを入力",
    "ko-KR": "답을 입력하세요",
    "pt-BR": "Digite sua resposta",
  },
  "输入你的答案\u2026": {
    "en-US": "Type your answer\u2026",
    "es-ES": "Escribe tu respuesta…",
    "fr-FR": "Tapez votre réponse…",
    "de-DE": "Antwort eingeben …",
    "ja-JP": "答えを入力…",
    "ko-KR": "답을 입력하세요…",
    "pt-BR": "Digite sua resposta…",
  },
  "你的回答": {
    "en-US": "Your answer",
    "es-ES": "Tu respuesta",
    "fr-FR": "Votre réponse",
    "de-DE": "Ihre Antwort",
    "ja-JP": "あなたの答え",
    "ko-KR": "내 답변",
    "pt-BR": "Sua resposta",
  },
  "提交答案": {
    "en-US": "Submit answer",
    "es-ES": "Enviar respuesta",
    "fr-FR": "Soumettre la réponse",
    "de-DE": "Antwort absenden",
    "ja-JP": "解答を送信",
    "ko-KR": "답변 제출",
    "pt-BR": "Enviar resposta",
  },
  "答对了": {
    "en-US": "Correct",
    "es-ES": "¡Correcto!",
    "fr-FR": "Correct !",
    "de-DE": "Richtig",
    "ja-JP": "正解",
    "ko-KR": "정답",
    "pt-BR": "Correto",
  },
  "待加强": {
    "en-US": "Needs work",
    "es-ES": "Necesita reforzarse",
    "fr-FR": "À renforcer",
    "de-DE": "Braucht Übung",
    "ja-JP": "要強化",
    "ko-KR": "보강 필요",
    "pt-BR": "Precisa reforçar",
  },
  "已回看": {
    "en-US": "Reviewed",
    "es-ES": "Repasado",
    "fr-FR": "Révisé",
    "de-DE": "Wiederholt",
    "ja-JP": "復習済み",
    "ko-KR": "복습함",
    "pt-BR": "Revisado",
  },
  "答对了！": {
    "en-US": "Correct!",
    "es-ES": "¡Correcto!",
    "fr-FR": "Correct !",
    "de-DE": "Richtig!",
    "ja-JP": "正解！",
    "ko-KR": "정답!",
    "pt-BR": "Correto!",
  },
  "需要加强，继续努力": {
    "en-US": "Needs work, keep trying",
    "es-ES": "Necesita reforzarse, sigue intentando",
    "fr-FR": "À renforcer, continuez",
    "de-DE": "Braucht Übung, weiter versuchen",
    "ja-JP": "要強化。続けましょう",
    "ko-KR": "보강이 필요합니다, 계속하세요",
    "pt-BR": "Precisa reforçar, continue tentando",
  },
  "连续答对 {count} 张！": {
    "en-US": "{count} in a row!",
    "es-ES": "¡{count} seguidas!",
    "fr-FR": "{count} d'affilée !",
    "de-DE": "{count} in Folge!",
    "ja-JP": "連続 {count} 枚正解！",
    "ko-KR": "연속 {count}장 정답!",
    "pt-BR": "{count} seguidas!",
  },
  "本题得分：{percent}%": {
    "en-US": "Score: {percent}%",
    "es-ES": "Puntuación: {percent}%",
    "fr-FR": "Score : {percent}%",
    "de-DE": "Punkte: {percent}%",
    "ja-JP": "この問題の得点：{percent}%",
    "ko-KR": "이 문항 점수: {percent}%",
    "pt-BR": "Pontuação: {percent}%",
  },
  "参考答案：": {
    "en-US": "Reference answer: ",
    "es-ES": "Respuesta de referencia: ",
    "fr-FR": "Réponse attendue : ",
    "de-DE": "Erwartete Antwort: ",
    "ja-JP": "参考解答：",
    "ko-KR": "참고 답안: ",
    "pt-BR": "Resposta esperada: ",
  },
  "你的回答：": {
    "en-US": "Your answer: ",
    "es-ES": "Tu respuesta: ",
    "fr-FR": "Votre réponse : ",
    "de-DE": "Ihre Antwort: ",
    "ja-JP": "あなたの答え：",
    "ko-KR": "내 답변: ",
    "pt-BR": "Sua resposta: ",
  },
  "迁移场景": {
    "en-US": "Transferable scenario",
    "es-ES": "Escenario transferible",
    "fr-FR": "Scénario transférable",
    "de-DE": "Übertragbares Szenario",
    "ja-JP": "転用シナリオ",
    "ko-KR": "전이 시나리오",
    "pt-BR": "Cenário transferível",
  },
  "常见错误": {
    "en-US": "Common mistakes",
    "es-ES": "Errores comunes",
    "fr-FR": "Erreurs fréquentes",
    "de-DE": "Häufige Fehler",
    "ja-JP": "よくある間違い",
    "ko-KR": "흔한 오류",
    "pt-BR": "Erros comuns",
  },
  "你觉得掌握了吗？": {
    "en-US": "How well do you know this?",
    "es-ES": "¿Cuánto lo dominas?",
    "fr-FR": "À quel point le maîtrisez-vous ?",
    "de-DE": "Wie gut beherrschen Sie das?",
    "ja-JP": "どのくらい把握できましたか？",
    "ko-KR": "얼마나 확실히 알고 있나요?",
    "pt-BR": "Quão bem você domina isso?",
  },
  "下一张": {
    "en-US": "Next card",
    "es-ES": "Siguiente",
    "fr-FR": "Suivante",
    "de-DE": "Nächste",
    "ja-JP": "次のカード",
    "ko-KR": "다음 카드",
    "pt-BR": "Próximo cartão",
  },
  "问教练": {
    "en-US": "Ask coach",
    "es-ES": "Preguntar al coach",
    "fr-FR": "Demander au coach",
    "de-DE": "Coach fragen",
    "ja-JP": "コーチに聞く",
    "ko-KR": "코치에게 묻기",
    "pt-BR": "Perguntar ao coach",
  },
  "在教练中实战": {
    "en-US": "Practice in coach",
    "es-ES": "Practicar en el coach",
    "fr-FR": "Pratiquer dans le coach",
    "de-DE": "Im Coach üben",
    "ja-JP": "Coach で実戦",
    "ko-KR": "코치에서 실전",
    "pt-BR": "Praticar no coach",
  },
  "依赖掌握": {
    "en-US": "Dependency mastery",
    "es-ES": "Dominio de dependencias",
    "fr-FR": "Maîtrise des dépendances",
    "de-DE": "Beherrschung der Abhängigkeiten",
    "ja-JP": "依存関係の把握",
    "ko-KR": "의존성 숙달",
    "pt-BR": "Domínio de dependências",
  },
  "待建立": {
    "en-US": "Not established",
    "es-ES": "Sin establecer",
    "fr-FR": "Non établi",
    "de-DE": "Nicht eingerichtet",
    "ja-JP": "未確立",
    "ko-KR": "미설정",
    "pt-BR": "Não estabelecido",
  },
  "最近反馈": {
    "en-US": "Recent feedback",
    "es-ES": "Feedback reciente",
    "fr-FR": "Feedback récent",
    "de-DE": "Neuestes Feedback",
    "ja-JP": "最近のフィードバック",
    "ko-KR": "최근 피드백",
    "pt-BR": "Feedback recente",
  },
};

function flashText(language: ComposerLanguage, key: string): string {
  if (language === "zh-CN") {
    return key;
  }
  return FLASH_TEXT[key]?.[language] ?? key;
}

function flashTextFormat(
  language: ComposerLanguage,
  key: string,
  values: Record<string, string | number>,
): string {
  return Object.entries(values).reduce(
    (copy, [name, value]) => copy.split(`{${name}}`).join(String(value)),
    flashText(language, key),
  );
}

/** Fixed zh label + per-language record, for keys whose en differs by context. */
function flashLevelText(
  language: ComposerLanguage,
  zh: string,
  values: Record<FlashTextLanguages, string>,
): string {
  return language === "zh-CN" ? zh : values[language];
}

/** handleMastery persists the reason — its en "Don't know" keeps the straight apostrophe. */
const MASTERY_REASON_TEXT: Record<"know" | "fuzzy" | "unknown", Record<FlashTextLanguages, string>> = {
  know: {
    "en-US": "Know well",
    "es-ES": "Lo domino",
    "fr-FR": "Je maîtrise",
    "de-DE": "Sicher gewusst",
    "ja-JP": "把握できた",
    "ko-KR": "알고 있음",
    "pt-BR": "Sei bem",
  },
  fuzzy: {
    "en-US": "Fuzzy",
    "es-ES": "Confuso",
    "fr-FR": "Flou",
    "de-DE": "Unklar",
    "ja-JP": "あやふや",
    "ko-KR": "애매함",
    "pt-BR": "Confuso",
  },
  unknown: {
    "en-US": "Don't know",
    "es-ES": "No lo sé",
    "fr-FR": "Je ne sais pas",
    "de-DE": "Nicht gewusst",
    "ja-JP": "わからない",
    "ko-KR": "모름",
    "pt-BR": "Não sei",
  },
};

/** The multiple-choice label reads "Correct answers" in en-US (singular is in FLASH_TEXT). */
const CREATE_CORRECT_ANSWER_MULTIPLE_TEXT: Record<FlashTextLanguages, string> = {
  "en-US": "Correct answers",
  "es-ES": "Respuestas correctas",
  "fr-FR": "Bonnes réponses",
  "de-DE": "Richtige Antworten",
  "ja-JP": "正解",
  "ko-KR": "정답",
  "pt-BR": "Respostas corretas",
};

/** Keyboard legend uses shorter labels than the nav buttons below it. */
const FLASH_KBD_LEGEND_TEXT: Record<"next" | "rate" | "coach", Record<FlashTextLanguages, string>> = {
  next: {
    "en-US": "Next",
    "es-ES": "Siguiente",
    "fr-FR": "Suivant",
    "de-DE": "Weiter",
    "ja-JP": "次へ",
    "ko-KR": "다음",
    "pt-BR": "Próximo",
  },
  rate: {
    "en-US": "Rate",
    "es-ES": "Evaluar",
    "fr-FR": "Évaluer",
    "de-DE": "Bewerten",
    "ja-JP": "評価",
    "ko-KR": "평가",
    "pt-BR": "Avaliar",
  },
  coach: {
    "en-US": "Coach",
    "es-ES": "Coach",
    "fr-FR": "Coach",
    "de-DE": "Coach",
    "ja-JP": "コーチ",
    "ko-KR": "코치",
    "pt-BR": "Coach",
  },
};

function normalizeAnswerMode(
  value: string | undefined,
  hasOptions: boolean,
): FlashcardAnswerMode {
  if (
    value === "text" ||
    value === "single_choice" ||
    value === "multiple_choice" ||
    value === "fill_blank" ||
    value === "sorting" ||
    value === "true_false"
  ) {
    return value;
  }
  if (value === "short") {
    return "text";
  }
  if (value === "choice") {
    return "single_choice";
  }
  if (value === "fill") {
    return "fill_blank";
  }
  return hasOptions ? "single_choice" : "text";
}

function answerModeSummary(language: ComposerLanguage, mode: FlashcardAnswerMode): string {
  if (mode === "single_choice") {
    return flashText(language, "从几个选项里选出最稳的一项。");
  }
  if (mode === "multiple_choice") {
    return flashText(language, "把所有成立的选项一起找出来。");
  }
  if (mode === "fill_blank") {
    return flashText(language, "补上缺失的 keyword 或 concept。");
  }
  if (mode === "sorting") {
    return flashText(language, "按正确顺序排好这些步骤。");
  }
  if (mode === "true_false") {
    return flashText(language, "先判断对错，再确认理由。");
  }
  return flashText(language, "先用你自己的话给出简短答案。");
}

// ---------------------------------------------------------------------------
// Feedback helpers
// ---------------------------------------------------------------------------

function getAnswerFeedback(language: ComposerLanguage, status: FlashcardAttempt["status"], streakCount: number): string {
  if (status === "correct") {
    if (streakCount >= 3) return flashTextFormat(language, "连续答对 {count} 张！", { count: streakCount });
    return flashText(language, "答对了！");
  }
  if (status === "needsWork") return flashText(language, "需要加强，继续努力");
  return flashText(language, "已回看");
}

function calculateStreak(attempts: FlashcardAttempt[]): number {
  let streak = 0;
  const sorted = [...attempts].sort((a, b) =>
    new Date(b.attemptedAt ?? 0).getTime() - new Date(a.attemptedAt ?? 0).getTime()
  );
  for (const attempt of sorted) {
    if (attempt.status === "correct") {
      streak++;
    } else if (attempt.status === "needsWork") {
      break;
    }
  }
  return streak;
}

function pickCard(deck: FlashcardDeck | undefined): FlashcardAttempt | undefined {
  if (!deck || !deck.cards || deck.cards.length === 0) {
    return undefined;
  }
  const unanswered = deck.cards.find((c) => c.status === "unanswered" || !c.status);
  return unanswered ?? deck.cards[0];
}

function feedbackKey(
  status?: FlashcardAttempt["status"],
): "correct" | "incorrect" | "partial" | null {
  if (status === "correct") return "correct";
  if (status === "needsWork") return "incorrect";
  if (status === "reviewed") return "partial";
  return null;
}

function StatusIcon({ status }: { status: FlashcardAttempt["status"] }): React.ReactNode {
  if (status === "correct") return <CheckMarkIcon size={14} />;
  if (status === "needsWork") return <XMarkIcon size={14} />;
  if (status === "reviewed") return <WarningIcon size={14} />;
  return null;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function CoachFlashView({
  language,
  deck,
  deckError = false,
  dependencyMastery,
  recentAttempts,
  busy = false,
  practiceBridge,
  cardStatus,
  cardStatusBusy = false,
  onCardStatusTransition,
  onRefreshDeck,
  onSubmitAnswer,
  onOpenCoach,
  onOpenPractice,
  onCreateFlashcard,
  compact = false,
  cardOnly = false,
  sourceChain,
  whyNow,
  targetSkill,
  scenarioPackLabel,
  feedbackTargets,
}: CoachFlashViewProps) {
  const card = useMemo(() => pickCard(deck), [deck]);
  const hasOptions = Boolean(card?.options && card.options.length > 0);
  const answerMode = normalizeAnswerMode(card?.answerMode, hasOptions);
  const isAnswered = Boolean(card?.status && card.status !== "unanswered");
  const fbKey = feedbackKey(card?.status);
  const copy = resolveCopy(language);

  // Local state
  const [textInput, setTextInput] = useState("");
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const [selectedIndices, setSelectedIndices] = useState<Set<number>>(new Set());
  const [fillBlankAnswers, setFillBlankAnswers] = useState<Record<number, string>>({});
  const [sortOrder, setSortOrder] = useState<number[]>([]);
  const [hintsRevealed, setHintsRevealed] = useState(0);
  const [contextOpen, setContextOpen] = useState(false);
  const [focusedOptionIdx, setFocusedOptionIdx] = useState(0);
  const [masteryMark, setMasteryMark] = useState<"know" | "fuzzy" | "unknown" | null>(null);
  const [studyPhase, setStudyPhase] = useState<FlashStudyPhase>("learn");

  // Creation form state
  const [isCreating, setIsCreating] = useState(false);
  const [createQuestion, setCreateQuestion] = useState("");
  const [createAnswerMode, setCreateAnswerMode] = useState<FlashcardAnswerMode>("text");
  const [createOptions, setCreateOptions] = useState<string[]>([""]);
  const [createExpectedAnswer, setCreateExpectedAnswer] = useState("");
  const [createCorrectIndex, setCreateCorrectIndex] = useState<number | null>(null);
  const [createCorrectIndices, setCreateCorrectIndices] = useState<Set<number>>(new Set());
  const [createCorrectSortOrder, setCreateCorrectSortOrder] = useState<number[]>([]);
  const [createFillBlankAnswers, setCreateFillBlankAnswers] = useState<Record<number, string>>({});
  const [createHints, setCreateHints] = useState<string[]>([""]);
  const [createContext, setCreateContext] = useState("");

  const answerRef = useRef<HTMLTextAreaElement>(null);
  const optionRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const containerRef = useRef<HTMLDivElement>(null);

  // Calculate current streak from recent attempts
  const streak = useMemo(() => calculateStreak(recentAttempts), [recentAttempts]);

  // Feedback message after answer
  const feedbackTitle = useMemo(() => {
    if (isAnswered && card?.status) {
      return getAnswerFeedback(language, card.status, streak);
    }
    return "";
  }, [language, isAnswered, card?.status, streak]);

  // Reset on card change
  useEffect(() => {
    setTextInput("");
    setSelectedIdx(null);
    setSelectedIndices(new Set());
    setFillBlankAnswers({});
    setSortOrder(card?.options ? Array.from({ length: card.options.length }, (_, i) => i) : []);
    setHintsRevealed(0);
    setContextOpen(false);
    setFocusedOptionIdx(0);
    setMasteryMark(null);
    setStudyPhase(isAnswered ? "review" : "learn");
  }, [card?.cardId, card?.options, isAnswered]);

  // Focus answer area on new card
  useEffect(() => {
    if (!isAnswered && studyPhase === "check") {
      setTimeout(() => {
        if (answerMode === "single_choice" || answerMode === "multiple_choice" || answerMode === "true_false") {
          (optionRefs.current[focusedOptionIdx] ?? optionRefs.current[0])?.focus();
          return;
        }
        answerRef.current?.focus();
      }, 80);
    }
  }, [answerMode, card?.cardId, focusedOptionIdx, isAnswered, studyPhase]);

  useEffect(() => {
    if (isAnswered && studyPhase !== "review") {
      setStudyPhase("review");
    }
  }, [isAnswered, studyPhase]);

  // Submit handler
  const handleSubmit = useCallback(() => {
    if (!card || busy || isAnswered) return;
    if (answerMode === "single_choice" || answerMode === "true_false") {
      if (selectedIdx === null) return;
      onSubmitAnswer({ cardId: card.cardId, selectedOptionIndex: selectedIdx });
    } else if (answerMode === "multiple_choice") {
      if (selectedIndices.size === 0) return;
      onSubmitAnswer({ cardId: card.cardId, selectedOptionIndices: Array.from(selectedIndices) });
    } else if (answerMode === "fill_blank") {
      const blanks = Object.keys(fillBlankAnswers).length;
      if (blanks === 0) return;
      onSubmitAnswer({ cardId: card.cardId, fillBlankAnswers });
    } else if (answerMode === "sorting") {
      onSubmitAnswer({ cardId: card.cardId, sortOrder });
    } else {
      if (!textInput.trim()) return;
      onSubmitAnswer({ cardId: card.cardId, learnerAnswer: textInput.trim() });
    }
  }, [answerMode, card, busy, isAnswered, selectedIdx, selectedIndices, fillBlankAnswers, sortOrder, textInput, onSubmitAnswer]);

  // Keyboard: Enter to submit, arrows for options
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (!isAnswered && studyPhase === "learn" && (e.key === "Enter" || e.key === " ")) {
        e.preventDefault();
        setStudyPhase("check");
        return;
      }
      if (e.key === "Enter" && !e.shiftKey) {
        if (studyPhase === "check" && (answerMode === "text" || answerMode === "single_choice")) {
          e.preventDefault();
          handleSubmit();
        }
      }
      if (
        (answerMode === "single_choice" || answerMode === "true_false") &&
        hasOptions &&
        !isAnswered &&
        studyPhase === "check"
      ) {
        const optionsCount = card?.options?.length ?? 0;
        if (e.key === "ArrowDown" || e.key === "ArrowRight") {
          e.preventDefault();
          const next = (focusedOptionIdx + 1) % optionsCount;
          setFocusedOptionIdx(next);
          optionRefs.current[next]?.focus();
        }
        if (e.key === "ArrowUp" || e.key === "ArrowLeft") {
          e.preventDefault();
          const prev = (focusedOptionIdx - 1 + optionsCount) % optionsCount;
          setFocusedOptionIdx(prev);
          optionRefs.current[prev]?.focus();
        }
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          setSelectedIdx(focusedOptionIdx);
        }
        if (e.key === "1" || e.key === "2" || e.key === "3" || e.key === "4") {
          const idx = parseInt(e.key, 10) - 1;
          if (idx < optionsCount) {
            e.preventDefault();
            setSelectedIdx(idx);
            setFocusedOptionIdx(idx);
            optionRefs.current[idx]?.focus();
          }
        }
      }
    },
    [answerMode, card?.options?.length, focusedOptionIdx, handleSubmit, hasOptions, isAnswered, studyPhase],
  );

  // Mastery mark handler — fail-closed: no local-only grade without status transition.
  const canTransitionCardStatus = Boolean(card?.cardId && onCardStatusTransition);
  const handleMastery = useCallback(
    (level: "know" | "fuzzy" | "unknown") => {
      if (!card?.cardId || !onCardStatusTransition) {
        return;
      }
      setMasteryMark(level);
      // The persisted reason keeps its own straight-apostrophe en string ("Don't know").
      const reason = flashLevelText(
        language,
        level === "know" ? "掌握" : level === "fuzzy" ? "模糊" : "不会",
        level === "know"
          ? MASTERY_REASON_TEXT.know
          : level === "fuzzy"
            ? MASTERY_REASON_TEXT.fuzzy
            : MASTERY_REASON_TEXT.unknown,
      );
      onCardStatusTransition(card.cardId, "reviewed", reason);
    },
    [card, language, onCardStatusTransition],
  );

  // Global keyboard shortcuts for immersion
  useEffect(() => {
    function handleGlobalKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement;
      if (target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA' || target?.isContentEditable) {
        return;
      }

      if (isAnswered) {
        switch (event.key) {
          case 'n':
          case 'N': {
            event.preventDefault();
            onRefreshDeck();
            break;
          }
          case '1': {
            event.preventDefault();
            handleMastery('know');
            break;
          }
          case '2': {
            event.preventDefault();
            handleMastery('fuzzy');
            break;
          }
          case '3': {
            event.preventDefault();
            handleMastery('unknown');
            break;
          }
        }
      }
    }

    window.addEventListener('keydown', handleGlobalKeyDown);
    return () => window.removeEventListener('keydown', handleGlobalKeyDown);
  }, [isAnswered, onRefreshDeck, handleMastery]);

  // Creation form handlers
  const resetCreationForm = useCallback(() => {
    setCreateQuestion("");
    setCreateAnswerMode("text");
    setCreateOptions([""]);
    setCreateExpectedAnswer("");
    setCreateCorrectIndex(null);
    setCreateCorrectIndices(new Set());
    setCreateCorrectSortOrder([]);
    setCreateFillBlankAnswers({});
    setCreateHints([""]);
    setCreateContext("");
    setIsCreating(false);
  }, []);

  const handleCreateSubmit = useCallback(() => {
    if (!onCreateFlashcard || !createQuestion.trim()) return;
    const payload: Parameters<typeof onCreateFlashcard>[0] = {
      question: createQuestion.trim(),
      answerMode: createAnswerMode,
      hintLadder: createHints.filter(Boolean),
      context: createContext.trim() || undefined,
    };
    if (createAnswerMode === "text") {
      payload.expectedAnswer = createExpectedAnswer.trim() || undefined;
    } else if (createAnswerMode === "single_choice") {
      payload.options = createOptions.filter(Boolean);
      payload.correctOptionIndex = createCorrectIndex ?? undefined;
    } else if (createAnswerMode === "multiple_choice") {
      payload.options = createOptions.filter(Boolean);
      payload.correctOptionIndices = Array.from(createCorrectIndices);
    } else if (createAnswerMode === "sorting") {
      payload.options = createOptions.filter(Boolean);
      payload.correctSortOrder = createCorrectSortOrder.length > 0 ? createCorrectSortOrder : undefined;
    } else if (createAnswerMode === "fill_blank") {
      const answers: Record<number, string> = {};
      const matches = createQuestion.match(/\{\{(\d+)\}\}/g);
      if (matches) {
        matches.forEach((m) => {
          const num = parseInt(m.replace(/[{}]/g, ""), 10);
          if (createFillBlankAnswers[num]) {
            answers[num] = createFillBlankAnswers[num];
          }
        });
      }
      payload.fillBlankAnswers = Object.keys(answers).length > 0 ? answers : undefined;
    }
    onCreateFlashcard(payload);
    resetCreationForm();
  }, [onCreateFlashcard, createQuestion, createAnswerMode, createOptions, createExpectedAnswer, createCorrectIndex, createCorrectIndices, createCorrectSortOrder, createFillBlankAnswers, createHints, createContext, resetCreationForm]);

  const addOption = useCallback(() => setCreateOptions((prev) => [...prev, ""]), []);
  const removeOption = useCallback((idx: number) => setCreateOptions((prev) => prev.filter((_, i) => i !== idx)), []);
  const updateOption = useCallback((idx: number, val: string) => {
    setCreateOptions((prev) => {
      const next = [...prev];
      next[idx] = val;
      return next;
    });
  }, []);

  const addHint = useCallback(() => setCreateHints((prev) => [...prev, ""]), []);
  const removeHint = useCallback((idx: number) => setCreateHints((prev) => prev.filter((_, i) => i !== idx)), []);
  const updateHint = useCallback((idx: number, val: string) => {
    setCreateHints((prev) => {
      const next = [...prev];
      next[idx] = val;
      return next;
    });
  }, []);

  // --- Error state ---
  if (deckError) {
    return (
      <section className="section-block flash-state flash-state--error">
        <span className="flash-state__icon" aria-hidden="true"><WarningIcon size={20} /></span>
        <strong className="flash-state__title">
          {flashText(language, "加载闪记卡失败")}
        </strong>
        <p className="flash-state__text">
          {flashText(language, "请检查连接后重试。")}
        </p>
      </section>
    );
  }

  // --- Empty state ---
  if (!deck || !card) {
    if (isCreating) {
      return (
        <section className="flash-view flash-view--creating" aria-label={flashText(language, "创建闪记卡")}>
          <div className="flash-create-form">
            <h3 className="flash-create-form__title">{flashText(language, "创建闪记卡")}</h3>

            <label className="flash-create-form__label">{flashText(language, "问题")}</label>
            <textarea
              className="flash-create-form__textarea"
              rows={3}
              value={createQuestion}
              onChange={(e) => setCreateQuestion(e.target.value)}
              placeholder={flashText(language, "输入问题... 填空用 {{1}} 占位")}
            />

            <label className="flash-create-form__label">{flashText(language, "答题模式")}</label>
            <select
              className="flash-create-form__select"
              value={createAnswerMode}
              onChange={(e) => setCreateAnswerMode(e.target.value as FlashcardAnswerMode)}
            >
              <option value="text">{flashText(language, "文本回答")}</option>
              <option value="single_choice">{flashText(language, "单选题")}</option>
              <option value="multiple_choice">{flashText(language, "多选题")}</option>
              <option value="sorting">{flashText(language, "排序题")}</option>
              <option value="fill_blank">{flashText(language, "填空题")}</option>
            </select>

            {(createAnswerMode === "single_choice" || createAnswerMode === "multiple_choice" || createAnswerMode === "sorting") && (
              <div className="flash-create-form__options">
                <label className="flash-create-form__label">{flashText(language, "选项")}</label>
                {createOptions.map((opt, idx) => (
                  <div key={idx} className="flash-create-form__option-row">
                    <input
                      className="flash-create-form__input"
                      value={opt}
                      onChange={(e) => updateOption(idx, e.target.value)}
                      placeholder={flashTextFormat(language, "选项 {index}", { index: idx + 1 })}
                    />
                    {createOptions.length > 1 && (
                      <button type="button" className="button button--ghost button--micro" onClick={() => removeOption(idx)}>
                        <XMarkIcon size={12} />
                      </button>
                    )}
                  </div>
                ))}
                <button type="button" className="button button--ghost button--micro" onClick={addOption}>
                  {flashText(language, "+ 添加选项")}
                </button>

                {createAnswerMode === "single_choice" && (
                  <div className="flash-create-form__correct">
                    <label className="flash-create-form__label">{flashText(language, "正确答案")}</label>
                    <select
                      className="flash-create-form__select"
                      value={createCorrectIndex ?? ""}
                      onChange={(e) => setCreateCorrectIndex(e.target.value === "" ? null : parseInt(e.target.value, 10))}
                    >
                      <option value="">{flashText(language, "选择正确答案")}</option>
                      {createOptions.filter(Boolean).map((opt, idx) => (
                        <option key={idx} value={idx}>{opt}</option>
                      ))}
                    </select>
                  </div>
                )}

                {createAnswerMode === "multiple_choice" && (
                  <div className="flash-create-form__correct">
                    <label className="flash-create-form__label">{flashLevelText(language, "正确答案", CREATE_CORRECT_ANSWER_MULTIPLE_TEXT)}</label>
                    <div className="flash-create-form__checkboxes">
                      {createOptions.filter(Boolean).map((opt, idx) => (
                        <label key={idx} className="flash-create-form__checkbox-label">
                          <input
                            type="checkbox"
                            checked={createCorrectIndices.has(idx)}
                            onChange={(e) => {
                              setCreateCorrectIndices((prev) => {
                                const next = new Set(prev);
                                if (e.target.checked) next.add(idx);
                                else next.delete(idx);
                                return next;
                              });
                            }}
                          />
                          {opt}
                        </label>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {createAnswerMode === "text" && (
              <div className="flash-create-form__expected">
                <label className="flash-create-form__label">{flashText(language, "参考答案")}</label>
                <textarea
                  className="flash-create-form__textarea"
                  rows={2}
                  value={createExpectedAnswer}
                  onChange={(e) => setCreateExpectedAnswer(e.target.value)}
                  placeholder={flashText(language, "输入参考答案...")}
                />
              </div>
            )}

            {createAnswerMode === "fill_blank" && (
              <div className="flash-create-form__fill-blank-hint">
                <p className="flash-create-form__hint-text">
                  {flashText(language, "在问题中使用 {{1}}、{{2}} 等标记填空位置，然后在下方输入每个空的正确答案。")}
                </p>
                {(() => {
                  const matches = createQuestion.match(/\{\{(\d+)\}\}/g);
                  if (!matches) return <p className="flash-create-form__warning">{flashText(language, "尚未在问题中检测到填空标记")}</p>;
                  const seen = new Set<number>();
                  return matches.map((m) => {
                    const num = parseInt(m.replace(/[{}]/g, ""), 10);
                    if (seen.has(num)) return null;
                    seen.add(num);
                    return (
                      <div key={num} className="flash-create-form__blank-row">
                        <label>{flashTextFormat(language, "空 {count}", { count: num })}</label>
                        <input
                          className="flash-create-form__input"
                          value={createFillBlankAnswers[num] ?? ""}
                          onChange={(e) => setCreateFillBlankAnswers((prev) => ({ ...prev, [num]: e.target.value }))}
                        />
                      </div>
                    );
                  });
                })()}
              </div>
            )}

            <div className="flash-create-form__hints">
              <label className="flash-create-form__label">{flashText(language, "提示（可选）")}</label>
              {createHints.map((hint, idx) => (
                <div key={idx} className="flash-create-form__hint-row">
                  <input
                    className="flash-create-form__input"
                    value={hint}
                    onChange={(e) => updateHint(idx, e.target.value)}
                    placeholder={flashTextFormat(language, "提示 {index}", { index: idx + 1 })}
                  />
                  {createHints.length > 1 && (
                    <button type="button" className="button button--ghost button--micro" onClick={() => removeHint(idx)}>
                      <XMarkIcon size={12} />
                    </button>
                  )}
                </div>
              ))}
              <button type="button" className="button button--ghost button--micro" onClick={addHint}>
                {flashText(language, "+ 添加提示")}
              </button>
            </div>

            <label className="flash-create-form__label">{flashText(language, "背景上下文（可选）")}</label>
            <textarea
              className="flash-create-form__textarea"
              rows={2}
              value={createContext}
              onChange={(e) => setCreateContext(e.target.value)}
              placeholder={flashText(language, "输入背景上下文...")}
            />

            <div className="flash-create-form__actions">
              <button
                className="button button--accent"
                type="button"
                onClick={handleCreateSubmit}
                disabled={!createQuestion.trim() || busy}
              >
                {flashText(language, "创建闪记卡")}
              </button>
              <button className="button button--ghost" type="button" onClick={resetCreationForm}>
                {flashText(language, "取消")}
              </button>
            </div>
          </div>
        </section>
      );
    }
    return (
      <section
        className="flash-view coach-empty-state coach-empty-state--welcome"
        aria-label={flashText(language, "闪卡复习")}
        ref={containerRef}
      >
        <div className="flash-empty__icon" aria-hidden="true">
          <BooksIcon size={32} />
        </div>
        <p className="coach-empty-state__copy">
          {flashText(language, "你的闪记卡库还是空的")}
        </p>
        <p className="coach-empty-state__hint">
          {t(
            language,
            "暂无闪卡。完成实战卡，或从对话生成闪记。",
            "No flashcards yet. Finish a practice card or generate flashcards from chat.",
          )}
        </p>
        <div className="coach-empty-state__starters">
          <button className="button button--accent" type="button" onClick={onOpenCoach}>
            {flashText(language, "去找教练聊聊")}
          </button>
          {onCreateFlashcard ? (
            <button className="button button--accent" type="button" onClick={() => setIsCreating(true)}>
              {flashText(language, "手动创建闪记卡")}
            </button>
          ) : null}
          <button className="button button--ghost" type="button" onClick={onRefreshDeck} disabled={busy}>
            {flashText(language, "刷新卡组")}
          </button>
        </div>
      </section>
    );
  }

  // --- Loading state ---
  if (busy && !isAnswered) {
    return (
      <section className="flash-view" aria-busy="true" aria-label={flashText(language, "加载中")}>
        <div className="flash-loading">
          <div className="training-skeleton-lines" aria-hidden="true">
            <span className="skeleton training-skeleton-line" />
            <span className="skeleton training-skeleton-line" />
            <span className="skeleton training-skeleton-line training-skeleton-line--short" />
          </div>
          <p className="flash-loading__text">
            {flashText(language, "提交中\u2026")}
          </p>
        </div>
      </section>
    );
  }

  const knowledgeTypeBadge = card.knowledgeType
    ? card.knowledgeType
    : null;

  const hintLadder = card.hintLadder ?? [];
  const canShowMoreHints = hintsRevealed < hintLadder.length;
  const rubricItems = Array.isArray(card.rubric) ? card.rubric : (card.rubric ? [card.rubric] : []);
  const commonMistakes = card.commonMistakes ?? [];
  const cardRecord = card as unknown as Record<string, unknown>;
  const lastFeedback = (
    (cardRecord.lastFeedback ?? cardRecord.last_feedback) as Record<string, unknown> | undefined
  );
  const gradedStatus: FlashcardAttempt["status"] =
    typeof lastFeedback?.correct === "boolean"
      ? lastFeedback.correct
        ? "correct"
        : "needsWork"
      : card.status;
  const gradedScore = typeof lastFeedback?.score === "number" ? lastFeedback.score : undefined;
  const gradedDetail = typeof lastFeedback?.detail === "string" ? lastFeedback.detail : undefined;
  const feedbackText =
    gradedDetail
    ?? (fbKey && card.feedback && typeof card.feedback === 'object' ? card.feedback[fbKey] : null);
  const visibleStudyPhase: FlashStudyPhase = isAnswered ? "review" : studyPhase;
  const sourceChainTrail = (sourceChain ?? []).filter(Boolean);
  const visibleFeedbackTargets = (feedbackTargets ?? []).filter(Boolean);
  const firstHint = hintLadder.find((hint) => hint?.trim())?.trim();
  const firstCommonMistake = commonMistakes.find((mistake) => mistake?.trim())?.trim();
  const cardContext = card.context?.trim() ?? "";
  const learnHeadline = targetSkill?.trim()
    ? flashTextFormat(language, "先把 {skill} 对齐，再开始检查。", { skill: targetSkill.trim() })
    : scenarioPackLabel?.trim()
      ? flashTextFormat(language, "先把 {pack} 这组场景读顺，再开始检查。", { pack: scenarioPackLabel.trim() })
      : flashText(language, "先把这张卡想让你锁住的判断点对齐，再开始检查。");
  const learnWhyNow = whyNow?.trim()
    ? whyNow.trim()
    : flashText(
        language,
        "先把下一步想清楚，再进入检查。这样更像真实工作流，不像突然考试。",
      );
  const studyCue = firstHint
    ?? (cardContext
      ? cardContext
      : flashText(
          language,
          "先用自己的话回忆：这张卡在帮你避免什么错误，或者在帮你确认哪个关键动作。",
        ));
  const returnCue = visibleFeedbackTargets[0]
    ?? flashText(
        language,
        "做完后带着你的答案和一个还不确定的点回到 Coach。",
      );
  const showLearnContextDetails = Boolean(cardContext) && cardContext !== studyCue;
  const showCheckSurface = visibleStudyPhase !== "learn";
  const startCheck = () => setStudyPhase("check");

  const hasCard = Boolean(deck && card);
  const isDeckComplete = deck && (
    (deck.dueCount === 0 && deck.remainingCount === 0) ||
    (deck.dueCount != null && deck.dueCount === 0 && deck.remainingCount != null && deck.remainingCount === 0)
  );
  const deckTotal = deck?.cards?.length ?? 0;
  const correctCount = deck?.cards?.filter(c => c.status === "correct" || c.status === "reviewed").length ?? 0;
  const accuracyPercent = deckTotal > 0 ? Math.round((correctCount / deckTotal) * 100) : 0;
  const isNoDeck = !deck || deckTotal === 0;

  return (
    <section
      key={card?.cardId ?? "empty"}
      className={`flash-view ${compact ? "flash-view--compact" : ""} ${cardOnly ? "flash-view--card-only" : ""} ${hasCard ? "card-enter" : ""}`}
      aria-label={flashText(language, "当前闪卡")}
      onKeyDown={handleKeyDown}
      ref={containerRef}
    >
      {/* ---- No deck state - first time user ---- */}
      {isNoDeck && !isCreating ? (
        <div className="flash-empty">
          <div className="flash-empty__icon" aria-hidden="true">
            <BooksIcon size={48} />
          </div>
          <h3 className="flash-empty__title">
            {flashText(language, "开始你的闪记训练")}
          </h3>
          <p className="flash-empty__description">
            {flashText(language, "从对话中学习新知识，或创建自定义闪记卡来强化记忆。")}
          </p>
          <div className="flash-empty__actions">
            <button
              className="button button--accent"
              type="button"
              onClick={onOpenCoach}
            >
              {flashText(language, "开始学习")}
            </button>
            {onCreateFlashcard && (
              <button
                className="button button--ghost"
                type="button"
                onClick={() => setIsCreating(true)}
              >
                {flashText(language, "创建闪记卡")}
              </button>
            )}
          </div>
          <div className="flash-empty__hints">
            <p className="flash-empty__hint-title">
              {flashText(language, "来源")}
            </p>
            <ul className="flash-empty__hint-list">
              <li>{flashText(language, "→ 对话生成")}</li>
              <li>{flashText(language, "→ 训练后生成")}</li>
              <li>{flashText(language, "→ 资料抽取")}</li>
            </ul>
          </div>
        </div>
      ) : isDeckComplete && !isCreating ? (
        <div className="flash-complete">
          <div className="flash-complete__icon" aria-hidden="true">
            <TrophyIcon size={48} />
          </div>
          <h3 className="flash-complete__title">
            {flashText(language, deckTotal === 0 ? "卡组已清空" : "本轮完成")}
          </h3>
          {deckTotal > 0 && (
            <p className="flash-complete__stats">
              {flashTextFormat(language, "本次复习 {count} 张 · 正确率 {percent}%", {
                count: deckTotal,
                percent: accuracyPercent,
              })}
            </p>
          )}
          {streak > 0 && (
            <p className="flash-complete__streak">
              {flashTextFormat(language, "连续 {count} 天", { count: streak })}
            </p>
          )}
          <div className="flash-complete__actions">
            <button
              className="button button--accent"
              type="button"
              onClick={onRefreshDeck}
            >
              {flashText(language, "再来一轮")}
            </button>
            <button
              className="button button--ghost"
              type="button"
              onClick={onOpenCoach}
            >
              {flashText(language, "去找教练")}
            </button>
          </div>
        </div>
      ) : (
        <div className="flash-card-root training-card">
          {/* ---- Flash card type badge (prominent) ---- */}
          <div className="flash-card__type-strip">
        <span className="flash-card__type-badge-main">
          <LightBulbIcon size={14} />
          {flashText(language, "闪记卡")}
        </span>
        <span className="flash-card__type-desc">
          {flashText(language, "快速回忆 · 即时反馈")}
        </span>
      </div>

      {/* ---- Source chain header ---- */}
      <div className="flash-card__header">
        <div className="flash-card__badges">
          {knowledgeTypeBadge ? (
            <span className="flash-card__badge flash-card__badge--type">
              {knowledgeTypeBadge}
            </span>
          ) : null}
          {scenarioPackLabel ? (
            <span className="message-part__status-chip">
              {flashTextFormat(language, "场景包 · {label}", { label: scenarioPackLabel })}
            </span>
          ) : null}
          <span className="flash-card__badge flash-card__badge--source">
            {flashText(language, "来自训练主线和薄弱点")}
          </span>
        </div>
        <div className="flash-card__header-actions">
          {onCreateFlashcard ? (
            <button
              type="button"
              className="button button--ghost button--micro"
              onClick={() => setIsCreating(true)}
              aria-label={flashText(language, "创建新闪记卡")}
            >
              {flashText(language, "+ 新建")}
            </button>
          ) : null}
          {deck.dueCount != null ? (
            <span className="flash-card__counter">
              {flashTextFormat(language, "待复习 {count}", { count: deck.dueCount })}
              {deck.remainingCount != null
                ? ` / ${flashTextFormat(language, "剩余 {count}", { count: deck.remainingCount })}`
                : ""}
            </span>
          ) : null}
        </div>
      </div>

      {/* ---- Source/why-now/target/feedback metadata is governance-only — moved to debug folding. ---- */}
      {visibleStudyPhase === "learn" ? (
        <div className="training-next-move flash-card__learn-first">
          <span className="training-next-move__label">{flashText(language, "先学习")}</span>
          <strong>{learnHeadline}</strong>
          <p>{learnWhyNow}</p>
          <ul className="training-inline-list flash-card__learn-first-list">
            <li>{flashTextFormat(language, "先看线索：{cue}", { cue: studyCue })}</li>
            <li>{flashTextFormat(language, "开始检查后：{summary}", { summary: answerModeSummary(language, answerMode) })}</li>
            {firstCommonMistake ? (
              <li>{flashTextFormat(language, "常见误区：{mistake}", { mistake: firstCommonMistake })}</li>
            ) : null}
            <li>{flashTextFormat(language, "带回 Coach：{cue}", { cue: returnCue })}</li>
          </ul>
          {showLearnContextDetails ? (
            <details className="training-details flash-card__learn-first-details">
              <summary>{flashText(language, "更多上下文")}</summary>
              <div className="training-details__summary">{cardContext}</div>
            </details>
          ) : null}
          <div className="training-verification-return__actions flash-card__learn-first-actions">
            <button className="button button--accent" type="button" onClick={startCheck} disabled={busy}>
              {flashText(language, "开始检查")}
            </button>
            <button className="button button--ghost" type="button" onClick={onOpenCoach}>
              {flashText(language, "问 Coach")}
            </button>
          </div>
        </div>
      ) : null}

      {hasCard && (sourceChainTrail.length || whyNow || targetSkill || feedbackTargets?.length) ? (
        <details className="flash-card__debug-meta">
          <summary>{flashText(language, "更多细节")}</summary>
          <div className="card-metadata">
            <div className="card-metadata__row">
              {sourceChainTrail.length ? (
                <span className="card-metadata__source">
                  {flashTextFormat(language, "来源: {chain}", { chain: sourceChain.join(" → ") })}
                </span>
              ) : null}
              {targetSkill ? (
                <span className="card-metadata__skill">{targetSkill}</span>
              ) : null}
            </div>
            {whyNow ? <p className="card-metadata__why">{whyNow}</p> : null}
            {feedbackTargets?.length ? (
              <div className="card-metadata__feedback">
                {feedbackTargets.map((target) => (
                  <span key={target} className="card-metadata__feedback-item">
                    <CheckMarkIcon size={12} />
                    {target}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        </details>
      ) : null}

      {showCheckSurface ? (
        <>
          <div className="training-flash-prompt flash-card__check-intro">
            <span>{flashText(language, visibleStudyPhase === "review" ? "已完成检查" : "现在检查")}</span>
            <p>{answerModeSummary(language, answerMode)}</p>
          </div>

      {/* ---- Question ---- */}
      <div className="flash-card__question" role="heading" aria-level={2}>
        <div className="flash-card__question-content">
          <MessageRichContent
            body={card.question ?? flashText(language, "（无问题）")}
            language={language}
          />
        </div>
      </div>

      {/* ---- Hint ladder (inline, next to question) ---- */}
      {hintLadder.length > 0 ? (
        <div className="flash-card__hints flash-card__hints--inline">
          {hintsRevealed === 0 && !isAnswered ? (
            <button
              className="flash-card__hints-count"
              type="button"
              onClick={() => setHintsRevealed(1)}
              aria-label={flashTextFormat(language, "{count} 个提示可用", {
                count: hintLadder.length,
                s: hintLadder.length > 1 ? "s" : "",
              })}
            >
              <span className="flash-card__hints-count-icon" aria-hidden="true">
                <LightBulbIcon size={14} />
              </span>
              <span className="flash-card__hints-count-text">
                {flashTextFormat(language, "{count} 个提示可用", {
                  count: hintLadder.length,
                  s: hintLadder.length > 1 ? "s" : "",
                })}
              </span>
            </button>
          ) : null}
          <div className="flash-card__hints-revealed">
            {hintLadder.slice(0, hintsRevealed).map((hint, idx) => (
              <div key={idx} className="flash-card__hint" role="status">
                <span className="flash-card__hint-label">
                  {flashTextFormat(language, "提示 {index}", { index: idx + 1 })}
                </span>
                <span className="flash-card__hint-text">{hint}</span>
              </div>
            ))}
          </div>
          {canShowMoreHints && hintsRevealed > 0 && !isAnswered ? (
            <button
              className="button button--ghost button--micro"
              type="button"
              onClick={() => setHintsRevealed((n) => n + 1)}
            >
              {flashText(language, "显示下一条提示")}
            </button>
          ) : null}
        </div>
      ) : null}

      {/* ---- Context (collapsible, default collapsed) ---- */}
      {card.context ? (
        <details className="flash-card__context" open={contextOpen} onToggle={(e) => setContextOpen((e.currentTarget as HTMLDetailsElement).open)}>
          <summary className="flash-card__context-toggle">
            <span className="flash-card__context-label">
              {flashText(language, "背景上下文")}
            </span>
            <span className="flash-card__context-arrow" aria-hidden="true">
              {contextOpen ? <ChevronUpIcon size={12} /> : <ChevronDownIcon size={12} />}
            </span>
          </summary>
          <div className="flash-card__context-body">
            {card.context}
          </div>
        </details>
      ) : null}

        </>
      ) : null}

      {/* ---- Answer area ---- */}
      {!isAnswered && showCheckSurface ? (
        <div className="flash-card__answer-area">
          {(() => {
            if (answerMode === "single_choice" || answerMode === "true_false") {
              return (
                <fieldset className="flash-card__options" role="radiogroup" aria-label={flashText(language, "选择答案")}>
                  <legend className="sr-only">{flashText(language, "选项")}</legend>
                  {card.options!.map((opt, idx) => (
                    <button
                      key={idx}
                      ref={(el) => { optionRefs.current[idx] = el; }}
                      type="button"
                      role="radio"
                      aria-checked={selectedIdx === idx}
                      className={`flash-card__option ${selectedIdx === idx ? "flash-card__option--selected" : ""}`}
                      onClick={() => setSelectedIdx(idx)}
                      tabIndex={idx === focusedOptionIdx ? 0 : -1}
                    >
                      <span className="flash-card__option-marker">
                        {selectedIdx === idx ? <RadioButtonIcon size={16} /> : <RadioButtonEmptyIcon size={16} />}
                      </span>
                      <span className="flash-card__option-text">{opt}</span>
                    </button>
                  ))}
                </fieldset>
              );
            }
            if (answerMode === "multiple_choice") {
              return (
                <fieldset className="flash-card__options" role="group" aria-label={flashText(language, "选择所有符合的选项")}>
                  <legend className="sr-only">{flashText(language, "多选项")}</legend>
                  {card.options!.map((opt, idx) => (
                    <button
                      key={idx}
                      type="button"
                      role="checkbox"
                      aria-checked={selectedIndices.has(idx)}
                      className={`flash-card__option ${selectedIndices.has(idx) ? "flash-card__option--selected" : ""}`}
                      onClick={() => {
                        setSelectedIndices((prev) => {
                          const next = new Set(prev);
                          if (next.has(idx)) next.delete(idx);
                          else next.add(idx);
                          return next;
                        });
                      }}
                    >
                      <span className="flash-card__option-marker">
                        {selectedIndices.has(idx) ? <CheckMarkIcon size={16} /> : <SquareIcon size={16} />}
                      </span>
                      <span className="flash-card__option-text">{opt}</span>
                    </button>
                  ))}
                </fieldset>
              );
            }
            if (answerMode === "sorting") {
              return (
                <div className="flash-card__sorting" role="list" aria-label={flashText(language, "排序选项")}>
                  {sortOrder.map((optIdx, position) => (
                    <div key={optIdx} className="flash-card__sort-item" role="listitem">
                      <span className="flash-card__sort-position">{position + 1}</span>
                      <span className="flash-card__sort-text">{card.options![optIdx]}</span>
                      <div className="flash-card__sort-controls">
                        <button
                          type="button"
                          className="button button--ghost button--micro"
                          disabled={position === 0}
                          onClick={() => {
                            setSortOrder((prev) => {
                              const next = [...prev];
                              [next[position], next[position - 1]] = [next[position - 1], next[position]];
                              return next;
                            });
                          }}
                          aria-label={flashText(language, "上移")}
                        >
                          <ChevronUpIcon size={12} />
                        </button>
                        <button
                          type="button"
                          className="button button--ghost button--micro"
                          disabled={position === sortOrder.length - 1}
                          onClick={() => {
                            setSortOrder((prev) => {
                              const next = [...prev];
                              [next[position], next[position + 1]] = [next[position + 1], next[position]];
                              return next;
                            });
                          }}
                          aria-label={flashText(language, "下移")}
                        >
                          <ChevronDownIcon size={12} />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              );
            }
            if (answerMode === "fill_blank") {
              const parts = (card.question ?? "").split(/\{\{(\d+)\}\}/g);
              let blankIndex = 0;
              return (
                <div className="flash-card__fill-blank">
                  <p className="flash-card__fill-blank-prompt">
                    {parts.map((part, i) => {
                      if (i % 2 === 1) {
                        const idx = blankIndex++;
                        return (
                          <input
                            key={i}
                            type="text"
                            className="flash-card__fill-blank-input"
                            value={fillBlankAnswers[idx] ?? ""}
                            onChange={(e) => {
                              setFillBlankAnswers((prev) => ({ ...prev, [idx]: e.target.value }));
                            }}
                            placeholder={flashTextFormat(language, "空 {count}", { count: idx + 1 })}
                            aria-label={flashTextFormat(language, "填空 {count}", { count: idx + 1 })}
                          />
                        );
                      }
                      return <span key={i}>{part}</span>;
                    })}
                  </p>
                </div>
              );
            }
            return (
              <div className="flash-card__text-input">
                <label htmlFor="flash-answer" className="sr-only">
                  {flashText(language, "输入你的答案")}
                </label>
                <textarea
                  id="flash-answer"
                  ref={answerRef}
                  className="flash-card__textarea"
                  rows={3}
                  placeholder={flashText(language, "输入你的答案\u2026")}
                  value={textInput}
                  onChange={(e) => setTextInput(e.target.value)}
                  disabled={busy}
                  aria-label={flashText(language, "你的回答")}
                />
              </div>
            );
          })()}

          {/* Submit */}
          <div className="flash-card__submit-row">
            <button
              className="button button--accent"
              type="button"
              onClick={handleSubmit}
              disabled={(() => {
                if (answerMode === "single_choice" || answerMode === "true_false") return selectedIdx === null;
                if (answerMode === "multiple_choice") return selectedIndices.size === 0;
                if (answerMode === "sorting") return false;
                if (answerMode === "fill_blank") return Object.keys(fillBlankAnswers).length === 0;
                return !textInput.trim();
              })() || busy}
            >
              {busy
                ? flashText(language, "提交中\u2026")
                : flashText(language, "提交答案")}
            </button>
          </div>
        </div>
      ) : null}

      {/* ---- Feedback after answer (rotateX reveal) ---- */}
      {isAnswered ? (
        <div className="training-flash-reveal-viewport">
          <div className="training-flash-reveal" key={card.cardId}>
            <div className="flash-card__feedback" aria-live="polite">
              <div className={`flash-card__feedback-banner flash-card__feedback-banner--${gradedStatus ?? "neutral"} score-pulse`}>
                <span className="flash-card__feedback-icon" aria-hidden="true">
                  <StatusIcon status={gradedStatus} />
                </span>
                <span className="flash-card__feedback-label">
                  {gradedStatus === "correct"
                    ? flashText(language, "答对了")
                    : gradedStatus === "needsWork"
                      ? flashText(language, "待加强")
                      : flashText(language, "已回看")}
                </span>
              </div>
              {/* Concise feedback line + (optional) deck-provided hint */}
              {feedbackTitle ? (
                <p className="flash-card__feedback-title">{feedbackTitle}</p>
              ) : null}
              {feedbackText ? (
                <p className="flash-card__feedback-text">{feedbackText}</p>
              ) : null}
              {gradedScore !== undefined ? (
                <p className="flash-card__feedback-score">
                  {flashTextFormat(language, "本题得分：{percent}%", { percent: Math.round(gradedScore * 100) })}
                </p>
              ) : null}

              {/* Expected answer */}
              {card.expectedAnswer ? (
                <div className="flash-card__reference">
                  <span className="flash-card__reference-label">
                    {flashText(language, "参考答案：")}
                  </span>
                  <span className="flash-card__reference-value">{card.expectedAnswer}</span>
                </div>
              ) : null}

              {/* Learner answer */}
              {card.learnerAnswer ? (
                <div className="flash-card__learner-answer">
                  <span className="flash-card__learner-label">
                    {flashText(language, "你的回答：")}
                  </span>
                  <span className="flash-card__learner-value">{card.learnerAnswer}</span>
                </div>
              ) : null}

              {/* Transferable scenario */}
              {card.transferableScenario ? (
                <div className="flash-card__transferable">
                  <span className="flash-card__transferable-label">
                    {flashText(language, "迁移场景")}
                  </span>
                  <p className="flash-card__transferable-text">{card.transferableScenario}</p>
                </div>
              ) : null}

              {/* Common mistakes */}
              {commonMistakes.length > 0 ? (
                <div className="flash-card__mistakes">
                  <span className="flash-card__mistakes-label">
                    {flashText(language, "常见错误")}
                  </span>
                  <ul className="flash-card__mistakes-list">
                    {commonMistakes.map((m, idx) => (
                      <li key={idx} className="flash-card__mistakes-item">{m}</li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {/* Rubric checklist (grading rubric, collapsed detail) */}
              {rubricItems.length > 0 ? (
                <div className="flash-card__rubric">
                  <CollapseSection
                    level={2}
                    title={copy.trainingCardDetailsRubric}
                    persistenceKey={`card-${card.cardId}-rubric`}
                  >
                    <ul className="flash-card__rubric-list">
                      {rubricItems.map((item, idx) => (
                        <li key={idx} className="flash-card__rubric-item">
                          <span className="flash-card__rubric-marker" aria-hidden="true">
                            <SquareIcon size={12} />
                          </span>
                          <span>{item}</span>
                        </li>
                      ))}
                    </ul>
                  </CollapseSection>
                </div>
              ) : null}

              {/* Mastery marking */}
              <div className="flash-card__mastery" role="radiogroup" aria-label={flashText(language, "你觉得掌握了吗？")}>
                <span className="flash-card__mastery-label">
                  {flashText(language, "你觉得掌握了吗？")}
                </span>
                <div className="flash-card__mastery-buttons">
                  <button
                    className={`button flash-card__mastery-btn ${masteryMark === "know" ? "flash-card__mastery-btn--active flash-card__mastery-btn--know" : ""}`}
                    type="button"
                    role="radio"
                    aria-checked={masteryMark === "know"}
                    onClick={() => handleMastery("know")}
                    disabled={cardStatusBusy || !canTransitionCardStatus}
                  >
                    → {flashText(language, "掌握")}
                    {masteryMark === "know" ? (
                      <span className="flash-card__mastery-check" aria-hidden="true">
                        <CheckMarkIcon size={12} />
                      </span>
                    ) : null}
                  </button>
                  <button
                    className={`button flash-card__mastery-btn ${masteryMark === "fuzzy" ? "flash-card__mastery-btn--active flash-card__mastery-btn--fuzzy" : ""}`}
                    type="button"
                    role="radio"
                    aria-checked={masteryMark === "fuzzy"}
                    onClick={() => handleMastery("fuzzy")}
                    disabled={cardStatusBusy || !canTransitionCardStatus}
                  >
                    → {flashText(language, "模糊")}
                    {masteryMark === "fuzzy" ? (
                      <span className="flash-card__mastery-check" aria-hidden="true">
                        <CheckMarkIcon size={12} />
                      </span>
                    ) : null}
                  </button>
                  <button
                    className={`button flash-card__mastery-btn ${masteryMark === "unknown" ? "flash-card__mastery-btn--active flash-card__mastery-btn--unknown" : ""}`}
                    type="button"
                    role="radio"
                    aria-checked={masteryMark === "unknown"}
                    onClick={() => handleMastery("unknown")}
                    disabled={cardStatusBusy || !canTransitionCardStatus}
                  >
                    → {flashText(language, "不会")}
                    {masteryMark === "unknown" ? (
                      <span className="flash-card__mastery-check" aria-hidden="true">
                        <CheckMarkIcon size={12} />
                      </span>
                    ) : null}
                  </button>
                </div>
              </div>

              {/* Actions after answer */}
              <div className="flash-card__kbd-hint" aria-hidden="true">
                <span className="flash-card__kbd">N</span>
                <span>{flashLevelText(language, "下一张", FLASH_KBD_LEGEND_TEXT.next)}</span>
                <span className="flash-card__kbd">1/2/3</span>
                <span>{flashLevelText(language, "自评", FLASH_KBD_LEGEND_TEXT.rate)}</span>
                <span className="flash-card__kbd">C</span>
                <span>{flashLevelText(language, "问教练", FLASH_KBD_LEGEND_TEXT.coach)}</span>
              </div>
              <div className="card-status-nav">
                <button
                  className="card-status-nav__btn card-status-nav__btn--primary"
                  type="button"
                  onClick={onRefreshDeck}
                  disabled={busy}
                >
                  {flashText(language, "下一张")} <ArrowRightIcon size={14} />
                </button>
                <button
                  className="card-status-nav__btn"
                  type="button"
                  onClick={onOpenCoach}
                >
                  {flashText(language, "问教练")}
                </button>
                {onOpenPractice && practiceBridge ? (
                  <button
                    className="card-status-nav__btn"
                    type="button"
                    onClick={() => onOpenPractice(practiceBridge)}
                  >
                    {flashText(language, "在教练中实战")}
                  </button>
                ) : null}
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {/* ---- Dependency mastery summary (compact) ---- */}
      {!cardOnly && dependencyMastery.length > 0 ? (
        <details className="flash-card__deps" aria-label={flashText(language, "依赖掌握")}>
          <summary className="flash-card__deps-toggle">
            <span className="eyebrow">{flashText(language, "依赖掌握")}</span>
            <span className="flash-card__deps-count">{dependencyMastery.length}</span>
          </summary>
          <div className="flash-card__deps-list">
            {dependencyMastery.slice(0, 5).map((dep) => (
              <div key={dep.dependencyKey} className="flash-card__dep-item">
                <span className="flash-card__dep-name">{dep.dependencyName}</span>
                <span className="flash-card__dep-score">
                  {dep.masteryStage ?? flashText(language, "待建立")}
                  {" "}
                  ({Math.round(dep.masteryScore * 100)}%)
                </span>
              </div>
            ))}
          </div>
        </details>
      ) : null}

      {/* ---- Recent attempts strip ---- */}
      {!cardOnly && recentAttempts.length > 0 ? (
        <div className="flash-card__recent" aria-label={flashText(language, "最近反馈")}>
          <span className="flash-card__recent-label eyebrow">
            {flashText(language, "最近反馈")}
          </span>
          <div className="flash-card__recent-strip">
            {recentAttempts.slice(0, 4).map((attempt) => (
              <span
                key={attempt.id}
                className={`flash-card__recent-pip flash-card__recent-pip--${attempt.status ?? "neutral"}`}
                title={attempt.question ?? ""}
                aria-label={`${attempt.question ?? ""}: ${attempt.status ?? "unanswered"}`}
              >
                <StatusIcon status={attempt.status} />
              </span>
            ))}
          </div>
        </div>
      ) : null}
      </div>
    )}
    </section>
  );
}

