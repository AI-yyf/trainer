'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const testControllerModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'testing',
  'testController.js',
);

function createCollection() {
  const values = new Map();
  return {
    add(item) {
      values.set(item.id, item);
    },
    get(id) {
      return values.get(id);
    },
    replace(items) {
      values.clear();
      for (const item of items) {
        values.set(item.id, item);
      }
    },
    values() {
      return Array.from(values.values());
    },
  };
}

function createTestItem(id, label, uri) {
  return {
    id,
    label,
    uri,
    error: undefined,
    description: undefined,
    children: createCollection(),
  };
}

function createVscodeMock() {
  const controller = {
    items: createCollection(),
    createTestItem,
    disposeCalled: false,
    dispose() {
      this.disposeCalled = true;
    },
  };

  return {
    Uri: {
      file(filePath) {
        return {
          fsPath: filePath,
          path: filePath.replace(/\\/g, '/'),
          toString() {
            return `file://${filePath.replace(/\\/g, '/')}`;
          },
        };
      },
    },
    tests: {
      createTestController() {
        return controller;
      },
    },
    __controller: controller,
  };
}

function getRootItem(controller, uri) {
  return controller.items.get(uri.toString());
}

test('publishReport groups snake_case checks and marks failures as errors', () => {
  const vscodeMock = createVscodeMock();
  const { TrainerTestController } = loadWithVscodeMock(testControllerModulePath, vscodeMock);

  const tests = new TrainerTestController();
  const uri = vscodeMock.Uri.file('F:\\trainer\\sample.py');

  tests.publishReport(
    {
      static_checks: [{ id: 'ruff', label: 'Ruff', status: 'passed', detail: 'clean' }],
      dynamic_checks: [{ id: 'pytest', label: 'Pytest', status: 'failed', detail: '1 failing example' }],
      semantic_checks: [{ id: 'spec', label: 'Spec fit', status: 'warning', detail: 'Missing edge case' }],
    },
    uri,
  );

  const root = getRootItem(vscodeMock.__controller, uri);
  assert.equal(root.label, 'sample.py');

  const groups = root.children.values();
  assert.equal(groups.length, 3);
  assert.equal(groups[0].label, 'Static Checks');
  assert.equal(groups[1].label, 'Dynamic Checks');
  assert.equal(groups[2].label, 'Semantic Checks');

  const dynamicCheck = groups[1].children.values()[0];
  assert.equal(dynamicCheck.label, 'Pytest');
  assert.equal(dynamicCheck.error, '1 failing example');
  assert.equal(dynamicCheck.description, '1 failing example');

  tests.dispose();
  assert.equal(vscodeMock.__controller.disposeCalled, true);
});

test('publishReport accepts camelCase payloads and creates default ids when missing', () => {
  const vscodeMock = createVscodeMock();
  const { TrainerTestController } = loadWithVscodeMock(testControllerModulePath, vscodeMock);

  const tests = new TrainerTestController();
  const uri = vscodeMock.Uri.file('F:\\trainer\\selection.py');

  tests.publishReport(
    {
      staticChecks: [{ label: 'Static without id', status: 'passed', detail: 'ok' }],
      dynamicChecks: [],
      semanticChecks: [{ status: 'failed', detail: 'semantic issue' }],
    },
    uri,
  );

  const root = getRootItem(vscodeMock.__controller, uri);
  const groups = root.children.values();
  const staticCheck = groups[0].children.values()[0];
  const semanticCheck = groups[2].children.values()[0];

  assert.equal(staticCheck.id, 'check-1');
  assert.equal(staticCheck.label, 'Static without id');
  assert.equal(semanticCheck.id, 'check-1');
  assert.equal(semanticCheck.label, 'Check 1');
  assert.equal(semanticCheck.error, 'semantic issue');
});

test('publishReport tolerates malformed reports and still publishes empty groups', () => {
  const vscodeMock = createVscodeMock();
  const { TrainerTestController } = loadWithVscodeMock(testControllerModulePath, vscodeMock);

  const tests = new TrainerTestController();
  const uri = vscodeMock.Uri.file('F:\\trainer\\empty.py');

  tests.publishReport({ summary: 'no structured checks here' }, uri);

  const root = getRootItem(vscodeMock.__controller, uri);
  const groups = root.children.values();

  assert.equal(groups.length, 3);
  assert.equal(groups[0].children.values().length, 0);
  assert.equal(groups[1].children.values().length, 0);
  assert.equal(groups[2].children.values().length, 0);
});
