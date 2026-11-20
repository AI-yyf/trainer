export type ResourceOpenTarget =
  | { kind: "vscode"; source: string }
  | { kind: "unavailable"; reason: "missing_source" | "capture_required" };

type ResourceOpenRecord = {
  kind?: string;
  source?: string;
  canonicalSource?: string;
  sandboxPath?: string;
  extractedArtifactPath?: string;
  canonicalMarkdownPath?: string | null;
  canonicalOriginalPath?: string | null;
};

const URL_PATTERN = /^https?:\/\//i;

function localOrEmpty(value: string | null | undefined): string {
  const trimmed = value?.trim();
  return trimmed && !URL_PATTERN.test(trimmed) ? trimmed : "";
}

/**
 * Local read targets in priority order: the canonical Markdown document first
 * (reading, search and citations all use it), then the managed sandbox
 * snapshot or extracted artifact, then the declared source and its canonical
 * alias.
 *
 * The values are not resolved against the filesystem here — this module is
 * shared with the webview. The extension host resolves relative paths against
 * the real workspace/admission roots and verifies that the file exists before
 * it opens an editor tab.
 */
export function resolveResourceReadCandidates(resource: ResourceOpenRecord): string[] {
  const markdown = localOrEmpty(resource.canonicalMarkdownPath);
  if (markdown) {
    return [markdown];
  }
  const snapshots = [resource.sandboxPath?.trim(), resource.extractedArtifactPath?.trim()].filter(
    (value): value is string => Boolean(value) && !URL_PATTERN.test(value!),
  );
  if (snapshots.length > 0) {
    return snapshots;
  }
  if (resource.kind === "url") {
    // For URL records `source`/`canonicalSource` are web addresses, never
    // filesystem paths; only the managed snapshot/extracted artifact above can
    // name a local copy.
    return [];
  }
  return [resource.source?.trim(), resource.canonicalSource?.trim()].filter(
    (value): value is string => Boolean(value) && !URL_PATTERN.test(value!),
  );
}

export function resolveResourceOpenTarget(resource: ResourceOpenRecord): ResourceOpenTarget {
  // The library's uniform artifact is the complete canonical Markdown: text,
  // structure, tables, images and notes all live there. Opening a row means
  // reading that document, not a summary record.
  return editorTarget(resource, resolveResourceReadCandidates(resource)[0]);
}

function editorTarget(resource: ResourceOpenRecord, source: string | undefined): ResourceOpenTarget {
  if (source) {
    return { kind: "vscode", source };
  }

  const hasWebSource = [resource.source, resource.canonicalSource].some(
    (value) => URL_PATTERN.test(value?.trim() ?? ""),
  );
  return {
    kind: "unavailable",
    reason: hasWebSource ? "capture_required" : "missing_source",
  };
}
