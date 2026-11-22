import type { ComposerLanguage } from "./types";
import type { TrainingReturnPayload } from "./trainingReturn";
import { normalizeCoachReturnCopy } from "./coachLanguage";

export interface TrainingCoachBridgeInput {
  language: ComposerLanguage;
  cardId?: string;
  cardType?: "practice" | "flash";
  taskTitle?: string;
  focusArea?: string;
  cardTitle?: string;
  learnerDeliverables?: string[];
  verificationSteps?: string[];
  successSignal?: string;
  returnWith?: string;
  latestVerifiedResult?: string;
  latestSubmittedResult?: string;
  reflection?: string;
  latestFollowup?: string;
  reviewSummary?: string;
  reviewBlocker?: string;
  reviewAbandonReason?: string;
  reviewPartialProgress?: string;
  reviewRootCause?: string;
  reviewNextRule?: string;
  reviewRecommendedActions?: string[];
  reviewStatus?: "active" | "resolved" | "archived";
}

export interface TrainingCoachBridge {
  mode: "continue_task" | "report_result" | "unstick";
  title: string;
  prompt: string;
  detail: string;
  ctaLabel: string;
  summaryLines: string[];
  trainingReturn?: TrainingReturnPayload;
}

type TrainingCoachCtaKind = "continue" | "result" | "blocker";

const trainingCoachCtaCopy: Record<
  ComposerLanguage,
  Record<TrainingCoachCtaKind, string>
> = {
  "zh-CN": {
    continue: "回到教练继续",
    result: "带结果回教练",
    blocker: "带卡点回教练",
  },
  "en-US": {
    continue: "Continue in Coach",
    result: "Bring result to Coach",
    blocker: "Bring blocker to Coach",
  },
  "es-ES": {
    continue: "Continuar con el coach",
    result: "Llevar el resultado al coach",
    blocker: "Llevar el bloqueo al coach",
  },
  "fr-FR": {
    continue: "Continuer avec le coach",
    result: "Ramener le résultat au coach",
    blocker: "Ramener le blocage au coach",
  },
  "de-DE": {
    continue: "Mit dem Coach fortfahren",
    result: "Ergebnis zum Coach bringen",
    blocker: "Hindernis zum Coach bringen",
  },
  "ja-JP": {
    continue: "コーチと続ける",
    result: "結果をコーチに戻す",
    blocker: "詰まった点をコーチに戻す",
  },
  "ko-KR": {
    continue: "코치와 계속하기",
    result: "결과를 코치에게 가져가기",
    blocker: "막힌 점을 코치에게 가져가기",
  },
  "pt-BR": {
    continue: "Continuar com o coach",
    result: "Levar o resultado ao coach",
    blocker: "Levar o bloqueio ao coach",
  },
};

function trainingCoachCtaLabel(language: ComposerLanguage, kind: TrainingCoachCtaKind): string {
  return trainingCoachCtaCopy[language]?.[kind] ?? trainingCoachCtaCopy["en-US"][kind];
}

function compact(value?: string): string | undefined {
  const normalized = value?.replace(/\s+/g, " ").trim();
  return normalized ? normalized : undefined;
}

function firstText(...values: Array<string | undefined>): string | undefined {
  for (const value of values) {
    const normalized = compact(value);
    if (normalized) {
      return normalized;
    }
  }
  return undefined;
}

function uniqueList(values: Array<string | undefined>, limit = 4): string[] {
  const seen = new Set<string>();
  const items: string[] = [];
  for (const value of values) {
    const normalized = compact(value);
    if (!normalized || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    items.push(normalized);
    if (items.length >= limit) {
      break;
    }
  }
  return items;
}

function compactList(values?: string[], limit = 3): string[] {
  return uniqueList(values ?? [], limit);
}

function buildTrainingReturn(
  input: TrainingCoachBridgeInput,
  mode: "report_result" | "unstick",
): TrainingReturnPayload | undefined {
  const cardId = compact(input.cardId);
  const cardTitle = compact(input.cardTitle) ?? compact(input.taskTitle);
  const cardType = input.cardType;
  if (!cardId || !cardTitle || !cardType) {
    return undefined;
  }

  if (mode === "report_result") {
    const verifiedResult = compact(input.latestVerifiedResult);
    const summary = firstText(
      input.reviewSummary,
      input.latestVerifiedResult,
      input.latestSubmittedResult,
    );
    if (!summary) {
      return undefined;
    }
    return {
      cardId,
      cardType,
      cardTitle,
      returnMode: "result",
      summary,
      verifiedResult,
      source: "training_bridge",
    };
  }

  const blocker = firstText(
    input.reviewBlocker,
    input.reviewAbandonReason,
    input.reviewRootCause,
    input.latestFollowup,
  );
  const summary = firstText(
    input.reviewPartialProgress,
    input.reviewBlocker,
    input.reviewAbandonReason,
    input.reviewRootCause,
    input.latestFollowup,
  );
  if (!summary && !blocker) {
    return undefined;
  }
  return {
    cardId,
    cardType,
    cardTitle,
    returnMode: "blocker",
    summary: summary ?? blocker ?? "",
    blocker: blocker ?? undefined,
    source: "training_bridge",
  };
}

function hasReportableResult(input: TrainingCoachBridgeInput): boolean {
  return Boolean(
    compact(input.latestVerifiedResult) ||
      compact(input.latestSubmittedResult) ||
      compact(input.reviewSummary) ||
      input.reviewStatus === "resolved",
  );
}

function hasStallSignal(input: TrainingCoachBridgeInput): boolean {
  return Boolean(
    compact(input.reviewBlocker) ||
      compact(input.reviewAbandonReason) ||
      compact(input.reviewPartialProgress) ||
      compact(input.reviewRootCause) ||
      compact(input.latestFollowup) ||
      input.reviewStatus === "active",
  );
}

interface TrainingCoachBridgeLocaleCopy {
  defaultFocus: string;
  reportHeader: (focus: string) => string;
  reportVerified: (verified: string) => string;
  reportNeedsVerify: string;
  reportSubmitted: (submitted: string) => string;
  reportReflection: (reflection: string) => string;
  reportPassSignal: (signal: string) => string;
  reportBringBack: (bringBack: string) => string;
  reportFallbackBringBack: string;
  reportFooter: string;
  unstickHeader: (focus: string) => string;
  unstickProgress: (progress: string) => string;
  unstickDefaultProgress: string;
  unstickBlocker: (blocker: string) => string;
  unstickDefaultBlocker: string;
  unstickFooter: string;
  continueHeader: (focus: string) => string;
  continueDeliverable: (deliverable: string) => string;
  continueDefaultDeliverable: string;
  continueVerify: (verification: string) => string;
  continueFooter: string;
  reportTitle: (focus: string) => string;
  reportDetailVerified: string;
  reportDetailSubmitted: string;
  summaryVerified: (verified: string) => string;
  summarySubmitted: (submitted: string) => string;
  summaryPassSignal: (signal: string) => string;
  summaryBringBack: (bringBack: string) => string;
  unstickTitle: (focus: string) => string;
  unstickDetail: string;
  summaryBlocker: (blocker: string) => string;
  summaryProgressSoFar: (progress: string) => string;
  summaryBringBackFirst: (bringBack: string) => string;
  continueTitle: (focus: string) => string;
  continueDetail: string;
  summaryYouDeliver: (deliverable: string) => string;
  summaryVerifyLikeThis: (verification: string) => string;
}

const TRAINING_BRIDGE_LOCALE_COPY: Record<ComposerLanguage, TrainingCoachBridgeLocaleCopy> = {
  "zh-CN": {
    defaultFocus: "当前训练卡",
    reportHeader: (focus) => `请评估我在「${focus}」中的提交，不要替我改代码。`,
    reportVerified: (verified) => `请评估这条结果记录及其证据：${verified}`,
    reportNeedsVerify: "请先评估当前记录和还需要的验证。",
    reportSubmitted: (submitted) => `我的提交是：\n${submitted}\n请判断答案和还需要的验证。`,
    reportReflection: (reflection) => `我的复盘是：\n${reflection}`,
    reportPassSignal: (signal) => `这张卡的过关信号是：${signal}`,
    reportBringBack: (bringBack) => `这张卡要求带回的内容是：${bringBack}`,
    reportFallbackBringBack: "请先判断这次结果是通过、部分通过、误解，还是需要降级。",
    reportFooter: "请你先评估，再决定是复盘、纳入计划证据、补闪记，还是给我下一张更合适的卡。",
    unstickHeader: (focus) => `请围绕「${focus}」指导我，不要替我改代码。`,
    unstickProgress: (progress) => `我已经推进到：${progress}`,
    unstickDefaultProgress: "我卡在这张训练卡上。",
    unstickBlocker: (blocker) => `当前卡点是：${blocker}`,
    unstickDefaultBlocker: "我需要你先帮我判断为什么这轮会卡住。",
    unstickFooter: "请你先判断根因更像理论、API、边界、验证还是资料问题，再决定该复盘、补闪记、压成更小实战，还是先回资料。",
    continueHeader: (focus) => `请围绕「${focus}」指导我，不要替我改代码。`,
    continueDeliverable: (deliverable) => `我接下来会自己完成：${deliverable}`,
    continueDefaultDeliverable: "请先继续压清这张训练卡的下一步。",
    continueVerify: (verification) => `我会先这样验证：${verification}`,
    continueFooter: "请告诉我从哪个文件或边界开始、我自己要写什么、以及做完后该带什么结果回给你。",
    reportTitle: (focus) => `把「${focus}」的结果带回教练`,
    reportDetailVerified: "带回验证记录，请教练判断通过程度和下一步。",
    reportDetailSubmitted: "带回答案，请教练判断还需要哪些验证。",
    summaryVerified: (verified) => `验证结果：${verified}`,
    summarySubmitted: (submitted) => `我的提交：${submitted}`,
    summaryPassSignal: (signal) => `过关信号：${signal}`,
    summaryBringBack: (bringBack) => `回带内容：${bringBack}`,
    unstickTitle: (focus) => `把「${focus}」的卡点带回教练`,
    unstickDetail: "把当前卡点带回对话，让教练先判断根因属于哪一层，再决定复盘、闪记、降级实战或回资料。",
    summaryBlocker: (blocker) => `当前卡点：${blocker}`,
    summaryProgressSoFar: (progress) => `已推进到：${progress}`,
    summaryBringBackFirst: (bringBack) => `先回带：${bringBack}`,
    continueTitle: (focus) => `围绕「${focus}」继续教练指导`,
    continueDetail: "先把下一小步和验证方式说清楚，再继续这张训练卡。",
    summaryYouDeliver: (deliverable) => `你来交付：${deliverable}`,
    summaryVerifyLikeThis: (verification) => `先这样验：${verification}`,
  },
  "en-US": {
    defaultFocus: "the current training card",
    reportHeader: (focus) => `Keep coaching around "${focus}" and stay coach-only. Do not edit code for me.`,
    reportVerified: (verified) => `Evaluate this result record and its evidence: ${verified}`,
    reportNeedsVerify: "Assess the current record and the verification still needed.",
    reportSubmitted: (submitted) => `My submission is:\n${submitted}\nAssess the answer and the verification still needed.`,
    reportReflection: (reflection) => `My reflection is:\n${reflection}`,
    reportPassSignal: (signal) => `The pass signal for this card was: ${signal}`,
    reportBringBack: (bringBack) => `Here is what I was supposed to bring back: ${bringBack}`,
    reportFallbackBringBack: "First decide whether this was a pass, partial pass, misunderstanding, or a loop that should be downgraded.",
    reportFooter: "Evaluate it first, then decide whether it should become review, plan evidence, flash reinforcement, or the next card.",
    unstickHeader: (focus) => `Keep coaching around "${focus}" and stay coach-only. Do not edit code for me.`,
    unstickProgress: (progress) => `I got as far as: ${progress}`,
    unstickDefaultProgress: "I tried this training card but got stuck.",
    unstickBlocker: (blocker) => `The current blocker is: ${blocker}`,
    unstickDefaultBlocker: "Help me identify why this loop is stuck.",
    unstickFooter: "First decide whether the root cause is theory, API usage, boundary judgment, verification, or missing material, then choose whether to review, flash, downgrade the practice slice, or go back to Resources.",
    continueHeader: (focus) => `Keep coaching around "${focus}" and stay coach-only. Do not edit code for me.`,
    continueDeliverable: (deliverable) => `I will implement this next: ${deliverable}`,
    continueDefaultDeliverable: "Keep compressing the next move for this training card.",
    continueVerify: (verification) => `I plan to verify it like this: ${verification}`,
    continueFooter: "Tell me which file or boundary to start from, what I should write myself, and what result I should bring back to you afterward.",
    reportTitle: (focus) => `Bring the "${focus}" result back to coach`,
    reportDetailVerified: "Bring the verification result back for assessment and the next step.",
    reportDetailSubmitted: "Bring the answer back so the coach can assess the verification still needed.",
    summaryVerified: (verified) => `Verification result: ${verified}`,
    summarySubmitted: (submitted) => `My submission: ${submitted}`,
    summaryPassSignal: (signal) => `Pass signal: ${signal}`,
    summaryBringBack: (bringBack) => `Bring back: ${bringBack}`,
    unstickTitle: (focus) => `Bring the "${focus}" blocker back to coach`,
    unstickDetail: "Bring the current blocker back so the coach can diagnose the layer first, then choose review, flash, a smaller practice slice, or Resources.",
    summaryBlocker: (blocker) => `Current blocker: ${blocker}`,
    summaryProgressSoFar: (progress) => `Progress so far: ${progress}`,
    summaryBringBackFirst: (bringBack) => `Bring back first: ${bringBack}`,
    continueTitle: (focus) => `Keep coaching around "${focus}"`,
    continueDetail: "Compress the next slice and the first verification before continuing this card.",
    summaryYouDeliver: (deliverable) => `You deliver: ${deliverable}`,
    summaryVerifyLikeThis: (verification) => `Verify like this: ${verification}`,
  },
  "es-ES": {
    defaultFocus: "la tarjeta de entrenamiento actual",
    reportHeader: (focus) => `Sigue guiándome en "${focus}" solo como coach. No edites código por mí.`,
    reportVerified: (verified) => `Evalúa este registro de resultado y su evidencia: ${verified}`,
    reportNeedsVerify: "Evalúa el registro actual y la verificación que aún falta.",
    reportSubmitted: (submitted) => `Mi entrega es:\n${submitted}\nEvalúa la respuesta y la verificación pendiente.`,
    reportReflection: (reflection) => `Mi reflexión es:\n${reflection}`,
    reportPassSignal: (signal) => `La señal de aprobación de esta tarjeta era: ${signal}`,
    reportBringBack: (bringBack) => `Lo que debía traer de vuelta era: ${bringBack}`,
    reportFallbackBringBack: "Decide primero si esto fue aprobado, parcial, malentendido o si conviene simplificar el paso.",
    reportFooter: "Evalúalo primero y luego decide si pasa a repaso, evidencia del plan, flashcard o la siguiente tarjeta.",
    unstickHeader: (focus) => `Sigue guiándome en "${focus}" solo como coach. No edites código por mí.`,
    unstickProgress: (progress) => `Avancé hasta: ${progress}`,
    unstickDefaultProgress: "Probé esta tarjeta de entrenamiento pero me quedé bloqueado.",
    unstickBlocker: (blocker) => `El bloqueo actual es: ${blocker}`,
    unstickDefaultBlocker: "Ayúdame a identificar por qué se atascó este ciclo.",
    unstickFooter: "Determina primero si la causa es teoría, uso de API, límites, verificación o falta de material, y elige si repasar, hacer flashcard, reducir la práctica o volver a Recursos.",
    continueHeader: (focus) => `Sigue guiándome en "${focus}" solo como coach. No edites código por mí.`,
    continueDeliverable: (deliverable) => `Voy a implementar esto a continuación: ${deliverable}`,
    continueDefaultDeliverable: "Sigue concretando el siguiente paso mínimo de esta tarjeta.",
    continueVerify: (verification) => `Pienso verificarlo así: ${verification}`,
    continueFooter: "Indícame desde qué archivo o límite empezar, qué debo escribir yo mismo y qué resultado traerte después.",
    reportTitle: (focus) => `Llevar el resultado de "${focus}" al coach`,
    reportDetailVerified: "Lleva el resultado de verificación para evaluarlo y decidir el siguiente paso.",
    reportDetailSubmitted: "Lleva la respuesta para que el coach evalúe la verificación restante.",
    summaryVerified: (verified) => `Resultado verificado: ${verified}`,
    summarySubmitted: (submitted) => `Mi entrega: ${submitted}`,
    summaryPassSignal: (signal) => `Señal de aprobación: ${signal}`,
    summaryBringBack: (bringBack) => `Traer de vuelta: ${bringBack}`,
    unstickTitle: (focus) => `Llevar el bloqueo de "${focus}" al coach`,
    unstickDetail: "Lleva el bloqueo actual al chat para diagnosticar la capa raíz y elegir el siguiente paso.",
    summaryBlocker: (blocker) => `Bloqueo actual: ${blocker}`,
    summaryProgressSoFar: (progress) => `Avance actual: ${progress}`,
    summaryBringBackFirst: (bringBack) => `Traer primero: ${bringBack}`,
    continueTitle: (focus) => `Seguir practicando "${focus}" con el coach`,
    continueDetail: "Concreta el siguiente pequeño paso y la primera verificación antes de continuar.",
    summaryYouDeliver: (deliverable) => `Tú entregas: ${deliverable}`,
    summaryVerifyLikeThis: (verification) => `Verifica así: ${verification}`,
  },
  "fr-FR": {
    defaultFocus: "la carte d'entraînement actuelle",
    reportHeader: (focus) => `Continuez à m'accompagner sur "${focus}" en restant coach uniquement. N'éditez pas de code à ma place.`,
    reportVerified: (verified) => `Évaluez ce résultat et ses preuves : ${verified}`,
    reportNeedsVerify: "Évaluez l'état actuel et la vérification encore nécessaire.",
    reportSubmitted: (submitted) => `Voici ma réponse :\n${submitted}\nÉvaluez-la et indiquez la vérification restante.`,
    reportReflection: (reflection) => `Ma réflexion :\n${reflection}`,
    reportPassSignal: (signal) => `Le critère de réussite de cette carte était : ${signal}`,
    reportBringBack: (bringBack) => `Ce que je devais rapporter : ${bringBack}`,
    reportFallbackBringBack: "Déterminez d'abord s'il s'agit d'une réussite, d'un résultat partiel, d'un malentendu ou d'un blocage à réduire.",
    reportFooter: "Évaluez d'abord, puis décidez s'il faut réviser, ajouter comme preuve au plan, créer une flashcard ou passer à la carte suivante.",
    unstickHeader: (focus) => `Continuez à m'accompagner sur "${focus}" en restant coach uniquement. N'éditez pas de code à ma place.`,
    unstickProgress: (progress) => `J'ai avancé jusqu'à : ${progress}`,
    unstickDefaultProgress: "J'ai essayé cette carte mais je suis bloqué.",
    unstickBlocker: (blocker) => `Le blocage actuel est : ${blocker}`,
    unstickDefaultBlocker: "Aidez-moi à identifier pourquoi cette boucle bloque.",
    unstickFooter: "Identifiez d'abord si la cause relève de la théorie, de l'API, des bornes, de la vérification ou d'un manque de ressources.",
    continueHeader: (focus) => `Continuez à m'accompagner sur "${focus}" en restant coach uniquement. N'éditez pas de code à ma place.`,
    continueDeliverable: (deliverable) => `Je vais réaliser ensuite : ${deliverable}`,
    continueDefaultDeliverable: "Aidez-moi à préciser la prochaine étape minimale de cette carte.",
    continueVerify: (verification) => `Je prévois de vérifier ainsi : ${verification}`,
    continueFooter: "Indiquez-moi par quel fichier ou quelle borne commencer, ce que je dois écrire moi-même et quel résultat rapporter ensuite.",
    reportTitle: (focus) => `Rapporter le résultat de "${focus}" au coach`,
    reportDetailVerified: "Rapportez le résultat vérifié pour évaluation et suite.",
    reportDetailSubmitted: "Rapportez la réponse afin que le coach précise la vérification restante.",
    summaryVerified: (verified) => `Résultat vérifié : ${verified}`,
    summarySubmitted: (submitted) => `Ma réponse : ${submitted}`,
    summaryPassSignal: (signal) => `Critère de réussite : ${signal}`,
    summaryBringBack: (bringBack) => `À rapporter : ${bringBack}`,
    unstickTitle: (focus) => `Rapporter le blocage de "${focus}" au coach`,
    unstickDetail: "Rapportez ce blocage pour diagnostiquer la cause racine et choisir la suite adaptée.",
    summaryBlocker: (blocker) => `Blocage actuel : ${blocker}`,
    summaryProgressSoFar: (progress) => `Avancement : ${progress}`,
    summaryBringBackFirst: (bringBack) => `À rapporter d'abord : ${bringBack}`,
    continueTitle: (focus) => `Continuer l'accompagnement sur "${focus}"`,
    continueDetail: "Précisez la prochaine petite étape et sa vérification avant de reprendre cette carte.",
    summaryYouDeliver: (deliverable) => `À livrer par vous : ${deliverable}`,
    summaryVerifyLikeThis: (verification) => `Vérifier ainsi : ${verification}`,
  },
  "de-DE": {
    defaultFocus: "die aktuelle Trainingskarte",
    reportHeader: (focus) => `Coache mich weiter zu "${focus}" und schreibe keinen Code für mich.`,
    reportVerified: (verified) => `Bewerte dieses Ergebnis und seinen Nachweis: ${verified}`,
    reportNeedsVerify: "Prüfe den aktuellen Stand und welche Verifikation noch nötig ist.",
    reportSubmitted: (submitted) => `Meine Einreichung lautet:\n${submitted}\nBewerte die Antwort und die noch nötige Prüfung.`,
    reportReflection: (reflection) => `Meine Reflexion:\n${reflection}`,
    reportPassSignal: (signal) => `Das Erfolgssignal dieser Karte war: ${signal}`,
    reportBringBack: (bringBack) => `Das sollte ich zurückbringen: ${bringBack}`,
    reportFallbackBringBack: "Entscheide zuerst, ob es bestanden, teilweise bestanden, ein Missverständnis oder zu verkleinern ist.",
    reportFooter: "Erst bewerten, dann entscheiden: Wiederholung, Plannachweis, Lernkarte oder die nächste passende Karte.",
    unstickHeader: (focus) => `Coache mich weiter zu "${focus}" und schreibe keinen Code für mich.`,
    unstickProgress: (progress) => `Ich bin so weit gekommen: ${progress}`,
    unstickDefaultProgress: "Ich habe diese Karte versucht, stecke aber fest.",
    unstickBlocker: (blocker) => `Aktueller Blocker: ${blocker}`,
    unstickDefaultBlocker: "Hilf mir zu erkennen, warum diese Schleife feststeckt.",
    unstickFooter: "Prüfe zuerst, ob die Ursache bei Theorie, API, Randfällen, Verifikation oder fehlendem Material liegt.",
    continueHeader: (focus) => `Coache mich weiter zu "${focus}" und schreibe keinen Code für mich.`,
    continueDeliverable: (deliverable) => `Als Nächstes setze ich selbst um: ${deliverable}`,
    continueDefaultDeliverable: "Verkleinere den nächsten Schritt für diese Karte weiter.",
    continueVerify: (verification) => `Ich plane es so zu prüfen: ${verification}`,
    continueFooter: "Sage mir, bei welcher Datei oder Grenze ich anfange, was ich selbst schreibe und welches Ergebnis ich zurückbringe.",
    reportTitle: (focus) => `Ergebnis zu "${focus}" zum Coach bringen`,
    reportDetailVerified: "Verifikationsergebnis zur Bewertung und für den nächsten Schritt zurückbringen.",
    reportDetailSubmitted: "Antwort zurückbringen, damit der Coach die noch nötige Prüfung einschätzt.",
    summaryVerified: (verified) => `Verifiziertes Ergebnis: ${verified}`,
    summarySubmitted: (submitted) => `Meine Einreichung: ${submitted}`,
    summaryPassSignal: (signal) => `Erfolgssignal: ${signal}`,
    summaryBringBack: (bringBack) => `Zurückbringen: ${bringBack}`,
    unstickTitle: (focus) => `Blocker zu "${focus}" zum Coach bringen`,
    unstickDetail: "Aktuellen Blocker zurückbringen, damit der Coach die Ursache klärt und den nächsten Schritt wählt.",
    summaryBlocker: (blocker) => `Aktueller Blocker: ${blocker}`,
    summaryProgressSoFar: (progress) => `Bisheriger Fortschritt: ${progress}`,
    summaryBringBackFirst: (bringBack) => `Zuerst zurückbringen: ${bringBack}`,
    continueTitle: (focus) => `Weiter coachen zu "${focus}"`,
    continueDetail: "Den nächsten kleinen Schritt und die erste Prüfung klären, bevor die Karte fortgesetzt wird.",
    summaryYouDeliver: (deliverable) => `Deine Aufgabe: ${deliverable}`,
    summaryVerifyLikeThis: (verification) => `So prüfen: ${verification}`,
  },
  "ja-JP": {
    defaultFocus: "現在のトレーニングカード",
    reportHeader: (focus) => `「${focus}」についてコーチのみで指導してください。コードは代わりに書かないでください。`,
    reportVerified: (verified) => `この結果記録と根拠を評価してください: ${verified}`,
    reportNeedsVerify: "現在の記録と追加で必要な検証を評価してください。",
    reportSubmitted: (submitted) => `私の回答です:\n${submitted}\n回答と不足している検証を判断してください。`,
    reportReflection: (reflection) => `私の振り返り:\n${reflection}`,
    reportPassSignal: (signal) => `このカードの合格条件: ${signal}`,
    reportBringBack: (bringBack) => `持ち帰るべき内容: ${bringBack}`,
    reportFallbackBringBack: "合格・部分合格・誤解・難易度調整のどれに該当するか先に判断してください。",
    reportFooter: "まず評価してから、復習・計画の根拠登録・フラッシュカード化・次のカードのどれにするか決めてください。",
    unstickHeader: (focus) => `「${focus}」についてコーチのみで指導してください。コードは代わりに書かないでください。`,
    unstickProgress: (progress) => `ここまで進みました: ${progress}`,
    unstickDefaultProgress: "このカードで詰まりました。",
    unstickBlocker: (blocker) => `現在の詰まりポイント: ${blocker}`,
    unstickDefaultBlocker: "なぜ詰まっているのか原因を一緒に切り分けてください。",
    unstickFooter: "原因が理論・API・境界条件・検証・資料不足のどれかを先に判定し、次の一手を選んでください。",
    continueHeader: (focus) => `「${focus}」についてコーチのみで指導してください。コードは代わりに書かないでください。`,
    continueDeliverable: (deliverable) => `次に自分で実装する内容: ${deliverable}`,
    continueDefaultDeliverable: "このカードの次の一歩をさらに具体的に絞ってください。",
    continueVerify: (verification) => `検証予定の方法: ${verification}`,
    continueFooter: "どのファイルや境界から始めるか、自分で何を書くか、完了後に何を持ち帰るかを教えてください。",
    reportTitle: (focus) => `「${focus}」の結果をコーチへ戻す`,
    reportDetailVerified: "検証結果を持ち帰り、達成度と次の一歩を判定してもらいます。",
    reportDetailSubmitted: "回答を持ち帰り、必要な追加検証をコーチに判断してもらいます。",
    summaryVerified: (verified) => `検証結果: ${verified}`,
    summarySubmitted: (submitted) => `提出内容: ${submitted}`,
    summaryPassSignal: (signal) => `合格条件: ${signal}`,
    summaryBringBack: (bringBack) => `持ち帰り: ${bringBack}`,
    unstickTitle: (focus) => `「${focus}」の詰まりをコーチへ相談`,
    unstickDetail: "詰まっている箇所を会話に戻し、原因を切り分けて次の一歩を決めます。",
    summaryBlocker: (blocker) => `現在の詰まり: ${blocker}`,
    summaryProgressSoFar: (progress) => `進捗: ${progress}`,
    summaryBringBackFirst: (bringBack) => `まず持ち帰る項目: ${bringBack}`,
    continueTitle: (focus) => `「${focus}」の指導を続ける`,
    continueDetail: "次の小さな一歩と最初の検証方法を確認してから続けます。",
    summaryYouDeliver: (deliverable) => `実装目標: ${deliverable}`,
    summaryVerifyLikeThis: (verification) => `検証方法: ${verification}`,
  },
  "ko-KR": {
    defaultFocus: "현재 훈련 카드",
    reportHeader: (focus) => `"${focus}"에 대해 코치 모드로만 지도해 주세요. 코드를 대신 수정하지 마세요.`,
    reportVerified: (verified) => `이 결과 기록과 근거를 평가해 주세요: ${verified}`,
    reportNeedsVerify: "현재 기록과 추가로 필요한 검증을 평가해 주세요.",
    reportSubmitted: (submitted) => `제 제출 내용은 다음과 같습니다:\n${submitted}\n답변과 더 필요한 검증을 판단해 주세요.`,
    reportReflection: (reflection) => `제 회고 내용:\n${reflection}`,
    reportPassSignal: (signal) => `이 카드의 통과 신호: ${signal}`,
    reportBringBack: (bringBack) => `가져오기로 한 결과: ${bringBack}`,
    reportFallbackBringBack: "통과, 부분 통과, 오해, 또는 난이도 하향 중 무엇인지 먼저 판단해 주세요.",
    reportFooter: "먼저 평가한 뒤 복습, 계획 근거 반영, 플래시 카드 보강, 다음 카드 중 무엇으로 갈지 정해 주세요.",
    unstickHeader: (focus) => `"${focus}"에 대해 코치 모드로만 지도해 주세요. 코드를 대신 수정하지 마세요.`,
    unstickProgress: (progress) => `여기까지 진행했습니다: ${progress}`,
    unstickDefaultProgress: "이 훈련 카드에서 막혔습니다.",
    unstickBlocker: (blocker) => `현재 막힌 지점: ${blocker}`,
    unstickDefaultBlocker: "왜 막혔는지 원인을 파악할 수 있게 도와주세요.",
    unstickFooter: "원인이 이론, API 사용법, 경계 판단, 검증, 자료 부족 중 어디에 있는지 먼저 짚어 주세요.",
    continueHeader: (focus) => `"${focus}"에 대해 코치 모드로만 지도해 주세요. 코드를 대신 수정하지 마세요.`,
    continueDeliverable: (deliverable) => `다음으로 직접 구현할 항목: ${deliverable}`,
    continueDefaultDeliverable: "이 카드의 다음 한 걸음을 더 작게 좁혀 주세요.",
    continueVerify: (verification) => `검증 계획: ${verification}`,
    continueFooter: "어느 파일/경계부터 시작할지, 직접 작성할 내용과 완료 후 가져올 결과를 알려 주세요.",
    reportTitle: (focus) => `"${focus}" 결과를 코치에게 전달`,
    reportDetailVerified: "검증 결과를 가져가 평가와 다음 단계를 받습니다.",
    reportDetailSubmitted: "답안을 가져가 필요한 추가 검증을 코치에게 판단받습니다.",
    summaryVerified: (verified) => `검증 결과: ${verified}`,
    summarySubmitted: (submitted) => `내 제출: ${submitted}`,
    summaryPassSignal: (signal) => `통과 기준: ${signal}`,
    summaryBringBack: (bringBack) => `가져갈 내용: ${bringBack}`,
    unstickTitle: (focus) => `"${focus}" 막힌 지점을 코치에게 전달`,
    unstickDetail: "현재 막힌 지점을 대화로 가져가 원인을 진단하고 다음 행동을 고릅니다.",
    summaryBlocker: (blocker) => `막힌 지점: ${blocker}`,
    summaryProgressSoFar: (progress) => `진행 상황: ${progress}`,
    summaryBringBackFirst: (bringBack) => `먼저 확인할 항목: ${bringBack}`,
    continueTitle: (focus) => `"${focus}" 코칭 이어가기`,
    continueDetail: "다음 작은 단계와 첫 검증 방법을 명확히 한 뒤 카드를 이어갑니다.",
    summaryYouDeliver: (deliverable) => `구현 목표: ${deliverable}`,
    summaryVerifyLikeThis: (verification) => `검증 방법: ${verification}`,
  },
  "pt-BR": {
    defaultFocus: "o cartão de treinamento atual",
    reportHeader: (focus) => `Continue me orientando sobre "${focus}" apenas como coach. Não edite código por mim.`,
    reportVerified: (verified) => `Avalie este registro de resultado e suas evidências: ${verified}`,
    reportNeedsVerify: "Avalie o registro atual e qual verificação ainda falta.",
    reportSubmitted: (submitted) => `Meu envio é:\n${submitted}\nAvalie a resposta e a verificação pendente.`,
    reportReflection: (reflection) => `Minha reflexão é:\n${reflection}`,
    reportPassSignal: (signal) => `O critério de aprovação deste cartão era: ${signal}`,
    reportBringBack: (bringBack) => `O que eu deveria trazer de volta: ${bringBack}`,
    reportFallbackBringBack: "Decida primeiro se foi aprovado, parcial, mal-entendido ou se vale reduzir a etapa.",
    reportFooter: "Avalie primeiro e depois decida entre revisão, evidência no plano, flashcard ou próximo cartão.",
    unstickHeader: (focus) => `Continue me orientando sobre "${focus}" apenas como coach. Não edite código por mim.`,
    unstickProgress: (progress) => `Avancei até: ${progress}`,
    unstickDefaultProgress: "Tentei este cartão de treinamento, mas travei.",
    unstickBlocker: (blocker) => `O bloqueio atual é: ${blocker}`,
    unstickDefaultBlocker: "Ajude-me a identificar por que este ciclo travou.",
    unstickFooter: "Identifique primeiro se a causa raiz é teoria, API, limites, verificação ou falta de material.",
    continueHeader: (focus) => `Continue me orientando sobre "${focus}" apenas como coach. Não edite código por mim.`,
    continueDeliverable: (deliverable) => `Vou implementar em seguida: ${deliverable}`,
    continueDefaultDeliverable: "Continue detalhando o próximo passo menor para este cartão.",
    continueVerify: (verification) => `Pretendo verificar assim: ${verification}`,
    continueFooter: "Diga por qual arquivo ou limite começar, o que devo escrever sozinho e qual resultado trazer depois.",
    reportTitle: (focus) => `Trazer resultado de "${focus}" ao coach`,
    reportDetailVerified: "Traga o resultado verificado para avaliação e próximo passo.",
    reportDetailSubmitted: "Traga a resposta para o coach avaliar a verificação restante.",
    summaryVerified: (verified) => `Resultado verificado: ${verified}`,
    summarySubmitted: (submitted) => `Meu envio: ${submitted}`,
    summaryPassSignal: (signal) => `Critério de aprovação: ${signal}`,
    summaryBringBack: (bringBack) => `Trazer de volta: ${bringBack}`,
    unstickTitle: (focus) => `Trazer bloqueio de "${focus}" ao coach`,
    unstickDetail: "Traga o bloqueio atual ao chat para diagnosticar a camada raiz e escolher a próxima ação.",
    summaryBlocker: (blocker) => `Bloqueio atual: ${blocker}`,
    summaryProgressSoFar: (progress) => `Progresso até aqui: ${progress}`,
    summaryBringBackFirst: (bringBack) => `Trazer primeiro: ${bringBack}`,
    continueTitle: (focus) => `Continuar coaching em "${focus}"`,
    continueDetail: "Defina o próximo passo pequeno e a primeira verificação antes de continuar este cartão.",
    summaryYouDeliver: (deliverable) => `Você entrega: ${deliverable}`,
    summaryVerifyLikeThis: (verification) => `Verifique assim: ${verification}`,
  },
};

function bridgeCopy(language: ComposerLanguage): TrainingCoachBridgeLocaleCopy {
  return TRAINING_BRIDGE_LOCALE_COPY[language] ?? TRAINING_BRIDGE_LOCALE_COPY["en-US"];
}

function focusLabel(input: TrainingCoachBridgeInput): string {
  return firstText(input.cardTitle, input.focusArea, input.taskTitle) || bridgeCopy(input.language).defaultFocus;
}

function reportPrompt(input: TrainingCoachBridgeInput, focus: string): string {
  const copy = bridgeCopy(input.language);
  const verified = compact(input.latestVerifiedResult);
  const submitted = input.latestSubmittedResult?.trim() || input.reviewSummary?.trim();
  const reflection = input.reflection?.trim();
  const bringBack = firstText(
    input.returnWith,
    input.latestFollowup,
    input.reviewNextRule,
    input.reviewRecommendedActions?.[0],
  );
  const passSignal = compact(input.successSignal);
  return [
    copy.reportHeader(focus),
    verified
      ? copy.reportVerified(verified)
      : !submitted
        ? copy.reportNeedsVerify
        : undefined,
    submitted && compact(submitted) !== verified
      ? copy.reportSubmitted(submitted)
      : undefined,
    reflection ? copy.reportReflection(reflection) : undefined,
    passSignal ? copy.reportPassSignal(passSignal) : undefined,
    bringBack ? copy.reportBringBack(bringBack) : copy.reportFallbackBringBack,
    copy.reportFooter,
  ]
    .filter(Boolean)
    .join("\n\n");
}

function unstickPrompt(input: TrainingCoachBridgeInput, focus: string): string {
  const copy = bridgeCopy(input.language);
  const progress = firstText(
    input.reviewPartialProgress,
    input.latestVerifiedResult,
    input.latestSubmittedResult,
  );
  const blocker = firstText(
    input.reviewBlocker,
    input.reviewAbandonReason,
    input.latestFollowup,
    input.reviewRootCause,
  );
  return [
    copy.unstickHeader(focus),
    progress ? copy.unstickProgress(progress) : copy.unstickDefaultProgress,
    blocker ? copy.unstickBlocker(blocker) : copy.unstickDefaultBlocker,
    copy.unstickFooter,
  ]
    .filter(Boolean)
    .join(" ");
}

function continuePrompt(input: TrainingCoachBridgeInput, focus: string): string {
  const copy = bridgeCopy(input.language);
  const deliverable = compactList(input.learnerDeliverables, 1)[0];
  const verification = compactList(input.verificationSteps, 1)[0];
  return [
    copy.continueHeader(focus),
    deliverable ? copy.continueDeliverable(deliverable) : copy.continueDefaultDeliverable,
    verification ? copy.continueVerify(verification) : undefined,
    copy.continueFooter,
  ]
    .filter(Boolean)
    .join(" ");
}

export function buildTrainingCoachBridge(input: TrainingCoachBridgeInput): TrainingCoachBridge {
  const copy = bridgeCopy(input.language);
  const focus = focusLabel(input);
  const mode = hasReportableResult(input)
    ? "report_result"
    : hasStallSignal(input)
      ? "unstick"
      : "continue_task";
  const verified = compact(input.latestVerifiedResult);
  const submitted = firstText(input.latestSubmittedResult, input.reviewSummary);
  const bringBack = firstText(
    input.returnWith,
    input.latestFollowup,
    input.reviewNextRule,
    input.reviewRecommendedActions?.[0],
  );
  const blocker = firstText(
    input.reviewBlocker,
    input.reviewAbandonReason,
    input.reviewRootCause,
    input.latestFollowup,
  );

  if (mode === "report_result") {
    const result: TrainingCoachBridge = {
      mode,
      title: copy.reportTitle(focus),
      prompt: reportPrompt(input, focus),
      detail: verified ? copy.reportDetailVerified : copy.reportDetailSubmitted,
      ctaLabel: trainingCoachCtaLabel(input.language, "result"),
      summaryLines: uniqueList(
        [
          verified ? copy.summaryVerified(verified) : undefined,
          !verified && submitted ? copy.summarySubmitted(submitted) : undefined,
          input.successSignal ? copy.summaryPassSignal(input.successSignal) : undefined,
          bringBack ? copy.summaryBringBack(bringBack) : undefined,
        ],
        4,
      ),
      trainingReturn: buildTrainingReturn(input, "report_result"),
    };
    const normalized = normalizeCoachReturnCopy(input.language, {
      title: result.title,
      detail: result.detail,
      summaryLines: result.summaryLines,
    });
    return {
      ...result,
      title: normalized.title ?? result.title,
      detail: normalized.detail ?? result.detail,
      summaryLines: normalized.summaryLines,
    };
  }

  if (mode === "unstick") {
    const result: TrainingCoachBridge = {
      mode,
      title: copy.unstickTitle(focus),
      prompt: unstickPrompt(input, focus),
      detail: copy.unstickDetail,
      ctaLabel: trainingCoachCtaLabel(input.language, "blocker"),
      summaryLines: uniqueList(
        [
          blocker ? copy.summaryBlocker(blocker) : undefined,
          input.reviewPartialProgress
            ? copy.summaryProgressSoFar(input.reviewPartialProgress)
            : undefined,
          bringBack ? copy.summaryBringBackFirst(bringBack) : undefined,
        ],
        4,
      ),
      trainingReturn: buildTrainingReturn(input, "unstick"),
    };
    const normalized = normalizeCoachReturnCopy(input.language, {
      title: result.title,
      detail: result.detail,
      summaryLines: result.summaryLines,
    });
    return {
      ...result,
      title: normalized.title ?? result.title,
      detail: normalized.detail ?? result.detail,
      summaryLines: normalized.summaryLines,
    };
  }

  const result: TrainingCoachBridge = {
    mode,
    title: copy.continueTitle(focus),
    prompt: continuePrompt(input, focus),
    detail: copy.continueDetail,
    ctaLabel: trainingCoachCtaLabel(input.language, "continue"),
    summaryLines: uniqueList(
      [
        compactList(input.learnerDeliverables, 1)[0]
          ? copy.summaryYouDeliver(compactList(input.learnerDeliverables, 1)[0])
          : undefined,
        compactList(input.verificationSteps, 1)[0]
          ? copy.summaryVerifyLikeThis(compactList(input.verificationSteps, 1)[0])
          : undefined,
        bringBack ? copy.summaryBringBack(bringBack) : undefined,
      ],
      4,
    ),
    trainingReturn: undefined,
  };
  const normalized = normalizeCoachReturnCopy(input.language, {
    title: result.title,
    detail: result.detail,
    summaryLines: result.summaryLines,
  });
  return {
    ...result,
    title: normalized.title ?? result.title,
    detail: normalized.detail ?? result.detail,
    summaryLines: normalized.summaryLines,
  };
}

export function composeTrainingCoachBridgeDraft(
  bridge: Pick<TrainingCoachBridge, "prompt" | "detail" | "summaryLines" | "title">,
): string {
  // The prompt already carries the full submission and requirements. Sidebar
  // summaries are shortened for display and must not be sent as duplicated data.
  if (bridge.prompt.trim()) {
    return bridge.prompt.trim();
  }
  const sections = uniqueList(
    [
      compact(bridge.prompt),
      compact(bridge.detail),
      bridge.summaryLines?.length
        ? uniqueList(bridge.summaryLines, 4)
            .map((line) => `- ${line}`)
            .join("\n")
        : undefined,
      compact(bridge.title),
    ],
    4,
  );
  return sections.join("\n\n");
}
