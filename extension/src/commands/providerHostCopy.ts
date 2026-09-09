import * as vscode from 'vscode';

import { isComposerLanguage, type ComposerLanguage } from '../../../shared/src/types';

/**
 * Host-side provider copy. The host posts operation/status messages before the
 * webview can localize them, so these strings ship localized per the request
 * language (payload → workspace setting → VS Code UI locale → en-US).
 */
export type ProviderHostCopyKey =
  | 'testConnected'
  | 'testConnectedReady'
  | 'testMissingKey'
  | 'testCheckInterrupted'
  | 'testIncomplete'
  | 'testLanguageCorruption'
  | 'testLanguageInconclusive'
  | 'testEmptyReply'
  | 'testRespondedUnusable'
  | 'testUnreachable'
  | 'testUnreachableAdvice'
  | 'saveChecking'
  | 'saveNoKey'
  | 'saveLocalNoKey'
  | 'modelsLoadedVerified'
  | 'modelsLoadedInconclusive'
  | 'modelsLoadedFailed'
  | 'modelsLoadedPlain'
  | 'modelsCachedVerified'
  | 'modelsCachedInconclusive'
  | 'modelsCachedFailed'
  | 'modelsCachedPlain'
  | 'savedModelReadyNoList'
  | 'savedModelUnverifiedNoList'
  | 'savedModelNoList'
  | 'modelResolvedSuffix'
  | 'switchVerifying'
  | 'switchAlreadyActive'
  | 'switchModelNotAllowed'
  | 'switchCatalogDetail'
  | 'switchVerifyingDetail'
  | 'clearNothingToClear'
  | 'clearCancelled'
  | 'clearDone';

type ProviderHostCopyTable = Record<ProviderHostCopyKey, string>;

const providerHostCopyTable: Record<ComposerLanguage, ProviderHostCopyTable> = {
  'zh-CN': {
    testConnected: '{name} 已连通。',
    testConnectedReady: 'Trainer 现在可以使用这个模型。',
    testMissingKey: '{name} 已保存,但还没有存放 API 密钥。补上密钥后 Trainer 才能工作。',
    testCheckInterrupted: 'Trainer 没能完成这次连接检查,请稍后再试。',
    testIncomplete: '{name} 还缺必要配置。请先保存连接名称、服务地址和模型。',
    testLanguageCorruption: '{name} 可以连通,但中文消息在到达模型前已损坏。',
    testLanguageInconclusive: '{name} 可以连通,但中文完整性还没有完全确认。',
    testEmptyReply: '{name} 可以连通,但回复内容无法使用。',
    testRespondedUnusable: '{name} 有响应,但 Trainer 暂时无法使用。',
    testUnreachable: '无法连通 {name}。',
    testUnreachableAdvice: '请检查服务地址、模型和 API 密钥后重试。',
    saveChecking: '连接设置已保存。Trainer 正在获取在线模型并检查回复质量。',
    saveNoKey: '连接设置已保存,但还没有存放 API 密钥,Trainer 暂时无法工作。请先补上密钥。',
    saveLocalNoKey:
      '连接设置已保存。这组连接指向本机服务,不需要 API 密钥即可使用。请测试连接以确认可用。',
    modelsLoadedVerified: '已加载 {count} 个在线模型,并确认当前连接可用。',
    modelsLoadedInconclusive: '已加载 {count} 个在线模型,但中文完整性还需要再次确认。',
    modelsLoadedFailed: '已加载 {count} 个在线模型,但 Trainer 暂时无法用这组连接教学。',
    modelsLoadedPlain: '已加载 {count} 个在线模型。',
    modelsCachedVerified: '已使用缓存模型,并确认当前连接可用,共 {count} 个在线模型。',
    modelsCachedInconclusive: '已使用缓存模型(共 {count} 个),但中文完整性还需要再次确认。',
    modelsCachedFailed: '已使用缓存模型(共 {count} 个),但 Trainer 暂时无法用这组连接教学。',
    modelsCachedPlain: '已使用缓存模型,共 {count} 个在线模型。',
    savedModelReadyNoList: '当前模型已连通可用。该服务没有提供在线模型列表,Trainer 保留了已保存的模型。',
    savedModelUnverifiedNoList: '连接设置已保存,但暂时还无法确认当前模型可用。',
    savedModelNoList: '连接设置已保存,但暂时还拿不到在线模型列表。',
    modelResolvedSuffix: ' Trainer 已把配置的模型解析为 {model}。',
    switchVerifying: "已切换到模型“{model}”。Trainer 正在确认这组连接。",
    switchAlreadyActive: '模型“{model}”已经是当前模型。',
    switchModelNotAllowed: '模型“{model}”不在当前连接的模型列表或已配置的模型目录中。',
    switchCatalogDetail: 'Trainer 已切换到目录中的 {model}。请先测试或刷新模型,再按可用模型使用。',
    switchVerifyingDetail: 'Trainer 已切换到 {model},正在确认连接;检查完成后输入框会自动恢复可用。',
    clearNothingToClear: '当前没有可清除的连接配置。',
    clearCancelled: '已取消清除连接配置。',
    clearDone: '连接配置已清除。',
  },
  'en-US': {
    testConnected: '{name} is connected.',
    testConnectedReady: 'Trainer can use this model now.',
    testMissingKey: '{name} is saved, but no API key is stored yet. Trainer cannot work until you add one.',
    testCheckInterrupted: 'Trainer could not finish the connection check. Try again in a moment.',
    testIncomplete: '{name} is missing required settings. Save the provider name, base URL, and model first.',
    testLanguageCorruption: '{name} is reachable, but Chinese input was corrupted before the model saw it.',
    testLanguageInconclusive: '{name} is reachable, but zh-CN integrity is not fully verified yet.',
    testEmptyReply: '{name} is reachable, but the reply was unusable.',
    testRespondedUnusable: '{name} responded, but Trainer still cannot use it yet.',
    testUnreachable: '{name} could not be reached.',
    testUnreachableAdvice: 'Check the base URL, model, and API key, then try again.',
    saveChecking: 'Provider settings saved. Trainer is fetching live models and checking reply health.',
    saveNoKey:
      'Provider settings saved, but Trainer still cannot work yet because no API key is stored. Add one before starting coaching.',
    saveLocalNoKey:
      'Provider settings saved. This connection points at a local service, so it can be used without an API key. Test the connection to verify it.',
    modelsLoadedVerified: 'Loaded {count} live models and verified the current connection.',
    modelsLoadedInconclusive:
      'Loaded {count} live models, but zh-CN integrity still needs verification on this connection.',
    modelsLoadedFailed: 'Loaded {count} live models, but Trainer cannot coach with this connection yet.',
    modelsLoadedPlain: 'Loaded {count} live models.',
    modelsCachedVerified: 'Used cached models and verified the current connection. {count} live models are available.',
    modelsCachedInconclusive:
      'Used cached models ({count} live models), but zh-CN integrity still needs verification on this connection.',
    modelsCachedFailed:
      'Used cached models ({count} live models), but Trainer cannot coach with this connection yet.',
    modelsCachedPlain: 'Used cached models. {count} live models are available.',
    savedModelReadyNoList:
      'The current model is connected and ready. This provider did not return a live model list, so Trainer kept the saved model.',
    savedModelUnverifiedNoList: 'Provider settings saved, but Trainer could not verify the current model yet.',
    savedModelNoList: 'Provider settings saved, but Trainer could not get the live model list yet.',
    modelResolvedSuffix: ' Trainer resolved the configured model to {model}.',
    switchVerifying: "Switched to model '{model}'. Trainer is verifying the connection on this model.",
    switchAlreadyActive: "Model '{model}' is already active.",
    switchModelNotAllowed: "Model '{model}' is not in the current provider model list or configured model catalog.",
    switchCatalogDetail:
      'Trainer switched to {model} from the configured catalog. Test or refresh models before treating it as available.',
    switchVerifyingDetail:
      'Trainer switched to {model}. Trainer is verifying this model now; the composer unlocks as soon as the check finishes.',
    clearNothingToClear: 'No provider configuration to clear.',
    clearCancelled: 'Provider clear cancelled.',
    clearDone: 'Provider configuration cleared.',
  },
  'es-ES': {
    testConnected: '{name} está conectado.',
    testConnectedReady: 'Trainer ya puede usar este modelo.',
    testMissingKey:
      '{name} está guardado, pero aún no hay clave API almacenada. Trainer no puede funcionar hasta que añadas una.',
    testCheckInterrupted: 'Trainer no pudo terminar la comprobación de conexión. Inténtalo de nuevo en un momento.',
    testIncomplete:
      'A {name} le faltan ajustes obligatorios. Guarda primero el nombre, la URL base y el modelo.',
    testLanguageCorruption:
      '{name} responde, pero el texto en chino se corrompió antes de llegar al modelo.',
    testLanguageInconclusive:
      '{name} responde, pero la integridad del chino (zh-CN) aún no está totalmente verificada.',
    testEmptyReply: '{name} responde, pero la respuesta no se puede usar.',
    testRespondedUnusable: '{name} respondió, pero Trainer todavía no puede usarlo.',
    testUnreachable: 'No se pudo conectar con {name}.',
    testUnreachableAdvice: 'Revisa la URL base, el modelo y la clave API, e inténtalo de nuevo.',
    saveChecking: 'Configuración guardada. Trainer está buscando modelos en vivo y comprobando la calidad de respuesta.',
    saveNoKey:
      'Configuración guardada, pero Trainer todavía no puede funcionar porque no hay clave API almacenada. Añade una antes de empezar.',
    saveLocalNoKey:
      'Configuración guardada. Esta conexión apunta a un servicio local, así que funciona sin clave API. Prueba la conexión para verificarla.',
    modelsLoadedVerified: 'Se cargaron {count} modelos en vivo y se verificó la conexión actual.',
    modelsLoadedInconclusive:
      'Se cargaron {count} modelos en vivo, pero la integridad del chino (zh-CN) aún necesita verificación.',
    modelsLoadedFailed:
      'Se cargaron {count} modelos en vivo, pero Trainer todavía no puede dar clase con esta conexión.',
    modelsLoadedPlain: 'Se cargaron {count} modelos en vivo.',
    modelsCachedVerified:
      'Se usaron modelos en caché y se verificó la conexión actual. Hay {count} modelos en vivo disponibles.',
    modelsCachedInconclusive:
      'Se usaron modelos en caché ({count} en vivo), pero la integridad del chino aún necesita verificación.',
    modelsCachedFailed:
      'Se usaron modelos en caché ({count} en vivo), pero Trainer todavía no puede dar clase con esta conexión.',
    modelsCachedPlain: 'Se usaron modelos en caché. Hay {count} modelos en vivo disponibles.',
    savedModelReadyNoList:
      'El modelo actual está conectado y listo. Este proveedor no devolvió una lista de modelos en vivo, así que Trainer mantuvo el modelo guardado.',
    savedModelUnverifiedNoList: 'Configuración guardada, pero Trainer aún no pudo verificar el modelo actual.',
    savedModelNoList: 'Configuración guardada, pero Trainer aún no pudo obtener la lista de modelos en vivo.',
    modelResolvedSuffix: ' Trainer resolvió el modelo configurado a {model}.',
    switchVerifying: "Cambiado al modelo «{model}». Trainer está verificando la conexión con este modelo.",
    switchAlreadyActive: 'El modelo «{model}» ya es el modelo actual.',
    switchModelNotAllowed:
      'El modelo «{model}» no está en la lista de modelos del proveedor ni en el catálogo configurado.',
    switchVerifyingDetail:
      'Trainer cambió a {model} y está verificando la conexión; el compositor se desbloquea en cuanto termine la comprobación.',
    switchCatalogDetail:
      'Trainer cambió a {model} del catálogo configurado. Prueba o actualiza los modelos antes de tratarlo como disponible.',
    clearNothingToClear: 'No hay configuración de proveedor que borrar.',
    clearCancelled: 'Borrado de la configuración cancelado.',
    clearDone: 'Configuración del proveedor borrada.',
  },
  'fr-FR': {
    testConnected: '{name} est connecté.',
    testConnectedReady: 'Trainer peut utiliser ce modèle.',
    testMissingKey:
      "{name} est enregistré, mais aucune clé API n'est stockée. Trainer ne peut pas fonctionner tant que vous ne l'avez pas ajoutée.",
    testCheckInterrupted: "Trainer n'a pas pu terminer la vérification de connexion. Réessayez dans un instant.",
    testIncomplete:
      '{name} manque de réglages requis. Enregistrez d’abord le nom, l’URL de base et le modèle.',
    testLanguageCorruption:
      '{name} est joignable, mais le texte chinois a été corrompu avant d’arriver au modèle.',
    testLanguageInconclusive:
      '{name} est joignable, mais l’intégrité du chinois (zh-CN) n’est pas encore totalement vérifiée.',
    testEmptyReply: '{name} est joignable, mais la réponse est inutilisable.',
    testRespondedUnusable: '{name} a répondu, mais Trainer ne peut pas encore l’utiliser.',
    testUnreachable: 'Impossible de joindre {name}.',
    testUnreachableAdvice: 'Vérifiez l’URL de base, le modèle et la clé API, puis réessayez.',
    saveChecking:
      'Paramètres enregistrés. Trainer récupère les modèles en direct et vérifie la qualité des réponses.',
    saveNoKey:
      'Paramètres enregistrés, mais Trainer ne peut pas encore fonctionner faute de clé API stockée. Ajoutez-en une pour commencer.',
    saveLocalNoKey:
      'Paramètres enregistrés. Cette connexion pointe vers un service local : elle fonctionne sans clé API. Testez la connexion pour la valider.',
    modelsLoadedVerified: '{count} modèles en direct chargés et connexion actuelle vérifiée.',
    modelsLoadedInconclusive:
      '{count} modèles en direct chargés, mais l’intégrité du chinois (zh-CN) doit encore être vérifiée.',
    modelsLoadedFailed:
      '{count} modèles en direct chargés, mais Trainer ne peut pas encore coacher avec cette connexion.',
    modelsLoadedPlain: '{count} modèles en direct chargés.',
    modelsCachedVerified:
      'Modèles en cache utilisés et connexion actuelle vérifiée. {count} modèles en direct sont disponibles.',
    modelsCachedInconclusive:
      'Modèles en cache utilisés ({count} en direct), mais l’intégrité du chinois doit encore être vérifiée.',
    modelsCachedFailed:
      'Modèles en cache utilisés ({count} en direct), mais Trainer ne peut pas encore coacher avec cette connexion.',
    modelsCachedPlain: 'Modèles en cache utilisés. {count} modèles en direct sont disponibles.',
    savedModelReadyNoList:
      'Le modèle actuel est connecté et prêt. Ce fournisseur n’a pas renvoyé de liste de modèles en direct ; Trainer a conservé le modèle enregistré.',
    savedModelUnverifiedNoList:
      'Paramètres enregistrés, mais Trainer n’a pas encore pu vérifier le modèle actuel.',
    savedModelNoList:
      'Paramètres enregistrés, mais Trainer n’a pas encore pu obtenir la liste des modèles en direct.',
    modelResolvedSuffix: ' Trainer a résolu le modèle configuré vers {model}.',
    switchVerifying: "Passé au modèle « {model} ». Trainer vérifie la connexion avec ce modèle.",
    switchAlreadyActive: 'Le modèle « {model} » est déjà le modèle actuel.',
    switchModelNotAllowed:
      'Le modèle « {model} » n’est ni dans la liste de modèles du fournisseur ni dans le catalogue configuré.',
    switchVerifyingDetail:
      'Trainer est passé à {model} et vérifie la connexion ; le composeur se débloque dès la vérification terminée.',
    switchCatalogDetail:
      'Trainer est passé à {model} du catalogue configuré. Testez ou actualisez les modèles avant de le considérer comme disponible.',
    clearNothingToClear: 'Aucune configuration de fournisseur à effacer.',
    clearCancelled: 'Effacement de la configuration annulé.',
    clearDone: 'Configuration du fournisseur effacée.',
  },
  'de-DE': {
    testConnected: '{name} ist verbunden.',
    testConnectedReady: 'Trainer kann dieses Modell jetzt verwenden.',
    testMissingKey:
      '{name} ist gespeichert, aber es ist noch kein API-Schlüssel hinterlegt. Trainer funktioniert erst, nachdem Sie einen hinzugefügt haben.',
    testCheckInterrupted:
      'Trainer konnte die Verbindungsprüfung nicht abschließen. Versuchen Sie es gleich noch einmal.',
    testIncomplete:
      '{name} fehlen erforderliche Einstellungen. Speichern Sie zuerst Name, Basis-URL und Modell.',
    testLanguageCorruption:
      '{name} ist erreichbar, aber der chinesische Text wurde beschädigt, bevor ihn das Modell sah.',
    testLanguageInconclusive:
      '{name} ist erreichbar, aber die chinesische Integrität (zh-CN) ist noch nicht vollständig bestätigt.',
    testEmptyReply: '{name} ist erreichbar, aber die Antwort war unbrauchbar.',
    testRespondedUnusable: '{name} hat geantwortet, aber Trainer kann es noch nicht verwenden.',
    testUnreachable: '{name} konnte nicht erreicht werden.',
    testUnreachableAdvice: 'Prüfen Sie Basis-URL, Modell und API-Schlüssel und versuchen Sie es erneut.',
    saveChecking:
      'Einstellungen gespeichert. Trainer ruft Live-Modelle ab und prüft die Antwortqualität.',
    saveNoKey:
      'Einstellungen gespeichert, aber Trainer kann noch nicht arbeiten, da kein API-Schlüssel hinterlegt ist. Fügen Sie einen hinzu, bevor Sie starten.',
    saveLocalNoKey:
      'Einstellungen gespeichert. Diese Verbindung zeigt auf einen lokalen Dienst und funktioniert ohne API-Schlüssel. Testen Sie die Verbindung zur Bestätigung.',
    modelsLoadedVerified: '{count} Live-Modelle geladen und die aktuelle Verbindung geprüft.',
    modelsLoadedInconclusive:
      '{count} Live-Modelle geladen, aber die chinesische Integrität muss noch bestätigt werden.',
    modelsLoadedFailed:
      '{count} Live-Modelle geladen, aber Trainer kann mit dieser Verbindung noch nicht unterrichten.',
    modelsLoadedPlain: '{count} Live-Modelle geladen.',
    modelsCachedVerified:
      'Zwischengespeicherte Modelle verwendet und die aktuelle Verbindung geprüft. {count} Live-Modelle verfügbar.',
    modelsCachedInconclusive:
      'Zwischengespeicherte Modelle verwendet ({count} Live-Modelle), aber die chinesische Integrität muss noch bestätigt werden.',
    modelsCachedFailed:
      'Zwischengespeicherte Modelle verwendet ({count} Live-Modelle), aber Trainer kann mit dieser Verbindung noch nicht unterrichten.',
    modelsCachedPlain: 'Zwischengespeicherte Modelle verwendet. {count} Live-Modelle verfügbar.',
    savedModelReadyNoList:
      'Das aktuelle Modell ist verbunden und bereit. Dieser Anbieter hat keine Live-Modellliste geliefert; Trainer behält das gespeicherte Modell.',
    savedModelUnverifiedNoList:
      'Einstellungen gespeichert, aber Trainer konnte das aktuelle Modell noch nicht prüfen.',
    savedModelNoList:
      'Einstellungen gespeichert, aber Trainer konnte die Live-Modellliste noch nicht abrufen.',
    modelResolvedSuffix: ' Trainer hat das konfigurierte Modell zu {model} aufgelöst.',
    switchVerifying: "Zu Modell „{model}“ gewechselt. Trainer überprüft gerade die Verbindung.",
    switchAlreadyActive: 'Modell „{model}“ ist bereits aktiv.',
    switchModelNotAllowed:
      'Modell „{model}“ ist weder in der Anbieter-Modellliste noch im konfigurierten Modellkatalog enthalten.',
    switchVerifyingDetail:
      'Trainer ist zu {model} gewechselt und prüft die Verbindung; der Composer wird frei, sobald die Prüfung abgeschlossen ist.',
    switchCatalogDetail:
      'Trainer ist zum Katalogmodell {model} gewechselt. Testen oder aktualisieren Sie die Modelle, bevor Sie es als verfügbar behandeln.',
    clearNothingToClear: 'Keine Anbieterkonfiguration zum Löschen vorhanden.',
    clearCancelled: 'Löschen der Anbieterkonfiguration abgebrochen.',
    clearDone: 'Anbieterkonfiguration gelöscht.',
  },
  'ja-JP': {
    testConnected: '{name} に接続できました。',
    testConnectedReady: 'Trainer はこのモデルをすぐに使えます。',
    testMissingKey:
      '{name} は保存されましたが、API キーがまだ保存されていません。追加するまで Trainer は動作できません。',
    testCheckInterrupted: 'Trainer は接続確認を完了できませんでした。しばらくしてからもう一度お試しください。',
    testIncomplete:
      '{name} には必要な設定が不足しています。先に接続名・ベース URL・モデルを保存してください。',
    testLanguageCorruption:
      '{name} に到達できますが、中国語のテキストがモデルに届く前に壊れました。',
    testLanguageInconclusive:
      '{name} に到達できますが、中国語 (zh-CN) の整合性はまだ完全には確認されていません。',
    testEmptyReply: '{name} に到達できますが、応答は使用できませんでした。',
    testRespondedUnusable: '{name} は応答しましたが、Trainer はまだ使用できません。',
    testUnreachable: '{name} に接続できませんでした。',
    testUnreachableAdvice: 'ベース URL・モデル・API キーを確認して、もう一度お試しください。',
    saveChecking: '設定を保存しました。Trainer はライブモデルを取得し、応答品質を確認しています。',
    saveNoKey:
      '設定は保存されましたが、API キーが保存されていないため Trainer はまだ動作できません。先に追加してください。',
    saveLocalNoKey:
      '設定を保存しました。この接続はローカルサービスを指しているため、API キーなしで動作します。接続をテストして確認してください。',
    modelsLoadedVerified: 'ライブモデルを {count} 件読み込み、現在の接続を確認しました。',
    modelsLoadedInconclusive:
      'ライブモデルを {count} 件読み込みましたが、中国語 (zh-CN) の整合性にはさらなる確認が必要です。',
    modelsLoadedFailed:
      'ライブモデルを {count} 件読み込みましたが、Trainer はまだこの接続では指導できません。',
    modelsLoadedPlain: 'ライブモデルを {count} 件読み込みました。',
    modelsCachedVerified:
      'キャッシュ済みのモデルを使用し、現在の接続を確認しました。ライブモデルは {count} 件あります。',
    modelsCachedInconclusive:
      'キャッシュ済みモデルを使用しました（ライブ {count} 件）が、中国語の整合性にはさらなる確認が必要です。',
    modelsCachedFailed:
      'キャッシュ済みモデルを使用しました（ライブ {count} 件）が、Trainer はまだこの接続では指導できません。',
    modelsCachedPlain: 'キャッシュ済みモデルを使用しました。ライブモデルは {count} 件あります。',
    savedModelReadyNoList:
      '現在のモデルは接続済みで利用可能です。このプロバイダーはライブモデル一覧を返さなかったため、Trainer は保存済みモデルをそのまま使います。',
    savedModelUnverifiedNoList: '設定は保存されましたが、Trainer はまだ現在のモデルを確認できませんでした。',
    savedModelNoList: '設定は保存されましたが、ライブモデル一覧をまだ取得できませんでした。',
    modelResolvedSuffix: ' Trainer は設定されたモデルを {model} に解決しました。',
    switchVerifying: "モデル「{model}」に切り替えました。Trainer はこのモデルで接続を確認しています。",
    switchAlreadyActive: 'モデル「{model}」はすでに有効です。',
    switchModelNotAllowed:
      'モデル「{model}」はプロバイダーのモデル一覧にも設定済みカタログにも含まれていません。',
    switchVerifyingDetail:
      'Trainer は {model} に切り替え、接続を確認中です。確認が完了すると入力欄が自動的に使えるようになります。',
    switchCatalogDetail:
      'Trainer は設定済みカタログの {model} に切り替えました。利用可能とみなす前に、テストかモデル更新を行ってください。',
    clearNothingToClear: 'クリアするプロバイダー設定はありません。',
    clearCancelled: 'プロバイダー設定のクリアを取り消しました。',
    clearDone: 'プロバイダー設定をクリアしました。',
  },
  'ko-KR': {
    testConnected: '{name}에 연결되었습니다.',
    testConnectedReady: 'Trainer에서 이 모델을 바로 사용할 수 있습니다.',
    testMissingKey:
      '{name}이(가) 저장되었지만 아직 API 키가 저장되지 않았습니다. 키를 추가하기 전까지 Trainer는 동작할 수 없습니다.',
    testCheckInterrupted: 'Trainer가 연결 확인을 마치지 못했습니다. 잠시 후 다시 시도하세요.',
    testIncomplete:
      '{name}에 필수 설정이 없습니다. 연결 이름, 베이스 URL, 모델을 먼저 저장하세요.',
    testLanguageCorruption: '{name}에 연결되지만, 중국어 텍스트가 모델에 도달하기 전에 손상되었습니다.',
    testLanguageInconclusive:
      '{name}에 연결되지만, 중국어(zh-CN) 무결성이 아직 완전히 확인되지 않았습니다.',
    testEmptyReply: '{name}에 연결되지만, 응답을 사용할 수 없습니다.',
    testRespondedUnusable: '{name}이(가) 응답했지만 Trainer가 아직 사용할 수 없습니다.',
    testUnreachable: '{name}에 연결할 수 없습니다.',
    testUnreachableAdvice: '베이스 URL, 모델, API 키를 확인한 뒤 다시 시도하세요.',
    saveChecking: '설정이 저장되었습니다. Trainer가 라이브 모델을 가져오고 응답 품질을 확인하고 있습니다.',
    saveNoKey:
      '설정은 저장되었지만 API 키가 없어 Trainer가 아직 동작할 수 없습니다. 시작하기 전에 키를 추가하세요.',
    saveLocalNoKey:
      '설정이 저장되었습니다. 이 연결은 로컬 서비스를 가리키므로 API 키 없이 동작합니다. 연결을 테스트해 확인하세요.',
    modelsLoadedVerified: '라이브 모델 {count}개를 불러오고 현재 연결을 확인했습니다.',
    modelsLoadedInconclusive:
      '라이브 모델 {count}개를 불러왔지만, 중국어(zh-CN) 무결성 확인이 아직 필요합니다.',
    modelsLoadedFailed:
      '라이브 모델 {count}개를 불러왔지만, Trainer는 아직 이 연결로 수업할 수 없습니다.',
    modelsLoadedPlain: '라이브 모델 {count}개를 불러왔습니다.',
    modelsCachedVerified:
      '캐시된 모델을 사용해 현재 연결을 확인했습니다. 라이브 모델 {count}개를 사용할 수 있습니다.',
    modelsCachedInconclusive:
      '캐시된 모델을 사용했습니다(라이브 {count}개). 중국어 무결성 확인이 아직 필요합니다.',
    modelsCachedFailed:
      '캐시된 모델을 사용했습니다(라이브 {count}개). Trainer는 아직 이 연결로 수업할 수 없습니다.',
    modelsCachedPlain: '캐시된 모델을 사용했습니다. 라이브 모델 {count}개를 사용할 수 있습니다.',
    savedModelReadyNoList:
      '현재 모델은 연결되어 사용할 수 있습니다. 이 공급자는 라이브 모델 목록을 반환하지 않아 Trainer는 저장된 모델을 유지합니다.',
    savedModelUnverifiedNoList: '설정은 저장되었지만, Trainer가 아직 현재 모델을 확인하지 못했습니다.',
    savedModelNoList: '설정은 저장되었지만, 라이브 모델 목록을 아직 가져오지 못했습니다.',
    modelResolvedSuffix: ' Trainer가 설정된 모델을 {model}(으)로 해석했습니다.',
    switchVerifying: "모델 '{model}'(으)로 전환했습니다. Trainer가 이 모델의 연결을 확인하고 있습니다.",
    switchAlreadyActive: "모델 '{model}'은(는) 이미 활성 모델입니다.",
    switchModelNotAllowed:
      "모델 '{model}'은(는) 공급자 모델 목록이나 설정된 모델 카탈로그에 없습니다.",
    switchVerifyingDetail:
      'Trainer가 {model}(으)로 전환해 연결을 확인하고 있습니다. 확인이 끝나면 입력창이 자동으로 활성화됩니다.',
    switchCatalogDetail:
      'Trainer가 설정된 카탈로그의 {model}(으)로 전환했습니다. 사용 가능한 것으로 보기 전에 테스트하거나 모델을 새로 고치세요.',
    clearNothingToClear: '삭제할 공급자 설정이 없습니다.',
    clearCancelled: '공급자 설정 삭제가 취소되었습니다.',
    clearDone: '공급자 설정이 삭제되었습니다.',
  },
  'pt-BR': {
    testConnected: '{name} está conectado.',
    testConnectedReady: 'O Trainer já pode usar este modelo.',
    testMissingKey:
      '{name} foi salvo, mas ainda não há chave de API armazenada. O Trainer não funciona até você adicionar uma.',
    testCheckInterrupted: 'O Trainer não conseguiu concluir a verificação de conexão. Tente novamente em instantes.',
    testIncomplete:
      '{name} está sem configurações obrigatórias. Salve antes o nome, a URL base e o modelo.',
    testLanguageCorruption:
      '{name} responde, mas o texto em chinês foi corrompido antes de chegar ao modelo.',
    testLanguageInconclusive:
      '{name} responde, mas a integridade do chinês (zh-CN) ainda não está totalmente verificada.',
    testEmptyReply: '{name} responde, mas a resposta não pôde ser usada.',
    testRespondedUnusable: '{name} respondeu, mas o Trainer ainda não consegue usá-lo.',
    testUnreachable: 'Não foi possível conectar a {name}.',
    testUnreachableAdvice: 'Confira a URL base, o modelo e a chave de API e tente novamente.',
    saveChecking:
      'Configurações salvas. O Trainer está buscando modelos ao vivo e verificando a qualidade das respostas.',
    saveNoKey:
      'Configurações salvas, mas o Trainer ainda não funciona porque não há chave de API armazenada. Adicione uma antes de começar.',
    saveLocalNoKey:
      'Configurações salvas. Esta conexão aponta para um serviço local, então funciona sem chave de API. Teste a conexão para confirmar.',
    modelsLoadedVerified: '{count} modelos ao vivo carregados e a conexão atual foi verificada.',
    modelsLoadedInconclusive:
      '{count} modelos ao vivo carregados, mas a integridade do chinês (zh-CN) ainda precisa de verificação.',
    modelsLoadedFailed:
      '{count} modelos ao vivo carregados, mas o Trainer ainda não pode ensinar com esta conexão.',
    modelsLoadedPlain: '{count} modelos ao vivo carregados.',
    modelsCachedVerified:
      'Modelos em cache usados e conexão atual verificada. Há {count} modelos ao vivo disponíveis.',
    modelsCachedInconclusive:
      'Modelos em cache usados ({count} ao vivo), mas a integridade do chinês ainda precisa de verificação.',
    modelsCachedFailed:
      'Modelos em cache usados ({count} ao vivo), mas o Trainer ainda não pode ensinar com esta conexão.',
    modelsCachedPlain: 'Modelos em cache usados. Há {count} modelos ao vivo disponíveis.',
    savedModelReadyNoList:
      'O modelo atual está conectado e pronto. Este provedor não retornou uma lista de modelos ao vivo, então o Trainer manteve o modelo salvo.',
    savedModelUnverifiedNoList:
      'Configurações salvas, mas o Trainer ainda não pôde verificar o modelo atual.',
    savedModelNoList:
      'Configurações salvas, mas o Trainer ainda não conseguiu obter a lista de modelos ao vivo.',
    modelResolvedSuffix: ' O Trainer resolveu o modelo configurado para {model}.',
    switchVerifying: 'Mudado para o modelo “{model}”. O Trainer está verificando a conexão neste modelo.',
    switchAlreadyActive: 'O modelo “{model}” já é o modelo atual.',
    switchModelNotAllowed:
      'O modelo “{model}” não está na lista de modelos do provedor nem no catálogo configurado.',
    switchVerifyingDetail:
      'O Trainer mudou para {model} e está verificando a conexão; o compositor é liberado assim que a verificação termina.',
    switchCatalogDetail:
      'O Trainer mudou para {model} do catálogo configurado. Teste ou atualize os modelos antes de tratá-lo como disponível.',
    clearNothingToClear: 'Nenhuma configuração de provedor para limpar.',
    clearCancelled: 'Limpeza da configuração cancelada.',
    clearDone: 'Configuração do provedor limpa.',
  },
};

function hostUiLanguage(): ComposerLanguage | undefined {
  const language = vscode.env?.language?.trim().toLowerCase();
  if (!language) {
    return undefined;
  }
  if (language.startsWith('zh')) {
    return 'zh-CN';
  }
  if (language.startsWith('en')) {
    return 'en-US';
  }
  if (language.startsWith('es')) {
    return 'es-ES';
  }
  if (language.startsWith('fr')) {
    return 'fr-FR';
  }
  if (language.startsWith('de')) {
    return 'de-DE';
  }
  if (language.startsWith('ja')) {
    return 'ja-JP';
  }
  if (language.startsWith('ko')) {
    return 'ko-KR';
  }
  if (language.startsWith('pt')) {
    return 'pt-BR';
  }
  return undefined;
}

/**
 * Resolve the copy language from an explicit request, then the workspace
 * response-language setting, then the VS Code UI locale. Returns undefined so
 * callers can keep their own fallbacks.
 */
export function resolveProviderHostLanguage(
  requestedLanguage?: string | undefined,
  workspaceLanguage?: unknown,
): ComposerLanguage | undefined {
  if (isComposerLanguage(requestedLanguage)) {
    return requestedLanguage;
  }
  if (typeof workspaceLanguage === 'string' && isComposerLanguage(workspaceLanguage)) {
    return workspaceLanguage;
  }
  return hostUiLanguage();
}

export function providerHostCopy(
  language: ComposerLanguage | undefined,
  key: ProviderHostCopyKey,
  params?: Record<string, string | number>,
): string {
  const table = providerHostCopyTable[language ?? 'en-US'] ?? providerHostCopyTable['en-US'];
  let text = table[key] ?? providerHostCopyTable['en-US'][key];
  if (params) {
    for (const [name, value] of Object.entries(params)) {
      text = text.split(`{${name}}`).join(String(value));
    }
  }
  return text;
}
