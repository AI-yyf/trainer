/**
 * Real library folders — the webview side of the `/library/groups` contract.
 *
 * The Library's organizational model is the existing resource
 * `collection_path` (relative to the managed library root). The groups
 * endpoint exposes that same space as real folders, including folders that
 * hold no resource yet, plus a per-folder resource count:
 *
 *   GET    /library/groups                 -> folders (tree)
 *   POST   /library/groups        { path } -> create one folder
 *   POST   /library/groups/rename { path, new_path }
 *   DELETE /library/groups        { path } -> move the folder to the trash
 *
 * Wire tolerance: the sidecar is the only writer, but a folder tree is easy to
 * shape differently (`groups`/`folders`/`nodes`, `path`/`group_path`,
 * `resource_count`/`count`), so the parser accepts the documented shape plus
 * the obvious spellings instead of failing a whole listing on one rename. A
 * node without a `path` is placed under its parent using its `name`.
 *
 * Counts: a report from the endpoint wins (`resourceCountReported`), because
 * only the sidecar knows about resources this session has not listed;
 * otherwise the count is derived from the resources the snapshot carries.
 *
 * The derived tree is not a second structure: it is built from the same
 * `collection_path` values the resource tree already uses, so the folder
 * section stays useful (and empty folders stay visible) even while a listing
 * is unavailable.
 */

export interface LibraryFolderNode {
  /** Case-preserving relative folder path, no leading or trailing separator. */
  path: string;
  /** Last path segment (display name). */
  name: string;
  /** Resources in this folder (recursive, as reported/derived). */
  resourceCount: number;
  /** True when the endpoint itself reported the count. */
  resourceCountReported: boolean;
  children: LibraryFolderNode[];
}

export interface LibraryFolderListResult {
  ok: boolean;
  folders: LibraryFolderNode[];
  /** Display-safe reason, empty when `ok`. */
  message: string;
}

/**
 * The host's answer to one folder request, delivered as a `library/folders`
 * message carrying the request's `operationId` (the same correlation pattern
 * as `training/resourceHandoff`). `folders` stays `unknown` because the payload
 * crosses the wire; `parseLibraryFolderTree` reads it.
 */
export interface LibraryFolderHostAnswer {
  ok: boolean;
  message: string;
  folders?: unknown;
  /** No answer inside the bounded window: the write is unconfirmed, not failed. */
  unconfirmed?: boolean;
}

export interface LibraryFolderFlatEntry {
  path: string;
  name: string;
  depth: number;
  resourceCount: number;
}

const MAX_FOLDER_SEGMENTS = 16;

/**
 * Normalize one folder path to the Library's case-preserving relative form.
 * Returns "" for anything that is not a safe relative folder path (absolute
 * paths, URLs, dot segments, over-deep nesting).
 */
export function normalizeLibraryFolderPath(value: unknown): string {
  const raw = String(value ?? "")
    .trim()
    .replace(/\\/g, "/")
    .replace(/^\.\/+/, "")
    .replace(/^\/+/, "")
    .replace(/\/+$/, "");
  if (!raw || /^[a-z][a-z\d+.-]*:\/\//i.test(raw) || /^[a-z]:\//i.test(raw)) {
    return "";
  }
  const segments = raw
    .split("/")
    .map((segment) => segment.trim())
    .filter((segment) => segment && segment !== ".");
  if (
    segments.length === 0 ||
    segments.length > MAX_FOLDER_SEGMENTS ||
    segments.some((segment) => segment === "..")
  ) {
    return "";
  }
  return segments.join("/");
}

/** Display name of a normalized folder path. */
export function libraryFolderName(path: string): string {
  const normalized = normalizeLibraryFolderPath(path);
  if (!normalized) {
    return "";
  }
  return normalized.split("/").pop() ?? normalized;
}

/** Parent folder path ("" when the folder sits at the library root). */
export function libraryFolderParentPath(path: string): string {
  const normalized = normalizeLibraryFolderPath(path);
  const separatorIndex = normalized.lastIndexOf("/");
  return separatorIndex <= 0 ? "" : normalized.slice(0, separatorIndex);
}

function readRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function readString(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function readCount(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value) && value >= 0) {
    return Math.floor(value);
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value.trim());
    if (Number.isFinite(parsed) && parsed >= 0) {
      return Math.floor(parsed);
    }
  }
  return undefined;
}

function folderChildrenCandidates(node: Record<string, unknown>): unknown[] {
  for (const key of ["children", "nodes", "items", "folders", "subgroups", "groups"]) {
    const candidate = node[key];
    if (Array.isArray(candidate)) {
      return candidate;
    }
  }
  return [];
}

function collectFolderNodes(
  input: unknown,
  parentPath: string,
  out: Map<string, LibraryFolderNode>,
): void {
  if (!Array.isArray(input)) {
    return;
  }
  for (const entry of input) {
    const record = readRecord(entry);
    if (!record) {
      continue;
    }
    const explicitPath = normalizeLibraryFolderPath(
      record.path ?? record.group_path ?? record.groupPath ?? record.id,
    );
    const name = readString(record.name ?? record.label ?? record.title);
    const path = explicitPath || (name ? normalizeLibraryFolderPath(`${parentPath}/${name}`) : "");
    if (!path) {
      continue;
    }
    const reportedCount =
      readCount(
        record.resource_count ??
          record.resourceCount ??
          record.count ??
          record.total_count ??
          record.totalCount,
      ) ?? (Array.isArray(record.resource_ids) ? record.resource_ids.length : undefined);
    const existing = out.get(path);
    if (existing) {
      if (reportedCount !== undefined && !existing.resourceCountReported) {
        existing.resourceCount = reportedCount;
        existing.resourceCountReported = true;
      }
    } else {
      out.set(path, {
        path,
        name: libraryFolderName(path),
        resourceCount: reportedCount ?? 0,
        resourceCountReported: reportedCount !== undefined,
        children: [],
      });
    }
    collectFolderNodes(folderChildrenCandidates(record), path, out);
  }
}

/** Parse a `/library/groups` payload (or a bare array) into a folder tree. */
export function parseLibraryFolderTree(payload: unknown): LibraryFolderNode[] {
  const record = readRecord(payload);
  const list =
    Array.isArray(payload)
      ? payload
      : record
        ? folderChildrenCandidates(record)
        : [];
  const flat = new Map<string, LibraryFolderNode>();
  collectFolderNodes(list, "", flat);
  return linkLibraryFolderNodes(flat);
}

/**
 * Folders derived from the resources' own `collection_path` values.
 * Internal intake layout segments (`sources/inbox/<resource-id>`, hash
 * context folders) are storage facts and never become user-visible folders.
 */
export function libraryFolderTreeFromResources(
  resources: readonly { collectionPath?: string; collectionRoot?: string }[],
): LibraryFolderNode[] {
  const internalLayoutSegment = /^(sources|inbox|context-[0-9a-f]{8,}|resource-[0-9a-f]{6,})$/i;
  const flat = new Map<string, LibraryFolderNode>();
  for (const resource of resources) {
    if (!String(resource.collectionRoot ?? "").trim()) {
      continue;
    }
    const path = normalizeLibraryFolderPath(resource.collectionPath);
    if (!path) {
      continue;
    }
    // `collection_path` addresses the resource itself; its folder is the path
    // without the last segment (same rule as the resource tree).
    const folderSegments = path
      .split("/")
      .slice(0, -1)
      .filter((segment) => !internalLayoutSegment.test(segment));
    if (folderSegments.length === 0) {
      continue;
    }
    for (let index = 1; index <= folderSegments.length; index += 1) {
      const ancestor = folderSegments.slice(0, index).join("/");
      const node = flat.get(ancestor) ?? {
        path: ancestor,
        name: folderSegments[index - 1],
        resourceCount: 0,
        resourceCountReported: false,
        children: [],
      };
      // Recursive folder count, matching the resource tree's folder counts.
      node.resourceCount += 1;
      flat.set(ancestor, node);
    }
  }
  return linkLibraryFolderNodes(flat);
}

function linkLibraryFolderNodes(flat: Map<string, LibraryFolderNode>): LibraryFolderNode[] {
  const nodes = [...flat.values()];
  for (const node of nodes) {
    node.children = [];
  }
  const roots: LibraryFolderNode[] = [];
  for (const node of nodes) {
    const parentPath = libraryFolderParentPath(node.path);
    const parent = parentPath ? flat.get(parentPath) : undefined;
    if (parent) {
      parent.children.push(node);
    } else {
      roots.push(node);
    }
  }
  const sortNodes = (list: LibraryFolderNode[]): void => {
    list.sort((left, right) => left.name.localeCompare(right.name));
    list.forEach((node) => sortNodes(node.children));
  };
  sortNodes(roots);
  return roots;
}

/**
 * Union two folder trees by path. The endpoint tree is authoritative for what
 * a folder *is*; the derived tree fills in counts it cannot know and keeps
 * folders visible while a listing is unavailable.
 */
export function mergeLibraryFolderTrees(
  primary: LibraryFolderNode[],
  extra: LibraryFolderNode[],
): LibraryFolderNode[] {
  const primaryFlat = new Map<string, LibraryFolderNode>();
  const collect = (nodes: LibraryFolderNode[]): void => {
    for (const node of nodes) {
      primaryFlat.set(node.path, node);
      collect(node.children);
    }
  };
  const extraFlat = new Map<string, LibraryFolderNode>();
  const collectExtra = (nodes: LibraryFolderNode[]): void => {
    for (const node of nodes) {
      extraFlat.set(node.path, node);
      collectExtra(node.children);
    }
  };
  collect(primary);
  collectExtra(extra);

  const merged = new Map<string, LibraryFolderNode>();
  for (const node of [...extraFlat.values(), ...primaryFlat.values()]) {
    const derived = extraFlat.get(node.path);
    const reported = node.resourceCountReported;
    merged.set(node.path, {
      path: node.path,
      name: node.name || libraryFolderName(node.path),
      resourceCount: reported
        ? node.resourceCount
        : Math.max(node.resourceCount, derived?.resourceCount ?? 0),
      resourceCountReported: reported,
      children: [],
    });
  }
  return linkLibraryFolderNodes(merged);
}

/**
 * Optimistic local tree edits. The view applies these right after a folder
 * write succeeds so a new folder appears without waiting for a refresh; a
 * failed write reverts by restoring the previous tree.
 */
export function addLibraryFolderPath(
  nodes: LibraryFolderNode[],
  path: string,
): LibraryFolderNode[] {
  const normalized = normalizeLibraryFolderPath(path);
  if (!normalized) {
    return nodes;
  }
  const next = cloneLibraryFolderTree(nodes);
  const flat = new Map<string, LibraryFolderNode>();
  const collect = (list: LibraryFolderNode[]): void => {
    for (const node of list) {
      flat.set(node.path, node);
      collect(node.children);
    }
  };
  collect(next);
  const segments = normalized.split("/");
  for (let index = 1; index <= segments.length; index += 1) {
    const folderPath = segments.slice(0, index).join("/");
    if (!flat.has(folderPath)) {
      const created: LibraryFolderNode = {
        path: folderPath,
        name: segments[index - 1],
        resourceCount: 0,
        resourceCountReported: false,
        children: [],
      };
      flat.set(folderPath, created);
    }
  }
  return linkLibraryFolderNodes(flat);
}

export function removeLibraryFolderPath(
  nodes: LibraryFolderNode[],
  path: string,
): LibraryFolderNode[] {
  const normalized = normalizeLibraryFolderPath(path);
  if (!normalized) {
    return nodes;
  }
  const keep = (list: LibraryFolderNode[]): LibraryFolderNode[] =>
    list
      .filter((node) => node.path !== normalized)
      .map((node) => ({ ...node, children: keep(node.children) }));
  return keep(nodes);
}

export function renameLibraryFolderPath(
  nodes: LibraryFolderNode[],
  path: string,
  nextPath: string,
): LibraryFolderNode[] {
  const normalized = normalizeLibraryFolderPath(path);
  const normalizedNext = normalizeLibraryFolderPath(nextPath);
  if (!normalized || !normalizedNext) {
    return nodes;
  }
  const remap = (list: LibraryFolderNode[]): LibraryFolderNode[] =>
    list.map((node) => {
      const matches = node.path === normalized || node.path.startsWith(`${normalized}/`);
      const remappedPath = matches
        ? `${normalizedNext}${node.path.slice(normalized.length)}`
        : node.path;
      return {
        ...node,
        path: remappedPath,
        name: libraryFolderName(remappedPath),
        children: remap(node.children),
      };
    });
  const detached = remap(nodes);
  const flat = new Map<string, LibraryFolderNode>();
  const collect = (list: LibraryFolderNode[]): void => {
    for (const node of list) {
      flat.set(node.path, node);
      collect(node.children);
    }
  };
  collect(detached);
  ensureLibraryFolderAncestors(flat);
  // The renamed folder may now sit under another parent; relink.
  return linkLibraryFolderNodes(flat);
}

/** Materialize any missing ancestor of the mapped folders. */
function ensureLibraryFolderAncestors(flat: Map<string, LibraryFolderNode>): void {
  for (const path of [...flat.keys()]) {
    const segments = path.split("/");
    for (let index = 1; index < segments.length; index += 1) {
      const ancestor = segments.slice(0, index).join("/");
      if (!flat.has(ancestor)) {
        flat.set(ancestor, {
          path: ancestor,
          name: segments[index - 1],
          resourceCount: 0,
          resourceCountReported: false,
          children: [],
        });
      }
    }
  }
}

function cloneLibraryFolderTree(nodes: LibraryFolderNode[]): LibraryFolderNode[] {
  return nodes.map((node) => ({ ...node, children: cloneLibraryFolderTree(node.children) }));
}

/** Depth-first flat view for pickers and selects (folders only). */
export function flattenLibraryFolders(nodes: LibraryFolderNode[]): LibraryFolderFlatEntry[] {
  const flat: LibraryFolderFlatEntry[] = [];
  const walk = (list: LibraryFolderNode[], depth: number): void => {
    for (const node of list) {
      flat.push({
        path: node.path,
        name: node.name,
        depth,
        resourceCount: node.resourceCount,
      });
      walk(node.children, depth + 1);
    }
  };
  walk(nodes, 0);
  return flat;
}
