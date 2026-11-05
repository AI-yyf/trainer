import type { Copy } from "../../lib/i18n/copyTypes";
import { MenuList, MenuToggleRow } from "../../app/appHelpers";

export type ComposerContextDetail = "focused" | "balanced" | "full";

export interface ComposerContextMenuProps {
  copy: Copy;
  /** sendContextShortSummary(data, layout, t) 的结果；空串表示无摘要。 */
  contextSummary: string;
  relatedFilesCount: number;
  includeRelatedFiles: boolean;
  followCurrentFile: boolean;
  contextDetail: ComposerContextDetail;
  onToggleRelatedFiles: () => void;
  onToggleFollowCurrentFile: () => void;
  onContextDetailChange: (detail: ComposerContextDetail) => void;
}

/**
 * Composer 的“当前上下文”菜单面板 (P2 模块化第三块，自 App.tsx 迁出)。
 * 纯展示切片：相关文件/跟随开关 + 上下文详略档位，无内部状态，
 * 行为与迁出前一致。
 */
export function ComposerContextMenu({
  copy,
  contextSummary,
  relatedFilesCount,
  includeRelatedFiles,
  followCurrentFile,
  contextDetail,
  onToggleRelatedFiles,
  onToggleFollowCurrentFile,
  onContextDetailChange,
}: ComposerContextMenuProps) {
  return (
    <section className="composer-menu-panel">
      <div className="composer-menu-panel__header">
        <span className="eyebrow">{copy.currentContext}</span>
        {contextSummary ? <strong>{contextSummary}</strong> : null}
      </div>
      <div className="composer-menu-panel__section">
        <MenuToggleRow
          label={copy.relatedFiles}
          value={
            includeRelatedFiles
              ? relatedFilesCount > 0
                ? String(relatedFilesCount)
                : copy.on
              : copy.off
          }
          active={includeRelatedFiles}
          onClick={onToggleRelatedFiles}
        />
        <MenuToggleRow
          label={copy.follow}
          value={followCurrentFile ? copy.on : copy.off}
          active={followCurrentFile}
          onClick={onToggleFollowCurrentFile}
        />
      </div>
      <div className="composer-menu-panel__section">
        <span className="eyebrow">{copy.contextDetail}</span>
        <MenuList
          items={[
            {
              label: copy.detailFocused,
              active: contextDetail === "focused",
              onClick: () => onContextDetailChange("focused"),
            },
            {
              label: copy.detailBalanced,
              active: contextDetail === "balanced",
              onClick: () => onContextDetailChange("balanced"),
            },
            {
              label: copy.detailFull,
              active: contextDetail === "full",
              onClick: () => onContextDetailChange("full"),
            },
          ]}
        />
      </div>
      <p className="composer-menu-panel__hint">{copy.contextAutoNote}</p>
    </section>
  );
}
