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
    const verifiedResult = firstText(input.latestVerifiedResult, input.reviewSummary, input.successSignal);
    const summary = firstText(
      input.reviewSummary,
      input.latestVerifiedResult,
      input.successSignal,
      input.returnWith,
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
      compact(input.reviewSummary) ||
      compact(input.successSignal) ||
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

function focusLabel(input: TrainingCoachBridgeInput): string {
  return (
    firstText(input.cardTitle, input.focusArea, input.taskTitle) ||
    (input.language === "zh-CN" ? "当前训练卡" : "the current training card")
  );
}

function reportPrompt(input: TrainingCoachBridgeInput, focus: string): string {
  const verified = firstText(input.latestVerifiedResult, input.reviewSummary);
  const bringBack = firstText(
    input.returnWith,
    input.latestFollowup,
    input.reviewNextRule,
    input.reviewRecommendedActions?.[0],
  );
  const passSignal = compact(input.successSignal);
  if (input.language === "zh-CN") {
    return [
      `请继续围绕「${focus}」做 coach-only 评估，不要替我改代码。`,
      verified
        ? `我已经完成了这一轮，并带回这条验证结果：${verified}`
        : "我已经完成了这一轮，需要你先评估结果。",
      passSignal ? `这张卡的过关信号是：${passSignal}` : undefined,
      bringBack
        ? `我按要求带回的是：${bringBack}`
        : "请先判断这次结果是通过、部分通过、误解，还是需要降级。",
      "请你先评估，再决定是复盘、纳入计划证据、补闪记，还是给我下一张更合适的卡。",
    ]
      .filter(Boolean)
      .join(" ");
  }
  return [
    `Keep coaching around "${focus}" and stay coach-only. Do not edit code for me.`,
    verified
      ? `I finished this loop and brought back this verification result: ${verified}`
      : "I finished this loop and need you to evaluate the result first.",
    passSignal ? `The pass signal for this card was: ${passSignal}` : undefined,
    bringBack
      ? `Here is what I was supposed to bring back: ${bringBack}`
      : "First decide whether this was a pass, partial pass, misunderstanding, or a loop that should be downgraded.",
    "Evaluate it first, then decide whether it should become review, plan evidence, flash reinforcement, or the next card.",
  ]
    .filter(Boolean)
    .join(" ");
}

function unstickPrompt(input: TrainingCoachBridgeInput, focus: string): string {
  const progress = firstText(
    input.reviewPartialProgress,
    input.latestVerifiedResult,
    input.learnerDeliverables?.[0],
  );
  const blocker = firstText(
    input.reviewBlocker,
    input.reviewAbandonReason,
    input.latestFollowup,
    input.reviewRootCause,
  );
  if (input.language === "zh-CN") {
    return [
      `请继续围绕「${focus}」做 coach-only 指导，不要替我改代码。`,
      progress ? `我已经推进到：${progress}` : "我已经尝试了这张训练卡，但卡住了。",
      blocker ? `当前卡点是：${blocker}` : "我需要你先帮我判断为什么这轮会卡住。",
      "请你先判断根因更像理论、API、边界、验证还是资料问题，再决定该复盘、补闪记、压成更小实战，还是先回资料。",
    ]
      .filter(Boolean)
      .join(" ");
  }
  return [
    `Keep coaching around "${focus}" and stay coach-only. Do not edit code for me.`,
    progress ? `I got as far as: ${progress}` : "I tried this training card but got stuck.",
    blocker ? `The current blocker is: ${blocker}` : "Help me identify why this loop is stuck.",
    "First decide whether the root cause is theory, API usage, boundary judgment, verification, or missing material, then choose whether to review, flash, downgrade the practice slice, or go back to Resources.",
  ]
    .filter(Boolean)
    .join(" ");
}

function continuePrompt(input: TrainingCoachBridgeInput, focus: string): string {
  const deliverable = compactList(input.learnerDeliverables, 1)[0];
  const verification = compactList(input.verificationSteps, 1)[0];
  if (input.language === "zh-CN") {
    return [
      `请继续围绕「${focus}」做 coach-only 指导，不要替我改代码。`,
      deliverable ? `我接下来会自己完成：${deliverable}` : "请先继续压清这张训练卡的下一步。",
      verification ? `我会先这样验证：${verification}` : undefined,
      "请告诉我从哪个文件或边界开始、我自己要写什么、以及做完后该带什么结果回给你。",
    ]
      .filter(Boolean)
      .join(" ");
  }
  return [
    `Keep coaching around "${focus}" and stay coach-only. Do not edit code for me.`,
    deliverable ? `I will implement this next: ${deliverable}` : "Keep compressing the next move for this training card.",
    verification ? `I plan to verify it like this: ${verification}` : undefined,
    "Tell me which file or boundary to start from, what I should write myself, and what result I should bring back to you afterward.",
  ]
    .filter(Boolean)
    .join(" ");
}

export function buildTrainingCoachBridge(input: TrainingCoachBridgeInput): TrainingCoachBridge {
  const focus = focusLabel(input);
  const mode = hasReportableResult(input)
    ? "report_result"
    : hasStallSignal(input)
      ? "unstick"
      : "continue_task";
  const verified = firstText(input.latestVerifiedResult, input.reviewSummary);
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
      title:
        input.language === "zh-CN"
          ? `把「${focus}」的结果带回教练`
          : `Bring the "${focus}" result back to coach`,
      prompt: reportPrompt(input, focus),
      detail:
        input.language === "zh-CN"
          ? "把验证结果带回对话，让教练先判定通过程度，再决定复盘、计划证据、闪记补漏还是下一张卡。"
          : "Bring the verification result back so the coach can score the loop before choosing review, plan evidence, flash reinforcement, or the next card.",
      ctaLabel: trainingCoachCtaLabel(input.language, "result"),
      summaryLines: uniqueList(
        [
          verified
            ? input.language === "zh-CN"
              ? `验证结果：${verified}`
              : `Verification result: ${verified}`
            : undefined,
          input.successSignal
            ? input.language === "zh-CN"
              ? `过关信号：${input.successSignal}`
              : `Pass signal: ${input.successSignal}`
            : undefined,
          bringBack
            ? input.language === "zh-CN"
              ? `回带内容：${bringBack}`
              : `Bring back: ${bringBack}`
            : undefined,
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
      title:
        input.language === "zh-CN"
          ? `把「${focus}」的卡点带回教练`
          : `Bring the "${focus}" blocker back to coach`,
      prompt: unstickPrompt(input, focus),
      detail:
        input.language === "zh-CN"
          ? "把当前卡点带回对话，让教练先判断根因属于哪一层，再决定复盘、闪记、降级实战或回资料。"
          : "Bring the current blocker back so the coach can diagnose the layer first, then choose review, flash, a smaller practice slice, or Resources.",
      ctaLabel: trainingCoachCtaLabel(input.language, "blocker"),
      summaryLines: uniqueList(
        [
          blocker
            ? input.language === "zh-CN"
              ? `当前卡点：${blocker}`
              : `Current blocker: ${blocker}`
            : undefined,
          input.reviewPartialProgress
            ? input.language === "zh-CN"
              ? `已推进到：${input.reviewPartialProgress}`
              : `Progress so far: ${input.reviewPartialProgress}`
            : undefined,
          bringBack
            ? input.language === "zh-CN"
              ? `先回带：${bringBack}`
              : `Bring back first: ${bringBack}`
            : undefined,
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
    title:
      input.language === "zh-CN"
        ? `围绕「${focus}」继续教练指导`
        : `Keep coaching around "${focus}"`,
    prompt: continuePrompt(input, focus),
    detail:
      input.language === "zh-CN"
        ? "先把下一小步和验证方式说清楚，再继续这张训练卡。"
        : "Compress the next slice and the first verification before continuing this card.",
    ctaLabel: trainingCoachCtaLabel(input.language, "continue"),
    summaryLines: uniqueList(
      [
        compactList(input.learnerDeliverables, 1)[0]
          ? input.language === "zh-CN"
            ? `你来交付：${compactList(input.learnerDeliverables, 1)[0]}`
            : `You deliver: ${compactList(input.learnerDeliverables, 1)[0]}`
          : undefined,
        compactList(input.verificationSteps, 1)[0]
          ? input.language === "zh-CN"
            ? `先这样验：${compactList(input.verificationSteps, 1)[0]}`
            : `Verify like this: ${compactList(input.verificationSteps, 1)[0]}`
          : undefined,
        bringBack
          ? input.language === "zh-CN"
            ? `做完带回：${bringBack}`
            : `Bring back: ${bringBack}`
          : undefined,
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
