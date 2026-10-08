import { IMAGE_ATTACHMENT_LIMITS as LIMITS, imageMimeType, imageHeaderDimensions,
  type ImageAttachmentErrorCode } from "../../../../shared/src/imageAttachmentPolicy";
import type { MessageAttachment } from "./types";

export interface ImageAttachmentWorkerRequest { files: File[]; remainingBytes: number }
export type ImageAttachmentWorkerReply = { ok: true; attachments: MessageAttachment[] } | { ok: false; code: ImageAttachmentErrorCode };
declare const FileReaderSync: { new(): { readAsDataURL(blob: Blob): string } };
const port = self as unknown as { onmessage: ((event: MessageEvent<ImageAttachmentWorkerRequest>) => void) | null; postMessage: (reply: ImageAttachmentWorkerReply) => void };

class ImageError extends Error { constructor(readonly code: ImageAttachmentErrorCode) { super(code); } }

async function stage(file: File): Promise<MessageAttachment> {
  const header = new Uint8Array(await file.slice(0, 128 * 1024).arrayBuffer());
  const mime = imageMimeType(header);
  if (!mime || (file.type && file.type !== mime)) throw new ImageError("type");
  const dimensions = imageHeaderDimensions(header, mime);
  if (!dimensions || dimensions.some((value) => value <= 0)) throw new ImageError("decode");
  const [width, height] = dimensions;
  const scale = Math.min(1, LIMITS.edge / width, LIMITS.edge / height, Math.sqrt(LIMITS.pixels / (width * height)));
  if (scale < LIMITS.minimumResizeScale || width * height > LIMITS.pixels / (LIMITS.minimumResizeScale ** 2)) throw new ImageError("dimensions");
  let bitmap: ImageBitmap;
  try { bitmap = await createImageBitmap(file); } catch { throw new ImageError("decode"); }
  let blob: Blob = file;
  let outputMime = mime;
  try {
    if (scale < 1 || blob.size > LIMITS.imageBytes) {
      // Lossless PNG avoids JPEG ringing around code/error text. Never shrink
      // a screenshot below 75%; reject with a crop prompt if it cannot fit.
      if (mime === "image/gif") throw new ImageError("size");
      const canvas = new OffscreenCanvas(Math.max(1, Math.floor(bitmap.width * scale)), Math.max(1, Math.floor(bitmap.height * scale)));
      const context = canvas.getContext("2d");
      if (!context) throw new ImageError("unavailable");
      context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      blob = await canvas.convertToBlob({ type: "image/png" });
      outputMime = "image/png";
    }
    if (blob.size > LIMITS.imageBytes) throw new ImageError("size");
    const url = new FileReaderSync().readAsDataURL(blob);
    return { id: crypto.randomUUID(), kind: "image", mimeType: outputMime,
      dataBase64: url.slice(url.indexOf(",") + 1), name: file.name, byteSize: blob.size };
  } finally { bitmap.close(); }
}

port.onmessage = (event) => {
  void (async () => {
    try {
      const attachments: MessageAttachment[] = [];
      let bytes = 0;
      for (const file of event.data.files) {
        const item = await stage(file);
        bytes += item.byteSize ?? 0;
        if (bytes > event.data.remainingBytes) throw new ImageError("total");
        attachments.push(item);
      }
      port.postMessage({ ok: true, attachments });
    } catch (error) {
      port.postMessage({ ok: false, code: error instanceof ImageError ? error.code : "decode" });
    }
  })();
};
