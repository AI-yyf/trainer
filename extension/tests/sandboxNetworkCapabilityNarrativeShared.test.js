'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  describeSandboxNetworkCapabilityDetail,
  describeSandboxNetworkCapabilityCoachDetail,
  describeSandboxNetworkCapabilityCoachFacts,
  describeSkillRuntimeGateCoachPolicyFacts,
  describeSkillRuntimeThreatCoachFact,
  describeSandboxNetworkCapabilityFacts,
  describeSandboxOsContainerExecutionPlan,
  describeSandboxNetworkReasonCode,
} = require('../dist/shared/src/sandboxNetworkCapabilityNarrative.js');

function createNetworkStatus() {
  return {
    summary: 'Narrow guards exist, but general os/container egress is still unavailable.',
    reasonCode: 'network_egress_os_container_executor_not_implemented',
    reasons: ['A supported container runtime is reachable, but the executor layer is not wired yet.'],
    networkFacts: {
      auditedPython: {
        status: 'guarded_allowlist_only',
        currentEnforcement: 'python_socket_guard',
        nextRequirement: 'os_or_container_egress_enforcement',
        reasonCode: '',
        reason: '',
        requiredExecutor: 'python_socket_guard',
      },
      unauditedPython: {
        status: 'blocked',
        currentEnforcement: 'runtime_preflight',
        nextRequirement: 'audited_sandbox_python_script',
        reasonCode: 'network_egress_unaudited_command_path',
        reason: 'Unaudited Python command paths stay blocked.',
        requiredExecutor: 'python_socket_guard',
      },
      nonPython: {
        status: 'blocked',
        currentEnforcement: 'runtime_preflight',
        nextRequirement: 'os_or_container_egress_enforcement',
        reasonCode: 'network_egress_non_python_entrypoint',
        reason: 'Generic non-Python network execution stays blocked unless it matches a verified Ruby or Node.js os/container lane.',
        requiredExecutor: 'os_container_egress',
      },
      childProcess: {
        status: 'blocked_by_preflight',
        currentEnforcement: 'runtime_preflight',
        nextRequirement: 'subprocess_free_audited_entrypoint',
        reasonCode: 'network_egress_child_process_escape_blocked',
        reason: 'Child-process escape surfaces stay blocked.',
        requiredExecutor: 'none',
      },
      osContainer: {
        status: 'missing',
        currentEnforcement: 'missing',
        nextRequirement: 'os_or_container_egress_enforcement',
        reasonCode: 'network_egress_os_container_executor_not_implemented',
        reason: 'Reachable runtime detected, but os_container_egress is not wired.',
        requiredExecutor: 'os_container_egress',
      },
      osContainerProbe: {
        availability: 'unavailable_executor_not_implemented',
        selectedRuntime: 'docker',
        selectedExecutorMode: 'none',
        selectedEntryRuntime: 'none',
        supportedEntryRuntimes: ['ruby', 'node'],
        reasonCode: 'network_egress_os_container_executor_not_implemented',
        reason: 'Reachable docker runtime detected, but Trainer has not wired a verified os_container_egress executor yet.',
        imageReference: 'ruby:3.3-alpine',
        imageRepoDigests: ['ruby@sha256:trustedbeadfeed'],
        selectedImageRepoDigest: 'ruby@sha256:trustedbeadfeed',
        imageTrustPolicy: 'trainer.resource_sandbox.os_container_image_trust.v1',
        imageTrustStatus: 'trusted',
      },
    },
  };
}

test('describeSandboxNetworkCapabilityFacts includes os/container probe truth', () => {
  const facts = describeSandboxNetworkCapabilityFacts(createNetworkStatus().networkFacts, 'en-US');

  assert.ok(facts.some((item) => item.includes('audited python: guarded')));
  assert.ok(facts.some((item) => item.includes('os/container isolation: missing')));
  assert.ok(
    facts.some(
      (item) =>
        item.includes('os/container probe: executor not implemented') &&
        item.includes('runtime: docker') &&
        item.includes('supported entries: ruby, node') &&
        item.includes('image: ruby:3.3-alpine'),
    ),
  );
});

test('describeSandboxNetworkCapabilityDetail falls back to joined lane/probe detail when facts exist', () => {
  const detail = describeSandboxNetworkCapabilityDetail(createNetworkStatus(), 'en-US');

  assert.match(detail, /audited python: guarded/);
  assert.match(detail, /os\/container probe: executor not implemented/);
  assert.doesNotMatch(detail, /^network gate:/);
});

test('describeSandboxNetworkCapabilityCoachFacts returns learner-facing lines without internal guard tokens', () => {
  const facts = describeSandboxNetworkCapabilityCoachFacts(createNetworkStatus().networkFacts, 'en-US');

  assert.ok(
    facts.some((item) => item.includes('Audited Python entry: networking is allowed only for approved hosts')),
  );
  assert.ok(facts.some((item) => item.includes('Generic non-Python commands: networking stays blocked by default')));
  assert.ok(!facts.some((item) => item.includes('runtime_preflight')));
  assert.ok(!facts.some((item) => item.includes('python_socket_guard')));
});

test('describeSandboxNetworkCapabilityCoachFacts uses zh white-list wording', () => {
  const facts = describeSandboxNetworkCapabilityCoachFacts(createNetworkStatus().networkFacts, 'zh-CN');

  assert.ok(facts.some((item) => item.includes('白名单网域')));
  assert.ok(!facts.some((item) => item.includes('allowlist')));
});

test('describeSandboxNetworkCapabilityCoachDetail returns coach-facing zh summary', () => {
  const detail = describeSandboxNetworkCapabilityCoachDetail(createNetworkStatus(), 'zh-CN');

  assert.match(detail, /已审计 Python 入口：只允许在白名单网域内联网/);
  assert.match(detail, /通用非 Python 命令：默认禁止联网/);
});

test('describeSandboxNetworkCapabilityDetail falls back to reason code when facts are missing', () => {
  const detail = describeSandboxNetworkCapabilityDetail(
    {
      summary: 'General network enforcement is missing.',
      reasonCode: 'network_egress_os_container_runtime_missing',
      reasons: [],
    },
    'en-US',
  );

  assert.equal(detail, 'network gate: container runtime missing');
});

test('describeSandboxNetworkReasonCode returns localized probe labels', () => {
  assert.equal(
    describeSandboxNetworkReasonCode('network_egress_os_container_probe_failed', 'en-US'),
    'network gate: container probe failed',
  );
  assert.equal(
    describeSandboxNetworkReasonCode('network_egress_os_container_image_missing', 'en-US'),
    'network gate: container image missing',
  );
  assert.equal(
    describeSandboxNetworkReasonCode('network_egress_requires_os_container_executor', 'en-US'),
    'network gate: os/container executor required',
  );
  assert.equal(
    describeSandboxNetworkReasonCode('network_egress_child_process_escape_blocked', 'en-US'),
    'network gate: child-process escape blocked',
  );
  assert.match(
    describeSandboxNetworkReasonCode('network_egress_os_container_probe_failed', 'zh-CN'),
    /容器|探测/,
  );
});

test('describeSandboxOsContainerExecutionPlan summarizes blocked and ready plan truth', () => {
  const blockedFacts = describeSandboxOsContainerExecutionPlan(
    {
      status: 'planned_blocked',
      runtime: 'none',
      executorMode: 'none',
      networkAllowlist: ['docs.example.com'],
      containerWorkdir: '/sandbox/skill',
      containerInputPath: '/sandbox/skill',
      containerOutputPaths: ['/sandbox/skill/out.txt'],
      runtimeCommand: [],
      reasonCode: 'network_egress_os_container_runtime_missing',
      reason: 'Container runtime missing.',
    },
    'en-US',
  );
  assert.match(blockedFacts[0], /container plan: planned but blocked/);
  assert.ok(blockedFacts.some((item) => item.includes('allowlist: docs.example.com')));
  assert.ok(blockedFacts.some((item) => item.includes('workdir: /sandbox/skill')));

  const readyFacts = describeSandboxOsContainerExecutionPlan(
    {
      status: 'planned_probe_ready',
      runtime: 'docker',
      executorMode: 'os_container_egress',
      selectedEntryRuntime: 'node',
      networkAllowlist: ['docs.example.com'],
      containerRootPath: '/trainer-sandbox',
      containerWorkdir: '/sandbox/skill',
      containerInputPath: '/sandbox/skill',
      containerOutputPaths: ['/sandbox/skill/out.txt'],
      runtimeCommand: ['docker', 'run', '--rm'],
      containerImage: 'node:22-alpine',
      containerImageRepoDigest: 'node@sha256:trustednodebeadfeed',
      imageTrustPolicy: 'trainer.resource_sandbox.os_container_image_trust.v1',
      imageTrustStatus: 'trusted',
      reasonCode: 'network_egress_os_container_executor_not_implemented',
      reason: 'Detected reachable runtime.',
    },
    'en-US',
  );
  assert.match(readyFacts[0], /container plan: runtime detected but executor not ready/);
  assert.ok(readyFacts.some((item) => item.includes('container root: /trainer-sandbox')));
  assert.ok(readyFacts.some((item) => item.includes('runtime cmd: docker run --rm')));
  assert.ok(readyFacts.some((item) => item.includes('entry: node')));
  assert.ok(readyFacts.some((item) => item.includes('image: node:22-alpine')));
  assert.ok(readyFacts.some((item) => item.includes('image trust: trusted')));
});

test('describeSkillRuntimeGateCoachPolicyFacts maps internal policy ids to coach facts', () => {
  const facts = describeSkillRuntimeGateCoachPolicyFacts({
    state: 'executor_blocked',
    policies: [
      'trainer.resource_sandbox.skill_runtime.v1',
      'trainer.resource_sandbox.skill_run_gate.v1;trainer.resource_sandbox.skill_isolated_executor.v1',
    ],
    language: 'en-US',
  });

  assert.ok(facts.some((item) => item.includes('Preflight boundary')));
  assert.ok(facts.some((item) => item.includes('Run gate')));
  assert.ok(facts.some((item) => item.includes('Isolated executor')));
  assert.ok(!facts.some((item) => item.includes('trainer.resource_sandbox')));
});

test('describeSkillRuntimeThreatCoachFact hides raw threat enum in coach wording', () => {
  const fact = describeSkillRuntimeThreatCoachFact('network_exfiltration', 'en-US');
  assert.equal(fact, 'Risk type: suspicious outbound network behavior was blocked.');
  assert.ok(!fact.includes('network_exfiltration'));
});
