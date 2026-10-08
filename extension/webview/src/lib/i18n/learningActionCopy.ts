import type { ComposerLanguage } from "../types";

interface LearningActionCopy {
  workspaceTitle: string; workspaceLabel: string; workspaceDetail: string;
  providerTitle: string; providerLabel: string; providerDetail: string;
  recoveringTitle: string; recoveringLabel: string; recoveringDetail: string;
  staleTitle: string; staleLabel: string; staleDetail: string;
  frozenTitle: string; frozenLabel: string; frozenDetail: string;
  blockerTitle: string; blockerLabel: string;
  evidenceTitle: string; verifiedEvidenceTitle: string; evidenceLabel: string; evidenceDetail: string;
  continueLabel: string; continueDetail: string;
  practiceTitle: string; practiceLabel: string; practiceDetail: string;
  returnTitle: string; returnLabel: string; returnDetail: string;
  reviewTitle: string; reviewLabel: string; reviewDetail: string;
  completedTitle: string; completedLabel: string; completedDetail: string;
  generateTitle: string; generateLabel: string; generateDetail: string;
  restoreTitle: string; restoreLabel: string; restoreDetail: string;
  directLabel: string; directDetail: string;
  complete: string;
}

/** Product copy belongs to the action, never a language branch in a view. */
const copies: Record<ComposerLanguage, LearningActionCopy> = {
  "zh-CN": {
    workspaceTitle: "先选择学习工作区", workspaceLabel: "选择工作区", workspaceDetail: "确认当前项目后，再继续学习。",
    providerTitle: "先连接教练模型", providerLabel: "设置模型", providerDetail: "连接可用模型后，继续当前学习。",
    recoveringTitle: "正在恢复当前学习", recoveringLabel: "恢复中…", recoveringDetail: "恢复完成后会显示当前工作区的下一步。",
    staleTitle: "需要刷新学习状态", staleLabel: "刷新状态", staleDetail: "当前状态尚未确认，刷新后再继续。",
    frozenTitle: "计划已暂停", frozenLabel: "恢复计划", frozenDetail: "恢复后继续当前步骤，不会创建新的计划。",
    blockerTitle: "先解决当前阻塞", blockerLabel: "与教练解决阻塞",
    evidenceTitle: "确认当前步骤的证据", verifiedEvidenceTitle: "确认这次验证结果", evidenceLabel: "确认采用这条证据", evidenceDetail: "确认前先核对结果；采用证据不会自动认定你已掌握。",
    continueLabel: "继续当前步骤", continueDetail: "完成当前步骤，再带真实结果回来核对。",
    practiceTitle: "当前练习进行中", practiceLabel: "继续练习", practiceDetail: "从上次停下的地方继续练习。",
    returnTitle: "完成练习复盘与回流", returnLabel: "完成练习回流", returnDetail: "先完成当前练习的复盘与回流，再开始下一项。",
    reviewTitle: "复习已到期", reviewLabel: "开始复习", reviewDetail: "回顾已学内容，检查现在能否独立完成。",
    completedTitle: "当前练习已完成", completedLabel: "回到教练", completedDetail: "带着本次结果继续对话，再决定下一步。",
    generateTitle: "确定你的学习目标", generateLabel: "制定学习计划", generateDetail: "先告诉教练你想学什么，再确认正式计划。",
    restoreTitle: "当前步骤尚未确认", restoreLabel: "与教练确认下一步", restoreDetail: "保留已有计划，先确认当前要做的事。",
    directLabel: "继续与教练学习", directDetail: "可以直接继续这个问题，无需先创建计划。", complete: "完成标准",
  },
  "en-US": {
    workspaceTitle: "Choose a learning workspace", workspaceLabel: "Choose workspace", workspaceDetail: "Confirm the current project before continuing.",
    providerTitle: "Connect a coach model", providerLabel: "Set up model", providerDetail: "Connect an available model to continue learning.",
    recoveringTitle: "Restoring current learning", recoveringLabel: "Restoring…", recoveringDetail: "The next step will appear when this workspace has been restored.",
    staleTitle: "Refresh learning state", staleLabel: "Refresh state", staleDetail: "The current state is unconfirmed. Refresh before continuing.",
    frozenTitle: "The plan is paused", frozenLabel: "Resume plan", frozenDetail: "Resume the current step without creating a new plan.",
    blockerTitle: "Resolve the current blocker", blockerLabel: "Resolve with coach",
    evidenceTitle: "Confirm this step’s evidence", verifiedEvidenceTitle: "Confirm this verification result", evidenceLabel: "Approve this evidence", evidenceDetail: "Check the result first. Approving evidence does not establish mastery.",
    continueLabel: "Continue current step", continueDetail: "Complete this step, then bring back the actual result.",
    practiceTitle: "Current practice is in progress", practiceLabel: "Continue practice", practiceDetail: "Continue your practice from where you left off.",
    returnTitle: "Finish reflection and return", returnLabel: "Finish practice handoff", returnDetail: "Finish reflection and return before starting another activity.",
    reviewTitle: "Review is due", reviewLabel: "Start review", reviewDetail: "Revisit what you learned and check whether you can do it independently.",
    completedTitle: "Current practice is complete", completedLabel: "Return to coach", completedDetail: "Continue the conversation with this result before deciding the next step.",
    generateTitle: "Choose your learning goal", generateLabel: "Create learning plan", generateDetail: "Tell the coach what you want to learn, then confirm a formal plan.",
    restoreTitle: "The current step is unconfirmed", restoreLabel: "Confirm next step with coach", restoreDetail: "Keep the existing plan and confirm what to do now.",
    directLabel: "Continue with coach", directDetail: "Continue this question directly without creating a plan first.", complete: "Complete when",
  },
  "es-ES": {
    workspaceTitle: "Elige un espacio de aprendizaje", workspaceLabel: "Elegir espacio", workspaceDetail: "Confirma el proyecto actual antes de continuar.",
    providerTitle: "Conecta un modelo de tutor", providerLabel: "Configurar modelo", providerDetail: "Conecta un modelo disponible para seguir aprendiendo.",
    recoveringTitle: "Restaurando el aprendizaje", recoveringLabel: "Restaurando…", recoveringDetail: "El siguiente paso aparecerá al restaurar este espacio.",
    staleTitle: "Actualiza el estado de aprendizaje", staleLabel: "Actualizar estado", staleDetail: "El estado actual no está confirmado. Actualízalo antes de continuar.",
    frozenTitle: "El plan está pausado", frozenLabel: "Reanudar plan", frozenDetail: "Retoma el paso actual sin crear otro plan.",
    blockerTitle: "Resuelve el bloqueo actual", blockerLabel: "Resolver con el tutor",
    evidenceTitle: "Confirma la evidencia de este paso", verifiedEvidenceTitle: "Confirma este resultado de verificación", evidenceLabel: "Aprobar esta evidencia", evidenceDetail: "Comprueba primero el resultado. Aprobar evidencia no demuestra dominio.",
    continueLabel: "Continuar el paso actual", continueDetail: "Completa este paso y vuelve con el resultado real.",
    practiceTitle: "La práctica está en curso", practiceLabel: "Continuar práctica", practiceDetail: "Continúa la práctica desde donde la dejaste.",
    returnTitle: "Completa la reflexión y el retorno", returnLabel: "Completar el retorno", returnDetail: "Termina la reflexión y el retorno antes de iniciar otra actividad.",
    reviewTitle: "Hay un repaso pendiente", reviewLabel: "Iniciar repaso", reviewDetail: "Revisa lo aprendido y comprueba si puedes hacerlo sin ayuda.",
    completedTitle: "La práctica actual ha terminado", completedLabel: "Volver al tutor", completedDetail: "Continúa la conversación con este resultado antes de decidir el siguiente paso.",
    generateTitle: "Elige tu objetivo de aprendizaje", generateLabel: "Crear plan de aprendizaje", generateDetail: "Explica al tutor qué quieres aprender y confirma un plan formal.",
    restoreTitle: "El paso actual no está confirmado", restoreLabel: "Confirmar el siguiente paso", restoreDetail: "Conserva el plan existente y confirma qué hacer ahora.",
    directLabel: "Continuar con el tutor", directDetail: "Continúa con esta pregunta sin crear primero un plan.", complete: "Completado cuando",
  },
  "fr-FR": {
    workspaceTitle: "Choisir un espace d’apprentissage", workspaceLabel: "Choisir l’espace", workspaceDetail: "Confirmez le projet actuel avant de continuer.",
    providerTitle: "Connecter un modèle de coach", providerLabel: "Configurer le modèle", providerDetail: "Connectez un modèle disponible pour poursuivre l’apprentissage.",
    recoveringTitle: "Restauration de l’apprentissage", recoveringLabel: "Restauration…", recoveringDetail: "La prochaine étape apparaîtra après la restauration de cet espace.",
    staleTitle: "Actualiser l’état d’apprentissage", staleLabel: "Actualiser l’état", staleDetail: "L’état actuel n’est pas confirmé. Actualisez-le avant de continuer.",
    frozenTitle: "Le plan est en pause", frozenLabel: "Reprendre le plan", frozenDetail: "Reprenez l’étape actuelle sans créer un nouveau plan.",
    blockerTitle: "Résoudre le blocage actuel", blockerLabel: "Résoudre avec le coach",
    evidenceTitle: "Confirmer la preuve de cette étape", verifiedEvidenceTitle: "Confirmez ce résultat de vérification", evidenceLabel: "Approuver cette preuve", evidenceDetail: "Vérifiez d’abord le résultat. Approuver une preuve ne signifie pas maîtriser.",
    continueLabel: "Continuer l’étape actuelle", continueDetail: "Terminez cette étape, puis revenez avec le résultat réel.",
    practiceTitle: "L’exercice actuel est en cours", practiceLabel: "Continuer l’exercice", practiceDetail: "Reprenez votre exercice là où vous l’avez laissé.",
    returnTitle: "Terminer la réflexion et le retour", returnLabel: "Terminer le retour d’exercice", returnDetail: "Terminez la réflexion et le retour avant une autre activité.",
    reviewTitle: "Une révision est due", reviewLabel: "Commencer la révision", reviewDetail: "Revoyez vos acquis et vérifiez votre autonomie.",
    completedTitle: "L’exercice actuel est terminé", completedLabel: "Revenir au coach", completedDetail: "Poursuivez la conversation avec ce résultat avant de choisir la suite.",
    generateTitle: "Choisir votre objectif", generateLabel: "Créer un plan d’apprentissage", generateDetail: "Expliquez au coach ce que vous voulez apprendre, puis confirmez un plan.",
    restoreTitle: "L’étape actuelle n’est pas confirmée", restoreLabel: "Confirmer la prochaine étape", restoreDetail: "Conservez le plan existant et confirmez quoi faire maintenant.",
    directLabel: "Continuer avec le coach", directDetail: "Poursuivez cette question sans créer un plan au préalable.", complete: "Terminé lorsque",
  },
  "de-DE": {
    workspaceTitle: "Lernarbeitsbereich auswählen", workspaceLabel: "Arbeitsbereich wählen", workspaceDetail: "Bestätige das aktuelle Projekt, bevor du fortfährst.",
    providerTitle: "Ein Coach-Modell verbinden", providerLabel: "Modell einrichten", providerDetail: "Verbinde ein verfügbares Modell, um weiterzulernen.",
    recoveringTitle: "Lernstand wird wiederhergestellt", recoveringLabel: "Wiederherstellung…", recoveringDetail: "Nach der Wiederherstellung erscheint der nächste Schritt für diesen Arbeitsbereich.",
    staleTitle: "Lernstand aktualisieren", staleLabel: "Status aktualisieren", staleDetail: "Der aktuelle Stand ist unbestätigt. Aktualisiere ihn vor dem Fortfahren.",
    frozenTitle: "Der Plan ist pausiert", frozenLabel: "Plan fortsetzen", frozenDetail: "Setze den aktuellen Schritt fort, ohne einen neuen Plan anzulegen.",
    blockerTitle: "Aktuelle Blockade lösen", blockerLabel: "Mit dem Coach lösen",
    evidenceTitle: "Nachweis für diesen Schritt bestätigen", verifiedEvidenceTitle: "Dieses Prüfergebnis bestätigen", evidenceLabel: "Diesen Nachweis bestätigen", evidenceDetail: "Prüfe zuerst das Ergebnis. Ein bestätigter Nachweis belegt noch keine Beherrschung.",
    continueLabel: "Aktuellen Schritt fortsetzen", continueDetail: "Schließe diesen Schritt ab und bringe das tatsächliche Ergebnis zurück.",
    practiceTitle: "Die aktuelle Übung läuft", practiceLabel: "Übung fortsetzen", practiceDetail: "Setze deine Übung dort fort, wo du aufgehört hast.",
    returnTitle: "Reflexion und Rückkehr abschließen", returnLabel: "Übungsrückkehr abschließen", returnDetail: "Beende Reflexion und Rückkehr vor einer weiteren Aktivität.",
    reviewTitle: "Wiederholung ist fällig", reviewLabel: "Wiederholung starten", reviewDetail: "Prüfe, ob du das Gelernte selbstständig anwenden kannst.",
    completedTitle: "Die aktuelle Übung ist abgeschlossen", completedLabel: "Zum Coach zurück", completedDetail: "Besprich dieses Ergebnis, bevor du den nächsten Schritt auswählst.",
    generateTitle: "Dein Lernziel wählen", generateLabel: "Lernplan erstellen", generateDetail: "Beschreibe dem Coach dein Lernziel und bestätige dann den Plan.",
    restoreTitle: "Der aktuelle Schritt ist unbestätigt", restoreLabel: "Nächsten Schritt bestätigen", restoreDetail: "Behalte den vorhandenen Plan und kläre, was jetzt zu tun ist.",
    directLabel: "Mit dem Coach fortfahren", directDetail: "Verfolge diese Frage direkt weiter, ohne zuerst einen Plan zu erstellen.", complete: "Abgeschlossen, wenn",
  },
  "ja-JP": {
    workspaceTitle: "学習用ワークスペースを選択", workspaceLabel: "ワークスペースを選択", workspaceDetail: "現在のプロジェクトを確認してから続けます。",
    providerTitle: "コーチ用モデルに接続", providerLabel: "モデルを設定", providerDetail: "利用できるモデルに接続して学習を続けます。",
    recoveringTitle: "現在の学習を復元中", recoveringLabel: "復元中…", recoveringDetail: "このワークスペースの復元が完了すると次の手順を表示します。",
    staleTitle: "学習状態の更新が必要です", staleLabel: "状態を更新", staleDetail: "現在の状態が未確認です。更新してから続けます。",
    frozenTitle: "計画は一時停止中です", frozenLabel: "計画を再開", frozenDetail: "新しい計画を作らず、現在の手順を再開します。",
    blockerTitle: "現在の問題を先に解消", blockerLabel: "コーチと問題を解消",
    evidenceTitle: "この手順の証拠を確認", verifiedEvidenceTitle: "今回の検証結果を確認", evidenceLabel: "この証拠を採用", evidenceDetail: "先に結果を確認してください。証拠の採用だけで習得済みとは判断しません。",
    continueLabel: "現在の手順を続ける", continueDetail: "この手順を完了し、実際の結果を持ち帰ります。",
    practiceTitle: "現在の練習は進行中です", practiceLabel: "練習を続ける", practiceDetail: "前回中断したところから練習を続けます。",
    returnTitle: "振り返りと復帰を完了する", returnLabel: "練習の振り返りと復帰を完了", returnDetail: "次の活動を始める前に、振り返りと復帰を完了します。",
    reviewTitle: "復習の時期です", reviewLabel: "復習を開始", reviewDetail: "学んだ内容を振り返り、自力でできるか確認します。",
    completedTitle: "現在の練習は完了しました", completedLabel: "コーチに戻る", completedDetail: "この結果をもとに会話を続け、次の手順を決めます。",
    generateTitle: "学習目標を決める", generateLabel: "学習計画を作成", generateDetail: "学びたい内容をコーチに伝え、正式な計画を確認します。",
    restoreTitle: "現在の手順は未確認です", restoreLabel: "コーチと次の手順を確認", restoreDetail: "既存の計画を保持し、今やることを確認します。",
    directLabel: "コーチと学習を続ける", directDetail: "計画を先に作らず、この質問をそのまま続けられます。", complete: "完了条件",
  },
  "ko-KR": {
    workspaceTitle: "학습 작업 공간 선택", workspaceLabel: "작업 공간 선택", workspaceDetail: "현재 프로젝트를 확인한 뒤 계속하세요.",
    providerTitle: "코치 모델 연결", providerLabel: "모델 설정", providerDetail: "사용 가능한 모델을 연결해 학습을 계속하세요.",
    recoveringTitle: "현재 학습 복원 중", recoveringLabel: "복원 중…", recoveringDetail: "이 작업 공간을 복원하면 다음 단계를 표시합니다.",
    staleTitle: "학습 상태를 새로 고쳐야 합니다", staleLabel: "상태 새로 고침", staleDetail: "현재 상태가 확인되지 않았습니다. 새로 고친 뒤 계속하세요.",
    frozenTitle: "계획이 일시 중지되었습니다", frozenLabel: "계획 재개", frozenDetail: "새 계획을 만들지 않고 현재 단계를 재개합니다.",
    blockerTitle: "현재 문제부터 해결", blockerLabel: "코치와 문제 해결",
    evidenceTitle: "현재 단계의 증거 확인", verifiedEvidenceTitle: "이번 검증 결과 확인", evidenceLabel: "이 증거 승인", evidenceDetail: "결과를 먼저 확인하세요. 증거 승인만으로 숙달했다고 판단하지 않습니다.",
    continueLabel: "현재 단계 계속", continueDetail: "이 단계를 마친 뒤 실제 결과를 가져오세요.",
    practiceTitle: "현재 연습 진행 중", practiceLabel: "연습 계속", practiceDetail: "이전에 멈춘 곳부터 연습을 이어가세요.",
    returnTitle: "회고와 복귀 마무리", returnLabel: "연습 복귀 완료", returnDetail: "다른 활동 전에 회고와 복귀를 마칩니다.",
    reviewTitle: "복습할 때입니다", reviewLabel: "복습 시작", reviewDetail: "배운 내용을 돌아보고 혼자 수행할 수 있는지 확인합니다.",
    completedTitle: "현재 연습을 마쳤습니다", completedLabel: "코치로 돌아가기", completedDetail: "이번 결과로 대화를 이어가고 다음 단계를 결정하세요.",
    generateTitle: "학습 목표 정하기", generateLabel: "학습 계획 만들기", generateDetail: "배우고 싶은 내용을 코치에게 말한 뒤 정식 계획을 확인하세요.",
    restoreTitle: "현재 단계가 확인되지 않았습니다", restoreLabel: "코치와 다음 단계 확인", restoreDetail: "기존 계획을 유지하고 지금 할 일을 확인합니다.",
    directLabel: "코치와 학습 계속", directDetail: "계획을 먼저 만들지 않고 이 질문을 계속할 수 있습니다.", complete: "완료 기준",
  },
  "pt-BR": {
    workspaceTitle: "Escolha um espaço de aprendizagem", workspaceLabel: "Escolher espaço", workspaceDetail: "Confirme o projeto atual antes de continuar.",
    providerTitle: "Conecte um modelo de tutor", providerLabel: "Configurar modelo", providerDetail: "Conecte um modelo disponível para continuar aprendendo.",
    recoveringTitle: "Restaurando a aprendizagem", recoveringLabel: "Restaurando…", recoveringDetail: "A próxima etapa aparecerá após restaurar este espaço.",
    staleTitle: "Atualize o estado de aprendizagem", staleLabel: "Atualizar estado", staleDetail: "O estado atual não foi confirmado. Atualize antes de continuar.",
    frozenTitle: "O plano está pausado", frozenLabel: "Retomar plano", frozenDetail: "Retome a etapa atual sem criar outro plano.",
    blockerTitle: "Resolva o bloqueio atual", blockerLabel: "Resolver com o tutor",
    evidenceTitle: "Confirme a evidência desta etapa", verifiedEvidenceTitle: "Confirme este resultado de verificação", evidenceLabel: "Aprovar esta evidência", evidenceDetail: "Confira o resultado primeiro. Aprovar uma evidência não comprova domínio.",
    continueLabel: "Continuar a etapa atual", continueDetail: "Conclua esta etapa e volte com o resultado real.",
    practiceTitle: "A prática está em andamento", practiceLabel: "Continuar prática", practiceDetail: "Continue a prática de onde parou.",
    returnTitle: "Concluir a reflexão e o retorno", returnLabel: "Concluir o retorno da prática", returnDetail: "Termine a reflexão e o retorno antes de iniciar outra atividade.",
    reviewTitle: "A revisão está pendente", reviewLabel: "Iniciar revisão", reviewDetail: "Revise o que aprendeu e confira se consegue fazer sozinho.",
    completedTitle: "A prática atual foi concluída", completedLabel: "Voltar ao tutor", completedDetail: "Continue a conversa com este resultado antes de decidir a próxima etapa.",
    generateTitle: "Escolha seu objetivo", generateLabel: "Criar plano de aprendizagem", generateDetail: "Diga ao tutor o que deseja aprender e confirme um plano formal.",
    restoreTitle: "A etapa atual não foi confirmada", restoreLabel: "Confirmar a próxima etapa", restoreDetail: "Mantenha o plano existente e confirme o que fazer agora.",
    directLabel: "Continuar com o tutor", directDetail: "Continue esta pergunta sem precisar criar um plano primeiro.", complete: "Concluído quando",
  },
};

export function learningActionCopy(language: ComposerLanguage): LearningActionCopy {
  return copies[language];
}
