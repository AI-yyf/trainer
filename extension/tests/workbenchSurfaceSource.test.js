'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const iconsPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'icons',
  'CoachIcons.tsx',
);
const bubblePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'coach',
  'CoachMessageBubble.tsx',
);
const stylesPath = path.resolve(__dirname, '..', 'webview', 'src', 'styles.css');

test('workbench header keeps only the connection pill; reply actions live under each coach reply', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const headerStart = source.indexOf('className="header-actions"');
  assert.ok(headerStart > -1, 'expected header-actions container');
  const header = source.slice(headerStart, headerStart + 1200);

  assert.doesNotMatch(header, /handleShareSession/);
  assert.doesNotMatch(header, /header-actions__button/);

  const bubble = fs.readFileSync(bubblePath, 'utf8');
  assert.match(bubble, /message-bubble__actions/);
  assert.match(bubble, /onMessageAction\?\.\("share", message\)/);
  assert.match(bubble, /onMessageAction\?\.\("save-resource", message\)/);
  assert.match(bubble, /onMessageAction\?\.\("training-card", message\)/);
});

test('share icon exists and is wired into each coach reply action row', () => {
  const icons = fs.readFileSync(iconsPath, 'utf8');
  assert.match(icons, /export function ShareIcon/);

  const bubble = fs.readFileSync(bubblePath, 'utf8');
  assert.match(bubble, /<ShareIcon size=\{13\}/);
});

test('skill deck offers manage flow for custom skills', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  assert.match(source, /skill-deck__manage-row/);
  assert.match(source, /skill-deck__custom-list/);
  assert.match(source, /skill-deck__create-row/);
  assert.match(source, /parseTrainerSkillShare\(skillImportText\)/);
  assert.match(source, /serializeTrainerSkillShare/);
  assert.match(source, /mergeSkillCatalog\(customSkills\)/);
  assert.match(source, /pendingDeleteSkillId/);
});

test('skill deck resolves on the trigger token so arguments keep the match', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  // Suggestions filter on the first $token only — text after it is skill
  // arguments, and a full-draft query would empty the deck for "$skill args".
  const skillsStart = source.indexOf('const matchingLocalSkills');
  assert.ok(skillsStart > -1, 'expected matchingLocalSkills declaration');
  const skillsBlock = source.slice(skillsStart, skillsStart + 1200);
  assert.match(skillsBlock, /trainerSkillTriggerToken\(normalizedDraft\)/);
  assert.match(skillsBlock, /filterTrainerSkills\(triggerToken/);
  assert.doesNotMatch(skillsBlock, /filterTrainerSkills\(normalizedDraft/);

  // The create row checks the whole catalog so an existing trigger never gets
  // a colliding affordance.
  const deckStart = source.indexOf('const renderSkillDeck');
  assert.ok(deckStart > -1, 'expected renderSkillDeck');
  const deckBlock = source.slice(deckStart, deckStart + 2500);
  assert.match(deckBlock, /trainerSkillTriggerToken\(normalizedDraft\)/);
  assert.match(deckBlock, /availableSkillCatalog\.some/);

  // Autocomplete replaces only the typed token; arguments survive.
  const selectStart = source.indexOf('const selectSkillSuggestion');
  assert.ok(selectStart > -1, 'expected selectSkillSuggestion');
  const selectBlock = source.slice(selectStart, selectStart + 800);
  assert.match(selectBlock, /normalizedDraft\.slice\(triggerToken\.length\)/);
});

test('enter submits a resolved skill with args instead of refilling the composer', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const enterStart = source.indexOf('alreadyResolvedWithArgs');
  assert.ok(enterStart > -1, 'expected alreadyResolvedWithArgs guard');
  const enterBlock = source.slice(enterStart - 600, enterStart + 900);
  assert.match(enterBlock, /normalizedDraft\.length > typedTrigger\.length/);
  assert.match(enterBlock, /selectedSkill\?\.trigger\.toLowerCase\(\) === typedTrigger\.toLowerCase\(\)/);
});

test('custom skills persist the normalized, capped list', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const persist = source.slice(
    source.indexOf('const persistCustomSkills'),
    source.indexOf('const saveCustomSkillDraft'),
  );
  // Local state must match what the save payload stores — a raw list over the
  // cap leaves the save-dedup comparison permanently mismatched.
  assert.match(persist, /setCoachDefaults\(\{ customSkills: normalizeTrainerCustomSkills\(next\) \}\)/);
  assert.match(
    source,
    /remaining\.length >= TRAINER_CUSTOM_SKILL_LIMIT[\s\S]*?tone: "error"/,
  );
});

test('message supplements always render inline with no fold', () => {
  const source = fs.readFileSync(bubblePath, 'utf8');

  // Supplement material (artifacts, attachments, context notes) renders flat:
  // a collapsed "I also used these" region read as a broken/empty card.
  assert.doesNotMatch(source, /shouldCollapseDetails/);
  assert.doesNotMatch(source, /CollapsibleBlock/);
  assert.match(source, /hasSupplementMaterial \?/);
  assert.match(source, /message-bubble__details-body">\{detailBlocks\}/);
});

test('message reply action buttons use token-driven styling', () => {
  const styles = fs.readFileSync(stylesPath, 'utf8');
  const block = styles.match(/\.message-bubble__action\s*\{[\s\S]*?\n\}/);
  assert.ok(block, 'expected message-bubble__action styles');
  assert.doesNotMatch(block[0], /#[0-9a-fA-F]{3,8}\b/, 'no hardcoded colors');
  assert.match(block[0], /var\(--/);
});
