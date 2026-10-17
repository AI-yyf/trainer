'use strict';

// P1 #13 (§5 + §7.7): Research is now the coach's preparation engine, a
// backstage capability. Its eight commands stay registered for deep-link
// compatibility (workbenchDestinations contract), but they must never leak
// back into the primary command catalog — the display surface was
// converged, and this guard pins that convergence.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(
  path.resolve(__dirname, '../../shared/src/commands.ts'),
  'utf8',
);

function slicePrimaryCatalog() {
  const start = source.indexOf('export const trainerCommandCatalog');
  const end = source.indexOf('export const researchCompatibilityCommandCatalog');
  assert.ok(start !== -1 && end !== -1 && end > start, 'catalog boundaries must exist');
  return source.slice(start, end);
}

test('primary command catalog carries no research commands', () => {
  assert.doesNotMatch(slicePrimaryCatalog(), /trainer\.research\./);
  assert.doesNotMatch(slicePrimaryCatalog(), /trainerCommands\.(createResearch|addResearchTheme|activateResearchTheme|advanceResearch|researchMessage|approveResearchDecision|getResearchStatus|researchStreamMessage)/);
});

test('research command ids stay available for deep-link compatibility', () => {
  for (const id of ['trainer.research.create', 'trainer.research.theme.add', 'trainer.research.advance', 'trainer.research.message', 'trainer.research.approve', 'trainer.research.status']) {
    assert.match(source, new RegExp(`"${id.replace(/\./g, '\\.')}"`), `${id} must remain registered`);
  }
});
