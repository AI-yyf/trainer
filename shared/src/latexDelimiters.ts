/**
 * Coach replies occasionally carry LaTeX math in `\[ ... \]` / `\( ... \)`
 * delimiters, which remark-math does not recognize — it parses `$$` / `$`.
 * Normalize those delimiters to the parseable form so formulas render
 * instead of showing raw backslashes, while leaving fenced code blocks and
 * inline code spans byte-identical.
 */
export function normalizeLatexDelimiters(markdown: string): string {
  if (!markdown || (!markdown.includes("\\[") && !markdown.includes("\\("))) {
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
        out += markdown.slice(index, closingIndex + runLength);
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
