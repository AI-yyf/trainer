'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const { pathToFileURL } = require('node:url');
const ts = require('typescript');

const extensionDir = path.resolve(__dirname, '..');
const scriptPath = path.join(extensionDir, 'scripts/verify-vsix-e2e.mjs');
let emitted;

async function emittedDriver() {
  if (emitted) return emitted;
  const original = ts.createSourceFile(scriptPath, fs.readFileSync(scriptPath, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);
  const writer = original.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'writeDriverExtension');
  assert.ok(writer, 'execute the actual driver generator');
  const helpers = await import(pathToFileURL(path.join(extensionDir, 'scripts/vsix-host-diagnostics.mjs')).href);
  const provider = await import(pathToFileURL(path.join(extensionDir, 'scripts/vsix-e2e-provider-config.mjs')).href);
  const files = new Map();
  const driverDir = '/owned-driver-generator';
  vm.runInNewContext(writer.getText(original) + '\nwriteDriverExtension(providerConfiguration);', {
    ...helpers,
    fs: { writeFileSync: (file, content) => files.set(file, content) },
    path: path.posix,
    driverDir,
    packageJson: JSON.parse(fs.readFileSync(path.join(extensionDir, 'package.json'), 'utf8')),
    buildVsixE2EProviderSavePayloadTemplate: provider.buildVsixE2EProviderSavePayloadTemplate,
    providerConfiguration: provider.resolveVsixE2EProviderConfiguration({ extensionDir }),
  });
  const source = files.get(path.posix.join(driverDir, 'extension.js'));
  assert.equal(typeof source, 'string');
  // Compile the complete emitted driver without activating it or launching Code.
  new vm.Script(source, { filename: 'actual-emitted-vsix-driver.js' });
  const ast = ts.createSourceFile('actual-emitted-vsix-driver.js', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);
  const helper = ast.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'sameLocalPath');
  let predicate;
  const visit = node => {
    if (ts.isCallExpression(node) && node.expression.getText(ast) === 'record' &&
        ts.isStringLiteral(node.arguments[0]) && node.arguments[0].text === 'admit-temporary-trainer-workspace') {
      const options = node.arguments[2];
      assert.ok(ts.isObjectLiteralExpression(options));
      predicate = options.properties.find(property => property.name?.getText(ast) === 'ok').initializer;
    }
    ts.forEachChild(node, visit);
  };
  visit(ast);
  assert.ok(helper && predicate, 'exercise the emitted helper and unchanged admission predicate');
  emitted = { helper: helper.getText(ast), predicate: predicate.getText(ast) };
  return emitted;
}

async function fixture(t, { unc = false } = {}) {
  const parent = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-driver-windows-identity-'));
  const physicalRoot = path.join(parent, 'owned');
  const outside = path.join(parent, 'outside');
  fs.mkdirSync(physicalRoot);
  fs.mkdirSync(outside);
  t.after(() => fs.rmSync(parent, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }));
  const win = path.win32;
  const longBase = unc ? '\\\\owned-server\\share\\trainer-fixture' : 'C:\\Users\\runneradmin\\AppData\\Local\\Temp\\trainer-fixture';
  const shortBase = unc ? '\\\\OWNED-SERVER\\SHARE\\trainer-fixture' : longBase.replace('runneradmin', 'RUNNER~1');
  const normalize = value => win.normalize(value.replace(/^\\\\\?\\UNC\\/i, '\\\\').replace(/^\\\\\?\\/, '')).replace(/^C:\\Users\\RUNNER~1\\/i, 'C:\\Users\\runneradmin\\');
  const physical = value => {
    const relative = win.relative(longBase, normalize(value));
    assert.ok(!win.isAbsolute(relative) && relative !== '..' && !relative.startsWith('..\\'), 'fixture IO escaped');
    return path.join(physicalRoot, ...relative.toLowerCase().split('\\'));
  };
  for (const child of ['trainer-workspace', 'workspace', 'foreign']) fs.mkdirSync(path.join(physicalRoot, child));
  const calls = [];
  const plainCalls = [];
  const plain = value => { plainCalls.push(value); return normalize(value); };
  plain.native = value => {
    calls.push(value);
    const actual = fs.realpathSync.native(physical(value));
    const relative = path.relative(fs.realpathSync.native(physicalRoot), actual);
    if (relative === '..' || relative.startsWith('..' + path.sep)) return 'D:\\outside-fixture\\' + path.basename(actual);
    const logical = win.join(longBase, ...relative.split(path.sep));
    if (unc) return '\\\\?\\UNC\\' + (value.startsWith('\\\\?\\') ? logical.slice(2).toUpperCase() : logical.slice(2));
    return '\\\\?\\' + (/RUNNER~1/i.test(value) ? logical.replace(/^C:/, 'c:').replace('runneradmin', 'RunnerAdmin') : logical);
  };
  const driver = await emittedDriver();
  const helper = vm.runInNewContext(driver.helper + '\nsameLocalPath;', { path: win, fs: { realpathSync: plain }, process: { platform: 'win32' } });
  const root = win.join(shortBase, 'trainer-workspace');
  const project = win.join(shortBase, 'workspace');
  const predicate = vm.runInNewContext('(' + driver.predicate + ')', { sameLocalPath: helper, smokeTrainerWorkspaceDir: root, smokeWorkspaceDir: project });
  const valid = { commandOk: true, status: 'managed', rootPath: win.join(longBase, 'trainer-workspace'),
    projectPath: win.join(longBase, 'workspace'), rootId: 'root-owned', projectId: 'project-owned', contextId: 'context-owned', sessionId: 'session-owned' };
  return { helper, predicate, valid, calls, plainCalls, root, project, longBase, plain, physicalRoot, outside, win };
}

test('actual emitted Windows driver admits the observed short/long-root managed identity', async t => {
  const f = await fixture(t);
  assert.equal(f.predicate(f.valid), true);
  assert.equal(f.calls.length, 4, 'both root and project must resolve both observed and requested paths');
});

test('actual emitted Windows driver admits extended UNC and native case aliases', async t => {
  const f = await fixture(t, { unc: true });
  const data = { ...f.valid, rootPath: '\\\\?\\UNC\\' + f.valid.rootPath.slice(2).toUpperCase(),
    projectPath: '\\\\?\\UNC\\' + f.valid.projectPath.slice(2).toUpperCase() };
  assert.equal(f.predicate(data), true);
  assert.equal(f.calls.length, 4);
});

test('actual emitted Windows driver rejects a different physical root or project', async t => {
  const f = await fixture(t);
  assert.equal(f.predicate({ ...f.valid, rootPath: f.win.join(f.longBase, 'foreign') }), false);
  assert.equal(f.predicate({ ...f.valid, projectPath: f.win.join(f.longBase, 'foreign') }), false);
});

test('actual emitted Windows driver rejects an owned link that resolves outside the expected root', async t => {
  const f = await fixture(t);
  fs.symlinkSync(f.outside, path.join(f.physicalRoot, 'outside-link'), process.platform === 'win32' ? 'junction' : 'dir');
  assert.equal(f.predicate({ ...f.valid, rootPath: f.win.join(f.longBase, 'outside-link') }), false);
  assert.ok(f.calls.length > 0, 'rejection must include actual native resolution of the link target');
});

test('actual emitted Windows driver rejects native denied or missing even for equal lexical paths', async t => {
  const f = await fixture(t);
  const data = { ...f.valid, rootPath: f.root, projectPath: f.project };
  f.plain.native = () => { throw Object.assign(new Error('owned fixture denial'), { code: 'EACCES' }); };
  assert.equal(f.predicate(data), false);
  f.plain.native = undefined;
  assert.equal(f.predicate(data), false);
  assert.equal(f.plainCalls.length, 0, 'native failures must never fall back to textual realpath');
});

test('actual emitted admission keeps command, managed status, root/project paths and all identity IDs mandatory', async t => {
  const f = await fixture(t);
  for (const changes of [{ commandOk: false }, { status: 'project-found' }, { rootPath: null }, { projectPath: null },
    { rootId: null }, { projectId: null }, { contextId: null }]) {
    assert.equal(f.predicate({ ...f.valid, ...changes }), false, JSON.stringify(changes));
  }
});

test('actual emitted Windows identity preserves a drive root before native lookup', async () => {
  const driver = await emittedDriver();
  const calls = [];
  const native = value => {
    calls.push(value);
    // C: is drive-relative and may resolve to its current directory, unlike C:\.
    return value === 'C:' ? 'C:\\owned-cwd' : value;
  };
  const helper = vm.runInNewContext(driver.helper + '\nsameLocalPath;', {
    path: path.win32, fs: { realpathSync: { native } }, process: { platform: 'win32' },
  });
  assert.equal(helper('C:\\', 'C:\\owned-cwd'), false);
  assert.deepEqual(calls, ['C:\\', 'C:\\owned-cwd']);
});

test('actual emitted POSIX driver preserves lexical equality, real alias equality and foreign/denied rejection', async () => {
  const driver = await emittedDriver();
  let deny = false;
  const native = value => {
    if (deny) throw new Error('owned fixture denial');
    return value === '/tmp/owned' ? '/private/tmp/owned' : value;
  };
  const helper = vm.runInNewContext(driver.helper + '\nsameLocalPath;', { path: path.posix, fs: { realpathSync: { native } }, process: { platform: 'darwin' } });
  assert.equal(helper('/tmp/owned', '/tmp/owned/'), true);
  assert.equal(helper('/tmp/owned', '/private/tmp/owned'), true);
  assert.equal(helper('/tmp/owned', '/foreign'), false);
  deny = true;
  assert.equal(helper('/tmp/owned', '/private/tmp/owned'), false);
});
