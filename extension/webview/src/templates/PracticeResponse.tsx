import { useState, type ReactNode } from "react";
import type { ComposerLanguage, MessageAttachment } from "../lib/types";
import { readImageAttachments } from "../lib/imageAttachments";
import { SystemState } from "./SystemState";

const COPY: Record<ComposerLanguage, { image: string; remove: string; error: string }> = {
  "zh-CN": { image: "附加作答图片", remove: "移除", error: "图片无法读取，请重试。" },
  "en-US": { image: "Attach answer image", remove: "Remove", error: "Could not read the image. Try again." },
  "es-ES": { image: "Adjuntar imagen", remove: "Quitar", error: "No se pudo leer la imagen. Inténtalo de nuevo." },
  "fr-FR": { image: "Joindre une image", remove: "Retirer", error: "Impossible de lire l’image. Réessayez." },
  "de-DE": { image: "Antwortbild anhängen", remove: "Entfernen", error: "Bild konnte nicht gelesen werden. Erneut versuchen." },
  "ja-JP": { image: "回答画像を添付", remove: "削除", error: "画像を読み込めません。再試行してください。" },
  "ko-KR": { image: "답변 이미지 첨부", remove: "제거", error: "이미지를 읽을 수 없습니다. 다시 시도하세요." },
  "pt-BR": { image: "Anexar imagem", remove: "Remover", error: "Não foi possível ler a imagem. Tente novamente." },
};

export interface PracticeResponseProps {
  language: ComposerLanguage;
  label: string;
  prompt?: string;
  value: string;
  submitLabel: string;
  busy?: boolean;
  disabled?: boolean;
  onChange: (value: string) => void;
  onSubmit: (value: string) => void;
  attachments?: MessageAttachment[];
  onAttachmentsChange?: (attachments: MessageAttachment[]) => void;
  attachmentsAvailable?: boolean;
  attachmentError?: string;
  children?: ReactNode;
}

/** Activity-owned answer/reflection, with no chat modes, model menu or history. */
export function PracticeResponse({ language, label, prompt, value, submitLabel, busy, disabled,
  onChange, onSubmit, attachments = [], onAttachmentsChange, attachmentsAvailable, attachmentError, children }: PracticeResponseProps) {
  const [error, setError] = useState<string>();
  const copy = COPY[language];
  const stageImages = async (files: FileList | File[]) => {
    if (!attachmentsAvailable || !onAttachmentsChange) { setError(attachmentError); return; }
    try {
      onAttachmentsChange([...attachments, ...await readImageAttachments(files)].slice(0, 4));
      setError(undefined);
    } catch { setError(copy.error); }
  };
  const hasContent = Boolean(value.trim() || attachments.length);
  return (
    <form className="template-practice-response" data-template="PracticeResponse" onSubmit={(event) => { event.preventDefault(); if (hasContent && !busy && !disabled) onSubmit(value); }}
      onDragOver={(event) => { if (attachmentsAvailable) event.preventDefault(); }}
      onDrop={(event) => { event.preventDefault(); if (!busy && !disabled) void stageImages(event.dataTransfer.files); }}>
      <label htmlFor="training-response">{label}</label>
      {prompt ? <p id="training-response-prompt" className="template-metadata">{prompt}</p> : null}
      {children}
      <textarea id="training-response" value={value} onChange={(event) => onChange(event.target.value)} rows={4} disabled={disabled || busy} aria-describedby={prompt ? "training-response-prompt" : undefined}
        onPaste={(event) => { if (event.clipboardData.files.length && !busy && !disabled) { event.preventDefault(); void stageImages(event.clipboardData.files); } }} />
      {attachmentsAvailable ? <label className="template-attachment-input">{copy.image}<input type="file" accept="image/*" multiple disabled={disabled || busy} onChange={(event) => { if (event.target.files) void stageImages(event.target.files); event.target.value = ""; }} /></label> : null}
      {attachments.map((attachment) => <div className="template-attachment" key={attachment.id}><span>{attachment.name}</span><button type="button" className="template-back" disabled={disabled || busy} onClick={() => onAttachmentsChange?.(attachments.filter((item) => item.id !== attachment.id))}>{copy.remove}</button></div>)}
      {error ? <SystemState kind="recoverable-error" title={error} /> : null}
      <button type="submit" className="button button--accent" data-primary-action="true" disabled={disabled || busy || !hasContent || (attachments.length > 0 && !attachmentsAvailable)} aria-busy={busy || undefined}>{submitLabel}</button>
    </form>
  );
}
