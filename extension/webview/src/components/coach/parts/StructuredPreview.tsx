import type { ReactNode } from "react";

import { StructuredTable } from "./StructuredTable";

type StructuredPreviewRecord = Record<string, unknown>;

function asRecord(value: unknown): StructuredPreviewRecord | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as StructuredPreviewRecord)
    : undefined;
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function asNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function asBoolean(value: unknown): boolean | undefined {
  return typeof value === "boolean" ? value : undefined;
}

function asRowMatrix(value: unknown): string[][] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((row) =>
    Array.isArray(row) ? row.map((cell) => String(cell ?? "")) : [String(row ?? "")]
  );
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item ?? "")) : [];
}

function asCellList(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null)
    : [];
}

function asArchiveEntryList(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null)
    : [];
}

function asParagraphs(value: unknown): string[] {
  const text = typeof value === "string" ? value.trim() : "";
  if (!text) {
    return [];
  }
  return text
    .replace(/\r\n/g, "\n")
    .split(/\n{2,}/)
    .map((paragraph) => paragraph.replace(/\s+\n/g, " ").replace(/\n+/g, " ").trim())
    .filter(Boolean)
    .slice(0, 4);
}

function renderTextualStructuredPreview(
  kindLabel: string,
  content: string,
  meta: ReactNode[] = [],
): ReactNode {
  return (
    <div className="structured-preview structured-preview--document">
      <div className="structured-preview__meta">
        <span>{kindLabel}</span>
        {meta}
      </div>
      <div className="structured-preview__document">
        <pre className="structured-preview__code">{content}</pre>
      </div>
    </div>
  );
}

export function renderStructuredPreview(
  structuredData: Record<string, unknown> | undefined,
  fallbackKind: string | undefined,
  fallbackText?: string,
): ReactNode | undefined {
  const data = asRecord(structuredData);
  if (!data) {
    if (fallbackKind !== "document" || !fallbackText?.trim()) {
      return undefined;
    }
    const paragraphs = asParagraphs(fallbackText);
    return (
      <div className="structured-preview structured-preview--document">
        <div className="structured-preview__meta">
          <span>Document</span>
          <span>Converted text</span>
        </div>
        <div className="structured-preview__document">
          {paragraphs.map((paragraph, index) => (
            <p key={`${index}-${paragraph.slice(0, 24)}`}>{paragraph}</p>
          ))}
        </div>
      </div>
    );
  }
  const kind = asString(data.kind) ?? fallbackKind;
  if (kind === "structured-text") {
    const content =
      asString(data.content ?? data.preview ?? data.excerpt ?? data.text ?? data.body) ??
      fallbackText ??
      "";
    const format = asString(data.format) ?? asString(data.language) ?? asString(data.kind);
    const truncated = asBoolean(data.truncated);
    const text = content.trim();
    return renderTextualStructuredPreview("Structured text", text || content, [
      format ? <span key="format">{format.toUpperCase()}</span> : null,
      truncated ? <span key="truncated">Quick preview only</span> : null,
    ].filter(Boolean) as ReactNode[]);
  }
  if (kind === "markup") {
    const content =
      asString(data.content ?? data.preview ?? data.excerpt ?? data.text ?? data.body) ??
      fallbackText ??
      "";
    const format = asString(data.format) ?? asString(data.language) ?? asString(data.kind);
    const truncated = asBoolean(data.truncated);
    const text = content.trim();
    return renderTextualStructuredPreview("Markup", text || content, [
      format ? <span key="format">{format.toUpperCase()}</span> : null,
      truncated ? <span key="truncated">Quick preview only</span> : null,
    ].filter(Boolean) as ReactNode[]);
  }
  if (kind === "document") {
    const content =
      asString(data.content ?? data.preview ?? data.excerpt ?? data.text ?? data.body) ??
      fallbackText ??
      "";
    const paragraphs = asParagraphs(content);
    const format = asString(data.format);
    const pageCount = asNumber(data.pageCount ?? data.page_count);
    const sectionCount = asNumber(data.sectionCount ?? data.section_count);
    const wordCount = asNumber(data.wordCount ?? data.word_count);
    const truncated = asBoolean(data.truncated);
    return (
      <div className="structured-preview structured-preview--document">
        <div className="structured-preview__meta">
          {format ? <span>{format.toUpperCase()}</span> : <span>Document</span>}
          {typeof pageCount === "number" ? <span>{pageCount} pages</span> : null}
          {typeof sectionCount === "number" ? <span>{sectionCount} sections</span> : null}
          {typeof wordCount === "number" ? <span>{wordCount} words</span> : null}
          {truncated ? <span>Quick preview only</span> : null}
        </div>
        <div className="structured-preview__document">
          {paragraphs.length > 0 ? (
            paragraphs.map((paragraph, index) => <p key={`${index}-${paragraph.slice(0, 24)}`}>{paragraph}</p>)
          ) : (
            <p>{content}</p>
          )}
        </div>
      </div>
    );
  }
  if (kind === "table") {
    const columns = asStringArray(data.columns);
    const rows = asRowMatrix(data.rows);
    const truncated = asBoolean(data.truncated);
    const rowCount = asNumber(data.rowCount);
    const columnCount = asNumber(data.columnCount);
    return (
      <div className="structured-preview structured-preview--table">
        <StructuredTable
          columns={columns}
          rows={rows}
          rowCount={rowCount}
          columnCount={columnCount}
          truncated={truncated}
        />
      </div>
    );
  }

  if (kind === "notebook") {
    const cells = asCellList(data.cells);
    const kernel = asString(data.kernel);
    const cellCount = asNumber(data.cellCount);
    const truncated = asBoolean(data.truncated);
    return (
      <div className="structured-preview structured-preview--notebook">
        <div className="structured-preview__meta">
          {kernel ? <span>{kernel}</span> : null}
          {typeof cellCount === "number" ? <span>{cellCount} cells</span> : null}
          {truncated ? <span>Quick preview only</span> : null}
        </div>
        <div className="structured-preview__notebook-list">
          {cells.map((cell, index) => {
            const cellType = asString(cell.cellType) ?? "cell";
            const source = asStringArray(cell.source);
            const outputs = asStringArray(cell.outputs);
            return (
              <section key={`${cellType}-${index}`} className="structured-preview__notebook-cell">
                <div className="structured-preview__notebook-cell-head">
                  <span className="eyebrow">{cellType}</span>
                  <span>#{typeof cell.index === "number" ? cell.index + 1 : index + 1}</span>
                </div>
                {source.length > 0 ? (
                  <pre className="structured-preview__code">{source.join("\n")}</pre>
                ) : null}
                {outputs.length > 0 ? (
                  <div className="structured-preview__outputs">
                    {outputs.map((output, outputIndex) => (
                      <pre key={outputIndex} className="structured-preview__output">
                        {output}
                      </pre>
                    ))}
                  </div>
                ) : null}
              </section>
            );
          })}
        </div>
      </div>
    );
  }

  if (kind === "archive") {
    const entries = asArchiveEntryList(data.previewEntries ?? data.entries);
    const format = asString(data.format);
    const entryCount = asNumber(data.entryCount);
    const truncated = asBoolean(data.truncated);
    return (
      <div className="structured-preview structured-preview--archive">
        <div className="structured-preview__meta">
          {format ? <span>{format.toUpperCase()}</span> : null}
          {typeof entryCount === "number" ? <span>{entryCount} entries</span> : null}
          {truncated ? <span>Quick preview only</span> : null}
        </div>
        <div className="structured-preview__notebook-list">
          {entries.map((entry, index) => {
            const name = asString(entry.path ?? entry.name) ?? `entry-${index + 1}`;
            const kindLabel = asString(entry.kind) ?? asString(entry.entry_kind) ?? "file";
            const sizeBytes = asNumber(entry.sizeBytes ?? entry.size);
            const linkTarget = asString(entry.linkTarget ?? entry.link_target);
            const snippet = asString(entry.preview ?? entry.snippet);
            return (
              <section key={`${name}-${index}`} className="structured-preview__notebook-cell">
                <div className="structured-preview__notebook-cell-head">
                  <span className="eyebrow">{kindLabel}</span>
                  {typeof sizeBytes === "number" ? <span>{sizeBytes} bytes</span> : null}
                </div>
                <div className="structured-preview__meta">
                  <span>{name}</span>
                  {linkTarget ? <span>{linkTarget}</span> : null}
                </div>
                {snippet ? <pre className="structured-preview__code">{snippet}</pre> : null}
              </section>
            );
          })}
        </div>
      </div>
    );
  }

  return undefined;
}
