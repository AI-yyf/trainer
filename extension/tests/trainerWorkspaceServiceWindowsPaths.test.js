'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const fsSync = require('node:fs');
const os = require('node:os');
const hostPath = require('node:path');
const win = hostPath.win32;
const vm = require('node:vm');

const modulePath = hostPath.resolve(__dirname, '../dist/extension/src/core/trainerWorkspaceService.js');

function globalState(initial = {}) {
  const values = new Map(Object.entries(initial));
  return { get: key => values.get(key), update: async (key, value) => {
    if (value === undefined) values.delete(key); else values.set(key, value);
  } };
}

async function fixture(t, { unc = false } = {}) {
  const physicalRoot = await fs.mkdtemp(hostPath.join(os.tmpdir(), 'trainer-win-paths-'));
  t.after(() => fs.rm(physicalRoot, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }));
  const base = unc ? '\\\\owned-server\\share\\trainer-fixture' : 'C:\\Users\\runneradmin\\AppData\\Local\\Temp\\trainer-fixture';
  const unextended = value => value.replace(/^\\\\\?\\UNC\\/i, '\\\\').replace(/^\\\\\?\\/, '');
  const expanded = value => win.normalize(unextended(value)).replace(/^C:\\Users\\RUNNER~1\\/i, 'C:\\Users\\runneradmin\\');
  const physical = value => {
    const relative = win.relative(base, expanded(value));
    assert.ok(relative === '' || (!win.isAbsolute(relative) && relative !== '..' && !relative.startsWith('..\\')), 'IO escaped the owned Windows fixture');
    return hostPath.join(physicalRoot, ...relative.toLowerCase().split('\\'));
  };
  const io = { ...fs };
  for (const method of ['mkdir', 'readFile', 'writeFile', 'lstat', 'stat', 'readdir', 'rm']) {
    io[method] = (value, ...args) => fs[method](physical(value), ...args);
  }
  io.rename = (source, target, ...args) => fs.rename(physical(source), physical(target), ...args);
  const nativeCalls = [];
  const plainCalls = [];
  let rejectNative = false;
  const native = value => {
    nativeCalls.push(value);
    if (rejectNative) throw Object.assign(new Error('fixture denied'), { code: 'EACCES' });
    const canonical = fsSync.realpathSync.native(physical(value));
    const relative = hostPath.relative(fsSync.realpathSync.native(physicalRoot), canonical);
    assert.ok(relative === '' || (relative !== '..' && !relative.startsWith('..' + hostPath.sep)), 'native path escaped fixture');
    const logical = win.join(base, ...relative.split(hostPath.sep));
    // A WinAPI canonical spelling can differ in drive/case and extended prefix.
    if (unc) return '\\\\?\\UNC\\' + (value.startsWith('\\\\?\\') ? logical.slice(2).toUpperCase() : logical.slice(2));
    const spelling = /RUNNER~1/i.test(value) ? logical.replace(/^C:/, 'c:').replace('runneradmin', 'RunnerAdmin') : logical;
    return '\\\\?\\' + spelling;
  };
  const plain = value => {
    plainCalls.push(value);
    fsSync.lstatSync(physical(value));
    return win.normalize(value); // Node's JS path walker preserves ordinary non-link 8.3 segments.
  };
  plain.native = native;
  const sync = { ...fsSync, realpathSync: plain };
  const vscode = { workspace: { workspaceFolders: [] }, env: {}, FileType: { Directory: 2, File: 1 },
    Uri: { parse: value => ({ scheme: 'file', fsPath: value, path: value }) } };
  const context = vm.createContext({ process: { platform: 'win32', pid: process.pid }, console, Buffer, URL, setTimeout });
  const load = filename => {
    const exports = {};
    const scopedRequire = request => {
      if (request === 'node:path') return win;
      if (request === 'node:fs/promises') return io;
      if (request === 'node:fs') return sync;
      if (request === 'vscode') return vscode;
      if (request === './workspaceRoots') return load(hostPath.join(hostPath.dirname(filename), 'workspaceRoots.js'));
      return require(request);
    };
    vm.compileFunction(fsSync.readFileSync(filename, 'utf8'), ['exports', 'require', 'module'], { parsingContext: context })
      (exports, scopedRequire, { exports });
    return exports;
  };
  return { ...load(modulePath), base, io, physical, nativeCalls, plainCalls,
    denyNative: () => { rejectNative = true; }, disableNative: () => { plain.native = undefined; } };
}

test('Windows public manifest reload accepts an 8.3 root and native drive/case alias without changing identity', async t => {
  const f = await fixture(t);
  const shortRoot = win.join(f.base.replace('runneradmin', 'RUNNER~1'), 'workspace');
  const canonicalRoot = win.join(f.base, 'workspace');
  const state = globalState();
  const service = new f.TrainerWorkspaceService({ globalState: state });
  await service.selectRoot(shortRoot);
  await state.update(f.TRAINER_WORKSPACE_ROOT_STORAGE_KEY, canonicalRoot);
  const restored = new f.TrainerWorkspaceService({ globalState: state });
  const manifest = await restored.readWorkspaceManifest();
  assert.equal(manifest.rootPath, shortRoot);
  assert.equal(manifest.manifestRevision, 1);
  assert.ok(f.nativeCalls.includes(shortRoot) && f.nativeCalls.includes(canonicalRoot), 'both physical paths must use native resolution');
});

test('Windows public managed admission accepts canonical backend paths for the same short-name root and project', async t => {
  const f = await fixture(t);
  const shortRoot = win.join(f.base.replace('runneradmin', 'RUNNER~1'), 'workspace');
  const project = win.join(f.base.replace('runneradmin', 'RUNNER~1'), 'project');
  await f.io.mkdir(project, { recursive: true });
  const service = new f.TrainerWorkspaceService({ globalState: globalState() });
  await service.selectRoot(shortRoot);
  const adopted = await service.setProjectAdoption(project, 'managed', {
    rootId: 'root-owned', projectId: 'project-owned', contextId: 'context-owned',
    canonicalRootPath: win.join(f.base, 'workspace'), canonicalProjectPath: win.join(f.base, 'project'),
    pending: false, revisions: { root: 1, project: 1, context: 1 },
  });
  assert.equal(adopted.contextId, 'context-owned');
  assert.equal(adopted.identityStatus, 'verified');
  assert.equal((await service.readWorkspaceManifest()).projects[adopted.fingerprint].projectId, 'project-owned');
});

test('Windows public manifest reload accepts extended UNC spelling of the same physical share', async t => {
  const f = await fixture(t, { unc: true });
  const root = win.join(f.base, 'workspace');
  const service = new f.TrainerWorkspaceService({ globalState: globalState() });
  await service.selectRoot(root);
  const manifestFile = win.join(root, f.TRAINER_WORKSPACE_MANIFEST_FILE);
  const manifest = JSON.parse(await f.io.readFile(manifestFile, 'utf8'));
  manifest.rootPath = '\\\\?\\UNC\\' + root.slice(2).toUpperCase();
  manifest.canonicalRootPath = manifest.rootPath;
  await f.io.writeFile(manifestFile, JSON.stringify(manifest));
  assert.equal((await service.readWorkspaceManifest()).rootPath, manifest.rootPath);
});

test('Windows public manifest rejects a genuine foreign root and denied native alias resolution', async t => {
  const f = await fixture(t);
  const root = win.join(f.base, 'workspace');
  const foreign = win.join(f.base, 'foreign');
  const service = new f.TrainerWorkspaceService({ globalState: globalState() });
  await service.selectRoot(root);
  await f.io.mkdir(foreign);
  const file = win.join(root, f.TRAINER_WORKSPACE_MANIFEST_FILE);
  const manifest = JSON.parse(await f.io.readFile(file, 'utf8'));
  manifest.rootPath = foreign; manifest.canonicalRootPath = foreign;
  await f.io.writeFile(file, JSON.stringify(manifest));
  await assert.rejects(service.readWorkspaceManifest(), /belongs to a different root/);
  manifest.rootPath = root.replace('runneradmin', 'RUNNER~1'); manifest.canonicalRootPath = manifest.rootPath;
  await f.io.writeFile(file, JSON.stringify(manifest));
  f.denyNative();
  await assert.rejects(service.readWorkspaceManifest(), /belongs to a different root/);
  assert.equal(f.plainCalls.length, 0, 'denied native resolution must not fall back to the JS walker');
});

test('Windows public manifest rejects an unresolved alias when native realpath is unavailable', async t => {
  const f = await fixture(t);
  const root = win.join(f.base, 'workspace');
  const service = new f.TrainerWorkspaceService({ globalState: globalState() });
  await service.selectRoot(root);
  const file = win.join(root, f.TRAINER_WORKSPACE_MANIFEST_FILE);
  const manifest = JSON.parse(await f.io.readFile(file, 'utf8'));
  manifest.rootPath = root.replace('runneradmin', 'RUNNER~1');
  manifest.canonicalRootPath = manifest.rootPath;
  await f.io.writeFile(file, JSON.stringify(manifest));
  f.disableNative();
  await assert.rejects(service.readWorkspaceManifest(), /belongs to a different root/);
  assert.equal(f.plainCalls.length, 0, 'missing native resolution must not fall back to the JS walker');
});
