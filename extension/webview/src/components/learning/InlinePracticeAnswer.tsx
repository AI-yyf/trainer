import type { ReactNode } from "react";

import type { ComposerLanguage } from "../../lib/types";

const COPY: Record<ComposerLanguage, { cue: string; reflectCue: string; focusAction: string }> = {
  "zh-CN": {
    cue: "请在下方输入框作答、追问提示或提交说明。",
    reflectCue: "请在下方输入框写下复盘结论并提交。",
    focusAction: "前往输入框",
  },
  "en-US": {
    cue: "Answer, ask for a hint, or describe your result in the input box below.",
    reflectCue: "Write your reflection in the input box below to record it.",
    focusAction: "Focus input",
  },
  "es-ES": {
    cue: "Responde, pide una pista o describe tu resultado en el cuadro inferior.",
    reflectCue: "Escribe tu reflexión en el cuadro inferior para registrarla.",
    focusAction: "Ir al cuadro",
  },
  "fr-FR": {
    cue: "Répondez, demandez un indice ou décrivez votre résultat dans la zone de saisie ci-dessous.",
    reflectCue: "Rédigez votre réflexion dans la zone de saisie ci-dessous pour l'enregistrer.",
    focusAction: "Aller à la saisie",
  },
  "de-DE": {
    cue: "Antworten, einen Hinweis anfordern oder das Ergebnis im Eingabefeld unten eintragen.",
    reflectCue: "Reflexion im Eingabefeld unten eintragen und absenden.",
    focusAction: "Zum Eingabefeld",
  },
  "ja-JP": {
    cue: "下の入力欄から回答、ヒントの質問、または結果の報告を行ってください。",
    reflectCue: "下の入力欄に振り返りを記入して送信してください。",
    focusAction: "入力欄へ移動",
  },
  "ko-KR": {
    cue: "아래 입력창에서 답안 제출, 힌트 요청 또는 결과 보고를 진행하세요.",
    reflectCue: "아래 입력창에 회고 내용을 작성해 제출하세요.",
    focusAction: "입력창으로 이동",
  },
  "pt-BR": {
    cue: "Responda, peça uma dica ou relate seu resultado na caixa de entrada abaixo.",
    reflectCue: "Escreva sua reflexão na caixa de entrada abaixo para registrá-la.",
    focusAction: "Ir para a entrada",
  },
};

export interface InlinePracticeAnswerProps {
  language: ComposerLanguage;
  reflectMode?: boolean;
  prompt?: ReactNode;
  onFocusComposer?: () => void;
}

/**
 * Single-composer sovereignty: the inline practice card never mounts a second
 * competing textarea. Answers, hints, and reflections route through the single
 * docked CoachComposer at the bottom of the workbench.
 */
export function InlinePracticeAnswer({
  language,
  reflectMode = false,
  prompt,
  onFocusComposer,
}: InlinePracticeAnswerProps) {
  const copy = COPY[language] ?? COPY["en-US"];
  return (
    <div
      className="inline-practice-answer"
      data-inline-practice-answer="true"
      data-single-composer-cue="true"
    >
      {prompt}
      <p
        className="inline-practice-answer__cue"
        onClick={onFocusComposer}
        role={onFocusComposer ? "button" : undefined}
        tabIndex={onFocusComposer ? 0 : undefined}
        onKeyDown={
          onFocusComposer
            ? (event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onFocusComposer();
                }
              }
            : undefined
        }
      >
        {reflectMode ? copy.reflectCue : copy.cue}
      </p>
    </div>
  );
}
