'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const webviewRoot = path.resolve(__dirname, '..', 'webview', 'src');
const primitivesPath = path.join(
  webviewRoot,
  'styles',
  'sections',
  'shared-design-system-primitives-empty-state-skeleton-shimmer.css',
);
const spinnerPath = path.join(webviewRoot, 'components', 'common', 'TrainerSpinner.tsx');
const commonIndexPath = path.join(webviewRoot, 'components', 'common', 'index.ts');

test('trainer spinner primitive is token-driven with a reduced-motion fallback', () => {
  const css = fs.readFileSync(primitivesPath, 'utf8');

  assert.match(css, /@keyframes trainer-spin/);
  assert.match(css, /\.trainer-spinner \{/);
  assert.match(css, /border-top-color: var\(--accent\)/);
  assert.match(css, /animation: trainer-spin 700ms linear infinite/);
  // No hardcoded colors: the ring uses the accent tokens only.
  assert.doesNotMatch(css, /\.trainer-spinner[^{]*\{[^}]*#[0-9a-f]{3,8}/i);
  // Reduced motion swaps rotation for a calm ring-and-dot mark.
  const reduced = css.slice(css.indexOf('@media (prefers-reduced-motion: reduce)'));
  assert.match(reduced, /\.trainer-spinner \{[\s\S]*?animation: none;/);
  assert.match(reduced, /\.trainer-spinner::after/);
});

test('TrainerSpinner exposes a localized status role and ships from common', () => {
  const component = fs.readFileSync(spinnerPath, 'utf8');
  const index = fs.readFileSync(commonIndexPath, 'utf8');

  assert.match(component, /export function TrainerSpinner/);
  assert.match(component, /role="status"/);
  assert.match(component, /aria-label=\{label\}/);
  assert.match(component, /trainer-spinner--\$\{size\}/);
  assert.match(index, /export \{ TrainerSpinner \} from "\.\/TrainerSpinner";/);
});

test('async surfaces use the spinner instead of bare text ellipses', () => {
  const mermaid = fs.readFileSync(
    path.join(webviewRoot, 'components', 'coach', 'MermaidBlock.tsx'),
    'utf8',
  );
  const pdf = fs.readFileSync(
    path.join(webviewRoot, 'components', 'preview', 'PdfPreviewContent.tsx'),
    'utf8',
  );
  const audio = fs.readFileSync(
    path.join(webviewRoot, 'components', 'preview', 'AudioPreviewContent.tsx'),
    'utf8',
  );

  assert.match(mermaid, /loadingLabel: string;/);
  assert.match(mermaid, /<TrainerSpinner size="sm" label=\{loadingLabel\} \/>/);
  assert.doesNotMatch(mermaid, /message-mermaid__loading">\.\.\.</);
  assert.match(pdf, /<TrainerSpinner size="sm" label="Loading PDF preview">/);
  assert.match(audio, /<TrainerSpinner size="sm" label=\{statusText\}>/);
});
