'use strict';

/**
 * Trainer side panel — full conversation client.
 *
 * Auth rides the same browser credential as capture. The page never sees the
 * sidecar instance token or a provider key: the sidecar's /browser/chat/*
 * lane scopes every call to the paired workspace.
 */

const T = self.TrainerCapture;

const CHAT_COPY = {
  'zh-CN': {
    practiceAnswerLabel: '你的作答',
    practiceAnswerPlaceholder: '在卡内写下这一轮的答案。',
    practiceSubmit: '提交作答',
    learning: '学习', practice: '练习', goal: '当前目标', duePractice: '到期练习',
    progress: '成长进度', history: '历史', newChat: '新对话', startInChat: '在对话中开始',
    notRunning: 'Trainer 未运行', notRunningDetail: '先打开 VS Code 中的 Trainer，再回到这里。',
    reconnect: '重新连接', openTrainer: '打开 Trainer', placeholder: '给 Trainer 发消息…',
    send: '发送', thinking: '正在思考…', connectionLost: '连接已断开。',
    empty: '从这里开始：问一个问题，或让 Trainer 继续当前学习。',
    practiceFallback: '当前练习', practicePrompt: (title) => `开始练习：${title}`,
    noGoal: '还没有正式计划。', noPractice: '现在没有到期练习。', noProgress: '完成一次练习后会出现进度。',
    practiceRecorded: '这次练习已记录。', practiceRecordFailed: '这次练习没有被记录,请在 Trainer 里重试。',
    progressUpdated: '进度已更新', evidenceCount: '{n} 条证据', viewGrowth: '查看成长',
    dimensionComprehension: '理解', dimensionImplementation: '实现', dimensionDebugging: '调试', dimensionTransfer: '迁移',
    stateNotVerified: '还未验证', stateAssisted: '有辅助完成', stateIndependent: '独立完成', stateRepeatVerified: '反复验证', stateNeedsReview: '需要回顾',
    close: '关闭',
    statusActive: '进行中', statusPending: '待开始', statusCompleted: '已完成', statusNeedsReview: '需要回顾', statusSkipped: '已跳过', statusDraft: '草稿',
  },
  'en-US': {
    practiceAnswerLabel: 'Your answer',
    practiceAnswerPlaceholder: "Write this round's answer in the card.",
    practiceSubmit: 'Submit answer',
    learning: 'Learning', practice: 'Practice', goal: 'Current goal', duePractice: 'Due practice',
    progress: 'Growth', history: 'History', newChat: 'New chat', startInChat: 'Start in chat',
    notRunning: 'Trainer is not running', notRunningDetail: 'Open Trainer in VS Code, then come back here.',
    reconnect: 'Reconnect', openTrainer: 'Open Trainer', placeholder: 'Message Trainer…',
    send: 'Send', thinking: 'Thinking…', connectionLost: 'The connection was lost.',
    empty: 'Start here: ask a question, or let Trainer continue the current learning step.',
    practiceFallback: 'Current practice', practicePrompt: (title) => `Start practice: ${title}`,
    noGoal: 'No formal plan yet.', noPractice: 'Nothing is due right now.', noProgress: 'Progress appears after one practice.',
    practiceRecorded: 'This practice was recorded.', practiceRecordFailed: 'This practice was not recorded. Retry it in Trainer.',
    progressUpdated: 'Progress updated', evidenceCount: '{n} evidence', viewGrowth: 'View growth',
    dimensionComprehension: 'Comprehension', dimensionImplementation: 'Implementation', dimensionDebugging: 'Debugging', dimensionTransfer: 'Transfer',
    stateNotVerified: 'Not verified yet', stateAssisted: 'Completed with hints', stateIndependent: 'Independent', stateRepeatVerified: 'Repeatedly verified', stateNeedsReview: 'Needs review',
    close: 'Close',
    statusActive: 'In progress', statusPending: 'Pending', statusCompleted: 'Completed', statusNeedsReview: 'Needs review', statusSkipped: 'Skipped', statusDraft: 'Draft',
  },
  'es-ES': {
    practiceAnswerLabel: 'Tu respuesta',
    practiceAnswerPlaceholder: 'Escribe la respuesta de esta ronda en la tarjeta.',
    practiceSubmit: 'Enviar respuesta',
    learning: 'Aprendizaje', practice: 'Práctica', goal: 'Objetivo actual', duePractice: 'Práctica pendiente',
    progress: 'Progreso', history: 'Historial', newChat: 'Nueva conversación', startInChat: 'Empezar en el chat',
    notRunning: 'Trainer no está en ejecución', notRunningDetail: 'Abre Trainer en VS Code y vuelve aquí.',
    reconnect: 'Reconectar', openTrainer: 'Abrir Trainer', placeholder: 'Escribe a Trainer…',
    send: 'Enviar', thinking: 'Pensando…', connectionLost: 'Se perdió la conexión.',
    empty: 'Empieza aquí: haz una pregunta o deja que Trainer continúe el paso actual.',
    practiceFallback: 'Práctica actual', practicePrompt: (title) => `Empezar práctica: ${title}`,
    noGoal: 'Aún no hay un plan formal.', noPractice: 'No hay práctica pendiente.', noProgress: 'El progreso aparece tras una práctica.',
    practiceRecorded: 'Esta práctica quedó registrada.', practiceRecordFailed: 'Esta práctica no quedó registrada. Repítela en Trainer.',
    progressUpdated: 'Progreso actualizado', evidenceCount: '{n} evidencias', viewGrowth: 'Ver progreso',
    dimensionComprehension: 'Comprensión', dimensionImplementation: 'Implementación', dimensionDebugging: 'Depuración', dimensionTransfer: 'Transferencia',
    stateNotVerified: 'Aún sin verificar', stateAssisted: 'Completado con ayudas', stateIndependent: 'Independiente', stateRepeatVerified: 'Verificado repetidamente', stateNeedsReview: 'Necesita repaso',
    close: 'Cerrar',
    statusActive: 'En curso', statusPending: 'Pendiente', statusCompleted: 'Completada', statusNeedsReview: 'Necesita repaso', statusSkipped: 'Omitida', statusDraft: 'Borrador',
  },
  'fr-FR': {
    practiceAnswerLabel: 'Votre réponse',
    practiceAnswerPlaceholder: 'Écrivez la réponse de ce tour dans la carte.',
    practiceSubmit: 'Envoyer la réponse',
    learning: 'Apprentissage', practice: 'Pratique', goal: 'Objectif actuel', duePractice: 'Pratique à faire',
    progress: 'Progression', history: 'Historique', newChat: 'Nouvelle conversation', startInChat: 'Commencer dans le chat',
    notRunning: 'Trainer ne tourne pas', notRunningDetail: 'Ouvrez Trainer dans VS Code, puis revenez ici.',
    reconnect: 'Reconnecter', openTrainer: 'Ouvrir Trainer', placeholder: 'Écrire à Trainer…',
    send: 'Envoyer', thinking: 'Réflexion…', connectionLost: 'La connexion a été perdue.',
    empty: 'Commencez ici : posez une question ou laissez Trainer poursuivre l’étape en cours.',
    practiceFallback: 'Pratique actuelle', practicePrompt: (title) => `Commencer la pratique : ${title}`,
    noGoal: 'Pas encore de plan formel.', noPractice: 'Rien à faire pour le moment.', noProgress: 'La progression apparaît après une pratique.',
    practiceRecorded: 'Cette pratique a été enregistrée.', practiceRecordFailed: "Cette pratique n'a pas été enregistrée. Réessayez dans Trainer.",
    progressUpdated: 'Progression mise à jour', evidenceCount: '{n} preuves', viewGrowth: 'Voir la progression',
    dimensionComprehension: 'Compréhension', dimensionImplementation: 'Implémentation', dimensionDebugging: 'Débogage', dimensionTransfer: 'Transfert',
    stateNotVerified: 'Pas encore vérifié', stateAssisted: 'Terminé avec aides', stateIndependent: 'Indépendant', stateRepeatVerified: 'Vérifié à plusieurs reprises', stateNeedsReview: 'À revoir',
    close: 'Fermer',
    statusActive: 'En cours', statusPending: 'En attente', statusCompleted: 'Terminée', statusNeedsReview: 'À revoir', statusSkipped: 'Ignorée', statusDraft: 'Brouillon',
  },
  'de-DE': {
    practiceAnswerLabel: 'Deine Antwort',
    practiceAnswerPlaceholder: 'Schreibe die Antwort dieser Runde in die Karte.',
    practiceSubmit: 'Antwort senden',
    learning: 'Lernen', practice: 'Übung', goal: 'Aktuelles Ziel', duePractice: 'Fällige Übung',
    progress: 'Fortschritt', history: 'Verlauf', newChat: 'Neuer Chat', startInChat: 'Im Chat starten',
    notRunning: 'Trainer läuft nicht', notRunningDetail: 'Öffne Trainer in VS Code und komm dann hierher zurück.',
    reconnect: 'Neu verbinden', openTrainer: 'Trainer öffnen', placeholder: 'Nachricht an Trainer…',
    send: 'Senden', thinking: 'Denkt nach…', connectionLost: 'Die Verbindung wurde getrennt.',
    empty: 'Starte hier: Stelle eine Frage oder lass Trainer den aktuellen Schritt fortsetzen.',
    practiceFallback: 'Aktuelle Übung', practicePrompt: (title) => `Übung starten: ${title}`,
    noGoal: 'Noch kein formeller Plan.', noPractice: 'Gerade nichts fällig.', noProgress: 'Fortschritt erscheint nach einer Übung.',
    practiceRecorded: 'Diese Übung wurde aufgezeichnet.', practiceRecordFailed: 'Diese Übung wurde nicht aufgezeichnet. Wiederhole sie in Trainer.',
    progressUpdated: 'Fortschritt aktualisiert', evidenceCount: '{n} Nachweise', viewGrowth: 'Fortschritt ansehen',
    dimensionComprehension: 'Verständnis', dimensionImplementation: 'Implementierung', dimensionDebugging: 'Fehlersuche', dimensionTransfer: 'Transfer',
    stateNotVerified: 'Noch nicht überprüft', stateAssisted: 'Mit Hinweisen abgeschlossen', stateIndependent: 'Selbstständig', stateRepeatVerified: 'Mehrfach überprüft', stateNeedsReview: 'Braucht Wiederholung',
    close: 'Schließen',
    statusActive: 'Aktiv', statusPending: 'Ausstehend', statusCompleted: 'Abgeschlossen', statusNeedsReview: 'Braucht Wiederholung', statusSkipped: 'Übersprungen', statusDraft: 'Entwurf',
  },
  'ja-JP': {
    practiceAnswerLabel: 'あなたの回答',
    practiceAnswerPlaceholder: 'この回の回答をカードに書きましょう。',
    practiceSubmit: '回答を送信',
    learning: '学習', practice: '練習', goal: '現在の目標', duePractice: '期限の練習',
    progress: '成長', history: '履歴', newChat: '新しい会話', startInChat: '会話で開始',
    notRunning: 'Trainer が起動していません', notRunningDetail: 'VS Code で Trainer を開いてから、ここに戻ってください。',
    reconnect: '再接続', openTrainer: 'Trainer を開く', placeholder: 'Trainer にメッセージ…',
    send: '送信', thinking: '考えています…', connectionLost: '接続が切れました。',
    empty: 'ここから始めましょう。質問するか、現在の学習ステップを続けてください。',
    practiceFallback: '現在の練習', practicePrompt: (title) => `練習を開始：${title}`,
    noGoal: '正式な計画はまだありません。', noPractice: '今は期限の練習がありません。', noProgress: '練習を1回終えると進捗が表示されます。',
    practiceRecorded: 'この練習を記録しました。', practiceRecordFailed: 'この練習は記録されませんでした。Trainer でやり直してください。',
    progressUpdated: '進捗を更新しました', evidenceCount: '{n} 件の証拠', viewGrowth: '成長を見る',
    dimensionComprehension: '理解', dimensionImplementation: '実装', dimensionDebugging: 'デバッグ', dimensionTransfer: '転移',
    stateNotVerified: 'まだ検証なし', stateAssisted: 'ヒント付きで完了', stateIndependent: '自力で完了', stateRepeatVerified: '繰り返し検証済み', stateNeedsReview: '要復習',
    close: '閉じる',
    statusActive: '進行中', statusPending: '未開始', statusCompleted: '完了', statusNeedsReview: '要復習', statusSkipped: 'スキップ', statusDraft: '下書き',
  },
  'ko-KR': {
    practiceAnswerLabel: '내 답변',
    practiceAnswerPlaceholder: '이번 답변을 카드에 적으세요.',
    practiceSubmit: '답변 제출',
    learning: '학습', practice: '연습', goal: '현재 목표', duePractice: '예정된 연습',
    progress: '성장', history: '기록', newChat: '새 대화', startInChat: '대화에서 시작',
    notRunning: 'Trainer가 실행 중이 아닙니다', notRunningDetail: 'VS Code에서 Trainer를 연 뒤 여기로 돌아오세요.',
    reconnect: '다시 연결', openTrainer: 'Trainer 열기', placeholder: 'Trainer에게 메시지…',
    send: '보내기', thinking: '생각 중…', connectionLost: '연결이 끊겼습니다.',
    empty: '여기서 시작하세요. 질문하거나 Trainer가 현재 학습 단계를 이어가게 하세요.',
    practiceFallback: '현재 연습', practicePrompt: (title) => `연습 시작: ${title}`,
    noGoal: '아직 공식 계획이 없습니다.', noPractice: '지금은 예정된 연습이 없습니다.', noProgress: '연습을 한 번 마치면 진행 상황이 표시됩니다.',
    practiceRecorded: '이번 연습이 기록되었습니다.', practiceRecordFailed: '이번 연습이 기록되지 않았습니다. Trainer에서 다시 시도하세요.',
    progressUpdated: '진행 상황이 업데이트되었습니다', evidenceCount: '증거 {n}개', viewGrowth: '성장 보기',
    dimensionComprehension: '이해', dimensionImplementation: '구현', dimensionDebugging: '디버깅', dimensionTransfer: '전이',
    stateNotVerified: '아직 검증 안 됨', stateAssisted: '힌트로 완료', stateIndependent: '독립 완료', stateRepeatVerified: '반복 검증됨', stateNeedsReview: '복습 필요',
    close: '닫기',
    statusActive: '진행 중', statusPending: '대기 중', statusCompleted: '완료', statusNeedsReview: '복습 필요', statusSkipped: '건너뜀', statusDraft: '초안',
  },
  'pt-BR': {
    practiceAnswerLabel: 'Sua resposta',
    practiceAnswerPlaceholder: 'Escreva a resposta desta rodada no cartão.',
    practiceSubmit: 'Enviar resposta',
    learning: 'Aprendizado', practice: 'Prática', goal: 'Objetivo atual', duePractice: 'Prática pendente',
    progress: 'Progresso', history: 'Histórico', newChat: 'Nova conversa', startInChat: 'Começar no chat',
    notRunning: 'O Trainer não está em execução', notRunningDetail: 'Abra o Trainer no VS Code e volte aqui.',
    reconnect: 'Reconectar', openTrainer: 'Abrir Trainer', placeholder: 'Mensagem para o Trainer…',
    send: 'Enviar', thinking: 'Pensando…', connectionLost: 'A conexão foi perdida.',
    empty: 'Comece aqui: faça uma pergunta ou deixe o Trainer continuar o passo atual.',
    practiceFallback: 'Prática atual', practicePrompt: (title) => `Começar prática: ${title}`,
    noGoal: 'Ainda não há um plano formal.', noPractice: 'Nada pendente agora.', noProgress: 'O progresso aparece após uma prática.',
    practiceRecorded: 'Esta prática foi registrada.', practiceRecordFailed: 'Esta prática não foi registrada. Repita no Trainer.',
    progressUpdated: 'Progresso atualizado', evidenceCount: '{n} evidências', viewGrowth: 'Ver progresso',
    dimensionComprehension: 'Compreensão', dimensionImplementation: 'Implementação', dimensionDebugging: 'Depuração', dimensionTransfer: 'Transferência',
    stateNotVerified: 'Ainda não verificado', stateAssisted: 'Concluído com dicas', stateIndependent: 'Independente', stateRepeatVerified: 'Verificado repetidamente', stateNeedsReview: 'Precisa de revisão',
    close: 'Fechar',
    statusActive: 'Em andamento', statusPending: 'Pendente', statusCompleted: 'Concluída', statusNeedsReview: 'Precisa de revisão', statusSkipped: 'Ignorada', statusDraft: 'Rascunho',
  },
};

/** The capability dimensions the panel reports, with their copy keys. */
const CAPABILITY_DIMENSIONS = {
  comprehension: 'dimensionComprehension',
  implementation: 'dimensionImplementation',
  debugging: 'dimensionDebugging',
  transfer: 'dimensionTransfer',
};

/** The capability band text, in the panel's language. */
const CAPABILITY_STATES = {
  not_verified: 'stateNotVerified',
  assisted: 'stateAssisted',
  independent: 'stateIndependent',
  repeat_verified: 'stateRepeatVerified',
  needs_review: 'stateNeedsReview',
};

function capabilityStateLabel(value) {
  const key = String(value || '').trim();
  const labelKey = CAPABILITY_STATES[key];
  return labelKey ? t(labelKey) : key.replace(/_/g, ' ');
}

const PRACTICE_STATUS_KEYS = {
  active: 'statusActive',
  in_progress: 'statusActive',
  ready: 'statusActive',
  due: 'statusActive',
  pending: 'statusPending',
  completed: 'statusCompleted',
  done: 'statusCompleted',
  passed: 'statusCompleted',
  needs_review: 'statusNeedsReview',
  skipped: 'statusSkipped',
  draft: 'statusDraft',
};

function practiceStatusLabel(raw) {
  const normalized = String(raw || '').trim().toLowerCase().replace(/[\s-]+/g, '_');
  const key = PRACTICE_STATUS_KEYS[normalized];
  if (key) return t(key);
  return normalized.replace(/_/g, ' ');
}

const language = T.copyFor(T.browserLocale()) ? T.resolveLanguageTag(T.browserLocale()) : 'en';
const copy = CHAT_COPY[T.browserLocale()] || CHAT_COPY['en-US'];
const responseLanguage = Object.keys(CHAT_COPY).find((key) => key === T.browserLocale()) || 'en-US';

const elements = {
  workspaceName: document.getElementById('workspace-name'),
  pageContext: document.getElementById('page-context'),
  connectionDot: document.getElementById('connection-dot'),
  connectionState: document.getElementById('connection-state'),
  connectionTitle: document.getElementById('connection-title'),
  connectionDetail: document.getElementById('connection-detail'),
  connectionRetry: document.getElementById('connection-retry'),
  connectionOpen: document.getElementById('connection-open'),
  conversation: document.getElementById('conversation'),
  practiceCard: document.getElementById('practice-card'),
  practiceTitle: document.getElementById('practice-title'),
  practiceFocus: document.getElementById('practice-focus'),
  practiceNotice: document.getElementById('practice-notice'),
  practiceStatus: document.getElementById('practice-status'),
  practiceStart: document.getElementById('practice-start'),
  practiceAnswerLabel: document.getElementById('practice-answer-label'),
  practiceAnswer: document.getElementById('practice-answer'),
  practiceSubmit: document.getElementById('practice-submit'),
  composer: document.getElementById('composer'),
  input: document.getElementById('message-input'),
  send: document.getElementById('send'),
  status: document.getElementById('composer-status'),
  learningStrip: document.getElementById('learning-strip'),
  learningStripTitle: document.getElementById('learning-strip-title'),
  learningStripDue: document.getElementById('learning-strip-due'),
  learningToggle: document.getElementById('learning-toggle'),
  historyToggle: document.getElementById('history-toggle'),
  openTrainer: document.getElementById('open-trainer'),
  historyOverlay: document.getElementById('history-overlay'),
  historyList: document.getElementById('history-list'),
  newChat: document.getElementById('new-chat'),
  learningOverlay: document.getElementById('learning-overlay'),
  learningGoalTitle: document.getElementById('learning-goal-title'),
  learningGoalStep: document.getElementById('learning-goal-step'),
  learningPracticeDetail: document.getElementById('learning-practice-detail'),
  learningProgress: document.getElementById('learning-progress'),
};

const state = {
  auth: null,
  sessionId: '',
  snapshot: null,
  messages: [],
  streaming: false,
  streamId: '',
  page: null,
  history: [],
  connected: false,
  busy: false,
  /** The live card the practice panel is answering. */
  practiceCardId: '',
  /** Last card whose answer was recorded in this sidepanel session. */
  recordedCardId: '',
  practiceFocus: '',
  practiceNotice: '',
  /** The progress receipt a recorded practice leaves in the conversation. */
  receipt: null,
};

function t(key, values) {
  const value = copy[key] ?? CHAT_COPY['en-US'][key] ?? '';
  return typeof value === 'function' ? value(values) : String(value).replace(/\{(\w+)\}/g, (_, name) => String(values?.[name] ?? ''));
}

function applyCopy() {
  document.documentElement.lang = language;
  document.title = 'Trainer';
  for (const node of document.querySelectorAll('[data-copy]')) {
    const key = node.getAttribute('data-copy');
    if (key && copy[key] && typeof copy[key] === 'string') node.textContent = t(key);
  }
  elements.input.placeholder = t('placeholder');
  elements.input.setAttribute('aria-label', t('placeholder'));
  elements.send.setAttribute('aria-label', t('send'));
  elements.send.title = t('send');
  elements.connectionRetry.textContent = t('reconnect');
  elements.connectionOpen.textContent = t('openTrainer');
  elements.practiceStart.textContent = t('startInChat');
  elements.practiceSubmit.textContent = t('practiceSubmit');
  elements.practiceAnswer.placeholder = t('practiceAnswerPlaceholder');
  elements.practiceAnswer.setAttribute('aria-label', t('practiceAnswerLabel'));
  elements.practiceCard.setAttribute('aria-label', t('practiceFallback'));
  elements.learningToggle.setAttribute('aria-label', t('learning'));
  elements.learningToggle.title = t('learning');
  elements.historyToggle.setAttribute('aria-label', t('history'));
  elements.historyToggle.title = t('history');
  elements.openTrainer.setAttribute('aria-label', t('openTrainer'));
  elements.openTrainer.title = t('openTrainer');
  elements.historyOverlay.querySelector('.overlay__panel')?.setAttribute('aria-label', t('history'));
  elements.learningOverlay.querySelector('.overlay__panel')?.setAttribute('aria-label', t('learning'));
  for (const closeButton of document.querySelectorAll('[data-close]')) {
    closeButton.setAttribute('aria-label', t('close'));
  }
  elements.newChat.textContent = t('newChat');
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function inlineMarkdown(value) {
  return value
    .replace(/`([^`\n]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[\s(])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
}

/** Small, safe Markdown renderer: escape first, then structure. */
function renderMarkdown(value) {
  const text = String(value || '').replace(/\r\n/g, '\n');
  if (!text.trim()) return '';
  const blocks = text.split(/\n{2,}/);
  const html = [];
  for (const block of blocks) {
    if (block.startsWith('```')) {
      const lines = block.split('\n');
      const code = lines.slice(1, lines[lines.length - 1] === '```' ? -1 : undefined).join('\n');
      html.push(`<pre><code>${escapeHtml(code)}</code></pre>`);
      continue;
    }
    const escaped = escapeHtml(block);
    const lines = escaped.split('\n');
    if (lines.every((line) => /^\s*[-*]\s+/.test(line))) {
      html.push(`<ul>${lines.map((line) => `<li>${inlineMarkdown(line.replace(/^\s*[-*]\s+/, ''))}</li>`).join('')}</ul>`);
      continue;
    }
    if (lines.every((line) => /^\s*\d+\.\s+/.test(line))) {
      html.push(`<ol>${lines.map((line) => `<li>${inlineMarkdown(line.replace(/^\s*\d+\.\s+/, ''))}</li>`).join('')}</ol>`);
      continue;
    }
    const heading = escaped.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      const level = Math.min(heading[1].length, 3);
      html.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }
    if (escaped.startsWith('>')) {
      html.push(`<blockquote>${inlineMarkdown(escaped.replace(/^>\s?/gm, ''))}</blockquote>`);
      continue;
    }
    html.push(`<p>${inlineMarkdown(escaped).replace(/\n/g, '<br>')}</p>`);
  }
  return html.join('');
}

function pick(source, ...keys) {
  if (!source || typeof source !== 'object') return undefined;
  for (const key of keys) {
    if (source[key] !== undefined && source[key] !== null) return source[key];
  }
  return undefined;
}

function normalizeMessages(snapshot) {
  const raw = pick(snapshot, 'messages') || [];
  return raw
    .filter((message) => message && typeof message === 'object')
    .map((message) => ({
      id: String(pick(message, 'id', 'message_id') || ''),
      role: String(pick(message, 'role') || 'assistant'),
      body: String(pick(message, 'body', 'content') || ''),
      timestamp: String(pick(message, 'timestamp', 'created_at') || ''),
      source: String(pick(message, 'contextNote', 'context_note') || ''),
      sourceResourceIds: pick(message, 'sourceResourceIds', 'source_resource_ids') || [],
    }));
}

function resourceTitle(id) {
  const resources = pick(state.snapshot || {}, 'resources') || [];
  return resources.find((resource) => String(resource.id) === String(id))?.title || '';
}

function messageSource(message) {
  const parts = [];
  if (message.source) parts.push(message.source);
  const ids = Array.isArray(message.sourceResourceIds) ? message.sourceResourceIds : [];
  for (const id of ids) {
    const title = resourceTitle(id);
    if (title) parts.push(title);
  }
  return [...new Set(parts)].join(' · ');
}

function isNearBottom() {
  const node = elements.conversation;
  return node.scrollHeight - node.scrollTop - node.clientHeight < 80;
}

function scrollToBottom(force = false) {
  if (!force && !isNearBottom()) return;
  elements.conversation.scrollTop = elements.conversation.scrollHeight;
}

function renderConversation() {
  const conversation = elements.conversation;
  const shouldStick = isNearBottom();
  conversation.textContent = '';
  if (!state.messages.length) {
    const empty = document.createElement('p');
    empty.className = 'conversation__empty';
    empty.textContent = t('empty');
    conversation.appendChild(empty);
  } else {
    for (const message of state.messages) {
      const item = document.createElement('article');
      item.className = `message message--${message.role === 'user' ? 'user' : 'assistant'}`;
      item.dataset.messageId = message.id;
      const role = document.createElement('span');
      role.className = 'message__role';
      role.textContent = message.role === 'user' ? 'You' : 'Trainer';
      const bubble = document.createElement('div');
      bubble.className = 'message__bubble';
      if (message.role === 'user') {
        bubble.textContent = message.body;
      } else {
        bubble.innerHTML = renderMarkdown(message.body);
        if (!message.body) {
          const typing = document.createElement('span');
          typing.className = 'typing';
          typing.innerHTML = '<span></span><span></span><span></span>';
          bubble.appendChild(typing);
        }
      }
      item.appendChild(role);
      item.appendChild(bubble);
      const source = messageSource(message);
      if (source) {
        const note = document.createElement('span');
        note.className = 'message__source';
        note.textContent = source;
        item.appendChild(note);
      }
      conversation.appendChild(item);
    }
  }
  if (state.receipt) {
    conversation.appendChild(renderProgressReceipt(state.receipt));
  }
  scrollToBottom(shouldStick || state.streaming);
}

/**
 * The progress receipt a recorded practice leaves in the conversation: the
 * dimensions that now carry evidence, and one action that opens the growth
 * detail. It never repeats the whole growth view.
 */
function renderProgressReceipt(receipt) {
  const item = document.createElement('article');
  item.className = 'progress-receipt';
  item.dataset.progressReceipt = 'true';
  const header = document.createElement('header');
  header.className = 'progress-receipt__header';
  const title = document.createElement('strong');
  title.textContent = t('progressUpdated');
  const evidence = document.createElement('span');
  evidence.textContent = t('evidenceCount', { n: String(receipt.evidenceCount) });
  header.append(title, evidence);
  const rows = document.createElement('ul');
  rows.className = 'progress-receipt__rows';
  for (const row of receipt.rows) {
    const li = document.createElement('li');
    const label = document.createElement('span');
    label.textContent = row.label;
    const value = document.createElement('strong');
    value.textContent = row.state;
    li.append(label, value);
    rows.appendChild(li);
  }
  const action = document.createElement('button');
  action.className = 'text-button progress-receipt__open';
  action.type = 'button';
  action.textContent = t('viewGrowth');
  action.onclick = () => {
    setOverlay('learning', true);
  };
  item.append(header, rows, action);
  return item;
}

function updateStreamingBubble() {
  const bubble = elements.conversation.querySelector('.message--assistant:last-of-type .message__bubble');
  if (bubble) {
    bubble.innerHTML = renderMarkdown(state.messages[state.messages.length - 1]?.body || '');
  }
  scrollToBottom(state.streaming);
}

function planInfo() {
  const snapshot = state.snapshot || {};
  const plan = pick(snapshot, 'plan') || {};
  const training = pick(snapshot, 'workspaceTrainingState', 'workspace_training_state') || {};
  const title = String(pick(plan, 'title', 'summary') || '').trim();
  const step = String(
    pick(plan, 'currentStep', 'current_step') ||
    pick(training, 'latestLearningFocusArea', 'latest_learning_focus_area') ||
    ''
  ).trim();
  const cardTitle = String(pick(training, 'selectedCardTitle', 'selected_card_title') || '').trim();
  const due = Array.isArray(pick(snapshot.memory || {}, 'reviews'))
    ? pick(snapshot.memory || {}, 'reviews').length
    : Array.isArray(pick(snapshot, 'reviewQueue', 'review_queue'))
      ? pick(snapshot, 'reviewQueue', 'review_queue').length
      : 0;
  return { title, step, cardTitle, due, training };
}

function renderLearning() {
  const { title, step, cardTitle, due } = planInfo();
  const stripTitle = step || cardTitle || title;
  elements.learningStrip.hidden = !stripTitle && due <= 0;
  elements.learningStripTitle.textContent = stripTitle || '';
  elements.learningStripDue.textContent = due > 0 ? t('duePractice').replace('{n}', String(due)) : '';
  elements.learningGoalTitle.textContent = title || (cardTitle ? cardTitle : t('noGoal'));
  elements.learningGoalStep.textContent = step || '';
  elements.learningPracticeDetail.textContent = cardTitle
    ? `${cardTitle}`
    : due > 0
      ? t('duePractice').replace('{n}', String(due))
      : t('noPractice');
  const projection = pick(planInfo().training, 'skillProjection', 'skill_projection') || {};
  const dimensions = pick(projection, 'dimensions') || {};
  elements.learningProgress.textContent = '';
  const rows = Object.entries(CAPABILITY_DIMENSIONS)
    .map(([key, labelKey]) => {
      const value = dimensions[key];
      if (!value) return null;
      return { label: t(labelKey), state: capabilityStateLabel(value.state), count: Number(value.verifiedCount || value.verified_count || 0) };
    })
    .filter(Boolean);
  for (const row of rows) {
    const li = document.createElement('li');
    const label = document.createElement('span');
    label.textContent = row.label;
    const value = document.createElement('strong');
    value.textContent = row.count > 0 ? `${row.state} · ${row.count}` : row.state;
    li.append(label, value);
    elements.learningProgress.appendChild(li);
  }
  if (!rows.length) {
    const li = document.createElement('li');
    li.className = 'learning-section__detail';
    li.textContent = t('noProgress');
    elements.learningProgress.appendChild(li);
  }
}

function renderPractice() {
  const { training, cardTitle } = planInfo();
  const title = cardTitle || String(pick(training, 'latestTrainingNextHop.title', 'latest_training_next_hop.title') || '').trim();
  const cardId = String(pick(training, 'selectedCardId', 'selected_card_id') || '').trim();
  state.practiceCardId = cardId;
  if (cardId && state.recordedCardId && cardId !== state.recordedCardId) {
    state.recordedCardId = '';
  }
  if (!title) {
    elements.practiceCard.hidden = true;
    return;
  }
  elements.practiceCard.hidden = false;
  elements.practiceTitle.textContent = title;
  const focus = String(
    pick(training, 'latestLearningFocusArea', 'latest_learning_focus_area') ||
    pick(training, 'selectedCardType', 'selected_card_type') ||
    ''
  ).trim();
  state.practiceFocus = focus;
  elements.practiceFocus.textContent = focus;
  elements.practiceNotice.textContent = state.practiceNotice;
  elements.practiceNotice.hidden = !state.practiceNotice;
  const rawStatus = pick(training, 'selectedCardStatus', 'selected_card_status') || '';
  elements.practiceStatus.textContent = practiceStatusLabel(rawStatus);
  const settled = Boolean(cardId && state.recordedCardId === cardId);
  if (elements.practiceAnswerLabel) {
    elements.practiceAnswerLabel.hidden = settled;
  }
  elements.practiceAnswer.hidden = settled;
  elements.practiceSubmit.hidden = settled;
  elements.practiceStart.disabled = state.busy;
  elements.practiceStart.onclick = () => {
    void sendMessage(t('practicePrompt', title));
  };
  // The practice card owns its answer: typing and submitting happen in the
  // panel, not in the generic chat box. The submitted turn stays a coaching
  // turn, so the transcript records what the learner actually wrote.
  elements.practiceSubmit.disabled = state.busy || settled;
  elements.practiceSubmit.onclick = () => {
    if (settled) return;
    const answer = String(elements.practiceAnswer.value || '').trim();
    if (!answer || state.busy) return;
    elements.practiceAnswer.value = '';
    void answerPractice(answer, title);
  };
}

/**
 * A practice answered in this panel is a real attempt.
 *
 * The answer travels the same server chain the workbench uses: the attempt
 * starts, the draft is recorded, and the practice return closes it. The server
 * owns the evidence trust level (a learner return is never host-verified) and
 * the workspace the result lands in, so the panel cannot claim a completion
 * it did not record. Only then does the answer also enter the conversation as
 * a coaching turn.
 */
async function answerPractice(answer, title) {
  const recorded = await recordPracticeAnswer(answer);
  if (!recorded) {
    renderPractice();
    return;
  }
  await sendMessage(`${title}\n\n${answer}`);
}

/**
 * Record the learner's answer through the training chain.
 *
 * @returns {Promise<boolean>} whether the practice was recorded.
 */
async function recordPracticeAnswer(answer) {
  const cardId = state.practiceCardId;
  if (!cardId || !state.auth) {
    state.practiceNotice = t('practiceRecordFailed');
    return false;
  }
  state.busy = true;
  state.practiceNotice = '';
  updateComposerState();
  renderPractice();
  try {
    let attemptId = '';
    try {
      const started = await postTraining('/training/attempt/start', { card_id: cardId });
      attemptId = String(pick(started?.attempt || {}, 'attempt_id', 'attemptId') || '');
    } catch (error) {
      // The attempt carries the in-flight draft; the practice return below is
      // the authoritative completion, so it still runs.
      console.warn('Trainer browser practice attempt start failed', error);
    }
    if (attemptId) {
      try {
        await postTraining('/training/attempt/update', {
          attempt_id: attemptId,
          answer_draft: answer,
        });
      } catch (error) {
        console.warn('Trainer browser practice attempt update failed', error);
      }
      try {
        // The evidence binds to what the learner actually wrote. The server
        // decides the trust level: a learner return is never host-verified, so
        // it shows up in the drilldown without attesting executable capability.
        await postTraining('/training/attempt/evidence', {
          attempt_id: attemptId,
          artifact_hash: await answerArtifactHash(answer),
          result: 'passed',
          runner_version: 'trainer-browser-panel',
          execution_location: 'browser_panel',
          limitations: ['learner_self_report'],
        });
      } catch (error) {
        console.warn('Trainer browser practice evidence failed', error);
      }
    }
    await postTraining('/training/practice-return', {
      card_id: cardId,
      passed: true,
      summary: answer,
      next_step: '',
      focus_area: state.practiceFocus,
      evidence_source: 'learner_return',
    });
    state.practiceNotice = t('practiceRecorded');
    state.recordedCardId = cardId;
    await bootstrap(state.sessionId);
    state.receipt = receiptFromSnapshot();
    renderConversation();
    return true;
  } catch (error) {
    state.practiceNotice = t('practiceRecordFailed');
    console.warn('Trainer browser practice return failed', error);
    return false;
  } finally {
    state.busy = false;
    updateComposerState();
    renderPractice();
  }
}

/** One training request to the paired sidecar. */
async function postTraining(path, body) {
  if (!state.auth) {
    throw new Error('Trainer is not connected.');
  }
  const response = await fetch(`${state.auth.baseUrl}/browser/chat${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${state.auth.credential}`,
    },
    body: JSON.stringify(body || {}),
    cache: 'no-store',
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => '');
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return await response.json();
}

/**
 * The progress receipt a recorded practice leaves behind: the dimensions that
 * now carry evidence, and nothing else. It is a receipt, not a page — the
 * growth detail stays in the learning overlay.
 */
function receiptFromSnapshot() {
  const projection = pick(planInfo().training, 'skillProjection', 'skill_projection') || {};
  const dimensions = pick(projection, 'dimensions') || {};
  const rows = Object.entries(CAPABILITY_DIMENSIONS)
    .map(([key, labelKey]) => {
      const value = dimensions[key];
      if (!value) return null;
      const count = Number(value.verifiedCount || value.verified_count || 0);
      if (count <= 0) return null;
      return { label: t(labelKey), state: capabilityStateLabel(value.state), count };
    })
    .filter(Boolean);
  if (!rows.length) {
    return null;
  }
  return {
    rows,
    evidenceCount: rows.reduce((total, row) => total + row.count, 0),
  };
}

/**
 * The artifact the evidence binds to: the learner's own answer.
 *
 * The panel has no runner and no verifier, so the honest binding is the text
 * the learner wrote. The server still decides the trust level — a self report
 * is never host-verified.
 */
async function answerArtifactHash(answer) {
  const bytes = new TextEncoder().encode(String(answer || ''));
  try {
    const digest = await crypto.subtle.digest('SHA-256', bytes);
    return Array.from(new Uint8Array(digest))
      .map((byte) => byte.toString(16).padStart(2, '0'))
      .join('');
  } catch (_error) {
    // A weak fallback still binds the evidence to this answer.
    let hash = 0;
    for (const byte of bytes) {
      hash = (hash * 31 + byte) >>> 0;
    }
    return `learner-answer-${hash.toString(16)}`;
  }
}

function renderAll() {
  elements.workspaceName.textContent = state.auth?.workspaceName || state.auth?.workspaceId || 'Trainer';
  elements.connectionDot.dataset.state = state.connected ? 'online' : 'offline';
  elements.pageContext.textContent = state.page?.title || state.page?.url || '';
  renderConversation();
  renderLearning();
  renderPractice();
  updateComposerState();
}

function updateComposerState() {
  const canSend = Boolean(state.auth && state.sessionId && !state.busy && elements.input.value.trim());
  elements.send.disabled = !canSend;
  elements.status.textContent = state.streaming ? t('thinking') : '';
}

async function sendMessage(text) {
  const message = String(text || '').trim();
  if (!message || state.busy || !state.auth || !state.sessionId) return;
  state.busy = true;
  state.streaming = true;
  state.streamId = `browser-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const now = new Date().toISOString();
  state.messages.push({ id: `local-user-${Date.now()}`, role: 'user', body: message, timestamp: now, source: '', sourceResourceIds: [] });
  state.messages.push({ id: state.streamId, role: 'assistant', body: '', timestamp: now, source: '', sourceResourceIds: [] });
  elements.input.value = '';
  elements.input.style.height = '';
  updateComposerState();
  renderConversation();
  scrollToBottom(true);

  const body = {
    session_id: state.sessionId,
    message,
    active_view: 'coach',
    stream: true,
    stream_id: state.streamId,
    request_id: `browser-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
    response_language: responseLanguage,
    page_context: state.page || undefined,
  };

  try {
    const response = await fetch(`${state.auth.baseUrl}/browser/chat/message/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        Authorization: `Bearer ${state.auth.credential}`,
      },
      body: JSON.stringify(body),
      cache: 'no-store',
    });
    if (!response.ok || !response.body) {
      const detail = await response.text().catch(() => '');
      throw new Error(detail || `HTTP ${response.status}`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';
    let completed = false;
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary;
      while ((boundary = buffer.indexOf('\n\n')) >= 0) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        let event = 'message';
        let data = '';
        for (const line of frame.split('\n')) {
          if (line.startsWith('event:')) event = line.slice(6).trim();
          else if (line.startsWith('data:')) data += line.slice(5).trim();
        }
        if (!data) continue;
        let payload;
        try { payload = JSON.parse(data); } catch (_error) { continue; }
        if (typeof payload.chunk === 'string') {
          state.messages[state.messages.length - 1].body += payload.chunk;
          updateStreamingBubble();
        } else if (event === 'complete' || payload.response) {
          completed = true;
          const reply = payload.response?.reply?.content || payload.response?.reply?.body;
          if (typeof reply === 'string' && reply.trim()) {
            state.messages[state.messages.length - 1].body = reply;
          }
        } else if (payload.type === 'error') {
          throw new Error(String(payload.message || payload.detail || 'Stream failed.'));
        } else if (payload.type === 'tool_call' || payload.type === 'step') {
          elements.status.textContent = String(payload.name || payload.title || t('thinking'));
        }
      }
    }
    if (!state.messages[state.messages.length - 1].body.trim()) {
      await bootstrap(state.sessionId);
    } else if (completed) {
      await bootstrap(state.sessionId);
    }
  } catch (error) {
    const last = state.messages[state.messages.length - 1];
    if (last && last.role === 'assistant' && !last.body.trim()) {
      last.body = t('connectionLost');
    }
    elements.status.textContent = t('connectionLost');
    console.warn('Trainer browser chat stream failed', error);
  } finally {
    state.busy = false;
    state.streaming = false;
    state.streamId = '';
    updateComposerState();
    renderConversation();
  }
}

async function fetchSessionList() {
  if (!state.auth) return [];
  const response = await fetch(`${state.auth.baseUrl}/browser/chat/sessions`, {
    headers: { Authorization: `Bearer ${state.auth.credential}` },
    cache: 'no-store',
  });
  if (!response.ok) return [];
  const body = await response.json().catch(() => []);
  return Array.isArray(body) ? body : [];
}

async function renderHistory() {
  elements.historyList.textContent = '';
  elements.historyList.appendChild(Object.assign(document.createElement('p'), {
    className: 'learning-section__detail',
    textContent: state.connected ? '' : t('connectionLost'),
  }));
  state.history = await fetchSessionList();
  elements.historyList.textContent = '';
  for (const item of state.history) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'history-row';
    button.setAttribute('aria-current', item.session_id === state.sessionId ? 'true' : 'false');
    const title = document.createElement('strong');
    title.textContent = String(item.summary || item.title || item.session_id || '').slice(0, 120);
    const meta = document.createElement('span');
    meta.textContent = [item.message_count ? `${item.message_count}` : '', item.updated_at || ''].filter(Boolean).join(' · ');
    button.append(title, meta);
    button.addEventListener('click', () => {
      closeOverlays();
      void bootstrap(String(item.session_id || ''));
    });
    elements.historyList.appendChild(button);
  }
}

function setOverlay(name, open) {
  const overlay = name === 'history' ? elements.historyOverlay : elements.learningOverlay;
  overlay.hidden = !open;
  const toggle = name === 'history' ? elements.historyToggle : elements.learningToggle;
  toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
  if (open) {
    if (name === 'history') void renderHistory();
    const close = overlay.querySelector('[data-close]');
    close?.focus();
  } else {
    toggle.focus();
  }
}

function closeOverlays() {
  elements.historyOverlay.hidden = true;
  elements.learningOverlay.hidden = true;
  elements.historyToggle.setAttribute('aria-expanded', 'false');
  elements.learningToggle.setAttribute('aria-expanded', 'false');
}

async function readActiveTab() {
  try {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    const tab = tabs && tabs[0];
    if (!tab || !T.httpUrlOnly(tab.url || '')) {
      state.page = null;
      return;
    }
    state.page = { url: String(tab.url), title: String(tab.title || tab.url) };
  } catch (_error) {
    state.page = null;
  }
}

async function connect() {
  elements.connectionState.hidden = true;
  state.connected = false;
  renderAll();
  let auth = await T.loadAuth();
  if (!auth.credential || !auth.baseUrl) {
    await new Promise((resolve) => chrome.runtime.sendMessage({ type: 'trainer:auto-pair' }, () => resolve()));
    auth = await T.loadAuth();
  }
  if (!auth.credential || !auth.baseUrl) {
    showConnectionState();
    return;
  }
  state.auth = auth;
  const snapshotState = await new Promise((resolve) => {
    chrome.runtime.sendMessage({ type: 'trainer:state' }, (value) => resolve(value || {}));
  });
  state.auth.workspaceName = snapshotState.workspaceName || auth.workspaceName || auth.workspaceId;
  await bootstrap(await loadStoredSession());
}

async function bootstrap(sessionId) {
  if (!state.auth) return;
  const params = new URLSearchParams();
  if (sessionId) params.set('session_id', sessionId);
  params.set('workspace_name', state.auth.workspaceName || '');
  try {
    const response = await fetch(`${state.auth.baseUrl}/browser/chat/bootstrap?${params}`, {
      headers: { Authorization: `Bearer ${state.auth.credential}` },
      cache: 'no-store',
    });
    if (response.status === 401) {
      showConnectionState();
      return;
    }
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const snapshot = await response.json();
    state.snapshot = snapshot;
    state.sessionId = String(snapshot.session_id || snapshot.sessionId || sessionId || '');
    state.messages = normalizeMessages(snapshot);
    state.connected = true;
    await saveStoredSession(state.sessionId);
    elements.connectionState.hidden = true;
    elements.composer.hidden = false;
    renderAll();
    scrollToBottom(true);
  } catch (_error) {
    showConnectionState();
  }
}

function showConnectionState() {
  state.connected = false;
  elements.connectionState.hidden = false;
  elements.connectionTitle.textContent = t('notRunning');
  elements.connectionDetail.textContent = t('notRunningDetail');
  elements.connectionDot.dataset.state = 'offline';
  elements.composer.hidden = true;
  elements.practiceCard.hidden = true;
  elements.learningStrip.hidden = true;
}

async function saveStoredSession(sessionId) {
  try {
    await chrome.storage.local.set({ 'trainer.sidepanel.session': String(sessionId || '') });
  } catch (_error) { /* storage is best-effort */ }
}

async function loadStoredSession() {
  try {
    const stored = await chrome.storage.local.get({ 'trainer.sidepanel.session': '' });
    return String(stored['trainer.sidepanel.session'] || '');
  } catch (_error) {
    return '';
  }
}

function openTrainer() {
  void chrome.runtime.sendMessage({ type: 'trainer:open', url: `${T.HOST_DEEP_LINK}coach` });
}

elements.composer.addEventListener('submit', (event) => {
  event.preventDefault();
  void sendMessage(elements.input.value);
});
elements.input.addEventListener('input', () => {
  elements.input.style.height = 'auto';
  elements.input.style.height = `${Math.min(elements.input.scrollHeight, 160)}px`;
  updateComposerState();
});
elements.input.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    void sendMessage(elements.input.value);
  }
});
elements.learningToggle.addEventListener('click', () => setOverlay('learning', elements.learningOverlay.hidden));
elements.historyToggle.addEventListener('click', () => setOverlay('history', elements.historyOverlay.hidden));
elements.learningStrip.addEventListener('click', () => setOverlay('learning', true));
elements.openTrainer.addEventListener('click', openTrainer);
elements.connectionOpen.addEventListener('click', openTrainer);
elements.connectionRetry.addEventListener('click', () => { void connect(); });
elements.newChat.addEventListener('click', () => {
  closeOverlays();
  state.sessionId = '';
  state.snapshot = null;
  state.messages = [];
  void bootstrap('');
});
for (const button of document.querySelectorAll('[data-close]')) {
  button.addEventListener('click', closeOverlays);
}
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') closeOverlays();
});
chrome.tabs.onActivated.addListener(() => { void readActiveTab().then(renderAll); });
chrome.tabs.onUpdated.addListener((_tabId, change, tab) => {
  if (tab.active && (change.url || change.title)) void readActiveTab().then(renderAll);
});

async function init() {
  applyCopy();
  await readActiveTab();
  await connect();
  window.setInterval(() => {
    if (!state.connected) {
      void chrome.runtime.sendMessage({ type: 'trainer:auto-pair' }, async () => {
        const auth = await T.loadAuth();
        if (auth.credential && auth.baseUrl) {
          state.auth = auth;
          await connect();
        }
      });
    }
  }, 5000);
}

document.addEventListener('DOMContentLoaded', () => { void init(); });
