import type { ReactNode } from "react";

import type { ComposerLanguage } from "../../lib/types";

const COPY: Record<ComposerLanguage, { label: string; submit: string; busy: string }> = {
  "zh-CN": { label: "作答内容", submit: "提交作答", busy: "正在提交…" },
  "en-US": { label: "Response", submit: "Submit response", busy: "Submitting…" },
  "es-ES": { label: "Respuesta", submit: "Enviar respuesta", busy: "Enviando…" },
  "fr-FR": { label: "Réponse", submit: "Envoyer la réponse", busy: "Envoi…" },
  "de-DE": { label: "Antwort", submit: "Antwort senden", busy: "Wird gesendet…" },
  "ja-JP": { label: "回答内容", submit: "回答を提出", busy: "送信中…" },
  "ko-KR": { label: "답안 내용", submit: "답안 제출", busy: "제출 중…" },
  "pt-BR": { label: "Resposta", submit: "Enviar resposta", busy: "Enviando…" },
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
