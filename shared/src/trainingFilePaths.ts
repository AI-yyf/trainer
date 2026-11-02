/**
 * Training-card file targeting helpers.
 *
 * Cards are authored by a model and frequently wrap paths in Markdown
 * backticks (`src/queue_lock.py`) or name only the leaf file. The host must
 * resolve those claims against the real editor without guessing a different
 * file. These helpers stay pure so both the extension host and tests can use
 * the same rules.
 */

export function normalizeTrainingFilePath(value: string): string {
  return value
    .trim()
    .replace(/^[`'"]+/, "")
    .replace(/[`'"]+$/, "")
    .replace(/\\/g, "/")
    .replace(/^\.\//, "")
    .replace(/\/+/g, "/")
    .trim();
}

export function normalizeFsPathForMatch(value: string): string {
  const normalized = value.replace(/\\/g, "/").replace(/\/+$/, "");
  return /^(?:[a-z]:|\/\/)/i.test(normalized) ? normalized.toLowerCase() : normalized;
}

function isAbsoluteFsPath(value: string): boolean {
  return /^(?:[a-zA-Z]:[\\/]|\/|\\\\)/.test(value);
}

export interface TrainingFileEditorMatchInput {
  filePath: string;
  editorPath: string;
  workspaceFolder?: string;
}

/**
 * Match a card path against the active editor.
 *
 * - Exact absolute / workspace-relative paths win.
 * - A leaf-only card path (`queue_lock.py`) matches a nested editor path
 *   (`.../src/queue_lock.py`) because the user already opened that file.
 * - Any other mismatch returns false; callers must not silently verify a
 *   different file.
 */
export function trainingFileMatchesEditorPath(
  input: TrainingFileEditorMatchInput,
): boolean {
  const file = normalizeTrainingFilePath(input.filePath);
  if (!file) {
    return false;
  }
  const editor = normalizeFsPathForMatch(input.editorPath);
  const workspace = input.workspaceFolder
    ? normalizeFsPathForMatch(input.workspaceFolder)
    : "";
  if (workspace && editor !== workspace && !editor.startsWith(`${workspace}/`)) {
    return false;
  }
  if (!workspace && !isAbsoluteFsPath(file)) {
    // Without a managed workspace the host cannot prove containment; never
    // match a relative/leaf card path by suffix alone.
    return false;
  }
  const absolute = isAbsoluteFsPath(file)
    ? normalizeFsPathForMatch(file)
    : input.workspaceFolder
      ? normalizeFsPathForMatch(
          `${input.workspaceFolder.replace(/[\\/]+$/, "")}/${file}`,
        )
      : normalizeFsPathForMatch(file);
  if (editor === absolute) {
    return true;
  }
  if (file.startsWith("/")) {
    return false;
  }
  return editor.endsWith(`/${file}`);
}
