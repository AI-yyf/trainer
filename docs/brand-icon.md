# Trainer T + coach-whistle icon

The mark fuses Trainer’s initial with a coach whistle: the T crossbar forms the
hollow mouthpiece, and its stem joins a rounded air chamber. A small rear loop,
an angular air window, and two coral sound strokes make the whistle recognizable.
Turquoise and rounded geometry keep it lively and approachable.

The selected PNG was generated with the built-in imagegen tool on 2026-10-08,
using the previous whistle PNG as an editing reference, then copied unchanged
into the repository. Actual dimensions: 1254 × 1254, RGBA, 435,268 bytes. All four
corners are transparent; the alpha range is 0–255. SHA-256:

`1bdbdc37c9ce815b630fc0773743bde4df712e9052dac3635e74d1d510328d13`.

The SVGs are a manually drawn native vector adaptation of that generated mark.
They share three filled paths in a 24 × 24 viewBox, with real negative-space
cutouts using evenodd fill. They contain no embedded raster. The Activity Bar and
its webview mirror use currentColor; the brand SVG and favicon adapt their two
colors to dark/light mode. The T silhouette remains legible in monochrome.

| Asset | Consumer |
| --- | --- |
| extension/media/trainer-icon.png | Extension manifest / Marketplace icon |
| extension/media/trainer-icon.svg | VS Code Activity Bar, native 24 px currentColor |
| extension/webview/src/assets/branding/trainer-mark.svg | Exact monochrome mirror |
| extension/media/trainer.svg | Theme-aware standalone brand mark |
| extension/webview/public/favicon.svg | Normal and VS Code preview HTML favicon |

Browser rendering was checked at 16, 24, and 128 CSS pixels on dark/light
backgrounds: all 18 raster/vector image loads and six inline monochrome SVGs
rendered. The sidebar guard checks mirror parity, native size, currentColor, and
absence of embedded raster. Review artifacts are in ignored output:

- `output/maturity/brand/icon-comparison.png`
- `output/maturity/brand/icon-asset-check.json`

## Generation prompt

Built-in imagegen edit, transparent background, one referenced whistle PNG:

```text
Use case: logo-brand. Edit the referenced Trainer coach-whistle icon into a SINGLE integrated T + WHISTLE brand mark.
Keep the reference's lively flat turquoise-and-coral palette and friendly rounded geometry, but redesign the silhouette around a clearly recognizable uppercase T. The T is the structure of the whistle itself, not a letter printed on a whistle.
The broad rounded horizontal crossbar of the T is the whistle's air tube and mouthpiece; its right end has a small unmistakable hollow blowing opening. A short central vertical stem naturally joins into a rounded whistle air chamber beneath it, forming the vertical stroke of the T. The air chamber can have a tiny rear attachment loop or a curved negative-space air slit, but stay simple. Two short warm coral sound strokes by the right mouthpiece express a coach calling the learner forward. A small angular air window in the crossbar reinforces the whistle function. The top crossbar must clearly extend on both sides of the center stem so the entire outline reads T even at 16px in monochrome.
This is one coherent object with smooth shared edges and a strong compact silhouette, not a collage. Keep the code/coaching identity implied by the initial T and the actual whistle. No separate typography, no pasted T glyph, no generic AI sparkle.
Style: very clean production-ready flat graphic, bold turquoise body, coral sound strokes, rounded corners and smooth curves. No gradients, shadow, texture, speckles, gloss or 3D perspective. The body stays opaque with true transparent openings.
Composition: centered square 1:1 logo with generous transparent margins, balanced and recognizable at 16px, 24px, and 128px.
Transparent background, no tile or frame. No words or other letters beyond the integrated T silhouette.
```
