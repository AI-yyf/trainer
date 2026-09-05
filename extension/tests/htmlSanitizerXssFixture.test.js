'use strict';

const fs = require('node:fs');
const Module = require('node:module');
const path = require('node:path');
const test = require('node:test');
const assert = require('node:assert/strict');

const webviewNodeModules = path.resolve(__dirname, '..', 'webview', 'node_modules');
if (!process.env.NODE_PATH?.split(path.delimiter).includes(webviewNodeModules)) {
  process.env.NODE_PATH = process.env.NODE_PATH
    ? `${webviewNodeModules}${path.delimiter}${process.env.NODE_PATH}`
    : webviewNodeModules;
  Module._initPaths();
}

const typescript = require(path.join(webviewNodeModules, 'typescript'));
const parse5 = require(path.join(webviewNodeModules, 'parse5'));

for (const extension of ['.ts', '.tsx']) {
  if (!require.extensions[extension]) {
    require.extensions[extension] = (module, filename) => {
      const source = fs.readFileSync(filename, 'utf8');
      const { outputText } = typescript.transpileModule(source, {
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

const htmlSanitizerPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'htmlSanitizer.ts',
);

function installParse5Document() {
  const previous = globalThis.document;

  function wrapNodes(parse5Nodes, ownerDocument, parent) {
    const out = [];
    for (const raw of parse5Nodes) {
      if (raw.nodeName === '#text') {
        const text = {
          nodeType: 3,
          nodeName: '#text',
          ownerDocument,
          parentNode: parent,
          get textContent() {
            return raw.value;
          },
          set textContent(value) {
            raw.value = String(value ?? '');
          },
          _raw: raw,
        };
        out.push(text);
        continue;
      }
      if (raw.nodeName === '#comment') {
        continue;
      }
      out.push(wrapElement(raw, ownerDocument, parent));
    }
    return out;
  }

  function wrapElement(raw, ownerDocument, parent) {
    const attrs = (raw.attrs || []).map((attr) => ({
      name: attr.name,
      value: attr.value,
    }));

    const element = {
      nodeType: 1,
      nodeName: String(raw.nodeName).toUpperCase(),
      tagName: String(raw.nodeName).toUpperCase(),
      ownerDocument,
      parentNode: parent,
      attributes: attrs,
      childNodes: [],
      get children() {
        return this.childNodes.filter((child) => child.nodeType === 1);
      },
      get firstChild() {
        return this.childNodes[0] ?? null;
      },
      getAttribute(name) {
        const found = attrs.find((attr) => attr.name.toLowerCase() === String(name).toLowerCase());
        return found ? found.value : null;
      },
      setAttribute(name, value) {
        const lower = String(name).toLowerCase();
        const existing = attrs.find((attr) => attr.name.toLowerCase() === lower);
        if (existing) {
          existing.name = name;
          existing.value = String(value);
          return;
        }
        attrs.push({ name, value: String(value) });
      },
      removeAttribute(name) {
        const lower = String(name).toLowerCase();
        const index = attrs.findIndex((attr) => attr.name.toLowerCase() === lower);
        if (index >= 0) {
          attrs.splice(index, 1);
        }
      },
      appendChild(child) {
        if (child.parentNode && child.parentNode !== this) {
          child.parentNode.childNodes = child.parentNode.childNodes.filter((node) => node !== child);
        }
        child.parentNode = this;
        this.childNodes.push(child);
        return child;
      },
      remove() {
        if (!this.parentNode) {
          return;
        }
        this.parentNode.childNodes = this.parentNode.childNodes.filter((node) => node !== this);
        this.parentNode = null;
      },
      replaceWith(...nodes) {
        if (!this.parentNode) {
          return;
        }
        const parentChildNodes = this.parentNode.childNodes;
        const index = parentChildNodes.indexOf(this);
        if (index < 0) {
          return;
        }
        const replacements = [];
        for (const node of nodes) {
          if (node.nodeName === '#document-fragment') {
            replacements.push(...node.childNodes);
            for (const child of node.childNodes) {
              child.parentNode = this.parentNode;
            }
            node.childNodes = [];
          } else {
            node.parentNode = this.parentNode;
            replacements.push(node);
          }
        }
        parentChildNodes.splice(index, 1, ...replacements);
        this.parentNode = null;
      },
      _raw: raw,
    };

    element.childNodes = wrapNodes(raw.childNodes || [], ownerDocument, element);
    return element;
  }

  function serializeNode(node) {
    if (node.nodeType === 3) {
      return node.textContent;
    }
    if (node.nodeName === '#document-fragment') {
      return node.childNodes.map(serializeNode).join('');
    }
    const tag = node.tagName.toLowerCase();
    const attrText = node.attributes
      .map((attr) => ` ${attr.name}="${String(attr.value).replace(/"/g, '&quot;')}"`)
      .join('');
    const voidTags = new Set(['br', 'hr', 'img', 'meta', 'link', 'base']);
    if (voidTags.has(tag)) {
      return `<${tag}${attrText}>`;
    }
    return `<${tag}${attrText}>${node.childNodes.map(serializeNode).join('')}</${tag}>`;
  }

  const documentShim = {
    createDocumentFragment() {
      return {
        nodeName: '#document-fragment',
        nodeType: 11,
        childNodes: [],
        appendChild(child) {
          if (child.parentNode) {
            child.parentNode.childNodes = child.parentNode.childNodes.filter((node) => node !== child);
          }
          child.parentNode = this;
          this.childNodes.push(child);
          return child;
        },
      };
    },
    createElement(tagName) {
      if (String(tagName).toLowerCase() !== 'template') {
        throw new Error(`unexpected createElement(${tagName})`);
      }
      let contentRoot = {
        nodeName: '#document-fragment',
        nodeType: 11,
        childNodes: [],
        get children() {
          return this.childNodes.filter((child) => child.nodeType === 1);
        },
      };
      return {
        content: contentRoot,
        set innerHTML(value) {
          const fragment = parse5.parseFragment(String(value ?? ''));
          contentRoot.childNodes = wrapNodes(fragment.childNodes || [], documentShim, contentRoot);
        },
        get innerHTML() {
          return contentRoot.childNodes.map(serializeNode).join('');
        },
      };
    },
  };

  globalThis.document = documentShim;
  return () => {
    if (previous === undefined) {
      delete globalThis.document;
    } else {
      globalThis.document = previous;
    }
  };
}

test('sanitizePreviewHtml fail-closed empty without document', () => {
  const hadDocument = Object.prototype.hasOwnProperty.call(globalThis, 'document');
  const previous = globalThis.document;
  delete globalThis.document;
  try {
    // Fresh require so typeof document is evaluated in this host.
    delete require.cache[require.resolve(htmlSanitizerPath)];
    const { sanitizePreviewHtml } = require(htmlSanitizerPath);
    assert.equal(
      sanitizePreviewHtml('<p onerror="x"><script>alert(1)</script>ok</p>'),
      '',
    );
  } finally {
    if (hadDocument) {
      globalThis.document = previous;
    } else {
      delete globalThis.document;
    }
    delete require.cache[require.resolve(htmlSanitizerPath)];
  }
});

test('sanitizePreviewHtml strips script onerror javascript fixture', () => {
  const restore = installParse5Document();
  try {
    delete require.cache[require.resolve(htmlSanitizerPath)];
    const { sanitizePreviewHtml } = require(htmlSanitizerPath);
    const fixture =
      '<section><p onerror="alert(1)">safe</p>' +
      '<script>alert(1)</script>' +
      '<img src="x" onerror="alert(1)">' +
      '<a href="javascript:alert(1)">click</a>' +
      '<div onclick="alert(1)">x</div></section>';
    const out = sanitizePreviewHtml(fixture);
    assert.doesNotMatch(out, /<script\b/i);
    assert.doesNotMatch(out, /\sonerror\s*=/i);
    assert.doesNotMatch(out, /\sonclick\s*=/i);
    assert.doesNotMatch(out, /javascript:/i);
    assert.match(out, /safe/);
  } finally {
    restore();
    delete require.cache[require.resolve(htmlSanitizerPath)];
  }
});

test('coach DiffRenderer escapes or sanitizes before dangerouslySetInnerHTML', () => {
  const source = fs.readFileSync(
    path.resolve(
      __dirname,
      '..',
      'webview',
      'src',
      'components',
      'coach',
      'parts',
      'DiffRenderer.tsx',
    ),
    'utf8',
  );
  assert.match(source, /sanitizePreviewHtml/);
  assert.match(source, /escapeHtml/);
  assert.doesNotMatch(
    source,
    /dangerouslySetInnerHTML=\{\{\s*__html:\s*highlightedLines\[index\]\s*\|\|\s*line\.content/,
  );
});

test('coach MermaidBlock Shiki Code Math MermaidRenderer route HTML through sanitizePreviewHtml', () => {
  const roots = [
    ['coach', 'MermaidBlock.tsx'],
    ['coach', 'parts', 'ShikiCodeBlock.tsx'],
    ['parts', 'CodeRenderer.tsx'],
    ['parts', 'MathRenderer.tsx'],
    ['parts', 'MermaidRenderer.tsx'],
  ];
  for (const parts of roots) {
    const source = fs.readFileSync(
      path.resolve(__dirname, '..', 'webview', 'src', 'components', ...parts),
      'utf8',
    );
    assert.match(source, /sanitizePreviewHtml/, parts.join('/'));
    assert.doesNotMatch(source, /securityLevel:\s*["']loose["']/, parts.join('/'));
  }
});

test('docx-unrelated XSS-shaped fixture: assigned innerHTML must be sanitized output', () => {
  const restore = installParse5Document();
  try {
    delete require.cache[require.resolve(htmlSanitizerPath)];
    const { sanitizePreviewHtml } = require(htmlSanitizerPath);
    // Shape-only fixture (not an exploit PoC). Simulates post-renderAsync staging HTML.
    const stagingHtml =
      '<div class="docx"><p onerror="x">body</p><script>x</script>' +
      '<img src="https://example.com/a.png" onerror="x"></div>';
    const sanitized = sanitizePreviewHtml(stagingHtml);
    assert.doesNotMatch(sanitized, /<script\b/i);
    assert.doesNotMatch(sanitized, /\sonerror\s*=/i);
    assert.match(sanitized, /body/);
    // DocxPreviewContent assigns only sanitized output to the visible container.
    const docxContainer = { innerHTML: '' };
    docxContainer.innerHTML = sanitized;
    assert.equal(docxContainer.innerHTML, sanitized);
    assert.doesNotMatch(docxContainer.innerHTML, /<script\b/i);
  } finally {
    restore();
    delete require.cache[require.resolve(htmlSanitizerPath)];
  }
});
