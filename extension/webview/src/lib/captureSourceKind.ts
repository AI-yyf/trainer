/**
 * Capture source recognition.
 *
 * The capture entry never asks "which kind is this?" — the address decides.
 * A repository address is a repository, a PDF address is a PDF, everything
 * else is a web page. The browser extension owns the same rule in
 * `browser-extension/shared.js` (`detectKind`); both surfaces must agree on
 * what a given link means.
 */

export type CaptureSourceKind = "web" | "pdf" | "github_repo" | "gitee_repo" | "gitlab_repo";

/** True for an address that serves a PDF document. */
export function isPdfCaptureUrl(rawUrl: string): boolean {
  const url = String(rawUrl || "").trim();
  if (!url) return false;
  const path = url.split(/[?#]/, 1)[0] || "";
  return /\.pdf$/i.test(path);
}

function hostOf(rawUrl: string): string {
  const match = String(rawUrl || "").trim().match(/^https?:\/\/([^/?#]+)/i);
  return String(match?.[1] || "").toLowerCase();
}

/** GitHub reserves top-level paths, so only `owner/repo` is a repository. */
function isGitHubRepoPath(rawUrl: string): boolean {
  return /^https?:\/\/(?:www\.)?github\.com\/[^/?#]+\/[^/?#]+\/?(?:[?#]|$)/i.test(String(rawUrl || "").trim());
}

/** Gitee mirrors the GitHub repository shape. */
function isGiteeRepoPath(rawUrl: string): boolean {
  return /^https?:\/\/(?:www\.)?gitee\.com\/[^/?#]+\/[^/?#]+\/?(?:[?#]|$)/i.test(String(rawUrl || "").trim());
}

/** GitLab nests groups: the repository is the last segment before `/-/`. */
function isGitLabRepoPath(rawUrl: string): boolean {
  const raw = String(rawUrl || "").trim();
  return /^https?:\/\/(?:www\.)?gitlab\.com\/[^/?#]+(?:\/[^/?#]+)+\/?(?:[?#]|$)/i.test(raw) && !/\/-\//.test(raw);
}

/**
 * Recognize what a capture address is. Anything unrecognized is a web page:
 * the sidecar fetches and extracts it like any other page.
 */
export function detectCaptureSourceKind(rawUrl: string): CaptureSourceKind {
  const raw = String(rawUrl || "").trim();
  if (!raw) return "web";
  const host = hostOf(raw);
  if (host === "github.com" || host === "www.github.com") {
    if (isGitHubRepoPath(raw)) return "github_repo";
    return isPdfCaptureUrl(raw) ? "pdf" : "web";
  }
  if (host === "gitee.com" || host === "www.gitee.com") {
    if (isGiteeRepoPath(raw)) return "gitee_repo";
    return isPdfCaptureUrl(raw) ? "pdf" : "web";
  }
  if (host === "gitlab.com" || host === "www.gitlab.com") {
    if (isGitLabRepoPath(raw)) return "gitlab_repo";
    return isPdfCaptureUrl(raw) ? "pdf" : "web";
  }
  return isPdfCaptureUrl(raw) ? "pdf" : "web";
}

/** True when the kind stores an owned artifact (a PDF or a repository clone). */
export function captureKindIsArtifact(kind: CaptureSourceKind): boolean {
  return kind !== "web";
}
