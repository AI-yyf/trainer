'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const resourcesWorkbenchPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'resources',
  'ResourcesWorkbenchView.tsx',
);
const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const stylesPath = path.resolve(__dirname, '..', 'webview', 'src', 'styles.css');
const typesPath = path.resolve(__dirname, '..', 'webview', 'src', 'lib', 'types.ts');

test('Resources uses real knowledge records and opens them through the existing native VS Code action', () => {
  const viewSource = fs.readFileSync(resourcesWorkbenchPath, 'utf8');
  const appSource = fs.readFileSync(appPath, 'utf8');
  const typesSource = fs.readFileSync(typesPath, 'utf8');

  assert.match(viewSource, /resources: ResourceRecord\[\];/);
  assert.match(viewSource, /onImportFiles\?: \(\) => void;/);
  assert.match(viewSource, /onImportFolder\?: \(\) => void;/);
  assert.match(viewSource, /onImportUrl\?: \(\) => void;/);
  assert.match(viewSource, /onOpenResource\?: \(resourceId: string\) => void;/);
  assert.match(viewSource, /onRefreshResources\?: \(\) => void \| Promise<void>;/);
  assert.match(viewSource, /pendingIndex: \{ zh: "\\u5f85\\u7d22\\u5f15", en: "Waiting to be indexed" \}/);
  assert.match(viewSource, /resource\.indexState === "pending"/);
  assert.match(viewSource, /tone: "pending"/);
  assert.match(viewSource, /DeletedResource,/);
  assert.match(viewSource, /export type \{ DeletedResource \} from "\.\.\/\.\.\/lib\/types";/);
  assert.match(typesSource, /export interface DeletedResource/);
  assert.match(typesSource, /resourceId: string;/);
  assert.match(typesSource, /recoverable: boolean;/);
  assert.match(viewSource, /deletedResources\?: DeletedResource\[\];/);
  assert.match(viewSource, /onDeleteResources\?: \(resourceIds: string\[\]\) => void \| Promise<void>;/);
  assert.match(viewSource, /onRestoreResources\?: \(resourceIds: string\[\]\) => void \| Promise<void>;/);
  assert.match(viewSource, /onRefreshDeletedResources\?: \(\) => void \| Promise<void>;/);
  assert.match(viewSource, /onImportFiles/);
  assert.match(viewSource, /onImportFolder/);
  assert.match(viewSource, /onImportUrl/);
  assert.match(viewSource, /const openResourceInVsCode = \(resource: ResourceRecord\) =>/);
  assert.match(viewSource, /onOpenResource\?\.\(resource\.id\)/);
  assert.match(viewSource, /onClick=\{\(\) => openResourceInVsCode\(selectedResource\)\}/);
  assert.match(viewSource, /function buildResourceTree\(/);
  assert.match(viewSource, /sandboxState\?\.nodes/);
  assert.match(viewSource, /function isRelativeFilePath\(/);
  assert.match(viewSource, /function trimHiddenCollectionRoots\(/);
  assert.match(viewSource, /function filterResourceTree\(/);
  assert.match(viewSource, /function findResourceAncestorCollectionIds\(/);
  assert.match(viewSource, /const visibleResourceTree = useMemo/);
  assert.match(viewSource, /const selectedResourceAncestorIds = useMemo/);
  assert.match(viewSource, /const renderedExpandedCollectionIds = useMemo/);
  assert.match(viewSource, /role="tree"/);
  assert.match(viewSource, /onSelect=\{selectResource\}/);
  assert.match(viewSource, /onOpen=\{openResourceInVsCode\}/);

  assert.match(appSource, /<ResourcesWorkbenchView[\s\S]*?resources=\{liveResources\}/);
  assert.match(appSource, /<ResourcesWorkbenchView[\s\S]*?deletedResources=\{data\.deletedResources\}/);
  assert.match(appSource, /onRefreshDeletedResources=/);
  assert.match(appSource, /onImportFiles=\{\(\) =>/);
  assert.match(appSource, /payloadMode: "files",/);
  assert.match(appSource, /onImportFolder=\{\(\) =>/);
  assert.match(appSource, /payloadMode: "folder",/);
  assert.match(appSource, /onImportUrl=\{\(\) =>/);
  assert.match(appSource, /payloadMode: "url",/);
  assert.match(appSource, /type: "resource\/open",/);
  assert.match(appSource, /commandId: trainerCommands\.indexResources,/);
  assert.match(appSource, /const requestResourceMutation = useCallback/);
  assert.match(appSource, /commandId:\s*kind === "delete" \? trainerCommands\.deleteResource : trainerCommands\.restoreResource/);
  assert.match(appSource, /payload: \{ resourceIds, __trainerResourceOperationId: requestId \}/);
  assert.match(appSource, /onDeleteResources=\{[\s\S]*?requestResourceMutation\("delete", resourceIds\)/);
  assert.match(appSource, /onRestoreResources=\{[\s\S]*?requestResourceMutation\("restore", resourceIds\)/);
  assert.match(
    appSource,
    /onDeleteResources=\{\s*isBrowserPreview\s*\?\s*undefined\s*:\s*\(resourceIds\) => requestResourceMutation\("delete", resourceIds\)/,
  );
  assert.match(
    appSource,
    /onRestoreResources=\{\s*isBrowserPreview\s*\?\s*undefined\s*:\s*\(resourceIds\) => requestResourceMutation\("restore", resourceIds\)/,
  );
  assert.match(appSource, /Browser preview cannot delete real resources\. Use the VS Code sidebar\./);
  assert.match(appSource, /Browser preview cannot restore real resources\. Use the VS Code sidebar\./);
});

test('Resources separates tree selection from explicit native opening', () => {
  const viewSource = fs.readFileSync(resourcesWorkbenchPath, 'utf8');
  const treeItemStart = viewSource.indexOf('function ResourceTreeItem(');
  const treeItemEnd = viewSource.indexOf('export function ResourcesWorkbenchView', treeItemStart);

  assert.ok(treeItemStart >= 0, 'expected the resource tree item renderer');
  assert.ok(treeItemEnd > treeItemStart, 'expected the resource tree item renderer to end');
  const treeItemSource = viewSource.slice(treeItemStart, treeItemEnd);

  assert.match(treeItemSource, /onClick=\{\(\) => onSelect\(node\.resource!\)\}/);
  assert.doesNotMatch(treeItemSource, /onClick=\{\(\) => onOpen\(node\.resource!\)\}/);
  assert.match(treeItemSource, /onDoubleClick=\{\(\) => onOpen\(node\.resource!\)\}/);
  assert.match(treeItemSource, /event\.key === "Enter"[\s\S]*?onOpen\(node\.resource!\);/);
  assert.match(treeItemSource, /aria-keyshortcuts="Enter Space"/);
  assert.match(treeItemSource, /type="checkbox"/);
  assert.match(treeItemSource, /onToggleSelection\(node\.resource!\.id\)/);
  assert.match(viewSource, /className="button button--primary button--compact resources-knowledge__open-action"[\s\S]*?onClick=\{\(\) => openResourceInVsCode\(selectedResource\)\}/);
});

test('Resources does not expose a project file manager or destructive sandbox controls', () => {
  const viewSource = fs.readFileSync(resourcesWorkbenchPath, 'utf8');

  assert.doesNotMatch(viewSource, /onCreateSandboxDirectory/);
  assert.doesNotMatch(viewSource, /onRenameSandboxPath/);
  assert.doesNotMatch(viewSource, /onDeleteSandboxPath/);
  assert.doesNotMatch(viewSource, /onRevealSandboxPath/);
  assert.doesNotMatch(viewSource, /resources-sandbox-tree/);
  assert.doesNotMatch(viewSource, /resources-file-manager/);
});

test('Resources collapses imports into one named, keyboard-accessible menu while refresh stays secondary', () => {
  const viewSource = fs.readFileSync(resourcesWorkbenchPath, 'utf8');
  const stylesSource = fs.readFileSync(stylesPath, 'utf8');

  assert.match(viewSource, /const \[isImportMenuOpen, setIsImportMenuOpen\] = useState\(false\);/);
  assert.match(viewSource, /resources-knowledge__add-resource/);
  assert.match(viewSource, /aria-haspopup="menu"/);
  assert.match(viewSource, /aria-expanded=\{canWriteResources && isImportMenuOpen\}/);
  assert.match(viewSource, /role="menu"/);
  assert.match(viewSource, /role="menuitem"/);
  assert.match(viewSource, /event\.key === "ArrowDown"/);
  assert.match(viewSource, /event\.key !== "Escape"/);
  assert.match(viewSource, /focusFirstImportMenuItem/);
  assert.match(viewSource, /runImportAction\(onImportFiles\)/);
  assert.match(viewSource, /runImportAction\(onImportFolder\)/);
  assert.match(viewSource, /runImportAction\(onImportUrl\)/);
  assert.match(
    viewSource,
    /onClick=\{\(\) => runImportAction\(onImportUrl\)\}[\s\S]*?disabled=\{isBrowserPreview && !isLiveBrowserPreview\}[\s\S]*?browserPreviewMutationNotice/,
  );
  assert.match(viewSource, /resources-knowledge__refresh-button/);
  assert.match(viewSource, /onClick=\{refreshResources\}/);
  assert.match(viewSource, /localize\(language, "addResource"\)/);
  assert.match(viewSource, /addResource: \{ zh: "\\u6dfb\\u52a0\\u8d44\\u6599", en: "Add resource" \}/);
  assert.match(stylesSource, /\.resources-knowledge__import-menu-wrap/);
  assert.match(stylesSource, /\.resources-knowledge__import-menu \{/);
  assert.match(stylesSource, /@media \(max-width: 460px\)/);
  assert.doesNotMatch(viewSource, /resources-knowledge__import-button/);
  assert.doesNotMatch(viewSource, /BookOpenIcon/);
});

test('Resources keeps the first screen focused and folds secondary governance actions', () => {
  const viewSource = fs.readFileSync(resourcesWorkbenchPath, 'utf8');
  const stylesSource = fs.readFileSync(stylesPath, 'utf8');

  assert.match(viewSource, /resources-knowledge__search/);
  assert.match(viewSource, /resources-knowledge__open-action/);
  assert.match(viewSource, /<details className="resources-knowledge__batch-actions">/);
  assert.match(viewSource, /<details className="resources-knowledge__governance">/);
  assert.match(viewSource, /<details className="resources-knowledge__training-handoff">/);
  assert.match(viewSource, /<details[\s\S]*?className="resources-knowledge__trash/);
  assert.match(stylesSource, /\.resources-knowledge__batch-actions/);
  assert.match(stylesSource, /\.resources-knowledge__governance/);
  assert.match(stylesSource, /\.resources-knowledge__training-handoff/);
  assert.match(stylesSource, /\.resources-knowledge__trash/);
});

test('Resources makes library writes visibly unavailable without blocking search or opening', () => {
  const viewSource = fs.readFileSync(resourcesWorkbenchPath, 'utf8');
  const appSource = fs.readFileSync(appPath, 'utf8');

  assert.match(viewSource, /export interface ResourceWriteAccess \{[\s\S]*?allowed: boolean;/);
  assert.match(viewSource, /resourceWriteAccess\?: ResourceWriteAccess;/);
  assert.match(viewSource, /onChooseWorkspaceRoot\?: \(\) => void;/);
  assert.match(viewSource, /const canWriteResources = resourceWriteAccess\?\.allowed !== false;/);
  assert.match(viewSource, /function resourceReadOnlyNotice\(/);
  assert.match(viewSource, /This project is read-only\. You can search and open resources\./);
  assert.match(viewSource, /setIsImportMenuOpen\(false\);[\s\S]*?setDeleteConfirmationResourceIds\(null\);/);
  assert.match(viewSource, /disabled=\{!canWriteResources\}/);
  assert.match(viewSource, /const indexActionDisabled = !canWriteResources \|\| !onRefreshResources \|\| isIndexRefreshing;/);
  assert.match(viewSource, /disabled=\{indexActionDisabled\}/);
  assert.match(viewSource, /const deleteActionDisabled =[\s\S]*?!canWriteResources/);
  assert.match(viewSource, /const restoreActionDisabled =[\s\S]*?!canWriteResources/);
  assert.match(viewSource, /const runImportAction =[\s\S]*?if \(!canWriteResources\) \{[\s\S]*?return;/);
  assert.match(
    viewSource,
    /const refreshResources =[\s\S]*?if \(!canWriteResources \|\| !onRefreshResources \|\| indexRefreshInFlightRef\.current\) \{[\s\S]*?return;/,
  );
  assert.match(viewSource, /resourceWriteAccess\?\.allowed !== false/);
  assert.match(viewSource, /function chooseWorkspaceRootLabel\(/);

  assert.match(viewSource, /onSearchResources\(\{ query: trimmedQuery, requestId \}\)/);
  assert.match(viewSource, /onOpenResource\?\.\(resource\.id\)/);
  assert.match(appSource, /const resourceWriteAccess = trainerWorkspaceAdmission\s*\?/);
  assert.match(appSource, /allowed: trainerWorkspaceAdmission\.status === "managed"/);
  assert.match(appSource, /trainerWorkspaceAdmission\.status === "root-missing"\s*\? t\.workspaceAdmissionRootMissingDetail/);
  assert.match(appSource, /<ResourcesWorkbenchView[\s\S]*?resourceWriteAccess=\{resourceWriteAccess\}/);
  assert.match(
    appSource,
    /onChooseWorkspaceRoot=\{[\s\S]*?trainerWorkspaceAdmission\?\.status === "root-missing"[\s\S]*?trainerCommands\.chooseTrainerWorkspaceRoot/,
  );
});

test('Resources keeps a slow index refresh single-flight across rapid clicks', () => {
  const viewSource = fs.readFileSync(resourcesWorkbenchPath, 'utf8');
  const appSource = fs.readFileSync(appPath, 'utf8');
  const refreshStart = viewSource.indexOf('const refreshResources = () => {');
  const refreshEnd = viewSource.indexOf('const toggleCollection =', refreshStart);

  assert.ok(refreshStart >= 0 && refreshEnd > refreshStart, 'expected the index refresh handler');
  const refreshSource = viewSource.slice(refreshStart, refreshEnd);

  assert.match(viewSource, /const \[isIndexRefreshing, setIsIndexRefreshing\] = useState\(false\);/);
  assert.match(viewSource, /const indexRefreshInFlightRef = useRef\(false\);/);
  assert.match(
    refreshSource,
    /if \(!canWriteResources \|\| !onRefreshResources \|\| indexRefreshInFlightRef\.current\) \{[\s\S]*?return;/,
  );
  assert.match(refreshSource, /indexRefreshInFlightRef\.current = true;/);
  assert.match(refreshSource, /void Promise\.resolve\(\)\s*\.then\(\(\) => onRefreshResources\(\)\)/);
  assert.match(
    refreshSource,
    /\.finally\(\(\) => \{[\s\S]*?indexRefreshInFlightRef\.current = false;[\s\S]*?setIsIndexRefreshing\(false\);/,
  );
  assert.match(viewSource, /aria-busy=\{isIndexRefreshing\}/);

  assert.match(appSource, /type ResourceOperationKind = "delete" \| "restore" \| "search" \| "index" \| "upload";/);
  assert.match(appSource, /const requestResourceIndex = useCallback\(\(\): Promise<void> =>/);
  assert.match(appSource, /kind: "index",[\s\S]*?commandId: trainerCommands\.indexResources,[\s\S]*?__trainerResourceOperationId: requestId/);
  assert.match(appSource, /isBrowserPreview[\s\S]*?: requestResourceIndex/);
});

test('Resources treats URL material as webpage snapshots without restoring status filters', () => {
  const viewSource = fs.readFileSync(resourcesWorkbenchPath, 'utf8');
  const stylesSource = fs.readFileSync(stylesPath, 'utf8');

  assert.match(viewSource, /captureWebSnapshot/);
  assert.match(viewSource, /web-snapshots/);
  assert.match(viewSource, /resourceIndexNotice/);
  assert.doesNotMatch(viewSource, /ResourceFilter/);
  assert.doesNotMatch(viewSource, /resources-file-toolbar/);
  assert.doesNotMatch(viewSource, /resources-knowledge__state/);
  assert.doesNotMatch(viewSource, /collectionSegmentPrefix}links/);
  assert.match(stylesSource, /grid-template-columns: 18px 18px minmax\(0, 1fr\) auto;/);
  assert.match(stylesSource, /\.resources-knowledge__actions \.resources-knowledge__icon-button/);
  assert.doesNotMatch(stylesSource, /\.resources-knowledge__state/);
});

test('Resources recursively selects filtered folder descendants and scopes deletion to visible items', () => {
  const viewSource = fs.readFileSync(resourcesWorkbenchPath, 'utf8');
  const treeItemStart = viewSource.indexOf('function ResourceTreeItem(');
  const treeItemEnd = viewSource.indexOf('export function ResourcesWorkbenchView', treeItemStart);
  const rootTreeMatch = viewSource.match(
    /\{visibleResourceTree\.map\(\(node\)\s*=>\s*\(([\s\S]*?)\)\)\}/,
  );
  const deleteHandlerStart = viewSource.indexOf('const deleteSelectedResources =');
  const deleteHandlerEnd = viewSource.indexOf('const openResourceInVsCode', deleteHandlerStart);

  assert.ok(treeItemStart >= 0 && treeItemEnd > treeItemStart, 'expected the resource tree item renderer');
  assert.ok(rootTreeMatch, 'expected the filtered root tree renderer');
  assert.ok(deleteHandlerStart >= 0 && deleteHandlerEnd > deleteHandlerStart, 'expected the batch delete handler');

  const treeItemSource = viewSource.slice(treeItemStart, treeItemEnd);
  const collectionStart = treeItemSource.indexOf('const isExpanded =');
  const collectionSource = treeItemSource.slice(collectionStart);
  const folderCheckboxStart = collectionSource.indexOf('<input');
  const folderCheckboxEnd = collectionSource.indexOf('/>', folderCheckboxStart);
  const folderCheckboxSource = collectionSource.slice(folderCheckboxStart, folderCheckboxEnd + 2);
  const folderCountStart = collectionSource.indexOf('resources-library-tree__count');
  const folderCountSource = collectionSource.slice(folderCountStart, folderCountStart + 240);
  const rootTreeSource = rootTreeMatch[0];
  const deleteHandlerSource = viewSource.slice(deleteHandlerStart, deleteHandlerEnd);

  assert.ok(collectionStart >= 0, 'expected the collection branch of the resource tree item renderer');
  assert.ok(folderCheckboxStart >= 0 && folderCheckboxEnd > folderCheckboxStart, 'expected the folder selection checkbox');
  assert.ok(folderCountStart >= 0, 'expected the recursive folder resource count');
  assert.match(
    viewSource,
    /function resourceIdsInTreeNode\(node: ResourceTreeNode\): string\[\][\s\S]*?node\.children\.flatMap\(resourceIdsInTreeNode\)/,
  );
  assert.match(
    viewSource,
    /const setResourceSelection = \(\s*resourceIds: string\[\],\s*selected: boolean,?\s*\) =>[\s\S]*?setSelectedResourceIds\(\(current\)\s*=>[\s\S]*?resourceIds\.forEach\(\s*\(?resourceId\)?\s*=>/,
  );

  // The collection receives the filtered node, so its recursive IDs are exactly the visible descendants.
  assert.match(
    viewSource,
    /const visibleResourceTree = useMemo\([\s\S]*?filterResourceTree\(resourceTree, visibleResourceIds\)/,
  );
  assert.match(collectionSource, /resourceIdsInTreeNode\(node\)/);
  assert.match(collectionSource, /selectedResourceIds\.has\(resourceId\)/);
  assert.match(collectionSource, /event\.stopPropagation\(\)/);
  assert.match(
    treeItemSource,
    /event\.key === " "[\s\S]*?event\.stopPropagation\(\)/,
    "only Space should stay within a checkbox; Escape and tree navigation must bubble to the tree",
  );
  assert.match(
    viewSource,
    /event\.target instanceof HTMLInputElement && event\.key === " "/,
    "tree navigation must remain available when a checkbox has focus",
  );
  assert.match(folderCheckboxSource, /type="checkbox"/);
  assert.match(folderCheckboxSource, /checked=/);
  assert.match(folderCheckboxSource, /localize\(language, "selectFolder"\)/);
  assert.match(folderCheckboxSource, /onChange=\{/);
  assert.match(collectionSource, /onSetSelection\(\s*[^,]+,\s*(?:!\s*[^)]+|event\.target\.checked)\)/);
  assert.match(folderCheckboxSource, /indeterminate/);
  assert.match(treeItemSource, /aria-label=\{node\.resource\.title\}/);
  assert.match(treeItemSource, /aria-current=\{isSelected \? "true" : undefined\}/);
  assert.match(collectionSource, /aria-label=\{node\.label\}/);
  assert.match(viewSource, /aria-multiselectable="true"/);
  assert.match(collectionSource, /aria-checked=\{isPartiallyMarked \? "mixed" : isMarked\}/);
  assert.match(folderCountSource, /(?:resourceIdsInTreeNode\(node\)|\b[A-Za-z0-9_]*(?:Resource|resource)Ids)\.length/);
  assert.doesNotMatch(folderCountSource, /node\.children\.length/);

  // Both the filtered roots and recursive descendants must receive the same bulk-selection action.
  assert.match(rootTreeSource, /onSetSelection=\{setResourceSelection\}/);
  assert.match(treeItemSource, /onSetSelection=\{onSetSelection\}/);

  // Folder selection feeds the existing selected-ID set; deletion remains one explicit, visible-only batch action.
  assert.match(
    deleteHandlerSource,
    /const resourceIds = \[\.\.\.selectedResourceIds\]\.filter\(\(resourceId\) => visibleResourceIds\.has\(resourceId\)\);/,
  );
  assert.match(deleteHandlerSource, /const deleteRequest = onDeleteResources\(resourceIds\);/);
  assert.match(deleteHandlerSource, /Promise\.resolve\(deleteRequest\)\.catch/);
});

test('Resources keeps search-result folders visibly collapsible', () => {
  const source = fs.readFileSync(resourcesWorkbenchPath, 'utf8');
  const renderedExpandedStart = source.indexOf('const renderedExpandedCollectionIds = useMemo');
  const toggleCollectionStart = source.indexOf('const toggleCollection =');
  const toggleCollectionEnd = source.indexOf('const handleTreeKeyDown', toggleCollectionStart);

  assert.ok(renderedExpandedStart >= 0, 'expected search expansion state');
  assert.ok(toggleCollectionStart >= 0 && toggleCollectionEnd > toggleCollectionStart, 'expected collection toggle');

  const renderedExpandedSource = source.slice(renderedExpandedStart, toggleCollectionStart);
  const toggleCollectionSource = source.slice(toggleCollectionStart, toggleCollectionEnd);

  assert.match(source, /const \[searchCollapsedCollectionIds, setSearchCollapsedCollectionIds\]/);
  assert.match(
    renderedExpandedSource,
    /collectionIds\(visibleResourceTree\)\.filter\(\(id\) => !searchCollapsedCollectionIds\.has\(id\)\)/,
  );
  assert.match(renderedExpandedSource, /setSearchCollapsedCollectionIds\(new Set\(\)\)/);
  assert.match(toggleCollectionSource, /if \(hasSearchQuery\)[\s\S]*?setSearchCollapsedCollectionIds/);
});

test('Resources derives compact Trash and mutation feedback from persistent host state', () => {
  const viewSource = fs.readFileSync(resourcesWorkbenchPath, 'utf8');
  const stylesSource = fs.readFileSync(stylesPath, 'utf8');

  assert.match(viewSource, /const trashSnapshotAvailable = deletedResources !== undefined;/);
  assert.match(viewSource, /const trashedResources = deletedResources \?\? \[\];/);
  assert.match(viewSource, /const restorableDeletedResources = useMemo/);
  assert.match(viewSource, /const isDeletePending = pendingDeletedResourceIds\.length > 0;/);
  assert.match(viewSource, /const isRestorePending = pendingRestoredResourceIds\.length > 0;/);
  assert.match(viewSource, /trashedResourceIds\.has\(resourceId\)/);
  assert.match(viewSource, /<details[\s\S]*?className="resources-knowledge__trash/);
  assert.doesNotMatch(viewSource, /recentDeletedResourceIds/);

  assert.match(viewSource, /const sandboxRoot = sandboxState\?\.sandboxRootPath \?\? sandboxState\?\.rootPath;/);
  assert.doesNotMatch(viewSource, /resources-knowledge__roots/);

  assert.match(viewSource, /function resourceTreeCollectionKind\(/);
  assert.match(viewSource, /collectionKind\?: "directory" \| "logical";/);
  assert.doesNotMatch(viewSource, /ContextLayersIcon|FileIcon|resources-library-tree__icon/);
  assert.match(stylesSource, /grid-template-columns: 24px minmax\(0, 1fr\)/);
  assert.match(viewSource, /const firstVisibleResourceAncestorIds = useMemo/);
  assert.match(viewSource, /firstResourceAncestorCollectionIds\(visibleResourceTree\)/);

  assert.match(stylesSource, /\.resources-knowledge__mutation/);
  assert.doesNotMatch(stylesSource, /\.resources-knowledge__roots/);
  assert.match(stylesSource, /\.resources-knowledge__trash/);
  assert.match(stylesSource, /max-height: 96px;/);
  assert.match(stylesSource, /\.resources-knowledge__detail\s*\{[\s\S]*?max-height: min\(280px, 36vh\);/);
  assert.match(stylesSource, /@media \(max-width: 360px\)[\s\S]*?\.resources-knowledge__detail\s*\{[\s\S]*?max-height: min\(280px, 42vh\);/);
});

test('Resources correlates host mutation results so failed delete or restore clears its pending state', () => {
  const appSource = fs.readFileSync(appPath, 'utf8');
  const viewSource = fs.readFileSync(resourcesWorkbenchPath, 'utf8');

  assert.match(appSource, /RESOURCE_OPERATION_STATUS_PATTERN/);
  assert.match(appSource, /parseResourceOperationStatus/);
  assert.match(appSource, /fallbackMessage: string/);
  assert.match(appSource, /message: message\.payload\.message\.slice\(marker\[0\]\.length\)\.trim\(\) \|\| fallbackMessage/);
  assert.match(appSource, /const localizedResourceOperationFallback = t\.stageDone;/);
  assert.match(appSource, /parseResourceOperationStatus\(message, localizedResourceOperationFallback\)/);
  assert.match(appSource, /const RESOURCE_OPERATION_TIMEOUT_MS = 45_000;/);
  assert.match(appSource, /resourceOperationResolversRef\.current\.set\(requestId/);
  assert.match(appSource, /window\.setTimeout\(\(\) =>/);
  assert.match(appSource, /operation\.reject\(new Error\("Resource operation timed out\."\)\)/);
  assert.match(appSource, /window\.clearTimeout\(operation\.timeoutId\)/);
  assert.match(appSource, /Resource operation was interrupted\./);
  assert.match(appSource, /operation\.reject\(new Error\(status\.message\)\)/);
  assert.match(appSource, /resolveResourceOperationStatus\(message\)/);
  assert.match(viewSource, /Promise\.resolve\(deleteRequest\)\.catch\(\(\) => reportMutationFailure\("delete", resourceIds\)\)/);
  assert.match(viewSource, /Promise\.resolve\(restoreRequest\)\.catch\(\(\) => reportMutationFailure\("restore", resourceIds\)\)/);
});

test('Resources preserves an explicit selection across views and records unmount separately', () => {
  const appSource = fs.readFileSync(appPath, 'utf8');
  const viewSource = fs.readFileSync(resourcesWorkbenchPath, 'utf8');

  assert.match(
    viewSource,
    /initialResourceContextIds\?: string\[\];/,
  );
  assert.match(viewSource, /onResourceSelectionChange\?\.\(selectedResourceContextIds, "selection"\);/);
  assert.match(viewSource, /onResourceSelectionChange\?\.\(\[\], "unmount"\);/);
  assert.match(appSource, /const turnActiveView = activeViewOverride \?\? activeView;/);
  assert.match(
    appSource,
    /const \[resourceConversationContextIds, setResourceConversationContextIds\] = useState<string\[\]>\(\[\]\);/,
  );
  assert.match(appSource, /if \(reason !== "unmount"\) \{\s*setResourceConversationContextIds\(resourceIds\);/);
  assert.match(appSource, /initialResourceContextIds=\{resourceConversationContextIds\}/);
  assert.match(appSource, /: selectedResourceContextIds\.length > 0\s*\? selectedResourceContextIds\s*:\s*resourceConversationContextIds;/);
  assert.match(appSource, /const resourceConversationContextLabel = useMemo\(/);
  assert.match(appSource, /activeView === "coach" && resourceConversationContextLabel/);
  assert.match(appSource, /setResourceConversationContextIds\(\[\]\);/);
  assert.match(appSource, /activeView: turnActiveView,/);
});

test('Resources starts a review card only from fresh, trusted, indexed material in a managed workspace', () => {
  const appSource = fs.readFileSync(appPath, 'utf8');
  const viewSource = fs.readFileSync(resourcesWorkbenchPath, 'utf8');

  assert.match(viewSource, /onStartTrainingFromResource\?: \(resourceId: string\) => Promise<ResourceTrainingHandoffResult>;/);
  assert.match(viewSource, /function resourceCanStartTraining\(resource: ResourceRecord\): boolean/);
  assert.match(viewSource, /function resourceHasTrainingTrust\(resource: ResourceRecord\): boolean/);
  assert.match(viewSource, /resource\.indexState === "indexed"/);
  assert.match(viewSource, /const trustState = resource\.trustState\?\.trim\(\)\.toLowerCase\(\);/);
  assert.match(viewSource, /if \(trustState && trustState !== "trusted"\) \{/);
  assert.match(viewSource, /const qualityFlags = \(resource\.qualityFlags \?\? \[\]\)\.filter\(\(flag\) => flag\.trim\(\)\.length > 0\);/);
  assert.match(viewSource, /if \(qualityFlags\.length > 0\) \{/);
  assert.match(viewSource, /resource\.trustScore >= 0\.75/);
  assert.match(viewSource, /!resourceHasTrainingTrust\(resource\)\s*\? "trust"/);
  assert.match(viewSource, /resourceHasTrainingTrust\(resource\) &&/);
  assert.match(viewSource, /resource\.freshness === "fresh"/);
  assert.match(viewSource, /"network_disabled"/);
  assert.match(viewSource, /"fetch_failed"/);
  assert.match(viewSource, /resourceWriteAccess\?\.allowed === true/);
  assert.match(viewSource, /selectedResourceCanStartTraining/);
  assert.match(viewSource, /createReviewCard: \{ zh: "\\u751f\\u6210\\u590d\\u4e60\\u5361", en: "Create review card" \}/);
  assert.match(viewSource, /return localize\(language, "createReviewCard"\);/);
  assert.match(
    viewSource,
    /const selectedResourceTrainingIsAvailable =\s*selectedResourceTrainingState\?\.phase === "ready"\s*\|\|\s*selectedResourceTrainingState\?\.phase === "not-current"/,
  );
  assert.match(viewSource, /selectedResourceTrainingIsAvailable \? \(/);
  assert.match(viewSource, /\|\|\s*selectedResourceTrainingIsAvailable/);
  assert.match(viewSource, /onClick=\{onOpenTraining\}/);
  assert.match(viewSource, /openCurrentTraining/);
  assert.match(
    viewSource,
    /selectedResourceTrainingReadiness\?\.canRefresh \? \(\s*<button[\s\S]*?onClick=\{refreshResources\}[\s\S]*?<span>\{refreshResourcesLabel\}<\/span>/,
  );
  assert.match(viewSource, /function resourceReuseSummary\(language: ComposerLanguage\): string/);
  assert.match(viewSource, /const selectedResourceReuseSummary = selectedResource \? resourceReuseSummary\(language\) : undefined;/);
  assert.match(viewSource, /resources-knowledge__reuse-summary/);
  assert.match(viewSource, /resources-knowledge__empty-hint/);

  assert.match(appSource, /const requestResourceTrainingHandoff = useCallback/);
  assert.match(appSource, /source: "resource_knowledge",[\s\S]*?cardType: "flash",[\s\S]*?submode: "flash"/);
  assert.match(appSource, /result\.outcome === "ready"[\s\S]*?setActiveView\("training"\)/);
  assert.match(appSource, /isBrowserPreview=\{browserPreviewFixture\}/);
  assert.match(
    appSource,
    /onStartTrainingFromResource=\{\s*browserPreviewFixture \? undefined : requestResourceTrainingHandoff\s*\}/,
  );
  assert.match(appSource, /onOpenTraining=\{\(\) => setActiveView\("training"\)\}/);
  assert.match(appSource, /message\.type === "training\/resourceHandoff"/);
});
