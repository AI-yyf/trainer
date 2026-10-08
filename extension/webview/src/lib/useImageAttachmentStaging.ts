import { useCallback, useEffect, useRef, useState } from "react";
import type { ComposerLanguage, MessageAttachment } from "./types";
import { ImageAttachmentError, readImageAttachments } from "./imageAttachments";

const COPY: Record<ComposerLanguage, { unreadable: string; limit: string; crop: string }> = {
  "zh-CN": { unreadable: "图片无法读取。请选择有效的 PNG、JPEG、GIF 或 WebP 图片。", limit: "最多附加四张图片。单张不超过 6 MB，总大小不超过 12 MB。", crop: "图片过大。请裁剪到需要讨论的代码或错误内容后重试。" },
  "en-US": { unreadable: "Could not read this image. Choose a valid PNG, JPEG, GIF or WebP.", limit: "Attach up to four images, at most 6 MB each and 12 MB in total.", crop: "This image is too large. Crop to the relevant code or error and try again." },
  "es-ES": { unreadable: "No se pudo leer la imagen. Elige un PNG, JPEG, GIF o WebP válido.", limit: "Adjunta hasta cuatro imágenes, de 6 MB cada una y 12 MB en total.", crop: "La imagen es demasiado grande. Recorta el código o error relevante y vuelve a intentarlo." },
  "fr-FR": { unreadable: "Impossible de lire l’image. Choisissez un PNG, JPEG, GIF ou WebP valide.", limit: "Joignez jusqu’à quatre images, de 6 Mo chacune et 12 Mo au total.", crop: "L’image est trop grande. Recadrez le code ou l’erreur utile, puis réessayez." },
  "de-DE": { unreadable: "Das Bild konnte nicht gelesen werden. Wählen Sie ein gültiges PNG, JPEG, GIF oder WebP.", limit: "Bis zu vier Bilder, jeweils höchstens 6 MB und insgesamt 12 MB.", crop: "Das Bild ist zu groß. Schneiden Sie den relevanten Code oder Fehler aus und versuchen Sie es erneut." },
  "ja-JP": { unreadable: "画像を読み込めません。有効な PNG、JPEG、GIF、WebP を選択してください。", limit: "画像は4枚まで、1枚6 MB、合計12 MB以下です。", crop: "画像が大きすぎます。必要なコードやエラー部分を切り抜いて再試行してください。" },
  "ko-KR": { unreadable: "이미지를 읽을 수 없습니다. 유효한 PNG, JPEG, GIF 또는 WebP를 선택하세요.", limit: "이미지는 최대 4장, 장당 6 MB, 총 12 MB까지 첨부할 수 있습니다.", crop: "이미지가 너무 큽니다. 필요한 코드나 오류 부분을 잘라 다시 시도하세요." },
  "pt-BR": { unreadable: "Não foi possível ler a imagem. Escolha um PNG, JPEG, GIF ou WebP válido.", limit: "Anexe até quatro imagens, de até 6 MB cada e 12 MB no total.", crop: "A imagem é grande demais. Recorte o código ou erro relevante e tente novamente." },
};

export function useImageAttachmentStaging(options: {
  scope: string; language: ComposerLanguage; attachments: MessageAttachment[];
  onChange?: (attachments: MessageAttachment[]) => void;
}) {
  const latest = useRef(options);
  latest.current = options;
  const pending = useRef<AbortController>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    pending.current?.abort();
    setError(undefined);
    setBusy(false);
    return () => { pending.current?.abort(); };
  }, [options.scope]);
  const stage = useCallback(async (files: FileList | File[]) => {
    if (!latest.current.onChange || pending.current && !pending.current.signal.aborted) return;
    const start = latest.current;
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true);
    setError(undefined);
    try {
      const additions = await readImageAttachments(files, { existing: start.attachments, signal: controller.signal });
      if (controller.signal.aborted || latest.current.scope !== start.scope) return;
      // Removing an image while this batch runs must not resurrect it.
      if (latest.current.attachments.map((item) => item.id).join("\0") !== start.attachments.map((item) => item.id).join("\0")) return;
      latest.current.onChange?.([...start.attachments, ...additions]);
    } catch (failure) {
      if (controller.signal.aborted || latest.current.scope !== start.scope) return;
      const copy = COPY[latest.current.language];
      const code = failure instanceof ImageAttachmentError ? failure.code : "decode";
      setError(code === "dimensions" || code === "size" ? copy.crop : code === "count" || code === "total" ? copy.limit : copy.unreadable);
    } finally {
      if (pending.current === controller) {
        pending.current = undefined;
        if (!controller.signal.aborted) setBusy(false);
      }
    }
  }, []);
  return { stage, busy, error };
}
