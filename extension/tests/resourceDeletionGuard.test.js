"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

/**
 * The library must never drop the last copy of a resource.
 *
 * The behavior is proven by `server/tests/test_md_only_migration_safety.py`.
 * This guard pins the shape that makes it hold: every path that removes the
 * learner's bytes checks the artifact that stands behind them **before** it
 * deletes, so a future edit cannot reorder the two.
 */

const repoRoot = path.resolve(__dirname, "..", "..");

function readSource(relativePath) {
  return fs.readFileSync(path.join(repoRoot, relativePath), "utf8");
}

/** The body of one method, from its definition to the next one. */
function methodBody(source, name) {
  const start = source.indexOf(`def ${name}(`);
  assert.notEqual(start, -1, `method not found: ${name}`);
  const next = source.indexOf("\n    def ", start + 1);
  return source.slice(start, next === -1 ? source.length : next);
}

const SERVICE = "server/app/resources/service.py";

test("the migration drops legacy originals only behind a readable canonical document", () => {
  const source = readSource(SERVICE);
  const chokepoint = methodBody(source, "_remove_originals_behind_markdown");

  assert.ok(
    chokepoint.includes("_has_readable_markdown"),
    "the deletion point must check that the canonical document is readable",
  );
  const check = chokepoint.indexOf("_has_readable_markdown");
  const removal = chokepoint.indexOf("unlink");
  assert.ok(removal !== -1, "the deletion point must actually delete the originals");
  assert.ok(
    check < removal,
    "the readable-document check must come before the deletion, not after it",
  );
});

test("the inline upload copy follows the same rule", () => {
  const source = readSource(SERVICE);
  const inline = methodBody(source, "_discard_managed_inline_source");

  assert.ok(
    inline.includes("_has_readable_markdown"),
    "the inline upload copy must check that the canonical document is readable",
  );
  assert.ok(
    inline.indexOf("_has_readable_markdown") < inline.indexOf("unlink"),
    "the readable-document check must come before the deletion",
  );
});

test("a readable canonical document is more than a named path", () => {
  const source = readSource(SERVICE);
  const helper = methodBody(source, "_has_readable_markdown");
  assert.ok(helper.includes("st_size > 0"), "an empty document must not stand behind the originals");
});

test("the shipped sidecar carries the same guard", () => {
  // The real product runs the bundled copy, not the source tree: the guard
  // has to hold in both.
  const bundled = readSource("extension/bundled/server/app/resources/service.py");
  const chokepoint = methodBody(bundled, "_remove_originals_behind_markdown");
  assert.ok(chokepoint.includes("_has_readable_markdown"));
  assert.ok(chokepoint.indexOf("_has_readable_markdown") < chokepoint.indexOf("unlink"));
});
