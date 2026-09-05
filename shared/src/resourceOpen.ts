export type ResourceOpenTarget =
  | { kind: "browser"; source: string }
  | { kind: "vscode"; source: string }
  | { kind: "unavailable"; reason: "missing_source" | "invalid_url" };

type ResourceOpenRecord = {
  kind?: string;
  source?: string;
  canonicalSource?: string;
  sandboxPath?: string;
};

const URL_PATTERN = /^https?:\/\//i;

export function resolveResourceOpenTarget(resource: ResourceOpenRecord): ResourceOpenTarget {
  const source = resource.source?.trim();
  const canonicalSource = resource.canonicalSource?.trim();

  if (resource.kind === "url") {
    const urlSource = [source, canonicalSource].find((value) => value && URL_PATTERN.test(value));
    return urlSource
      ? { kind: "browser", source: urlSource }
      : { kind: "unavailable", reason: source || canonicalSource ? "invalid_url" : "missing_source" };
  }

  const localSource = [resource.sandboxPath?.trim(), source, canonicalSource].find(
    (value) => value && !URL_PATTERN.test(value),
  );
  return localSource
    ? { kind: "vscode", source: localSource }
    : { kind: "unavailable", reason: source || canonicalSource ? "invalid_url" : "missing_source" };
}
