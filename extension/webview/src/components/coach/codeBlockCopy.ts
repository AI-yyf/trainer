import type { ComposerLanguage } from "../../lib/types";

type CodeBlockCopy = {
  code: string;
  copy: string;
  copied: string;
};

const codeBlockCopy: Record<ComposerLanguage, CodeBlockCopy> = {
  "zh-CN": {
    code: "\u4ee3\u7801",
    copy: "\u590d\u5236",
    copied: "\u5df2\u590d\u5236",
  },
  "en-US": {
    code: "Code",
    copy: "Copy",
    copied: "Copied",
  },
  "es-ES": {
    code: "C\u00f3digo",
    copy: "Copiar",
    copied: "Copiado",
  },
  "fr-FR": {
    code: "Code",
    copy: "Copier",
    copied: "Copi\u00e9",
  },
  "de-DE": {
    code: "Code",
    copy: "Kopieren",
    copied: "Kopiert",
  },
  "ja-JP": {
    code: "\u30b3\u30fc\u30c9",
    copy: "\u30b3\u30d4\u30fc",
    copied: "\u30b3\u30d4\u30fc\u3057\u307e\u3057\u305f",
  },
  "ko-KR": {
    code: "\ucf54\ub4dc",
    copy: "\ubcf5\uc0ac",
    copied: "\ubcf5\uc0ac\ub428",
  },
  "pt-BR": {
    code: "C\u00f3digo",
    copy: "Copiar",
    copied: "Copiado",
  },
};

export function resolveCodeBlockCopy(language: ComposerLanguage): CodeBlockCopy {
  return codeBlockCopy[language] ?? codeBlockCopy["en-US"];
}
