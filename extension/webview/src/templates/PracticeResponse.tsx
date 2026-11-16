import { useRef, type ReactNode } from "react";
import { AttachmentIcon, CloseIcon, SendIcon } from "../components/icons";
import type { ComposerLanguage, MessageAttachment } from "../lib/types";
import { useImageAttachmentStaging } from "../lib/useImageAttachmentStaging";
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
  placeholder?: string;
  value: string;
  submitLabel: string;
  busy?: boolean;
  disabled?: boolean;
  onChange: (value: string) => void;
  onSubmit: (value: string) => void;
  attachments?: MessageAttachment[];
  attachmentScope?: string;
  onAttachmentsChange?: (attachments: MessageAttachment[]) => void;
  attachmentsAvailable?: boolean;
  attachmentError?: string;
  children?: ReactNode;
}

/** Activity-owned answer/reflection, with no chat modes, model menu or history. */
export function PracticeResponse({ language, label, prompt, placeholder, value, submitLabel, busy, disabled,
  onChange, onSubmit, attachments = [], attachmentScope = "practice-response", onAttachmentsChange, attachmentsAvailable, attachmentError, children }: PracticeResponseProps) {
  const imageStaging = useImageAttachmentStaging({ scope: attachmentScope, language, attachments, onChange: onAttachmentsChange });
  const copy = COPY[language];
  const fileInputRef = useRef<HTMLInputElement>(null);
  const stageImages = async (files: FileList | File[]) => {
    if (attachmentsAvailable && onAttachmentsChange) await imageStaging.stage(files);
  };
  const canSubmit = !disabled && !busy && !imageStaging.busy &&
    Boolean(value.trim() || attachments.length) && (!attachments.length || attachmentsAvailable);
  return (
    <div className="composer-shell--quiet template-practice-response">
      <form
        className="composer"
        data-template="PracticeResponse"
        aria-busy={busy || undefined}
        onSubmit={(event) => {
          event.preventDefault();
          if (canSubmit) onSubmit(value);
        }}
        onDragOver={(event) => { if (attachmentsAvailable) event.preventDefault(); }}
        onDrop={(event) => {
          event.preventDefault();
          if (!busy && !disabled) void stageImages(event.dataTransfer.files);
        }}
      >
        <label className="sr-only" htmlFor="training-response">{label}</label>
        {prompt ? <p id="training-response-prompt" className="template-metadata">{prompt}</p> : null}
        {children}
        {attachments.length > 0 ? <div className="composer__attachments">
          {attachments.map((attachment) => (
            <span className="composer__attachment-chip" key={attachment.id}>
              <span className="composer__attachment-label">{attachment.name}</span>
              <button type="button" className="composer__attachment-remove" aria-label={copy.remove} disabled={disabled || busy} onClick={() => onAttachmentsChange?.(attachments.filter((item) => item.id !== attachment.id))}>
                <CloseIcon size={12} />
              </button>
            </span>
          ))}
        </div> : null}
        {(imageStaging.error || (attachments.length > 0 && attachmentError)) ? (
          <SystemState kind="recoverable-error" title={imageStaging.error ?? attachmentError ?? copy.error} />
        ) : null}
        <div className="composer__body">
          <div className="composer__frame">
            <textarea
              id="training-response"
              value={value}
              placeholder={placeholder ?? label}
              onChange={(event) => onChange(event.target.value)}
              rows={2}
              disabled={disabled || busy}
              aria-describedby={prompt ? "training-response-prompt" : undefined}
              onKeyDown={(event) => {
                if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing || event.keyCode === 229) return;
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }}
              onPaste={(event) => {
                if (!attachmentsAvailable || !event.clipboardData.files.length || busy || disabled) return;
                event.preventDefault();
                void stageImages(event.clipboardData.files);
              }}
            />
          </div>
        </div>
        <div className="composer__footer">
          <div className="composer__actions">
            {attachmentsAvailable ? <>
              <input ref={fileInputRef} type="file" accept="image/*" multiple hidden onChange={(event) => {
                if (event.target.files) void stageImages(event.target.files);
                event.target.value = "";
              }} />
              <button type="button" className="icon-button" aria-label={copy.image} title={copy.image} disabled={disabled || busy} onClick={() => fileInputRef.current?.click()}>
                <AttachmentIcon size={16} />
              </button>
            </> : null}
            <div className="composer__send-wrap">
              <button type="submit" className="composer__send" data-primary-action="true" aria-label={submitLabel} title={submitLabel} disabled={!canSubmit}>
                <SendIcon size={16} />
              </button>
            </div>
          </div>
        </div>
      </form>
    </div>
  );
}
