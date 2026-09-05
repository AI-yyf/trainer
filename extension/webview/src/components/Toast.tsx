import { type ReactNode, useCallback, createContext, useContext, useEffect, useState } from "react";

export type ToastLevel = "info" | "pass" | "warn" | "error";

export interface Toast {
  id: string;
  title: string;
  detail?: string;
  level: ToastLevel;
  duration?: number;
  action?: {
    label: string;
    onClick: () => void;
  };
}

export interface ToastOptions {
  title: string;
  detail?: string;
  level?: ToastLevel;
  duration?: number;
  action?: {
    label: string;
    onClick: () => void;
  };
}

interface ToastItemProps {
  toast: Toast;
  onDismiss: (id: string) => void;
}

interface ToastContainerProps {
  toasts: Toast[];
  onDismiss: (id: string) => void;
}

interface ToastContextValue {
  toasts: Toast[];
  showToast: (options: ToastOptions) => string;
  dismissToast: (id: string) => void;
  clearToasts: () => void;
}

interface ToastProviderProps {
  children: ReactNode;
  maxVisible?: number;
}

const levelIcons: Record<ToastLevel, string> = {
  info: "i",
  pass: "OK",
  warn: "!",
  error: "x",
};

const levelClasses: Record<ToastLevel, string> = {
  info: "toast--info",
  pass: "toast--pass",
  warn: "toast--warn",
  error: "toast--error",
};

const ToastContext = createContext<ToastContextValue | null>(null);

let globalShowToast: ((options: ToastOptions) => string) | null = null;

function ToastItem({ toast, onDismiss }: ToastItemProps) {
  const [isExiting, setIsExiting] = useState(false);

  const handleDismiss = useCallback(() => {
    setIsExiting(true);
    setTimeout(() => onDismiss(toast.id), 200);
  }, [onDismiss, toast.id]);

  useEffect(() => {
    if (toast.duration === 0) {
      return undefined;
    }
    const timer = setTimeout(handleDismiss, toast.duration ?? 4000);
    return () => clearTimeout(timer);
  }, [handleDismiss, toast.duration]);

  return (
    <div
      className={`toast ${levelClasses[toast.level]} ${isExiting ? "toast--exiting" : ""}`}
      role="alert"
      aria-live="polite"
    >
      {toast.duration !== 0 ? (
        <div
          className="toast__progress"
          style={{ animationDuration: `${toast.duration ?? 4000}ms` }}
        />
      ) : null}
      <span className="toast__icon" aria-hidden="true">
        {levelIcons[toast.level]}
      </span>
      <div className="toast__content">
        <span className="toast__title">{toast.title}</span>
        {toast.detail ? <span className="toast__detail">{toast.detail}</span> : null}
      </div>
      {toast.action ? (
        <button className="toast__action" onClick={toast.action.onClick}>
          {toast.action.label}
        </button>
      ) : null}
      <button
        className="toast__dismiss"
        onClick={handleDismiss}
        title="Close"
        aria-label="Close notification"
      >
        x
      </button>
    </div>
  );
}

function ToastContainer({ toasts, onDismiss }: ToastContainerProps) {
  if (toasts.length === 0) {
    return null;
  }

  return (
    <div className="toast-container" aria-live="polite">
      {toasts.map((toast) => (
        <ToastItem key={toast.id} toast={toast} onDismiss={onDismiss} />
      ))}
    </div>
  );
}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error("useToast must be used within ToastProvider");
  }
  return context;
}

export function showToast(options: ToastOptions): string {
  if (!globalShowToast) {
    console.warn("[Toast] No ToastProvider mounted, toast not shown:", options.title);
    return "";
  }
  return globalShowToast(options);
}

export function toastPass(title: string, detail?: string): string {
  return showToast({ title, detail, level: "pass" });
}

export function toastError(title: string, detail?: string): string {
  return showToast({ title, detail, level: "error", duration: 6000 });
}

export function toastWarn(title: string, detail?: string): string {
  return showToast({ title, detail, level: "warn", duration: 5000 });
}

export function toastInfo(title: string, detail?: string): string {
  return showToast({ title, detail, level: "info" });
}

export function ToastProvider({ children, maxVisible = 3 }: ToastProviderProps) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const showToastWithContext = useCallback(
    (options: ToastOptions): string => {
      const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      const toast: Toast = {
        id,
        ...options,
        level: options.level ?? "info",
      };

      setToasts((previous) => [toast, ...previous].slice(0, maxVisible));
      return id;
    },
    [maxVisible],
  );

  const dismissToast = useCallback((id: string) => {
    setToasts((previous) => previous.filter((toast) => toast.id !== id));
  }, []);

  const clearToasts = useCallback(() => {
    setToasts([]);
  }, []);

  useEffect(() => {
    globalShowToast = showToastWithContext;
    return () => {
      globalShowToast = null;
    };
  }, [showToastWithContext]);

  const value: ToastContextValue = {
    toasts,
    showToast: showToastWithContext,
    dismissToast,
    clearToasts,
  };

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </ToastContext.Provider>
  );
}
