'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  resolveResourceWorkbenchGovernance,
} = require('../dist/shared/src/resourceWorkbenchGovernance.js');

test('resource workbench keeps detail and sandbox mutually exclusive', () => {
  const result = resolveResourceWorkbenchGovernance({
    preferredSurface: 'detail',
    hasSelectedResource: true,
    hasDetail: true,
    hasSandbox: true,
  });

  assert.deepEqual(result, {
    activeSurface: 'detail',
    canOpenDetail: true,
    canOpenSandbox: true,
    showDetail: true,
    showSandbox: false,
  });
});

test('resource workbench falls back to sandbox when detail cannot open', () => {
  const result = resolveResourceWorkbenchGovernance({
    preferredSurface: 'detail',
    hasSelectedResource: false,
    hasDetail: false,
    hasSandbox: true,
  });

  assert.deepEqual(result, {
    activeSurface: 'sandbox',
    canOpenDetail: false,
    canOpenSandbox: true,
    showDetail: false,
    showSandbox: true,
  });
});

test('resource workbench falls back to list when no secondary surface is available', () => {
  const result = resolveResourceWorkbenchGovernance({
    preferredSurface: 'sandbox',
    hasSelectedResource: false,
    hasDetail: false,
    hasSandbox: false,
  });

  assert.deepEqual(result, {
    activeSurface: 'list',
    canOpenDetail: false,
    canOpenSandbox: false,
    showDetail: false,
    showSandbox: false,
  });
});
