"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const matrixPath = path.resolve(__dirname, "..", "..", "e2e", "trainer-experience-matrix.js");
const {
  GROUP_COUNTS,
  PERSONAS,
  PREVIEW_EVIDENCE,
  SCENARIOS,
  VIEW_ORDER,
} = require(matrixPath);

test("the Trainer experience matrix keeps 200 uniquely traceable user scenarios", () => {
  assert.equal(SCENARIOS.length, 200);
  assert.deepEqual(GROUP_COUNTS, {
    coach: 34,
    plan: 34,
    resources: 38,
    training: 44,
    settings: 20,
    cross: 30,
  });
  assert.equal(new Set(SCENARIOS.map((scenario) => scenario.id)).size, 200);
  assert.equal(new Set(SCENARIOS.map((scenario) => scenario.definitionId)).size, 89);
});

test("every scenario is an authored user contract, not a label with a runner attached", () => {
  const runners = new Set(["coach", "plan", "resources", "training", "settings", "cross"]);
  const languages = new Set(["zh-CN", "en-US", "es-ES", "fr-FR", "de-DE", "ja-JP", "ko-KR", "pt-BR"]);

  for (const scenario of SCENARIOS) {
    assert.match(scenario.id, /^([CPRTSX])\d{2}$/, `invalid ID: ${scenario.id}`);
    assert.ok(scenario.title.length > 0, `${scenario.id} needs a title`);
    assert.ok(scenario.definitionId.length > 0, `${scenario.id} needs an authored definition ID`);
    assert.ok(scenario.domain.length > 0, `${scenario.id} needs a learning domain`);
    assert.ok(scenario.userGoal.length > 0, `${scenario.id} needs a user goal`);
    assert.ok(VIEW_ORDER.includes(scenario.view), `${scenario.id} has an unknown view`);
    assert.ok(runners.has(scenario.runner), `${scenario.id} has no executable runner`);
    assert.ok(languages.has(scenario.language), `${scenario.id} has an unsupported locale`);
    assert.ok(scenario.viewport.width >= 300, `${scenario.id} is below the supported narrow width`);
    assert.ok(scenario.viewport.height >= 800, `${scenario.id} needs a usable sidebar height`);
    assert.ok(scenario.requirements.length >= 3, `${scenario.id} needs traceable requirements`);

    assert.ok(scenario.persona?.id, `${scenario.id} needs an authored learner persona`);
    assert.ok(PERSONAS[scenario.persona.id], `${scenario.id} has an unknown learner persona`);
    assert.equal(scenario.persona.language, scenario.language, `${scenario.id} has a locale mismatch`);
    assert.ok(scenario.persona.role, `${scenario.id} needs a human learner role`);
    assert.ok(scenario.persona.context, `${scenario.id} needs a learner context`);
    assert.ok(scenario.persona.goal, `${scenario.id} needs a learner goal`);

    assert.ok(scenario.userAction?.kind, `${scenario.id} needs a concrete user action`);
    assert.ok(Array.isArray(scenario.expected?.visible), `${scenario.id} needs visible expectations`);
    assert.ok(scenario.expected.visible.length >= 3, `${scenario.id} needs several visible expectations`);
    assert.ok(Array.isArray(scenario.expected?.forbidden), `${scenario.id} needs forbidden outcomes`);
    assert.ok(scenario.expected.forbidden.length >= 3, `${scenario.id} needs safety constraints`);
    assert.ok(scenario.expected?.recovery?.kind, `${scenario.id} needs a recovery contract`);
    assert.ok(scenario.expected?.persistence?.kind, `${scenario.id} needs a persistence contract`);

    assert.equal(scenario.primaryLayer, "PW", `${scenario.id} must declare the Preview evidence layer`);
    assert.equal(scenario.evidence.primaryLayer, "PW", `${scenario.id} has inconsistent primary evidence`);
    assert.equal(scenario.evidence.realSidecar, false, `${scenario.id} must not claim a real sidecar`);
    assert.match(scenario.evidence.limitation, /Preview fixtures/i, `${scenario.id} needs a Preview limitation`);
  }
});

test("persona assignment is authored by journey rather than derived from scenario IDs", () => {
  const personasByDefinition = new Map();
  for (const scenario of SCENARIOS) {
    const knownPersona = personasByDefinition.get(scenario.definitionId);
    if (knownPersona) {
      assert.equal(
        scenario.persona.id,
        knownPersona,
        `${scenario.definitionId} must keep its authored persona across variants`,
      );
    } else {
      personasByDefinition.set(scenario.definitionId, scenario.persona.id);
    }
  }

  const source = fs.readFileSync(matrixPath, "utf8");
  assert.doesNotMatch(source, /scenario\.id[^\n]*%|id\.slice\([^\n]*%/, "persona must not be derived from an ID modulo");
});

test("the matrix covers the requested learner domains and failure paths", () => {
  const domains = new Set(SCENARIOS.map((scenario) => scenario.domain));
  for (const requiredDomain of [
    "Python",
    "TypeScript",
    "JavaScript",
    "AI",
    "GitHub",
    "API",
    "Remote SSH",
    "Debugging",
    "VS Code",
    "Scientific research",
    "English",
    "Writing",
  ]) {
    assert.ok(domains.has(requiredDomain), `missing required learner domain: ${requiredDomain}`);
  }

  const definitionIds = new Set(SCENARIOS.map((scenario) => scenario.definitionId));
  for (const requiredPath of [
    "provider-recovery-thread",
    "agent-failure-context-recovery",
    "workspace-root-missing",
    "path-migration",
    "language-switch",
    "provider-switch",
    "blocked-card-recovery",
  ]) {
    assert.ok(definitionIds.has(requiredPath), `missing required recovery path: ${requiredPath}`);
  }
});

test("Preview-verifiable contracts are executable while host-only contracts state their limit", () => {
  assert.equal(PREVIEW_EVIDENCE.primaryLayer, "PW");
  assert.equal(PREVIEW_EVIDENCE.realSidecar, false);

  for (const scenario of SCENARIOS) {
    for (const forbidden of scenario.expected.forbidden) {
      assert.ok(
        forbidden.verification === "PW" || forbidden.verification === "VSIX",
        `${scenario.id} has an unknown forbidden-outcome layer`,
      );
    }
    for (const contract of [scenario.expected.recovery, scenario.expected.persistence]) {
      assert.ok(
        contract.verification === "PW" || contract.verification === "VSIX",
        `${scenario.id} has an unknown contract layer`,
      );
      if (contract.verification === "VSIX") {
        assert.ok(contract.limitation, `${scenario.id} must explain a host-only contract limit`);
      }
    }
  }
});
