'use strict';

/**
 * Mermaid output is model-controlled markup that ends up on the page. The
 * renderer rebuilds it from an allowlist before it reaches the DOM
 * (webview/src/lib/mermaidDiagram.ts). These tests feed it diagrams that try
 * the things a hostile chart would try, and check what survives.
 *
 * linkedom stands in for the browser DOM; its lack of an XML serializer is
 * covered by the small serializer below, behind the module's DOM adapter.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { DOMParser, parseHTML } = require('linkedom');

const { loadTsModule, WEBVIEW_ROOT } = require('./helpers/loadTsModule');

const { document } = parseHTML('<!doctype html><html><body></body></html>');

function escapeText(value) {
  return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function serializeChildren(node) {
  let out = '';
  for (const child of node.childNodes) {
    if (child.nodeType === 3) {
      out += escapeText(child.nodeValue);
    } else if (child.nodeType === 1) {
      out += serializeElement(child);
    }
  }
  return out;
}

function serializeElement(element) {
  const attributes = Array.from(element.attributes)
    .map((attribute) => ` ${attribute.name.toLowerCase()}="${escapeText(attribute.value).replace(/"/g, '&quot;')}"`)
    .join('');
  // Names are folded to lower case: linkedom reports element names in upper
  // case and attribute case is not what these tests are about.
  const name = element.localName.toLowerCase();
  return `<${name}${attributes}>${serializeChildren(element)}</${name}>`;
}

const mermaid = loadTsModule(path.join(WEBVIEW_ROOT, 'src', 'lib', 'mermaidDiagram.ts'));

// The adapter is the seam between the pure scrubbing logic and a DOM.
// Mermaid writes for the HTML parser (void elements in labels are not
// self-closed), so the scrubber reads it that way too.
mermaid.mermaidDomAdapter.parseSvgRoot = (markup) =>
  new DOMParser().parseFromString(markup, 'text/html').querySelector('svg');
mermaid.mermaidDomAdapter.serialize = (element) => serializeElement(element);

function scrub(markup) {
  return mermaid.scrubMermaidSvg(markup, document);
}

/** Lower-cased output for structure assertions. */
function scrubLower(markup) {
  return scrub(markup).toLowerCase();
}

const SVG_OPEN = '<svg xmlns="http://www.w3.org/2000/svg" id="trainer-mermaid-1" width="100%" style="max-width: 100%;" viewBox="0 0 200 100">';
const COMMENT_OPEN = '<!';

/** The opening tag of the first element named `tag` in lower-cased output. */
function openingTag(lower, tag) {
  const match = new RegExp(`<${tag}\\b[^>]*>`).exec(lower);
  assert.ok(match, `no <${tag}> in ${lower}`);
  return match ? match[0] : '';
}

/** Attribute order is the DOM's business; these tests only care about presence. */
function hasAttributes(tagSource, expected) {
  for (const [name, value] of Object.entries(expected)) {
    assert.ok(
      tagSource.includes(` ${name}="${value}"`),
      `${name}="${value}" is not on ${tagSource}`,
    );
  }
}

test('a real diagram keeps its theme, shapes, markers and labels', () => {
  const scrubbed = scrubLower(
    `${SVG_OPEN}<style>#trainer-mermaid-1 .edgePath .path { stroke: #d0bccc; stroke-width: 2px; } ` +
      '#trainer-mermaid-1 .node rect { fill: #1f1f1f; stroke: #9a9a9a; } ' +
      '#trainer-mermaid-1 .label { font-family: sans-serif; font-size: 12px; color: #eee; }</style>' +
      '<defs><marker id="arrow" markerWidth="12" markerHeight="12" refX="6" refY="7" orient="auto">' +
      '<path d="M 0 0 L 12 7 L 0 14" fill="none" stroke="#d0bccc" stroke-width="1"/></marker>' +
      '<linearGradient id="fade" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#111"/></linearGradient></defs>' +
      '<g class="edgePath"><path class="path" d="M10 10 C 20 20" marker-end="url(#arrow)"/></g>' +
      '<g class="node"><rect x="20" y="30" width="80" height="40" fill="url(#fade)"/>' +
      '<foreignObject width="80" height="40"><div xmlns="http://www.w3.org/1999/xhtml" style="display: table-cell; white-space: nowrap; text-align: center;">' +
      '<span class="nodeLabel"><p>Decide &amp; act</p></span></div></foreignObject></g>' +
      '<text x="10" y="90" text-anchor="start">Caption</text>' +
      // Assembled so the legacy HTML-like-comment rule cannot read the
      // opener at the start of a source line.
      COMMENT_OPEN + '-- a comment --><![CDATA[ ignored ]]></svg>',
  );

  assert.ok(scrubbed, 'a real diagram renders');
  // The root keeps its id: mermaid's generated rules match through it.
  hasAttributes(openingTag(scrubbed, 'svg'), {
    id: 'trainer-mermaid-1',
    viewbox: '0 0 200 100',
    style: 'max-width: 100%',
    xmlns: 'http://www.w3.org/2000/svg',
    'xmlns:xlink': 'http://www.w3.org/1999/xlink',
  });
  // The theme survives in full: none of it is resource-loading.
  assert.match(
    scrubbed,
    /<style>#trainer-mermaid-1 \.edgepath \.path \{ stroke: #d0bccc; stroke-width: 2px; \}\n#trainer-mermaid-1 \.node rect \{ fill: #1f1f1f; stroke: #9a9a9a; \}\n#trainer-mermaid-1 \.label \{ font-family: sans-serif; font-size: 12px; color: #eee; \}<\/style>/,
  );
  // Markers, gradients and the local references to them.
  hasAttributes(openingTag(scrubbed, 'marker'), {
    id: 'arrow',
    markerwidth: '12',
    markerheight: '12',
    refx: '6',
    refy: '7',
    orient: 'auto',
  });
  hasAttributes(openingTag(scrubbed, 'stop'), { offset: '0%', 'stop-color': '#111' });
  hasAttributes(openingTag(scrubbed, 'lineargradient'), {
    id: 'fade',
    x1: '0',
    y1: '0',
    x2: '1',
    y2: '1',
  });
  assert.ok(
    /<path [^>]*marker-end="url\(#arrow\)"[^>]*>/.test(scrubbed),
    'the edge keeps its local marker reference',
  );
  hasAttributes(openingTag(scrubbed, 'rect'), { fill: 'url(#fade)', x: '20', width: '80' });
  // HTML labels stay labels.
  hasAttributes(openingTag(scrubbed, 'foreignobject'), { width: '80', height: '40' });
  assert.match(
    scrubbed,
    /<div style="display: table-cell; white-space: nowrap; text-align: center"><span class="nodelabel"><p>decide &amp; act<\/p><\/span><\/div>/,
  );
  // Text is text.
  assert.match(scrubbed, /<text [^>]*>caption<\/text>/);
  // Comments and CDATA are not diagram.
  assert.doesNotMatch(scrubbed, /a comment|ignored/);
});

test('script, event handlers, links, embedded images and animation are removed', () => {
  const scrubbed = scrubLower(
    `${SVG_OPEN}<script>window.__pwned = true;</script>` +
      '<g onclick="alert(1)" onmouseover="alert(2)" fill="#fff"><rect width="10" height="10" ONLOAD="alert(3)"/></g>' +
      '<a href="https://evil.example/" target="_blank"><text>click me</text></a>' +
      '<a href="javascript:alert(1)"><circle r="4"/></a>' +
      '<image href="https://evil.example/track.png" width="1" height="1"/>' +
      '<image xlink:href="https://evil.example/track.png"/>' +
      '<use href="https://evil.example/remote.svg#x"/>' +
      '<use href="#local-symbol"/>' +
      '<animate attributeName="href" to="javascript:alert(1)"/><set attributeName="onmouseover" to="alert(1)"/>' +
      // An iframe is a raw-text element to the HTML parser: it has to be closed,
      // or everything after it would be read as its (inert) text.
      '<iframe src="https://evil.example/"></iframe>' +
      '<foreignObject><div><script>alert(1)</script><iframe src="https://evil.example/"></iframe>' +
      '<img src="https://evil.example/pixel.png"/><a href="https://evil.example/">link</a>' +
      '<p onclick="alert(1)" style="color: red">kept label</p></div></foreignObject></svg>',
  );

  assert.ok(scrubbed);
  for (const forbidden of [
    'script',
    'onclick',
    'onmouseover',
    'onload',
    'javascript:',
    'evil.example',
    '<a ',
    '<image',
    '<iframe',
    '<img',
    '<animate',
    '<set',
    'target=',
  ]) {
    assert.equal(scrubbed.includes(forbidden), false, `${forbidden} must not survive: ${scrubbed}`);
  }
  // The shapes around the removed markup are still a diagram.
  hasAttributes(openingTag(scrubbed, 'rect'), { width: '10', height: '10' });
  assert.match(scrubbed, /<text>click me<\/text>/);
  assert.match(scrubbed, /<circle r="4"><\/circle>/);
  assert.match(scrubbed, /<use href="#local-symbol"><\/use>/, 'a reference inside the SVG is kept');
  assert.match(scrubbed, /style="color: red"/);
  assert.match(scrubbed, /kept label/);
  // An anchor is unwrapped, so its wording survives as plain text — never as a link.
  assert.match(scrubbed, />link<p style="color: red">/);
});

test('styles can style the diagram but cannot load a resource or leave its box', () => {
  const scrubbed = scrubLower(
    `${SVG_OPEN}<style>@import url("https://evil.example/a.css"); ` +
      '@font-face { font-family: x; src: url("https://evil.example/f.woff"); } ' +
      '#trainer-mermaid-1 .a { fill: red; background: url(https://evil.example/b.png); } ' +
      '#trainer-mermaid-1 .b { stroke: blue; behavior: url(#default#time2); } ' +
      '.c { width: expression(alert(1)); color: green; position: fixed; } ' +
      '#trainer-mermaid-1 .d { stroke-dasharray: 3 3; }</style>' +
      '<rect style="color: red; background: url(https://evil.example/x.png); position: fixed; opacity: 0.5" width="1" height="1"/>' +
      '<rect style="background\\3a url(https://evil.example/y.png)" width="1" height="1"/></svg>',
  );

  assert.ok(scrubbed);
  for (const forbidden of ['evil.example', '@import', '@font-face', 'expression(', 'behavior', 'position: fixed', '\\']) {
    assert.equal(scrubbed.includes(forbidden), false, `${forbidden} must not survive: ${scrubbed}`);
  }
  // Safe theme declarations are kept.
  assert.match(scrubbed, /\.a \{ fill: red; \}/);
  assert.match(scrubbed, /\.b \{ stroke: blue; \}/);
  assert.match(scrubbed, /color: green;/);
  assert.match(scrubbed, /\.d \{ stroke-dasharray: 3 3; \}/);
  const rects = scrubbed.match(/<rect [^>]*>/g) || [];
  assert.equal(rects.length, 2);
  assert.ok(rects.some((tag) => tag.includes('style="color: red; opacity: 0.5"')), `first rect keeps its safe declarations: ${rects}`);
  assert.ok(rects.some((tag) => !tag.includes('style=')), `a style that only tries to load is dropped whole: ${rects}`);
});

test('an escaped colon cannot smuggle a resource into a declaration', () => {
  // In CSS, `\\3a` is a colon. Read as "property: value" on the first literal
  // colon, the resource would land on the property side and slip past.
  const smuggled = 'background' + String.fromCharCode(92) + '3a url(https://evil.example/y.png)';
  assert.equal(mermaid.filterInlineStyle(`color: red; ${smuggled}`), 'color: red');
  assert.equal(mermaid.filterInlineStyle(`fill: red; color\\3a url(https://evil.example/y.png)`), 'fill: red');
  const sheet = mermaid.filterDiagramStylesheet(
    '.x { fill: red; ' + smuggled + '; } .y { stroke: blue; }',
  );
  assert.equal(sheet.includes('evil.example'), false, sheet);
  assert.match(sheet, /^\.x \{ fill: red; \}\n\.y \{ stroke: blue; \}$/);
});

test('a label with HTML void elements still renders, without the image', () => {
  // Mermaid's own output is not well-formed XML: '<br>' and '<img>' are void
  // elements. Reading it as XML refuses every chart with a line break in a
  // label, so the scrubber reads it the way Mermaid writes it.
  const scrubbed = scrubLower(
    SVG_OPEN +
      '<g class="node"><foreignObject width="60" height="30"><div xmlns="http://www.w3.org/1999/xhtml">' +
      '<span class="nodeLabel"><p>first<br>second<img src="https://evil.example/x.png">third</p></span></div></foreignObject></g></svg>',
  );
  assert.ok(scrubbed, 'the diagram is not refused');
  // Void elements need no closing tag in HTML; the test serializer prints one.
  assert.match(scrubbed, /first<br>(?:<\/br>)?second/);
  assert.match(scrubbed, /third/);
  assert.equal(scrubbed.includes('<img'), false);
  assert.equal(scrubbed.includes('evil.example'), false);
});

test('at-rules are removed with their whole block, keyframes included', () => {
  const sheet = mermaid.filterDiagramStylesheet([
    '#g .edge-animation-slow { stroke-dasharray: 9,5!important; animation: dash 50s linear infinite; }',
    '@keyframes dash { to { stroke-dashoffset: 0; } }',
    '@keyframes edge-animation-frame { from { stroke-dashoffset: 0; } }',
    '@font-face { font-family: x; src: url(https://evil.example/f.woff); }',
    '@import url("https://evil.example/a.css");',
    '#g .node rect { fill: #1f1f1f; }',
    '@media (prefers-reduced-motion) { #g .a { stroke: red; } }',
    '#g p { margin: 0; }',
  ].join('\n'));
  assert.equal(sheet, [
    '#g .edge-animation-slow { stroke-dasharray: 9,5!important; animation: dash 50s linear infinite; }',
    '#g .node rect { fill: #1f1f1f; }',
    '#g p { margin: 0; }',
  ].join('\n'));
  for (const leftover of ['@', 'keyframes', 'evil.example', 'from ', 'to ', 'stroke-dashoffset']) {
    assert.equal(sheet.includes(leftover), false, `${leftover} must be gone: ${sheet}`);
  }
});

test('markup that is not an SVG document, or an SVG with nothing allowed, yields nothing', () => {
  assert.equal(scrub(''), '');
  assert.equal(scrub('   '), '');
  assert.equal(scrub('<html><body><script>alert(1)</script></body></html>'), '');
  assert.equal(scrub('not xml at all <'), '');
  assert.equal(scrub(`${SVG_OPEN}<script>alert(1)</script><image href="https://evil.example/x.png"/></svg>`), '');
});

test('the shadow stylesheet is part of the module, not the page stylesheet', () => {
  assert.match(mermaid.MERMAID_SHADOW_CSS, /:host \{ display: block;/);
  assert.match(mermaid.MERMAID_SHADOW_CSS, /svg \{ display: block; width: max-content; height: auto; min-width: 100%; \}/);
  const canvas = require('node:fs').readFileSync(
    path.join(WEBVIEW_ROOT, 'src', 'styles', 'sections', 'mermaid-block.css'),
    'utf8',
  );
  assert.doesNotMatch(canvas, /\.message-mermaid__canvas svg/, 'the SVG is no longer in the light DOM');
});

test('a diagram the size of a book is refused before it is rendered', () => {
  assert.equal(mermaid.isMermaidSourceTooLarge('graph TD; A-->B'), false);
  assert.equal(mermaid.isMermaidSourceTooLarge('A\n'.repeat(mermaid.MERMAID_MAX_SOURCE_LINES)), false);
  assert.equal(mermaid.isMermaidSourceTooLarge('A\n'.repeat(mermaid.MERMAID_MAX_SOURCE_LINES + 1)), true);
  assert.equal(mermaid.isMermaidSourceTooLarge('x'.repeat(mermaid.MERMAID_MAX_SOURCE_CHARS)), false);
  assert.equal(mermaid.isMermaidSourceTooLarge('x'.repeat(mermaid.MERMAID_MAX_SOURCE_CHARS + 1)), true);
});

test('rendering refuses an oversized chart without calling Mermaid', async () => {
  await assert.rejects(
    () => mermaid.renderMermaidDiagram('x'.repeat(mermaid.MERMAID_MAX_SOURCE_CHARS + 1), {
      elementId: 'big',
      theme: 'dark',
      ownerDocument: document,
    }),
    /too large/,
  );
});

test('inline style and stylesheet filtering are available on their own', () => {
  assert.equal(mermaid.filterInlineStyle('color: red; background: url(x.png)'), 'color: red');
  assert.equal(mermaid.filterInlineStyle('bad'), '');
  assert.equal(
    mermaid.filterDiagramStylesheet('.a { fill: red; } .b { background: url(https://x/y); }'),
    // A rule left without declarations is dropped whole.
    '.a { fill: red; }',
  );
});
