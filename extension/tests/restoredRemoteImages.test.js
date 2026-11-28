// Restored behavioral regression test. Original file: extension/tests/remoteImages.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: Remote image policy: address classification, localized placeholders, sanitized preview HTML, click loading, forged placeholder rejection.
//
// Restoration: whole - all 9 original test definitions, code and assertions unchanged.
// Target: webview TypeScript transpiled in memory with typescript.transpileModule.

'use strict';

/**
 * A remote image is a request the learner never made: it tells another site
 * who is reading. These tests cover the three pieces that keep it from
 * loading on its own (webview/src/lib/remoteImages.ts):
 *
 *   - where an image address points (local loads, remote waits);
 *   - the sanitizer, which turns a remote <img> in preview HTML into a
 *     placeholder;
 *   - the delegated click that loads one image when the learner asks.
 *
 * linkedom stands in for the browser DOM.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const webviewNodeModules = path.resolve(__dirname, '..', 'webview', 'node_modules');
const typescript = require(path.join(webviewNodeModules, 'typescript'));

// Load the webview's TypeScript sources in this realm, where `document` is
// the linkedom document the sanitizer and the placeholders work on.
for (const extension of ['.ts', '.tsx']) {
  if (!require.extensions[extension]) {
    require.extensions[extension] = (module, filename) => {
      const { outputText } = typescript.transpileModule(fs.readFileSync(filename, 'utf8'), {
        compilerOptions: {
          module: typescript.ModuleKind.CommonJS,
          target: typescript.ScriptTarget.ES2020,
          jsx: typescript.JsxEmit.ReactJSX,
          esModuleInterop: true,
        },
        fileName: filename,
      });
      module._compile(outputText, filename);
    };
  }
}

const linkedom = require('linkedom');

function freshWorld() {
  const { document, Event } = linkedom.parseHTML('<!doctype html><html lang="en"><body></body></html>');
  // linkedom keeps a <template>'s innerHTML at what was first parsed; a
  // browser serialises the current content. The sanitizer reads its result
  // back through it, so give the test document the browser's behaviour.
  const templateProto = Object.getPrototypeOf(document.createElement('template'));
  const chain = [];
  for (let proto = templateProto; proto; proto = Object.getPrototypeOf(proto)) {
    chain.push(proto);
  }
  const parsedInnerHTML = chain
    .map((proto) => Object.getOwnPropertyDescriptor(proto, 'innerHTML'))
    .find((descriptor) => descriptor && typeof descriptor.set === 'function');
  Object.defineProperty(templateProto, 'innerHTML', {
    configurable: true,
    get() {
      return Array.from(this.content.childNodes)
        .map((node) => (node.nodeType === 1 ? node.outerHTML : node.textContent))
        .join('');
    },
    set(value) {
      parsedInnerHTML.set.call(this, value);
    },
  });
  const had = (name) => Object.prototype.hasOwnProperty.call(globalThis, name);
  const previous = { document: had('document') ? globalThis.document : undefined, Element: had('Element') ? globalThis.Element : undefined };
  globalThis.document = document;
  globalThis.Element = linkedom.Element;
  const lib = path.resolve(__dirname, '..', 'webview', 'src', 'lib');
  for (const name of ['remoteImages', 'htmlSanitizer', 'i18n/segments/messageRichContentCopy']) {
    delete require.cache[require.resolve(path.join(lib, `${name}.ts`))];
  }
  const remoteImages = require(path.join(lib, 'remoteImages.ts'));
  const sanitizer = require(path.join(lib, 'htmlSanitizer.ts'));
  const richContent = require(path.resolve(__dirname, '..', 'webview', 'src', 'components', 'coach', 'MessageRichContent.tsx'));
  return {
    document,
    Event,
    remoteImages,
    sanitizer,
    richContent,
    restore() {
      for (const name of ['document', 'Element']) {
        if (previous[name] === undefined) {
          delete globalThis[name];
        } else {
          globalThis[name] = previous[name];
        }
      }
    },
  };
}

test('an image address is local, remote, or not an image address', () => {
  const { remoteImages } = freshWorld();
  const classify = remoteImages.classifyImageUrl;

  // Local: nothing leaves the machine.
  for (const local of [
    'data:image/png;base64,iVBORw0KGgo=',
    'blob:https://file+.vscode-resource.vscode-cdn.net/1234',
    'vscode-resource:/Users/me/library/image.png',
    'vscode-webview-resource:/Users/me/library/image.png',
    'http://127.0.0.1:34891/generated-images/abc.png',
    'http://localhost:8765/resource/img.png',
    // The extension's own files, served through VS Code's webview origin.
    'https://file+.vscode-resource.vscode-cdn.net/c%3A/Users/me/pic.png',
    'https://7a2b3c4d.vscode-cdn.net/some/asset.png',
  ]) {
    assert.equal(classify(local), 'local', local);
  }

  // Remote: another site would learn about the learner.
  for (const remote of [
    'https://example.com/pixel.png',
    'http://example.com/pixel.png',
    // A loopback prefix is not a loopback host.
    'http://127.0.0.1.evil.example/pixel.png',
    'http://localhost.evil.example/pixel.png',
    'https://user@example.com/pixel.png?topic=private',
  ]) {
    assert.equal(classify(remote), 'remote', remote);
  }

  // Not something that is rendered as an image at all.
  for (const none of ['', '   ', null, undefined, 'javascript:alert(1)', 'file:///etc/passwd', 'ftp://x/y.png', 'not a url']) {
    assert.equal(classify(none), null, String(none));
  }
});

test('the placeholder speaks the UI language, and names the host', () => {
  const { remoteImages, document } = freshWorld();
  remoteImages.setRemoteImageLanguageResolver(() => 'zh-CN');
  const chinese = remoteImages.remoteImageLabels();
  assert.equal(chinese.load, '加载远程图片');
  assert.match(chinese.hint, /远程图片在你点击之前不会加载/);

  remoteImages.setRemoteImageLanguageResolver(() => 'de-DE');
  const german = remoteImages.createRemoteImagePlaceholder(document, 'https://cdn.example.org/fig.png?v=1#x', {
    alt: 'Architektur',
    width: '640',
    height: '480px',
  });
  assert.equal(german.getAttribute('type'), 'button');
  assert.equal(german.getAttribute('data-remote-src'), 'https://cdn.example.org/fig.png?v=1#x');
  assert.equal(german.getAttribute('data-remote-alt'), 'Architektur');
  assert.equal(german.getAttribute('data-remote-width'), '640');
  // Sizes are digits only; anything else is dropped rather than copied.
  assert.equal(german.getAttribute('data-remote-height'), null);
  assert.match(german.getAttribute('aria-label'), /^Externes Bild laden · cdn\.example\.org$/);
  const text = german.textContent;
  assert.match(text, /Externes Bild laden/);
  assert.match(text, /cdn\.example\.org/);
  assert.match(text, /Architektur/);
  // Nothing in the placeholder can load anything.
  assert.equal(german.querySelector('img, source, iframe'), null);
  assert.equal(/src="/.test(german.outerHTML.replace(/data-remote-src="/, '')), false);
});

test('sanitized preview HTML holds remote images back and shows local ones', () => {
  const { sanitizer, remoteImages } = freshWorld();
  remoteImages.setRemoteImageLanguageResolver(() => 'en-US');
  const out = sanitizer.sanitizePreviewHtml(
    '<p>Before</p>' +
      '<img src="https://tracker.example/pixel.png" alt="A figure" width="300" onerror="alert(1)">' +
      '<img src="/generated-images/local.png" alt="sidecar">' +
      '<img src="data:image/png;base64,iVBORw0KGgo=" alt="inline">' +
      '<img src="https://file+.vscode-resource.vscode-cdn.net/c%3A/lib/pic.png" alt="library">' +
      '<img src="http://127.0.0.1.evil.example/pixel.png" alt="masquerading">' +
      '<img src="javascript:alert(1)" alt="scripted">' +
      '<p>After</p>',
  );

  // The remote ones became placeholders; their address survives only as data.
  assert.equal((out.match(/class="trainer-remote-image"/g) || []).length, 2);
  assert.match(out, /data-remote-src="https:\/\/tracker\.example\/pixel\.png"/);
  assert.match(out, /data-remote-src="http:\/\/127\.0\.0\.1\.evil\.example\/pixel\.png"/);
  assert.match(out, /data-remote-alt="A figure"/);
  assert.match(out, /data-remote-width="300"/);
  assert.match(out, /Load remote image/);
  assert.match(out, /tracker\.example/);
  assert.doesNotMatch(out, /<img[^>]+src="https?:\/\/(?!file\+\.vscode-resource)/);
  assert.doesNotMatch(out, /onerror|javascript:/);

  // Local images are untouched, and the text around them is still there.
  assert.match(out, /<p>Before<\/p>/);
  assert.match(out, /<p>After<\/p>/);
  assert.match(out, /<img src="\/generated-images\/local\.png" alt="sidecar">/);
  // A data: address was never allowed in preview HTML; that rule is unchanged.
  assert.match(out, /<img alt="inline">/);
  assert.match(out, /src="https:\/\/file\+\.vscode-resource\.vscode-cdn\.net\/c%3A\/lib\/pic\.png"/);
});

test('a click loads exactly the image that was clicked', () => {
  const { document, Event, remoteImages, sanitizer } = freshWorld();
  remoteImages.setRemoteImageLanguageResolver(() => 'en-US');
  const host = document.createElement('div');
  host.innerHTML = sanitizer.sanitizePreviewHtml(
    '<p>Text <a href="https://example.com/page">a link</a></p>' +
      '<img src="https://tracker.example/one.png" alt="One" width="120">' +
      '<img src="https://tracker.example/two.png" alt="Two">',
  );
  document.body.appendChild(host);
  const uninstall = remoteImages.installRemoteImageActivation(document);

  const placeholders = host.querySelectorAll('.trainer-remote-image');
  assert.equal(placeholders.length, 2);

  // Clicking the paragraph or the link loads nothing.
  for (const selector of ['p', 'a']) {
    host.querySelector(selector).dispatchEvent(new Event('click', { bubbles: true, cancelable: true }));
  }
  assert.equal(host.querySelectorAll('img').length, 0);
  assert.equal(host.querySelectorAll('.trainer-remote-image').length, 2);

  // Clicking deep inside one placeholder loads that one image only.
  placeholders[0].querySelector('.trainer-remote-image__label').dispatchEvent(
    new Event('click', { bubbles: true, cancelable: true }),
  );
  const loaded = host.querySelectorAll('img');
  assert.equal(loaded.length, 1);
  assert.equal(loaded[0].getAttribute('src'), 'https://tracker.example/one.png');
  assert.equal(loaded[0].getAttribute('alt'), 'One');
  assert.equal(loaded[0].getAttribute('width'), '120');
  assert.equal(host.querySelectorAll('.trainer-remote-image').length, 1);

  // Installing twice does not make one click load two images.
  const uninstallAgain = remoteImages.installRemoteImageActivation(document);
  host.querySelector('.trainer-remote-image').dispatchEvent(new Event('click', { bubbles: true }));
  assert.equal(host.querySelectorAll('img').length, 2);
  assert.equal(host.querySelectorAll('.trainer-remote-image').length, 0);

  // After uninstalling, a new placeholder is inert again.
  uninstall();
  uninstallAgain();
  host.appendChild(
    remoteImages.createRemoteImagePlaceholder(document, 'https://tracker.example/three.png'),
  );
  host.querySelector('.trainer-remote-image').dispatchEvent(new Event('click', { bubbles: true }));
  assert.equal(host.querySelectorAll('img').length, 2);
  assert.equal(host.querySelectorAll('.trainer-remote-image').length, 1);
});

test('a tampered placeholder never loads', () => {
  const { document, remoteImages } = freshWorld();
  for (const tampered of ['javascript:alert(1)', 'data:text/html,<script>alert(1)</script>', '/local.png', '']) {
    const placeholder = remoteImages.createRemoteImagePlaceholder(document, 'https://tracker.example/x.png');
    placeholder.setAttribute('data-remote-src', tampered);
    document.body.appendChild(placeholder);
    assert.equal(remoteImages.activateRemoteImage(placeholder), null, tampered);
    assert.equal(document.body.querySelector('img'), null, `a placeholder rewritten to ${JSON.stringify(tampered)} must not load`);
  }
});

test('the markdown path keeps the address and lets the image component decide', () => {
  const { richContent, remoteImages } = freshWorld();
  const transform = richContent.markdownUrlTransform;
  const masquerading = 'http://127.0.0.1.evil.example/pixel.png';
  assert.equal(transform(masquerading, 'src'), masquerading);
  // The address is a valid image address, so it reaches the component — and
  // there it is what it is: a remote host, held back until clicked.
  assert.equal(remoteImages.classifyImageUrl(transform(masquerading, 'src')), 'remote');
  assert.equal(remoteImages.classifyImageUrl(transform('https://cdn.example/x.png', 'src')), 'remote');
  assert.equal(remoteImages.classifyImageUrl(transform('http://127.0.0.1:34891/a.png', 'src')), 'local');
  // Data URLs are still gated to raster images for src.
  assert.equal(transform('data:text/html;base64,PHNjcmlwdD4=', 'src'), '');
  assert.equal(transform('data:image/png;base64,iVBORw0KGgo=', 'href'), '');
});


test('an address the browser normalizes is classified by what it becomes', () => {
  const { remoteImages, document } = freshWorld();
  const classify = remoteImages.classifyImageUrl;

  // Every one of these is a real network address once the browser parses it,
  // although none starts with "https://". A prefix test left them live.
  for (const remote of [
    'https:\\attacker.example\\p.png',
    'http:attacker.example/p.png',
    'ht\ntps://attacker.example/p.png',
    ' https://attacker.example/p.png ',
  ]) {
    assert.equal(classify(remote), 'remote', JSON.stringify(remote));
  }

  // A network-path reference has no scheme of its own: it inherits the
  // page's, so it is remote only on an http(s) page.
  assert.equal(classify('//attacker.example/p.png'), null);
  Object.defineProperty(document, 'baseURI', { value: 'https://reader.example/a/', configurable: true });
  assert.equal(classify('//attacker.example/p.png'), 'remote');
  assert.equal(classify('//127.0.0.1:8765/x.png'), 'local');
});

test('a normalized remote address still becomes a placeholder', () => {
  const { sanitizer } = freshWorld();
  const out = sanitizer.sanitizePreviewHtml(
    '<img src="https:\\attacker.example\\p.png" alt="figure">' +
      '<img src="http:attacker.example/q.png" alt="second">',
  );

  assert.equal((out.match(/class="trainer-remote-image"/g) || []).length, 2);
  assert.doesNotMatch(out, /<img[^>]+src=/);
  assert.match(out, /data-remote-src="https:\\attacker\.example\\p\.png"/);
});

test('untrusted markup cannot forge a remote-image placeholder', () => {
  const { sanitizer } = freshWorld();
  const out = sanitizer.sanitizePreviewHtml(
    '<div data-trainer-remote-image="true" data-remote-src="https://attacker.example/x.png" ' +
      'data-remote-alt="click me">open</div>',
  );

  // The delegated click handler trusts these attributes; none may survive.
  assert.doesNotMatch(out, /data-trainer-remote-image|data-remote-/);
  assert.match(out, /open/);
});
