/** Transport budgets; original resource-library bytes are never rewritten. */
export const IMAGE_ATTACHMENT_LIMITS = {
  count: 4,
  sourceBytes: 12 * 1024 * 1024,
  imageBytes: 6 * 1024 * 1024,
  totalBytes: 12 * 1024 * 1024,
  pixels: 16 * 1024 * 1024,
  edge: 8192,
  minimumResizeScale: 0.75,
} as const;

export type ImageAttachmentErrorCode = "type" | "size" | "total" | "count" | "decode" | "dimensions" | "unavailable";
export type ImageMimeType = "image/png" | "image/jpeg" | "image/gif" | "image/webp";

export function imageMimeType(bytes: Uint8Array): ImageMimeType | undefined {
  if (bytes.length >= 8 && [137, 80, 78, 71, 13, 10, 26, 10].every((value, i) => bytes[i] === value)) return "image/png";
  if (bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255) return "image/jpeg";
  const text = (start: number, end: number) => String.fromCharCode(...bytes.slice(start, end));
  if (["GIF87a", "GIF89a"].includes(text(0, 6))) return "image/gif";
  if (text(0, 4) === "RIFF" && text(8, 12) === "WEBP") return "image/webp";
  return undefined;
}

/** Read dimensions before allocating a decoded bitmap (including JPEG bombs). */
export function imageHeaderDimensions(bytes: Uint8Array, mime: ImageMimeType): [number, number] | undefined {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (mime === "image/png" && bytes.length >= 24) return [view.getUint32(16), view.getUint32(20)];
  if (mime === "image/gif" && bytes.length >= 10) return [view.getUint16(6, true), view.getUint16(8, true)];
  if (mime === "image/jpeg") {
    let position = 2;
    while (position + 8 < bytes.length) {
      if (bytes[position++] !== 255) return undefined;
      while (bytes[position] === 255) position++;
      const marker = bytes[position++] ?? 0;
      if (marker === 0xD9 || marker === 0xDA) break;
      if (marker === 0x01 || (marker >= 0xD0 && marker <= 0xD7)) continue;
      if (position + 2 > bytes.length) break;
      const length = view.getUint16(position);
      if (length < 2 || position + length > bytes.length) break;
      if ([0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF].includes(marker)) {
        return [view.getUint16(position + 5), view.getUint16(position + 3)];
      }
      position += length;
    }
  }
  if (mime === "image/webp" && bytes.length >= 30) {
    const kind = String.fromCharCode(...bytes.slice(12, 16));
    if (kind === "VP8X") return [1 + (bytes[24] ?? 0) + ((bytes[25] ?? 0) << 8) + ((bytes[26] ?? 0) << 16), 1 + (bytes[27] ?? 0) + ((bytes[28] ?? 0) << 8) + ((bytes[29] ?? 0) << 16)];
    if (kind === "VP8 " && bytes[23] === 0x9D && bytes[24] === 0x01 && bytes[25] === 0x2A) return [view.getUint16(26, true) & 0x3FFF, view.getUint16(28, true) & 0x3FFF];
    if (kind === "VP8L" && bytes[20] === 0x2F) {
      const bits = view.getUint32(21, true);
      return [(bits & 0x3FFF) + 1, ((bits >>> 14) & 0x3FFF) + 1];
    }
  }
  return undefined;
}
