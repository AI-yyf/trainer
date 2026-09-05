import * as vscode from 'vscode';

import {
  buildTestRunAttestationBody,
  dispatchTestRunAttestation,
  resolveAttestationWorkspaceId,
  resolveLivePracticeCard,
  type TrainingAttestationRuntime,
} from './trainingAttestation';

export class TrainerTestController implements vscode.Disposable {
  private readonly controller = vscode.tests.createTestController("trainer", "Trainer");
  private readonly checksByItem = new WeakMap<vscode.TestItem, EvaluationCheck>();
  private attestationRuntime: TrainingAttestationRuntime | undefined;

  constructor(attestationRuntime?: TrainingAttestationRuntime) {
    this.attestationRuntime = attestationRuntime;
    // Run profile so the published checks execute from the VS Code Testing
    // view. Optional call: embedded hosts and test mocks may not implement
    // createRunProfile, in which case the checks stay display-only.
    this.controller.createRunProfile?.(
      'Run',
      vscode.TestRunProfileKind.Run,
      (request, token) => this.runPublishedChecks(request, token),
      true,
    );
  }

  /**
   * Attach the lazily-created command context services used for training
   * verification attestation. Called once activation finishes wiring the
   * runtime; passing undefined detaches attestation.
   */
  public setAttestationRuntime(runtime: TrainingAttestationRuntime | undefined): void {
    this.attestationRuntime = runtime;
  }

  public publishReport(report: unknown, uri: vscode.Uri): void {
    const root = this.getOrCreateItem(uri.toString(), uri.path.split("/").pop() ?? "Current File", uri);
    this.controller.items.add(root);
    const resolved = normalizeReport(report);

    root.children.replace([
      this.toGroup("Static Checks", resolved.staticChecks),
      this.toGroup("Dynamic Checks", resolved.dynamicChecks),
      this.toGroup("Semantic Checks", resolved.semanticChecks),
    ]);
  }

  private toGroup(label: string, checks: EvaluationCheck[]): vscode.TestItem {
    const group = this.controller.createTestItem(label, label);
    for (const check of checks) {
      const item = this.controller.createTestItem(check.id, check.label);
      item.error = check.status === "failed" ? check.detail : undefined;
      item.description = check.detail;
      this.checksByItem.set(item, check);
      group.children.add(item);
    }
    return group;
  }

  private getOrCreateItem(id: string, label: string, uri: vscode.Uri): vscode.TestItem {
    return this.controller.items.get(id) ?? this.controller.createTestItem(id, label, uri);
  }

  /**
   * Execute the currently published checks as a VS Code test run. Warnings
   * count as passing (they do not fail a run); only `failed` checks fail it.
   * After a fully-passing run with at least one executed check, the result is
   * attested to the sidecar so a live practice card's handoff becomes
   * verified server-side.
   */
  private async runPublishedChecks(
    request: vscode.TestRunRequest,
    token?: vscode.CancellationToken,
  ): Promise<void> {
    const run = this.controller.createTestRun(request);
    const excluded = new Set<string>((request.exclude ?? []).map((item) => item.id));
    const outputLines: string[] = [];
    let executed = 0;
    let failures = 0;

    for (const root of this.collectionItems(this.controller.items)) {
      const outcome = this.executeItemTree(root, excluded, token, run, outputLines);
      executed += outcome.executed;
      failures += outcome.failures;
    }

    run.end();

    if (executed > 0 && failures === 0) {
      this.attestSuccessfulRun(executed, outputLines);
    }
  }

  private executeItemTree(
    item: vscode.TestItem,
    excluded: Set<string>,
    token: vscode.CancellationToken | undefined,
    run: vscode.TestRun,
    outputLines: string[],
  ): { executed: number; failures: number } {
    if (token?.isCancellationRequested || excluded.has(item.id)) {
      return { executed: 0, failures: 0 };
    }

    const children = this.collectionItems(item.children);
    if (children.length > 0) {
      let executed = 0;
      let failures = 0;
      for (const child of children) {
        const outcome = this.executeItemTree(child, excluded, token, run, outputLines);
        executed += outcome.executed;
        failures += outcome.failures;
      }
      return { executed, failures };
    }

    const check = this.checksByItem.get(item);
    if (!check) {
      return { executed: 0, failures: 0 };
    }

    if (check.status === 'failed') {
      const message = check.detail || `${check.label} failed`;
      run.failed(item, new vscode.TestMessage(message));
      outputLines.push(`FAIL ${check.label}: ${message}`);
      return { executed: 1, failures: 1 };
    }

    run.passed(item);
    outputLines.push(
      check.detail ? `PASS ${check.label}: ${check.detail}` : `PASS ${check.label}`,
    );
    return { executed: 1, failures: 0 };
  }

  private collectionItems(collection: vscode.TestItemCollection): vscode.TestItem[] {
    const items: vscode.TestItem[] = [];
    collection.forEach((item) => items.push(item));
    return items;
  }

  /**
   * Attest a successful run to the sidecar (fire-and-forget — attestation must
   * never break or delay the test UX).
   *
   * Provenance: the VS Code Testing API TestRunRequest carries no information
   * about which surface requested the run, so no trainer-training-surface gate
   * exists in this controller. Until such provenance is added, any successful
   * run attests when a live practice card exists for the current workspace;
   * the sidecar still validates that the attested card is the live one.
   */
  private attestSuccessfulRun(testCount: number, outputLines: string[]): void {
    const runtime = this.attestationRuntime;
    if (!runtime) {
      return;
    }

    const hostState = runtime.getHostState();
    const card = resolveLivePracticeCard(hostState);
    if (!card) {
      return;
    }

    const body = buildTestRunAttestationBody({
      card,
      summary: `Test run passed: ${testCount} test(s)`,
      testsOutput: outputLines.join('\n'),
      sessionId: runtime.getSessionId(),
      workspaceId: resolveAttestationWorkspaceId(hostState),
    });
    void dispatchTestRunAttestation(runtime, body);
  }

  public dispose(): void {
    this.controller.dispose();
  }
}

type EvaluationCheck = {
  id: string;
  label: string;
  status: string;
  detail: string;
};

function normalizeReport(report: unknown): {
  staticChecks: EvaluationCheck[];
  dynamicChecks: EvaluationCheck[];
  semanticChecks: EvaluationCheck[];
} {
  const record = report && typeof report === "object" ? (report as Record<string, unknown>) : {};
  return {
    staticChecks: normalizeChecks(record.static_checks ?? record.staticChecks),
    dynamicChecks: normalizeChecks(record.dynamic_checks ?? record.dynamicChecks),
    semanticChecks: normalizeChecks(record.semantic_checks ?? record.semanticChecks),
  };
}

function normalizeChecks(value: unknown): EvaluationCheck[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((item, index) => {
    const record = item && typeof item === "object" ? (item as Record<string, unknown>) : {};
    return {
      id: typeof record.id === "string" ? record.id : `check-${index + 1}`,
      label: typeof record.label === "string" ? record.label : `Check ${index + 1}`,
      status: typeof record.status === "string" ? record.status : "warning",
      detail: typeof record.detail === "string" ? record.detail : "",
    };
  });
}
