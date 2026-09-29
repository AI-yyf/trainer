/**
 * Render deck.html → trainer-intro.mp4
 *
 * The deck is driven by a single virtual clock (window.__seek), so every frame
 * is a pure function of t. We screenshot N frames and let ffmpeg encode them.
 *
 *   node render.mjs [--fps 30] [--quality 92] [--scale 1]
 */
import { chromium } from '/Users/Apple/Desktop/trainer/node_modules/playwright/index.mjs';
import { execFileSync } from 'node:child_process';
import { mkdirSync, rmSync, existsSync, statSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const FRAMES = join(HERE, 'frames');
const OUT = join(HERE, 'out');
const FFMPEG = '/opt/homebrew/bin/ffmpeg';

const argv = process.argv.slice(2);
const arg = (k, d) => {
  const i = argv.indexOf('--' + k);
  return i === -1 ? d : argv[i + 1];
};
const FPS = Number(arg('fps', 30));
const QUALITY = Number(arg('quality', 92));
const SCALE = Number(arg('scale', 1));
const KEEP_FRAMES = argv.includes('--keep');

rmSync(FRAMES, { recursive: true, force: true });
mkdirSync(FRAMES, { recursive: true });
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({
  args: ['--force-color-profile=srgb', '--disable-lcd-text', '--font-render-hinting=none'],
});
const ctx = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  deviceScaleFactor: SCALE,
});
const page = await ctx.newPage();
page.on('pageerror', e => console.error('[page error]', e.message));
page.on('console', m => { if (m.type() === 'error') console.error('[console]', m.text().slice(0, 300)); });

await page.goto('file://' + join(HERE, 'deck.html'));
await page.waitForFunction(() => window.__ready, null, { timeout: 30000 });
await page.evaluate(() => window.__ready);

const duration = await page.evaluate(() => window.__duration);
const total = Math.ceil(duration * FPS);
console.log(`rendering ${total} frames @ ${FPS}fps  (${duration}s, ${1920 * SCALE}x${1080 * SCALE})`);

const t0 = Date.now();
for (let i = 0; i < total; i++) {
  const t = i / FPS;
  await page.evaluate(tt => window.__seek(tt), t);
  const name = join(FRAMES, `f${String(i).padStart(5, '0')}.jpg`);
  await page.screenshot({ path: name, type: 'jpeg', quality: QUALITY });
  if (i % 60 === 0 || i === total - 1) {
    const pct = ((i + 1) / total * 100).toFixed(1);
    const el = (Date.now() - t0) / 1000;
    const eta = el / (i + 1) * (total - i - 1);
    console.log(`  ${String(i).padStart(5)}/${total}  t=${t.toFixed(2)}s  ${pct}%  elapsed ${el.toFixed(0)}s  eta ${eta.toFixed(0)}s`);
  }
}
await browser.close();

const count = readdirSync(FRAMES).filter(f => f.endsWith('.jpg')).length;
console.log(`captured ${count} frames, encoding…`);

const mp4 = join(OUT, 'trainer-intro.mp4');
execFileSync(FFMPEG, [
  '-y', '-hide_banner', '-loglevel', 'error',
  '-framerate', String(FPS),
  '-i', join(FRAMES, 'f%05d.jpg'),
  '-c:v', 'libx264',
  '-preset', 'slow',
  '-crf', '17',
  '-pix_fmt', 'yuv420p',
  '-profile:v', 'high',
  '-level', '4.1',
  '-movflags', '+faststart',
  mp4,
], { stdio: 'inherit' });

// a lighter-weight web-friendly copy
execFileSync(FFMPEG, [
  '-y', '-hide_banner', '-loglevel', 'error',
  '-i', mp4, '-c:v', 'libx264', '-preset', 'slow', '-crf', '26',
  '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
  join(OUT, 'trainer-intro-web.mp4'),
], { stdio: 'inherit' });

if (!KEEP_FRAMES) rmSync(FRAMES, { recursive: true, force: true });

for (const f of [mp4, join(OUT, 'trainer-intro-web.mp4')]) {
  console.log(`${f}  ${(statSync(f).size / 1048576).toFixed(1)} MB`);
}
console.log(`done in ${((Date.now() - t0) / 1000 / 60).toFixed(1)} min`);
