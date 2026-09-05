import { useCallback, useMemo, useState } from "react";

import type { ComposerLanguage } from "../../lib/types";
import { resolveCodeBlockCopy } from "./codeBlockCopy";
import { ShikiCodeBlock } from "./parts/ShikiCodeBlock";

export interface RichCodeBlockProps {
  code: string;
  language: ComposerLanguage;
  languageId?: string;
  className?: string;
  showCopyButton?: boolean;
}

function copyLabel(language: ComposerLanguage, copied: boolean): string {
  const copy = resolveCodeBlockCopy(language);
  return copied ? copy.copied : copy.copy;
}

function languageLabel(language: ComposerLanguage, languageId?: string): string {
  const normalized = languageId?.trim();
  if (normalized) {
    return normalized;
  }
  return resolveCodeBlockCopy(language).code;
}

export function RichCodeBlock({
  code,
  language,
  languageId,
  className,
  showCopyButton = true,
}: RichCodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const headerLabel = useMemo(
    () => languageLabel(language, languageId),
    [language, languageId],
  );

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => {
        setCopied(false);
      }, 1400);
    } catch {
      setCopied(false);
    }
  }, [code]);

  return (
    <div className={["code-block-wrapper", className].filter(Boolean).join(" ")}>
      <div className="code-block-header">
        <span className="code-block-lang">{headerLabel}</span>
        {showCopyButton ? (
          <button
            type="button"
            className="code-block-copy-btn"
            onClick={() => {
              void handleCopy();
            }}
            aria-label={copyLabel(language, copied)}
            title={copyLabel(language, copied)}
          >
            {copyLabel(language, copied)}
          </button>
        ) : null}
      </div>
      <ShikiCodeBlock code={code} languageId={languageId} />
    </div>
  );
}
