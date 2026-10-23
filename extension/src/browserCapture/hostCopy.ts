import { isComposerLanguage, type ComposerLanguage } from '../../../shared/src/types';

/**
 * Host-side browser-capture copy (information bars, action labels and the
 * deep-link diagnostics that surface in the Trainer output channel).
 *
 * Same mechanism as `providerHostCopy.ts`: one table keyed by
 * `ComposerLanguage` (compile-time completeness for all eight languages), a
 * prefix-based locale resolver and a `{placeholder}` formatter. This module
 * deliberately stays free of the `vscode` module (like `installBundle.ts`) so
 * it can be unit-tested without an extension host; callers resolve the UI
 * language themselves and pass it in.
 */

export type BrowserCaptureHostCopyKey =
  | 'installReady'
  | 'installStepExtensions'
  | 'installStepDeveloperMode'
  | 'installStepLoadUnpacked'
  | 'installStepPair'
  | 'installFolderFallback'
  | 'openExtensionsPage'
  | 'noChromiumBrowserFound'
  | 'browserOpenFailed'
  | 'copyFolderPath'
  | 'copyCode'
  | 'installBundleMissing'
  | 'installFailed'
  | 'installSucceeded'
  | 'sidecarUnavailable'
  | 'pairingCodeSummaryOne'
  | 'pairingCodeSummaryMany'
  | 'pairingCodeIssued'
  | 'pairingRegisterFailed'
  | 'pairingRevokedHadCode'
  | 'pairingRevokedIdle'
  | 'pairingRevokeFailed'
  | 'deepLinkIgnoredLog'
  | 'deepLinkUnconfirmedLog'
  | 'deepLinkOpenedLog';

type BrowserCaptureHostCopyTable = Record<BrowserCaptureHostCopyKey, string>;

export const browserCaptureHostCopyTable: Record<ComposerLanguage, BrowserCaptureHostCopyTable> = {
  'zh-CN': {
    installReady: '{label} 已就绪。',
    installStepExtensions: '1. 打开浏览器的扩展页：chrome://extensions、edge://extensions、brave://extensions、opera://extensions、vivaldi://extensions（Arc 用 arc://extensions）。',
    installStepDeveloperMode: '2. 开启开发者模式。',
    installStepLoadUnpacked: '3. 选择“加载已解压的扩展程序”，选中 {dir}。',
    installStepPair: '4. 在 Trainer 设置中点“显示配对码”，再到扩展弹窗输入。',
    installFolderFallback: 'Trainer 无法自动打开该文件夹。请在文件管理器中手动打开：{dir}',
    openExtensionsPage: '打开扩展页',
    noChromiumBrowserFound: '没有检测到 Chromium 浏览器。请手动打开 Chrome、Edge、Brave、Arc、Opera 或 Vivaldi 的扩展页。',
    browserOpenFailed: 'Trainer 无法打开 {browser}：{reason}',
    copyFolderPath: '复制文件夹路径',
    copyCode: '复制配对码',
    installBundleMissing:
      '当前 Trainer 构建未内置浏览器采集拓展。请安装包含 browser-capture/ 的 Trainer VSIX。',
    installFailed: 'Trainer 无法安装浏览器采集拓展：{reason}',
    installSucceeded:
      '{label} 已安装到 {dir}。请在浏览器的扩展页中以“加载已解压的扩展程序”方式加载。',
    sidecarUnavailable: 'Trainer 暂时不可用。',
    pairingCodeSummaryOne: '请在 1 分钟内将此配对码输入 Trainer 采集弹窗（单次有效）。',
    pairingCodeSummaryMany: '请在 {minutes} 分钟内将此配对码输入 Trainer 采集弹窗（单次有效）。',
    pairingCodeIssued: 'Trainer 浏览器配对码已生成。请在 Trainer 采集弹窗中输入。',
    pairingRegisterFailed: 'Trainer 无法注册浏览器配对码：{reason}',
    pairingRevokedHadCode: '浏览器配对已撤销，采集拓展需要重新配对。',
    pairingRevokedIdle: '浏览器配对已撤销，没有等待使用的配对码。',
    pairingRevokeFailed: 'Trainer 无法撤销浏览器配对：{reason}',
    deepLinkIgnoredLog: '已忽略无法识别的深链：{uri}',
    deepLinkUnconfirmedLog: '资源 {resourceId} 的深链在 {attempts} 次尝试后仍无法确认工作台可见',
    deepLinkOpenedLog: '深链已打开资源 {resourceId}（投递尝试 {attempts} 次）',
  },
  'en-US': {
    installReady: '{label} is ready.',
    installStepExtensions: '1. Open your browser\'s extensions page: chrome://extensions, edge://extensions, brave://extensions, opera://extensions, vivaldi://extensions (Arc: arc://extensions).',
    installStepDeveloperMode: '2. Turn on Developer mode.',
    installStepLoadUnpacked: '3. Choose "Load unpacked" and select {dir}.',
    installStepPair: '4. In Trainer Settings, choose "Show pairing code", then enter it in the extension popup.',
    installFolderFallback:
      'Trainer could not open the folder automatically. Open this path in your file manager: {dir}',
    openExtensionsPage: 'Open Extensions Page',
    noChromiumBrowserFound: 'No Chromium browser was detected. Open the extensions page of Chrome, Edge, Brave, Arc, Opera or Vivaldi manually.',
    browserOpenFailed: 'Trainer could not open {browser}: {reason}',
    copyFolderPath: 'Copy Folder Path',
    copyCode: 'Copy Code',
    installBundleMissing:
      'This Trainer build does not bundle the browser capture extension. Install a Trainer VSIX that ships browser-capture/.',
    installFailed: 'Trainer could not install the browser capture extension: {reason}',
    installSucceeded: '{label} installed to {dir}. Load it unpacked from your browser\'s extensions page.',
    sidecarUnavailable: 'Trainer is unavailable.',
    pairingCodeSummaryOne:
      'Enter this code in the Trainer Capture popup within 1 minute (single use).',
    pairingCodeSummaryMany:
      'Enter this code in the Trainer Capture popup within {minutes} minutes (single use).',
    pairingCodeIssued:
      'Trainer browser pairing code generated. Enter it in the Trainer Capture popup.',
    pairingRegisterFailed: 'Trainer could not register a browser pairing code: {reason}',
    pairingRevokedHadCode: 'Browser pairing revoked. The capture extension must pair again.',
    pairingRevokedIdle: 'Browser pairing revoked. No code was waiting to be redeemed.',
    pairingRevokeFailed: 'Trainer could not revoke the browser pairing: {reason}',
    deepLinkIgnoredLog: 'ignored unrecognized deep link: {uri}',
    deepLinkUnconfirmedLog:
      'deep link for {resourceId} could not confirm a visible workbench after {attempts} attempts',
    deepLinkOpenedLog:
      'deep link opened resource {resourceId} (delivery attempts: {attempts})',
  },
  'es-ES': {
    installReady: '{label} está listo.',
    installStepExtensions: '1. Abre la página de extensiones de tu navegador: chrome://extensions, edge://extensions, brave://extensions, opera://extensions o vivaldi://extensions (Arc: arc://extensions).',
    installStepDeveloperMode: '2. Activa el modo de desarrollador.',
    installStepLoadUnpacked: '3. Elige «Cargar descomprimida» y selecciona {dir}.',
    installStepPair: '4. En Ajustes de Trainer elige «Mostrar código de emparejamiento» e introdúcelo en la ventana de la extensión.',
    installFolderFallback:
      'Trainer no pudo abrir la carpeta automáticamente. Ábrela manualmente en tu gestor de archivos: {dir}',
    openExtensionsPage: 'Abrir página de extensiones',
    noChromiumBrowserFound: 'No se detectó ningún navegador Chromium. Abre manualmente la página de extensiones de Chrome, Edge, Brave, Arc, Opera o Vivaldi.',
    browserOpenFailed: 'Trainer no pudo abrir {browser}: {reason}',
    copyFolderPath: 'Copiar ruta de la carpeta',
    copyCode: 'Copiar código',
    installBundleMissing:
      'Esta versión de Trainer no incluye la extensión de captura. Instala un VSIX de Trainer que incluya browser-capture/.',
    installFailed: 'Trainer no pudo instalar la extensión de captura: {reason}',
    installSucceeded:
      '{label} se instaló en {dir}. Cárgala como extensión descomprimida desde la página de extensiones de tu navegador.',
    sidecarUnavailable: 'Trainer no está disponible.',
    pairingCodeSummaryOne:
      'Introduce este código en la ventana de Trainer Capture en 1 minuto (un solo uso).',
    pairingCodeSummaryMany:
      'Introduce este código en la ventana de Trainer Capture en {minutes} minutos (un solo uso).',
    pairingCodeIssued:
      'Código de emparejamiento del navegador generado. Introdúcelo en la ventana de Trainer Capture.',
    pairingRegisterFailed: 'Trainer no pudo registrar un código de emparejamiento: {reason}',
    pairingRevokedHadCode:
      'Emparejamiento del navegador revocado. La extensión de captura debe volver a emparejarse.',
    pairingRevokedIdle:
      'Emparejamiento del navegador revocado. No había ningún código pendiente de usar.',
    pairingRevokeFailed: 'Trainer no pudo revocar el emparejamiento del navegador: {reason}',
    deepLinkIgnoredLog: 'se ignoró un enlace profundo no reconocido: {uri}',
    deepLinkUnconfirmedLog:
      'el enlace profundo de {resourceId} no pudo confirmar un área de trabajo visible tras {attempts} intentos',
    deepLinkOpenedLog:
      'el enlace profundo abrió el recurso {resourceId} (intentos de entrega: {attempts})',
  },
  'fr-FR': {
    installReady: '{label} est prêt.',
    installStepExtensions: '1. Ouvrez la page des extensions de votre navigateur : chrome://extensions, edge://extensions, brave://extensions, opera://extensions ou vivaldi://extensions (Arc : arc://extensions).',
    installStepDeveloperMode: '2. Activez le mode développeur.',
    installStepLoadUnpacked: '3. Choisissez « Charger l’extension non empaquetée » et sélectionnez {dir}.',
    installStepPair: '4. Dans Réglages de Trainer, choisissez « Afficher le code d’association », puis saisissez-le dans la fenêtre de l’extension.',
    installFolderFallback:
      'Trainer n’a pas pu ouvrir le dossier automatiquement. Ouvrez-le dans votre gestionnaire de fichiers : {dir}',
    openExtensionsPage: 'Ouvrir la page des extensions',
    noChromiumBrowserFound: 'Aucun navigateur Chromium détecté. Ouvrez manuellement la page des extensions de Chrome, Edge, Brave, Arc, Opera ou Vivaldi.',
    browserOpenFailed: 'Trainer n’a pas pu ouvrir {browser} : {reason}',
    copyFolderPath: 'Copier le chemin du dossier',
    copyCode: 'Copier le code',
    installBundleMissing:
      'Cette version de Trainer n’inclut pas l’extension de capture. Installez un VSIX Trainer contenant browser-capture/.',
    installFailed: 'Trainer n’a pas pu installer l’extension de capture : {reason}',
    installSucceeded:
      '{label} a été installé dans {dir}. Chargez-le comme extension non empaquetée depuis la page des extensions de votre navigateur.',
    sidecarUnavailable: 'Trainer est indisponible.',
    pairingCodeSummaryOne:
      'Saisissez ce code dans la fenêtre Trainer Capture sous 1 minute (usage unique).',
    pairingCodeSummaryMany:
      'Saisissez ce code dans la fenêtre Trainer Capture sous {minutes} minutes (usage unique).',
    pairingCodeIssued:
      'Code d’association du navigateur généré. Saisissez-le dans la fenêtre Trainer Capture.',
    pairingRegisterFailed: 'Trainer n’a pas pu enregistrer de code d’association : {reason}',
    pairingRevokedHadCode:
      'Association du navigateur révoquée. L’extension de capture doit s’associer à nouveau.',
    pairingRevokedIdle:
      'Association du navigateur révoquée. Aucun code n’attendait d’être utilisé.',
    pairingRevokeFailed: 'Trainer n’a pas pu révoquer l’association du navigateur : {reason}',
    deepLinkIgnoredLog: 'lien profond non reconnu ignoré : {uri}',
    deepLinkUnconfirmedLog:
      'le lien profond de {resourceId} n’a pas pu confirmer un espace de travail visible après {attempts} tentatives',
    deepLinkOpenedLog:
      'le lien profond a ouvert la ressource {resourceId} (tentatives de livraison : {attempts})',
  },
  'de-DE': {
    installReady: '{label} ist bereit.',
    installStepExtensions: '1. Öffne die Erweiterungsseite deines Browsers: chrome://extensions, edge://extensions, brave://extensions, opera://extensions oder vivaldi://extensions (Arc: arc://extensions).',
    installStepDeveloperMode: '2. Aktiviere den Entwicklermodus.',
    installStepLoadUnpacked: '3. Wähle „Entpackte Erweiterung laden“ und dann {dir}.',
    installStepPair: '4. Wähle in den Trainer-Einstellungen „Kopplungscode anzeigen“ und gib ihn im Erweiterungsfenster ein.',
    installFolderFallback:
      'Trainer konnte den Ordner nicht automatisch öffnen. Öffne diesen Pfad selbst im Dateimanager: {dir}',
    openExtensionsPage: 'Erweiterungsseite öffnen',
    noChromiumBrowserFound: 'Kein Chromium-Browser gefunden. Öffne die Erweiterungsseite von Chrome, Edge, Brave, Arc, Opera oder Vivaldi manuell.',
    browserOpenFailed: 'Trainer konnte {browser} nicht öffnen: {reason}',
    copyFolderPath: 'Ordnerpfad kopieren',
    copyCode: 'Code kopieren',
    installBundleMissing:
      'Diese Trainer-Version enthält die Browser-Erweiterung nicht. Installiere ein Trainer-VSIX mit browser-capture/.',
    installFailed: 'Trainer konnte die Browser-Erweiterung nicht installieren: {reason}',
    installSucceeded:
      '{label} wurde nach {dir} installiert. Lade sie über die Erweiterungsseite deines Browsers als entpackte Erweiterung.',
    sidecarUnavailable: 'Trainer ist nicht verfügbar.',
    pairingCodeSummaryOne:
      'Gib diesen Code innerhalb von 1 Minute im Trainer-Capture-Fenster ein (einmalig verwendbar).',
    pairingCodeSummaryMany:
      'Gib diesen Code innerhalb von {minutes} Minuten im Trainer-Capture-Fenster ein (einmalig verwendbar).',
    pairingCodeIssued:
      'Browser-Kopplungscode erstellt. Gib ihn im Trainer-Capture-Fenster ein.',
    pairingRegisterFailed: 'Trainer konnte keinen Browser-Kopplungscode registrieren: {reason}',
    pairingRevokedHadCode:
      'Browser-Kopplung aufgehoben. Die Erweiterung muss erneut koppeln.',
    pairingRevokedIdle:
      'Browser-Kopplung aufgehoben. Es wartete kein Code auf die Verwendung.',
    pairingRevokeFailed: 'Trainer konnte die Browser-Kopplung nicht aufheben: {reason}',
    deepLinkIgnoredLog: 'unbekannter Deep-Link ignoriert: {uri}',
    deepLinkUnconfirmedLog:
      'Deep-Link für {resourceId} konnte nach {attempts} Versuchen kein sichtbares Workbench-Fenster bestätigen',
    deepLinkOpenedLog:
      'Deep-Link hat Ressource {resourceId} geöffnet (Zustellversuche: {attempts})',
  },
  'ja-JP': {
    installReady: '{label} の準備ができました。',
    installStepExtensions: '1. ブラウザーの拡張機能ページを開きます：chrome://extensions、edge://extensions、brave://extensions、opera://extensions、vivaldi://extensions（Arc は arc://extensions）。',
    installStepDeveloperMode: '2. デベロッパーモードをオンにします。',
    installStepLoadUnpacked:
      '3.「パッケージ化されていない拡張機能を読み込む」を選び、{dir} を指定します。',
    installStepPair: '4. Trainer の設定で「ペアリングコードを表示」を選び、拡張機能のポップアップに入力します。',
    installFolderFallback:
      'Trainer はフォルダーを自動で開けませんでした。ファイルマネージャーで次のパスを開いてください：{dir}',
    openExtensionsPage: '拡張機能ページを開く',
    noChromiumBrowserFound: 'Chromium 系ブラウザーが見つかりません。Chrome、Edge、Brave、Arc、Opera、Vivaldi の拡張機能ページを手動で開いてください。',
    browserOpenFailed: 'Trainer は {browser} を開けませんでした：{reason}',
    copyFolderPath: 'フォルダーのパスをコピー',
    copyCode: 'コードをコピー',
    installBundleMissing:
      'この Trainer ビルドにはブラウザーキャプチャ拡張機能が含まれていません。browser-capture/ を含む Trainer VSIX をインストールしてください。',
    installFailed: 'Trainer はブラウザーキャプチャ拡張機能をインストールできませんでした：{reason}',
    installSucceeded:
      '{label} を {dir} にインストールしました。ブラウザーの拡張機能ページから「パッケージ化されていない拡張機能」として読み込んでください。',
    sidecarUnavailable: 'Trainer を利用できません。',
    pairingCodeSummaryOne:
      'このコードを 1 分以内に Trainer Capture のポップアップへ入力してください（1 回限り有効）。',
    pairingCodeSummaryMany:
      'このコードを {minutes} 分以内に Trainer Capture のポップアップへ入力してください（1 回限り有効）。',
    pairingCodeIssued:
      'ブラウザーのペアリングコードを発行しました。Trainer Capture のポップアップへ入力してください。',
    pairingRegisterFailed: 'Trainer はブラウザーのペアリングコードを登録できませんでした：{reason}',
    pairingRevokedHadCode:
      'ブラウザーのペアリングを解除しました。キャプチャ拡張機能は再ペアリングが必要です。',
    pairingRevokedIdle:
      'ブラウザーのペアリングを解除しました。使用待ちのコードはありませんでした。',
    pairingRevokeFailed: 'Trainer はブラウザーのペアリングを解除できませんでした：{reason}',
    deepLinkIgnoredLog: '認識できないディープリンクを無視しました：{uri}',
    deepLinkUnconfirmedLog:
      '{resourceId} のディープリンクは {attempts} 回試行してもワークベンチの表示を確認できませんでした',
    deepLinkOpenedLog:
      'ディープリンクでリソース {resourceId} を開きました（配信試行: {attempts} 回）',
  },
  'ko-KR': {
    installReady: '{label}이(가) 준비되었습니다.',
    installStepExtensions: '1. 브라우저의 확장 프로그램 페이지를 엽니다: chrome://extensions, edge://extensions, brave://extensions, opera://extensions, vivaldi://extensions (Arc: arc://extensions).',
    installStepDeveloperMode: '2. 개발자 모드를 켭니다.',
    installStepLoadUnpacked: '3. "압축해제된 확장 프로그램을 로드"를 선택하고 {dir}을(를) 지정합니다.',
    installStepPair: '4. Trainer 설정에서 "페어링 코드 표시"를 선택한 뒤 확장 프로그램 팝업에 입력하세요.',
    installFolderFallback:
      'Trainer가 폴더를 자동으로 열지 못했습니다. 파일 관리자에서 다음 경로를 직접 여세요: {dir}',
    openExtensionsPage: '확장 프로그램 페이지 열기',
    noChromiumBrowserFound: 'Chromium 브라우저를 찾지 못했습니다. Chrome, Edge, Brave, Arc, Opera, Vivaldi의 확장 프로그램 페이지를 직접 여세요.',
    browserOpenFailed: 'Trainer가 {browser}을(를) 열지 못했습니다: {reason}',
    copyFolderPath: '폴더 경로 복사',
    copyCode: '코드 복사',
    installBundleMissing:
      '이 Trainer 빌드에는 브라우저 캡처 확장이 포함되어 있지 않습니다. browser-capture/가 포함된 Trainer VSIX를 설치하세요.',
    installFailed: 'Trainer가 브라우저 캡처 확장을 설치하지 못했습니다: {reason}',
    installSucceeded:
      '{label}을(를) {dir}에 설치했습니다. 브라우저의 확장 프로그램 페이지에서 "압축해제된 확장 프로그램"으로 로드하세요.',
    sidecarUnavailable: 'Trainer를 사용할 수 없습니다.',
    pairingCodeSummaryOne: '1분 안에 이 코드를 Trainer Capture 팝업에 입력하세요(1회용).',
    pairingCodeSummaryMany: '{minutes}분 안에 이 코드를 Trainer Capture 팝업에 입력하세요(1회용).',
    pairingCodeIssued:
      '브라우저 페어링 코드가 생성되었습니다. Trainer Capture 팝업에 입력하세요.',
    pairingRegisterFailed: 'Trainer가 브라우저 페어링 코드를 등록하지 못했습니다: {reason}',
    pairingRevokedHadCode:
      '브라우저 페어링을 해제했습니다. 캡처 확장을 다시 페어링해야 합니다.',
    pairingRevokedIdle: '브라우저 페어링을 해제했습니다. 대기 중이던 코드는 없습니다.',
    pairingRevokeFailed: 'Trainer가 브라우저 페어링을 해제하지 못했습니다: {reason}',
    deepLinkIgnoredLog: '알 수 없는 딥링크를 무시했습니다: {uri}',
    deepLinkUnconfirmedLog:
      '{resourceId} 딥링크가 {attempts}회 시도 후에도 워크벤치 표시를 확인하지 못했습니다',
    deepLinkOpenedLog:
      '딥링크로 리소스 {resourceId}을(를) 열었습니다(전달 시도: {attempts}회)',
  },
  'pt-BR': {
    installReady: '{label} está pronto.',
    installStepExtensions: '1. Abra a página de extensões do seu navegador: chrome://extensions, edge://extensions, brave://extensions, opera://extensions ou vivaldi://extensions (Arc: arc://extensions).',
    installStepDeveloperMode: '2. Ative o modo de desenvolvedor.',
    installStepLoadUnpacked: '3. Escolha "Carregar sem compactação" e selecione {dir}.',
    installStepPair: '4. Nas Configurações do Trainer, escolha “Mostrar código de pareamento” e insira-o na janela da extensão.',
    installFolderFallback:
      'O Trainer não conseguiu abrir a pasta automaticamente. Abra este caminho no gerenciador de arquivos: {dir}',
    openExtensionsPage: 'Abrir página de extensões',
    noChromiumBrowserFound: 'Nenhum navegador Chromium foi detectado. Abra manualmente a página de extensões do Chrome, Edge, Brave, Arc, Opera ou Vivaldi.',
    browserOpenFailed: 'O Trainer não conseguiu abrir {browser}: {reason}',
    copyFolderPath: 'Copiar caminho da pasta',
    copyCode: 'Copiar código',
    installBundleMissing:
      'Esta versão do Trainer não inclui a extensão de captura. Instale um VSIX do Trainer que inclua browser-capture/.',
    installFailed: 'O Trainer não conseguiu instalar a extensão de captura: {reason}',
    installSucceeded:
      '{label} foi instalado em {dir}. Carregue-o sem compactação na página de extensões do seu navegador.',
    sidecarUnavailable: 'O Trainer está indisponível.',
    pairingCodeSummaryOne:
      'Digite este código na janela do Trainer Capture em até 1 minuto (uso único).',
    pairingCodeSummaryMany:
      'Digite este código na janela do Trainer Capture em até {minutes} minutos (uso único).',
    pairingCodeIssued:
      'Código de emparelhamento do navegador gerado. Digite-o na janela do Trainer Capture.',
    pairingRegisterFailed:
      'O Trainer não conseguiu registrar um código de emparelhamento: {reason}',
    pairingRevokedHadCode:
      'Emparelhamento do navegador revogado. A extensão de captura precisa emparelhar novamente.',
    pairingRevokedIdle:
      'Emparelhamento do navegador revogado. Nenhum código aguardava uso.',
    pairingRevokeFailed:
      'O Trainer não conseguiu revogar o emparelhamento do navegador: {reason}',
    deepLinkIgnoredLog: 'link profundo não reconhecido ignorado: {uri}',
    deepLinkUnconfirmedLog:
      'o link profundo de {resourceId} não conseguiu confirmar um workbench visível após {attempts} tentativas',
    deepLinkOpenedLog:
      'o link profundo abriu o recurso {resourceId} (tentativas de entrega: {attempts})',
  },
};

const LOCALE_PREFIXES: ReadonlyArray<[string, ComposerLanguage]> = [
  ['zh', 'zh-CN'],
  ['en', 'en-US'],
  ['es', 'es-ES'],
  ['fr', 'fr-FR'],
  ['de', 'de-DE'],
  ['ja', 'ja-JP'],
  ['ko', 'ko-KR'],
  ['pt', 'pt-BR'],
];

/**
 * Resolve a VS Code UI language tag to one of the eight supported languages by
 * simple prefix match (zh-TW → zh-CN, en-GB → en-US, es-419 → es-ES,
 * pt-PT → pt-BR); anything unrecognized or empty falls back to en-US.
 */
export function resolveBrowserCaptureCopyLanguage(language: unknown): ComposerLanguage {
  if (isComposerLanguage(language)) {
    return language;
  }
  const value = typeof language === 'string' ? language.trim().toLowerCase() : '';
  if (!value) {
    return 'en-US';
  }
  for (const [prefix, resolved] of LOCALE_PREFIXES) {
    if (value === prefix || value.startsWith(`${prefix}-`) || value.startsWith(`${prefix}_`)) {
      return resolved;
    }
  }
  return 'en-US';
}

export function browserCaptureHostCopy(
  language: ComposerLanguage | undefined,
  key: BrowserCaptureHostCopyKey,
  params?: Record<string, string | number>,
): string {
  const table = browserCaptureHostCopyTable[language ?? 'en-US'] ?? browserCaptureHostCopyTable['en-US'];
  let text = table[key] ?? browserCaptureHostCopyTable['en-US'][key];
  if (params) {
    for (const [name, value] of Object.entries(params)) {
      text = text.split(`{${name}}`).join(String(value));
    }
  }
  return text;
}
