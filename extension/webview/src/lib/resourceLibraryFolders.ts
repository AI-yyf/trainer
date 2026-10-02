import type { ResourceRecord } from "./types";

/** Collection paths include the filename; only validated relative parents become folders. */
export function resourceFolderSegments(resource: Pick<ResourceRecord, "collectionPath" | "collectionRoot">): string[] {
  if (!resource.collectionRoot?.trim()) return [];
  const path = resource.collectionPath?.trim().replace(/\\/g, "/") ?? "";
  if (!path || /^(?:\/|[a-z]:|[a-z][a-z\d+.-]*:\/\/)/i.test(path)) return [];
  const parts = path.split("/");
  if (parts.some(part => !part.trim() || part === "." || part === "..")) return [];
  return parts.slice(0, -1);
}

export function resourceFolderEntries(resources: ResourceRecord[], current: readonly string[]) {
  const folders = new Set<string>();
  const files: ResourceRecord[] = [];
  for (const resource of resources) {
    const parents = resourceFolderSegments(resource);
    if (!current.every((segment, index) => parents[index] === segment)) continue;
    if (parents.length > current.length) folders.add(parents[current.length]);
    else files.push(resource);
  }
  return { folders: [...folders].sort((a, b) => a.localeCompare(b)), files };
}
