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
function hasMathOperator(text: string): boolean {
  return /[=+*/^_\\-]/.test(text);
}

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
  const hasMacro =
    /\\(?:frac|sqrt|sum|prod|int|lim|alpha|beta|gamma|delta|theta|lambda|mu|sigma|pi|infty|partial|nabla|cdot|times|div|pm|le|ge|neq|approx|equiv|to|rightarrow|left|right|begin|end|text|mathrm|mathbf|mathbb|mathcal|overline|hat|vec|dot|bar|binom|log|ln|sin|cos|tan|exp|max|min|arg|det|dim|ker|deg|gcd|bmod|pmod|quad|qquad)\b/.test(
      text,
    );
  const operatorCount = (text.match(/[=+\-*/]/g) ?? []).length;
  if (hasMacro) {
    // \frac, \sqrt, \sum, \alpha are unambiguous math even without an operator.
    return true;
  }
  if (hasCaret) {
    return operatorCount >= 1;
  }
  if (hasShortSubscript && operatorCount <= 1) {
    // A bare definition like c_t = 1 is still a formula; reject call syntax.
    return /^[A-Za-z]_[A-Za-z0-9]+\s*=\s*[^;{}()"'`]+$/.test(text);
  }
  return hasShortSubscript && operatorCount >= 2;
}

const LATEX_COLOR_COMMAND = /\\(?:textcolor|fcolorbox|colorbox|pagecolor|color|cellcolor|rowcolor|columncolor)(?:\[[^\]]*\])?\{[^{}]*\}/g;
const LATEX_DEFINE_COLOR = /\\(?:definecolor|providecolor)(?:\[[^\]]*\])?\{[^{}]*\}(?:\{[^{}]*\}){0,2}/g;

function stripColorCommands(expression: string): string {
  return expression
    .replace(LATEX_DEFINE_COLOR, "")
    .replace(LATEX_COLOR_COMMAND, "");
}

/**
 * Math can carry \textcolor/\color, which would paint a second hue inside an
 * otherwise monochrome surface. Strip only inside math spans, leaving code
 * spans and fences byte-identical.
 */
function stripMathColors(markdown: string): string {
  if (!markdown.includes("\\color") && !markdown.includes("\\textcolor")) {
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
      while (markdown[index + runLength] === "`") runLength += 1;
      const closer = "`".repeat(runLength);
      const closing = markdown.indexOf(closer, index + runLength);
      if (closing === -1) {
        out += markdown.slice(index, index + runLength);
        index += runLength;
      } else {
        out += markdown.slice(index, closing + runLength);
        index = closing + runLength;
      }
      continue;
    }
    if (!inFence && markdown[index] === "$" && markdown[index - 1] !== "\\") {
      const display = markdown.startsWith("$$", index);
      const delimiter = display ? "$$" : "$";
      const closing = markdown.indexOf(delimiter, index + delimiter.length);
      if (closing === -1) {
        out += markdown[index];
        index += 1;
        continue;
      }
      out += delimiter + stripColorCommands(markdown.slice(index + delimiter.length, closing)) + delimiter;
      index = closing + delimiter.length;
      continue;
    }
    out += markdown[index];
    index += 1;
  }
  return out;
}

export function normalizeLatexDelimiters(markdown: string): string {
  if (!markdown) {
    return markdown;
  }
  if (
    !markdown.includes("\\[") &&
    !markdown.includes("\\(") &&
    !markdown.includes("`") &&
    !markdown.includes("\\color") &&
    !markdown.includes("\\textcolor")
  ) {
    return markdown;
  }
  // Models commonly fence display math as ```math / ```latex. Turn that fence
  // into remark-math's $$ block before the character scan.
  markdown = markdown.replace(
    /^(```|~~~)[ \t]*(math|latex|tex)[ \t]*\n([\s\S]*?)^\1[ \t]*$/gim,
    (_match, _fence, _language, body: string) => `$$\n${body.trimEnd()}\n$$`,
  );
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
        const wrappedInline = /^\\\(([\s\S]+)\\\)$/.exec(content.trim());
        const wrappedDisplay = /^\\\[([\s\S]+)\\\]$/.exec(content.trim());
        if (wrappedInline && hasMathOperator(wrappedInline[1])) {
          out += `$${wrappedInline[1].trim()}$`;
        } else if (wrappedDisplay && hasMathOperator(wrappedDisplay[1])) {
          out += `$$\n${wrappedDisplay[1].trim()}\n$$`;
        } else if (looksLikeInlineFormula(content)) {
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
  return stripMathColors(out);
}
