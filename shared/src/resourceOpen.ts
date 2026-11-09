export type ResourceOpenTarget =
  | { kind: "browser"; source: string }
  | { kind: "vscode"; source: string }
  | { kind: "unavailable"; reason: "missing_source" | "invalid_url" };

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

/**
 * "Open the original" targets: the untouched copy kept in the library first,
 * then the sandbox snapshot/artifact, then the declared local source.
 */
export function resolveResourceOriginalCandidates(resource: ResourceOpenRecord): string[] {
  const original = localOrEmpty(resource.canonicalOriginalPath);
  if (original) {
    return [original];
  }
  const snapshots = [resource.sandboxPath?.trim(), resource.extractedArtifactPath?.trim()].filter(
    (value): value is string => Boolean(value) && !URL_PATTERN.test(value!),
  );
  if (snapshots.length > 0) {
    return snapshots;
  }
  if (resource.kind === "url") {
    return [];
  }
  return [resource.source?.trim(), resource.canonicalSource?.trim()].filter(
    (value): value is string => Boolean(value) && !URL_PATTERN.test(value!),
  );
}

/** True when "open original" points somewhere other than the Markdown digest. */
export function hasDistinctOriginal(resource: ResourceOpenRecord): boolean {
  const read = resolveResourceReadCandidates(resource)[0]?.trim();
  const original = resolveResourceOriginalCandidates(resource)[0]?.trim();
  return Boolean(original) && original !== read;
}

/**
 * Backwards-compatible alias used by the open command: a row click opens the
 * canonical Markdown document, not the binary original.
 */
export function resolveResourceLocalCandidates(resource: ResourceOpenRecord): string[] {
  return resolveResourceReadCandidates(resource);
}

export function resolveResourceOpenTarget(resource: ResourceOpenRecord): ResourceOpenTarget {
  // The library's uniform artifact is the complete canonical Markdown: text,
  // structure, tables, images and notes all live there. Opening a row means
  // reading that document, not a summary record.
  const readCandidates = resolveResourceReadCandidates(resource);
  if (readCandidates.length > 0) {
    return { kind: "vscode", source: readCandidates[0] };
  }

  const source = resource.source?.trim();
  const canonicalSource = resource.canonicalSource?.trim();
  const urlSource = [source, canonicalSource].find(
    (value): value is string => Boolean(value) && URL_PATTERN.test(value!),
  );
  if (urlSource) {
    return { kind: "browser", source: urlSource };
  }

  return {
    kind: "unavailable",
    reason: source || canonicalSource ? "invalid_url" : "missing_source",
  };
}

/**
 * The untouched source behind a library Markdown. This is a secondary action:
 * a web source keeps its live URL, a local file opens its original bytes (or
 * the managed sandbox copy when the original was not retained).
 */
export function resolveResourceOriginalTarget(resource: ResourceOpenRecord): ResourceOpenTarget {
  const source = resource.source?.trim();
  const canonicalSource = resource.canonicalSource?.trim();
  const urlSource = [source, canonicalSource].find(
    (value): value is string => Boolean(value) && URL_PATTERN.test(value!),
  );
  if (urlSource) {
    return { kind: "browser", source: urlSource };
  }

  const originalCandidates = resolveResourceOriginalCandidates(resource);
  if (originalCandidates.length > 0) {
    return { kind: "vscode", source: originalCandidates[0] };
  }

  return {
    kind: "unavailable",
    reason: source || canonicalSource ? "invalid_url" : "missing_source",
  };
}
