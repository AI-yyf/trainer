import {
  useEffect,
  useRef,
  useCallback,
  useState,
  type ClipboardEvent,
  type DragEvent,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
} from "react";

import type { ComposerLanguage, MessageAttachment } from "../../lib/types";
import { AttachmentIcon, CheckMarkIcon, CloseIcon, PlusIcon, SendIcon, SquareIcon } from "../icons";
import { ComposerIconButton } from "./ComposerIconButton";

const MAX_STAGED_ATTACHMENTS = 4;

type ComposerLocaleCopy = {
  placeholder: string;
  busyLabel: string;
  accessibilityLabel: string;
  submitLabel: string;
  cancelLabel: string;
  emptySubmitLabel: string;
  blockedSubmitLabel: string;
  attachmentCount: (count: number) => string;
  attachmentCapability: string;
  dropToAttach: string;
  imageUnavailable: string;
  image: string;
  removeAttachment: string;
  clear: string;
  plusMenu: string;
};

const composerLocaleCopy: Record<ComposerLanguage, ComposerLocaleCopy> = {
  "zh-CN": {
    placeholder: "问教练",
    busyLabel: "教练正在思考",
    accessibilityLabel: "向教练发送消息",
    submitLabel: "发送消息",
    cancelLabel: "取消回复",
    emptySubmitLabel: "输入消息或拖入图片后发送",
    blockedSubmitLabel: "当前无法发送",
    attachmentCount: (count) => `已附加 ${count}/${MAX_STAGED_ATTACHMENTS} 张图片`,
    attachmentCapability: "当前连接暂不支持图片输入。",
    dropToAttach: "松开以附加图片",
    imageUnavailable: "当前连接暂不支持图片输入",
    image: "图片",
    removeAttachment: "移除附件",
    clear: "清空",
    plusMenu: "给这一条加点东西",
  },
  "en-US": {
    placeholder: "Ask the coach",
    busyLabel: "Trainer is thinking",
    accessibilityLabel: "Send a message to the coach",
    submitLabel: "Send message",
    cancelLabel: "Cancel reply",
    emptySubmitLabel: "Write a message or drop an image to send",
    blockedSubmitLabel: "Sending is unavailable",
    attachmentCount: (count) => `${count} of ${MAX_STAGED_ATTACHMENTS} images attached`,
    attachmentCapability: "Image input is not available for this connection yet.",
    dropToAttach: "Drop to attach image",
    imageUnavailable: "Image input is unavailable for this connection",
    image: "image",
    removeAttachment: "Remove attachment",
    clear: "Clear",
    plusMenu: "Add to this message",
  },
  "es-ES": {
    placeholder: "Dile al entrenador qué quieres construir o dónde te has atascado.",
    busyLabel: "El entrenador está pensando",
    accessibilityLabel: "Enviar un mensaje al entrenador",
    submitLabel: "Enviar mensaje",
    cancelLabel: "Cancelar respuesta",
    emptySubmitLabel: "Escribe un mensaje o suelta una imagen para enviarlo",
    blockedSubmitLabel: "Ahora no se puede enviar",
    attachmentCount: (count) => `${count} de ${MAX_STAGED_ATTACHMENTS} imágenes adjuntas`,
    attachmentCapability: "Esta conexión todavía no admite imágenes.",
    dropToAttach: "Suelta para adjuntar una imagen",
    imageUnavailable: "Las imágenes no están disponibles para esta conexión",
    image: "imagen",
    removeAttachment: "Quitar archivo adjunto",
    clear: "Limpiar",
    plusMenu: "Añadir a este mensaje",
  },
  "fr-FR": {
    placeholder: "Dites au coach ce que vous voulez créer ou où vous êtes bloqué.",
    busyLabel: "Le coach réfléchit",
    accessibilityLabel: "Envoyer un message au coach",
    submitLabel: "Envoyer le message",
    cancelLabel: "Annuler la réponse",
    emptySubmitLabel: "Écrivez un message ou déposez une image pour l’envoyer",
    blockedSubmitLabel: "L’envoi est indisponible pour le moment",
    attachmentCount: (count) => `${count}/${MAX_STAGED_ATTACHMENTS} images jointes`,
    attachmentCapability: "Cette connexion ne prend pas encore en charge les images.",
    dropToAttach: "Déposez pour joindre une image",
    imageUnavailable: "Les images ne sont pas disponibles avec cette connexion",
    image: "image",
    removeAttachment: "Retirer la pièce jointe",
    clear: "Effacer",
    plusMenu: "Ajouter à ce message",
  },
  "de-DE": {
    placeholder: "Sag dem Coach, was du bauen möchtest oder wo du festhängst.",
    busyLabel: "Coach denkt nach",
    accessibilityLabel: "Nachricht an den Coach senden",
    submitLabel: "Nachricht senden",
    cancelLabel: "Antwort abbrechen",
    emptySubmitLabel: "Schreibe eine Nachricht oder ziehe ein Bild hierher, um es zu senden",
    blockedSubmitLabel: "Senden ist derzeit nicht möglich",
    attachmentCount: (count) => `${count} von ${MAX_STAGED_ATTACHMENTS} Bildern angehängt`,
    attachmentCapability: "Diese Verbindung unterstützt noch keine Bildeingaben.",
    dropToAttach: "Loslassen, um ein Bild anzuhängen",
    imageUnavailable: "Bildeingaben sind für diese Verbindung nicht verfügbar",
    image: "Bild",
    removeAttachment: "Anhang entfernen",
    clear: "Leeren",
    plusMenu: "Dieser Nachricht hinzufügen",
  },
  "ja-JP": {
    placeholder: "作りたいものや、行き詰まっている箇所をコーチに伝えてください。",
    busyLabel: "コーチが考えています",
    accessibilityLabel: "コーチにメッセージを送信",
    submitLabel: "メッセージを送信",
    cancelLabel: "返信をキャンセル",
    emptySubmitLabel: "メッセージを入力するか、画像をドロップして送信",
    blockedSubmitLabel: "現在は送信できません",
    attachmentCount: (count) => `${count}/${MAX_STAGED_ATTACHMENTS} 枚の画像を添付済み`,
    attachmentCapability: "この接続ではまだ画像を入力できません。",
    dropToAttach: "画像をドロップして添付",
    imageUnavailable: "この接続では画像を入力できません",
    image: "画像",
    removeAttachment: "添付を削除",
    clear: "消去",
    plusMenu: "このメッセージに追加",
  },
  "ko-KR": {
    placeholder: "만들고 싶은 것 또는 막힌 지점을 코치에게 알려 주세요.",
    busyLabel: "코치가 생각 중입니다",
    accessibilityLabel: "코치에게 메시지 보내기",
    submitLabel: "메시지 보내기",
    cancelLabel: "답변 취소",
    emptySubmitLabel: "메시지를 입력하거나 이미지를 놓아 보내세요",
    blockedSubmitLabel: "현재 보낼 수 없습니다",
    attachmentCount: (count) => `${count}/${MAX_STAGED_ATTACHMENTS}개 이미지 첨부됨`,
    attachmentCapability: "이 연결에서는 아직 이미지를 입력할 수 없습니다.",
    dropToAttach: "이미지를 놓아 첨부",
    imageUnavailable: "이 연결에서는 이미지 입력을 사용할 수 없습니다",
    image: "이미지",
    removeAttachment: "첨부 파일 제거",
    clear: "지우기",
    plusMenu: "이 메시지에 추가",
  },
  "pt-BR": {
    placeholder: "Diga ao coach o que você quer criar ou onde está com dificuldade.",
    busyLabel: "O coach está pensando",
    accessibilityLabel: "Enviar uma mensagem ao coach",
    submitLabel: "Enviar mensagem",
    cancelLabel: "Cancelar resposta",
    emptySubmitLabel: "Escreva uma mensagem ou solte uma imagem para enviar",
    blockedSubmitLabel: "Não é possível enviar agora",
    attachmentCount: (count) => `${count}/${MAX_STAGED_ATTACHMENTS} imagens anexadas`,
    attachmentCapability: "Esta conexão ainda não aceita imagens.",
    dropToAttach: "Solte para anexar uma imagem",
    imageUnavailable: "As imagens não estão disponíveis nesta conexão",
    image: "imagem",
    removeAttachment: "Remover anexo",
    clear: "Limpar",
    plusMenu: "Adicionar a esta mensagem",
  },
};

export interface ComposerActionItem {
  id: string;
  label: string;
  icon: ReactNode;
  active?: boolean;
  disabled?: boolean;
  pinned?: boolean;
  onClick?: () => void;
}

export interface ComposerSecondaryAction {
  id: string;
  label: string;
  title?: string;
  ariaLabel?: string;
  icon?: ReactNode;
  compact?: boolean;
  disabled?: boolean;
  tone?: "accent" | "ghost";
  type?: "button" | "submit";
  onClick?: () => void;
}

export interface ComposerModeControl {
  id: string;
  label: string;
  value: string;
  options: Array<{
    value: string;
    label: string;
    description?: string;
  }>;
  disabled?: boolean;
  onChange: (value: string) => void;
}

export interface CoachComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onCancel?: () => void;
  density?: "default" | "compact";
  placeholder?: string;
  disabled?: boolean;
  submitDisabled?: boolean;
  busy?: boolean;
  busyLabel?: string;
  textareaId?: string;
  minRows?: number;
  submitLabel?: string;
  cancelLabel?: string;
  submitAriaLabel?: string;
  emptySubmitAriaLabel?: string;
  accessibilityLabel?: string;
  allowEmptySubmit?: boolean;
  inputReadOnly?: boolean;
  summary?: string;
  hintText?: string;
  shortcutHint?: string;
  leadingActions?: ComposerActionItem[];
  secondaryActions?: ComposerSecondaryAction[];
  modeControl?: ComposerModeControl;
  showCharCount?: boolean;
  maxLength?: number;
  language?: ComposerLanguage;
  onKeyDown?: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
  onNavigateHistory?: (direction: "previous" | "next") => boolean;
  accessory?: ReactNode;
  /** Image attachments staged for the next send (paste / drop). */
  attachments?: MessageAttachment[];
  onAttachmentsChange?: (attachments: MessageAttachment[]) => void;
  attachmentsAvailable?: boolean;
  attachmentsUnavailableReason?: string;
  submitBlockedReason?: string;
}

export function CoachComposer({
  value,
  onChange,
  onSubmit,
  onCancel,
  density = "default",
  placeholder,
  disabled = false,
  submitDisabled = false,
  busy = false,
  busyLabel,
  textareaId = "coach-composer",
  minRows = 2,
  submitLabel = "",
  cancelLabel,
  submitAriaLabel,
  emptySubmitAriaLabel,
  accessibilityLabel,
  allowEmptySubmit = false,
  inputReadOnly = false,
  summary,
  hintText,
  shortcutHint,
  leadingActions,
  secondaryActions,
  modeControl,
  showCharCount = true,
  maxLength = 2000,
  language = "zh-CN",
  onKeyDown,
  onNavigateHistory,
  accessory,
  attachments,
  onAttachmentsChange,
  attachmentsAvailable = true,
  attachmentsUnavailableReason,
  submitBlockedReason,
}: CoachComposerProps) {
  const localizedCopy = composerLocaleCopy[language] ?? composerLocaleCopy["en-US"];
  const resolvedPlaceholder = placeholder ?? localizedCopy.placeholder;
  const resolvedBusyLabel = busyLabel ?? localizedCopy.busyLabel;
  const resolvedCancelLabel = cancelLabel ?? localizedCopy.cancelLabel;
  const resolvedAccessibilityLabel = accessibilityLabel ?? localizedCopy.accessibilityLabel;
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const modeControlRef = useRef<HTMLDivElement | null>(null);
  const modeOptionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const plusControlRef = useRef<HTMLDivElement | null>(null);
  const plusOptionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const dragDepthRef = useRef(0);
  const sideButtonHandledRef = useRef<number | null>(null);
  const [showAttachmentCapabilityNote, setShowAttachmentCapabilityNote] = useState(false);
  const [isDragActive, setIsDragActive] = useState(false);
  const [isModeMenuOpen, setIsModeMenuOpen] = useState(false);
  const [isPlusMenuOpen, setIsPlusMenuOpen] = useState(false);
  const compactMode = density === "compact";
  const isTextareaDisabled = disabled || busy;
  const attachmentsEnabled = Boolean(onAttachmentsChange) && !inputReadOnly;
  const attachmentsInteractive = attachmentsEnabled && attachmentsAvailable;
  const stagedAttachments = attachments ?? [];
  const attachmentCapabilityText = attachmentsEnabled && !attachmentsInteractive
    ? attachmentsUnavailableReason?.trim() ||
      localizedCopy.attachmentCapability
    : "";
  const attachmentCapabilityNoteId = `${textareaId}-attachment-capability-note`;
  const submitBlockedReasonId = `${textareaId}-submit-blocked-reason`;
  const composerStatusId = `${textareaId}-status`;
  const revealAttachmentCapabilityNote = useCallback(() => {
    setShowAttachmentCapabilityNote(true);
  }, []);

  useEffect(() => {
    if (attachmentsInteractive) {
      setShowAttachmentCapabilityNote(false);
    }
  }, [attachmentsInteractive]);

  const handleAttachFiles = useCallback(
    async (files: FileList | File[]) => {
      if (!attachmentsInteractive || !onAttachmentsChange) {
        return;
      }
      const list = Array.from(files);
      if (list.length === 0) {
        return;
      }
      const next: MessageAttachment[] = [];
      for (const file of list) {
        const isImage = file.type.startsWith("image/");
        if (!isImage) {
          continue;
        }
        const buffer = await file.arrayBuffer();
        const bytes = new Uint8Array(buffer);
        let binary = "";
        for (let i = 0; i < bytes.byteLength; i += 1) {
          binary += String.fromCharCode(bytes[i] ?? 0);
        }
        next.push({
          id: `${Date.now()}-${file.name}`,
          kind: "image",
          mimeType: file.type || "image/png",
          dataBase64: btoa(binary),
          name: file.name,
          byteSize: file.size,
        });
      }
      if (next.length === 0) {
        return;
      }
      onAttachmentsChange([...stagedAttachments, ...next].slice(0, MAX_STAGED_ATTACHMENTS));
    },
    [attachmentsInteractive, onAttachmentsChange, stagedAttachments],
  );

  const handlePaste = useCallback(
    (event: ClipboardEvent<HTMLTextAreaElement>) => {
      const items = Array.from(event.clipboardData.items);
      const images = items
        .filter((item) => item.type.startsWith("image/"))
        .map((item) => item.getAsFile())
        .filter((file): file is File => Boolean(file));
      if (images.length === 0) {
        return;
      }
      if (!attachmentsInteractive || !onAttachmentsChange) {
        revealAttachmentCapabilityNote();
        return;
      }
      event.preventDefault();
      void handleAttachFiles(images);
    },
    [attachmentsInteractive, onAttachmentsChange, handleAttachFiles, revealAttachmentCapabilityNote],
  );

  const handleDragEnter = useCallback(
    (event: DragEvent<HTMLDivElement>) => {
      if (!Array.from(event.dataTransfer.types).includes("Files")) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      dragDepthRef.current += 1;
      if (attachmentsEnabled) {
        setIsDragActive(true);
      }
    },
    [attachmentsEnabled],
  );

  const handleDragOver = useCallback(
    (event: DragEvent<HTMLDivElement>) => {
      if (!Array.from(event.dataTransfer.types).includes("Files")) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      event.dataTransfer.dropEffect = attachmentsInteractive ? "copy" : "none";
    },
    [attachmentsInteractive],
  );

  const handleDragLeave = useCallback((event: DragEvent<HTMLDivElement>) => {
    if (!Array.from(event.dataTransfer.types).includes("Files")) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
    if (dragDepthRef.current === 0) {
      setIsDragActive(false);
    }
  }, []);

  const handleDrop = useCallback(
    (event: DragEvent<HTMLDivElement>) => {
      if (!Array.from(event.dataTransfer.types).includes("Files")) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      dragDepthRef.current = 0;
      setIsDragActive(false);
      if (!attachmentsInteractive || !onAttachmentsChange) {
        revealAttachmentCapabilityNote();
        return;
      }
      void handleAttachFiles(event.dataTransfer.files);
    },
    [attachmentsInteractive, onAttachmentsChange, handleAttachFiles, revealAttachmentCapabilityNote],
  );

  const handleRemoveAttachment = useCallback(
    (id: string) => {
      if (!onAttachmentsChange) {
        return;
      }
      onAttachmentsChange(stagedAttachments.filter((item) => item.id !== id));
    },
    [onAttachmentsChange, stagedAttachments],
  );
  const areActionsDisabled = disabled || busy;
  const trimmedValue = value.trim();
  const hasSubmissionContent = trimmedValue.length > 0 || stagedAttachments.length > 0;
  const hasSubmissionPermission = allowEmptySubmit || hasSubmissionContent;
  const isSubmitDisabled = submitDisabled || !hasSubmissionPermission;
  const canSubmit = !isTextareaDisabled && !isSubmitDisabled;
  const sendState = busy ? "streaming" : submitDisabled ? "blocked" : hasSubmissionPermission ? "ready" : "idle";
  const resolvedSummary = summary?.trim() ? summary : undefined;
  const resolvedHintText = hintText?.trim() ? hintText : undefined;
  const primaryHelperText = busy ? resolvedBusyLabel : resolvedSummary ?? resolvedHintText;
  const resolvedShortcutHint = !busy && shortcutHint?.trim() ? shortcutHint : undefined;
  const resolvedLeadingActions = leadingActions ?? [];
  const resolvedSecondaryActions = secondaryActions ?? [];
  const pinnedLeadingActions = resolvedLeadingActions.filter((action) => action.pinned);
  const plusMenuActions = resolvedLeadingActions.filter((action) => !action.pinned);
  const hasLeadingActions = resolvedLeadingActions.length > 0;
  const hasPinnedLeadingActions = pinnedLeadingActions.length > 0;
  const hasPlusMenu = plusMenuActions.length > 0;
  const hasSecondaryActions = resolvedSecondaryActions.length > 0;
  const hasModeControl = Boolean(modeControl);
  const selectedModeOption = modeControl?.options.find((option) => option.value === modeControl.value) ?? modeControl?.options[0];
  const modeMenuId = `${modeControl?.id ?? textareaId}-menu`;
  const plusMenuId = `${textareaId}-plus-menu`;
  const plusMenuAriaLabel = localizedCopy.plusMenu;
  const showToolbarDivider = hasLeadingActions || hasSecondaryActions || hasModeControl;
  const showHelperText = Boolean(
    busy ||
      resolvedSummary ||
      (resolvedHintText && trimmedValue.length > 0 && trimmedValue.length < 24) ||
      (resolvedShortcutHint && trimmedValue.length === 0),
  );
  const classes = [
    "composer",
    compactMode ? "composer--compact" : "",
    primaryHelperText || resolvedShortcutHint ? "composer--with-helper" : "composer--quiet",
    hasLeadingActions ? "composer--with-leading-actions" : "",
    hasSecondaryActions ? "composer--with-secondary-actions" : "",
  ]
    .filter(Boolean)
    .join(" ");
  const submitButtonLabel =
    submitAriaLabel?.trim() || accessibilityLabel?.trim() || submitLabel?.trim() || localizedCopy.submitLabel;
  const emptySubmitLabel = emptySubmitAriaLabel?.trim() || localizedCopy.emptySubmitLabel;
  const blockedSubmitLabel = localizedCopy.blockedSubmitLabel;
  const resolvedSubmitButtonLabel = busy
    ? resolvedBusyLabel
    : submitDisabled && hasSubmissionContent
      ? blockedSubmitLabel
      : !hasSubmissionPermission
        ? emptySubmitLabel
        : submitButtonLabel;
  const attachmentCountLabel = localizedCopy.attachmentCount(stagedAttachments.length);
  const resolvedSubmitBlockedReason = submitBlockedReason?.trim() || "";
  const composerStatusText = busy
    ? resolvedBusyLabel
    : submitDisabled && hasSubmissionContent
      ? resolvedSubmitBlockedReason || blockedSubmitLabel
      : showAttachmentCapabilityNote
        ? attachmentCapabilityText
        : "";
  const charCount = value.length;
  const isNearLimit = charCount > maxLength * 0.9;
  const dropPromptText = attachmentsInteractive ? localizedCopy.dropToAttach : localizedCopy.imageUnavailable;

  const handleClear = useCallback(() => {
    onChange("");
    textareaRef.current?.focus();
  }, [onChange]);

  const focusModeOption = useCallback((index: number) => {
    modeOptionRefs.current[index]?.focus();
  }, []);

  const openModeMenu = useCallback(
    (focusIndex?: number) => {
      if (!modeControl || modeControl.disabled || areActionsDisabled) {
        return;
      }
      const selectedIndex = modeControl.options.findIndex((option) => option.value === modeControl.value);
      const nextIndex = focusIndex ?? Math.max(0, selectedIndex);
      setIsPlusMenuOpen(false);
      setIsModeMenuOpen(true);
      window.requestAnimationFrame(() => focusModeOption(nextIndex));
    },
    [areActionsDisabled, focusModeOption, modeControl],
  );

  const closeModeMenu = useCallback((restoreFocus = false) => {
    setIsModeMenuOpen(false);
    if (restoreFocus) {
      window.requestAnimationFrame(() => {
        modeControlRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
      });
    }
  }, []);

  const handleModeOptionSelect = useCallback(
    (value: string) => {
      if (!modeControl) {
        return;
      }
      modeControl.onChange(value);
      closeModeMenu(true);
    },
    [closeModeMenu, modeControl],
  );

  const handleModeTriggerKeyDown = useCallback(
    (event: KeyboardEvent<HTMLButtonElement>) => {
      if (!modeControl || event.key === "Tab") {
        return;
      }
      if (event.key === "Escape") {
        closeModeMenu();
        return;
      }
      if (event.key === "ArrowDown" || event.key === "ArrowUp" || event.key === "Home" || event.key === "End") {
        event.preventDefault();
        const selectedIndex = modeControl.options.findIndex((option) => option.value === modeControl.value);
        const lastIndex = Math.max(0, modeControl.options.length - 1);
        const targetIndex =
          event.key === "ArrowUp"
            ? Math.max(0, selectedIndex - 1)
            : event.key === "End"
              ? lastIndex
              : event.key === "Home"
                ? 0
                : Math.min(lastIndex, selectedIndex + 1);
        openModeMenu(targetIndex);
      }
    },
    [closeModeMenu, modeControl, openModeMenu],
  );

  const handleModeMenuKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      if (!modeControl) {
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        closeModeMenu(true);
        return;
      }
      if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
        return;
      }
      event.preventDefault();
      const currentIndex = modeOptionRefs.current.findIndex((element) => element === document.activeElement);
      const lastIndex = Math.max(0, modeControl.options.length - 1);
      const nextIndex =
        event.key === "ArrowUp"
          ? Math.max(0, currentIndex - 1)
          : event.key === "End"
            ? lastIndex
            : event.key === "Home"
              ? 0
              : Math.min(lastIndex, currentIndex + 1);
      focusModeOption(nextIndex);
    },
    [closeModeMenu, focusModeOption, modeControl],
  );

  useEffect(() => {
    if (!isModeMenuOpen) {
      return;
    }
    const handlePointerDown = (event: PointerEvent) => {
      if (!modeControlRef.current?.contains(event.target as Node)) {
        closeModeMenu();
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [closeModeMenu, isModeMenuOpen]);

  useEffect(() => {
    if (!modeControl || modeControl.disabled || areActionsDisabled) {
      setIsModeMenuOpen(false);
    }
  }, [areActionsDisabled, modeControl?.disabled, modeControl?.id]);

  const focusPlusOption = useCallback((index: number) => {
    plusOptionRefs.current[index]?.focus();
  }, []);

  const openPlusMenu = useCallback(
    (focusIndex?: number) => {
      if (!hasPlusMenu || areActionsDisabled) {
        return;
      }
      const selectedIndex = plusMenuActions.findIndex((action) => action.active);
      const nextIndex = focusIndex ?? Math.max(0, selectedIndex);
      setIsModeMenuOpen(false);
      setIsPlusMenuOpen(true);
      window.requestAnimationFrame(() => focusPlusOption(nextIndex));
    },
    [areActionsDisabled, focusPlusOption, hasPlusMenu, plusMenuActions],
  );

  const closePlusMenu = useCallback((restoreFocus = false) => {
    setIsPlusMenuOpen(false);
    if (restoreFocus) {
      window.requestAnimationFrame(() => {
        plusControlRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
      });
    }
  }, []);

  const handlePlusOptionSelect = useCallback(
    (action: ComposerActionItem) => {
      if (action.disabled) {
        return;
      }
      action.onClick?.();
      closePlusMenu(true);
    },
    [closePlusMenu],
  );

  const handlePlusTriggerKeyDown = useCallback(
    (event: KeyboardEvent<HTMLButtonElement>) => {
      if (event.key === "Tab") {
        return;
      }
      if (event.key === "Escape") {
        closePlusMenu();
        return;
      }
      if (event.key === "ArrowDown" || event.key === "ArrowUp" || event.key === "Home" || event.key === "End") {
        event.preventDefault();
        const selectedIndex = plusMenuActions.findIndex((action) => action.active);
        const lastIndex = Math.max(0, plusMenuActions.length - 1);
        const targetIndex =
          event.key === "ArrowUp"
            ? Math.max(0, selectedIndex - 1)
            : event.key === "End"
              ? lastIndex
              : event.key === "Home"
                ? 0
                : Math.min(lastIndex, selectedIndex + 1);
        openPlusMenu(targetIndex);
      }
    },
    [closePlusMenu, openPlusMenu, plusMenuActions],
  );

  const handlePlusMenuKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closePlusMenu(true);
        return;
      }
      if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
        return;
      }
      event.preventDefault();
      const currentIndex = plusOptionRefs.current.findIndex((element) => element === document.activeElement);
      const lastIndex = Math.max(0, plusMenuActions.length - 1);
      const nextIndex =
        event.key === "ArrowUp"
          ? Math.max(0, currentIndex - 1)
          : event.key === "End"
            ? lastIndex
            : event.key === "Home"
              ? 0
              : Math.min(lastIndex, currentIndex + 1);
      focusPlusOption(nextIndex);
    },
    [closePlusMenu, focusPlusOption, plusMenuActions],
  );

  useEffect(() => {
    if (!isPlusMenuOpen) {
      return;
    }
    const handlePointerDown = (event: PointerEvent) => {
      if (!plusControlRef.current?.contains(event.target as Node)) {
        closePlusMenu();
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [closePlusMenu, isPlusMenuOpen]);

  useEffect(() => {
    if (!hasPlusMenu || areActionsDisabled) {
      setIsPlusMenuOpen(false);
    }
  }, [areActionsDisabled, hasPlusMenu]);

  const handleTextareaKeyDown = useCallback(
    (event: KeyboardEvent<HTMLTextAreaElement>) => {
      onKeyDown?.(event);
      if (
        event.defaultPrevented ||
        event.nativeEvent.isComposing ||
        !onNavigateHistory ||
        event.altKey ||
        event.ctrlKey ||
        event.metaKey ||
        event.shiftKey
      ) {
        return;
      }

      const textarea = event.currentTarget;
      const hasCollapsedCaret = textarea.selectionStart === textarea.selectionEnd;
      const atStart = hasCollapsedCaret && textarea.selectionStart === 0;
      const atEnd = hasCollapsedCaret && textarea.selectionEnd === textarea.value.length;
      const direction = event.key === "ArrowUp" && atStart
        ? "previous"
        : event.key === "ArrowDown" && atEnd
          ? "next"
          : undefined;

      if (direction && onNavigateHistory(direction)) {
        event.preventDefault();
      }
    },
    [onKeyDown, onNavigateHistory],
  );

  const navigateWithSideButton = useCallback(
    (button: number) => {
      if (!onNavigateHistory || (button !== 3 && button !== 4)) {
        return;
      }
      onNavigateHistory(button === 3 ? "previous" : "next");
      textareaRef.current?.focus();
    },
    [onNavigateHistory],
  );

  const handleComposerMouseDown = useCallback(
    (event: MouseEvent<HTMLFormElement>) => {
      if (event.button !== 3 && event.button !== 4) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      sideButtonHandledRef.current = event.button;
      navigateWithSideButton(event.button);
    },
    [navigateWithSideButton],
  );

  const handleComposerAuxClick = useCallback(
    (event: MouseEvent<HTMLFormElement>) => {
      if (event.button !== 3 && event.button !== 4) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      if (sideButtonHandledRef.current === event.button) {
        sideButtonHandledRef.current = null;
        return;
      }
      navigateWithSideButton(event.button);
    },
    [navigateWithSideButton],
  );

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) {
      return;
    }

    const computedStyle = window.getComputedStyle(textarea);
    const lineHeight = Number.parseFloat(computedStyle.lineHeight) || 18;
    const padTop = Number.parseFloat(computedStyle.paddingTop) || 0;
    const padBottom = Number.parseFloat(computedStyle.paddingBottom) || 0;
    const minHeight = Math.max(
      Math.round(lineHeight * minRows) + padTop + padBottom,
      36,
    );
    const maxHeight = Math.max(minHeight, compactMode ? 112 : 140);

    textarea.style.height = "0px";
    const nextHeight = Math.min(Math.max(textarea.scrollHeight, minHeight), maxHeight);
    textarea.style.height = `${nextHeight}px`;
    textarea.style.overflowY = textarea.scrollHeight > maxHeight ? "auto" : "hidden";
  }, [compactMode, value, minRows]);

  return (
    <form
      className={classes}
      aria-busy={busy}
      data-send-state={sendState}
      data-drop-state={isDragActive ? "active" : undefined}
      onAuxClick={handleComposerAuxClick}
      onMouseDown={handleComposerMouseDown}
      onSubmit={(event) => {
        event.preventDefault();
        if (canSubmit) {
          onSubmit();
        }
      }}
    >
      {accessory ? <div className="composer__accessory">{accessory}</div> : null}

      <label className="sr-only" htmlFor={textareaId}>
        {resolvedAccessibilityLabel}
      </label>
      <span className="sr-only" id={composerStatusId} aria-live="polite">
        {composerStatusText}
      </span>
      {attachmentsEnabled && stagedAttachments.length > 0 ? (
        <div className="composer__attachments" aria-label={attachmentCountLabel} aria-live="polite">
          {stagedAttachments.map((attachment) => (
            <span
              key={attachment.id}
              className="composer__attachment-chip"
              title={`${attachment.name ?? attachment.id} (${attachment.mimeType})`}
            >
              <span className="composer__attachment-icon" aria-hidden="true">
                <AttachmentIcon size={12} />
              </span>
              <span className="composer__attachment-label">
                {attachment.name ?? localizedCopy.image}
              </span>
              <button
                type="button"
                className="composer__attachment-remove"
                aria-label={localizedCopy.removeAttachment}
                onClick={() => handleRemoveAttachment(attachment.id)}
                disabled={isTextareaDisabled}
              >
                <CloseIcon size={12} />
              </button>
            </span>
          ))}
          <span className="composer__attachment-count" aria-hidden="true">
            {stagedAttachments.length}/{MAX_STAGED_ATTACHMENTS}
          </span>
        </div>
      ) : null}
      {attachmentsEnabled && showAttachmentCapabilityNote && attachmentCapabilityText ? (
        <div className="composer__capability-note" id={attachmentCapabilityNoteId} role="status">
          <AttachmentIcon size={13} />
          <span>{attachmentCapabilityText}</span>
        </div>
      ) : null}
      {stagedAttachments.length > 0 && resolvedSubmitBlockedReason ? (
        <div className="composer__capability-note" id={submitBlockedReasonId} role="status">
          <AttachmentIcon size={13} />
          <span>{resolvedSubmitBlockedReason}</span>
        </div>
      ) : null}
      <div className="composer__body">
        <div
          className={`composer__frame ${showCharCount ? "composer__frame--with-count" : ""} ${
            isDragActive ? "composer__frame--drop-target" : ""
          } ${isDragActive && !attachmentsInteractive ? "composer__frame--drop-unavailable" : ""
          }`.trim()}
          onDragEnter={handleDragEnter}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          <textarea
            ref={textareaRef}
            id={textareaId}
            value={value}
            rows={minRows}
            disabled={isTextareaDisabled}
            readOnly={inputReadOnly}
            aria-describedby={[
              composerStatusId,
              showAttachmentCapabilityNote ? attachmentCapabilityNoteId : "",
              stagedAttachments.length > 0 && resolvedSubmitBlockedReason ? submitBlockedReasonId : "",
            ]
              .filter(Boolean)
              .join(" ")}
            placeholder={resolvedPlaceholder}
            onChange={(event) => onChange(event.target.value.slice(0, maxLength))}
            onKeyDown={handleTextareaKeyDown}
            onPaste={attachmentsEnabled ? handlePaste : undefined}
          />
          {isDragActive ? (
            <div
              className={`composer__drop-prompt ${
                !attachmentsInteractive ? "composer__drop-prompt--unavailable" : ""
              }`.trim()}
              role="status"
              aria-live="polite"
            >
              <span className="composer__drop-prompt-pulse" aria-hidden="true" />
              <span>{dropPromptText}</span>
            </div>
          ) : null}
          {showCharCount && (
            <span className={`composer__char-count ${isNearLimit ? "composer__char-count--near-limit" : ""}`}>
              {charCount}/{maxLength}
            </span>
          )}
        </div>
      </div>
      <div className="composer__footer">
        {showHelperText ? (
          <div className="composer__summary" aria-live={busy ? "polite" : undefined}>
            <span className="composer__summary-main">
              {(busy || resolvedSummary || (resolvedHintText && trimmedValue.length > 0)) ? (
                <span className="composer__hint" title={resolvedHintText ?? primaryHelperText}>
                  {primaryHelperText}
                </span>
              ) : null}
            </span>
            {resolvedShortcutHint && trimmedValue.length === 0 ? (
              <span className="composer__shortcut" title={resolvedShortcutHint}>
                {resolvedShortcutHint}
              </span>
            ) : null}
          </div>
        ) : (
          <div className="composer__summary composer__summary--quiet" aria-hidden="true" />
        )}

        <div className="composer__actions">
          {hasPlusMenu || hasPinnedLeadingActions ? (
            <div className="composer__leading-actions">
              {hasPlusMenu ? (
                <div className="composer__plus-control" ref={plusControlRef}>
                  <button
                    aria-controls={isPlusMenuOpen ? plusMenuId : undefined}
                    aria-expanded={isPlusMenuOpen}
                    aria-haspopup="menu"
                    aria-label={plusMenuAriaLabel}
                    className={`icon-button composer-plus-control__trigger ${
                      isPlusMenuOpen ? "is-open" : ""
                    }`.trim()}
                    disabled={areActionsDisabled}
                    onClick={() => {
                      if (isPlusMenuOpen) {
                        closePlusMenu();
                        return;
                      }
                      openPlusMenu();
                    }}
                    onKeyDown={handlePlusTriggerKeyDown}
                    title={plusMenuAriaLabel}
                    type="button"
                  >
                    <span className="icon-button__glyph" aria-hidden="true">
                      <PlusIcon size={16} />
                    </span>
                  </button>
                  {isPlusMenuOpen ? (
                    <div
                      aria-label={plusMenuAriaLabel}
                      className="composer-mode-menu composer-plus-menu"
                      id={plusMenuId}
                      onKeyDown={handlePlusMenuKeyDown}
                      role="menu"
                    >
                      {plusMenuActions.map((action, index) => {
                        const isActive = Boolean(action.active);
                        return (
                          <button
                            key={action.id}
                            aria-checked={isActive}
                            className={`composer-mode-menu__option composer-plus-menu__option ${
                              isActive ? "is-active" : ""
                            }`}
                            disabled={action.disabled || areActionsDisabled}
                            onClick={() => handlePlusOptionSelect(action)}
                            ref={(element) => {
                              plusOptionRefs.current[index] = element;
                            }}
                            role="menuitemcheckbox"
                            type="button"
                          >
                            <span className="composer-mode-menu__copy">
                              <strong>{action.label}</strong>
                            </span>
                            <span className="composer-mode-menu__state" aria-hidden="true">
                              {isActive ? <CheckMarkIcon size={16} /> : null}
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  ) : null}
                </div>
              ) : null}

              {hasPinnedLeadingActions ? (
                <div className="composer-iconbar composer-iconbar--footer">
                  {pinnedLeadingActions.map((action) => (
                    <ComposerIconButton
                      key={action.id}
                      active={action.active}
                      disabled={action.disabled || areActionsDisabled}
                      icon={action.icon}
                      label={action.label}
                      onClick={action.onClick}
                    />
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}

          {modeControl ? (
            <div className="composer__mode-control" ref={modeControlRef}>
              <button
                aria-controls={isModeMenuOpen ? modeMenuId : undefined}
                aria-expanded={isModeMenuOpen}
                aria-haspopup="menu"
                aria-label={`${modeControl.label}: ${selectedModeOption?.label ?? modeControl.label}`}
                className={`icon-button composer-mode-control__trigger composer-mode-control__trigger--label ${
                  isModeMenuOpen ? "is-open" : ""
                }`.trim()}
                disabled={modeControl.disabled || areActionsDisabled}
                id={modeControl.id}
                onClick={() => {
                  if (isModeMenuOpen) {
                    closeModeMenu();
                    return;
                  }
                  openModeMenu();
                }}
                onKeyDown={handleModeTriggerKeyDown}
                title={selectedModeOption?.label ?? modeControl.label}
                type="button"
              >
                <span className="composer-mode-control__label">
                  {selectedModeOption?.label ?? modeControl.label}
                </span>
              </button>
              {isModeMenuOpen ? (
                <div
                  aria-label={modeControl.label}
                  className="composer-mode-menu"
                  id={modeMenuId}
                  onKeyDown={handleModeMenuKeyDown}
                  role="menu"
                >
                  {modeControl.options.map((option, index) => {
                    const isSelected = option.value === modeControl.value;
                    return (
                      <button
                        key={option.value}
                        aria-checked={isSelected}
                        className={`composer-mode-menu__option ${isSelected ? "is-active" : ""}`}
                        onClick={() => handleModeOptionSelect(option.value)}
                        ref={(element) => {
                          modeOptionRefs.current[index] = element;
                        }}
                        role="menuitemradio"
                        type="button"
                      >
                        <span className="composer-mode-menu__copy">
                          <strong>{option.label}</strong>
                        </span>
                        <span className="composer-mode-menu__state" aria-hidden="true">
                          {isSelected ? <CheckMarkIcon size={16} /> : null}
                        </span>
                      </button>
                    );
                  })}
                </div>
              ) : null}
            </div>
          ) : null}

          {hasSecondaryActions ? (
            <div className="composer__buttons">
              {resolvedSecondaryActions.map((action) => (
                action.compact && action.icon ? (
                  <ComposerIconButton
                    key={action.id}
                    active={action.tone === "accent"}
                    disabled={action.disabled || areActionsDisabled}
                    icon={action.icon}
                    label={action.ariaLabel ?? action.label}
                    title={action.title}
                    onClick={action.onClick}
                  />
                ) : (
                  <button
                    key={action.id}
                    className={`button ${action.tone === "accent" ? "button--accent" : "button--ghost"} ${
                      action.icon ? "composer-secondary-button composer-secondary-button--with-icon" : "composer-secondary-button"
                    }`}
                    type={action.type ?? "button"}
                    disabled={action.disabled || areActionsDisabled}
                    title={action.title ?? action.label}
                    onClick={action.type === "submit" ? undefined : action.onClick}
                  >
                    {action.icon ? (
                      <span className="button__icon" aria-hidden="true">
                        {action.icon}
                      </span>
                    ) : null}
                    <span className="composer-secondary-button__label">{action.label}</span>
                  </button>
                )
              ))}
            </div>
          ) : null}

          {value && !busy && (
            <button
              type="button"
              className="composer__clear-btn"
              onClick={handleClear}
              aria-label={localizedCopy.clear}
              title={localizedCopy.clear}
            >
              <CloseIcon size={16} />
            </button>
          )}

          {showToolbarDivider ? <span className="composer__toolbar-divider" aria-hidden="true" /> : null}

          <div className="composer__send-wrap">
            <button
              aria-label={busy ? resolvedCancelLabel : resolvedSubmitButtonLabel}
              title={busy ? resolvedCancelLabel : resolvedSubmitButtonLabel}
              className={`composer__send ${busy ? "is-busy" : ""}`.trim()}
              disabled={busy ? !onCancel : !canSubmit}
              onClick={busy ? onCancel : undefined}
              type={busy ? "button" : "submit"}
            >
              {busy ? <SquareIcon size={16} /> : <SendIcon size={16} />}
            </button>
          </div>
        </div>
      </div>
    </form>
  );
}
