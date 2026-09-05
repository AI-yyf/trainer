const lightTheme = {
  bg0: "#ffffff",
  bg1: "#f6f6f6",
  bg2: "#ededed",
  bg3: "#dcdcdc",
  fg0: "#1f1f1f",
  fg1: "#3b3b3b",
  fgMuted: "#6a6a6a",
  line: "#d2d2d2",
  accent: "#7b6f5d",
  accentSoft: "rgba(123, 111, 93, 0.08)",
  success: "#107c41",
  warning: "#8a6d1f",
  danger: "#c42b1c",
  focusRing: "rgba(123, 111, 93, 0.24)",
  overlay: "rgba(0, 0, 0, 0.22)",
  shadowSoft: "none",
  colorScheme: "light",
} as const;

const darkTheme = {
  bg0: "#121212",
  bg1: "#1a1a1a",
  bg2: "#222222",
  bg3: "#292929",
  fg0: "#efefef",
  fg1: "#cdcdcd",
  fgMuted: "#a0a0a0",
  line: "#343434",
  accent: "#9d907a",
  accentSoft: "rgba(157, 144, 122, 0.1)",
  success: "#4ec9b0",
  warning: "#d7ba7d",
  danger: "#f48771",
  focusRing: "rgba(157, 144, 122, 0.28)",
  overlay: "rgba(7, 7, 7, 0.58)",
  shadowSoft: "none",
  colorScheme: "dark",
} as const;

export const workbenchTokens = {
  color: {
    bg0: darkTheme.bg0,
    bg1: darkTheme.bg1,
    bg2: darkTheme.bg2,
    bg3: darkTheme.bg3,
    fg0: darkTheme.fg0,
    fg1: darkTheme.fg1,
    fgMuted: darkTheme.fgMuted,
    line: darkTheme.line,
    accent: darkTheme.accent,
    success: darkTheme.success,
    warning: darkTheme.warning,
    danger: darkTheme.danger,
    focusRing: darkTheme.focusRing,
  },
  themes: {
    light: lightTheme,
    dark: darkTheme,
  },
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
export type WorkbenchThemeName = keyof typeof workbenchTokens.themes;
export type WorkbenchThemeTokens = (typeof workbenchTokens.themes)[WorkbenchThemeName];
