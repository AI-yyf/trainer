import { useEffect, useMemo, useRef, useState } from "react";

import type { ComposerLanguage } from "../../lib/types";
import type { LibraryFolderNode } from "../../lib/libraryFolders";
import {
  captureKindIsArtifact,
  detectCaptureSourceKind,
  type CaptureSourceKind,
} from "../../lib/captureSourceKind";

/**
 * One capture entry for the library, in the shape of the "add to knowledge
 * base" dialogs people already know: choose the source, choose the target
 * knowledge base, then add.
 *
 * The dialog never captures by itself: it hands a complete request to the
 * owner, which owns the sidecar call and the honest outcome.
 */

export type ResourceCaptureSourceKind = "web" | "pdf" | "pdf_scan" | "github" | "gitee" | "gitlab";

export interface ResourceCaptureDialogRequest {
  /** The kind the sidecar understands ("web" / "pdf" / the repo kinds). */
  kind: "web" | "pdf" | "github_repo" | "gitee_repo" | "gitlab_repo";
  url: string;
  title?: string;
  /** Also download the original into the library folder (PDF bytes / repo clone). */
  download: boolean;
  /** The chosen knowledge base (a library folder path), "" is the library root. */
  targetDir: string;
}

export interface ResourceCaptureDialogProps {
  language: ComposerLanguage;
  /** The library's knowledge bases (folders), already loaded by the owner. */
  knowledgeBases: LibraryFolderNode[];
  busy?: boolean;
  message?: string;
  onClose: () => void;
  onSubmit: (request: ResourceCaptureDialogRequest) => void | Promise<void>;
}

const COPY: Record<
  ComposerLanguage,
  {
    title: string;
    web: string;
    pdf: string;
    github: string;
    gitee: string;
    gitlab: string;
    url: string;
    urlPlaceholder: string;
    /** Prefix of the read-only "what this address is" line. */
    detected: string;
    pickFile: string;
    fileHint: string;
    target: string;
    root: string;
    submit: string;
    cancel: string;
    invalidUrl: string;
    invalidQr: string;
    scanQr: string;
  }
> = {
  "zh-CN": {
    title: "添加到资料库",
    web: "网页",
    pdf: "PDF",
    github: "GitHub",
    gitee: "Gitee",
    gitlab: "GitLab",
    url: "链接 / 项目地址",
    urlPlaceholder: "粘贴网页链接、PDF 地址或代码仓库地址",
    detected: "已识别",
    pickFile: "选择文件",
    fileHint: "可选：选择文档或二维码图片；资料将默认转为 Markdown 文档与配套图片。",
    target: "目标知识库",
    root: "资料库根目录",
    submit: "加入资料库",
    cancel: "取消",
    invalidUrl: "请填写有效的链接或项目地址。",
    invalidQr: "这张图片里没有读到链接。",
    scanQr: "读取二维码",
  },
  "en-US": {
    title: "Add to the library",
    web: "Web",
    pdf: "PDF",
    github: "GitHub",
    gitee: "Gitee",
    gitlab: "GitLab",
    url: "Link / repository",
    urlPlaceholder: "Paste a web link, a PDF address or a repository address",
    detected: "Detected",
    pickFile: "Choose a file",
    fileHint: "Optional: choose a document or QR image; Trainer stores resources as Markdown and images.",
    target: "Target knowledge base",
    root: "Library root",
    submit: "Add to library",
    cancel: "Cancel",
    invalidUrl: "Enter a valid link or repository address.",
    invalidQr: "No link was found in this image.",
    scanQr: "Read the QR code",
  },
  "es-ES": {
    title: "Añadir a la biblioteca",
    web: "Web",
    pdf: "PDF",
    github: "GitHub",
    gitee: "Gitee",
    gitlab: "GitLab",
    url: "Enlace / repositorio",
    urlPlaceholder: "Pega un enlace web, una dirección de PDF o un repositorio",
    detected: "Detectado",
    pickFile: "Elegir un archivo",
    fileHint: "Opcional: un archivo PDF o una imagen QR con el enlace. Trainer lo reconoce.",
    target: "Base de conocimiento",
    root: "Raíz de la biblioteca",
    submit: "Añadir a la biblioteca",
    cancel: "Cancelar",
    invalidUrl: "Escribe un enlace o una dirección de repositorio válida.",
    invalidQr: "No se encontró ningún enlace en esta imagen.",
    scanQr: "Leer el código QR",
  },
  "fr-FR": {
    title: "Ajouter à la bibliothèque",
    web: "Web",
    pdf: "PDF",
    github: "GitHub",
    gitee: "Gitee",
    gitlab: "GitLab",
    url: "Lien / dépôt",
    urlPlaceholder: "Collez un lien web, une adresse de PDF ou un dépôt",
    detected: "Détecté",
    pickFile: "Choisir un fichier",
    fileHint: "Facultatif : un fichier PDF ou une image QR portant le lien. Trainer le reconnaît.",
    target: "Base de connaissances",
    root: "Racine de la bibliothèque",
    submit: "Ajouter à la bibliothèque",
    cancel: "Annuler",
    invalidUrl: "Saisissez un lien ou une adresse de dépôt valide.",
    invalidQr: "Aucun lien n'a été trouvé dans cette image.",
    scanQr: "Lire le code QR",
  },
  "de-DE": {
    title: "Zur Bibliothek hinzufügen",
    web: "Web",
    pdf: "PDF",
    github: "GitHub",
    gitee: "Gitee",
    gitlab: "GitLab",
    url: "Link / Repository",
    urlPlaceholder: "Füge einen Web-Link, eine PDF-Adresse oder ein Repository ein",
    detected: "Erkannt",
    pickFile: "Datei wählen",
    fileHint: "Optional: eine PDF-Datei oder ein QR-Bild mit dem Link. Trainer erkennt beides.",
    target: "Ziel-Wissensbasis",
    root: "Bibliothekswurzel",
    submit: "Zur Bibliothek hinzufügen",
    cancel: "Abbrechen",
    invalidUrl: "Gib einen gültigen Link oder eine Repository-Adresse ein.",
    invalidQr: "In diesem Bild wurde kein Link gefunden.",
    scanQr: "QR-Code lesen",
  },
  "ja-JP": {
    title: "ライブラリに追加",
    web: "ウェブ",
    pdf: "PDF",
    github: "GitHub",
    gitee: "Gitee",
    gitlab: "GitLab",
    url: "リンク / リポジトリ",
    urlPlaceholder: "ウェブリンク、PDF アドレス、リポジトリを貼り付け",
    detected: "判別",
    pickFile: "ファイルを選択",
    fileHint: "任意：PDF ファイル、またはリンクを含む QR 画像。Trainer が自動で判別します。",
    target: "ナレッジベース",
    root: "ライブラリ直下",
    submit: "ライブラリに追加",
    cancel: "キャンセル",
    invalidUrl: "有効なリンクまたはリポジトリのアドレスを入力してください。",
    invalidQr: "この画像にリンクは見つかりませんでした。",
    scanQr: "QRコード を読む",
  },
  "ko-KR": {
    title: "라이브러리에 추가",
    web: "웹",
    pdf: "PDF",
    github: "GitHub",
    gitee: "Gitee",
    gitlab: "GitLab",
    url: "링크 / 저장소",
    urlPlaceholder: "웹 링크, PDF 주소 또는 저장소 주소를 붙여넣으세요",
    detected: "감지됨",
    pickFile: "파일 선택",
    fileHint: "선택 사항: PDF 파일 또는 링크가 담긴 QR 이미지. Trainer가 자동으로 판단합니다.",
    target: "지식 베이스",
    root: "라이브러리 루트",
    submit: "라이브러리에 추가",
    cancel: "취소",
    invalidUrl: "유효한 링크나 저장소 주소를 입력하세요.",
    invalidQr: "이 이미지에서 링크를 찾지 못했습니다.",
    scanQr: "QR 코드 읽기",
  },
  "pt-BR": {
    title: "Adicionar à biblioteca",
    web: "Web",
    pdf: "PDF",
    github: "GitHub",
    gitee: "Gitee",
    gitlab: "GitLab",
    url: "Link / repositório",
    urlPlaceholder: "Cole um link da web, um endereço de PDF ou um repositório",
    detected: "Detectado",
    pickFile: "Escolher um arquivo",
    fileHint: "Opcional: um arquivo PDF ou uma imagem QR com o link. O Trainer reconhece.",
    target: "Base de conhecimento",
    root: "Raiz da biblioteca",
    submit: "Adicionar à biblioteca",
    cancel: "Cancelar",
    invalidUrl: "Informe um link ou endereço de repositório válido.",
    invalidQr: "Nenhum link foi encontrado nesta imagem.",
    scanQr: "Ler o código QR",
  },
};

const KIND_LABEL: Record<CaptureSourceKind, keyof ReturnType<typeof sourceLabelKeys>> = {
  web: "web",
  pdf: "pdf",
  github_repo: "github",
  gitee_repo: "gitee",
  gitlab_repo: "gitlab",
};

function sourceLabelKeys() {
  return {
    web: "web" as const,
    pdf: "pdf" as const,
    github: "github" as const,
    gitee: "gitee" as const,
    gitlab: "gitlab" as const,
  };
}

/**
 * Read a QR code from an image with the browser's own detector. The platform
 * API is the only decoder Trainer ships: it needs no extra dependency and it
 * never leaves the machine. A platform without the API says so plainly
 * instead of pretending the scan worked.
 */
async function readQrFromImage(file: File): Promise<string> {
  const Detector = (globalThis as { BarcodeDetector?: new (options?: unknown) => { detect: (source: ImageBitmapSource) => Promise<Array<{ rawValue?: string }>> } }).BarcodeDetector;
  if (!Detector) {
    throw new Error("qr_unsupported");
  }
  const bitmap = await createImageBitmap(file);
  try {
    const codes = await new Detector({ formats: ["qr_code"] }).detect(bitmap);
    const value = codes.find((code) => typeof code.rawValue === "string" && code.rawValue.trim())?.rawValue;
    if (!value) {
      throw new Error("qr_empty");
    }
    return value.trim();
  } finally {
    bitmap.close?.();
  }
}

export function ResourceCaptureDialog({
  language,
  knowledgeBases,
  busy = false,
  message,
  onClose,
  onSubmit,
}: ResourceCaptureDialogProps) {
  const copy = COPY[language];
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | undefined>(undefined);
  const [targetDir, setTargetDir] = useState("");
  const [problem, setProblem] = useState<string | undefined>(undefined);
  const dialogRef = useRef<HTMLDivElement | null>(null);

  const bases = useMemo(() => {
    const flat: Array<{ path: string; name: string }> = [];
    const walk = (nodes: LibraryFolderNode[]) => {
      for (const node of nodes) {
        flat.push({ path: node.path, name: node.name });
        if (node.children.length > 0) walk(node.children);
      }
    };
    walk(knowledgeBases);
    return flat;
  }, [knowledgeBases]);

  useEffect(() => {
    dialogRef.current?.focus();
  }, []);

  // The file decides what it is: a PDF is captured as a PDF, an image is read
  // for the QR link it carries. There is no mode to pick first.
  const fileIsImage = (value: File): boolean => value.type.startsWith("image/");

  const submit = async () => {
    setProblem(undefined);
    if (file) {
      if (fileIsImage(file)) {
        let scanned = "";
        try {
          scanned = await readQrFromImage(file);
        } catch (error) {
          setProblem(error instanceof Error && error.message === "qr_unsupported" ? copy.scanQr : copy.invalidQr);
          return;
        }
        const scannedKind = detectCaptureSourceKind(scanned);
        await onSubmit({
          kind: scannedKind,
          url: scanned,
          download: captureKindIsArtifact(scannedKind),
          targetDir,
        });
        return;
      }
      // Convert uploaded documents directly into canonical Markdown + images
      // without storing a raw PDF copy in the library folder.
      const dataUrl = await readFileAsDataUrl(file);
      await onSubmit({
        kind: "pdf",
        url: dataUrl,
        title: file.name,
        download: false,
        targetDir,
      });
      return;
    }
    const trimmed = url.trim();
    if (!trimmed) {
      setProblem(copy.invalidUrl);
      return;
    }
    const kind = detectCaptureSourceKind(trimmed);
    await onSubmit({
      kind,
      url: trimmed,
      // A repository is cloned into the library folder; a page is only a
      // Markdown snapshot.
      download: captureKindIsArtifact(kind),
      targetDir,
    });
  };

  return (
    <div className="resource-capture" role="dialog" aria-modal="true" aria-label={copy.title} tabIndex={-1} ref={dialogRef}>
      <header className="resource-capture__header">
        <h2>{copy.title}</h2>
        <button type="button" className="app-shell-overlay__close" aria-label={copy.cancel} title={copy.cancel} onClick={onClose}>
          ×
        </button>
      </header>

      <section className="resource-capture__section">
        <label className="resource-capture__legend" htmlFor="resource-capture-url">
          {copy.url}
        </label>
        <input
          id="resource-capture-url"
          type="text"
          inputMode="url"
          className="resource-capture__url"
          placeholder={copy.urlPlaceholder}
          value={url}
          onChange={(event) => setUrl(event.target.value)}
        />
        <p className="resource-capture__hint" role="status" aria-live="polite">
          {url.trim() ? `${copy.detected}: ${copy[KIND_LABEL[detectCaptureSourceKind(url)]]}` : ""}
        </p>

        <p className="resource-capture__legend">{copy.pickFile}</p>
        <input
          type="file"
          accept="application/pdf,.pdf,image/*"
          className="resource-capture__file"
          aria-label={copy.pickFile}
          data-capture-file="true"
          onChange={(event) => setFile(event.target.files?.[0])}
        />
        <p className="resource-capture__hint">{copy.fileHint}</p>
      </section>

      <section className="resource-capture__section">
        <p className="resource-capture__legend">{copy.target}</p>
        <ul className="resource-capture__targets" role="radiogroup" aria-label={copy.target}>
          <li>
            <label className="resource-capture__target">
              <input
                type="radio"
                name="resource-capture-target"
                value=""
                checked={targetDir === ""}
                onChange={() => setTargetDir("")}
              />
              <span>{copy.root}</span>
            </label>
          </li>
          {bases.map((base) => (
            <li key={base.path}>
              <label className="resource-capture__target">
                <input
                  type="radio"
                  name="resource-capture-target"
                  value={base.path}
                  checked={targetDir === base.path}
                  onChange={() => setTargetDir(base.path)}
                />
                <span>{base.name}</span>
              </label>
            </li>
          ))}
        </ul>
      </section>

      {problem || message ? (
        <p className="resource-capture__message" role="status">
          {problem ?? message}
        </p>
      ) : null}

      <footer className="resource-capture__footer">
        <button
          type="button"
          className="button button--accent button--compact"
          data-capture-submit="true"
          disabled={busy}
          aria-busy={busy}
          onClick={() => void submit()}
        >
          {copy.submit}
        </button>
        <button type="button" className="button button--ghost button--compact" onClick={onClose} disabled={busy}>
          {copy.cancel}
        </button>
      </footer>
    </div>
  );
}

async function readFileAsDataUrl(file: File): Promise<string> {
  const buffer = await file.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  const base64 = btoa(binary);
  return `data:${file.type || "application/pdf"};base64,${base64}`;
}
