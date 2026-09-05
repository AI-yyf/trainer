'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const webviewRoot = path.resolve(__dirname, '..', 'webview');
const docxPreviewPath = path.resolve(
  webviewRoot,
  'src',
  'components',
  'preview',
  'DocxPreviewContent.tsx',
);
const packageJsonPath = path.resolve(webviewRoot, 'package.json');
const distAssetsDir = path.resolve(webviewRoot, 'dist', 'assets');

test('DocxPreviewContent sanitizes after renderAsync before visible innerHTML', () => {
  const source = fs.readFileSync(docxPreviewPath, 'utf8');
  assert.match(source, /import \{ sanitizePreviewHtml \} from ["']\.\.\/\.\.\/lib\/htmlSanitizer["']/);
  assert.match(source, /const staging = document\.createElement\(["']div["']\)/);
  assert.match(source, /await renderAsync\(arrayBuffer,\s*staging,\s*staging,/);
  assert.match(source, /const sanitized = sanitizePreviewHtml\(staging\.innerHTML\)/);
  assert.match(source, /docxContainer\.innerHTML\s*=\s*sanitized/);
  assert.match(source, /Safe DOCX preview unavailable/);
  assert.doesNotMatch(source, /await renderAsync\(arrayBuffer,\s*docxContainer/);
});

test('DocxPreviewContent mammoth fallback still sanitizes before display', () => {
  const source = fs.readFileSync(docxPreviewPath, 'utf8');
  assert.match(source, /const sanitizedFallback = sanitizePreviewHtml\(result\.value \?\? [\"'][\"']\)/);
  assert.match(source, /setFallbackHtml\(sanitizedFallback\)/);
});

test('DocxPreviewContent mammoth empty or unsanitized-empty fails closed without ready/fallback', () => {
  const source = fs.readFileSync(docxPreviewPath, 'utf8');
  assert.match(source, /if \(!sanitizedFallback\.trim\(\)\)/);
  assert.match(
    source,
    /Safe DOCX preview unavailable \(empty or unsanitized HTML was not shown\)/,
  );
  assert.match(source, /setFallbackHtml\(null\)/);
  assert.doesNotMatch(
    source,
    /setFallbackHtml\(sanitizePreviewHtml\(result\.value\)\);\s*setStatus\([\"']fallback[\"']\)/,
  );
  // empty mammoth path must not mark ready
  const mammothBlock = source.slice(source.indexOf('mammoth.convertToHtml'));
  const fallbackAssign = mammothBlock.indexOf("setStatus(\"fallback\")");
  const emptyGuard = mammothBlock.indexOf('!sanitizedFallback.trim()');
  assert.ok(emptyGuard >= 0 && emptyGuard < fallbackAssign, 'empty guard must precede fallback status');
  assert.doesNotMatch(mammothBlock.slice(0, fallbackAssign), /setStatus\([\"']ready[\"']\)/);
});

test('CoachMessageParts wires live DocxPreview for document assetUri file_preview parts', () => {
  const source = fs.readFileSync(
    path.resolve(webviewRoot, 'src', 'components', 'coach', 'CoachMessageParts.tsx'),
    'utf8',
  );
  assert.match(source, /import \{ DocxPreview \} from ["']\.\.\/preview\/DocxPreview["']/);
  assert.match(source, /import \{ isDocxPreviewPath \} from ["'].*previewAssets["']/);
  assert.match(source, /previewKind === ["']document["']/);
  assert.match(source, /isDocxPreviewPath\(part\.path\)/);
  assert.match(source, /<DocxPreview[\s\S]*src=\{assetUri\}/);
  // Fail-closed dual-read: snake_case host/sidecar fields still mount DocxPreview
  assert.match(source, /raw\.preview_kind/);
  assert.match(source, /raw\.asset_uri/);
});

test('conversation file_preview paints via CoachMessageParts only (registry is HTML stub)', () => {
  const bubble = fs.readFileSync(
    path.resolve(webviewRoot, 'src', 'components', 'coach', 'CoachMessageBubble.tsx'),
    'utf8',
  );
  const conversation = fs.readFileSync(
    path.resolve(webviewRoot, 'src', 'components', 'coach', 'CoachConversationView.tsx'),
    'utf8',
  );
  const app = fs.readFileSync(path.resolve(webviewRoot, 'src', 'app', 'App.tsx'), 'utf8');
  const sharedRegistry = fs.readFileSync(
    path.resolve(__dirname, '..', '..', 'shared', 'src', 'partsRendererRegistry.ts'),
    'utf8',
  );
  const coachPartRegistry = fs.readFileSync(
    path.resolve(webviewRoot, 'src', 'components', 'coach', 'parts', 'index.tsx'),
    'utf8',
  );

  // Live conversation paint path
  assert.match(bubble, /import \{ CoachMessageParts \} from ["']\.\/CoachMessageParts["']/);
  assert.match(bubble, /<CoachMessageParts parts=\{visibleParts \?\? \[\]\} language=\{language\} \/>/);
  assert.match(conversation, /import \{ CoachMessageBubble \} from ["']\.\/CoachMessageBubble["']/);
  assert.match(conversation, /<CoachMessageBubble[\s\S]*message=\{message\}/);
  assert.match(app, /<CoachConversationView/);
  assert.match(app, /<CoachMessageBubble/);

  // App/conversation must not route parts through shared HTML registry or React PartsRenderer
  assert.doesNotMatch(app, /partsRendererRegistry|PartsRenderer|getPartsRendererRegistry/);
  assert.doesNotMatch(conversation, /partsRendererRegistry|PartsRenderer|getPartsRendererRegistry|CoachMessageParts|partRegistry/);
  assert.doesNotMatch(bubble, /partsRendererRegistry|PartsRenderer|getPartsRendererRegistry|partRegistry|FilePreviewRenderer/);

  // shared registry file_preview is HTML stub — no DocxPreview mount
  const filePreviewRegister = sharedRegistry.match(
    /registry\.register(?:<FilePreviewPart>)?\(["']file_preview["'][\s\S]*?\}\);/,
  );
  assert.ok(filePreviewRegister, 'expected shared file_preview register block');
  assert.match(filePreviewRegister[0], /trainer-file-preview/);
  assert.doesNotMatch(filePreviewRegister[0], /DocxPreview|docx-preview/);

  // coach/parts partRegistry FilePreviewRenderer is dead for conversation (no import consumers)
  assert.match(coachPartRegistry, /file_preview:\s*\(\{ part \}\) => <FilePreviewRenderer part=\{part\} \/>/);
  assert.doesNotMatch(bubble, /from ["']\.\/parts["']|from ["']\.\/parts\/index/);
  assert.doesNotMatch(conversation, /from ["']\.\/parts["']|from ["']\.\/parts\/index/);
});

test('host-invented docx file_preview camelCase shape matches Coach DocxPreview gate', () => {
  const hostSource = fs.readFileSync(
    path.resolve(__dirname, '..', 'src', 'core', 'previewAssetUris.ts'),
    'utf8',
  );
  const coachSource = fs.readFileSync(
    path.resolve(webviewRoot, 'src', 'components', 'coach', 'CoachMessageParts.tsx'),
    'utf8',
  );

  // Host invents camelCase Coach-consumable fields (and maps snake→camel fail-closed).
  assert.match(hostSource, /HOST_DOCX_FILE_PREVIEW_MESSAGE_ID\s*=\s*["']host-file-preview-docx["']/);
  assert.match(hostSource, /type:\s*["']file_preview["']/);
  assert.match(hostSource, /previewKind:\s*["']document["']/);
  assert.match(hostSource, /assetUri:\s*preview\.assetUri/);
  assert.match(hostSource, /normalizeFilePreviewPartCamel/);
  assert.match(hostSource, /raw\.preview_kind/);
  assert.match(hostSource, /raw\.asset_uri/);

  // Coach gate: document + assetUri + docx path (camel, with snake fallback).
  assert.match(coachSource, /previewKind === ["']document["']/);
  assert.match(coachSource, /Boolean\(assetUri\)/);
  assert.match(coachSource, /isDocxPreviewPath\(part\.path\)/);
  assert.match(coachSource, /<DocxPreview[\s\S]*src=\{assetUri\}/);
});

test('webview package.json declares mammoth and docx-preview for real Docx preview', () => {
  const pkg = JSON.parse(fs.readFileSync(packageJsonPath, 'utf8'));
  const deps = pkg.dependencies ?? {};
  assert.equal(typeof deps.mammoth, 'string');
  assert.equal(typeof deps['docx-preview'], 'string');
  assert.match(deps.mammoth, /^\^?1\./);
  assert.match(deps['docx-preview'], /^\^?0\./);
});

test('webview dist includes a Docx preview chunk that only assigns sanitized HTML', () => {
  assert.ok(fs.existsSync(distAssetsDir), 'webview dist/assets missing — rebuild webview');
  const assetFiles = fs
    .readdirSync(distAssetsDir)
    .filter((name) => name.endsWith('.js'));
  const docxChunkNames = assetFiles.filter((name) => /^DocxPreviewContent-/i.test(name));
  assert.ok(
    docxChunkNames.length >= 1,
    `expected DocxPreviewContent-*.js in dist/assets, found: ${docxChunkNames.join(', ') || '(none)'}`,
  );

  let foundSanitizedAssign = false;
  let foundLibSurface = false;
  for (const name of docxChunkNames) {
    const body = fs.readFileSync(path.join(distAssetsDir, name), 'utf8');
    if (
      /Safe DOCX preview unavailable/.test(body) &&
      /innerHTML/.test(body)
    ) {
      foundSanitizedAssign = true;
    }
    if (/convertToHtml|renderAsync|docx-preview__docx/.test(body)) {
      foundLibSurface = true;
    }
  }

  if (!foundLibSurface) {
    for (const name of assetFiles) {
      const body = fs.readFileSync(path.join(distAssetsDir, name), 'utf8');
      if (/convertToHtml/.test(body) && /docx-preview__docx|Safe DOCX preview unavailable/.test(body)) {
        foundLibSurface = true;
        break;
      }
      // mammoth / docx-preview often land in adjacent hashed vendor chunks
      if (/mammoth|docx-preview/.test(name) || /\/\*! mammoth|docx-preview/.test(body)) {
        foundLibSurface = true;
        break;
      }
    }
  }

  // Broader proof: any asset containing both mammoth API and sanitizer fail-closed message
  if (!foundLibSurface || !foundSanitizedAssign) {
    for (const name of assetFiles) {
      const body = fs.readFileSync(path.join(distAssetsDir, name), 'utf8');
      if (/Safe DOCX preview unavailable/.test(body) && /innerHTML/.test(body)) {
        foundSanitizedAssign = true;
      }
      if (/\.convertToHtml\s*\(/.test(body) || /renderAsync/.test(body)) {
        foundLibSurface = true;
      }
    }
  }

  assert.ok(foundSanitizedAssign, 'Docx chunk must keep sanitized innerHTML assign + fail-closed empty message');
  assert.ok(foundLibSurface, 'dist must include mammoth/docx-preview code (not theater)');
});
