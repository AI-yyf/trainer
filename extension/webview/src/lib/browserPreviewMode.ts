/**
 * Lightweight browser-preview mode check decoupled from `browserSidecar.ts`
 * so the 14k-LOC browser preview harness stays lazy-loaded out of the
 * production VS Code Webview bundle.
 */

export function isBrowserPreviewFixtureMode(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  const win = window as Window & {
    __TRAINER_BROWSER_PREVIEW__?: unknown;
    __TRAINER_BOOTSTRAP__?: unknown;
  };
  if (win.__TRAINER_BROWSER_PREVIEW__ !== true) {
    return false;
  }
  const previewSearch = new URLSearchParams(window.location.search);
  if (previewSearch.get("live") === "1") {
    return false;
  }
  return Boolean(win.__TRAINER_BOOTSTRAP__) && typeof win.__TRAINER_BOOTSTRAP__ === "object";
}
