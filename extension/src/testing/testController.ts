import * as vscode from 'vscode';

export interface TrainerTestVerificationRuntime {
  evaluateFile(uri: vscode.Uri): Promise<unknown>;
  outputChannel: Pick<vscode.OutputChannel, 'appendLine'>;
}

export class TrainerTestController implements vscode.Disposable {
  private readonly controller = vscode.tests.createTestController('trainer', 'Trainer');
  private readonly checksByItem = new WeakMap<vscode.TestItem, EvaluationCheck>();

  constructor(private verificationRuntime?: TrainerTestVerificationRuntime) {
    this.controller.createRunProfile?.('Run', vscode.TestRunProfileKind.Run,
      (request, token) => this.runPublishedChecks(request, token), true);
  }

  public setVerificationRuntime(runtime: TrainerTestVerificationRuntime): void {
    this.verificationRuntime = runtime;
  }

  public publishReport(report: unknown, uri: vscode.Uri): void {
    const root = this.controller.items.get(uri.toString())
      ?? this.controller.createTestItem(uri.toString(), uri.path.split('/').pop() ?? 'Current File', uri);
    this.controller.items.add(root);
    const resolved = normalizeReport(report);
    root.children.replace([
      this.toGroup('Static Checks', resolved.staticChecks),
      this.toGroup('Dynamic Checks', resolved.dynamicChecks),
      this.toGroup('Semantic Checks', resolved.semanticChecks),
    ]);
  }

  private toGroup(label: string, checks: EvaluationCheck[]): vscode.TestItem {
    const group = this.controller.createTestItem(label, label);
    for (const check of checks) {
      const item = this.controller.createTestItem(check.id, check.label);
      item.error = check.status === 'failed' ? check.detail : undefined;
      item.description = check.detail.split(/\r?\n/, 1)[0].slice(0, 200);
      this.checksByItem.set(item, check);
      group.children.add(item);
    }
    return group;
  }

  /** Re-read and evaluate selected files. A displayed report is never a new test run. */
  private async runPublishedChecks(request: vscode.TestRunRequest, token?: vscode.CancellationToken): Promise<void> {
    const run = this.controller.createTestRun(request);
    try {
      for (const root of this.collectionItems(this.controller.items)) {
        if (token?.isCancellationRequested) break;
        const include = request.include
          ? request.include.flatMap(item => this.itemPath(root, item) ?? []) : [JSON.stringify([root.id])];
        const exclude = (request.exclude ?? []).flatMap(item => this.itemPath(root, item) ?? []);
        if (include.length === 0 || exclude.includes(JSON.stringify([root.id]))) continue;
        if (!root.uri || typeof this.verificationRuntime?.evaluateFile !== 'function') {
          run.skipped(root);
          continue;
        }
        this.executeItemTree(root, [root.id], include, exclude, token, run, true);
        run.started(root);
        try {
          const report = await this.verificationRuntime.evaluateFile(root.uri);
          if (token?.isCancellationRequested) break;
          this.publishReport(report, root.uri);
          this.executeItemTree(root, [root.id], include, exclude, token, run);
        } catch (error) {
          run.errored(root, new vscode.TestMessage('Trainer could not run this file. Check the model connection and retry evaluation.'));
          this.verificationRuntime.outputChannel.appendLine(`[trainer-tests] ${error instanceof Error ? error.name : 'Verification failed'}`);
        }
      }
    } finally {
      run.end();
    }
    // /evaluate/current-file records only its own, card-bound verification.
    // Replaying display checks must never attest against a newly selected card.
  }

  private itemPath(root: vscode.TestItem, target: vscode.TestItem, parent: string[] = []): string[] | undefined {
    const path = [...parent, root.id];
    if (root === target) return [JSON.stringify(path)];
    for (const child of this.collectionItems(root.children)) {
      const result = this.itemPath(child, target, path);
      if (result) return result;
    }
    return undefined;
  }

  private executeItemTree(
    item: vscode.TestItem, path: string[], include: string[], exclude: string[],
    token: vscode.CancellationToken | undefined, run: vscode.TestRun, queueOnly = false,
  ): void {
    const isPrefix = (encoded: string, ancestor: boolean): boolean => {
      const selected = JSON.parse(encoded) as string[];
      const prefix = ancestor ? selected : path;
      const full = ancestor ? path : selected;
      return prefix.every((id, index) => full[index] === id);
    };
    if (token?.isCancellationRequested || exclude.some(encoded => isPrefix(encoded, true))
      || !include.some(encoded => isPrefix(encoded, true) || isPrefix(encoded, false))) return;
    const children = this.collectionItems(item.children);
    if (children.length > 0) {
      for (const child of children) this.executeItemTree(child, [...path, child.id], include, exclude, token, run, queueOnly);
      return;
    }
    const check = this.checksByItem.get(item);
    if (!check) return;
    if (queueOnly) {
      run.enqueued(item);
      return;
    }
    if (!['passed', 'failed'].includes(check.status)) {
      run.skipped(item);
    } else if (check.status === 'failed') {
      run.failed(item, new vscode.TestMessage(check.detail || `${check.label} failed`));
    } else {
      run.passed(item);
    }
  }

  private collectionItems(collection: vscode.TestItemCollection): vscode.TestItem[] {
    const items: vscode.TestItem[] = [];
    collection.forEach(item => items.push(item));
    return items;
  }

  public dispose(): void { this.controller.dispose(); }
}

type EvaluationCheck = { id: string; label: string; status: string; detail: string };
function normalizeReport(report: unknown) {
  const record = report && typeof report === 'object' ? report as Record<string, unknown> : {};
  return { staticChecks: normalizeChecks(record.static_checks ?? record.staticChecks),
    dynamicChecks: normalizeChecks(record.dynamic_checks ?? record.dynamicChecks),
    semanticChecks: normalizeChecks(record.semantic_checks ?? record.semanticChecks) };
}
function normalizeChecks(value: unknown): EvaluationCheck[] {
  if (!Array.isArray(value)) return [];
  return value.map((item, index) => {
    const record = item && typeof item === 'object' ? item as Record<string, unknown> : {};
    return { id: typeof record.id === 'string' ? record.id : `check-${index + 1}`,
      label: typeof record.label === 'string' ? record.label : `Check ${index + 1}`,
      status: typeof record.status === 'string' ? record.status : 'warning',
      detail: typeof record.detail === 'string' ? record.detail : '' };
  });
}
