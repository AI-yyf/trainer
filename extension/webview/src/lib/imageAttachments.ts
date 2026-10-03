import type { MessageAttachment } from "./types";

/** Shared image transport encoding; both chat and activity inputs own their staging. */
export async function readImageAttachments(files: FileList | File[]): Promise<MessageAttachment[]> {
  const images = Array.from(files).filter((file) => file.type.startsWith("image/")).slice(0, 4);
  return Promise.all(images.map(async (file) => {
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = "";
    for (const byte of bytes) binary += String.fromCharCode(byte);
    return { id: crypto.randomUUID(), kind: "image" as const, mimeType: file.type,
      dataBase64: btoa(binary), name: file.name, byteSize: file.size };
  }));
}
