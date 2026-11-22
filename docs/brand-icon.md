# Trainer Architectural Monogram Mark

Trainer’s brand mark is an understated, centered two-stroke architectural **T**
with a clean parallel diagonal parting on a pure porcelain-white canvas,
inspired by Trainer’s “White Moonlight Teacher” palette (Porcelain White
`#FFFFFF`/`#F8FAFC` + Midnight & Royal Indigo `#191642`/`#6366F1` — zero green).

- **Activity Bar & Webview Monochrome Mirror (`24 × 24`)**: `extension/media/trainer-icon.svg` and `extension/webview/src/assets/branding/trainer-mark.svg` are byte-identical `fill="currentColor"` silhouettes preserving clarity down to 16 px.
- **Color Brand & Favicon (`128 × 128` / `512 × 512`)**: `extension/media/trainer.svg`, `extension/webview/public/favicon.svg`, `browser-extension/icons/trainer-capture.svg`, and the Marketplace PNG `extension/media/trainer-icon.png` use the white-background indigo emblem.

| Asset | Consumer |
| --- | --- |
| `extension/media/trainer-icon.png` | Extension manifest / Marketplace icon (512 × 512 PNG on white) |
| `extension/media/trainer-icon.svg` | VS Code Activity Bar, native 24 px `currentColor` |
| `extension/webview/src/assets/branding/trainer-mark.svg` | Exact monochrome mirror |
| `extension/media/trainer.svg` | Standalone porcelain-white vector brand mark |
| `extension/webview/public/favicon.svg` | Normal and VS Code preview HTML favicon |
| `browser-extension/icons/trainer-capture.svg` & `icon{16,32,48,128}.png` | Browser capture companion extension icons |

`extension/media/trainer-icon.png` was rendered from the vector SVG via Chromium at 512 × 512 px (69,329 bytes, SHA-256 `7ba263b9c12891cfc97df12c9faea9b004710a7179e307aae948f650f6903504`).
