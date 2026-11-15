export interface BrowserSourceRef {
  url: string;
  title: string;
  selection: string;
  resourceId?: string;
  versionId?: string;
  contentHash?: string;
  location?: Record<string, string>;
}

export const MAX_BROWSER_SOURCE_REFS = 8;

export function parseBrowserSourceRef(input: unknown): BrowserSourceRef | undefined {
  if (!input || typeof input !== 'object' || Array.isArray(input)) return undefined;
  const { url, title, selection, resourceId, versionId, contentHash, location } = input as Record<string, unknown>;
  if (typeof url !== 'string' || url.length > 2048 || /\s/.test(url) ||
      typeof title !== 'string' || typeof selection !== 'string' || !selection.trim()) return undefined;
  try {
    const page = new URL(url);
    if (!['http:', 'https:'].includes(page.protocol) || page.username || page.password) return undefined;
  } catch {
    return undefined;
  }
  const source = { url, title, selection };
  if (typeof resourceId !== 'string' || !resourceId || typeof versionId !== 'string' || !versionId ||
      typeof contentHash !== 'string' || !contentHash) return source;
  const anchor = location && typeof location === 'object' && !Array.isArray(location)
    ? Object.fromEntries(Object.entries(location).filter((entry): entry is [string, string] => typeof entry[1] === 'string'))
    : undefined;
  return { ...source, resourceId, versionId, contentHash, location: anchor };
}

export function parseBrowserSourceRefs(input: unknown): BrowserSourceRef[] | undefined {
  if (!Array.isArray(input)) return undefined;
  const sources = input.slice(-MAX_BROWSER_SOURCE_REFS).map(parseBrowserSourceRef)
    .filter((source): source is BrowserSourceRef => source !== undefined);
  return sources.length ? sources : undefined;
}
