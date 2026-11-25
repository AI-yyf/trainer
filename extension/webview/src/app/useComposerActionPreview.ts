import { useState } from "react";
import type { MessageAttachment } from "../lib/types";

export interface ComposerSubmission {
  text: string;
  attachments?: MessageAttachment[];
}

interface ComposerActionPreview {
  kind: "plan" | "browser" | "library";
  key: string;
  scope: string;
  text: string;
  detail?: string;
  submission?: ComposerSubmission;
}

/** A queued request has left the draft; confirmation must retain that submission. */
export function useComposerActionPreview() {
  const [preview, setPreview] = useState<ComposerActionPreview>();
  const requestPreview = (value: Omit<ComposerActionPreview, "submission">, submission?: ComposerSubmission) => {
    setPreview({ ...value, submission });
  };
  const confirmPreview = (submit: (key: string, submission?: ComposerSubmission) => Promise<void>) => {
    if (preview) void submit(preview.key, preview.submission);
  };
  return { preview, setPreview, requestPreview, confirmPreview };
}
