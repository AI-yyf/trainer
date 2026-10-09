# Trainer geometric T icon

Trainer’s mark is a custom uppercase T: a broad crossbar, a centered stem,
softened corners, and a small upper-right chamfer. Its single silhouette stays
clear at Activity Bar and favicon sizes. The design replaces the T + whistle
mark at the user’s request on 2026-10-09.

All four SVG assets share one filled path in a 24 × 24 viewBox. The silhouette
occupies x = 3–21 and y = 4–20, leaving balanced transparent margins. No font,
embedded raster, decorative strokes, or external resource is required.

The Activity Bar and its webview mirror are identical and use currentColor.
The standalone brand SVG and favicon use the existing turquoise palette:
#009d9a in light mode and #24cecc in dark mode. The Marketplace PNG uses the
light-mode color on a transparent background.

| Asset | Consumer |
| --- | --- |
| extension/media/trainer-icon.png | Extension manifest / Marketplace icon |
| extension/media/trainer-icon.svg | VS Code Activity Bar, native 24 px currentColor |
| extension/webview/src/assets/branding/trainer-mark.svg | Exact monochrome mirror |
| extension/media/trainer.svg | Theme-aware standalone brand mark |
| extension/webview/public/favicon.svg | Normal and VS Code preview HTML favicon |

The PNG was rendered directly from the native brand SVG with Chromium:
512 × 512, RGBA, 4,067 bytes. All four corners are transparent; the alpha range
is 0–255. SHA-256:

`8dd55ead7faf28a9a25ccddf5fee6db6047caab71ae624b290e2dea16b689950`.

Browser rendering was inspected at 16, 24, and 128 CSS pixels on dark/light
backgrounds. All 18 raster/vector image loads and six inline monochrome marks
rendered. The existing sidebar guard checks mirror parity, native dimensions,
currentColor, and absence of embedded raster.

Review artifacts and the rendering script are in ignored output:

- `output/brand-t/t-mark-light.png`
- `output/brand-t/t-mark-dark.png`
- `output/brand-t/asset-check.json`
- `output/brand-t/render-marks.cjs`

Earlier branding screenshots and verification reports remain historical records
of their original commits.
