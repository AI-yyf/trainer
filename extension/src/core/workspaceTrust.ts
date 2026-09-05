import * as vscode from 'vscode';
import * as fs from 'node:fs';
import * as path from 'node:path';
import {
  resolveWorkspaceFolderPathForFile,
  resolveWorkspaceFolderPathForKnownFiles,
} from './workspaceRoots';

type WorkspaceTrustLanguage =
  | 'zh-CN'
  | 'en-US'
  | 'es-ES'
  | 'fr-FR'
  | 'de-DE'
  | 'ja-JP'
  | 'ko-KR'
  | 'pt-BR';

const workspaceTrustCopy: Record<
  WorkspaceTrustLanguage,
  { message: string; action: string }
> = {
  'zh-CN': {
    message: '要继续使用 Trainer，请先信任当前工作区。',
    action: '管理工作区信任',
  },
  'en-US': {
    message: 'Trust this workspace before continuing with Trainer.',
    action: 'Manage Workspace Trust',
  },
  'es-ES': {
    message: 'Confia en este espacio de trabajo antes de continuar con Trainer.',
    action: 'Administrar confianza del espacio',
  },
  'fr-FR': {
    message: 'Approuvez cet espace de travail avant de continuer avec Trainer.',
    action: 'Gérer la confiance de l’espace',
  },
  'de-DE': {
    message: 'Vertrauen Sie diesem Arbeitsbereich, bevor Sie mit Trainer fortfahren.',
    action: 'Arbeitsbereichsvertrauen verwalten',
  },
  'ja-JP': {
    message: 'Trainer を続ける前に、このワークスペースを信頼してください。',
    action: 'ワークスペースの信頼を管理',
  },
  'ko-KR': {
    message: 'Trainer를 계속 사용하려면 이 작업 공간을 신뢰하세요.',
    action: '작업 공간 신뢰 관리',
  },
  'pt-BR': {
    message: 'Confie neste espaço de trabalho antes de continuar com o Trainer.',
    action: 'Gerenciar confiança do espaço',
  },
};

function resolveWorkspaceTrustLanguage(): WorkspaceTrustLanguage {
  const language = vscode.env?.language?.trim().toLowerCase();
  if (language?.startsWith('en')) {
    return 'en-US';
  }
  if (language?.startsWith('es')) {
    return 'es-ES';
  }
  if (language?.startsWith('fr')) {
    return 'fr-FR';
  }
  if (language?.startsWith('de')) {
    return 'de-DE';
  }
  if (language?.startsWith('ja')) {
    return 'ja-JP';
  }
  if (language?.startsWith('ko')) {
    return 'ko-KR';
  }
  if (language?.startsWith('pt')) {
    return 'pt-BR';
  }
  return 'zh-CN';
}

export class WorkspaceTrustGuard {
  private readonly recentFiles: string[] = [];
  private readonly recentEditedFiles: string[] = [];

  async ensureTrusted(_reason: string): Promise<boolean> {
    if (vscode.workspace.isTrusted) {
      return true;
    }

    const copy = workspaceTrustCopy[resolveWorkspaceTrustLanguage()];
    const selection = await vscode.window.showWarningMessage(
      copy.message,
      copy.action,
    );

    if (selection) {
      await vscode.commands.executeCommand('workbench.trust.manage');
    }

    return vscode.workspace.isTrusted;
  }

  rememberActiveEditor(editor: vscode.TextEditor | undefined = vscode.window.activeTextEditor): void {
    const path = editor?.document.uri.fsPath;
    if (!path) {
      return;
    }
    this.rememberPath(this.recentFiles, path);
  }

  rememberDocumentEdit(document: vscode.TextDocument): void {
    const path = document.uri.fsPath;
    if (!path) {
      return;
    }
    this.rememberPath(this.recentEditedFiles, path);
    this.rememberPath(this.recentFiles, path);
  }

  getSnapshot(): {
    trusted: boolean;
    workspaceFolder?: string;
    activeWorkspaceRoot?: string;
    activeFile?: string;
    activeLanguageId?: string;
    remoteName?: string;
    isRemoteWorkspace?: boolean;
    selectionRange?: string;
    selectionText?: string;
    diagnosticErrors?: number;
    diagnosticWarnings?: number;
    documentVersion?: number;
    recentFiles?: string[];
    recentEditedFiles?: string[];
    relatedFiles?: string[];
  } {
    const workspaceFolders = vscode.workspace.workspaceFolders ?? [];
    const editor = vscode.window.activeTextEditor;
    const document = editor?.document;
    const activeFile = document?.uri.fsPath;
    this.rememberActiveEditor(editor);
    const selection = editor?.selection;
    const selectionText =
      document && selection && !selection.isEmpty ? document.getText(selection) : undefined;
    const diagnostics = document ? vscode.languages.getDiagnostics(document.uri) : [];
    const diagnosticErrors = diagnostics.filter(
      (item) => item.severity === vscode.DiagnosticSeverity.Error,
    ).length;
    const diagnosticWarnings = diagnostics.filter(
      (item) => item.severity === vscode.DiagnosticSeverity.Warning,
    ).length;
    const selectionRange =
      selection && !selection.isEmpty
        ? `${selection.start.line + 1}:${selection.start.character + 1}-${selection.end.line + 1}:${selection.end.character + 1}`
        : undefined;
    const activeWorkspaceRoot =
      resolveWorkspaceFolderPathForFile(activeFile) ??
      resolveWorkspaceFolderPathForKnownFiles(this.recentFiles);
    const remoteName = vscode.env?.remoteName?.trim() || undefined;
    const workspaceFolder = activeWorkspaceRoot ?? (workspaceFolders.length === 1
      ? workspaceFolders[0]?.uri.fsPath
      : undefined);

    return {
      trusted: vscode.workspace.isTrusted,
      workspaceFolder,
      activeWorkspaceRoot,
      activeFile,
      activeLanguageId: document?.languageId,
      remoteName,
      isRemoteWorkspace: Boolean(remoteName),
      selectionRange,
      selectionText,
      diagnosticErrors,
      diagnosticWarnings,
      documentVersion: document?.version,
      recentFiles: [...this.recentFiles],
      recentEditedFiles: [...this.recentEditedFiles],
      relatedFiles: document ? this.resolveRelatedFiles(document) : [],
    };
  }

  private rememberPath(target: string[], path: string): void {
    const next = path.trim();
    if (!next) {
      return;
    }
    const existingIndex = target.indexOf(next);
    if (existingIndex >= 0) {
      target.splice(existingIndex, 1);
    }
    target.unshift(next);
    if (target.length > 5) {
      target.length = 5;
    }
  }

  private resolveRelatedFiles(document: vscode.TextDocument): string[] {
    const baseDir = path.dirname(document.uri.fsPath);
    const matches = new Set<string>();

    for (const specifier of this.extractImportReferences(document.getText(), document.languageId)) {
      const resolved = this.resolveImportReference(baseDir, document.languageId, specifier);
      if (resolved && resolved !== document.uri.fsPath) {
        matches.add(resolved);
      }
    }

    return Array.from(matches).slice(0, 4);
  }

  private extractImportReferences(content: string, languageId: string): string[] {
    const results: string[] = [];
    const push = (specifier: string) => {
      if (specifier.startsWith('.')) {
        results.push(specifier);
      }
    };

    if (languageId === 'python') {
      for (const match of content.matchAll(/^\s*from\s+([.\w]+)\s+import\s+/gm)) {
        push(match[1]);
      }
      return results;
    }

    for (const match of content.matchAll(/from\s+["']([^"']+)["']/g)) {
      push(match[1]);
    }
    for (const match of content.matchAll(/import\s*\(\s*["']([^"']+)["']\s*\)/g)) {
      push(match[1]);
    }
    return results;
  }

  private resolveImportReference(
    baseDir: string,
    languageId: string,
    specifier: string,
  ): string | undefined {
    const candidateBases =
      languageId === 'python'
        ? this.resolvePythonSpecifier(baseDir, specifier)
        : [path.resolve(baseDir, specifier)];

    const extensions =
      languageId === 'python'
        ? ['.py', path.sep + '__init__.py']
        : ['', '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.json', path.sep + 'index.ts', path.sep + 'index.tsx', path.sep + 'index.js'];

    for (const candidateBase of candidateBases) {
      for (const extension of extensions) {
        const candidatePath = `${candidateBase}${extension}`;
        if (fs.existsSync(candidatePath) && fs.statSync(candidatePath).isFile()) {
          return candidatePath;
        }
      }
    }

    return undefined;
  }

  private resolvePythonSpecifier(baseDir: string, specifier: string): string[] {
    const leadingDots = specifier.match(/^\.+/)?.[0].length ?? 0;
    const remainder = specifier.slice(leadingDots).replace(/\./g, path.sep);
    let resolvedBase = baseDir;
    for (let index = 1; index < leadingDots; index += 1) {
      resolvedBase = path.dirname(resolvedBase);
    }
    return [path.resolve(resolvedBase, remainder)];
  }
}
