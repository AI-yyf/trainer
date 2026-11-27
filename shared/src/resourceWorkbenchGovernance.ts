/** Match the sidecar's acknowledged-upload rule when removing recovered UI chrome. */
export function resourceRecordIsAcknowledgedUpload(item: {
  sandboxPath?: string;
  canonicalSource?: string;
  sourceType?: string;
  indexState?: string;
  source?: string;
}): boolean {
  return Boolean(
    item.sandboxPath?.trim() || item.canonicalSource?.trim() || item.sourceType?.trim() ||
    ["indexed", "parsed"].includes(item.indexState?.trim().toLowerCase() ?? "") ||
    /^(inline|https?|file|workspace):\/\//i.test(item.source?.trim() ?? ""),
  );
}
