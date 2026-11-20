import type { ReactNode } from "react";

import type { ComposerLanguage } from "../../lib/types";

const COPY: Record<ComposerLanguage, { label: string; submit: string; busy: string }> = {
  "zh-CN": { label: "你的作答", submit: "提交", busy: "保存中…" },
  "en-US": { label: "Your answer", submit: "Submit", busy: "Saving…" },
  "es-ES": { label: "Tu respuesta", submit: "Enviar", busy: "Guardando…" },
  "fr-FR": { label: "Votre réponse", submit: "Envoyer", busy: "Enregistrement…" },
  "de-DE": { label: "Deine Antwort", submit: "Senden", busy: "Speichern…" },
  "ja-JP": { label: "あなたの回答", submit: "送信", busy: "保存中…" },
  "ko-KR": { label: "내 답변", submit: "제출", busy: "저장 중…" },
  "pt-BR": { label: "Sua resposta", submit: "Enviar", busy: "Salvando…" },
};

export interface InlinePracticeAnswerProps {
  language: ComposerLanguage;
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  busy?: boolean;
  placeholder?: string;
  prompt?: ReactNode;
  /**
   * The submit control is an input affordance, not always the phase's primary
   * action. When the card already owns a primary action for this phase (the
   * file-verification step), the answer stays secondary so the phase keeps
   * exactly one accent.
   */
  submitTone?: "accent" | "ghost";
  /**
   * Localized label for the phase's own submit action. The card owns the
   * phase, so the label names that action (record a reflection, submit an
   * answer) instead of a generic "submit".
   */
  submitLabel?: string;
}

/**
 * Practice answers live inside the card. The dock composer keeps serving the
 * conversation; sending a practice answer never routes through it.
 */
export function InlinePracticeAnswer({
  language,
  value,
  onChange,
  onSubmit,
  busy = false,
  placeholder,
  prompt,
  submitTone = "accent",
  submitLabel,
}: InlinePracticeAnswerProps) {
  const copy = COPY[language];
  const canSubmit = value.trim().length > 0 && !busy;
  const resolvedSubmitLabel = submitLabel?.trim() || copy.submit;
  return (
    <form
      className="inline-practice-answer"
      data-inline-practice-answer="true"
      onSubmit={(event) => {
        event.preventDefault();
        if (canSubmit) onSubmit();
      }}
    >
      {prompt}
      <label className="inline-practice-answer__label" htmlFor="inline-practice-answer-input">
        {copy.label}
      </label>
      <textarea
        id="inline-practice-answer-input"
        className="inline-practice-answer__input"
        value={value}
        rows={2}
        disabled={busy}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
      <button type="submit" className={`button button--${submitTone} inline-practice-answer__submit`} disabled={!canSubmit}>
        {busy ? copy.busy : resolvedSubmitLabel}
      </button>
    </form>
  );
}
