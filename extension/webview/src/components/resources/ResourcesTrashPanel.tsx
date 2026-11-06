import type { ComposerLanguage, DeletedResource } from "../../lib/types";
import {
  resourceText,
  resourceTextLocaleOverrides,
  type ResourceTextKey,
} from "../../lib/i18n/segments/resourcesInlineText";
import { RefreshIcon, TrashIcon } from "../icons";

/**
 * 资料库「回收站」面板 (P2 模块化，自 ResourcesWorkbenchView 迁出)。
 * 纯展示切片：折叠列表 + 恢复按钮，无内部状态；恢复的派发（pending 管理、
 * 搜索刷新、失败上报）仍由宿主 `onRestore` 承担。
 */

function localize(language: ComposerLanguage, key: ResourceTextKey): string {
  if (language === "zh-CN") {
    return resourceText[key].zh;
  }
  if (language === "en-US") {
    return resourceText[key].en;
  }
  return resourceTextLocaleOverrides[language][key] ?? resourceText[key].en;
}

export function deletedResourceId(resource: DeletedResource): string | undefined {
  return resource.resourceId.trim() || undefined;
}

export function isDeletedResourceRecoverable(resource: DeletedResource): boolean {
  return Boolean(deletedResourceId(resource)) && resource.recoverable;
}

function resourceReadOnlyNotice(language: ComposerLanguage): string {
  return localize(language, "readOnlyNotice");
}

export interface ResourcesTrashPanelProps {
  language: ComposerLanguage;
  /** 已解析的回收站列表（宿主保证 deletedResources ?? []）。 */
  deletedResources: DeletedResource[];
  /** 回收站快照是否已加载（未加载时显示 loading 文案）。 */
  snapshotAvailable: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  isRestorePending: boolean;
  isDeletePending: boolean;
  pendingRestoredResourceIds: string[];
  canWriteResources: boolean;
  writeBlockedReason?: string;
  isBrowserPreview: boolean;
  restoreUnavailableReason?: string;
  /** 宿主是否提供了恢复回调（false 时按钮不渲染）。 */
  restoreAvailable: boolean;
  /** 单个资源恢复派发（宿主 restoreDeletedResource）。 */
  onRestore: (resourceId: string) => void;
}

export function ResourcesTrashPanel({
  language,
  deletedResources,
  snapshotAvailable,
  open,
  onOpenChange,
  isRestorePending,
  isDeletePending,
  pendingRestoredResourceIds,
  canWriteResources,
  writeBlockedReason,
  isBrowserPreview,
  restoreUnavailableReason,
  restoreAvailable,
  onRestore,
}: ResourcesTrashPanelProps) {
  return (
    <details
      className="resources-knowledge__trash resources-library-tree__trash"
      open={open}
      onToggle={(event) => onOpenChange(event.currentTarget.open)}
      aria-busy={isRestorePending}
    >
      <summary>
        <span>
          <TrashIcon size={14} aria-hidden="true" />
          {/* r1-g2-1: one expression — "回收站 (1)" — instead of a title row
              plus a second count sentence on the far edge. */}
          <strong>
            {localize(language, "trashTitle")}
            {snapshotAvailable ? ` (${deletedResources.length})` : ""}
          </strong>
        </span>
      </summary>
      <div className="resources-knowledge__trash-body">
        {!snapshotAvailable ? (
          <p className="resources-empty resources-empty--compact">
            {localize(language, "trashLoading")}
          </p>
        ) : null}
        {snapshotAvailable && deletedResources.length === 0 ? (
          <p className="resources-empty resources-empty--compact">
            {localize(language, "trashEmpty")}
          </p>
        ) : null}
        {snapshotAvailable && deletedResources.length > 0 ? (
          <ul className="resources-knowledge__trash-list">
            {deletedResources.map((resource, index) => {
              const resourceId = deletedResourceId(resource);
              const canRestore = isDeletedResourceRecoverable(resource);
              const restorePendingForItem =
                resourceId !== undefined && pendingRestoredResourceIds.includes(resourceId);
              const restoreLabel = localize(language, "restoreResource");
              const restoreTitle = `${restoreLabel}: ${resource.title}`;
              const restoreDisabledReason = !canWriteResources
                ? writeBlockedReason ?? resourceReadOnlyNotice(language)
                : isBrowserPreview
                  ? localize(language, "browserPreviewMutationNotice")
                  : restoreUnavailableReason;
              return (
                <li key={resourceId ?? `unknown-deleted-resource-${index}`}>
                  <span className="resources-knowledge__trash-item-title" title={resource.title}>
                    {resource.title}
                  </span>
                  {resource.collectionPath ? (
                    <span className="resources-knowledge__trash-item-path" title={resource.collectionPath}>
                      {resource.collectionPath}
                    </span>
                  ) : null}
                  {!canRestore ? (
                    <span className="resources-knowledge__trash-item-status">
                      {localize(language, "notRestorable")}
                    </span>
                  ) : null}
                  {canRestore && restoreAvailable && resourceId ? (
                    <button
                      className="button button--compact resources-knowledge__restore-action"
                      type="button"
                      onClick={() => onRestore(resourceId)}
                      disabled={!canWriteResources || isBrowserPreview || !restoreAvailable || isDeletePending || isRestorePending}
                      aria-busy={restorePendingForItem}
                      aria-label={restoreTitle}
                      title={restoreDisabledReason ?? restoreTitle}
                    >
                      <RefreshIcon size={12} />
                      <span>{restoreLabel}</span>
                    </button>
                  ) : null}
                </li>
              );
            })}
          </ul>
        ) : null}
      </div>
    </details>
  );
}
