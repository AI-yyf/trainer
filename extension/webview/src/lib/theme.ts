import { workbenchTokens, type WorkbenchThemeName } from "../../../../shared/src/tokens";

/**
 * Trainer follows the host theme.
 *
 * Colour always comes from the VS Code theme variables (`--vscode-*`) declared
 * in `styles/sections/trainer-design-tokens-base-styles.css`; for the browser
 * preview those resolve to CSS system colours (`Canvas`, `CanvasText`, …).
 * This bridge only mirrors which theme kind is active (light/dark) and keeps
 * the layout tokens installed. It never writes colour values.
 */
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

let activeFallbackTheme: WorkbenchThemeName = "dark";
let followHostTheme = true;

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

function syncHostTheme(): void {
  const resolvedTheme = followHostTheme
    ? resolveHostThemeName(activeFallbackTheme)
    : activeFallbackTheme;
  const root = document.documentElement;

  root.dataset.theme = resolvedTheme;
  // `color-scheme` is what makes the CSS system-colour fallbacks follow the
  // chosen theme in the standalone preview; inside VS Code the host sets it.
  root.style.colorScheme = resolvedTheme;
}

export function applyWorkbenchTheme(themeName: WorkbenchThemeName, followHost = true): void {
  const root = document.documentElement;

  activeFallbackTheme = themeName;
  followHostTheme = followHost;
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
