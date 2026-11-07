import type { ResourceRecord, SandboxState } from "../../lib/types";

/**
 * Pure library path/folder vocabulary for Resources. This module owns path
 * normalization, hidden intake roots, sandbox-relative paths and the fallback
 * grouping used by the tree. Rendering and localization stay in the view.
 */
export const INTERNAL_LAYOUT_SEGMENT_PATTERN =
  /^(sources|inbox|context-[0-9a-f]{8,}|resource-[0-9a-f]{6,})$/i;

export type SandboxNodePath = {
  normalizedPaths: string[];
  relativeSegments: string[];
};

export const collectionSegmentPrefix = "__collection__:";
const hiddenCollectionRootSegments = new Set(["trainer", ".trainer", ".trainer-sandbox", "sandbox"]);

export function normalizePath(value: string | undefined): string {
  return String(value ?? "")
    .trim()
    .replace(/\\/g, "/")
    .replace(/\/+$/g, "");
}

export function pathSegments(value: string | undefined): string[] {
  return String(value ?? "")
    .trim()
    .replace(/\\/g, "/")
    .replace(/^[a-z]:\//i, "")
    .replace(/^\/+/, "")
    .split("/")
    .map((segment) => segment.trim())
    .filter((segment) => segment && segment !== "." && segment !== "..");
}

export function isRelativeFilePath(value: string | undefined): boolean {
  const path = String(value ?? "").trim().replace(/\\/g, "/");
  return Boolean(path) && !/^(?:[a-z]:\/|\/|[a-z][a-z\d+.-]*:\/\/)/i.test(path);
}

export function collectionPathSegments(
  value: string | undefined,
  collectionRoot: string | undefined,
): string[] {
  const collectionPath = String(value ?? "").trim().replace(/\\/g, "/");
  if (
    !String(collectionRoot ?? "").trim() ||
    !isRelativeFilePath(collectionPath) ||
    collectionPath.split("/").some((segment) => {
      const trimmedSegment = segment.trim();
      return trimmedSegment === "." || trimmedSegment === "..";
    })
  ) {
    return [];
  }
  // The intake layout (`sources/inbox/<resource-id>`, hash context folders) is
  // storage, not filing; it never becomes a visible group on any surface.
  return visibleCollectionSegments(pathSegments(collectionPath));
}

export function trimHiddenCollectionRoots(segments: string[]): string[] {
  const privateRootIndex = segments.findIndex((segment) => {
    const normalized = normalizePath(segment);
    return normalized === ".trainer" || normalized === ".trainer-sandbox";
  });
  const candidateSegments = privateRootIndex >= 0 ? segments.slice(privateRootIndex + 1) : segments;
  let firstVisibleSegment = 0;
  while (
    firstVisibleSegment < candidateSegments.length &&
    hiddenCollectionRootSegments.has(normalizePath(candidateSegments[firstVisibleSegment]))
  ) {
    firstVisibleSegment += 1;
  }
  return candidateSegments.slice(firstVisibleSegment);
}

export function relativeSandboxPath(value: string | undefined, sandboxRoot: string | undefined): string | undefined {
  const normalizedValue = normalizePath(value);
  const normalizedRoot = normalizePath(sandboxRoot);
  if (!normalizedValue || !normalizedRoot) {
    return undefined;
  }
  if (normalizedValue === normalizedRoot) {
    return "";
  }
  if (normalizedValue.startsWith(`${normalizedRoot}/`)) {
    return normalizedValue.slice(normalizedRoot.length + 1);
  }
  return undefined;
}

export function compactSandboxPath(value: string | undefined, sandboxRoot: string | undefined): string | undefined {
  const normalizedValue = normalizePath(value);
  if (!normalizedValue) {
    return undefined;
  }

  const relativePath = relativeSandboxPath(normalizedValue, sandboxRoot);
  const candidate = relativePath ?? pathSegments(normalizedValue).slice(-3).join("/");
  if (!candidate) {
    return undefined;
  }

  const segments = candidate.split("/").filter(Boolean);
  const shortened = segments.length > 3 ? `.../${segments.slice(-3).join("/")}` : segments.join("/");
  return shortened.length > 64 ? `...${shortened.slice(-61)}` : shortened;
}

export function toSandboxNodePaths(
  nodes: SandboxState["nodes"] | undefined,
  sandboxRoot: string | undefined,
): SandboxNodePath[] {
  if (!Array.isArray(nodes)) {
    return [];
  }

  return nodes.flatMap((node) => {
    const path = typeof node.path === "string" ? node.path : undefined;
    const relativePath = typeof node.relativePath === "string" ? node.relativePath : undefined;
    const name = typeof node.name === "string" ? node.name : undefined;
    const nodeKind = typeof node.nodeKind === "string" ? node.nodeKind : undefined;
    const type = typeof node.type === "string" ? node.type : undefined;
    const isDirectory = nodeKind === "directory" || type === "folder";
    const explicitRelativePath = isRelativeFilePath(relativePath) ? relativePath : undefined;
    const derivedRelativePath = relativeSandboxPath(path, sandboxRoot);
    const nodeRelativePath = explicitRelativePath ?? derivedRelativePath;
    const relativeSegments = trimHiddenCollectionRoots(pathSegments(nodeRelativePath));
    const normalizedPaths = [normalizePath(path), normalizePath(relativePath), normalizePath(nodeRelativePath)]
      .filter((candidate): candidate is string => Boolean(candidate));

    if (isDirectory || !nodeRelativePath || relativeSegments.length === 0 || normalizedPaths.length === 0) {
      return [];
    }

    return [{ normalizedPaths, relativeSegments }];
  });
}

export function isUrl(value: string | undefined): boolean {
  return /^https?:\/\//i.test(String(value ?? "").trim());
}

export function sourcePathSegments(value: string | undefined, sandboxRoot: string | undefined): string[] {
  const sandboxRelative = relativeSandboxPath(value, sandboxRoot);
  if (sandboxRelative !== undefined) {
    return pathSegments(sandboxRelative);
  }

  const source = String(value ?? "").trim();
  if (isUrl(source)) {
    try {
      const url = new URL(source);
      return [url.hostname, ...pathSegments(url.pathname)];
    } catch {
      return pathSegments(source.replace(/^https?:\/\//i, ""));
    }
  }

  return pathSegments(source);
}

export function fallbackCollectionSegments(
  resource: ResourceRecord,
  sandboxRoot: string | undefined,
): string[] {
  const sandboxPath = resource.sandboxPath?.trim();
  const source = sandboxPath ?? resource.canonicalSource ?? resource.source;
  const sourceSegments = sourcePathSegments(source, sandboxRoot);
  const isSandboxResource = relativeSandboxPath(source, sandboxRoot) !== undefined;

  if (isSandboxResource && sourceSegments.length > 1) {
    return sourceSegments.slice(0, -1);
  }

  if (sandboxPath) {
    return [`${collectionSegmentPrefix}imported`];
  }

  if (isUrl(source)) {
    const host = sourceSegments[0];
    return host
      ? [`${collectionSegmentPrefix}web-snapshots`, host]
      : [`${collectionSegmentPrefix}web-snapshots`];
  }

  if (sourceSegments.length > 1) {
    // Local folders are already the learner's own filing system. Wrapping
    // them in an artificial "References" root added a level that made the
    // visible counts disagree with the library total, so the real folders stay
    // top-level.
    return visibleCollectionSegments(
      trimHiddenCollectionRoots(
        sourceSegments.slice(Math.max(0, sourceSegments.length - 3), -1),
      ),
    );
  }

  return [
    resource.kind === "url"
      ? `${collectionSegmentPrefix}web-snapshots`
      : `${collectionSegmentPrefix}imported`,
  ];
}

export function resourcePathCandidates(resource: ResourceRecord, sandboxRoot: string | undefined): string[] {
  const values = [resource.sandboxPath, resource.canonicalSource, resource.source];
  return Array.from(
    new Set(
      values.flatMap((value) => {
        const normalized = normalizePath(value);
        const sandboxRelative = relativeSandboxPath(value, sandboxRoot);
        return [normalized, normalizePath(sandboxRelative)].filter(Boolean);
      }),
    ),
  );
}

export function resourceTreeSegments(
  resource: ResourceRecord,
  sandboxRoot: string | undefined,
  sandboxNodes: SandboxNodePath[],
): string[] {
  const logicalCollectionSegments = collectionPathSegments(
    resource.collectionPath,
    resource.collectionRoot,
  );
  if (logicalCollectionSegments.length > 0) {
    return logicalCollectionSegments.slice(0, -1);
  }

  const candidates = new Set(resourcePathCandidates(resource, sandboxRoot));
  const matchingNode = sandboxNodes.find((node) => node.normalizedPaths.some((path) => candidates.has(path)));
  if (matchingNode) {
    return visibleCollectionSegments(matchingNode.relativeSegments.slice(0, -1));
  }
  return visibleCollectionSegments(fallbackCollectionSegments(resource, sandboxRoot));
}

/**
 * Internal intake layout (`sources/inbox/<resource-id>`, hash context
 * folders) describes where the bytes live, not how the learner filed the
 * material; those segments never become user-visible groups.
 */
export function visibleCollectionSegments(segments: string[]): string[] {
  return segments.filter((segment) => !INTERNAL_LAYOUT_SEGMENT_PATTERN.test(segment.trim()));
}

