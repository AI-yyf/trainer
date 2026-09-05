'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const sidebarCommandsModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'shared',
  'src',
  'sidebarCommands.js',
);

const {
  filterSidebarControlCommands,
  findSidebarControlCommand,
  normalizeSidebarCommandInput,
  sidebarControlCommandLabel,
} = require(sidebarCommandsModulePath);

test('normalizeSidebarCommandInput trims and collapses spaces', () => {
  assert.equal(normalizeSidebarCommandInput('   /open   review   '), '/open review');
});

test('findSidebarControlCommand does not steal remote trainer slash commands', () => {
  assert.equal(findSidebarControlCommand('/review'), undefined);
  assert.equal(findSidebarControlCommand('/plan'), undefined);
  assert.equal(findSidebarControlCommand('/next'), undefined);
});

test('findSidebarControlCommand resolves stable english local control aliases', () => {
  assert.equal(findSidebarControlCommand('/open review')?.id, 'open-coach');
  assert.equal(findSidebarControlCommand('/lang zh')?.id, 'lang-zh');
  assert.equal(findSidebarControlCommand('/follow off')?.id, 'follow-off');
});

test('filterSidebarControlCommands suggests matching local controls only', () => {
  const commands = filterSidebarControlCommands('/open r');
  assert.equal(commands[0]?.id, 'open-resources');
  assert.ok(commands.some((command) => command.id === 'open-resources'));
  assert.ok(commands.every((command) => command.id.startsWith('open-')));
});

test('sidebarControlCommandLabel returns localized primary labels', () => {
  assert.equal(sidebarControlCommandLabel('open-coach', 'en-US'), '/open coach');
  assert.equal(sidebarControlCommandLabel('open-resources', 'en-US'), '/open resources');
  assert.equal(sidebarControlCommandLabel('open-training', 'en-US'), '/open training');
});

test('new five-view local commands resolve for resources and training', () => {
  assert.equal(findSidebarControlCommand('/open resources')?.id, 'open-resources');
  assert.equal(findSidebarControlCommand('/open training')?.id, 'open-training');
});
