'use strict';

/**
 * Trainer Capture — shared module.
 *
 * Loaded three ways: importScripts() in the MV3 service worker, a <script> in
 * the popup, and as the declarative content script on http(s) pages.
 *
 * Layout:
 *   1. Pure helpers — no chrome/browser API access at module scope or inside
 *      these functions, so extension/tests/browserCaptureShared.test.js can
 *      require() the file in plain Node.
 *   2. Thin chrome wrappers — storage, fetch, locale. Every wrapper assumes
 *      the extension environment and stays free of business rules.
 *   3. Content-script page affordance — the PDF auto-float button, inert
 *      unless the document itself is a PDF.
 *
 * Data-channel discipline: no page scripts are injected, no cookies or page
 * bodies are read; the extension forwards only the URL / title / selection the
 * user explicitly captured, and the local Trainer sidecar performs all
 * fetching, snapshotting and authoritative deduplication.
 */
(function (global) {
  'use strict';

  // =========================================================================
  // 1. Pure helpers (no chrome APIs)
  // =========================================================================

  const API = {
    health: '/health',
    pair: '/browser/pair',
    status: '/browser/status',
    capture: '/resources/capture',
    autoPair: '/browser/auto-pair',
    coachDraft: '/browser/coach-draft'
  };

  // Deep links open the Trainer host (VS Code) on the resource library.
  const DEEP_LINK_PREFIX = 'vscode://local.trainer-extension/library/';
  const HOST_DEEP_LINK = 'vscode://local.trainer-extension/';

  const SIDECAR = {
    host: '127.0.0.1',
    defaultBaseUrl: 'http://127.0.0.1:8765',
    // SidecarProcessManager allocates from this range upwards.
    managedPortStart: 34891,
    managedPortEnd: 34911,
    // Probes must fail fast: a cold port answers immediately with ECONNREFUSED.
    probeTimeoutMs: 900
  };

  const LIMITS = {
    historyDisplay: 5,
    historyStore: 50,
    queue: 100
  };

  const STORAGE_KEYS = {
    baseUrl: 'trainerCapture.baseUrl',
    credential: 'trainerCapture.credential',
    history: 'trainerCapture.history',
    queue: 'trainerCapture.queue',
    draftQueue: 'trainerCapture.draftQueue',
    workspaceName: 'trainerCapture.workspaceName',
    autoPairDisabled: 'trainerCapture.autoPairDisabled',
    focusId: 'trainerCapture.focusId',
    workspaceId: 'trainerCapture.workspaceId',
    targetDir: 'trainerCapture.targetDir',
    connection: 'trainerCapture.connection',
    statusCache: 'trainerCapture.statusCache',
    notice: 'trainerCapture.notice'
  };

  const CAPTURE_KINDS = ['web', 'pdf', 'github_repo'];

  // Kinds the sidecar can save into the project folder (task 二). Web pages
  // stay library-only: a page has no single canonical file to download.
  const DOWNLOAD_KINDS = ['pdf', 'github_repo'];

  /** Default download folder, relative to the workspace root. */
  const DEFAULT_TARGET_DIR = 'Trainer Library/';

  // Download folder shape, mirrored from the sidecar's library path rules so the
  // popup rejects a folder up front instead of paying a 422 round trip.
  const MAX_TARGET_DIR_DEPTH = 6;
  const MAX_TARGET_DIR_SEGMENT_CHARS = 60;
  const MAX_TARGET_DIR_CHARS = 240;
  const RESERVED_TARGET_DIR_SEGMENTS = new Set([
    '.trainer',
    '.trainer-sandbox',
    '.git',
    'inline-resources',
    'sandbox'
  ]);

  // Reserved github.com first path segments that are not repositories.
  const GITHUB_RESERVED_OWNERS = new Set([
    'about',
    'apps',
    'collections',
    'contact',
    'enterprise',
    'events',
    'explore',
    'features',
    'issues',
    'login',
    'marketplace',
    'new',
    'notifications',
    'orgs',
    'pricing',
    'pulls',
    'search',
    'settings',
    'site',
    'sponsors',
    'topics',
    'trending',
    'users'
  ]);

  // ------------------------------------------------------------------ copy --
  //
  // Eight languages, one key set. Every user-visible string in the popup,
  // context menus, notifications and the PDF float button comes from here;
  // the browser locale selects the dictionary (prefix match, en fallback).

  const COPY = {
    zh: {
      appTitle: 'Trainer 采集',
      checking: '正在检查…',
      detecting: '正在探测本机 Trainer…',
      detected: '找到 Trainer：{url}',
      detectFailed: '未找到本机 Trainer。请先在 VS Code 中打开 Trainer，然后重试。',
      detectAgain: '重新探测',
      needsPair: '需要先配对',
      pairHeading: '配对',
      connectHeading: '连接 Trainer',
      pairCodeLabel: '配对码',
      pairCodePlaceholder: '6 位配对码',
      pairCodeHint: '在 VS Code 执行「Trainer: 复制配对码」，把 6 位码粘贴到这里。',
      pairAction: '配对',
      pairInvalidCode: '配对码应为 6 位数字。',
      pairCodeRejected: '配对码不正确或已过期。',
      pairTransport: '无法连接 Trainer，请确认 VS Code 中的 Trainer 正在运行。',
      pairQueueWaiting: '已有 {count} 条采集在本地排队，配对后将自动投递；也可在 Trainer 资料库查看。',
      pairSuccess: '配对成功',
      pairedAs: '已连接 · {workspace}',
      libraryCountLabel: '资料库 {count} 条',
      pairRevoke: '撤销配对',
      pairAgain: '重新配对',
      pairRevokeHint: '撤销配对会清空本机凭证、待投递队列与本地采集记录，确定吗？',
      pairRevokeDone: '已撤销配对',
      pairRevokeLocalOnly: '已在本地撤销；未能通知 Trainer（可能已离线）。',
      openTrainer: '打开 Trainer',
      close: '关闭',
      captureHeading: '加入资料库',
      capturePage: '将当前页面加入资料库',
      captureBusy: '正在添加…',
      bindingLabel: '绑定学习目标（可选）',
      bindingHint: '该选择同时作为右键菜单采集的默认绑定。',
      bindingNone: '不绑定',
      queueHeading: '待投递',
      queueCount: '{count} 条等待投递',
      queueRetry: '立即重试',
      queueFlushing: '正在投递…',
      queueFlushed: '已投递 {count} 条',
      queueNothing: '没有可投递的采集。',
      queueOffline: 'Trainer 仍不可达，稍后会自动重试。',
      queueUnpaired: '尚未配对，无法投递。',
      queueEmpty: '没有待投递的采集。',
      autoConnecting: '正在连接本地 Trainer…',
      autoConnected: '已连接',
      autoRetry: '重试连接',
      autoPairFailed: '未找到正在运行的 Trainer',
      autoDisconnected: '已断开',
      autoOfflineHint: '现在采集也会自动排队，Trainer 启动后送达。',
      coachQueued: '已排队，Trainer 启动后自动送入输入框（{count} 条待投递）',
      coachQueueFull: '待投递队列已满（100 条），请先打开 Trainer 完成投递。',
      queueWorkspaceChanged: '这条记录属于另一个工作区，已保留但不会投递到当前项目。',
      queueDraftLabel: '划词',
      historyHeading: '最近采集',
      historyEmpty: '还没有采集记录。',
      openInTrainer: '在 Trainer 中打开',
      statusOk: '成功',
      statusDuplicated: '已在资料库',
      statusQueued: '待投递',
      statusFailed: '失败',
      kindWeb: '网页',
      kindPdf: 'PDF',
      kindGithub: 'GitHub 仓库',
      kindUnknown: '来源',
      menuPage: '加入 Trainer 资料库',
      menuLink: '加入资料库（链接）',
      menuGithubGroup: '加入资料库（GitHub 仓库）',
      menuGithubReadme: '加入资料库（README+结构）',
      menuGithubDocs: '加入资料库（含 docs/）',
      coachMenu: '问 Trainer 教练',
      captureSuccess: '已加入资料库：{title}',
      captureDeduped: '已在资料库：{title}',
      captureDuplicateLocal: '已在资料库（本地记录）：{title}',
      captureDuplicateQueued: '已在待投递队列：{title}',
      captureQueued: 'Trainer 未能完成采集，已排队（{count} 条待投递）',
      captureFailed: '添加失败：{message}',
      captureUnpaired: '请先点击拓展图标完成配对，再加入资料库。',
      captureNoUrl: '该条目没有可采集的 http/https 地址。',
      captureGithubNeedsRepo: 'GitHub 采集需要仓库地址（github.com/<owner>/<repo>）。',
      coachSent: '已送入 Trainer 输入框（未发送）',
      coachFailed: '送入失败：{message}',
      coachEmptySelection: '没有可送入的选中文本。',
      errUnauthorized: '凭证无效或已撤销，请重新配对。',
      errNetworkDisabled: 'Trainer 已关闭网络抓取，无法下载该来源。',
      errBrowseOnly: '当前工作区为只读模式，无法写入资料库。',
      errReadmeNotFound: '该仓库没有可用的 README。',
      errTimeout: '请求超时：Trainer 还在处理这个来源，稍后会自动重试。',
      errUnreachable: '无法连接 Trainer。',
      errServerMessage: '添加失败（HTTP {status}）：{message}',
      errServerStatus: '添加失败：Trainer 返回 HTTP {status}。',
      notifyLibraryTitle: 'Trainer 资料库',
      notifyPending: '正在添加到 Trainer…',
      notifyQueuedTitle: 'Trainer 未能完成采集',
      notifyFailedTitle: 'Trainer 采集失败',
      notifyDraftTitle: 'Trainer 教练',
      notifyQueueDoneTitle: 'Trainer 待投递完成',
      pdfButton: '加入 Trainer',
      pdfTitle: '将这篇 PDF 加入 Trainer 资料库',
      pdfWorking: '添加中…',
      pdfDone: '已加入资料库',
      pdfDuplicate: '已在资料库',
      pdfQueued: '已排队',
      pdfNeedsPair: '请先配对',
      pdfFailed: '失败，点击重试',
      // Download-to-project-folder entries (task 二).
      menuPdfGroup: 'PDF 选项',
      menuPdfLibrary: '加入资料库（PDF）',
      menuPdfDownload: '下载 PDF 到项目文件夹',
      menuGithubDownload: '下载项目到文件夹',
      downloadHeading: '下载到项目文件夹',
      downloadLabel: '目标文件夹',
      downloadPlaceholder: 'Trainer Library/',
      downloadHint: '保存在当前项目内；文件夹不存在时会自动创建。',
      downloadAction: '下载到项目文件夹',
      downloadBusy: '正在下载…',
      downloadInvalidFolder: '请填写项目内的相对文件夹（不要绝对路径，也不要包含「..」）。',
      downloadUnsupported: '下载功能适用于 PDF 与 GitHub 仓库。',
      captureDownloaded: '已下载到 {path}',
      captureDownloadedDeduped: '该文件已在项目文件夹：{path}',
      captureDownloadQueued: 'Trainer 未能完成下载，已排队（{count} 条待投递）',
      captureQueueFull: '待投递队列已满（100 条）。请先连接 Trainer 完成投递，再采集新内容。',
      notifyDownloadTitle: 'Trainer 下载',
      savedPathLabel: '已保存：{path}',
      openInVsCode: '在 VS Code 打开',
      // Trainer-not-running state (task 三).
      statusOffline: 'Trainer 未运行',
      statusOfflineDetail: '已配对。捕获会自动暂存在本机，Trainer 启动后自动送达。',
      workspaceLabel: '工作区',
      queueClear: '清空队列',
      queueClearConfirm: '清空待投递队列？尚未投递的采集将丢失。',
      queueDelete: '删除',
      queueDeleteTitle: '从队列删除：{title}',
      queueAttempts: '已尝试 {count} 次'
    },
    en: {
      appTitle: 'Trainer Capture',
      checking: 'Checking…',
      detecting: 'Looking for Trainer on this machine…',
      detected: 'Found Trainer at {url}',
      detectFailed: 'Trainer was not found. Open Trainer in VS Code, then try again.',
      detectAgain: 'Detect again',
      needsPair: 'Pairing required',
      pairHeading: 'Pairing',
      connectHeading: 'Connect to Trainer',
      pairCodeLabel: 'Pairing code',
      pairCodePlaceholder: '6-digit code',
      pairCodeHint: 'Run "Trainer: Copy pairing code" in VS Code, then paste the 6-digit code here.',
      pairAction: 'Pair',
      pairInvalidCode: 'The pairing code must be 6 digits.',
      pairCodeRejected: 'That pairing code is wrong or has expired.',
      pairTransport: 'Trainer is unreachable. Make sure Trainer is running in VS Code.',
      pairQueueWaiting: '{count} captures are queued locally; they deliver automatically once paired, or open Trainer\'s library to review them.',
      pairSuccess: 'Paired',
      pairedAs: 'Connected · {workspace}',
      libraryCountLabel: '{count} items in the library',
      pairRevoke: 'Revoke pairing',
      pairAgain: 'Pair again',
      pairRevokeHint: 'Revoking clears the local credential, the pending queue and the local capture records. Continue?',
      pairRevokeDone: 'Pairing revoked',
      pairRevokeLocalOnly: 'Revoked locally; Trainer could not be notified (probably offline).',
      openTrainer: 'Open Trainer',
      close: 'Close',
      captureHeading: 'Add to library',
      capturePage: 'Add this page to the library',
      captureBusy: 'Adding…',
      bindingLabel: 'Bind a learning focus (optional)',
      bindingHint: 'This choice also becomes the default for right-click captures.',
      bindingNone: 'No binding',
      queueHeading: 'Pending delivery',
      queueCount: '{count} waiting to be delivered',
      queueRetry: 'Retry now',
      queueFlushing: 'Delivering…',
      queueFlushed: 'Delivered {count} item(s)',
      queueNothing: 'Nothing to deliver.',
      queueOffline: 'Trainer is still unreachable; retrying automatically.',
      queueUnpaired: 'Not paired yet, nothing can be delivered.',
      queueEmpty: 'Nothing waiting to be delivered.',
      autoConnecting: 'Connecting to local Trainer…',
      autoConnected: 'Connected',
      autoRetry: 'Retry connection',
      autoPairFailed: 'Trainer is not running yet',
      autoDisconnected: 'Disconnected',
      autoOfflineHint: 'Captures are queued automatically and delivered when Trainer starts.',
      coachQueued: 'Queued — it will prefill the coach composer when Trainer starts ({count} pending)',
      coachQueueFull: 'The pending queue is full (100). Open Trainer and let it deliver first.',
      queueWorkspaceChanged: 'This item belongs to another workspace. It is kept but will not be delivered to the current project.',
      queueDraftLabel: 'Selection',
      historyHeading: 'Recent captures',
      historyEmpty: 'No captures yet.',
      openInTrainer: 'Open in Trainer',
      statusOk: 'Added',
      statusDuplicated: 'Already in library',
      statusQueued: 'Queued',
      statusFailed: 'Failed',
      kindWeb: 'Web page',
      kindPdf: 'PDF',
      kindGithub: 'GitHub repo',
      kindUnknown: 'Source',
      menuPage: 'Add to Trainer library',
      menuLink: 'Add to library (link)',
      menuGithubGroup: 'Add to library (GitHub repo)',
      menuGithubReadme: 'Add to library (README + structure)',
      menuGithubDocs: 'Add to library (with docs/)',
      coachMenu: 'Ask the Trainer coach',
      captureSuccess: 'Added to the library: {title}',
      captureDeduped: 'Already in the library: {title}',
      captureDuplicateLocal: 'Already in your library (local record): {title}',
      captureDuplicateQueued: 'Already queued for delivery: {title}',
      captureQueued: 'Trainer could not finish the capture; queued ({count} pending)',
      captureFailed: 'Capture failed: {message}',
      captureUnpaired: 'Pair the extension first (click the toolbar icon), then capture.',
      captureNoUrl: 'This entry has no http/https address to capture.',
      captureGithubNeedsRepo: 'Capturing GitHub needs a repository URL (github.com/<owner>/<repo>).',
      coachSent: 'Sent to the Trainer composer (not sent yet)',
      coachFailed: 'Could not send to Trainer: {message}',
      coachEmptySelection: 'There is no selected text to send.',
      errUnauthorized: 'The credential is invalid or revoked — pair again.',
      errNetworkDisabled: 'Trainer has network fetching disabled; this source cannot be downloaded.',
      errBrowseOnly: 'This workspace is read-only, so the library cannot be written.',
      errReadmeNotFound: 'No usable README was found for that repository.',
      errTimeout: 'Request timed out: Trainer is still working on this source; it will retry.',
      errUnreachable: 'Trainer is unreachable.',
      errServerMessage: 'Capture failed (HTTP {status}): {message}',
      errServerStatus: 'Capture failed: Trainer returned HTTP {status}.',
      notifyLibraryTitle: 'Trainer library',
      notifyPending: 'Adding to Trainer…',
      notifyQueuedTitle: 'Trainer could not finish the capture',
      notifyFailedTitle: 'Trainer capture failed',
      notifyDraftTitle: 'Trainer coach',
      notifyQueueDoneTitle: 'Trainer queue delivered',
      pdfButton: 'Add to Trainer',
      pdfTitle: 'Add this PDF to the Trainer library',
      pdfWorking: 'Adding…',
      pdfDone: 'Added to library',
      pdfDuplicate: 'Already in library',
      pdfQueued: 'Queued',
      pdfNeedsPair: 'Pair first',
      pdfFailed: 'Failed — click to retry',
      // Download-to-project-folder entries (task 二).
      menuPdfGroup: 'PDF actions',
      menuPdfLibrary: 'Add to library (PDF)',
      menuPdfDownload: 'Download PDF to project folder',
      menuGithubDownload: 'Download repo to project folder',
      downloadHeading: 'Download to project folder',
      downloadLabel: 'Target folder',
      downloadPlaceholder: 'Trainer Library/',
      downloadHint: 'Saved inside the current project. The folder is created if it does not exist.',
      downloadAction: 'Download to project folder',
      downloadBusy: 'Downloading…',
      downloadInvalidFolder: 'Use a relative folder inside the project (no "..", no absolute path).',
      downloadUnsupported: 'Downloading is available for PDFs and GitHub repositories.',
      captureDownloaded: 'Downloaded to {path}',
      captureDownloadedDeduped: 'Already downloaded to {path}',
      captureDownloadQueued: 'Trainer could not finish the download; queued ({count} pending)',
      captureQueueFull: 'The pending queue is full (100). Deliver it to Trainer before capturing more.',
      notifyDownloadTitle: 'Trainer download',
      savedPathLabel: 'Saved to {path}',
      openInVsCode: 'Open in VS Code',
      // Trainer-not-running state (task 三).
      statusOffline: 'Trainer is not running',
      statusOfflineDetail: 'Paired and ready. Captures are stored locally and delivered automatically once Trainer starts.',
      workspaceLabel: 'Workspace',
      queueClear: 'Clear queue',
      queueClearConfirm: 'Clear the pending queue? Captures that were not delivered yet will be lost.',
      queueDelete: 'Delete',
      queueDeleteTitle: 'Remove from the queue: {title}',
      queueAttempts: 'Attempts: {count}'
    },
    es: {
      appTitle: 'Captura de Trainer',
      checking: 'Comprobando…',
      detecting: 'Buscando Trainer en este equipo…',
      detected: 'Trainer encontrado en {url}',
      detectFailed: 'No se encontró Trainer. Abre Trainer en VS Code y vuelve a intentarlo.',
      detectAgain: 'Volver a buscar',
      needsPair: 'Se requiere emparejamiento',
      pairHeading: 'Emparejamiento',
      connectHeading: 'Conectar con Trainer',
      pairCodeLabel: 'Código de emparejamiento',
      pairCodePlaceholder: 'Código de 6 dígitos',
      pairCodeHint: 'Ejecuta «Trainer: Show Browser Pairing Code» en VS Code y pega aquí el código de 6 dígitos.',
      pairAction: 'Emparejar',
      pairInvalidCode: 'El código de emparejamiento debe tener 6 dígitos.',
      pairCodeRejected: 'Ese código de emparejamiento es incorrecto o ha caducado.',
      pairTransport: 'No se puede conectar con Trainer. Comprueba que Trainer esté en ejecución en VS Code.',
      pairQueueWaiting: 'Hay {count} capturas en cola local; se entregarán al emparejar, o abre la biblioteca de Trainer para revisarlas.',
      pairSuccess: 'Emparejado',
      pairedAs: 'Conectado · {workspace}',
      libraryCountLabel: '{count} elementos en la biblioteca',
      pairRevoke: 'Anular emparejamiento',
      pairAgain: 'Volver a emparejar',
      pairRevokeHint: 'Anular el emparejamiento borra la credencial local, la cola de entrega y los registros de captura locales. ¿Continuar?',
      pairRevokeDone: 'Emparejamiento anulado',
      pairRevokeLocalOnly: 'Anulado localmente; no se pudo avisar a Trainer (probablemente sin conexión).',
      openTrainer: 'Abrir Trainer',
      close: 'Cerrar',
      captureHeading: 'Añadir a la biblioteca',
      capturePage: 'Añadir esta página a la biblioteca',
      captureBusy: 'Añadiendo…',
      bindingLabel: 'Vincular un objetivo de aprendizaje (opcional)',
      bindingHint: 'Esta elección también es el vínculo predeterminado para las capturas del menú contextual.',
      bindingNone: 'Sin vincular',
      queueHeading: 'Pendientes de entrega',
      queueCount: '{count} en espera de entrega',
      queueRetry: 'Reintentar ahora',
      queueFlushing: 'Entregando…',
      queueFlushed: 'Se entregaron {count} elemento(s)',
      queueNothing: 'Nada que entregar.',
      queueOffline: 'Trainer sigue inaccesible; se reintentará automáticamente.',
      queueUnpaired: 'Aún no está emparejado; no se puede entregar nada.',
      queueEmpty: 'Nada en espera de entrega.',
      autoConnecting: 'Conectando con Trainer local…',
      autoConnected: 'Conectado',
      autoRetry: 'Reintentar conexión',
      autoPairFailed: 'Trainer aún no está en ejecución',
      autoDisconnected: 'Desconectado',
      autoOfflineHint: 'Las capturas se guardan en cola y se entregan cuando Trainer inicie.',
      coachQueued: 'En cola: se enviará al compositor cuando Trainer inicie ({count} pendientes)',
      coachQueueFull: 'La cola está llena (100). Abre Trainer para entregarla primero.',
      queueWorkspaceChanged: 'Este elemento pertenece a otro espacio de trabajo. Se conserva pero no se entregará al proyecto actual.',
      queueDraftLabel: 'Selección',
      historyHeading: 'Capturas recientes',
      historyEmpty: 'Aún no hay capturas.',
      openInTrainer: 'Abrir en Trainer',
      statusOk: 'Añadido',
      statusDuplicated: 'Ya en la biblioteca',
      statusQueued: 'En cola',
      statusFailed: 'Error',
      kindWeb: 'Página web',
      kindPdf: 'PDF',
      kindGithub: 'Repositorio de GitHub',
      kindUnknown: 'Origen',
      menuPage: 'Añadir a la biblioteca de Trainer',
      menuLink: 'Añadir a la biblioteca (enlace)',
      menuGithubGroup: 'Añadir a la biblioteca (repositorio de GitHub)',
      menuGithubReadme: 'Añadir a la biblioteca (README + estructura)',
      menuGithubDocs: 'Añadir a la biblioteca (con docs/)',
      coachMenu: 'Preguntar al entrenador de Trainer',
      captureSuccess: 'Añadido a la biblioteca: {title}',
      captureDeduped: 'Ya está en la biblioteca: {title}',
      captureDuplicateLocal: 'Ya está en tu biblioteca (registro local): {title}',
      captureDuplicateQueued: 'Ya está en la cola de entrega: {title}',
      captureQueued: 'Trainer no pudo completar la captura; en cola ({count} pendientes)',
      captureFailed: 'Error al añadir: {message}',
      captureUnpaired: 'Empareja primero la extensión (haz clic en el icono de la barra de herramientas) y luego captura.',
      captureNoUrl: 'Esta entrada no tiene una dirección http/https que capturar.',
      captureGithubNeedsRepo: 'Capturar GitHub requiere una URL de repositorio (github.com/<owner>/<repo>).',
      coachSent: 'Enviado al cuadro de entrada de Trainer (sin enviar)',
      coachFailed: 'No se pudo enviar a Trainer: {message}',
      coachEmptySelection: 'No hay texto seleccionado para enviar.',
      errUnauthorized: 'La credencial no es válida o fue revocada; vuelve a emparejar.',
      errNetworkDisabled: 'Trainer tiene desactivada la descarga de red; esta fuente no se puede descargar.',
      errBrowseOnly: 'Este espacio de trabajo es de solo lectura; no se puede escribir en la biblioteca.',
      errReadmeNotFound: 'No se encontró un README utilizable en ese repositorio.',
      errTimeout: 'Tiempo de espera agotado: Trainer sigue procesando esta fuente; se reintentará.',
      errUnreachable: 'No se puede conectar con Trainer.',
      errServerMessage: 'Error al añadir (HTTP {status}): {message}',
      errServerStatus: 'Error al añadir: Trainer devolvió HTTP {status}.',
      notifyLibraryTitle: 'Biblioteca de Trainer',
      notifyPending: 'Añadiendo a Trainer…',
      notifyQueuedTitle: 'Trainer no pudo completar la captura',
      notifyFailedTitle: 'Error de captura de Trainer',
      notifyDraftTitle: 'Entrenador de Trainer',
      notifyQueueDoneTitle: 'Cola de entrega completada',
      pdfButton: 'Añadir a Trainer',
      pdfTitle: 'Añadir este PDF a la biblioteca de Trainer',
      pdfWorking: 'Añadiendo…',
      pdfDone: 'Añadido a la biblioteca',
      pdfDuplicate: 'Ya en la biblioteca',
      pdfQueued: 'En cola',
      pdfNeedsPair: 'Empareja primero',
      pdfFailed: 'Error; haz clic para reintentar',
      // Download-to-project-folder entries (task 二).
      menuPdfGroup: 'Acciones de PDF',
      menuPdfLibrary: 'Añadir a la biblioteca (PDF)',
      menuPdfDownload: 'Descargar el PDF a la carpeta del proyecto',
      menuGithubDownload: 'Descargar el repositorio a la carpeta',
      downloadHeading: 'Descargar a la carpeta del proyecto',
      downloadLabel: 'Carpeta de destino',
      downloadPlaceholder: 'Trainer Library/',
      downloadHint: 'Se guarda dentro del proyecto actual; la carpeta se crea si no existe.',
      downloadAction: 'Descargar a la carpeta del proyecto',
      downloadBusy: 'Descargando…',
      downloadInvalidFolder: 'Usa una carpeta relativa dentro del proyecto (sin «..» ni rutas absolutas).',
      downloadUnsupported: 'La descarga está disponible para PDF y repositorios de GitHub.',
      captureDownloaded: 'Descargado en {path}',
      captureDownloadedDeduped: 'Ya está descargado en {path}',
      captureDownloadQueued: 'Trainer no pudo completar la descarga; en cola ({count} pendientes)',
      captureQueueFull: 'La cola pendiente está llena (100). Entrégala a Trainer antes de capturar más.',
      notifyDownloadTitle: 'Descarga de Trainer',
      savedPathLabel: 'Guardado en {path}',
      openInVsCode: 'Abrir en VS Code',
      // Trainer-not-running state (task 三).
      statusOffline: 'Trainer no está en ejecución',
      statusOfflineDetail: 'Emparejado y listo. Las capturas se guardan localmente y se entregan solas cuando Trainer arranque.',
      workspaceLabel: 'Espacio de trabajo',
      queueClear: 'Vaciar la cola',
      queueClearConfirm: '¿Vaciar la cola de entrega? Las capturas aún no entregadas se perderán.',
      queueDelete: 'Eliminar',
      queueDeleteTitle: 'Quitar de la cola: {title}',
      queueAttempts: 'Intentos: {count}'
    },
    fr: {
      appTitle: 'Capture Trainer',
      checking: 'Vérification…',
      detecting: 'Recherche de Trainer sur cet ordinateur…',
      detected: 'Trainer trouvé sur {url}',
      detectFailed: 'Trainer est introuvable. Ouvrez Trainer dans VS Code, puis réessayez.',
      detectAgain: 'Rechercher à nouveau',
      needsPair: 'Association requise',
      pairHeading: 'Association',
      connectHeading: 'Connexion à Trainer',
      pairCodeLabel: 'Code d’association',
      pairCodePlaceholder: 'Code à 6 chiffres',
      pairCodeHint: 'Exécutez « Trainer: Show Browser Pairing Code » dans VS Code, puis collez le code à 6 chiffres ici.',
      pairAction: 'Associer',
      pairInvalidCode: 'Le code d’association doit comporter 6 chiffres.',
      pairCodeRejected: 'Ce code d’association est incorrect ou a expiré.',
      pairTransport: 'Trainer est injoignable. Vérifiez que Trainer est bien démarré dans VS Code.',
      pairQueueWaiting: '{count} captures en file locale ; elles seront livrées après appariement, ou ouvrez la bibliothèque de Trainer pour les consulter.',
      pairSuccess: 'Associé',
      pairedAs: 'Connecté · {workspace}',
      libraryCountLabel: '{count} éléments dans la bibliothèque',
      pairRevoke: 'Dissocier',
      pairAgain: 'Associer à nouveau',
      pairRevokeHint: 'La dissociation efface l’identifiant local, la file d’attente et les captures locales. Continuer ?',
      pairRevokeDone: 'Association supprimée',
      pairRevokeLocalOnly: 'Révoqué localement ; Trainer n’a pas pu être prévenu (probablement hors ligne).',
      openTrainer: 'Ouvrir Trainer',
      close: 'Fermer',
      captureHeading: 'Ajouter à la bibliothèque',
      capturePage: 'Ajouter cette page à la bibliothèque',
      captureBusy: 'Ajout…',
      bindingLabel: 'Associer un objectif d’apprentissage (facultatif)',
      bindingHint: 'Ce choix devient aussi l’association par défaut des captures par menu contextuel.',
      bindingNone: 'Aucune association',
      queueHeading: 'File d’attente',
      queueCount: '{count} en attente d’envoi',
      queueRetry: 'Réessayer maintenant',
      queueFlushing: 'Envoi en cours…',
      queueFlushed: '{count} élément(s) envoyé(s)',
      queueNothing: 'Rien à envoyer.',
      queueOffline: 'Trainer est toujours injoignable ; nouvelle tentative automatique.',
      queueUnpaired: 'Pas encore associé : rien ne peut être envoyé.',
      queueEmpty: 'Rien en attente d’envoi.',
      autoConnecting: 'Connexion à Trainer local…',
      autoConnected: 'Connecté',
      autoRetry: 'Réessayer la connexion',
      autoPairFailed: 'Trainer n’est pas encore lancé',
      autoDisconnected: 'Déconnecté',
      autoOfflineHint: 'Les captures sont mises en file et livrées au démarrage de Trainer.',
      coachQueued: 'En file — la sélection sera préremplie au démarrage de Trainer ({count} en attente)',
      coachQueueFull: 'La file d’attente est pleine (100). Ouvrez Trainer pour la livrer d’abord.',
      queueWorkspaceChanged: 'Cet élément appartient à un autre espace de travail. Il est conservé mais ne sera pas livré au projet actuel.',
      queueDraftLabel: 'Sélection',
      historyHeading: 'Captures récentes',
      historyEmpty: 'Aucune capture pour le moment.',
      openInTrainer: 'Ouvrir dans Trainer',
      statusOk: 'Ajouté',
      statusDuplicated: 'Déjà dans la bibliothèque',
      statusQueued: 'En attente',
      statusFailed: 'Échec',
      kindWeb: 'Page web',
      kindPdf: 'PDF',
      kindGithub: 'Dépôt GitHub',
      kindUnknown: 'Source',
      menuPage: 'Ajouter à la bibliothèque Trainer',
      menuLink: 'Ajouter à la bibliothèque (lien)',
      menuGithubGroup: 'Ajouter à la bibliothèque (dépôt GitHub)',
      menuGithubReadme: 'Ajouter à la bibliothèque (README + structure)',
      menuGithubDocs: 'Ajouter à la bibliothèque (avec docs/)',
      coachMenu: 'Demander au coach Trainer',
      captureSuccess: 'Ajouté à la bibliothèque : {title}',
      captureDeduped: 'Déjà dans la bibliothèque : {title}',
      captureDuplicateLocal: 'Déjà dans votre bibliothèque (enregistrement local) : {title}',
      captureDuplicateQueued: 'Déjà dans la file d’envoi : {title}',
      captureQueued: 'Trainer n’a pas pu terminer la capture ; mis en attente ({count} en attente)',
      captureFailed: 'Échec de l’ajout : {message}',
      captureUnpaired: 'Associez d’abord l’extension (cliquez sur l’icône de la barre d’outils), puis capturez.',
      captureNoUrl: 'Cette entrée n’a pas d’adresse http/https à capturer.',
      captureGithubNeedsRepo: 'La capture GitHub nécessite une URL de dépôt (github.com/<owner>/<repo>).',
      coachSent: 'Envoyé dans la zone de saisie de Trainer (pas encore envoyé)',
      coachFailed: 'Impossible d’envoyer à Trainer : {message}',
      coachEmptySelection: 'Aucun texte sélectionné à envoyer.',
      errUnauthorized: 'L’identifiant est invalide ou révoqué — associez à nouveau.',
      errNetworkDisabled: 'Le téléchargement réseau est désactivé dans Trainer ; cette source ne peut pas être téléchargée.',
      errBrowseOnly: 'Cet espace de travail est en lecture seule ; impossible d’écrire dans la bibliothèque.',
      errReadmeNotFound: 'Aucun README utilisable n’a été trouvé dans ce dépôt.',
      errTimeout: 'Délai dépassé : Trainer traite encore cette source ; une nouvelle tentative suivra.',
      errUnreachable: 'Trainer est injoignable.',
      errServerMessage: 'Échec de l’ajout (HTTP {status}) : {message}',
      errServerStatus: 'Échec de l’ajout : Trainer a renvoyé HTTP {status}.',
      notifyLibraryTitle: 'Bibliothèque Trainer',
      notifyPending: 'Ajout à Trainer…',
      notifyQueuedTitle: 'Trainer n’a pas pu terminer la capture',
      notifyFailedTitle: 'Échec de la capture Trainer',
      notifyDraftTitle: 'Coach Trainer',
      notifyQueueDoneTitle: 'File d’attente envoyée',
      pdfButton: 'Ajouter à Trainer',
      pdfTitle: 'Ajouter ce PDF à la bibliothèque Trainer',
      pdfWorking: 'Ajout…',
      pdfDone: 'Ajouté à la bibliothèque',
      pdfDuplicate: 'Déjà dans la bibliothèque',
      pdfQueued: 'En attente',
      pdfNeedsPair: 'Associez d’abord',
      pdfFailed: 'Échec — cliquez pour réessayer',
      // Download-to-project-folder entries (task 二).
      menuPdfGroup: 'Actions PDF',
      menuPdfLibrary: 'Ajouter à la bibliothèque (PDF)',
      menuPdfDownload: 'Télécharger le PDF dans le dossier du projet',
      menuGithubDownload: 'Télécharger le dépôt dans le dossier',
      downloadHeading: 'Télécharger dans le dossier du projet',
      downloadLabel: 'Dossier de destination',
      downloadPlaceholder: 'Trainer Library/',
      downloadHint: 'Enregistré dans le projet actuel ; le dossier est créé au besoin.',
      downloadAction: 'Télécharger dans le dossier du projet',
      downloadBusy: 'Téléchargement…',
      downloadInvalidFolder: 'Utilisez un dossier relatif dans le projet (sans « .. » ni chemin absolu).',
      downloadUnsupported: 'Le téléchargement concerne les PDF et les dépôts GitHub.',
      captureDownloaded: 'Téléchargé dans {path}',
      captureDownloadedDeduped: 'Déjà téléchargé dans {path}',
      captureDownloadQueued: 'Trainer n’a pas pu terminer le téléchargement ; en attente ({count} en attente)',
      captureQueueFull: 'La file d’attente est pleine (100). Livrez-la à Trainer avant de capturer davantage.',
      notifyDownloadTitle: 'Téléchargement Trainer',
      savedPathLabel: 'Enregistré dans {path}',
      openInVsCode: 'Ouvrir dans VS Code',
      // Trainer-not-running state (task 三).
      statusOffline: 'Trainer n’est pas démarré',
      statusOfflineDetail: 'Associé et prêt. Les captures sont stockées localement et envoyées automatiquement au démarrage de Trainer.',
      workspaceLabel: 'Espace de travail',
      queueClear: 'Vider la file',
      queueClearConfirm: 'Vider la file d’attente ? Les captures non envoyées seront perdues.',
      queueDelete: 'Supprimer',
      queueDeleteTitle: 'Retirer de la file : {title}',
      queueAttempts: 'Tentatives : {count}'
    },
    de: {
      appTitle: 'Trainer-Erfassung',
      checking: 'Wird geprüft…',
      detecting: 'Trainer wird auf diesem Rechner gesucht…',
      detected: 'Trainer gefunden unter {url}',
      detectFailed: 'Trainer wurde nicht gefunden. Öffne Trainer in VS Code und versuche es erneut.',
      detectAgain: 'Erneut suchen',
      needsPair: 'Kopplung erforderlich',
      pairHeading: 'Kopplung',
      connectHeading: 'Mit Trainer verbinden',
      pairCodeLabel: 'Kopplungscode',
      pairCodePlaceholder: '6-stelliger Code',
      pairCodeHint: 'Führe „Trainer: Show Browser Pairing Code“ in VS Code aus und füge den 6-stelligen Code hier ein.',
      pairAction: 'Koppeln',
      pairInvalidCode: 'Der Kopplungscode muss aus 6 Ziffern bestehen.',
      pairCodeRejected: 'Dieser Kopplungscode ist falsch oder abgelaufen.',
      pairTransport: 'Trainer ist nicht erreichbar. Stelle sicher, dass Trainer in VS Code läuft.',
      pairQueueWaiting: '{count} Aufnahmen sind lokal in der Warteschlange; sie werden nach dem Koppeln automatisch zugestellt, oder öffne die Trainer-Bibliothek.',
      pairSuccess: 'Gekoppelt',
      pairedAs: 'Verbunden · {workspace}',
      libraryCountLabel: '{count} Einträge in der Bibliothek',
      pairRevoke: 'Kopplung aufheben',
      pairAgain: 'Erneut koppeln',
      pairRevokeHint: 'Beim Aufheben werden die lokale Anmeldeinformation, die Warteschlange und die lokalen Erfassungen gelöscht. Fortfahren?',
      pairRevokeDone: 'Kopplung aufgehoben',
      pairRevokeLocalOnly: 'Lokal aufgehoben; Trainer konnte nicht benachrichtigt werden (wahrscheinlich offline).',
      openTrainer: 'Trainer öffnen',
      close: 'Schließen',
      captureHeading: 'Zur Bibliothek hinzufügen',
      capturePage: 'Diese Seite zur Bibliothek hinzufügen',
      captureBusy: 'Wird hinzugefügt…',
      bindingLabel: 'Ein Lernziel binden (optional)',
      bindingHint: 'Diese Auswahl ist zugleich die Standardbindung für Erfassungen über das Kontextmenü.',
      bindingNone: 'Keine Bindung',
      queueHeading: 'Ausstehende Übertragung',
      queueCount: '{count} warten auf Übertragung',
      queueRetry: 'Jetzt erneut versuchen',
      queueFlushing: 'Wird übertragen…',
      queueFlushed: '{count} Element(e) übertragen',
      queueNothing: 'Nichts zu übertragen.',
      queueOffline: 'Trainer ist weiterhin nicht erreichbar; erneuter Versuch erfolgt automatisch.',
      queueUnpaired: 'Noch nicht gekoppelt; es kann nichts übertragen werden.',
      queueEmpty: 'Nichts wartet auf Übertragung.',
      autoConnecting: 'Verbindung zu lokalem Trainer…',
      autoConnected: 'Verbunden',
      autoRetry: 'Verbindung erneut versuchen',
      autoPairFailed: 'Trainer läuft noch nicht',
      autoDisconnected: 'Getrennt',
      autoOfflineHint: 'Aufnahmen werden automatisch eingereiht und beim Start von Trainer zugestellt.',
      coachQueued: 'Eingereiht – wird beim Start von Trainer in den Coach-Composer eingesetzt ({count} ausstehend)',
      coachQueueFull: 'Die Warteschlange ist voll (100). Öffne Trainer, um sie zuerst zuzustellen.',
      queueWorkspaceChanged: 'Dieses Element gehört zu einem anderen Arbeitsbereich. Es bleibt erhalten, wird aber nicht an das aktuelle Projekt zugestellt.',
      queueDraftLabel: 'Auswahl',
      historyHeading: 'Letzte Erfassungen',
      historyEmpty: 'Noch keine Erfassungen.',
      openInTrainer: 'In Trainer öffnen',
      statusOk: 'Hinzugefügt',
      statusDuplicated: 'Bereits in der Bibliothek',
      statusQueued: 'In Warteschlange',
      statusFailed: 'Fehlgeschlagen',
      kindWeb: 'Webseite',
      kindPdf: 'PDF',
      kindGithub: 'GitHub-Repository',
      kindUnknown: 'Quelle',
      menuPage: 'Zur Trainer-Bibliothek hinzufügen',
      menuLink: 'Zur Bibliothek hinzufügen (Link)',
      menuGithubGroup: 'Zur Bibliothek hinzufügen (GitHub-Repository)',
      menuGithubReadme: 'Zur Bibliothek hinzufügen (README + Struktur)',
      menuGithubDocs: 'Zur Bibliothek hinzufügen (mit docs/)',
      coachMenu: 'Trainer-Coach fragen',
      captureSuccess: 'Zur Bibliothek hinzugefügt: {title}',
      captureDeduped: 'Bereits in der Bibliothek: {title}',
      captureDuplicateLocal: 'Bereits in deiner Bibliothek (lokaler Eintrag): {title}',
      captureDuplicateQueued: 'Bereits in der Übertragungswarteschlange: {title}',
      captureQueued: 'Trainer konnte die Erfassung nicht abschließen; in Warteschlange ({count} ausstehend)',
      captureFailed: 'Hinzufügen fehlgeschlagen: {message}',
      captureUnpaired: 'Koppele zuerst die Erweiterung (auf das Symbol in der Symbolleiste klicken) und erfasse dann.',
      captureNoUrl: 'Dieser Eintrag hat keine http/https-Adresse zum Erfassen.',
      captureGithubNeedsRepo: 'GitHub-Erfassung erfordert eine Repository-URL (github.com/<owner>/<repo>).',
      coachSent: 'In das Trainer-Eingabefeld übernommen (noch nicht gesendet)',
      coachFailed: 'Senden an Trainer fehlgeschlagen: {message}',
      coachEmptySelection: 'Es ist kein ausgewählter Text zum Senden vorhanden.',
      errUnauthorized: 'Die Anmeldeinformation ist ungültig oder wurde aufgehoben — bitte erneut koppeln.',
      errNetworkDisabled: 'Trainer hat das Abrufen aus dem Netzwerk deaktiviert; diese Quelle kann nicht geladen werden.',
      errBrowseOnly: 'Dieser Arbeitsbereich ist schreibgeschützt; die Bibliothek kann nicht geschrieben werden.',
      errReadmeNotFound: 'Für dieses Repository wurde keine nutzbare README gefunden.',
      errTimeout: 'Zeitüberschreitung: Trainer verarbeitet diese Quelle noch; sie wird erneut versucht.',
      errUnreachable: 'Trainer ist nicht erreichbar.',
      errServerMessage: 'Hinzufügen fehlgeschlagen (HTTP {status}): {message}',
      errServerStatus: 'Hinzufügen fehlgeschlagen: Trainer hat HTTP {status} zurückgegeben.',
      notifyLibraryTitle: 'Trainer-Bibliothek',
      notifyPending: 'Wird zu Trainer hinzugefügt…',
      notifyQueuedTitle: 'Trainer konnte die Erfassung nicht abschließen',
      notifyFailedTitle: 'Trainer-Erfassung fehlgeschlagen',
      notifyDraftTitle: 'Trainer-Coach',
      notifyQueueDoneTitle: 'Warteschlange übertragen',
      pdfButton: 'Zu Trainer hinzufügen',
      pdfTitle: 'Dieses PDF zur Trainer-Bibliothek hinzufügen',
      pdfWorking: 'Wird hinzugefügt…',
      pdfDone: 'Zur Bibliothek hinzugefügt',
      pdfDuplicate: 'Bereits in der Bibliothek',
      pdfQueued: 'In Warteschlange',
      pdfNeedsPair: 'Zuerst koppeln',
      pdfFailed: 'Fehlgeschlagen – zum Wiederholen klicken',
      // Download-to-project-folder entries (task 二).
      menuPdfGroup: 'PDF-Aktionen',
      menuPdfLibrary: 'Zur Bibliothek hinzufügen (PDF)',
      menuPdfDownload: 'PDF in den Projektordner laden',
      menuGithubDownload: 'Repository in den Ordner laden',
      downloadHeading: 'In den Projektordner laden',
      downloadLabel: 'Zielordner',
      downloadPlaceholder: 'Trainer Library/',
      downloadHint: 'Wird im aktuellen Projekt gespeichert; der Ordner wird bei Bedarf angelegt.',
      downloadAction: 'In den Projektordner laden',
      downloadBusy: 'Wird geladen…',
      downloadInvalidFolder: 'Verwende einen relativen Ordner im Projekt (kein „..“, kein absoluter Pfad).',
      downloadUnsupported: 'Das Herunterladen gilt für PDFs und GitHub-Repositories.',
      captureDownloaded: 'Nach {path} geladen',
      captureDownloadedDeduped: 'Bereits nach {path} geladen',
      captureDownloadQueued: 'Trainer konnte den Download nicht abschließen; in Warteschlange ({count} ausstehend)',
      captureQueueFull: 'Die Warteschlange ist voll (100). Übertrage sie an Trainer, bevor du weiter erfasst.',
      notifyDownloadTitle: 'Trainer-Download',
      savedPathLabel: 'Gespeichert unter {path}',
      openInVsCode: 'In VS Code öffnen',
      // Trainer-not-running state (task 三).
      statusOffline: 'Trainer läuft nicht',
      statusOfflineDetail: 'Gekoppelt und bereit. Erfassungen werden lokal gespeichert und automatisch übertragen, sobald Trainer startet.',
      workspaceLabel: 'Arbeitsbereich',
      queueClear: 'Warteschlange leeren',
      queueClearConfirm: 'Warteschlange leeren? Noch nicht übertragene Erfassungen gehen verloren.',
      queueDelete: 'Löschen',
      queueDeleteTitle: 'Aus der Warteschlange entfernen: {title}',
      queueAttempts: 'Versuche: {count}'
    },
    ja: {
      appTitle: 'Trainer キャプチャ',
      checking: '確認中…',
      detecting: 'この PC 上の Trainer を探しています…',
      detected: 'Trainer が見つかりました：{url}',
      detectFailed: 'Trainer が見つかりません。VS Code で Trainer を開いてから、もう一度お試しください。',
      detectAgain: '再検出',
      needsPair: 'ペアリングが必要です',
      pairHeading: 'ペアリング',
      connectHeading: 'Trainer に接続',
      pairCodeLabel: 'ペアリングコード',
      pairCodePlaceholder: '6 桁のコード',
      pairCodeHint: 'VS Code で「Trainer: Show Browser Pairing Code」を実行し、6 桁のコードをここに貼り付けてください。',
      pairAction: 'ペアリング',
      pairInvalidCode: 'ペアリングコードは 6 桁の数字です。',
      pairCodeRejected: 'そのペアリングコードは正しくないか、有効期限が切れています。',
      pairTransport: 'Trainer に接続できません。VS Code で Trainer が実行中か確認してください。',
      pairQueueWaiting: '{count} 件のキャプチャがローカルに待機中です。ペアリング後に自動送信されます。Trainer のライブラリからも確認できます。',
      pairSuccess: 'ペアリング完了',
      pairedAs: '接続済み · {workspace}',
      libraryCountLabel: 'ライブラリ {count} 件',
      pairRevoke: 'ペアリングを解除',
      pairAgain: '再ペアリング',
      pairRevokeHint: 'ペアリングを解除すると、ローカル資格情報・配信待ちキュー・ローカルのキャプチャ記録が消去されます。続行しますか？',
      pairRevokeDone: 'ペアリングを解除しました',
      pairRevokeLocalOnly: 'ローカルでは解除しましたが、Trainer に通知できませんでした（オフラインの可能性があります）。',
      openTrainer: 'Trainer を開く',
      close: '閉じる',
      captureHeading: 'ライブラリに追加',
      capturePage: 'このページをライブラリに追加',
      captureBusy: '追加中…',
      bindingLabel: '学習目標を紐付け（任意）',
      bindingHint: 'この選択は右クリックメニューでのキャプチャの既定の紐付けにもなります。',
      bindingNone: '紐付けなし',
      queueHeading: '配信待ち',
      queueCount: '{count} 件が配信待ち',
      queueRetry: '今すぐ再試行',
      queueFlushing: '配信中…',
      queueFlushed: '{count} 件を配信しました',
      queueNothing: '配信するものはありません。',
      queueOffline: 'Trainer にまだ接続できません。自動的に再試行します。',
      queueUnpaired: 'まだペアリングされていないため、配信できません。',
      queueEmpty: '配信待ちはありません。',
      autoConnecting: 'ローカル Trainer に接続中…',
      autoConnected: '接続済み',
      autoRetry: '接続を再試行',
      autoPairFailed: 'Trainer はまだ起動していません',
      autoDisconnected: '切断済み',
      autoOfflineHint: 'キャプチャは自動的にキューに入り、Trainer の起動時に届けられます。',
      coachQueued: 'キューに追加しました。Trainer 起動時にコーチ入力欄へ挿入されます（{count} 件待機）',
      coachQueueFull: '待機キューがいっぱいです（100 件）。先に Trainer を開いて送信してください。',
      queueWorkspaceChanged: 'この項目は別のワークスペースのものです。保持されますが、現在のプロジェクトには送信されません。',
      queueDraftLabel: '選択範囲',
      historyHeading: '最近のキャプチャ',
      historyEmpty: 'まだキャプチャ記録がありません。',
      openInTrainer: 'Trainer で開く',
      statusOk: '追加済み',
      statusDuplicated: 'ライブラリにあり',
      statusQueued: '配信待ち',
      statusFailed: '失敗',
      kindWeb: 'Web ページ',
      kindPdf: 'PDF',
      kindGithub: 'GitHub リポジトリ',
      kindUnknown: 'ソース',
      menuPage: 'Trainer ライブラリに追加',
      menuLink: 'ライブラリに追加（リンク）',
      menuGithubGroup: 'ライブラリに追加（GitHub リポジトリ）',
      menuGithubReadme: 'ライブラリに追加（README + 構成）',
      menuGithubDocs: 'ライブラリに追加（docs/ を含む）',
      coachMenu: 'Trainer コーチに質問',
      captureSuccess: 'ライブラリに追加しました：{title}',
      captureDeduped: 'すでにライブラリにあります：{title}',
      captureDuplicateLocal: 'すでにライブラリにあります（ローカル記録）：{title}',
      captureDuplicateQueued: 'すでに配信待ちキューにあります：{title}',
      captureQueued: 'Trainer がキャプチャを完了できなかったため、キューに追加しました（{count} 件待ち）',
      captureFailed: '追加に失敗しました：{message}',
      captureUnpaired: '先に拡張機能をペアリングしてから（ツールバーアイコンをクリック）、キャプチャしてください。',
      captureNoUrl: 'この項目にはキャプチャできる http/https アドレスがありません。',
      captureGithubNeedsRepo: 'GitHub のキャプチャにはリポジトリ URL（github.com/<owner>/<repo>）が必要です。',
      coachSent: 'Trainer の入力欄に送りました（未送信）',
      coachFailed: 'Trainer への送信に失敗しました：{message}',
      coachEmptySelection: '送信できる選択テキストがありません。',
      errUnauthorized: '資格情報が無効か失効しています。もう一度ペアリングしてください。',
      errNetworkDisabled: 'Trainer のネットワーク取得が無効なため、このソースはダウンロードできません。',
      errBrowseOnly: 'このワークスペースは読み取り専用のため、ライブラリに書き込めません。',
      errReadmeNotFound: 'そのリポジトリには使用できる README が見つかりませんでした。',
      errTimeout: 'タイムアウトしました：Trainer はまだこのソースを処理中です。自動的に再試行します。',
      errUnreachable: 'Trainer に接続できません。',
      errServerMessage: '追加に失敗しました（HTTP {status}）：{message}',
      errServerStatus: '追加に失敗しました：Trainer が HTTP {status} を返しました。',
      notifyLibraryTitle: 'Trainer ライブラリ',
      notifyPending: 'Trainer に追加中…',
      notifyQueuedTitle: 'Trainer がキャプチャを完了できませんでした',
      notifyFailedTitle: 'Trainer のキャプチャに失敗',
      notifyDraftTitle: 'Trainer コーチ',
      notifyQueueDoneTitle: '配信待ちを配信しました',
      pdfButton: 'Trainer に追加',
      pdfTitle: 'この PDF を Trainer ライブラリに追加',
      pdfWorking: '追加中…',
      pdfDone: 'ライブラリに追加しました',
      pdfDuplicate: 'ライブラリにあります',
      pdfQueued: '配信待ち',
      pdfNeedsPair: '先にペアリングしてください',
      pdfFailed: '失敗しました。クリックで再試行',
      // Download-to-project-folder entries (task 二).
      menuPdfGroup: 'PDF の操作',
      menuPdfLibrary: 'ライブラリに追加（PDF）',
      menuPdfDownload: 'PDF をプロジェクトフォルダーにダウンロード',
      menuGithubDownload: 'リポジトリをフォルダーにダウンロード',
      downloadHeading: 'プロジェクトフォルダーにダウンロード',
      downloadLabel: '保存先フォルダー',
      downloadPlaceholder: 'Trainer Library/',
      downloadHint: '現在のプロジェクト内に保存します。フォルダーがなければ作成します。',
      downloadAction: 'プロジェクトフォルダーにダウンロード',
      downloadBusy: 'ダウンロード中…',
      downloadInvalidFolder: 'プロジェクト内の相対フォルダーを指定してください（「..」や絶対パスは使えません）。',
      downloadUnsupported: 'ダウンロードは PDF と GitHub リポジトリで利用できます。',
      captureDownloaded: '{path} にダウンロードしました',
      captureDownloadedDeduped: 'すでに {path} にあります',
      captureDownloadQueued: 'Trainer がダウンロードを完了できなかったため、キューに追加しました（{count} 件待ち）',
      captureQueueFull: '待機キューがいっぱいです（100 件）。Trainer に送信してから新しい取得を行ってください。',
      notifyDownloadTitle: 'Trainer のダウンロード',
      savedPathLabel: '保存先：{path}',
      openInVsCode: 'VS Code で開く',
      // Trainer-not-running state (task 三).
      statusOffline: 'Trainer が起動していません',
      statusOfflineDetail: 'ペアリング済み。キャプチャは端末に一時保存され、Trainer の起動後に自動で届きます。',
      workspaceLabel: 'ワークスペース',
      queueClear: 'キューを空にする',
      queueClearConfirm: '配信待ちキューを空にしますか？未配信のキャプチャは失われます。',
      queueDelete: '削除',
      queueDeleteTitle: 'キューから削除：{title}',
      queueAttempts: '試行回数：{count}'
    },
    ko: {
      appTitle: 'Trainer 캡처',
      checking: '확인 중…',
      detecting: '이 컴퓨터에서 Trainer를 찾는 중…',
      detected: 'Trainer를 찾았습니다: {url}',
      detectFailed: 'Trainer를 찾지 못했습니다. VS Code에서 Trainer를 연 뒤 다시 시도하세요.',
      detectAgain: '다시 찾기',
      needsPair: '페어링 필요',
      pairHeading: '페어링',
      connectHeading: 'Trainer 연결',
      pairCodeLabel: '페어링 코드',
      pairCodePlaceholder: '6자리 코드',
      pairCodeHint: 'VS Code에서 "Trainer: Show Browser Pairing Code"를 실행한 뒤 6자리 코드를 여기에 붙여넣으세요.',
      pairAction: '페어링',
      pairInvalidCode: '페어링 코드는 6자리 숫자여야 합니다.',
      pairCodeRejected: '페어링 코드가 잘못되었거나 만료되었습니다.',
      pairTransport: 'Trainer에 연결할 수 없습니다. VS Code에서 Trainer가 실행 중인지 확인하세요.',
      pairQueueWaiting: '{count}개의 캡처가 로컬 대기열에 있습니다. 페어링 후 자동 전달되며, Trainer 라이브러리에서도 확인할 수 있습니다.',
      pairSuccess: '페어링됨',
      pairedAs: '연결됨 · {workspace}',
      libraryCountLabel: '라이브러리 {count}개',
      pairRevoke: '페어링 해제',
      pairAgain: '다시 페어링',
      pairRevokeHint: '페어링을 해제하면 로컬 자격 증명, 전송 대기 큐, 로컬 캡처 기록이 모두 지워집니다. 계속할까요?',
      pairRevokeDone: '페어링을 해제했습니다',
      pairRevokeLocalOnly: '로컬에서 해제했지만 Trainer에 알리지 못했습니다(오프라인 상태일 수 있습니다).',
      openTrainer: 'Trainer 열기',
      close: '닫기',
      captureHeading: '라이브러리에 추가',
      capturePage: '이 페이지를 라이브러리에 추가',
      captureBusy: '추가 중…',
      bindingLabel: '학습 목표 연결(선택)',
      bindingHint: '이 선택은 마우스 오른쪽 버튼 메뉴 캡처의 기본 연결로도 사용됩니다.',
      bindingNone: '연결 안 함',
      queueHeading: '전송 대기',
      queueCount: '{count}개 전송 대기 중',
      queueRetry: '지금 재시도',
      queueFlushing: '전송 중…',
      queueFlushed: '{count}개를 전송했습니다',
      queueNothing: '전송할 항목이 없습니다.',
      queueOffline: 'Trainer에 아직 연결할 수 없습니다. 자동으로 다시 시도합니다.',
      queueUnpaired: '아직 페어링되지 않아 전송할 수 없습니다.',
      queueEmpty: '전송 대기 중인 항목이 없습니다.',
      autoConnecting: '로컬 Trainer에 연결하는 중…',
      autoConnected: '연결됨',
      autoRetry: '연결 다시 시도',
      autoPairFailed: 'Trainer가 아직 실행 중이 아닙니다',
      autoDisconnected: '연결 해제됨',
      autoOfflineHint: '캡처는 자동으로 대기열에 저장되고 Trainer가 시작되면 전달됩니다.',
      coachQueued: '대기열에 저장했습니다. Trainer가 시작되면 코치 입력창에 채워집니다({count}개 대기).',
      coachQueueFull: '대기열이 가득 찼습니다(100개). 먼저 Trainer를 열어 전달하세요.',
      queueWorkspaceChanged: '이 항목은 다른 작업 공간의 것입니다. 보관되지만 현재 프로젝트로 전달되지는 않습니다.',
      queueDraftLabel: '선택',
      historyHeading: '최근 캡처',
      historyEmpty: '아직 캡처 기록이 없습니다.',
      openInTrainer: 'Trainer에서 열기',
      statusOk: '추가됨',
      statusDuplicated: '이미 라이브러리에 있음',
      statusQueued: '대기 중',
      statusFailed: '실패',
      kindWeb: '웹 페이지',
      kindPdf: 'PDF',
      kindGithub: 'GitHub 리포지토리',
      kindUnknown: '출처',
      menuPage: 'Trainer 라이브러리에 추가',
      menuLink: '라이브러리에 추가(링크)',
      menuGithubGroup: '라이브러리에 추가(GitHub 리포지토리)',
      menuGithubReadme: '라이브러리에 추가(README + 구조)',
      menuGithubDocs: '라이브러리에 추가(docs/ 포함)',
      coachMenu: 'Trainer 코치에게 질문',
      captureSuccess: '라이브러리에 추가했습니다: {title}',
      captureDeduped: '이미 라이브러리에 있습니다: {title}',
      captureDuplicateLocal: '이미 라이브러리에 있습니다(로컬 기록): {title}',
      captureDuplicateQueued: '이미 전송 대기 큐에 있습니다: {title}',
      captureQueued: 'Trainer가 캡처를 완료하지 못해 대기열에 넣었습니다({count}개 대기)',
      captureFailed: '추가 실패: {message}',
      captureUnpaired: '먼저 확장 프로그램을 페어링한 뒤(툴바 아이콘 클릭) 캡처하세요.',
      captureNoUrl: '이 항목에는 캡처할 http/https 주소가 없습니다.',
      captureGithubNeedsRepo: 'GitHub 캡처에는 리포지토리 URL(github.com/<owner>/<repo>)이 필요합니다.',
      coachSent: 'Trainer 입력창에 넣었습니다(아직 전송 안 됨)',
      coachFailed: 'Trainer로 보내지 못했습니다: {message}',
      coachEmptySelection: '보낼 선택 텍스트가 없습니다.',
      errUnauthorized: '자격 증명이 유효하지 않거나 해제되었습니다. 다시 페어링하세요.',
      errNetworkDisabled: 'Trainer의 네트워크 가져오기가 꺼져 있어 이 소스를 내려받을 수 없습니다.',
      errBrowseOnly: '이 워크스페이스는 읽기 전용이라 라이브러리에 쓸 수 없습니다.',
      errReadmeNotFound: '해당 리포지토리에서 사용할 수 있는 README를 찾지 못했습니다.',
      errTimeout: '시간 초과: Trainer가 아직 이 소스를 처리 중입니다. 자동으로 다시 시도합니다.',
      errUnreachable: 'Trainer에 연결할 수 없습니다.',
      errServerMessage: '추가 실패(HTTP {status}): {message}',
      errServerStatus: '추가 실패: Trainer가 HTTP {status}를 반환했습니다.',
      notifyLibraryTitle: 'Trainer 라이브러리',
      notifyPending: 'Trainer에 추가 중…',
      notifyQueuedTitle: 'Trainer가 캡처를 완료하지 못했습니다',
      notifyFailedTitle: 'Trainer 캡처 실패',
      notifyDraftTitle: 'Trainer 코치',
      notifyQueueDoneTitle: '전송 대기 전송 완료',
      pdfButton: 'Trainer에 추가',
      pdfTitle: '이 PDF를 Trainer 라이브러리에 추가',
      pdfWorking: '추가 중…',
      pdfDone: '라이브러리에 추가했습니다',
      pdfDuplicate: '이미 라이브러리에 있습니다',
      pdfQueued: '대기열에 추가됨',
      pdfNeedsPair: '먼저 페어링하세요',
      pdfFailed: '실패 — 클릭하여 다시 시도',
      // Download-to-project-folder entries (task 二).
      menuPdfGroup: 'PDF 작업',
      menuPdfLibrary: '라이브러리에 추가(PDF)',
      menuPdfDownload: 'PDF를 프로젝트 폴더로 다운로드',
      menuGithubDownload: '리포지토리를 폴더로 다운로드',
      downloadHeading: '프로젝트 폴더로 다운로드',
      downloadLabel: '대상 폴더',
      downloadPlaceholder: 'Trainer Library/',
      downloadHint: '현재 프로젝트 안에 저장합니다. 폴더가 없으면 새로 만듭니다.',
      downloadAction: '프로젝트 폴더로 다운로드',
      downloadBusy: '다운로드 중…',
      downloadInvalidFolder: '프로젝트 내부의 상대 폴더를 입력하세요(".."나 절대 경로는 사용할 수 없습니다).',
      downloadUnsupported: '다운로드는 PDF와 GitHub 리포지토리에서 사용할 수 있습니다.',
      captureDownloaded: '{path}에 다운로드했습니다',
      captureDownloadedDeduped: '이미 {path}에 있습니다',
      captureDownloadQueued: 'Trainer가 다운로드를 완료하지 못해 대기열에 넣었습니다({count}개 대기)',
      captureQueueFull: '대기 열이 가득 찼습니다(100개). Trainer로 전송한 후에 새로 캡처하세요.',
      notifyDownloadTitle: 'Trainer 다운로드',
      savedPathLabel: '저장 위치: {path}',
      openInVsCode: 'VS Code에서 열기',
      // Trainer-not-running state (task 三).
      statusOffline: 'Trainer가 실행 중이 아닙니다',
      statusOfflineDetail: '페어링됨. 캡처는 로컬에 임시 저장되고 Trainer가 시작되면 자동으로 전달됩니다.',
      workspaceLabel: '워크스페이스',
      queueClear: '대기열 비우기',
      queueClearConfirm: '전송 대기 큐를 비울까요? 아직 전송되지 않은 캡처는 사라집니다.',
      queueDelete: '삭제',
      queueDeleteTitle: '대기열에서 삭제: {title}',
      queueAttempts: '시도 {count}회'
    },
    pt: {
      appTitle: 'Captura do Trainer',
      checking: 'Verificando…',
      detecting: 'Procurando o Trainer neste computador…',
      detected: 'Trainer encontrado em {url}',
      detectFailed: 'O Trainer não foi encontrado. Abra o Trainer no VS Code e tente novamente.',
      detectAgain: 'Procurar novamente',
      needsPair: 'Emparelhamento necessário',
      pairHeading: 'Emparelhamento',
      connectHeading: 'Conectar ao Trainer',
      pairCodeLabel: 'Código de emparelhamento',
      pairCodePlaceholder: 'Código de 6 dígitos',
      pairCodeHint: 'Execute "Trainer: Show Browser Pairing Code" no VS Code e cole o código de 6 dígitos aqui.',
      pairAction: 'Emparelhar',
      pairInvalidCode: 'O código de emparelhamento deve ter 6 dígitos.',
      pairCodeRejected: 'Esse código de emparelhamento está incorreto ou expirou.',
      pairTransport: 'O Trainer está inacessível. Verifique se o Trainer está em execução no VS Code.',
      pairQueueWaiting: '{count} capturas estão na fila local; serão entregues após o pareamento, ou abra a biblioteca do Trainer para revisá-las.',
      pairSuccess: 'Emparelhado',
      pairedAs: 'Conectado · {workspace}',
      libraryCountLabel: '{count} itens na biblioteca',
      pairRevoke: 'Revogar emparelhamento',
      pairAgain: 'Emparelhar novamente',
      pairRevokeHint: 'Revogar o emparelhamento apaga a credencial local, a fila de entrega e os registros de captura locais. Continuar?',
      pairRevokeDone: 'Emparelhamento revogado',
      pairRevokeLocalOnly: 'Revogado localmente; não foi possível avisar o Trainer (provavelmente offline).',
      openTrainer: 'Abrir Trainer',
      close: 'Fechar',
      captureHeading: 'Adicionar à biblioteca',
      capturePage: 'Adicionar esta página à biblioteca',
      captureBusy: 'Adicionando…',
      bindingLabel: 'Vincular uma meta de aprendizado (opcional)',
      bindingHint: 'Esta escolha também vira o vínculo padrão para capturas pelo menu de contexto.',
      bindingNone: 'Sem vínculo',
      queueHeading: 'Pendentes de entrega',
      queueCount: '{count} aguardando entrega',
      queueRetry: 'Tentar novamente',
      queueFlushing: 'Entregando…',
      queueFlushed: '{count} item(ns) entregue(s)',
      queueNothing: 'Nada a entregar.',
      queueOffline: 'O Trainer continua inacessível; nova tentativa automática.',
      queueUnpaired: 'Ainda não emparelhado; nada pode ser entregue.',
      queueEmpty: 'Nada aguardando entrega.',
      autoConnecting: 'Conectando ao Trainer local…',
      autoConnected: 'Conectado',
      autoRetry: 'Tentar conexão novamente',
      autoPairFailed: 'O Trainer ainda não está em execução',
      autoDisconnected: 'Desconectado',
      autoOfflineHint: 'As capturas entram na fila e são entregues quando o Trainer iniciar.',
      coachQueued: 'Na fila — será preenchido no compositor quando o Trainer iniciar ({count} pendentes)',
      coachQueueFull: 'A fila está cheia (100). Abra o Trainer para entregá-la primeiro.',
      queueWorkspaceChanged: 'Este item pertence a outro espaço de trabalho. Ele é mantido, mas não será entregue ao projeto atual.',
      queueDraftLabel: 'Seleção',
      historyHeading: 'Capturas recentes',
      historyEmpty: 'Ainda não há capturas.',
      openInTrainer: 'Abrir no Trainer',
      statusOk: 'Adicionado',
      statusDuplicated: 'Já na biblioteca',
      statusQueued: 'Na fila',
      statusFailed: 'Falha',
      kindWeb: 'Página da web',
      kindPdf: 'PDF',
      kindGithub: 'Repositório do GitHub',
      kindUnknown: 'Fonte',
      menuPage: 'Adicionar à biblioteca do Trainer',
      menuLink: 'Adicionar à biblioteca (link)',
      menuGithubGroup: 'Adicionar à biblioteca (repositório do GitHub)',
      menuGithubReadme: 'Adicionar à biblioteca (README + estrutura)',
      menuGithubDocs: 'Adicionar à biblioteca (com docs/)',
      coachMenu: 'Perguntar ao treinador do Trainer',
      captureSuccess: 'Adicionado à biblioteca: {title}',
      captureDeduped: 'Já está na biblioteca: {title}',
      captureDuplicateLocal: 'Já está na sua biblioteca (registro local): {title}',
      captureDuplicateQueued: 'Já está na fila de entrega: {title}',
      captureQueued: 'O Trainer não conseguiu concluir a captura; na fila ({count} pendentes)',
      captureFailed: 'Falha ao adicionar: {message}',
      captureUnpaired: 'Emparelhe a extensão primeiro (clique no ícone da barra de ferramentas) e depois capture.',
      captureNoUrl: 'Este item não tem um endereço http/https para capturar.',
      captureGithubNeedsRepo: 'A captura do GitHub exige uma URL de repositório (github.com/<owner>/<repo>).',
      coachSent: 'Enviado para o campo do Trainer (ainda não enviado)',
      coachFailed: 'Não foi possível enviar ao Trainer: {message}',
      coachEmptySelection: 'Não há texto selecionado para enviar.',
      errUnauthorized: 'A credencial é inválida ou foi revogada; emparelhe novamente.',
      errNetworkDisabled: 'O Trainer está com a busca na rede desativada; esta fonte não pode ser baixada.',
      errBrowseOnly: 'Este workspace é somente leitura; não é possível gravar na biblioteca.',
      errReadmeNotFound: 'Nenhum README utilizável foi encontrado nesse repositório.',
      errTimeout: 'Tempo esgotado: o Trainer ainda está processando esta fonte; haverá nova tentativa.',
      errUnreachable: 'O Trainer está inacessível.',
      errServerMessage: 'Falha ao adicionar (HTTP {status}): {message}',
      errServerStatus: 'Falha ao adicionar: o Trainer retornou HTTP {status}.',
      notifyLibraryTitle: 'Biblioteca do Trainer',
      notifyPending: 'Adicionando ao Trainer…',
      notifyQueuedTitle: 'O Trainer não conseguiu concluir a captura',
      notifyFailedTitle: 'Falha na captura do Trainer',
      notifyDraftTitle: 'Treinador do Trainer',
      notifyQueueDoneTitle: 'Fila entregue',
      pdfButton: 'Adicionar ao Trainer',
      pdfTitle: 'Adicionar este PDF à biblioteca do Trainer',
      pdfWorking: 'Adicionando…',
      pdfDone: 'Adicionado à biblioteca',
      pdfDuplicate: 'Já na biblioteca',
      pdfQueued: 'Na fila',
      pdfNeedsPair: 'Emparelhe primeiro',
      pdfFailed: 'Falha — clique para tentar novamente',
      // Download-to-project-folder entries (task 二).
      menuPdfGroup: 'Ações de PDF',
      menuPdfLibrary: 'Adicionar à biblioteca (PDF)',
      menuPdfDownload: 'Baixar o PDF para a pasta do projeto',
      menuGithubDownload: 'Baixar o repositório para a pasta',
      downloadHeading: 'Baixar para a pasta do projeto',
      downloadLabel: 'Pasta de destino',
      downloadPlaceholder: 'Trainer Library/',
      downloadHint: 'Salvo dentro do projeto atual; a pasta é criada se não existir.',
      downloadAction: 'Baixar para a pasta do projeto',
      downloadBusy: 'Baixando…',
      downloadInvalidFolder: 'Use uma pasta relativa dentro do projeto (sem ".." nem caminho absoluto).',
      downloadUnsupported: 'O download está disponível para PDFs e repositórios do GitHub.',
      captureDownloaded: 'Baixado para {path}',
      captureDownloadedDeduped: 'Já está baixado em {path}',
      captureDownloadQueued: 'O Trainer não conseguiu concluir o download; na fila ({count} pendentes)',
      captureQueueFull: 'A fila pendente está cheia (100). Entregue ao Trainer antes de capturar mais.',
      notifyDownloadTitle: 'Download do Trainer',
      savedPathLabel: 'Salvo em {path}',
      openInVsCode: 'Abrir no VS Code',
      // Trainer-not-running state (task 三).
      statusOffline: 'O Trainer não está em execução',
      statusOfflineDetail: 'Emparelhado e pronto. As capturas ficam salvas localmente e são entregues automaticamente quando o Trainer iniciar.',
      workspaceLabel: 'Workspace',
      queueClear: 'Limpar a fila',
      queueClearConfirm: 'Limpar a fila de entrega? As capturas ainda não entregues serão perdidas.',
      queueDelete: 'Excluir',
      queueDeleteTitle: 'Remover da fila: {title}',
      queueAttempts: 'Tentativas: {count}'
    }
  };

  // Language tags for `document.documentElement.lang`.
  const LOCALE_TAGS = {
    zh: 'zh-CN',
    en: 'en',
    es: 'es-ES',
    fr: 'fr-FR',
    de: 'de-DE',
    ja: 'ja-JP',
    ko: 'ko-KR',
    pt: 'pt-BR'
  };

  const LOCALE_PREFIXES = ['zh', 'en', 'es', 'fr', 'de', 'ja', 'ko', 'pt'];

  /**
   * Simple prefix match on a BCP 47 tag: zh-TW → zh, en-GB → en, es-419 → es,
   * pt-PT → pt, ja → ja. Anything unrecognized falls back to en.
   */
  function resolveLocale(language) {
    const value = String(language || '').trim().toLowerCase();
    if (!value) {
      return 'en';
    }
    for (const prefix of LOCALE_PREFIXES) {
      if (value === prefix || value.indexOf(`${prefix}-`) === 0 || value.indexOf(`${prefix}_`) === 0) {
        return prefix;
      }
    }
    return 'en';
  }

  /** BCP 47 tag for the resolved locale, for the popup root element. */
  function resolveLanguageTag(language) {
    return LOCALE_TAGS[resolveLocale(language)] || LOCALE_TAGS.en;
  }

  function copyFor(language) {
    const locale = resolveLocale(language);
    if (locale === 'en') {
      return Object.assign({}, COPY.en);
    }
    return Object.assign({}, COPY.en, COPY[locale]);
  }

  function formatCopy(template, values) {
    if (typeof template !== 'string') {
      return '';
    }
    return template.replace(/\{(\w+)\}/g, (match, key) => {
      if (values && Object.prototype.hasOwnProperty.call(values, key) && values[key] !== null && values[key] !== undefined) {
        return String(values[key]);
      }
      return match;
    });
  }

  // -------------------------------------------------------------------- urls --

  const TRACKING_PARAM_PATTERNS = [/^utm_/i];
  const TRACKING_PARAMS = new Set([
    '_ga',
    '_gl',
    'dclid',
    'fbclid',
    'gclid',
    'igshid',
    'mc_cid',
    'mc_eid',
    'ref_src',
    'ref_url',
    'scm',
    'spm',
    'trk',
    'twclid',
    'yclid'
  ]);

  function isTrackingParam(name) {
    const value = String(name || '');
    if (!value) {
      return false;
    }
    if (TRACKING_PARAM_PATTERNS.some((pattern) => pattern.test(value))) {
      return true;
    }
    return TRACKING_PARAMS.has(value.toLowerCase());
  }

  function httpUrlOnly(url) {
    return /^https?:\/\//i.test(String(url || '').trim());
  }

  /**
   * Canonical capture URL: no hash, no tracking parameters, no redundant
   * trailing slash. Returns '' for anything that is not http(s).
   */
  function normalizeCaptureUrl(rawUrl) {
    const input = String(rawUrl || '').trim();
    if (!httpUrlOnly(input)) {
      return '';
    }
    let parsed;
    try {
      parsed = new URL(input);
    } catch (_error) {
      return '';
    }
    parsed.hash = '';
    const kept = [];
    for (const [name, value] of parsed.searchParams.entries()) {
      if (!isTrackingParam(name)) {
        kept.push([name, value]);
      }
    }
    parsed.search = '';
    for (const [name, value] of kept) {
      parsed.searchParams.append(name, value);
    }
    if (parsed.pathname.length > 1) {
      const collapsed = parsed.pathname.replace(/\/+$/, '');
      parsed.pathname = collapsed || '/';
    }
    return parsed.href;
  }

  /**
   * Dedup key: canonical URL with parameters sorted, scoped by capture kind and
   * by the capture *action* — so the "README + structure" and "with docs/"
   * GitHub variants never collapse into one entry, and a download into the
   * project folder is never masked by an earlier add-to-library capture of the
   * same source (and vice versa). A download also carries its target folder:
   * the same PDF saved into two folders is two legitimate actions, while a
   * repeat into the same folder is a duplicate.
   */
  function buildDedupKey(target) {
    const normalized = normalizeCaptureUrl(target && target.url);
    if (!normalized) {
      return '';
    }
    const kind = normalizeKind(target && target.kind);
    const variant = buildDedupVariant(kind, target);
    let canonical = normalized;
    try {
      const parsed = new URL(normalized);
      const sorted = Array.from(parsed.searchParams.entries()).sort((first, second) => {
        if (first[0] !== second[0]) {
          return first[0] < second[0] ? -1 : 1;
        }
        return first[1] < second[1] ? -1 : first[1] > second[1] ? 1 : 0;
      });
      parsed.search = '';
      for (const [name, value] of sorted) {
        parsed.searchParams.append(name, value);
      }
      canonical = parsed.href;
    } catch (_error) {
      canonical = normalized;
    }
    const scope = [target && target.workspaceId || '', target && target.focusId || '', target && target.captureMode || 'snapshot', target && target.selection || ''];
    return `${kind}|${variant}|${canonical}|${JSON.stringify(scope)}`;
  }

  function buildDedupVariant(kind, target) {
    const parts = [];
    if (kind === 'github_repo' && target && target.includeDocs === true) {
      parts.push('docs');
    }
    if (isDownloadTarget(target)) {
      parts.push('download');
      parts.push(normalizeTargetDir(target && target.targetDir).toLowerCase());
    }
    return parts.length ? parts.join('+') : 'base';
  }

  function normalizeKind(value) {
    const kind = String(value || '').trim().toLowerCase();
    return CAPTURE_KINDS.indexOf(kind) >= 0 ? kind : 'web';
  }

  // -------------------------------------------------------------- download --

  function supportsDownload(kind) {
    return DOWNLOAD_KINDS.indexOf(normalizeKind(kind)) >= 0;
  }

  function isDownloadTarget(target) {
    return Boolean(target) && target.download === true && supportsDownload(target.kind);
  }

  /**
   * Normalize a user-supplied download folder into a project-relative path
   * ending with '/'. An empty value resolves to DEFAULT_TARGET_DIR; anything
   * the sidecar would reject — absolute path, drive letter, '~', '..', hidden
   * or reserved segments, over-long path — resolves to '' so the caller can
   * reject it instead of forwarding a dangerous path to the sidecar.
   */
  function normalizeTargetDir(value) {
    const raw = String(value === null || value === undefined ? '' : value)
      .trim()
      .replace(/\\/g, '/');
    if (!raw) {
      return DEFAULT_TARGET_DIR;
    }
    if (raw.startsWith('/') || raw.startsWith('~') || /^[A-Za-z]:/.test(raw)) {
      return '';
    }
    if (raw.length > MAX_TARGET_DIR_CHARS) {
      return '';
    }
    const segments = raw.split('/').map((segment) => segment.trim()).filter(Boolean);
    if (!segments.length) {
      return DEFAULT_TARGET_DIR;
    }
    if (segments.length > MAX_TARGET_DIR_DEPTH) {
      return '';
    }
    for (const segment of segments) {
      if (segment === '.' || segment === '..' || segment.startsWith('.')) {
        return '';
      }
      if (segment.length > MAX_TARGET_DIR_SEGMENT_CHARS) {
        return '';
      }
      // eslint-disable-next-line no-control-regex
      if (/[\u0000-\u001f<>:"|?*]/.test(segment)) {
        return '';
      }
      if (RESERVED_TARGET_DIR_SEGMENTS.has(segment.toLowerCase())) {
        return '';
      }
    }
    return `${segments.join('/')}/`;
  }

  /** True when the input is empty (default folder) or a safe relative folder. */
  function targetDirIsValid(value) {
    const raw = String(value === null || value === undefined ? '' : value).trim();
    if (!raw) {
      return true;
    }
    return normalizeTargetDir(raw) !== '';
  }

  function historySavedPath(entry) {
    return String((entry && entry.savedPath) || '').trim();
  }

  function isPdfUrl(url) {
    return /\.pdf(?:$|[?#])/i.test(String(url || ''));
  }

  function githubRepoLabel(url) {
    const match = String(url || '').match(
      /^https?:\/\/(?:www\.)?github\.com\/([A-Za-z0-9._-]+)\/([A-Za-z0-9._-]+?)(?:\.git)?(?:\/|$|[?#])/i
    );
    if (!match) {
      return null;
    }
    if (GITHUB_RESERVED_OWNERS.has(match[1].toLowerCase())) {
      return null;
    }
    return `${match[1]}/${match[2]}`;
  }

  function githubRepositoryUrl(url) {
    const label = githubRepoLabel(url);
    return label ? `https://github.com/${label}` : '';
  }

  function detectKind(url) {
    if (githubRepoLabel(url) && /^https?:\/\/(?:www\.)?github\.com\/[^/?#]+\/[^/?#]+\/?(?:[?#]|$)/i.test(url)) {
      return 'github_repo';
    }
    if (isPdfUrl(url)) {
      return 'pdf';
    }
    return 'web';
  }

  function buildDeepLink(resourceId) {
    const id = String(resourceId || '').trim();
    return id ? `${DEEP_LINK_PREFIX}${encodeURIComponent(id)}` : '';
  }

  function normalizeBaseUrl(value) {
    const raw = String(value || '').trim();
    if (!raw) {
      return '';
    }
    const withScheme = /^https?:\/\//i.test(raw) ? raw : `http://${raw}`;
    let parsed;
    try {
      parsed = new URL(withScheme);
    } catch (_error) {
      return '';
    }
    if (!parsed.hostname || !parsed.host) {
      return '';
    }
    const path = parsed.pathname.replace(/\/+$/, '');
    return `${parsed.protocol}//${parsed.host}${path}`;
  }

  // ----------------------------------------------------------------- probes --

  /**
   * Ordered, de-duplicated probe candidates: the last known base URL first
   * (fast path), then the sidecar default, then the VS Code managed range.
   */
  function buildProbeCandidates(options) {
    const opts = options || {};
    const host = String(opts.host || SIDECAR.host).trim() || SIDECAR.host;
    const defaultBaseUrl = normalizeBaseUrl(opts.defaultBaseUrl || SIDECAR.defaultBaseUrl);
    const rawStart = Number(opts.portStart);
    const rawEnd = Number(opts.portEnd);
    const start = Number.isFinite(rawStart) ? Math.trunc(rawStart) : SIDECAR.managedPortStart;
    const end = Number.isFinite(rawEnd) ? Math.trunc(rawEnd) : SIDECAR.managedPortEnd;
    const candidates = [];
    const push = (value) => {
      const normalized = normalizeBaseUrl(value);
      if (normalized && candidates.indexOf(normalized) < 0) {
        candidates.push(normalized);
      }
    };
    push(opts.storedBaseUrl);
    push(defaultBaseUrl);
    const low = Math.min(start, end);
    const high = Math.max(start, end);
    for (let port = low; port <= high; port += 1) {
      push(`http://${host}:${port}`);
    }
    return candidates;
  }

  // ------------------------------------------------------------------- ids --

  let clientIdCounter = 0;

  function createClientId(prefix, now, random) {
    clientIdCounter = (clientIdCounter + 1) % 46656;
    const time = Number.isFinite(now) ? now : Date.now();
    const sample = typeof random === 'function' ? random() : Math.random();
    const bounded = Math.max(0, Math.min(0.999999, Number(sample) || 0));
    const entropy = Math.floor(bounded * 36 ** 4).toString(36).padStart(4, '0');
    return `${prefix}-${time.toString(36)}-${clientIdCounter.toString(36).padStart(3, '0')}-${entropy}`;
  }

  function createClientCaptureId(now, random) {
    return createClientId('bc', now, random);
  }

  function createCoachDraftId(now, random) {
    return createClientId('bd', now, random);
  }

  function normalizePairCode(value) {
    const digits = String(value || '').replace(/[^0-9]/g, '');
    return digits.length === 6 ? digits : '';
  }

  function isValidPairCode(value) {
    return normalizePairCode(value).length === 6;
  }

  // ------------------------------------------------------------------ queue --

  function createQueueItem(input) {
    const source = input || {};
    const url = normalizeCaptureUrl(source.url);
    const kind = normalizeKind(source.kind);
    const download = isDownloadTarget({ download: source.download, kind });
    const item = {
      clientCaptureId: String(source.clientCaptureId || createClientCaptureId()),
      dedupKey: String(
        source.dedupKey ||
          buildDedupKey({
            ...source,
            url,
            kind,
            includeDocs: source.includeDocs,
            download,
            targetDir: source.targetDir
          })
      ),
      url,
      kind,
      workspaceId: String(source.workspaceId || '').trim(),
      workspaceName: String(source.workspaceName || '').trim(),
      captureMode: ['link', 'selection'].includes(source.captureMode) ? source.captureMode : 'snapshot',
      title: source.title ? String(source.title).trim() : '',
      selection: source.selection ? String(source.selection) : '',
      focusId: source.focusId ? String(source.focusId) : '',
      includeDocs: kind === 'github_repo' && source.includeDocs === true,
      download,
      targetDir: download ? normalizeTargetDir(source.targetDir) : '',
      createdAt: String(source.createdAt || new Date().toISOString()),
      attempts: Number.isFinite(source.attempts) ? Math.trunc(source.attempts) : 0,
      lastError: '',
      lastAttemptAt: ''
    };
    return item;
  }

  function enqueueCapture(queue, item, limit) {
    const cap = Number.isFinite(limit) ? Math.max(1, Math.trunc(limit)) : LIMITS.queue;
    const list = Array.isArray(queue) ? queue.slice() : [];
    const next = Object.assign({}, item);
    if (!next.dedupKey) {
      next.dedupKey = buildDedupKey(next);
    }
    if (!next.clientCaptureId) {
      next.clientCaptureId = createClientCaptureId();
    }
    if (!next.createdAt) {
      next.createdAt = new Date().toISOString();
    }
    if (!Number.isFinite(next.attempts)) {
      next.attempts = 0;
    }
    if (next.workspaceId === undefined) {
      next.workspaceId = '';
    }
    const alreadyQueued = list.some(
      (entry) =>
        entry.clientCaptureId === next.clientCaptureId ||
        (entry.dedupKey && entry.dedupKey === next.dedupKey)
    );
    if (alreadyQueued) {
      return { queue: list, added: false, dropped: [], rejectedFull: false };
    }
    // Accepted-but-undelivered work must never be silently evicted: a full
    // queue rejects the new capture and the caller reports it honestly.
    if (list.length >= cap) {
      return { queue: list, added: false, dropped: [], rejectedFull: true };
    }
    list.push(next);
    return { queue: list, added: true, dropped: [], rejectedFull: false };
  }

  function dequeueCapture(queue, clientCaptureId) {
    return (Array.isArray(queue) ? queue : []).filter(
      (entry) => entry.clientCaptureId !== clientCaptureId
    );
  }

  /** Pure alias used by the popup queue manager (same semantics as dequeue). */
  function removeQueueItem(queue, clientCaptureId) {
    return dequeueCapture(queue, clientCaptureId);
  }

  /** Pure queue manager "clear": no entries, same as a never-used queue. */
  function clearQueue() {
    return [];
  }

  function markQueueAttempt(queue, clientCaptureId, error, at) {
    const stamp = String(at || new Date().toISOString());
    return (Array.isArray(queue) ? queue : []).map((entry) => {
      if (entry.clientCaptureId !== clientCaptureId) {
        return entry;
      }
      return Object.assign({}, entry, {
        attempts: (Number.isFinite(entry.attempts) ? entry.attempts : 0) + 1,
        lastAttemptAt: stamp,
        lastError: error ? String(error) : ''
      });
    });
  }

  function takeNextQueueItem(queue) {
    return Array.isArray(queue) && queue.length ? queue[0] : null;
  }

  function summarizeQueue(queue) {
    const list = Array.isArray(queue) ? queue : [];
    return { count: list.length, next: list.length ? list[0] : null };
  }

  // -------------------------------------------------- coach-draft queue ----
  // Selections are just as valuable as page captures: losing one because the
  // sidecar was down is the same broken promise. Drafts get their own queue
  // with the workspace they were captured under.

  function createDraftQueueItem(input) {
    const source = input || {};
    const selection = String(source.selection || '').trim();
    if (!selection) {
      return null;
    }
    return {
      clientDraftId: String(source.clientDraftId || createCoachDraftId()),
      selection,
      url: normalizeCaptureUrl(source.url) || String(source.url || '').trim(),
      title: String(source.title || '').trim(),
      workspaceId: String(source.workspaceId || '').trim(),
      createdAt: String(source.createdAt || new Date().toISOString()),
      attempts: Number.isFinite(source.attempts) ? Math.trunc(source.attempts) : 0,
      lastError: '',
      lastAttemptAt: ''
    };
  }

  function enqueueDraft(queue, item, limit) {
    const cap = Number.isFinite(limit) ? Math.max(1, Math.trunc(limit)) : LIMITS.queue;
    const list = Array.isArray(queue) ? queue.slice() : [];
    if (!item) {
      return { queue: list, added: false, rejectedFull: false };
    }
    if (list.some((entry) => entry.clientDraftId === item.clientDraftId)) {
      return { queue: list, added: false, rejectedFull: false };
    }
    if (list.length >= cap) {
      return { queue: list, added: false, rejectedFull: true };
    }
    list.push(item);
    return { queue: list, added: true, rejectedFull: false };
  }

  function dequeueDraft(queue, clientDraftId) {
    return (Array.isArray(queue) ? queue : []).filter(
      (entry) => entry.clientDraftId !== clientDraftId
    );
  }

  function markDraftAttempt(queue, clientDraftId, error, at) {
    const stamp = String(at || new Date().toISOString());
    return (Array.isArray(queue) ? queue : []).map((entry) => {
      if (entry.clientDraftId !== clientDraftId) {
        return entry;
      }
      return Object.assign({}, entry, {
        attempts: (Number.isFinite(entry.attempts) ? entry.attempts : 0) + 1,
        lastAttemptAt: stamp,
        lastError: error ? String(error) : ''
      });
    });
  }

  function takeNextDraft(queue) {
    return Array.isArray(queue) && queue.length ? queue[0] : null;
  }

  /**
   * Client-side duplicate hint. The sidecar stays authoritative (client_capture_id
   * idempotency + server dedup), this only avoids double capture/queueing.
   * Failed history entries never count as duplicates.
   */
  function findLocalDuplicate(sources, dedupKey) {
    const key = String(dedupKey || '');
    if (!key) {
      return null;
    }
    const queue = sources && Array.isArray(sources.queue) ? sources.queue : [];
    const queued = queue.find((entry) => entry && entry.dedupKey === key);
    if (queued) {
      return { where: 'queue', entry: queued };
    }
    const history = sources && Array.isArray(sources.history) ? sources.history : [];
    const recorded = history.find(
      (entry) =>
        entry &&
        entry.dedupKey === key &&
        (entry.status === 'ok' || entry.status === 'duplicated')
    );
    if (recorded) {
      return { where: 'history', entry: recorded };
    }
    return null;
  }

  // --------------------------------------------------------------- payloads --

  function buildCapturePayload(input) {
    const source = input || {};
    const url = normalizeCaptureUrl(source.url);
    const kind = normalizeKind(source.kind);
    const payload = {
      url,
      kind,
      client_capture_id: String(source.clientCaptureId || '')
    };
    // Workspace identity: lets the sidecar reject any capture that arrives at
    // a different workspace than the one that accepted it (T-0008).
    const workspaceId = String(source.workspaceId || '').trim();
    if (workspaceId) {
      payload.workspace_id = workspaceId;
    }
    if (source.captureMode === 'link' || source.captureMode === 'selection') {
      payload.capture_mode = source.captureMode;
    }
    const title = String(source.title || '').trim();
    if (title) {
      payload.title = title;
    }
    const selection = String(source.selection || '');
    if (selection) {
      payload.selection = selection;
    }
    const focusId = String(source.focusId || '').trim();
    if (focusId) {
      payload.bind_focus_id = focusId;
    }
    if (kind === 'github_repo' && source.includeDocs === true) {
      payload.include_docs = true;
    }
    // Download-to-project-folder variant (task 二): the sidecar both indexes
    // the source and saves it under the workspace-relative target folder.
    if (isDownloadTarget({ download: source.download, kind })) {
      payload.download = true;
      payload.target_dir = normalizeTargetDir(source.targetDir);
    }
    return payload;
  }

  function buildCoachDraftPayload(input) {
    const source = input || {};
    const selection = String(source.selection || '').trim();
    if (!selection) {
      return null;
    }
    const url = normalizeCaptureUrl(source.url) || String(source.url || '').trim();
    return {
      selection,
      url,
      title: String(source.title || '').trim(),
      client_id: String(source.clientId || createCoachDraftId())
    };
  }

  function normalizeCaptureResponse(body) {
    const record = body && typeof body === 'object' ? body : {};
    const resourceId = record.resource_id ? String(record.resource_id) : '';
    const deepLink = String(record.deep_link || '').trim() || buildDeepLink(resourceId);
    const savedPath = String(record.saved_path || record.savedPath || '').trim();
    return { resourceId, deduped: record.deduped === true, deepLink, savedPath };
  }

  /**
   * Accepts both the raw /browser/status body (snake_case) and an already
   * normalized payload, so caching can never strip the values back to empty.
   */
  function normalizeStatusPayload(body) {
    const source = body && typeof body === 'object' ? body : {};
    const rawOptions = Array.isArray(source.focus_options)
      ? source.focus_options
      : Array.isArray(source.focusOptions)
        ? source.focusOptions
        : [];
    const rawCount = source.library_count !== undefined ? source.library_count : source.libraryCount;
    const count = Number(rawCount);
    return {
      workspaceId: String(source.workspace_id || source.workspaceId || '').trim(),
      workspaceName: String(source.workspace_name || source.workspaceName || '').trim(),
      libraryCount: Number.isFinite(count) ? count : 0,
      focusOptions: rawOptions
        .map((option) => ({
          id: String((option && option.id) || ''),
          label: String((option && option.label) || '')
        }))
        .filter((option) => option.id && option.label)
    };
  }

  function captureLabel(target) {
    const source = target || {};
    const title = String(source.title || '').trim();
    if (title) {
      return title;
    }
    return String(source.url || '').trim();
  }

  function kindCopyKey(kind) {
    if (kind === 'pdf') {
      return 'kindPdf';
    }
    if (kind === 'github_repo') {
      return 'kindGithub';
    }
    if (kind === 'web') {
      return 'kindWeb';
    }
    return 'kindUnknown';
  }

  function statusCopyKey(status) {
    if (status === 'ok') {
      return 'statusOk';
    }
    if (status === 'duplicated') {
      return 'statusDuplicated';
    }
    if (status === 'queued') {
      return 'statusQueued';
    }
    return 'statusFailed';
  }

  // ----------------------------------------------------------------- errors --

  function describeHttpError(status, body, copy) {
    const dict = copy || COPY.en;
    const detail = body && typeof body === 'object' ? body.detail : null;
    const code = detail && typeof detail === 'object' ? String(detail.code || '') : '';
    const message =
      detail && typeof detail === 'object'
        ? String(detail.message || '')
        : typeof detail === 'string'
          ? detail
          : '';

    if (status === 401 || status === 403) {
      return dict.errUnauthorized;
    }
    if (status === 409 && code === 'network_disabled') {
      return dict.errNetworkDisabled;
    }
    if (status === 409 && code === 'browse_only_persistence_blocked') {
      return dict.errBrowseOnly;
    }
    if (status === 404 && code === 'readme_not_found') {
      return message || dict.errReadmeNotFound;
    }
    if (message) {
      return formatCopy(dict.errServerMessage, { status, message });
    }
    return formatCopy(dict.errServerStatus, { status });
  }

  function describeTransportError(error, copy) {
    const dict = copy || COPY.en;
    const name = error && error.name ? String(error.name) : '';
    return name === 'AbortError' ? dict.errTimeout : dict.errUnreachable;
  }

  function formatTimestamp(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return '';
    }
    const pad = (part) => String(part).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  // =========================================================================
  // 2. Chrome wrappers (storage / fetch / locale) — thin by design
  // =========================================================================

  const REQUEST_TIMEOUT_MS = 120000;
  const PAIR_TIMEOUT_MS = 15000;
  const STATUS_TIMEOUT_MS = 8000;

  function browserLocale() {
    try {
      if (typeof chrome !== 'undefined' && chrome.i18n && typeof chrome.i18n.getUILanguage === 'function') {
        const value = chrome.i18n.getUILanguage();
        if (value) {
          return value;
        }
      }
    } catch (_error) {
      /* fall through to navigator */
    }
    try {
      if (typeof navigator !== 'undefined' && navigator.language) {
        return navigator.language;
      }
    } catch (_error) {
      /* fall through to English */
    }
    return 'en';
  }

  function activeCopy() {
    return copyFor(browserLocale());
  }

  async function requestJson(options) {
    const controller = new AbortController();
    const timeoutMs = Number.isFinite(options.timeoutMs) ? options.timeoutMs : REQUEST_TIMEOUT_MS;
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const headers = { 'Content-Type': 'application/json' };
      if (options.credential) {
        headers.Authorization = `Bearer ${options.credential}`;
      }
      const response = await fetch(`${options.baseUrl}${options.path}`, {
        method: options.method || 'GET',
        headers,
        body: options.body ? JSON.stringify(options.body) : undefined,
        signal: controller.signal
      });
      let text = '';
      try {
        text = await response.text();
      } catch (_error) {
        text = '';
      }
      let body = null;
      try {
        body = text ? JSON.parse(text) : null;
      } catch (_error) {
        body = null;
      }
      return { ok: response.ok, status: response.status, body, transportError: '' };
    } catch (error) {
      const aborted = error && error.name === 'AbortError';
      return { ok: false, status: 0, body: null, transportError: aborted ? 'timeout' : 'network' };
    } finally {
      clearTimeout(timer);
    }
  }

  function isRetryableStatus(status, transportError) {
    if (transportError) {
      return true;
    }
    return status === 408 || status === 429 || status >= 500;
  }

  async function probeBaseUrl(baseUrl, timeoutMs) {
    const result = await requestJson({
      baseUrl,
      path: API.health,
      method: 'GET',
      timeoutMs: Number.isFinite(timeoutMs) ? timeoutMs : SIDECAR.probeTimeoutMs
    });
    if (result.status === 0) {
      return { baseUrl, reachable: false, needsAuth: false };
    }
    return {
      baseUrl,
      reachable: true,
      needsAuth: result.status === 401 || result.status === 403,
      status: result.status
    };
  }

  /**
   * Probe the stored URL and the default port first, then the managed range in
   * parallel. Any HTTP answer (even 401) means "Trainer is here".
   */
  async function discoverSidecar(options) {
    const candidates = buildProbeCandidates(options || {});
    if (!candidates.length) {
      return { found: false, baseUrl: '', baseUrls: [], needsAuth: false, candidates };
    }
    const fast = candidates.slice(0, 2);
    const slow = candidates.slice(2);
    const hits = [];
    const settle = async (list) => {
      const results = await Promise.all(list.map((candidate) => probeBaseUrl(candidate)));
      for (const entry of results) {
        if (entry.reachable) hits.push(entry);
      }
      return hits[0] || null;
    };
    await settle(fast);
    // Probe the managed range even when the default port answers: with two
    // VS Code windows the default 8765 sidecar may belong to a different
    // window than the one that minted this pairing code.
    if (slow.length) {
      await settle(slow);
    }
    return {
      found: hits.length > 0,
      baseUrl: hits[0] ? hits[0].baseUrl : '',
      // Multiple VS Code windows run independent sidecars. Pairing must try
      // every reachable instance: the first one is not necessarily the window
      // that minted the code.
      baseUrls: hits.map((entry) => entry.baseUrl),
      needsAuth: hits[0] ? hits[0].needsAuth : false,
      candidates,
    };
  }

  async function pairSidecar(baseUrl, code) {
    const dict = activeCopy();
    const normalized = normalizePairCode(code);
    if (!normalized) {
      return { ok: false, reason: 'invalid_code', message: dict.pairInvalidCode };
    }
    const base = normalizeBaseUrl(baseUrl);
    if (!base) {
      return { ok: false, reason: 'invalid_base_url', message: dict.pairTransport };
    }
    const result = await requestJson({
      baseUrl: base,
      path: API.pair,
      method: 'POST',
      body: { code: normalized },
      timeoutMs: PAIR_TIMEOUT_MS
    });
    if (!result.ok) {
      if (result.status === 401 || result.status === 403 || result.status === 404 || result.status === 422) {
        return { ok: false, reason: 'rejected', status: result.status, message: dict.pairCodeRejected };
      }
      const message = result.transportError
        ? dict.pairTransport
        : describeHttpError(result.status, result.body, dict);
      return { ok: false, reason: result.transportError ? 'transport' : 'http', status: result.status, message };
    }
    const credential = String((result.body && result.body.credential) || '').trim();
    if (!credential) {
      return { ok: false, reason: 'empty_credential', message: dict.pairCodeRejected };
    }
    const workspaceId = String((result.body && result.body.workspace_id) || '').trim();
    return { ok: true, credential, baseUrl: base, workspaceId };
  }

  async function autoPairSidecar(baseUrl) {
    const dict = activeCopy();
    const base = normalizeBaseUrl(baseUrl);
    if (!base) {
      return { ok: false, reason: 'invalid_base_url', message: dict.pairTransport };
    }
    const result = await requestJson({
      baseUrl: base,
      path: API.autoPair,
      method: 'POST',
      body: {},
      timeoutMs: PAIR_TIMEOUT_MS
    });
    if (!result.ok) {
      const message = result.transportError
        ? dict.pairTransport
        : describeHttpError(result.status, result.body, dict);
      return {
        ok: false,
        reason: result.transportError ? 'transport' : 'http',
        status: result.status,
        message
      };
    }
    const credential = String((result.body && result.body.credential) || '').trim();
    if (!credential) {
      return { ok: false, reason: 'empty_credential', message: dict.pairCodeRejected };
    }
    return {
      ok: true,
      credential,
      baseUrl: base,
      workspaceId: String((result.body && result.body.workspace_id) || '').trim(),
      workspaceName: String((result.body && result.body.workspace_name) || '').trim()
    };
  }

  async function revokePairing(baseUrl, credential) {
    const dict = activeCopy();
    const base = normalizeBaseUrl(baseUrl);
    if (!base || !credential) {
      return { ok: false, message: dict.pairRevokeLocalOnly };
    }
    const result = await requestJson({
      baseUrl: base,
      path: API.pair,
      method: 'DELETE',
      credential,
      timeoutMs: STATUS_TIMEOUT_MS
    });
    if (result.ok || result.status === 401 || result.status === 403 || result.status === 404) {
      // 401/403/404 mean the sidecar cannot know that credential either.
      return { ok: result.ok, message: dict.pairRevokeDone };
    }
    return { ok: false, message: dict.pairRevokeLocalOnly };
  }

  async function fetchStatus(baseUrl, credential) {
    const dict = activeCopy();
    const result = await requestJson({
      baseUrl,
      path: API.status,
      method: 'GET',
      credential,
      timeoutMs: STATUS_TIMEOUT_MS
    });
    if (!result.ok) {
      return {
        ok: false,
        status: result.status,
        unauthorized: result.status === 401 || result.status === 403,
        retryable: isRetryableStatus(result.status, result.transportError),
        transportError: result.transportError,
        message: result.transportError
          ? describeTransportError({ name: result.transportError === 'timeout' ? 'AbortError' : '' }, dict)
          : describeHttpError(result.status, result.body, dict)
      };
    }
    return { ok: true, status: normalizeStatusPayload(result.body) };
  }

  async function sendCapture(baseUrl, credential, payload) {
    const dict = activeCopy();
    const result = await requestJson({
      baseUrl,
      path: API.capture,
      method: 'POST',
      credential,
      body: payload,
      timeoutMs: REQUEST_TIMEOUT_MS
    });
    if (!result.ok) {
      return {
        ok: false,
        status: result.status,
        unauthorized: result.status === 401 || result.status === 403,
        retryable: isRetryableStatus(result.status, result.transportError),
        transportError: result.transportError,
        message: result.transportError
          ? describeTransportError({ name: result.transportError === 'timeout' ? 'AbortError' : '' }, dict)
          : describeHttpError(result.status, result.body, dict)
      };
    }
    const normalized = normalizeCaptureResponse(result.body);
    return {
      ok: true,
      status: result.status,
      resourceId: normalized.resourceId,
      deduped: normalized.deduped,
      deepLink: normalized.deepLink,
      savedPath: normalized.savedPath
    };
  }

  async function sendCoachDraft(baseUrl, credential, payload) {
    const dict = activeCopy();
    const result = await requestJson({
      baseUrl,
      path: API.coachDraft,
      method: 'POST',
      credential,
      body: payload,
      timeoutMs: STATUS_TIMEOUT_MS
    });
    if (!result.ok) {
      return {
        ok: false,
        status: result.status,
        unauthorized: result.status === 401 || result.status === 403,
        message: result.transportError
          ? describeTransportError({ name: result.transportError === 'timeout' ? 'AbortError' : '' }, dict)
          : describeHttpError(result.status, result.body, dict)
      };
    }
    return { ok: true, status: result.status, accepted: !(result.body && result.body.ok === false) };
  }

  async function loadAuth() {
    const stored = await chrome.storage.local.get({
      [STORAGE_KEYS.baseUrl]: '',
      [STORAGE_KEYS.credential]: '',
      [STORAGE_KEYS.workspaceId]: ''
    });
    return {
      baseUrl: normalizeBaseUrl(stored[STORAGE_KEYS.baseUrl]),
      credential: String(stored[STORAGE_KEYS.credential] || '').trim(),
      workspaceId: String(stored[STORAGE_KEYS.workspaceId] || '').trim()
    };
  }

  async function saveAuth(baseUrl, credential, workspaceId) {
    const normalized = normalizeBaseUrl(baseUrl);
    const token = String(credential || '').trim();
    if (!normalized || !token) {
      return loadAuth();
    }
    // Pin the paired workspace so in-flight/queued captures carry the identity
    // they were accepted under (issue T-0008). Re-pairing replaces it.
    const updates = {
      [STORAGE_KEYS.baseUrl]: normalized,
      [STORAGE_KEYS.credential]: token
    };
    if (workspaceId !== undefined) {
      updates[STORAGE_KEYS.workspaceId] = String(workspaceId || '').trim();
    }
    await chrome.storage.local.set(updates);
    return { baseUrl: normalized, credential: token, workspaceId: String(workspaceId || '').trim() };
  }

  async function clearAuth() {
    await chrome.storage.local.remove([
      STORAGE_KEYS.baseUrl,
      STORAGE_KEYS.credential,
      STORAGE_KEYS.connection,
      STORAGE_KEYS.statusCache,
      STORAGE_KEYS.notice
    ]);
  }

  async function loadHistory() {
    const stored = await chrome.storage.local.get({ [STORAGE_KEYS.history]: [] });
    const entries = stored[STORAGE_KEYS.history];
    return Array.isArray(entries) ? entries : [];
  }

  async function clearHistory() {
    await chrome.storage.local.remove(STORAGE_KEYS.history);
  }

  async function recordHistory(entry, limit) {
    const history = await loadHistory();
    const cap = Number.isFinite(limit) ? Math.max(1, Math.trunc(limit)) : LIMITS.historyStore;
    const next = [entry, ...history].slice(0, cap);
    await chrome.storage.local.set({ [STORAGE_KEYS.history]: next });
    return next;
  }

  async function loadQueue() {
    const stored = await chrome.storage.local.get({ [STORAGE_KEYS.queue]: [] });
    const queue = stored[STORAGE_KEYS.queue];
    return Array.isArray(queue) ? queue : [];
  }

  async function saveQueue(queue) {
    await chrome.storage.local.set({ [STORAGE_KEYS.queue]: Array.isArray(queue) ? queue : [] });
  }

  async function loadDraftQueue() {
    const stored = await chrome.storage.local.get({ [STORAGE_KEYS.draftQueue]: [] });
    const queue = stored[STORAGE_KEYS.draftQueue];
    return Array.isArray(queue) ? queue : [];
  }

  async function saveDraftQueue(queue) {
    await chrome.storage.local.set({
      [STORAGE_KEYS.draftQueue]: Array.isArray(queue) ? queue : []
    });
  }

  async function loadWorkspaceName() {
    const stored = await chrome.storage.local.get({ [STORAGE_KEYS.workspaceName]: '' });
    return String(stored[STORAGE_KEYS.workspaceName] || '').trim();
  }

  async function saveWorkspaceName(name) {
    const value = String(name || '').trim();
    await chrome.storage.local.set({ [STORAGE_KEYS.workspaceName]: value });
    return value;
  }

  async function loadFocusId() {
    const stored = await chrome.storage.local.get({ [STORAGE_KEYS.focusId]: '' });
    return String(stored[STORAGE_KEYS.focusId] || '').trim();
  }

  async function saveFocusId(focusId) {
    const value = String(focusId || '').trim();
    await chrome.storage.local.set({ [STORAGE_KEYS.focusId]: value });
    return value;
  }

  /** Download folder: stored normalized, empty input falls back to the default. */
  async function loadTargetDir() {
    const stored = await chrome.storage.local.get({ [STORAGE_KEYS.targetDir]: '' });
    return normalizeTargetDir(stored[STORAGE_KEYS.targetDir]);
  }

  async function saveTargetDir(targetDir) {
    const value = normalizeTargetDir(targetDir);
    await chrome.storage.local.set({ [STORAGE_KEYS.targetDir]: value });
    return value;
  }

  /**
   * Last observed sidecar reachability: 'ok' (Trainer answered), 'offline'
   * (paired but unreachable) or 'unknown' (never checked / unpaired). The popup
   * needs it to tell "Trainer is not running" apart from "not paired yet".
   */
  async function loadConnection() {
    const stored = await chrome.storage.local.get({ [STORAGE_KEYS.connection]: 'unknown' });
    const value = String(stored[STORAGE_KEYS.connection] || '');
    return value === 'ok' || value === 'offline' ? value : 'unknown';
  }

  async function saveConnection(state) {
    const value = state === 'ok' || state === 'offline' ? state : 'unknown';
    await chrome.storage.local.set({ [STORAGE_KEYS.connection]: value });
    return value;
  }

  async function loadStatusCache() {
    const stored = await chrome.storage.local.get({ [STORAGE_KEYS.statusCache]: null });
    return normalizeStatusPayload(stored[STORAGE_KEYS.statusCache]);
  }

  async function saveStatusCache(status) {
    await chrome.storage.local.set({ [STORAGE_KEYS.statusCache]: normalizeStatusPayload(status) });
  }

  async function loadNotice() {
    const stored = await chrome.storage.local.get({ [STORAGE_KEYS.notice]: '' });
    return String(stored[STORAGE_KEYS.notice] || '');
  }

  async function saveNotice(message) {
    await chrome.storage.local.set({ [STORAGE_KEYS.notice]: String(message || '') });
  }

  async function clearNotice() {
    await chrome.storage.local.set({ [STORAGE_KEYS.notice]: '' });
  }

  // =========================================================================
  // 3. Content-script page affordance: the PDF auto-float button.
  //
  // shared.js is the declarative content script for http(s) pages (see
  // manifest.json content_scripts), so this section runs on every page — and
  // stays completely inert unless the document itself is a PDF
  // (document.contentType === 'application/pdf'). Nothing is read from the
  // page: the button only forwards location.href and the document title after
  // the user clicks it.
  // =========================================================================

  const PDF_FLOAT_BUTTON_ID = 'trainer-capture-pdf-float';

  function pdfFloatStyles() {
    return [
      'position: fixed',
      'right: 18px',
      'bottom: 18px',
      'z-index: 2147483647',
      'padding: 8px 14px',
      'border: 1px solid rgba(15, 23, 42, 0.18)',
      'border-radius: 999px',
      'background: #2563eb',
      'color: #ffffff',
      'font: 600 12px/1.2 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif',
      'box-shadow: 0 6px 18px rgba(15, 23, 42, 0.28)',
      'cursor: pointer'
    ].join('; ');
  }

  function createPdfFloatButton(page) {
    const dict = copyFor(browserLocale());
    const label = (key) => String(dict[key] || '');
    const button = page.createElement('button');
    button.id = PDF_FLOAT_BUTTON_ID;
    button.type = 'button';
    button.textContent = label('pdfButton');
    button.title = label('pdfTitle');
    button.setAttribute('aria-label', label('pdfTitle'));
    button.style.cssText = pdfFloatStyles();

    let busy = false;
    const settle = (text, disable) => {
      button.textContent = text;
      if (disable) {
        button.disabled = true;
        button.style.cursor = 'default';
      }
    };

    button.addEventListener('click', () => {
      if (busy || button.disabled) {
        return;
      }
      busy = true;
      button.textContent = label('pdfWorking');
      chrome.runtime.sendMessage(
        { type: 'trainer:pdf-capture', url: location.href, title: document.title || '' },
        (response) => {
          busy = false;
          if (chrome.runtime.lastError) {
            settle(label('pdfFailed'), false);
            return;
          }
          const status = response && response.status ? String(response.status) : 'failed';
          if (status === 'ok') {
            settle(label('pdfDone'), true);
            return;
          }
          if (status === 'duplicated' || status === 'duplicate-local') {
            settle(label('pdfDuplicate'), true);
            return;
          }
          if (status === 'queued') {
            settle(label('pdfQueued'), false);
            return;
          }
          if (status === 'unpaired') {
            settle(label('pdfNeedsPair'), false);
            return;
          }
          settle(label('pdfFailed'), false);
        }
      );
    });

    return button;
  }

  function mountPdfFloatButton() {
    try {
      if (typeof document === 'undefined' || !document) {
        return;
      }
      if (document.contentType !== 'application/pdf') {
        return;
      }
      if (document.getElementById(PDF_FLOAT_BUTTON_ID)) {
        return;
      }
      if (typeof chrome === 'undefined' || !chrome.runtime || typeof chrome.runtime.sendMessage !== 'function') {
        return;
      }
      const attach = () => {
        const root = document.body || document.documentElement;
        if (root && !document.getElementById(PDF_FLOAT_BUTTON_ID)) {
          root.appendChild(createPdfFloatButton(document));
        }
      };
      if (document.body) {
        attach();
      } else {
        document.addEventListener('DOMContentLoaded', attach, { once: true });
      }
    } catch (error) {
      // A content script must never break the page it runs on.
      console.warn('Trainer Capture PDF button failed:', error);
    }
  }

  mountPdfFloatButton();

  global.TrainerCapture = {
    // pure
    API,
    COPY,
    LIMITS,
    SIDECAR,
    STORAGE_KEYS,
    DEFAULT_TARGET_DIR,
    DOWNLOAD_KINDS,
    DEEP_LINK_PREFIX,
    HOST_DEEP_LINK,
    resolveLocale,
    resolveLanguageTag,
    copyFor,
    formatCopy,
    isTrackingParam,
    httpUrlOnly,
    normalizeCaptureUrl,
    buildDedupKey,
    buildDedupVariant,
    normalizeKind,
    isPdfUrl,
    githubRepoLabel,
    githubRepositoryUrl,
    detectKind,
    buildDeepLink,
    normalizeBaseUrl,
    buildProbeCandidates,
    createClientId,
    createClientCaptureId,
    createCoachDraftId,
    normalizePairCode,
    isValidPairCode,
    supportsDownload,
    isDownloadTarget,
    normalizeTargetDir,
    targetDirIsValid,
    historySavedPath,
    createQueueItem,
    enqueueCapture,
    dequeueCapture,
    removeQueueItem,
    clearQueue,
    markQueueAttempt,
    takeNextQueueItem,
    summarizeQueue,
    createDraftQueueItem,
    enqueueDraft,
    dequeueDraft,
    markDraftAttempt,
    takeNextDraft,
    findLocalDuplicate,
    buildCapturePayload,
    buildCoachDraftPayload,
    normalizeCaptureResponse,
    normalizeStatusPayload,
    captureLabel,
    kindCopyKey,
    statusCopyKey,
    describeHttpError,
    describeTransportError,
    formatTimestamp,
    isRetryableStatus,
    // chrome wrappers
    browserLocale,
    activeCopy,
    requestJson,
    probeBaseUrl,
    discoverSidecar,
    pairSidecar,
    autoPairSidecar,
    revokePairing,
    fetchStatus,
    sendCapture,
    sendCoachDraft,
    loadAuth,
    saveAuth,
    clearAuth,
    loadHistory,
    clearHistory,
    recordHistory,
    loadQueue,
    saveQueue,
    loadDraftQueue,
    saveDraftQueue,
    loadWorkspaceName,
    saveWorkspaceName,
    loadFocusId,
    saveFocusId,
    loadTargetDir,
    saveTargetDir,
    loadConnection,
    saveConnection,
    loadStatusCache,
    saveStatusCache,
    loadNotice,
    saveNotice,
    clearNotice
  };
})(typeof self !== 'undefined' ? self : globalThis);

if (typeof module !== 'undefined' && module.exports) {
  module.exports = globalThis.TrainerCapture;
}
