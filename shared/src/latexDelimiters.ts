/**
 * Coach replies occasionally carry LaTeX math in `\[ ... \]` / `\( ... \)`
 * delimiters, which remark-math does not recognize — it parses `$$` / `$`.
 * Normalize those delimiters to the parseable form so formulas render
 * instead of showing raw backslashes. Fenced blocks stay byte-identical;
 * inline code stays byte-identical unless it is unambiguously a formula.
 */
/**
 * Code spans are usually code, but models often wrap an inline formula in
 * backticks to protect underscores (`c_retry`). remark-math never parses
 * inlineCode, so such a formula renders as raw code. Only promote spans that
 * carry strong math signals: a one-letter subscript (`c_retry`), a superscript,
 * or a LaTeX macro, plus an operator. Snake_case identifiers (`foo_bar = 1`)
 * and code keywords stay untouched.
 */
function looksLikeInlineFormula(content: string): boolean {
  const text = content.trim();
  if (!text || text.length > 160 || text.includes("$") || text.includes("`")) {
    return false;
  }
  if (/[;]/.test(text) || /(=>|==|!=|:=|\/\/|\/\*|<\/|#include)/.test(text)) {
    return false;
  }
  if (/(^|\s)(const|let|var|function|def|return|class|import|from|async|await|if|for|while)\s/.test(text)) {
    return false;
  }
  if (/["']/.test(text)) {
    return false;
  }
  const hasShortSubscript = /(^|[^A-Za-z0-9])[A-Za-z]_[A-Za-z0-9{]/.test(text);
  const hasCaret = /\^/.test(text);
  const hasMacro = /\\[A-Za-z]+/.test(text);
  const operatorCount = (text.match(/[=+\-*/]/g) ?? []).length;
  if (hasCaret || hasMacro) {
    return operatorCount >= 1;
  }
  return hasShortSubscript && operatorCount >= 2;
}

export function normalizeLatexDelimiters(markdown: string): string {
  if (!markdown) {
    return markdown;
  }
  if (!markdown.includes("\\[") && !markdown.includes("\\(") && !markdown.includes("`")) {
    return markdown;
  }
  let out = "";
  let index = 0;
  let inFence = false;
  let fenceMarker = "";
  while (index < markdown.length) {
    const atLineStart = index === 0 || markdown[index - 1] === "\n";
    if (atLineStart) {
      const fence = /^(```|~~~)/.exec(markdown.slice(index, index + 3));
      if (fence) {
        if (!inFence) {
          inFence = true;
          fenceMarker = fence[1];
        } else if (markdown.startsWith(fenceMarker, index)) {
          inFence = false;
        }
        out += fence[1];
        index += fence[1].length;
        continue;
      }
    }
    if (!inFence && markdown[index] === "`") {
      let runLength = 0;
      while (markdown[index + runLength] === "`") {
        runLength += 1;
      }
      const closer = "`".repeat(runLength);
      const closingIndex = markdown.indexOf(closer, index + runLength);
      if (closingIndex === -1) {
        out += markdown.slice(index, index + runLength);
        index += runLength;
      } else {
        const content = markdown.slice(index + runLength, closingIndex);
        if (looksLikeInlineFormula(content)) {
          out += `$${content.trim()}$`;
        } else {
          out += markdown.slice(index, closingIndex + runLength);
        }
        index = closingIndex + runLength;
      }
      continue;
    }
    if (!inFence && markdown.startsWith("\\[", index)) {
      out += "$$";
      index += 2;
      continue;
    }
    if (!inFence && markdown.startsWith("\\]", index)) {
      out += "$$";
      index += 2;
      continue;
    }
    if (!inFence && markdown.startsWith("\\(", index)) {
      out += "$";
      index += 2;
      continue;
    }
    if (!inFence && markdown.startsWith("\\)", index)) {
      out += "$";
      index += 2;
      continue;
    }
    out += markdown[index];
    index += 1;
  }
  return out;
}
