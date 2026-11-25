import { useCallback, useEffect, useState, type Dispatch, type RefObject, type SetStateAction } from "react";
import type { MessageAttachment } from "../lib/types";
import type { ComposerSubmission } from "./useComposerActionPreview";

interface QueuedSubmission {
  id: string;
  text: string;
  attachments: MessageAttachment[];
}

type Submit = (key?: string, submission?: ComposerSubmission) => Promise<void>;

/** Drain in order, stopping for a live reply or an action awaiting confirmation. */
export function useComposerQueue(scope: string, busy: boolean, submit: RefObject<Submit | null>) {
  const [queue, setQueue] = useState<{ scope: string; items: QueuedSubmission[] }>({ scope, items: [] });
  // Derive this during render: clearing in an effect alone can send the old
  // session's next item in the render that switches to a different session.
  const items = queue.scope === scope ? queue.items : [];
  const setItems: Dispatch<SetStateAction<QueuedSubmission[]>> = useCallback((update) => {
    setQueue((current) => {
      const previous = current.scope === scope ? current.items : [];
      return { scope, items: typeof update === "function" ? update(previous) : update };
    });
  }, [scope]);
  useEffect(() => {
    if (busy || queue.scope !== scope || queue.items.length === 0) return;
    const [next, ...rest] = queue.items;
    setItems(rest);
    void submit.current?.(undefined, { text: next.text, attachments: next.attachments });
  }, [busy, queue, scope, setItems, submit]);
  return { items, setItems };
}
