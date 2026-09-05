import React, { type ReactNode } from "react";
import ReactDOM from "react-dom/client";
import "katex/dist/katex.min.css";

import { sanitizeVisibleText } from "./lib/visibleText";
import { getInjectedBootstrapState, postMessage, reportWebviewError } from "./lib/vscode";
import type { ComposerLanguage } from "./lib/types";
import "./styles.css";

interface StartupErrorBoundaryProps {
  children: ReactNode;
}

interface StartupErrorBoundaryState {
  error?: Error;
}

interface StartupCopy {
  coach: string;
  starting: string;
  loading: string;
  preparing: string;
  preparingWorkspace: string;
  unavailable: string;
  errorHeading: string;
  errorMessage: string;
}

interface StartupBootstrap {
  sessionLabel?: unknown;
  memory?: {
    workspace?: {
      responseLanguage?: unknown;
    };
  };
  providerConfig?: {
    responseLanguage?: unknown;
  };
}

const STARTUP_COPY: Record<ComposerLanguage, StartupCopy> = {
  "zh-CN": {
    coach: "教练",
    starting: "正在打开",
    loading: "正在准备对话界面...",
    preparing: "正在准备",
    preparingWorkspace: "正在准备当前工作区。",
    unavailable: "暂时无法打开",
    errorHeading: "Trainer 暂时没能打开。",
    errorMessage: "关闭这个面板后重新打开；如果还是不行，重启 VS Code 后再试。",
  },
  "en-US": {
    coach: "Coach",
    starting: "Starting",
    loading: "Getting the coach ready...",
    preparing: "Getting ready:",
    preparingWorkspace: "Getting the current workspace ready.",
    unavailable: "Couldn't open",
    errorHeading: "Trainer couldn't open right now.",
    errorMessage: "Close this panel and open it again. If it still doesn't work, restart VS Code and try once more.",
  },
  "es-ES": {
    coach: "Entrenador",
    starting: "Iniciando",
    loading: "Preparando el entrenador...",
    preparing: "Preparando:",
    preparingWorkspace: "Preparando el espacio de trabajo actual.",
    unavailable: "No se puede abrir",
    errorHeading: "Trainer no se puede abrir ahora.",
    errorMessage: "Cierra este panel y vuelve a abrirlo. Si sigue sin funcionar, reinicia VS Code e inténtalo de nuevo.",
  },
  "fr-FR": {
    coach: "Coach",
    starting: "Ouverture",
    loading: "Préparation du coach...",
    preparing: "Préparation :",
    preparingWorkspace: "Préparation de l'espace de travail actuel.",
    unavailable: "Impossible d'ouvrir",
    errorHeading: "Trainer ne peut pas s'ouvrir pour le moment.",
    errorMessage: "Fermez ce panneau et rouvrez-le. Si cela ne fonctionne toujours pas, redémarrez VS Code et réessayez.",
  },
  "de-DE": {
    coach: "Coach",
    starting: "Wird geöffnet",
    loading: "Coach wird vorbereitet...",
    preparing: "Wird vorbereitet:",
    preparingWorkspace: "Der aktuelle Arbeitsbereich wird vorbereitet.",
    unavailable: "Kann nicht geöffnet werden",
    errorHeading: "Trainer kann gerade nicht geöffnet werden.",
    errorMessage: "Schließe dieses Panel und öffne es erneut. Wenn es weiterhin nicht funktioniert, starte VS Code neu und versuche es noch einmal.",
  },
  "ja-JP": {
    coach: "コーチ",
    starting: "起動中",
    loading: "コーチを準備しています...",
    preparing: "準備中:",
    preparingWorkspace: "現在のワークスペースを準備しています。",
    unavailable: "開けません",
    errorHeading: "Trainer を今は開けません。",
    errorMessage: "このパネルを閉じて、もう一度開いてください。それでもだめなら、VS Code を再起動してからもう一度試してください。",
  },
  "ko-KR": {
    coach: "코치",
    starting: "시작 중",
    loading: "코치를 준비하고 있습니다...",
    preparing: "준비 중:",
    preparingWorkspace: "현재 작업 공간을 준비하고 있습니다.",
    unavailable: "열 수 없습니다",
    errorHeading: "지금은 Trainer를 열 수 없습니다.",
    errorMessage: "이 패널을 닫았다가 다시 열어 보세요. 계속되지 않으면 VS Code를 재시작한 뒤 다시 시도하세요.",
  },
  "pt-BR": {
    coach: "Treinador",
    starting: "Iniciando",
    loading: "Preparando o treinador...",
    preparing: "Preparando:",
    preparingWorkspace: "Preparando o espaço de trabalho atual.",
    unavailable: "Não foi possível abrir",
    errorHeading: "O Trainer não pode ser aberto agora.",
    errorMessage: "Feche este painel e abra-o novamente. Se ainda não funcionar, reinicie o VS Code e tente outra vez.",
  },
};

function resolveStartupLanguage(injected?: StartupBootstrap): ComposerLanguage {
  const candidates = [
    injected?.memory?.workspace?.responseLanguage,
    injected?.providerConfig?.responseLanguage,
    typeof document === "undefined" ? undefined : document.documentElement.lang,
    typeof navigator === "undefined" ? undefined : navigator.language,
  ];

  for (const candidate of candidates) {
    if (typeof candidate !== "string") {
      continue;
    }
    if (Object.prototype.hasOwnProperty.call(STARTUP_COPY, candidate)) {
      return candidate as ComposerLanguage;
    }
    if (candidate.toLowerCase().startsWith("zh")) {
      return "zh-CN";
    }
  }

  return "en-US";
}

function startupCopy(injected?: StartupBootstrap): StartupCopy {
  return STARTUP_COPY[resolveStartupLanguage(injected)];
}

class StartupErrorBoundary extends React.Component<
  StartupErrorBoundaryProps,
  StartupErrorBoundaryState
> {
  state: StartupErrorBoundaryState = {};

  static getDerivedStateFromError(error: Error): StartupErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error): void {
    console.error("[trainer] render failure", error);
    reportWebviewError({
      source: "render-boundary",
      message: error.message || "Unknown render failure",
      stack: error.stack,
    });
  }

  render(): ReactNode {
    if (this.state.error) {
      return <FatalStartupError />;
    }

    return this.props.children;
  }
}

function FatalStartupError() {
  const copy = startupCopy(getInjectedBootstrapState<StartupBootstrap>());

  return (
    <div className="trainer-startup-error">
      <div className="trainer-startup-error__eyebrow">
        <span>Trainer</span>
        <span>{copy.unavailable}</span>
      </div>
      <div className="trainer-startup-error__panel">
        <strong className="trainer-startup-error__heading">{copy.errorHeading}</strong>
        <p className="trainer-startup-error__message">{copy.errorMessage}</p>
      </div>
    </div>
  );
}

function toError(error: unknown): Error {
  if (error instanceof Error) {
    return error;
  }

  if (typeof error === "string" && error.trim().length > 0) {
    return new Error(error);
  }

  return new Error("Unknown startup error");
}

function preferredTheme(): "light" | "dark" {
  if (typeof window !== "undefined" && typeof window.matchMedia === "function") {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  return "dark";
}

function StartupShell({ copy, message }: { copy: StartupCopy; message: string }) {
  return (
    <div className="trainer-startup-shell">
      <div className="trainer-startup-shell__eyebrow">
        <span>{copy.coach}</span>
        <span>{copy.starting}</span>
      </div>
      <div className="trainer-startup-shell__card">
        <strong className="trainer-startup-shell__heading">{copy.loading}</strong>
        <p className="trainer-startup-shell__message">
          {message}
        </p>
      </div>
    </div>
  );
}

const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error("Trainer root element was not found.");
}

const root = ReactDOM.createRoot(rootElement);
let startupFailed = false;
let bootstrapStartedAt = Date.now();
let bootstrapRecoveryRequested = false;
let lastRenderedFatalMessage = "";
let startupUiMounted = false;

function renderStartupFailure(error: unknown): void {
  const resolvedError = toError(error);
  const signature = `${resolvedError.name}:${resolvedError.message}:${resolvedError.stack ?? ""}`;
  if (startupFailed && signature === lastRenderedFatalMessage) {
    return;
  }

  startupFailed = true;
  lastRenderedFatalMessage = signature;
  console.error("[trainer] startup failure", resolvedError);
  reportWebviewError({
    source: "startup",
    message: resolvedError.message || "Unknown startup failure",
    stack: resolvedError.stack,
  });
  root.render(<FatalStartupError />);
}

function renderStartupShell(copy: StartupCopy, message: string): void {
  root.render(<StartupShell copy={copy} message={message} />);
}

function requestBootstrapRecovery(reason: string): void {
  if (bootstrapRecoveryRequested) {
    return;
  }
  bootstrapRecoveryRequested = true;
  reportWebviewError({
    source: "bootstrap-recovery",
    message: reason,
  });
  postMessage({ type: "request/bootstrap" });
}

window.addEventListener("error", (event) => {
  const error = toError(event.error ?? event.message);
  reportWebviewError({
    source: "window.error",
    message: error.message,
    stack: error.stack,
  });
  if (!startupFailed && !startupUiMounted) {
    renderStartupFailure(event.error ?? event.message);
  }
  requestBootstrapRecovery("Window error detected after render; requesting a fresh bootstrap.");
});

window.addEventListener("unhandledrejection", (event) => {
  const error = toError(event.reason);
  reportWebviewError({
    source: "unhandledrejection",
    message: error.message,
    stack: error.stack,
  });
  if (!startupFailed && !startupUiMounted) {
    renderStartupFailure(event.reason);
  }
  requestBootstrapRecovery("Unhandled rejection detected after render; requesting a fresh bootstrap.");
});

async function bootstrap(): Promise<void> {
  bootstrapStartedAt = Date.now();
  startupFailed = false;
  bootstrapRecoveryRequested = false;
  lastRenderedFatalMessage = "";
  startupUiMounted = false;

  // Browser live preview: `index.html?live=1&sidecarPort=<port>` wires the real
  // sidecar event bridge (training commands, stream cancel) that otherwise only
  // the vscode-preview.html entry installs.
  const previewSearch = new URLSearchParams(window.location.search);
  if (previewSearch.get("live") === "1" && typeof window.acquireVsCodeApi !== "function") {
    const { installBrowserPreviewEnvironment } = await import("./lib/browserPreviewHarness");
    installBrowserPreviewEnvironment();
  }

  const injected = getInjectedBootstrapState<StartupBootstrap>();
  const sessionLabel = sanitizeVisibleText(injected?.sessionLabel).trim();
  const copy = startupCopy(injected);
  renderStartupShell(
    copy,
    sessionLabel
      ? `${copy.preparing} ${sessionLabel}`
      : copy.preparingWorkspace,
  );

  const [{ App }, { applyWorkbenchTheme, installWorkbenchHostThemeBridge }] = await Promise.all([
    import("./app/App"),
    import("./lib/theme"),
  ]);

  applyWorkbenchTheme(preferredTheme());
  installWorkbenchHostThemeBridge();

  root.render(
    <React.StrictMode>
      <StartupErrorBoundary>
        <App />
      </StartupErrorBoundary>
    </React.StrictMode>,
  );
  rootElement!.dataset.trainerAppReady = "true";
  startupUiMounted = true;
}

void bootstrap().catch((error) => {
  renderStartupFailure(error);
});

window.setTimeout(() => {
  if (!startupFailed && !startupUiMounted && Date.now() - bootstrapStartedAt >= 2500) {
    requestBootstrapRecovery("Trainer bootstrap watchdog requested a fresh bootstrap after reopen.");
  }
}, 2500);
