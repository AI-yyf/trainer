import type { MessageAttachment } from "./types";
import ImageWorker from "./imageAttachmentWorker?worker&inline";
import { IMAGE_ATTACHMENT_LIMITS as LIMITS, type ImageAttachmentErrorCode } from "../../../../shared/src/imageAttachmentPolicy";
import type { ImageAttachmentWorkerReply } from "./imageAttachmentWorker";

export class ImageAttachmentError extends Error {
  constructor(readonly code: ImageAttachmentErrorCode) { super(code); }
}

/** Entire batches commit atomically; decoding/encoding runs outside the UI. */
export async function readImageAttachments(files: FileList | File[], options: {
  existing?: MessageAttachment[]; signal?: AbortSignal;
} = {}): Promise<MessageAttachment[]> {
  options.signal?.throwIfAborted();
  const existing = options.existing ?? [];
  const slots = Math.max(0, LIMITS.count - existing.length);
  if (!slots) throw new ImageAttachmentError("count");
  // File metadata is cheap; only admitted files ever enter the worker/read path.
  const selected = Array.from(files).filter((file) => !file.type || file.type.startsWith("image/")).slice(0, slots);
  if (!selected.length) return [];
  if (selected.some((file) => file.size <= 0 || file.size > LIMITS.sourceBytes)) throw new ImageAttachmentError("size");
  if (selected.reduce((total, file) => total + file.size, 0) > LIMITS.sourceBytes * 2) throw new ImageAttachmentError("total");
  const remainingBytes = LIMITS.totalBytes - existing.reduce((total, item) => total + (item.byteSize ?? Math.floor((item.dataBase64?.length ?? 0) * 3 / 4)), 0);
  if (remainingBytes <= 0) throw new ImageAttachmentError("total");
  let worker: Worker;
  try { worker = new ImageWorker(); } catch { throw new ImageAttachmentError("unavailable"); }
  return new Promise((resolve, reject) => {
    const finish = () => { clearTimeout(timeout); options.signal?.removeEventListener("abort", abort); worker.terminate(); };
    const abort = () => { finish(); reject(options.signal?.reason ?? new DOMException("Attachment staging cancelled", "AbortError")); };
    const timeout = setTimeout(() => { finish(); reject(new ImageAttachmentError("decode")); }, 30_000);
    options.signal?.addEventListener("abort", abort, { once: true });
    if (options.signal?.aborted) { abort(); return; }
    worker.onerror = () => { finish(); reject(new ImageAttachmentError("decode")); };
    worker.onmessage = (event: MessageEvent<ImageAttachmentWorkerReply>) => {
      finish();
      if (event.data.ok) resolve(event.data.attachments);
      else reject(new ImageAttachmentError(event.data.code));
    };
    try { worker.postMessage({ files: selected, remainingBytes }); }
    catch { finish(); reject(new ImageAttachmentError("unavailable")); }
  });
}
