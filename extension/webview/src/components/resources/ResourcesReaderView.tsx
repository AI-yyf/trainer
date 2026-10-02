import { useEffect, useRef, useState } from "react";
import { resolveResourceOpenTarget } from "../../../../../shared/src/resourceOpen";
import { SearchIcon, UploadIcon, FolderIcon, ChevronLeftIcon, ArrowRightIcon } from "../icons";
import { resolveCopy } from "../../lib/i18n/copy";
import { resourceFolderEntries, resourceFolderSegments } from "../../lib/resourceLibraryFolders";
import { ResourceLibraryIcon } from "./ResourceLibraryIcon";
import { TrainerSpinner } from "../common/TrainerSpinner";
import {
  compactResourceSearchPlaceholder,
  resourceLibraryText,
  type ResourcesWorkbenchViewProps,
} from "./ResourcesWorkbenchView";

/** The library is a reading entry point; source management stays out of this surface. */
export function ResourcesReaderView({
  language, resources, resourceSearch, resourceWriteAccess,
  onImportFiles, onImportFolder, onOpenResource, onSearchResources, onSearchQueryChange,
  onDebugVisibleFacts,
}: ResourcesWorkbenchViewProps) {
  const [query, setQuery] = useState("");
  const [requestId, setRequestId] = useState<string>();
  const [failed, setFailed] = useState(false);
  const [folder, setFolder] = useState<string[]>([]);
  const copy = resolveCopy(language);
  const searchRef = useRef(onSearchResources);
  searchRef.current = onSearchResources;
  const normalizedQuery = query.trim();
  const workspaceId = resourceSearch?.workspaceId;
  useEffect(() => {
    setFailed(false);
    setRequestId(undefined);
    if (!normalizedQuery || !searchRef.current) return;
    let live = true;
    const timer = window.setTimeout(() => {
      const id = `resource-reader-${crypto.randomUUID()}`;
      setRequestId(id);
      void Promise.resolve().then(() => searchRef.current?.({ query: normalizedQuery, requestId: id }))
        .catch(() => { if (live) setFailed(true); });
    }, 250);
    return () => { live = false; window.clearTimeout(timer); };
  }, [normalizedQuery, workspaceId]);
  useEffect(() => {
    onDebugVisibleFacts?.({ surface: "resources", activeView: "resources",
      activeSurface: "library", compactMode: true, singleWorkbenchSurface: true,
      resourceDetailVisible: false, detailPaneVisible: false,
      sandboxPaneVisible: false, previewPaneVisible: false });
  }, [onDebugVisibleFacts]);
  const searchMatches = Boolean(normalizedQuery && requestId &&
    resourceSearch?.requestId === requestId && resourceSearch.query.trim() === normalizedQuery);
  const pending = Boolean(normalizedQuery && onSearchResources && !searchMatches && !failed);
  const filtered = normalizedQuery
    ? resources.filter(resource => `${resource.title} ${resource.collectionPath ?? ""} ${resource.source ?? ""} ${resource.summary ?? ""}`
      .toLocaleLowerCase().includes(normalizedQuery.toLocaleLowerCase()))
    : resources;
  const entries = resourceFolderEntries(resources, folder);
  const visibleResources = normalizedQuery ? searchMatches ? resourceSearch?.hits ?? [] : filtered : entries.files;
  useEffect(() => {
    if (folder.length && !resources.some(resource => folder.every((segment, index) => resourceFolderSegments(resource)[index] === segment))) {
      setFolder([]);
    }
  }, [folder, resources]);
  const t = (key: Parameters<typeof resourceLibraryText>[1]) => resourceLibraryText(language, key);
  return (
    <section className="workbench-pane resources-pane resources-reader" aria-label={t("title")}>
      <div className="resources-reader__toolbar">
        <label className="resources-search resources-reader__search">
          <SearchIcon size={14} aria-hidden="true" />
          <input type="search" value={query} placeholder={compactResourceSearchPlaceholder[language]}
            aria-label={compactResourceSearchPlaceholder[language]}
            onChange={event => { setQuery(event.target.value); onSearchQueryChange?.(event.target.value); }} />
        </label>
        <button className="button button--ghost" type="button"
          disabled={!onImportFiles || resourceWriteAccess?.allowed === false}
          title={resourceWriteAccess?.reason} onClick={onImportFiles} aria-label={t("addResource")}>
          <UploadIcon size={14} /><span>{t("addResource")}</span>
        </button>
        <button className="button button--ghost resources-reader__import-folder" type="button"
          disabled={!onImportFolder || resourceWriteAccess?.allowed === false}
          title={resourceWriteAccess?.reason || copy.addFolder} aria-label={copy.addFolder} onClick={onImportFolder}>
          <FolderIcon size={17} aria-hidden="true" />
          <span aria-hidden="true">+</span>
        </button>
      </div>
      {!normalizedQuery && folder.length ? <nav className="resources-reader__breadcrumb" aria-label={t("title")}>
        <button type="button" onClick={() => setFolder(folder.slice(0, -1))} aria-label={copy.back} title={copy.back}>
          <ChevronLeftIcon size={15} />
        </button>
        <button type="button" onClick={() => setFolder([])}>{t("title")}</button>
        {folder.map((segment, index) => <span key={folder.slice(0, index + 1).join("/")}>
          <span aria-hidden="true">/</span>
          <button type="button" aria-current={index === folder.length - 1 ? "page" : undefined}
            onClick={() => setFolder(folder.slice(0, index + 1))}>{segment}</button>
        </span>)}
      </nav> : null}
      {pending ? <div className="resources-reader__pending" role="status"><TrainerSpinner label={t("searching")} size="sm" /></div> : null}
      {failed ? <p role="alert">{t("searchFailed")}</p> : null}
      <ul className="resources-reader__list" aria-label={t("title")}>
        {!normalizedQuery ? entries.folders.map(name => <li key={`folder:${name}`}>
          <button className="resources-reader__item resources-reader__item--folder" type="button"
            onClick={() => setFolder([...folder, name])} title={name} data-library-folder={name}>
            <span className="resources-reader__icon"><ResourceLibraryIcon kind="folder" /></span>
            <span>{name}</span><ArrowRightIcon size={14} aria-hidden="true" />
          </button>
        </li>) : null}
        {visibleResources.map(resource => {
          const target = resolveResourceOpenTarget(resource);
          return <li key={resource.id}>
            <button className="resources-reader__item" type="button"
              disabled={!onOpenResource || target.kind === "unavailable"}
              onClick={() => onOpenResource?.(resource.id)} title={resource.title}>
              <span className="resources-reader__icon"><ResourceLibraryIcon kind={resource.kind} /></span>
              <span>{resource.title}{normalizedQuery && resource.collectionPath ?
                <small className="resources-reader__path">{resource.collectionPath}</small> : null}</span>
              <ArrowRightIcon size={14} aria-hidden="true" />
            </button>
          </li>;
        })}
      </ul>
      {!visibleResources.length && (normalizedQuery || !entries.folders.length) && !pending ? <p className="resources-reader__empty">
        {normalizedQuery ? t("noMatches") : t("emptyTitle")}
      </p> : null}
    </section>
  );
}
