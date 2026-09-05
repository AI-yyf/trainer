'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const composerPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'composer',
  'CoachComposer.tsx',
);
const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const stylesPath = path.resolve(__dirname, '..', 'webview', 'src', 'styles.css');

function sourceBetween(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  assert.ok(start >= 0, `expected ${startMarker}`);
  const end = source.indexOf(endMarker, start);
  assert.ok(end > start, `expected ${endMarker} after ${startMarker}`);
  return source.slice(start, end);
}

function compactAndDefaultBounds(source, marker) {
  const resizeEffect = sourceBetween(
    source,
    'const minHeight =',
    'textarea.style.height = "0px";',
  );
  const markerIndex = resizeEffect.indexOf(marker);
  assert.ok(markerIndex >= 0, `expected ${marker}`);
  const nextDeclaration = resizeEffect.indexOf('const ', markerIndex + marker.length);
  const candidates = [
    ...resizeEffect
      .slice(markerIndex, nextDeclaration > markerIndex ? nextDeclaration : undefined)
      .matchAll(/compactMode\s*\?\s*(\d+)\s*:\s*(\d+)/g),
  ];
  const values = candidates.at(-1);
  assert.ok(values, `expected numeric compact/default ${marker} bound`);
  return { compact: Number(values[1]), default: Number(values[2]) };
}

test('Composer gives parent key handling first, then only navigates sent history from collapsed text boundaries', () => {
  const source = fs.readFileSync(composerPath, 'utf8');
  const handler = sourceBetween(source, 'const handleTextareaKeyDown', 'const handleComposerMouseDown');

  assert.match(source, /onNavigateHistory\?: \(direction: "previous" \| "next"\) => boolean;/);
  assert.match(handler, /onKeyDown\?\.\(event\);/);
  assert.match(handler, /event\.defaultPrevented/);
  assert.ok(
    handler.indexOf('onKeyDown?.(event);') < handler.indexOf('event.defaultPrevented'),
    'command and skill candidates must receive the key before draft history',
  );
  assert.match(handler, /textarea\.selectionStart === textarea\.selectionEnd/);
  assert.match(handler, /textarea\.selectionStart === 0/);
  assert.match(handler, /textarea\.selectionEnd === textarea\.value\.length/);
  assert.match(handler, /event\.key === "ArrowUp"[\s\S]*?"previous"/);
  assert.match(handler, /event\.key === "ArrowDown"[\s\S]*?"next"/);
  assert.match(handler, /direction && onNavigateHistory\(direction\)[\s\S]*?event\.preventDefault\(\)/);
  assert.match(source, /onKeyDown=\{handleTextareaKeyDown\}/);
});

test('App history uses only this session user sends and preserves a cursor plus scratch draft', () => {
  const source = fs.readFileSync(appPath, 'utf8');

  assert.match(source, /sessionSentMessageHistory/);
  assert.match(source, /data\.conversation\s*\.filter\(\(message\) => message\.role === "user"\)/);
  assert.match(source, /composerHistoryCursorRef/);
  assert.match(source, /composerHistoryScratchDraftRef/);
  assert.match(source, /const navigateComposerHistory/);
  assert.match(source, /composerHistoryScratchDraftRef\.current = draft/);
  assert.match(source, /setComposerDraft\(composerHistoryScratchDraftRef\.current\)/);
  assert.match(source, /onNavigateHistory=\{navigateComposerHistory\}/);
});

test('Composer side mouse buttons map to history and consume browser navigation events', () => {
  const source = fs.readFileSync(composerPath, 'utf8');
  const handlers = sourceBetween(source, 'const navigateWithSideButton', '  useEffect(() => {');

  assert.match(source, /const handleComposerMouseDown/);
  assert.match(source, /const handleComposerAuxClick/);
  assert.match(source, /onMouseDown=\{handleComposerMouseDown\}/);
  assert.match(source, /onAuxClick=\{handleComposerAuxClick\}/);
  assert.match(handlers, /event\.button !== 3/);
  assert.match(handlers, /event\.button !== 4/);
  assert.match(handlers, /button === 3 \? "previous" : "next"/);
  assert.match(handlers, /onNavigateHistory\(button === 3 \? "previous" : "next"\)/);
  assert.match(handlers, /event\.preventDefault\(\)/);
});

test('Image drops use the existing attachment staging path and show a transient drag state', () => {
  const source = fs.readFileSync(composerPath, 'utf8');
  const styles = fs.readFileSync(stylesPath, 'utf8');

  assert.match(source, /onDragEnter=\{/);
  assert.match(source, /onDragLeave=\{/);
  assert.match(source, /onDragOver=\{/);
  assert.match(source, /onDrop=\{/);
  assert.match(source, /event\.dataTransfer\.files/);
  assert.match(source, /handleAttachFiles\(event\.dataTransfer\.files\)/);
  assert.match(source, /event\.preventDefault\(\)/);
  assert.match(source, /set\w*Drag\w*\(true\)/);
  assert.match(source, /set\w*Drag\w*\(false\)/);
  assert.match(source, /if \(attachmentsEnabled\) \{\s*setIsDragActive\(true\);/);
  assert.match(source, /composer__frame--drop-unavailable/);
  assert.match(source, /composer__drop-prompt--unavailable/);
  assert.match(source, /data-drop-state=\{isDragActive \? "active" : undefined\}/);
  assert.match(source, /composer__frame--drop-target/);
  assert.match(source, /composer__drop-prompt/);
  assert.doesNotMatch(source, /fileInputRef/);
  assert.doesNotMatch(source, /composer__attach-btn/);
  assert.match(
    styles,
    /\.composer__frame--drop-target\s*\{[\s\S]*?(?:border(?:-color)?|outline|background):/,
  );
  assert.match(styles, /\.composer__drop-prompt\s*\{[\s\S]*?animation:/);
  assert.match(styles, /\.composer__frame--drop-unavailable\s*\{[\s\S]*?--composer-drop-accent:\s*var\(--warning\)/);
  assert.match(styles, /\.composer__drop-prompt--unavailable\s*\{[\s\S]*?--composer-drop-accent:\s*var\(--warning\)/);
  assert.match(styles, /@keyframes composer-drop-pulse/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)/);
});

test('Composer expands vertical input room in both densities without changing the narrow-sidebar width contract', () => {
  const source = fs.readFileSync(composerPath, 'utf8');
  const styles = fs.readFileSync(stylesPath, 'utf8');
  const maxBounds = compactAndDefaultBounds(source, 'const maxHeight =');
  const frame = styles.match(/(?:^|\n)\.composer__frame\s*\{[\s\S]*?\n\}/);
  const textarea = styles.match(/(?:^|\n)\.composer__frame textarea\s*\{[\s\S]*?\n\}/);

  assert.ok(frame, 'expected the narrow-sidebar composer frame rule');
  assert.ok(textarea, 'expected the narrow-sidebar textarea rule');
  assert.match(source, /const minHeight = Math\.max\(/);
  assert.match(source, /padTop \+ padBottom,\s*36,/);
  assert.ok(maxBounds.compact >= 112, 'compact composer maximum stays tall enough to grow');
  assert.ok(maxBounds.default >= 140, 'default composer maximum stays tall enough to grow');
  assert.match(frame[0], /flex:\s*1/);
  assert.match(textarea[0], /width:\s*100%/);
  assert.match(styles, /@media \(max-width: 360px\)[\s\S]*?\.composer__accessory/);
});

test('View-specific composer modes use a bounded native-style menu instead of an unstructured select', () => {
  const composerSource = fs.readFileSync(composerPath, 'utf8');
  const appSource = fs.readFileSync(appPath, 'utf8');
  const styles = fs.readFileSync(stylesPath, 'utf8');

  assert.match(composerSource, /const \[isModeMenuOpen, setIsModeMenuOpen\] = useState\(false\)/);
  assert.match(composerSource, /aria-haspopup="menu"/);
  assert.match(composerSource, /className="composer-mode-menu"/);
  assert.match(composerSource, /role="menu"/);
  assert.match(composerSource, /role="menuitemradio"/);
  assert.match(composerSource, /handleModeTriggerKeyDown/);
  assert.match(composerSource, /handleModeMenuKeyDown/);
  assert.match(composerSource, /document\.addEventListener\("pointerdown", handlePointerDown\)/);
  assert.doesNotMatch(composerSource, /<select\b/);
  assert.match(appSource, /description: mode\.header/);
  assert.match(styles, /\.composer-mode-menu\s*\{[\s\S]*?inline-size:\s*min\(272px, calc\(100vw - 32px\)\)/);
  assert.match(styles, /\.composer__mode-control\s*\{[\s\S]*?position:\s*static;/);
  assert.match(styles, /@media \(max-width: 360px\)[\s\S]*?\.composer-mode-menu/);
  assert.match(styles, /\.composer-mode-menu__option\.is-active[\s\S]*?background:/);
});
