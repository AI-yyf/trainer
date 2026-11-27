import type { PersistedWorkbenchState } from "./types";

export type WorkbenchHostSurface = "sidebar" | "editor" | "browser-sidepanel";

/**
 * Minimal host transport contract shared by the VS Code Webview, the Browser
 * Extension MV3 Side Panel, and the DOM preview harness.
 *
 * Keeping the host boundary down to state persistence + bidirectional message
 * passing allows `extension/webview` to run unchanged inside both VS Code and
 * Chromium `chrome.sidePanel` without duplicating UI components.
 */
export interface WorkbenchHostTransport {
  readonly id: string;
  readonly surface: WorkbenchHostSurface;
  /**
   * True when backed by a real host bridge (VS Code Webview or Browser Side
   * Panel connected to the local sidecar), rather than the standalone mock
   * preview harness.
   */
  readonly isNativeHost: boolean;
  getState(): PersistedWorkbenchState | undefined;
  setState(state: PersistedWorkbenchState): void;
  postMessage(message: unknown): void;
  subscribe(listener: (rawMessage: unknown) => void): () => void;
}

interface RawVsCodeApi {
  getState(): PersistedWorkbenchState | undefined;
  setState(state: PersistedWorkbenchState): void;
  postMessage(message: unknown): void;
}

const STORAGE_KEY = "trainer:webview";
const PREVIEW_HOST_MESSAGE_EVENT = "trainer:host-message";

let explicitTransport: WorkbenchHostTransport | undefined;
let cachedVsCodeApi: RawVsCodeApi | undefined;
let cachedVsCodeTransport: WorkbenchHostTransport | undefined;
let cachedDomPreviewTransport: WorkbenchHostTransport | undefined;

function detectWindowSurface(): WorkbenchHostSurface {
  if (typeof window === "undefined") {
    return "sidebar";
  }
  if (window.__TRAINER_SURFACE__ === "editor") {
    return "editor";
  }
  if (window.__TRAINER_SURFACE__ === "browser-sidepanel") {
    return "browser-sidepanel";
  }
  return "sidebar";
}

function getPreviewStorageKey(): string {
  if (
    typeof window !== "undefined" &&
    window.__TRAINER_BROWSER_PREVIEW__ &&
    window.__TRAINER_PREVIEW_STORAGE_KEY__
  ) {
    return window.__TRAINER_PREVIEW_STORAGE_KEY__;
  }
  return STORAGE_KEY;
}

function subscribeWindowMessages(
  listener: (rawMessage: unknown) => void,
  enablePreviewCustomEvent: boolean,
): () => void {
  if (typeof window === "undefined") {
    return () => undefined;
  }

  const handleWindowMessage = (event: MessageEvent<unknown>) => {
    listener(event.data);
  };
  const handlePreviewEvent = (event: Event) => {
    listener((event as CustomEvent<unknown>).detail);
  };

  window.addEventListener("message", handleWindowMessage);
  if (enablePreviewCustomEvent) {
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__ = listener;
    window.addEventListener(PREVIEW_HOST_MESSAGE_EVENT, handlePreviewEvent);
  }

  return () => {
    window.removeEventListener("message", handleWindowMessage);
    if (enablePreviewCustomEvent) {
      delete window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__;
      window.removeEventListener(PREVIEW_HOST_MESSAGE_EVENT, handlePreviewEvent);
    }
  };
}

function createVsCodeWebviewTransport(api: RawVsCodeApi): WorkbenchHostTransport {
  return {
    id: "vscode-webview",
    get surface() {
      return detectWindowSurface();
    },
    isNativeHost: true,
    getState: () => api.getState(),
    setState: (state) => {
      api.setState(state);
    },
    postMessage: (message) => {
      api.postMessage(message);
    },
    subscribe: (listener) =>
      subscribeWindowMessages(
        listener,
        typeof window !== "undefined" && window.__TRAINER_BROWSER_PREVIEW__ === true,
      ),
  };
}

function createDomPreviewTransport(): WorkbenchHostTransport {
  return {
    id: "dom-preview",
    get surface() {
      return detectWindowSurface();
    },
    isNativeHost: false,
    getState: () => {
      if (typeof window === "undefined") {
        return undefined;
      }
      try {
        const raw = window.localStorage.getItem(getPreviewStorageKey());
        return raw ? (JSON.parse(raw) as PersistedWorkbenchState) : undefined;
      } catch {
        return undefined;
      }
    },
    setState: (state) => {
      if (typeof window === "undefined") {
        return;
      }
      try {
        window.localStorage.setItem(getPreviewStorageKey(), JSON.stringify(state));
      } catch {
        // Storage can be disabled in restricted preview contexts.
      }
    },
    postMessage: (message) => {
      if (typeof window === "undefined") {
        return;
      }
      if (
        message &&
        typeof message === "object" &&
        "type" in message &&
        (message.type === "webview/ready" ||
          message.type === "debug/error" ||
          message.type === "debug/visibleFacts")
      ) {
        return;
      }
      window.dispatchEvent(
        new CustomEvent("trainer:webview-action", {
          detail: message,
        }),
      );
    },
    subscribe: (listener) => subscribeWindowMessages(listener, true),
  };
}

export function registerWorkbenchHostTransport(
  transport: WorkbenchHostTransport | undefined,
): void {
  explicitTransport = transport;
}

export function resolveWorkbenchHostTransport(): WorkbenchHostTransport {
  if (explicitTransport) {
    return explicitTransport;
  }

  if (typeof window !== "undefined") {
    if (!cachedVsCodeApi && typeof window.acquireVsCodeApi === "function") {
      cachedVsCodeApi = window.acquireVsCodeApi();
      cachedVsCodeTransport = createVsCodeWebviewTransport(cachedVsCodeApi);
    }
    if (cachedVsCodeTransport) {
      return cachedVsCodeTransport;
    }
  }

  cachedDomPreviewTransport ??= createDomPreviewTransport();
  return cachedDomPreviewTransport;
}

export function isBrowserSidePanelSurface(): boolean {
  return resolveWorkbenchHostTransport().surface === "browser-sidepanel";
}

export function resetWorkbenchHostTransportForTests(): void {
  explicitTransport = undefined;
  cachedVsCodeApi = undefined;
  cachedVsCodeTransport = undefined;
  cachedDomPreviewTransport = undefined;
}
