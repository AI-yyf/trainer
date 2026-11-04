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
};

const URL_PATTERN = /^https?:\/\//i;

/**
 * Local sources in priority order: the managed snapshot first, then the
 * extracted artifact, then the declared source and its canonical alias.
 *
 * The values are not resolved against the filesystem here — this module is
 * shared with the webview. The extension host resolves relative paths against
 * the real workspace/admission roots and verifies that the file exists before
 * it opens an editor tab.
 */
export function resolveResourceLocalCandidates(resource: ResourceOpenRecord): string[] {
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
  const source = resource.source?.trim();
  const canonicalSource = resource.canonicalSource?.trim();
  const localCandidates = resolveResourceLocalCandidates(resource);
  if (localCandidates.length > 0) {
    return { kind: "vscode", source: localCandidates[0] };
  }

  if (resource.kind === "url") {
    const urlSource = [source, canonicalSource].find((value) => value && URL_PATTERN.test(value));
    return urlSource
      ? { kind: "browser", source: urlSource }
      : { kind: "unavailable", reason: source || canonicalSource ? "invalid_url" : "missing_source" };
  }

  return {
    kind: "unavailable",
    reason: source || canonicalSource ? "invalid_url" : "missing_source",
  };
}
