import {
  workbenchTokens,
  type WorkbenchThemeName,
  type WorkbenchThemeTokens,
} from "../../../../shared/src/tokens";

const rootVariableEntries = [
  ["--radius-s", workbenchTokens.radius.s],
  ["--radius-m", workbenchTokens.radius.m],
  ["--radius-l", workbenchTokens.radius.l],
  ["--space-1", workbenchTokens.space[1]],
  ["--space-2", workbenchTokens.space[2]],
  ["--space-3", workbenchTokens.space[3]],
  ["--space-4", workbenchTokens.space[4]],
  ["--space-5", workbenchTokens.space[5]],
  ["--space-6", workbenchTokens.space[6]],
  ["--line-height-body", workbenchTokens.type.lineHeight],
] as const;

const fallbackVariableEntries = [
  ["--trainer-fallback-bg-0", "bg0"],
  ["--trainer-fallback-bg-1", "bg1"],
  ["--trainer-fallback-bg-2", "bg2"],
  ["--trainer-fallback-bg-3", "bg3"],
  ["--trainer-fallback-fg-0", "fg0"],
  ["--trainer-fallback-fg-1", "fg1"],
  ["--trainer-fallback-fg-muted", "fgMuted"],
  ["--trainer-fallback-line", "line"],
  ["--trainer-fallback-accent", "accent"],
  ["--trainer-fallback-success", "success"],
  ["--trainer-fallback-warning", "warning"],
  ["--trainer-fallback-danger", "danger"],
  ["--trainer-fallback-focus-ring", "focusRing"],
  ["--trainer-fallback-overlay", "overlay"],
  ["--trainer-fallback-shadow-soft", "shadowSoft"],
] as const satisfies ReadonlyArray<readonly [string, keyof WorkbenchThemeTokens]>;

let activeFallbackTheme: WorkbenchThemeName = "dark";

function setStyleProperty(
  style: CSSStyleDeclaration | Record<string, unknown> | undefined,
  name: string,
  value: string,
): void {
  if (!style) {
    return;
  }
  if (typeof (style as CSSStyleDeclaration).setProperty === "function") {
    (style as CSSStyleDeclaration).setProperty(name, value);
    return;
  }
  (style as Record<string, unknown>)[name] = value;
}

function resolveHostThemeName(fallbackTheme: WorkbenchThemeName): WorkbenchThemeName {
  const root = document.documentElement;
  const body = document.body;
  const classNames = [root.getAttribute("class"), body?.getAttribute("class")]
    .filter((value): value is string => Boolean(value))
    .join(" ")
    .toLowerCase();
  const themeKinds = [
    root.getAttribute("data-vscode-theme-kind"),
    body?.getAttribute("data-vscode-theme-kind"),
  ]
    .filter((value): value is string => Boolean(value))
    .join(" ")
    .toLowerCase();

  if (
    classNames.includes("vscode-high-contrast-light") ||
    classNames.includes("high-contrast-light") ||
    classNames.includes("vscode-hc-light") ||
    classNames.includes("vscode-light") ||
    themeKinds.includes("light")
  ) {
    return "light";
  }
  if (
    classNames.includes("vscode-high-contrast") ||
    classNames.includes("vscode-hc-black") ||
    classNames.includes("vscode-dark") ||
    themeKinds.includes("dark") ||
    themeKinds.includes("high-contrast")
  ) {
    return "dark";
  }
  return fallbackTheme;
}

function applyFallbackTheme(themeName: WorkbenchThemeName): void {
  const fallback = workbenchTokens.themes[themeName];
  const root = document.documentElement;

  for (const [name, tokenName] of fallbackVariableEntries) {
    setStyleProperty(root.style, name, fallback[tokenName]);
  }
}

function syncHostTheme(): void {
  const resolvedTheme = resolveHostThemeName(activeFallbackTheme);
  const root = document.documentElement;

  root.dataset.theme = resolvedTheme;
  root.style.colorScheme = resolvedTheme;
  applyFallbackTheme(resolvedTheme);
}

export function applyWorkbenchTheme(themeName: WorkbenchThemeName): void {
  const root = document.documentElement;

  activeFallbackTheme = themeName;
  for (const [name, value] of rootVariableEntries) {
    setStyleProperty(root.style, name, value);
  }
  syncHostTheme();
}

export function installWorkbenchHostThemeBridge(): () => void {
  const sync = () => syncHostTheme();
  const root = document.documentElement;
  const observer = new MutationObserver(sync);
  const attributes = ["class", "data-vscode-theme-kind"];

  observer.observe(root, { attributes: true, attributeFilter: attributes });
  if (document.body) {
    observer.observe(document.body, { attributes: true, attributeFilter: attributes });
  }

  sync();

  return () => {
    observer.disconnect();
  };
}
