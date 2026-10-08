import { useLayoutEffect, useRef, type RefObject } from "react";
import type { ActiveWorkbenchView } from "../lib/types";
import { useWorkbenchState } from "./useWorkbenchState";

const READING_SURFACES: Record<ActiveWorkbenchView, string> = {
  coach: ".coach-conversation-view__list",
  plan: ".plan-view",
  resources: ".resources-knowledge",
  training: ".training-pane",
  progress: ".progress-view-section",
  settings: ".settings-pane",
};

/** Locate the actual reading pane, rather than its non-scrolling shell. */
export function getSurfaceScrollElement(root: HTMLElement, view: ActiveWorkbenchView) {
  return root.querySelector<HTMLElement>(`[data-surface="${view}"] ${READING_SURFACES[view]}`);
}

/** Preserve reading positions by real workspace/session identity, including reload. */
export function useSurfaceScroll(containerRef: RefObject<HTMLElement>, activeView: ActiveWorkbenchView, scope: string) {
  const positions = useRef(new Map(Object.entries(useWorkbenchState.getState().layout.surfaceScrollPositions ?? {})));
  useLayoutEffect(() => {
    const root = containerRef.current;
    if (!root) return;
    const key = `${scope}\u0000${activeView}`;
    const saved = positions.current.get(key);
    let pane: HTMLElement | null = null;
    let restoring = true;
    let timeout: number | undefined;
    let previousOverflowAnchor = "";
    const restore = () => {
      if (pane && restoring) pane.scrollTop = saved ?? (activeView === "coach" ? pane.scrollHeight : 0);
    };
    const remember = () => { if (pane && !restoring) positions.current.set(key, pane.scrollTop); };
    const persist = () => {
      if (pane) useWorkbenchState.getState().rememberSurfaceScroll(key, positions.current.get(key) ?? pane.scrollTop);
    };
    const finishRestore = () => {
      if (!restoring) return;
      restoring = false;
      resize.disconnect();
      if (pane) pane.style.overflowAnchor = previousOverflowAnchor;
      remember();
    };
    const resize = new ResizeObserver(restore);
    const connect = () => {
      if (pane) return;
      pane = getSurfaceScrollElement(root, activeView);
      if (!pane) return;
      // Offscreen content-visibility estimates settle after showing the pane.
      // Browser anchoring must not subtract their height changes from the
      // explicitly restored reading offset.
      previousOverflowAnchor = pane.style.overflowAnchor;
      pane.style.overflowAnchor = "none";
      mutations.disconnect();
      restore();
      resize.observe(pane);
      if (pane.firstElementChild) resize.observe(pane.firstElementChild);
      pane.addEventListener("scroll", remember, { passive: true });
      pane.addEventListener("wheel", finishRestore, { passive: true });
      pane.addEventListener("pointerdown", finishRestore, { passive: true });
      pane.addEventListener("keydown", finishRestore);
      timeout = window.setTimeout(finishRestore, saved !== undefined ? 1000 : 250);
    };
    // A lazy surface may mount after the shell's layout effect.
    const mutations = new MutationObserver(connect);
    mutations.observe(root, { childList: true, subtree: true });
    connect();
    const frame = window.requestAnimationFrame(restore);
    const onPageHide = () => { remember(); persist(); };
    window.addEventListener("pagehide", onPageHide);
    return () => {
      window.cancelAnimationFrame(frame);
      window.clearTimeout(timeout);
      mutations.disconnect();
      resize.disconnect();
      if (pane) pane.style.overflowAnchor = previousOverflowAnchor;
      pane?.removeEventListener("scroll", remember);
      pane?.removeEventListener("wheel", finishRestore);
      pane?.removeEventListener("pointerdown", finishRestore);
      pane?.removeEventListener("keydown", finishRestore);
      window.removeEventListener("pagehide", onPageHide);
      persist();
    };
  }, [activeView, containerRef, scope]);
}
