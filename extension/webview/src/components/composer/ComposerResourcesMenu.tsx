import type { ComposerLanguage, ResourceRecord } from "../../lib/types";
import type { Copy } from "../../lib/i18n/copyTypes";
import { FolderIcon, LinkIcon, UploadIcon } from "../icons";

export type ComposerUploadPayloadMode = "files" | "folder" | "url";

export interface ComposerUploadInputRefs {
  filesInputRef: { current: HTMLInputElement | null };
  folderInputRef: { current: HTMLInputElement | null };
}

type ResourceChip = Pick<ResourceRecord, "id" | "title" | "status">;

export interface ComposerResourcesMenuProps {
  copy: Copy;
  composerLanguage: ComposerLanguage;
  /** 本地化辅助 (appUiCopy)：与 App 内同一实现，保持文案行为不变。 */
  localize: (language: ComposerLanguage, text: string) => string;
  resources: ResourceChip[];
  isBrowserPreview: boolean;
  uploadInputRefs: ComposerUploadInputRefs;
  uploadLimit: number;
  onTriggerUpload: (options: {
    browserPreview: boolean;
    payloadMode: ComposerUploadPayloadMode;
    folder?: boolean;
    filesInputRef: { current: HTMLInputElement | null };
    folderInputRef: { current: HTMLInputElement | null };
  }) => void;
}

const MAX_VISIBLE_RESOURCE_CHIPS = 6;

/**
 * Composer 的“添加资料”菜单面板 (P2 模块化第一块，自 App.tsx 迁出)。
 * 纯展示切片：无内部状态，行为与迁出前逐字节一致。
 */
export function ComposerResourcesMenu({
  copy,
  composerLanguage,
  localize,
  resources,
  isBrowserPreview,
  uploadInputRefs,
  uploadLimit,
  onTriggerUpload,
}: ComposerResourcesMenuProps) {
  const upload = (payloadMode: ComposerUploadPayloadMode, folder?: boolean) =>
    onTriggerUpload({
      browserPreview: isBrowserPreview,
      payloadMode,
      folder,
      filesInputRef: uploadInputRefs.filesInputRef,
      folderInputRef: uploadInputRefs.folderInputRef,
    });

  return (
    <section className="composer-menu-panel composer-menu-panel--resources">
      <div className="composer-menu-panel__header">
        <span className="eyebrow">{copy.resourcesMenu}</span>
        <strong>
          {resources.length > 0
            ? localize(composerLanguage, "这次会附带 {n} 份资料")
                .replace("{n}", String(resources.length))
                .replace("{s}", resources.length === 1 ? "" : "s")
            : copy.resourcesEmpty}
        </strong>
      </div>
      <div className="composer-menu-panel__section">
        <div className="menu-list is-compact">
          <button className="menu-list__item" type="button" onClick={() => upload("files")}>
            <span className="menu-list__icon" aria-hidden="true">
              <UploadIcon size={14} />
            </span>
            <span className="menu-list__body">
              <strong>{copy.addFiles}</strong>
            </span>
          </button>
          <button className="menu-list__item" type="button" onClick={() => upload("folder", true)}>
            <span className="menu-list__icon" aria-hidden="true">
              <FolderIcon size={14} />
            </span>
            <span className="menu-list__body">
              <strong>{copy.addFolder}</strong>
            </span>
          </button>
          {!isBrowserPreview ? (
            <button className="menu-list__item" type="button" onClick={() => upload("url")}>
              <span className="menu-list__icon" aria-hidden="true">
                <LinkIcon size={14} />
              </span>
              <span className="menu-list__body">
                <strong>{copy.addUrl}</strong>
              </span>
            </button>
          ) : null}
        </div>
        {resources.length >= uploadLimit ? (
          <p className="composer-menu-panel__hint">{copy.maxFilesHint}</p>
        ) : null}
      </div>
      {resources.length > 0 ? (
        <div className="composer-menu-panel__section">
          <p className="composer-menu-panel__hint">
            {localize(composerLanguage, "这些资料会和当前消息一起发给教练参考。")}
          </p>
          <div className="composer-resource-list">
            {resources.slice(0, MAX_VISIBLE_RESOURCE_CHIPS).map((resource) => (
              <div
                key={resource.id}
                className="composer-resource-chip"
                title={[resource.title, resource.status].filter(Boolean).join(" · ")}
              >
                <strong>{resource.title}</strong>
                <span>{resource.status}</span>
              </div>
            ))}
          </div>
          {resources.length > MAX_VISIBLE_RESOURCE_CHIPS ? (
            <p className="composer-menu-panel__hint">
              {localize(composerLanguage, "另外还有 {n} 份资料会一起带上。").replace(
                "{n}",
                String(resources.length - MAX_VISIBLE_RESOURCE_CHIPS),
              )}
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
