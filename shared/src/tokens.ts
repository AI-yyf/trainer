/**
 * Trainer design tokens.
 *
 * Colour is intentionally absent here. Every surface, text, border, accent and
 * semantic colour resolves from the active VS Code theme (`--vscode-*`), with
 * CSS system colours (`Canvas`, `CanvasText`, `GrayText`, …) as the fallback
 * for the standalone browser preview. Nothing in the product hardcodes a hue,
 * so Trainer follows any VS Code theme — light, dark, high contrast or custom.
 *
 * Only geometry, spacing and typography scale live in TypeScript, because
 * those values are layout decisions rather than theme decisions.
 */
export const workbenchTokens = {
  radius: {
    s: "4px",
    m: "6px",
    l: "8px",
  },
  space: {
    1: "4px",
    2: "8px",
    3: "12px",
    4: "16px",
    5: "24px",
    6: "32px",
  },
  type: {
    ui: "var(--vscode-font-family, 'Segoe UI Variable Text', 'Segoe UI Variable', 'Segoe UI', system-ui, sans-serif), 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei UI', 'Microsoft YaHei', 'Noto Sans CJK SC'",
    body: "var(--vscode-font-family, 'Segoe UI Variable Text', 'Segoe UI Variable', 'Segoe UI', system-ui, sans-serif), 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei UI', 'Microsoft YaHei', 'Noto Sans CJK SC'",
    mono: "var(--vscode-editor-font-family, 'Cascadia Code', Consolas, monospace), 'Noto Sans Mono CJK SC'",
    sizeSm: "13px",
    sizeMd: "13px",
    sizeLg: "13px",
    lineHeight: "1.5",
  },
} as const;

export type WorkbenchTokens = typeof workbenchTokens;
export type WorkbenchThemeName = "light" | "dark";
