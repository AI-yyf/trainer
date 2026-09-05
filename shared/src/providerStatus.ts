import type { ProviderProtocol } from "./models";
import {
  normalizeProviderProtocol,
  providerProtocolCompletionLabel,
  providerProtocolEndpointHint,
  providerProtocolFamily,
} from "./providerProtocols";
import type { ComposerLanguage } from "./types";

export type ProviderSurfaceLanguage = ComposerLanguage;

export interface ProviderStatusLike {
  configured: boolean;
  apiKeyConfigured: boolean;
  name?: string;
  baseUrl?: string;
  model: string;
  resolvedModel?: string;
  profileCount?: number;
  providerProfiles?: Array<Record<string, unknown>>;
  availableModels: string[];
  modelListStatus: 'idle' | 'loading' | 'ready' | 'error';
  modelListDetail?: string;
  modelErrorCategory?: string;
  modelRetryable?: boolean;
  protocol?: ProviderProtocol | string;
  capabilities?: {
    vision?: boolean;
    tools?: boolean;
  };
  lastTestResult?: {
    ok: boolean;
    status: string;
    detail?: string;
    errorCategory?: string;
    retryable?: boolean;
    checkedAt?: string;
    providerName?: string;
    baseUrl?: string;
    model?: string;
    protocol?: ProviderProtocol | string;
    responseLanguage?: string;
    capabilityEvidence?: Array<{
      name: string;
      declared: boolean;
      observed: boolean | null;
      state: 'verified' | 'unsupported' | 'unverified' | 'disabled';
    }>;
  };
}

export type ProviderSendStateStatus =
  | 'missing_provider'
  | 'missing_api_key'
  | 'warming'
  | 'blocked_error'
  | 'degraded_error'
  | 'refreshing'
  | 'ready';

export interface ProviderSendState {
  blocked: boolean;
  status: ProviderSendStateStatus;
  reason?: string;
  warning?: string;
}

export type ProviderTestFreshness = 'fresh' | 'stale' | 'unknown';

export interface ProviderTestReadiness {
  freshness: ProviderTestFreshness;
  targetsCurrentConnection: boolean | undefined;
  languageVerified: boolean;
  ready: boolean;
}

export const PROVIDER_TEST_FRESHNESS_WINDOW_MS = 30 * 60 * 1000;

export type ProviderImageInputStateStatus =
  | 'setup_required'
  | 'missing_vision'
  | 'missing_tools'
  | 'unsupported_protocol'
  | 'ready';

export interface ProviderImageInputState {
  supported: boolean;
  status: ProviderImageInputStateStatus;
  reason?: string;
  detail?: string;
}

const hardBlockingCategories = new Set([
  'invalid_key_or_permission',
  'invalid_api_key',
  'authentication_failed',
  'model_unsupported',
  'model_not_supported',
  'model_not_found',
  'language_corruption',
  'malformed_response',
  'empty_response',
  'reasoning_leak',
  'reasoning_budget_exhausted',
  'truncated_or_empty',
]);

const recentTestBlockingCategories = new Set([
  'invalid_key_or_permission',
  'invalid_api_key',
  'authentication_failed',
  'model_unsupported',
  'model_not_supported',
  'model_not_found',
  'language_corruption',
  'malformed_response',
  'empty_response',
  'reasoning_leak',
  'reasoning_budget_exhausted',
  'truncated_or_empty',
]);

const recentTestDegradedCategories = new Set([
  'rate_limit',
  'timeout',
  'network',
  'network_error',
  'context_length_exceeded',
  'language_probe_inconclusive',
]);

const recentTestConnectivityFailureCategories = new Set([
  'timeout',
  'network',
  'network_error',
]);

type ProviderStatusPhraseKey =
  | 'invalid_key_or_permission'
  | 'rate_limit'
  | 'timeout'
  | 'network'
  | 'malformed_response'
  | 'model_unsupported'
  | 'model_not_found'
  | 'workspace_trust'
  | 'sidecar_unavailable'
  | 'missing_provider_reason'
  | 'missing_api_key_reason'
  | 'generic_check_hint'
  | 'warming_reason'
  | 'degraded_warning'
  | 'model_list_unavailable_warning'
  | 'refreshing_warning'
  | 'missing_vision_reason'
  | 'missing_vision_detail'
  | 'missing_tools_reason'
  | 'missing_tools_detail'
  | 'image_ready_detail';

const providerStatusPhraseTable: Record<
  ProviderSurfaceLanguage,
  Record<ProviderStatusPhraseKey, string>
> = {
  'zh-CN': {
    invalid_key_or_permission: '这组连接暂时不能用。到“设置”检查密钥和权限后再试。',
    rate_limit: '服务正忙，请稍等再试。',
    timeout: '等了很久还没有回复。检查网络后再试。',
    network: '暂时连不上模型。检查连接后再试。',
    malformed_response: '收到的回复暂时无法使用。稍后再试，或换一个模型。',
    model_unsupported: '所选模型暂时不能用。到“设置”换一个模型。',
    model_not_found: '当前没有可用模型。到“设置”重新选择。',
    workspace_trust: '需要先信任当前工作区，才能继续。',
    sidecar_unavailable: 'Trainer 正在准备中，请稍等。',
    missing_provider_reason: '还没有完成模型连接。请到“设置”完成连接。',
    missing_api_key_reason: '这组连接还没完成。到“设置”补上密钥后再试。',
    generic_check_hint: '到“设置”检查连接后再试。',
    warming_reason: '正在检查连接，请稍等。',
    degraded_warning: '最近一次检查没有完成，Trainer 会先继续使用之前可用的模型。',
    model_list_unavailable_warning: '当前模型已通过连接测试，但模型列表暂时读取不到。可以继续使用，稍后再刷新。',
    refreshing_warning: '正在后台更新模型列表，Trainer 会继续使用之前可用的模型。',
    missing_vision_reason: '当前连接不支持图片输入，图片不会发送。',
    missing_vision_detail: '文字对话不受影响。换支持图片的模型后再试。',
    missing_tools_reason: '图片暂时不能发送，文字对话仍可使用。',
    missing_tools_detail: '换一个支持图片的模型，或先继续文字对话。',
    image_ready_detail: '图片输入已就绪。下一次教练对话会把暂存图片一并发给模型。',
  },
  'en-US': {
    invalid_key_or_permission: 'This connection cannot be used right now. Open Settings to check the key and access.',
    rate_limit: 'The service is busy right now. Wait a moment and try again.',
    timeout: 'The service took too long to reply. Check the connection and try again.',
    network: 'Trainer cannot reach the model right now. Check the connection and try again.',
    malformed_response: 'The reply cannot be used right now. Try again later or choose another model.',
    model_unsupported: 'The selected model cannot be used here. Choose another model in Settings.',
    model_not_found: 'No model is available right now. Choose another one in Settings.',
    workspace_trust: 'Trust this workspace before continuing.',
    sidecar_unavailable: 'Trainer is getting ready. Give it a moment.',
    missing_provider_reason: 'The model connection is not set up yet. Finish it in Settings.',
    missing_api_key_reason: 'This connection is not complete yet. Add the key in Settings, then try again.',
    generic_check_hint: 'Open Settings to check the connection, then try again.',
    warming_reason: 'Trainer is checking the connection. Give it a moment.',
    degraded_warning: 'The latest check did not finish, so Trainer will keep using the last working model for now.',
    model_list_unavailable_warning: 'The current model passed its connection test, but the model list is unavailable right now. You can keep using it and refresh later.',
    refreshing_warning: 'Trainer is updating the model list in the background and will keep using the last working model for now.',
    missing_vision_reason: 'Pictures cannot be sent right now; text coaching still works.',
    missing_vision_detail: 'Text coaching still works. Choose a model that supports pictures to use them.',
    missing_tools_reason: 'Pictures cannot be sent right now, but text coaching still works.',
    missing_tools_detail: 'Choose a model that supports pictures, or continue with text for now.',
    image_ready_detail: 'Image input is ready. Staged pictures will be sent with the next coach turn.',
  },
  'es-ES': {
    invalid_key_or_permission: 'La clave API no es válida o no tiene acceso a este modelo o proyecto.',
    rate_limit: 'El proveedor está limitando solicitudes ahora mismo. Espera un momento y vuelve a intentarlo.',
    timeout: 'La solicitud agotó el tiempo antes de que el proveedor respondiera.',
    network: 'Trainer no pudo llegar al proveedor. Revisa la base URL y la ruta de red.',
    malformed_response: 'El endpoint respondió con un formato que no coincide con el esquema compatible con OpenAI.',
    model_unsupported: 'El endpoint responde, pero no acepta el nombre de modelo configurado.',
    model_not_found: 'El endpoint responde, pero este gateway no tiene ahora mismo un canal disponible para ese modelo.',
    workspace_trust: 'Este workspace todavía no es de confianza, así que Trainer no puede obtener la lista de modelos.',
    sidecar_unavailable: 'El sidecar local de Trainer todavía no está listo, así que no se puede obtener la lista de modelos.',
    missing_provider_reason: 'Todavía no hay un proveedor guardado. Termina primero la configuración en Ajustes.',
    missing_api_key_reason: 'La conexión está guardada, pero todavía falta la clave API para que Trainer pueda funcionar.',
    generic_check_hint: 'Revisa la base URL, el nombre del modelo y los permisos.',
    warming_reason: 'Trainer todavía está comprobando la lista de modelos de este proveedor. Dale un momento.',
    degraded_warning: 'La última comprobación de modelos no terminó bien, así que Trainer seguirá usando por ahora el último modelo confirmado.',
    model_list_unavailable_warning: 'El modelo actual superó la prueba de conexión, pero la lista de modelos no está disponible ahora. Puedes seguir usándolo y actualizar más tarde.',
    refreshing_warning: 'Trainer está actualizando la lista de modelos en segundo plano y seguirá usando por ahora el último modelo confirmado.',
    missing_vision_reason: 'Esta conexión todavía no tiene visión, así que las imágenes preparadas no llegarán al modelo.',
    missing_vision_detail: 'La guía por texto está lista, pero la entrada de imágenes seguirá apagada hasta que cambies a un modelo o proveedor con visión.',
    missing_tools_reason: 'Esta conexión puede guiar por texto, pero las imágenes no llegarán realmente al modelo porque la entrada de imágenes de Trainer todavía depende del flujo con herramientas.',
    missing_tools_detail: 'Para que las imágenes lleguen de verdad al modelo, esta conexión necesita por ahora visión y llamadas a herramientas.',
    image_ready_detail: 'La entrada de imágenes está lista. Las imágenes preparadas se enviarán con el siguiente turno del coach.',
  },
  'fr-FR': {
    invalid_key_or_permission: "La clé API est invalide ou n'a pas accès à ce modèle ou projet.",
    rate_limit: 'Le fournisseur limite actuellement les requêtes. Attendez un moment puis réessayez.',
    timeout: "La requête a expiré avant que le fournisseur ne réponde.",
    network: "Trainer n'a pas pu joindre le fournisseur. Vérifiez la base URL et le chemin réseau.",
    malformed_response: "Le point de terminaison a renvoyé un format qui ne correspond pas au schéma compatible OpenAI.",
    model_unsupported: "Le point de terminaison répond, mais le nom du modèle configuré n'est pas accepté.",
    model_not_found: "Le point de terminaison répond, mais cette passerelle n'a actuellement aucun canal disponible pour ce modèle.",
    workspace_trust: "Cet espace de travail n'est pas encore approuvé, donc Trainer ne peut pas récupérer la liste des modèles.",
    sidecar_unavailable: "Le sidecar local de Trainer n'est pas encore prêt, donc la liste des modèles ne peut pas être récupérée.",
    missing_provider_reason: "Aucun fournisseur de modèle n'est encore enregistré. Terminez d'abord la configuration dans Réglages.",
    missing_api_key_reason: "La connexion est enregistrée, mais il manque encore la clé API pour que Trainer puisse fonctionner.",
    generic_check_hint: 'Vérifiez la base URL, le nom du modèle et les autorisations.',
    warming_reason: 'Trainer vérifie encore la liste des modèles pour ce fournisseur. Patientez un instant.',
    degraded_warning: "La dernière vérification des modèles n'a pas complètement réussi, donc Trainer continuera pour l'instant avec le dernier modèle confirmé.",
    model_list_unavailable_warning: 'Le modèle actuel a réussi le test de connexion, mais la liste des modèles est indisponible pour le moment. Vous pouvez continuer à l’utiliser et actualiser plus tard.',
    refreshing_warning: "Trainer actualise la liste des modèles en arrière-plan et continuera pour l'instant avec le dernier modèle confirmé.",
    missing_vision_reason: "Cette connexion n'a pas encore la vision, donc les images préparées ne parviendront pas au modèle.",
    missing_vision_detail: "Le coaching texte est prêt, mais l'entrée image restera désactivée tant que vous n'utiliserez pas un modèle ou fournisseur avec vision.",
    missing_tools_reason: "Cette connexion peut coacher en texte, mais les images n'atteindront pas réellement le modèle car l'entrée image de Trainer dépend encore du chemin avec outils.",
    missing_tools_detail: "Pour que les images atteignent réellement le modèle, cette connexion a actuellement besoin à la fois de vision et d'appels d'outils.",
    image_ready_detail: "L'entrée image est prête. Les images préparées seront envoyées avec le prochain tour du coach.",
  },
  'de-DE': {
    invalid_key_or_permission: 'Der API-Schlüssel ist ungültig oder hat keinen Zugriff auf dieses Modell oder Projekt.',
    rate_limit: 'Der Anbieter begrenzt Anfragen gerade. Warten Sie kurz und versuchen Sie es erneut.',
    timeout: 'Die Anfrage hat das Zeitlimit erreicht, bevor der Anbieter geantwortet hat.',
    network: 'Trainer konnte den Anbieter nicht erreichen. Prüfen Sie Base URL und Netzwerkpfad.',
    malformed_response: 'Der Endpunkt hat ein Format zurückgegeben, das nicht zum OpenAI-kompatiblen Schema passt.',
    model_unsupported: 'Der Endpunkt ist erreichbar, akzeptiert aber den konfigurierten Modellnamen nicht.',
    model_not_found: 'Der Endpunkt ist erreichbar, aber dieses Gateway hat derzeit keinen verfügbaren Kanal für das Modell.',
    workspace_trust: 'Dieser Arbeitsbereich ist noch nicht vertrauenswürdig, daher kann Trainer die Modellliste nicht laden.',
    sidecar_unavailable: 'Der lokale Trainer-Sidecar ist noch nicht bereit, daher kann die Modellliste nicht geladen werden.',
    missing_provider_reason: 'Es ist noch kein Modellanbieter gespeichert. Schließen Sie zuerst die Einrichtung in Einstellungen ab.',
    missing_api_key_reason: 'Die Verbindung ist gespeichert, aber Trainer braucht noch einen API-Schlüssel, bevor es arbeiten kann.',
    generic_check_hint: 'Prüfen Sie Base URL, Modellname und Berechtigungen.',
    warming_reason: 'Trainer prüft noch die Modellliste dieses Anbieters. Einen Moment bitte.',
    degraded_warning: 'Die letzte Modellprüfung war nicht vollständig erfolgreich, daher verwendet Trainer vorerst weiter das zuletzt bestätigte Modell.',
    model_list_unavailable_warning: 'Das aktuelle Modell hat den Verbindungstest bestanden, aber die Modellliste ist gerade nicht verfügbar. Sie können es weiter verwenden und später aktualisieren.',
    refreshing_warning: 'Trainer aktualisiert die Modellliste im Hintergrund und verwendet vorerst weiter das zuletzt bestätigte Modell.',
    missing_vision_reason: 'Diese Verbindung hat noch keine Vision-Fähigkeit, daher erreichen vorbereitete Bilder das Modell nicht.',
    missing_vision_detail: 'Text-Coaching ist bereit, aber die Bildeingabe bleibt aus, bis Sie zu einem Modell oder Anbieter mit Vision wechseln.',
    missing_tools_reason: 'Diese Verbindung kann textbasiert coachen, aber Bilder erreichen das Modell nicht wirklich, weil die Bildeingabe von Trainer noch vom Werkzeugpfad abhängt.',
    missing_tools_detail: 'Damit Bilder das Modell wirklich erreichen, braucht diese Verbindung derzeit sowohl Vision als auch Tool-Aufrufe.',
    image_ready_detail: 'Die Bildeingabe ist bereit. Vorbereitete Bilder werden mit der nächsten Coach-Nachricht gesendet.',
  },
  'ja-JP': {
    invalid_key_or_permission: 'API キーが無効か、このモデルまたはプロジェクトへの権限がありません。',
    rate_limit: '現在プロバイダー側でレート制限中です。少し待ってからもう一度試してください。',
    timeout: 'プロバイダーが応答する前にリクエストがタイムアウトしました。',
    network: 'Trainer はプロバイダーに接続できませんでした。base URL とネットワーク経路を確認してください。',
    malformed_response: 'エンドポイントの応答形式が OpenAI 互換スキーマと一致しません。',
    model_unsupported: 'エンドポイントには接続できますが、設定したモデル名は受け付けられていません。',
    model_not_found: 'エンドポイントには接続できますが、このゲートウェイには現在そのモデル向けの利用可能なチャネルがありません。',
    workspace_trust: 'このワークスペースはまだ信頼されていないため、Trainer はモデル一覧を取得できません。',
    sidecar_unavailable: 'ローカルの Trainer sidecar がまだ準備できていないため、モデル一覧を取得できません。',
    missing_provider_reason: 'まだモデルプロバイダーが保存されていません。先に設定画面で provider 設定を完了してください。',
    missing_api_key_reason: '接続は保存されていますが、Trainer が動くには API キーがまだ必要です。',
    generic_check_hint: 'base URL、モデル名、権限を確認してください。',
    warming_reason: 'Trainer はこの provider のモデル一覧をまだ確認中です。少し待ってください。',
    degraded_warning: '直近のモデル確認は完全には成功していないため、Trainer はいったん最後に確認できたモデルを使い続けます。',
    model_list_unavailable_warning: '現在のモデルは接続テストに通りましたが、モデル一覧は今は取得できません。引き続き使えます。あとで更新してください。',
    refreshing_warning: 'Trainer はバックグラウンドでモデル一覧を更新しており、いったん最後に確認できたモデルを使い続けます。',
    missing_vision_reason: 'この接続ではまだ視覚機能が有効ではないため、準備した画像はモデルに届きません。',
    missing_vision_detail: 'テキスト指導は利用できますが、画像入力は vision 対応のモデルまたは provider に切り替えるまで無効のままです。',
    missing_tools_reason: 'この接続はテキスト指導には使えますが、Trainer の画像入力はまだツール呼び出し経路に依存しているため、画像は実際にはモデルへ届きません。',
    missing_tools_detail: '画像を本当にモデルへ届けるには、この接続で vision とツール呼び出しの両方が必要です。',
    image_ready_detail: '画像入力の準備ができました。準備済みの画像は次の coach ターンで送信されます。',
  },
  'ko-KR': {
    invalid_key_or_permission: 'API 키가 올바르지 않거나 이 모델 또는 프로젝트에 접근 권한이 없습니다.',
    rate_limit: '현재 제공자가 속도를 제한하고 있습니다. 잠시 후 다시 시도하세요.',
    timeout: '제공자가 응답하기 전에 요청 시간이 초과되었습니다.',
    network: 'Trainer가 제공자에 도달하지 못했습니다. base URL과 네트워크 경로를 확인하세요.',
    malformed_response: '엔드포인트가 OpenAI 호환 형식과 맞지 않는 응답을 돌려주었습니다.',
    model_unsupported: '엔드포인트에는 연결되지만 설정된 모델 이름을 받아들이지 않습니다.',
    model_not_found: '엔드포인트에는 연결되지만 이 게이트웨이에는 현재 해당 모델용 채널이 없습니다.',
    workspace_trust: '이 워크스페이스는 아직 신뢰되지 않아 Trainer가 모델 목록을 가져올 수 없습니다.',
    sidecar_unavailable: '로컬 Trainer 사이드카가 아직 준비되지 않아 모델 목록을 가져올 수 없습니다.',
    missing_provider_reason: '저장된 모델 제공자가 아직 없습니다. 먼저 설정에서 provider 구성을 완료하세요.',
    missing_api_key_reason: '연결은 저장되었지만 Trainer가 작동하려면 아직 API 키가 필요합니다.',
    generic_check_hint: 'base URL, 모델 이름, 권한을 확인하세요.',
    warming_reason: 'Trainer가 이 provider의 모델 목록을 아직 확인 중입니다. 잠시만 기다려 주세요.',
    degraded_warning: '최근 모델 확인이 완전히 성공하지 못해 Trainer는 우선 마지막으로 확인된 모델을 계속 사용합니다.',
    model_list_unavailable_warning: '현재 모델은 연결 테스트를 통과했지만 모델 목록을 지금 가져올 수 없습니다. 계속 사용할 수 있으며 나중에 새로 고침할 수 있습니다.',
    refreshing_warning: 'Trainer가 백그라운드에서 모델 목록을 새로 고치는 동안 마지막으로 확인된 모델을 계속 사용합니다.',
    missing_vision_reason: '이 연결에는 아직 비전 기능이 없어 준비된 이미지가 모델에 도달하지 않습니다.',
    missing_vision_detail: '텍스트 코칭은 가능하지만 비전 지원 모델이나 provider로 바꾸기 전까지 이미지 입력은 꺼진 상태로 유지됩니다.',
    missing_tools_reason: '이 연결은 텍스트 코칭은 가능하지만 Trainer의 이미지 입력이 아직 도구 호출 경로에 의존하므로 이미지는 실제로 모델에 도달하지 않습니다.',
    missing_tools_detail: '이미지가 실제로 모델에 도달하려면 현재 이 연결에 비전과 도구 호출이 모두 필요합니다.',
    image_ready_detail: '이미지 입력이 준비되었습니다. 준비된 이미지는 다음 coach 턴과 함께 전송됩니다.',
  },
  'pt-BR': {
    invalid_key_or_permission: 'A chave de API é inválida ou não tem acesso a este modelo ou projeto.',
    rate_limit: 'O provedor está limitando requisições agora. Espere um momento e tente novamente.',
    timeout: 'A solicitação expirou antes de o provedor responder.',
    network: 'O Trainer não conseguiu alcançar o provedor. Verifique a base URL e o caminho de rede.',
    malformed_response: 'O endpoint respondeu com um formato que não corresponde ao esquema compatível com OpenAI.',
    model_unsupported: 'O endpoint está acessível, mas não aceita o nome de modelo configurado.',
    model_not_found: 'O endpoint está acessível, mas este gateway não tem no momento um canal disponível para esse modelo.',
    workspace_trust: 'Este workspace ainda não é confiável, então o Trainer não pode buscar a lista de modelos.',
    sidecar_unavailable: 'O sidecar local do Trainer ainda não está pronto, então a lista de modelos não pode ser buscada.',
    missing_provider_reason: 'Ainda não há um provedor salvo. Termine primeiro a configuração em Ajustes.',
    missing_api_key_reason: 'A conexão está salva, mas o Trainer ainda precisa de uma chave de API para funcionar.',
    generic_check_hint: 'Verifique a base URL, o nome do modelo e as permissões.',
    warming_reason: 'O Trainer ainda está confirmando a lista de modelos deste provedor. Aguarde um momento.',
    degraded_warning: 'A última verificação de modelos não terminou totalmente bem, então o Trainer continuará usando por enquanto o último modelo confirmado.',
    model_list_unavailable_warning: 'O modelo atual passou no teste de conexão, mas a lista de modelos não está disponível agora. Você pode continuar usando-o e atualizar mais tarde.',
    refreshing_warning: 'O Trainer está atualizando a lista de modelos em segundo plano e continuará usando por enquanto o último modelo confirmado.',
    missing_vision_reason: 'Esta conexão ainda não tem visão, então as imagens preparadas não chegarão ao modelo.',
    missing_vision_detail: 'O coaching por texto está pronto, mas a entrada de imagem continuará desligada até você mudar para um modelo ou provedor com visão.',
    missing_tools_reason: 'Esta conexão consegue orientar por texto, mas as imagens não chegarão de fato ao modelo porque a entrada de imagem do Trainer ainda depende do fluxo com ferramentas.',
    missing_tools_detail: 'Para que as imagens realmente cheguem ao modelo, esta conexão precisa no momento de visão e chamadas de ferramentas.',
    image_ready_detail: 'A entrada de imagem está pronta. As imagens preparadas serão enviadas no próximo turno do coach.',
  },
};

const unsupportedImageProtocolByLanguage: Record<
  ProviderSurfaceLanguage,
  { reason: string; detail: string }
> = {
  'zh-CN': {
    reason: '图片暂时不能通过这条连接发送。',
    detail: '请在“设置”里换一条支持图片的连接，或先继续文字对话。',
  },
  'en-US': {
    reason: 'Pictures cannot be sent through this connection yet.',
    detail: 'In Settings, choose a connection that supports pictures, or continue with text for now.',
  },
  'es-ES': {
    reason: 'El protocol actual todavía no puede enviar imágenes de forma fiable al modelo.',
    detail: 'Trainer solo envía imágenes por sus rutas verificadas OpenAI Chat o Anthropic Messages. Cambia el protocol o usa verificación de texto.',
  },
  'fr-FR': {
    reason: 'Le protocol actuel ne peut pas encore transmettre les images de manière fiable au modèle.',
    detail: 'Trainer envoie les images uniquement par ses chemins vérifiés OpenAI Chat ou Anthropic Messages. Changez de protocol ou utilisez une vérification textuelle.',
  },
  'de-DE': {
    reason: 'Das aktuelle protocol kann Bilder noch nicht zuverlässig an das Modell senden.',
    detail: 'Trainer sendet Bilder nur über seine verifizierten OpenAI-Chat- oder Anthropic-Messages-Pfade. Wechseln Sie das protocol oder nutzen Sie Textverifikation.',
  },
  'ja-JP': {
    reason: '現在の protocol では画像を確実にモデルへ送れません。',
    detail: 'Trainer は検証済みの OpenAI Chat または Anthropic Messages 経路でのみ画像を送信します。protocol を切り替えるか、テキスト検証を使ってください。',
  },
  'ko-KR': {
    reason: '현재 protocol은 이미지를 모델에 안정적으로 전달할 수 없습니다.',
    detail: 'Trainer는 검증된 OpenAI Chat 또는 Anthropic Messages 경로로만 이미지를 보냅니다. protocol을 바꾸거나 텍스트 검증을 사용하세요.',
  },
  'pt-BR': {
    reason: 'O protocol atual ainda não consegue enviar imagens ao modelo com confiança.',
    detail: 'O Trainer envia imagens apenas pelos caminhos verificados OpenAI Chat ou Anthropic Messages. Troque o protocol ou use verificação por texto.',
  },
};

const unverifiedProviderWarningByLanguage: Record<ProviderSurfaceLanguage, string> = {
  'zh-CN': '这组连接还没有确认可用。先测试连接或刷新模型后再继续。',
  'en-US': 'This connection has not been confirmed yet. Test it or refresh models before continuing.',
  'es-ES': 'Este modelo aún no se ha verificado. Prueba la conexión o actualiza los modelos antes de confiar en él.',
  'fr-FR': "Ce modèle n'a pas encore été vérifié. Testez la connexion ou actualisez les modèles avant de vous y fier.",
  'de-DE': 'Dieses Modell ist noch nicht verifiziert. Testen Sie die Verbindung oder aktualisieren Sie die Modelle, bevor Sie sich darauf verlassen.',
  'ja-JP': 'この model はまだ検証されていません。使用する前に接続をテストするか、models を更新してください。',
  'ko-KR': '이 model은 아직 검증되지 않았습니다. 사용하기 전에 연결을 테스트하거나 models를 새로 고치세요.',
  'pt-BR': 'Este model ainda não foi verificado. Teste a conexão ou atualize os models antes de depender dele.',
};

function unverifiedProviderWarning(language: ProviderSurfaceLanguage): string {
  return unverifiedProviderWarningByLanguage[language] ?? unverifiedProviderWarningByLanguage['en-US'];
}

const providerErrorCategoryKeyMap: Partial<Record<string, ProviderStatusPhraseKey>> = {
  invalid_key_or_permission: 'invalid_key_or_permission',
  invalid_api_key: 'invalid_key_or_permission',
  authentication_failed: 'invalid_key_or_permission',
  rate_limit: 'rate_limit',
  timeout: 'timeout',
  network: 'network',
  network_error: 'network',
  malformed_response: 'malformed_response',
  model_unsupported: 'model_unsupported',
  model_not_supported: 'model_unsupported',
  model_not_found: 'model_not_found',
  workspace_trust: 'workspace_trust',
  sidecar_unavailable: 'sidecar_unavailable',
};

function providerStatusPhrase(
  language: ProviderSurfaceLanguage,
  key: ProviderStatusPhraseKey,
): string {
  return providerStatusPhraseTable[language]?.[key] ?? providerStatusPhraseTable['en-US'][key];
}

export function countSavedProviderProfiles(
  provider: Pick<ProviderStatusLike, 'profileCount' | 'providerProfiles'>,
): number {
  const countedProfiles = Array.isArray(provider.providerProfiles)
    ? provider.providerProfiles.filter(
        (item): item is Record<string, unknown> =>
          Boolean(item) && typeof item === 'object' && !Array.isArray(item),
      ).length
    : 0;
  const declaredCount =
    typeof provider.profileCount === 'number' && Number.isFinite(provider.profileCount)
      ? Math.max(0, Math.trunc(provider.profileCount))
      : 0;
  return Math.max(countedProfiles, declaredCount);
}

export function hasSavedProviderProfiles(
  provider: Pick<ProviderStatusLike, 'profileCount' | 'providerProfiles'>,
): boolean {
  return countSavedProviderProfiles(provider) > 0;
}

function missingProviderReason(
  provider: Pick<ProviderStatusLike, 'profileCount' | 'providerProfiles'>,
  language: ProviderSurfaceLanguage,
): string {
  if (!hasSavedProviderProfiles(provider)) {
    return providerStatusPhrase(language, 'missing_provider_reason');
  }

  switch (language) {
    case 'zh-CN':
      return '还没有选中可用连接。到“设置”选择已保存的连接。';
    case 'es-ES':
      return 'Todavía no hay un provider activo. Elige primero un profile guardado en Ajustes.';
    case 'fr-FR':
      return "Aucun provider actif n'est appliqué pour l'instant. Choisissez d'abord un profile enregistré dans Réglages.";
    case 'de-DE':
      return 'Es ist noch kein aktiver provider angewendet. Wählen Sie zuerst ein gespeichertes profile in Einstellungen aus.';
    case 'ja-JP':
      return 'まだ有効な provider は適用されていません。先に設定で保存済み profile を選んでください。';
    case 'ko-KR':
      return '아직 활성 provider가 적용되지 않았습니다. 먼저 설정에서 저장된 profile을 선택하세요.';
    case 'pt-BR':
      return 'Ainda não há um provider ativo aplicado. Escolha primeiro um profile salvo em Ajustes.';
    case 'en-US':
    default:
      return 'No saved connection is selected yet. Open Settings and choose one.';
  }
}

export function isCoachProviderBlockingCategory(category: string | undefined | null): boolean {
  return Boolean(category && hardBlockingCategories.has(category));
}

export function providerTransportIsConfigured(
  provider:
    | {
        name?: string;
        baseUrl?: string;
        model?: string;
      }
    | null
    | undefined,
): boolean {
  return Boolean(String(provider?.baseUrl ?? "").trim() && String(provider?.model ?? "").trim());
}

function providerCapabilityIsVerified(
  provider: Pick<ProviderStatusLike, 'capabilities' | 'lastTestResult'> | undefined,
  name: string,
): boolean {
  const evidence = provider?.lastTestResult?.capabilityEvidence?.find(
    (entry) => entry.name.trim().toLowerCase() === name,
  );
  return evidence?.state === 'verified' && evidence.observed === true;
}

function providerHasVisionCapability(
  provider: Pick<ProviderStatusLike, 'capabilities' | 'lastTestResult'> | undefined,
): boolean {
  return providerCapabilityIsVerified(provider, 'vision');
}

function providerHasToolCapability(
  provider: Pick<ProviderStatusLike, 'capabilities' | 'lastTestResult'> | undefined,
): boolean {
  return providerCapabilityIsVerified(provider, 'tools');
}

function providerSupportsImageProtocol(
  provider: Pick<ProviderStatusLike, 'protocol'> | undefined,
): boolean {
  if (!provider?.protocol) {
    return true;
  }
  const protocol = normalizeProviderProtocol(provider.protocol);
  return Boolean(protocol);
}

export function providerSupportsImageInput(
  provider: Pick<ProviderStatusLike, 'capabilities' | 'protocol' | 'lastTestResult'> | undefined,
): boolean {
  return (
    providerHasVisionCapability(provider) &&
    providerSupportsImageProtocol(provider)
  );
}

function providerSurfacePrefersChinese(language: string | undefined): boolean {
  return Boolean(language && language.toLowerCase().startsWith('zh'));
}

function lastProviderTestTargetedChinese(
  lastTest: NonNullable<ProviderStatusLike['lastTestResult']>,
): boolean {
  return Boolean(lastTest.responseLanguage && lastTest.responseLanguage.toLowerCase().startsWith('zh'));
}

function normalizeProviderTestTarget(value: string | undefined): string | undefined {
  const normalized = value?.trim().replace(/\/+$/, '').toLowerCase();
  return normalized || undefined;
}

export function providerTestTargetsCurrentConnection(
  provider: Pick<ProviderStatusLike, 'name' | 'baseUrl' | 'model' | 'protocol' | 'lastTestResult'>,
): boolean | undefined {
  const lastTest = provider.lastTestResult;
  if (!lastTest) {
    return undefined;
  }

  const testProvider = normalizeProviderTestTarget(lastTest.providerName);
  const testBaseUrl = normalizeProviderTestTarget(lastTest.baseUrl);
  const testModel = normalizeProviderTestTarget(lastTest.model);
  const providerName = normalizeProviderTestTarget(provider.name);
  const providerBaseUrl = normalizeProviderTestTarget(provider.baseUrl);
  const providerModel = normalizeProviderTestTarget(provider.model);

  if (!testProvider || !testBaseUrl || !testModel || !providerName || !providerBaseUrl || !providerModel) {
    return undefined;
  }

  if (testProvider !== providerName || testBaseUrl !== providerBaseUrl || testModel !== providerModel) {
    return false;
  }

  const testProtocol = normalizeProviderTestTarget(lastTest.protocol);
  const providerProtocol = normalizeProviderTestTarget(provider.protocol);
  return !testProtocol || !providerProtocol || testProtocol === providerProtocol;
}

export function describeProviderTestReadiness(
  provider: Pick<ProviderStatusLike, 'name' | 'baseUrl' | 'model' | 'protocol' | 'lastTestResult'>,
  language: ProviderSurfaceLanguage,
  now = Date.now(),
): ProviderTestReadiness {
  const lastTest = provider.lastTestResult;
  const targetsCurrentConnection = providerTestTargetsCurrentConnection(provider);
  const languageVerified =
    !providerSurfacePrefersChinese(language) || Boolean(lastTest && lastProviderTestTargetedChinese(lastTest));
  const checkedAt = lastTest?.checkedAt?.trim();
  const checkedAtMs = checkedAt ? Date.parse(checkedAt) : Number.NaN;
  const currentTime = Number.isFinite(now) ? now : Date.now();

  if (!lastTest || !Number.isFinite(checkedAtMs) || checkedAtMs > currentTime || targetsCurrentConnection === undefined) {
    return {
      freshness: 'unknown',
      targetsCurrentConnection,
      languageVerified,
      ready: false,
    };
  }

  if (!targetsCurrentConnection || currentTime - checkedAtMs > PROVIDER_TEST_FRESHNESS_WINDOW_MS) {
    return {
      freshness: 'stale',
      targetsCurrentConnection,
      languageVerified,
      ready: false,
    };
  }

  return {
    freshness: 'fresh',
    targetsCurrentConnection,
    languageVerified,
    ready: lastTest.ok === true && languageVerified,
  };
}

function languageIntegrityFallbackWarning(language: ProviderSurfaceLanguage): string {
  if (providerSurfacePrefersChinese(language)) {
    return '最近一次检查发现中文消息没有正常送达。请在“设置”更换连接；暂时可以用英文继续。';
  }
  return 'The latest check found that Chinese messages are not arriving intact. In Settings, switch connections; English can still work for now.';
}

function languageIntegrityInconclusiveWarning(
  language: ProviderSurfaceLanguage,
  targetedChinese: boolean,
): string {
  if (targetedChinese) {
    if (providerSurfacePrefersChinese(language)) {
      return '这条连接可以使用，但中文消息还没有完全确认。请重新测试；需要时可暂时用英文继续。';
    }
    return 'This connection can work, but Chinese messages are not fully confirmed yet. Test again; use English for now if needed.';
  }
  if (providerSurfacePrefersChinese(language)) {
    return '这条连接可以使用，但消息是否完整送达还没确认。建议重新测试后再继续。';
  }
  return 'This connection can work, but message delivery is not fully confirmed yet. Test again before relying on it.';
}

function visibleCoachingTextRecovery(language: ProviderSurfaceLanguage): string {
  const messages: Record<ProviderSurfaceLanguage, string> = {
    'zh-CN': '这组连接没有返回可用回复。到“设置”换一个模型后重新测试。',
    'en-US': 'This connection returned no usable reply. In Settings, choose another model and test again.',
    'es-ES': 'Este provider no devolvi\u00f3 texto visible del coach. Elige un modelo o gateway que devuelva una respuesta final y vuelve a probar.',
    'fr-FR': "Le provider n'a renvoy\u00e9 aucun texte de coaching visible. Choisissez un mod\u00e8le ou une passerelle qui renvoie une r\u00e9ponse finale, puis testez \u00e0 nouveau.",
    'de-DE': 'Der Anbieter hat keinen sichtbaren Coaching-Text zur\u00fcckgegeben. W\u00e4hlen Sie ein Modell oder Gateway, das eine abschlie\u00dfende Antwort zur\u00fcckgibt, und testen Sie erneut.',
    'ja-JP': '\u3053\u306e provider \u306f\u8868\u793a\u53ef\u80fd\u306a\u30b3\u30fc\u30c1\u5fdc\u7b54\u3092\u8fd4\u3057\u307e\u305b\u3093\u3067\u3057\u305f\u3002\u6700\u7d42\u56de\u7b54\u3092\u8fd4\u3059\u30e2\u30c7\u30eb\u307e\u305f\u306f gateway \u3092\u9078\u3093\u3067\u3001\u3082\u3046\u4e00\u5ea6\u30c6\u30b9\u30c8\u3057\u3066\u304f\u3060\u3055\u3044\u3002',
    'ko-KR': '\uc774 provider\ub294 \ud45c\uc2dc\ud560 \uc218 \uc788\ub294 \ucf54\uce6d \ud14d\uc2a4\ud2b8\ub97c \ubc18\ud658\ud558\uc9c0 \uc54a\uc558\uc2b5\ub2c8\ub2e4. \ucd5c\uc885 \ub2f5\ubcc0\uc744 \ubc18\ud658\ud558\ub294 \ubaa8\ub378 \ub610\ub294 gateway\ub97c \uc120\ud0dd\ud55c \ub2e4\uc74c \ub2e4\uc2dc \ud14c\uc2a4\ud2b8\ud558\uc138\uc694.',
    'pt-BR': 'O provider n\u00e3o retornou texto vis\u00edvel do coach. Escolha um modelo ou gateway que retorne uma resposta final e teste novamente.',
  };

  return messages[language] ?? messages['en-US'];
}

export function providerErrorHint(
  provider: Pick<ProviderStatusLike, 'modelErrorCategory' | 'modelListDetail'>,
  language: ProviderSurfaceLanguage,
): string | undefined {
  const category = provider.modelErrorCategory;
  if (!category) {
    return undefined;
  }

  if (category === 'language_corruption') {
    return language === 'zh-CN'
      ? '中文消息没有正常送达。请在“设置”更换连接，或暂时用英文继续。'
      : 'Chinese messages are not arriving intact. In Settings, switch connections or use English for now.';
  }

  if (category === 'language_probe_inconclusive') {
    return language === 'zh-CN'
      ? '这条连接可以使用，但中文消息还没有完全确认。请重新测试。'
      : 'This connection can work, but Chinese messages are not fully confirmed yet. Test again.';
  }

  if (category === 'empty_response' || category === 'reasoning_leak' || category === 'reasoning_budget_exhausted') {
    return visibleCoachingTextRecovery(language);
  }

  const translatedCategory = providerErrorCategoryKeyMap[category];
  if (translatedCategory) {
    return providerStatusPhrase(language, translatedCategory);
  }
  return undefined;
}

function providerGenericCheckHint(language: ProviderSurfaceLanguage): string {
  return providerStatusPhrase(language, 'generic_check_hint');
}

function providerDegradedWarning(
  language: ProviderSurfaceLanguage,
  hint: string | undefined,
): string {
  return `${providerStatusPhrase(language, 'degraded_warning')}${hint ? ` ${hint}` : ''}`.trim();
}

function describeRecentProviderTestState(
  provider: Pick<
    ProviderStatusLike,
    'name' | 'baseUrl' | 'model' | 'protocol' | 'lastTestResult'
  >,
  language: ProviderSurfaceLanguage,
  now: number,
): ProviderSendState | undefined {
  const lastTest = provider.lastTestResult;
  if (!lastTest || lastTest.ok !== false) {
    return undefined;
  }

  const category = lastTest.errorCategory ?? lastTest.status;
  const hint =
    providerErrorHint(
      {
        modelErrorCategory: category,
        modelListDetail: lastTest.detail,
      },
      language,
    ) ??
    providerGenericCheckHint(language);

  if (
    category === 'language_corruption' &&
    lastProviderTestTargetedChinese(lastTest) &&
    !providerSurfacePrefersChinese(language)
  ) {
    return {
      blocked: false,
      status: 'degraded_error',
      warning: languageIntegrityFallbackWarning(language),
    };
  }

  if (category === 'language_probe_inconclusive') {
    return {
      blocked: false,
      status: 'degraded_error',
      warning: languageIntegrityInconclusiveWarning(
        language,
        lastProviderTestTargetedChinese(lastTest),
      ),
    };
  }

  const testReadiness = describeProviderTestReadiness(provider, language, now);
  if (
    category &&
    recentTestConnectivityFailureCategories.has(category) &&
    testReadiness.freshness === 'fresh' &&
    testReadiness.targetsCurrentConnection === true
  ) {
    return {
      blocked: true,
      status: 'blocked_error',
      reason: hint,
    };
  }

  if (category && recentTestBlockingCategories.has(category)) {
    return {
      blocked: true,
      status: 'blocked_error',
      reason: hint,
    };
  }

  if (category && recentTestDegradedCategories.has(category)) {
    return {
      blocked: false,
      status: 'degraded_error',
      warning: providerDegradedWarning(language, hint),
    };
  }

  if (lastTest.retryable === true) {
    return {
      blocked: false,
      status: 'degraded_error',
      warning: providerDegradedWarning(language, hint),
    };
  }

  return {
    blocked: true,
    status: 'blocked_error',
    reason: hint,
  };
}

export function describeProviderSendState(
  provider: ProviderStatusLike,
  language: ProviderSurfaceLanguage,
  now = Date.now(),
): ProviderSendState {
  const transportMissing =
    (provider.baseUrl !== undefined && !String(provider.baseUrl).trim()) ||
    (provider.model !== undefined && !String(provider.model).trim());
  if (!provider.configured || transportMissing) {
    return {
      blocked: true,
      status: 'missing_provider',
      reason: missingProviderReason(provider, language),
    };
  }

  if (!provider.apiKeyConfigured) {
    return {
      blocked: true,
      status: 'missing_api_key',
      reason: providerStatusPhrase(language, 'missing_api_key_reason'),
    };
  }

    const testReadiness = describeProviderTestReadiness(provider, language, now);
  if (provider.lastTestResult?.ok === true && !testReadiness.ready) {
    return {
      blocked: true,
      status: 'blocked_error',
      reason: unverifiedProviderWarning(language),
    };
  }

  const declaredProtocol = typeof provider.protocol === 'string' ? provider.protocol.trim() : '';
  if (declaredProtocol && !normalizeProviderProtocol(declaredProtocol)) {
    return {
      blocked: true,
      status: 'blocked_error',
      reason: unverifiedProviderWarning(language),
    };
  }

  const availableModels = Array.isArray(provider.availableModels) ? provider.availableModels : [];
  const hasUsableModels = availableModels.length > 0;
  const errorHint = providerErrorHint(provider, language) ?? providerGenericCheckHint(language);

  if (provider.modelListStatus === 'loading' && !hasUsableModels) {
    return {
      blocked: true,
      status: 'warming',
      reason: providerStatusPhrase(language, 'warming_reason'),
    };
  }

  if (provider.modelListStatus === 'error') {
    if (testReadiness.ready) {
      return {
        blocked: false,
        status: 'degraded_error',
        warning: providerStatusPhrase(language, 'model_list_unavailable_warning'),
      };
    }

    const shouldBlock = !hasUsableModels || hardBlockingCategories.has(provider.modelErrorCategory ?? '');
    if (shouldBlock) {
      return {
        blocked: true,
        status: 'blocked_error',
        reason: errorHint,
      };
    }

    return {
      blocked: false,
      status: 'degraded_error',
      warning: providerDegradedWarning(language, errorHint),
    };
  }

  if (provider.modelListStatus === 'loading' && hasUsableModels) {
    return {
      blocked: false,
      status: 'refreshing',
      warning: providerStatusPhrase(language, 'refreshing_warning'),
    };
  }

  const recentTestState = describeRecentProviderTestState(provider, language, now);
  if (recentTestState) {
    return recentTestState;
  }

  if (!provider.lastTestResult) {
    return {
      blocked: true,
      status: 'blocked_error',
      reason: unverifiedProviderWarning(language),
    };
  }

  if (!testReadiness.ready) {
    return {
      blocked: true,
      status: 'blocked_error',
      reason: unverifiedProviderWarning(language),
    };
  }

  return {
    blocked: false,
    status: 'ready',
  };
}

export function describeProviderImageInputState(
  provider: ProviderStatusLike,
  language: ProviderSurfaceLanguage,
  now = Date.now(),
): ProviderImageInputState {
  const sendState = describeProviderSendState(provider, language, now);
  if (sendState.blocked) {
    return {
      supported: false,
      status: 'setup_required',
      reason: sendState.reason,
      detail: sendState.reason,
    };
  }

  if (!providerHasVisionCapability(provider)) {
    return {
      supported: false,
      status: 'missing_vision',
      reason: providerStatusPhrase(language, 'missing_vision_reason'),
      detail: providerStatusPhrase(language, 'missing_vision_detail'),
    };
  }

  if (!providerSupportsImageProtocol(provider)) {
    const copy = unsupportedImageProtocolByLanguage[language] ?? unsupportedImageProtocolByLanguage['en-US'];
    return {
      supported: false,
      status: 'unsupported_protocol',
      reason: copy.reason,
      detail: copy.detail,
    };
  }

  return {
    supported: true,
    status: 'ready',
    detail: providerStatusPhrase(language, 'image_ready_detail'),
  };
}

export type ProviderStatusTone = 'pass' | 'warn' | 'fail';

export interface ProviderStatusVerdict {
  tone: ProviderStatusTone;
  status: string;
  detail: string;
}

export interface ProviderProtocolSummaryInput {
  protocol?: ProviderProtocol | string;
  protocolDiagnostic?: Record<string, unknown>;
}

export interface ProviderProfileSummaryInput {
  profileId?: string;
  profileLabel?: string;
  profileMode?: string;
  profileCount?: number;
  profileHistory?: Array<Record<string, unknown>>;
}

export interface ProviderConnectionSummaryInput {
  providerName?: string;
  profileSummary?: ProviderStatusVerdict;
  protocolSummary?: ProviderStatusVerdict;
  modelTestSummary?: string;
  diagnosticVerdict?: ProviderStatusVerdict;
  configured?: boolean;
  apiKeyConfigured?: boolean;
  apiKeySavedLabel?: string;
  apiKeyMissingLabel?: string;
}

export interface ProviderSetupSummaryInput {
  providerName?: string;
  draftName?: string;
  selectedProtocolLabel?: string;
  credentialModeLabel?: string;
  model?: string;
  providerSaved?: boolean;
  apiKeyConfigured?: boolean;
  apiKeyMissingLabel?: string;
}

export interface ProviderCapabilityCapsuleInput {
  providerName?: string;
  profileSummary?: ProviderStatusVerdict;
  protocolSummary?: ProviderStatusVerdict;
  diagnosticsVerdict?: ProviderStatusVerdict;
  profileCount?: number;
  templateCount?: number;
  taskBindingCount?: number;
  lastTestSummary?: string;
  capabilityState?: string;
}

export interface ProviderTaskBindingMatrixLike {
  alias?: string;
  fallbackAliases?: string[];
  requiredCapabilities?: string[];
}

export interface ProviderCapabilityFlagsLike {
  chat?: boolean;
  responses?: boolean;
  vision?: boolean;
  embeddings?: boolean;
  tools?: boolean;
  jsonSchema?: boolean;
  structuredOutput?: boolean;
  streaming?: boolean;
}

export interface ProviderCapabilityMatrixInput {
  modelAliases?: Record<string, string>;
  taskBindings?: Record<string, ProviderTaskBindingMatrixLike>;
  modelCapabilities?: Record<string, ProviderCapabilityFlagsLike>;
  capabilityFlags?: ProviderCapabilityFlagsLike;
}

export interface ProviderCapabilityMatrixEntry {
  label: string;
  detail: string;
}

export interface ProviderCapabilityMatrixGroups {
  aliases: ProviderCapabilityMatrixEntry[];
  taskBindings: ProviderCapabilityMatrixEntry[];
  modelCapabilities: ProviderCapabilityMatrixEntry[];
  capabilityFlags: string[];
}

export interface ProviderCapabilityMatrixSummary {
  aliasSummary: string;
  taskBindingSummary: string;
  modelCapabilitySummary: string;
  capabilitySummary: string;
}

type ProviderCapabilityLabel = keyof ProviderCapabilityFlagsLike;

interface ProviderSummaryCopy {
  connectionChecked: string;
  connectionNeedsAttention: string;
  taskNeedsAttention: string;
  modelNeedsAttention: string;
  modelTestNeedsAttention: string;
  modelListNeedsAttention: string;
  ready: string;
  modelListReady: string;
  modelListUpdating: string;
  modelListIdle: string;
  modelTestPassed: string;
  unnamedConnection: string;
  connectionMode: string;
  savedConnections: string;
  changeHistory: string;
  latestChange: string;
  unknown: string;
  directConnection: string;
  gatewayConnection: string;
  openAiConnection: string;
  anthropicConnection: string;
  geminiConnection: string;
  connectionType: string;
  capabilities: string;
  noCapabilities: string;
  taskUses: string;
  taskNeeds: string;
  taskFallback: string;
  otherTask: string;
  otherCapability: string;
  task: string;
  tasks: string;
  model: string;
  models: string;
  protocolLabels: Record<ProviderProtocol, string>;
  capabilityLabels: Record<ProviderCapabilityLabel, string>;
  taskLabels: Record<string, string>;
}

const providerSummaryCopyByLanguage: Record<ProviderSurfaceLanguage, ProviderSummaryCopy> = {
  'zh-CN': {
    connectionChecked: '连接已检查',
    connectionNeedsAttention: '连接需要处理',
    taskNeedsAttention: '任务设置需要处理',
    modelNeedsAttention: '模型需要处理',
    modelTestNeedsAttention: '模型测试未通过',
    modelListNeedsAttention: '模型列表暂不可用',
    ready: '已就绪',
    modelListReady: '模型已就绪',
    modelListUpdating: '正在更新模型',
    modelListIdle: '尚未检查模型',
    modelTestPassed: '模型测试通过',
    unnamedConnection: '未命名连接',
    connectionMode: '连接方式',
    savedConnections: '已保存连接',
    changeHistory: '切换记录',
    latestChange: '最近切换',
    unknown: '未知',
    directConnection: '直连',
    gatewayConnection: '通过网关',
    openAiConnection: 'OpenAI 兼容连接',
    anthropicConnection: 'Anthropic 兼容连接',
    geminiConnection: 'Gemini 连接',
    connectionType: '模型连接',
    capabilities: '可用功能',
    noCapabilities: '没有可用功能',
    taskUses: '使用',
    taskNeeds: '需要',
    taskFallback: '备用',
    otherTask: '其他任务',
    otherCapability: '其他功能',
    task: '任务',
    tasks: '任务',
    model: '模型',
    models: '模型',
    protocolLabels: {
      openai_responses: 'OpenAI 响应接口',
      openai_chat_completions: 'OpenAI 聊天接口',
      openai_chat_completions_compatible: 'OpenAI 兼容聊天接口',
      anthropic_messages: 'Anthropic 消息接口',
      gemini_generate_content: 'Gemini 内容生成接口',
    },
    capabilityLabels: {
      chat: '对话',
      responses: '响应接口',
      streaming: '实时输出',
      tools: '工具调用',
      jsonSchema: 'JSON 格式',
      vision: '图片理解',
      embeddings: '语义检索',
      structuredOutput: '结构化回复',
    },
    taskLabels: {
      coach_reply: '教练回复',
      coach_critique: '教练点评',
      resource_rerank: '资料排序',
      plan_summary: '计划摘要',
      resource_embedding: '资料检索',
    },
  },
  'en-US': {
    connectionChecked: 'Protocol checked',
    connectionNeedsAttention: 'Protocol blocked',
    taskNeedsAttention: 'Task binding blocked',
    modelNeedsAttention: 'Model blocked',
    modelTestNeedsAttention: 'Model test blocked',
    modelListNeedsAttention: 'Model list blocked',
    ready: 'Passed',
    modelListReady: 'Model list ready',
    modelListUpdating: 'Model list refreshing',
    modelListIdle: 'Model list idle',
    modelTestPassed: 'Model test passed',
    unnamedConnection: 'Profile',
    connectionMode: 'Mode',
    savedConnections: 'Profiles',
    changeHistory: 'History',
    latestChange: 'Latest switch',
    unknown: 'unknown',
    directConnection: 'direct',
    gatewayConnection: 'gateway',
    openAiConnection: 'OpenAI connection',
    anthropicConnection: 'Anthropic connection',
    geminiConnection: 'Gemini connection',
    connectionType: 'Connection',
    capabilities: 'Capabilities',
    noCapabilities: 'Capabilities: none',
    taskUses: 'alias',
    taskNeeds: 'required',
    taskFallback: 'fallback',
    otherTask: 'task',
    otherCapability: 'other capability',
    task: 'task binding',
    tasks: 'task binding',
    model: 'model diagnostic',
    models: 'model diagnostic',
    protocolLabels: {
      openai_responses: 'OpenAI Responses',
      openai_chat_completions: 'OpenAI Chat Completions',
      openai_chat_completions_compatible: 'OpenAI-compatible chat completions',
      anthropic_messages: 'Anthropic Messages',
      gemini_generate_content: 'Gemini GenerateContent',
    },
    capabilityLabels: {
      chat: 'chat',
      responses: 'responses',
      streaming: 'streaming',
      tools: 'tools',
      jsonSchema: 'json schema',
      vision: 'vision',
      embeddings: 'embeddings',
      structuredOutput: 'structured output',
    },
    taskLabels: {
      coach_reply: 'coach_reply',
      coach_critique: 'coach_critique',
      resource_rerank: 'resource_rerank',
      plan_summary: 'plan_summary',
      resource_embedding: 'resource_embedding',
    },
  },
  'es-ES': {
    connectionChecked: 'Conexión comprobada',
    connectionNeedsAttention: 'La conexión necesita atención',
    taskNeedsAttention: 'La configuración de una tarea necesita atención',
    modelNeedsAttention: 'Un modelo necesita atención',
    modelTestNeedsAttention: 'La prueba del modelo falló',
    modelListNeedsAttention: 'La lista de modelos no está disponible',
    ready: 'Listo',
    modelListReady: 'Modelos listos',
    modelListUpdating: 'Actualizando modelos',
    modelListIdle: 'Modelos sin comprobar',
    modelTestPassed: 'Prueba del modelo superada',
    unnamedConnection: 'Conexión sin nombre',
    connectionMode: 'Modo de conexión',
    savedConnections: 'Conexiones guardadas',
    changeHistory: 'Cambios',
    latestChange: 'Último cambio',
    unknown: 'desconocido',
    directConnection: 'Conexión directa',
    gatewayConnection: 'Mediante gateway',
    openAiConnection: 'Conexión compatible con OpenAI',
    anthropicConnection: 'Conexión compatible con Anthropic',
    geminiConnection: 'Conexión con Gemini',
    connectionType: 'Conexión del modelo',
    capabilities: 'Funciones disponibles',
    noCapabilities: 'No hay funciones disponibles',
    taskUses: 'usa',
    taskNeeds: 'necesita',
    taskFallback: 'alternativa',
    otherTask: 'otra tarea',
    otherCapability: 'otra función',
    task: 'tarea',
    tasks: 'tareas',
    model: 'modelo',
    models: 'modelos',
    protocolLabels: {
      openai_responses: 'Respuestas de OpenAI',
      openai_chat_completions: 'Chat Completions de OpenAI',
      openai_chat_completions_compatible: 'Chat compatible con OpenAI',
      anthropic_messages: 'Mensajes de Anthropic',
      gemini_generate_content: 'Generación de contenido de Gemini',
    },
    capabilityLabels: {
      chat: 'chat',
      responses: 'respuestas',
      streaming: 'respuesta en directo',
      tools: 'herramientas',
      jsonSchema: 'formato JSON',
      vision: 'imágenes',
      embeddings: 'búsqueda semántica',
      structuredOutput: 'respuesta estructurada',
    },
    taskLabels: {
      coach_reply: 'respuesta del coach',
      coach_critique: 'comentario del coach',
      resource_rerank: 'orden de recursos',
      plan_summary: 'resumen del plan',
      resource_embedding: 'búsqueda de recursos',
    },
  },
  'fr-FR': {
    connectionChecked: 'Connexion vérifiée',
    connectionNeedsAttention: 'La connexion demande votre attention',
    taskNeedsAttention: 'La configuration d’une tâche demande votre attention',
    modelNeedsAttention: 'Un modèle demande votre attention',
    modelTestNeedsAttention: 'Le test du modèle a échoué',
    modelListNeedsAttention: 'La liste des modèles est indisponible',
    ready: 'Prêt',
    modelListReady: 'Modèles prêts',
    modelListUpdating: 'Mise à jour des modèles',
    modelListIdle: 'Modèles non vérifiés',
    modelTestPassed: 'Test du modèle réussi',
    unnamedConnection: 'Connexion sans nom',
    connectionMode: 'Mode de connexion',
    savedConnections: 'Connexions enregistrées',
    changeHistory: 'Changements',
    latestChange: 'Dernier changement',
    unknown: 'inconnu',
    directConnection: 'Connexion directe',
    gatewayConnection: 'Via une passerelle',
    openAiConnection: 'Connexion compatible OpenAI',
    anthropicConnection: 'Connexion compatible Anthropic',
    geminiConnection: 'Connexion Gemini',
    connectionType: 'Connexion du modèle',
    capabilities: 'Fonctions disponibles',
    noCapabilities: 'Aucune fonction disponible',
    taskUses: 'utilise',
    taskNeeds: 'requiert',
    taskFallback: 'secours',
    otherTask: 'autre tâche',
    otherCapability: 'autre fonction',
    task: 'tâche',
    tasks: 'tâches',
    model: 'modèle',
    models: 'modèles',
    protocolLabels: {
      openai_responses: 'Réponses OpenAI',
      openai_chat_completions: 'Chat Completions OpenAI',
      openai_chat_completions_compatible: 'Chat compatible OpenAI',
      anthropic_messages: 'Messages Anthropic',
      gemini_generate_content: 'Génération de contenu Gemini',
    },
    capabilityLabels: {
      chat: 'conversation',
      responses: 'réponses',
      streaming: 'réponse en direct',
      tools: 'outils',
      jsonSchema: 'format JSON',
      vision: 'images',
      embeddings: 'recherche sémantique',
      structuredOutput: 'réponse structurée',
    },
    taskLabels: {
      coach_reply: 'réponse du coach',
      coach_critique: 'retour du coach',
      resource_rerank: 'tri des ressources',
      plan_summary: 'résumé du plan',
      resource_embedding: 'recherche de ressources',
    },
  },
  'de-DE': {
    connectionChecked: 'Verbindung geprüft',
    connectionNeedsAttention: 'Die Verbindung braucht Aufmerksamkeit',
    taskNeedsAttention: 'Eine Aufgabeneinstellung braucht Aufmerksamkeit',
    modelNeedsAttention: 'Ein Modell braucht Aufmerksamkeit',
    modelTestNeedsAttention: 'Der Modelltest ist fehlgeschlagen',
    modelListNeedsAttention: 'Die Modellliste ist nicht verfügbar',
    ready: 'Bereit',
    modelListReady: 'Modelle bereit',
    modelListUpdating: 'Modelle werden aktualisiert',
    modelListIdle: 'Modelle noch nicht geprüft',
    modelTestPassed: 'Modelltest bestanden',
    unnamedConnection: 'Unbenannte Verbindung',
    connectionMode: 'Verbindungsart',
    savedConnections: 'Gespeicherte Verbindungen',
    changeHistory: 'Änderungen',
    latestChange: 'Letzter Wechsel',
    unknown: 'unbekannt',
    directConnection: 'Direkte Verbindung',
    gatewayConnection: 'Über ein Gateway',
    openAiConnection: 'OpenAI-kompatible Verbindung',
    anthropicConnection: 'Anthropic-kompatible Verbindung',
    geminiConnection: 'Gemini-Verbindung',
    connectionType: 'Modellverbindung',
    capabilities: 'Verfügbare Funktionen',
    noCapabilities: 'Keine Funktionen verfügbar',
    taskUses: 'verwendet',
    taskNeeds: 'benötigt',
    taskFallback: 'Alternative',
    otherTask: 'andere Aufgabe',
    otherCapability: 'andere Funktion',
    task: 'Aufgabe',
    tasks: 'Aufgaben',
    model: 'Modell',
    models: 'Modelle',
    protocolLabels: {
      openai_responses: 'OpenAI-Antworten',
      openai_chat_completions: 'OpenAI-Chat Completions',
      openai_chat_completions_compatible: 'OpenAI-kompatibler Chat',
      anthropic_messages: 'Anthropic-Nachrichten',
      gemini_generate_content: 'Gemini-Inhaltserstellung',
    },
    capabilityLabels: {
      chat: 'Chat',
      responses: 'Antworten',
      streaming: 'Live-Antwort',
      tools: 'Werkzeuge',
      jsonSchema: 'JSON-Format',
      vision: 'Bilder',
      embeddings: 'semantische Suche',
      structuredOutput: 'strukturierte Antwort',
    },
    taskLabels: {
      coach_reply: 'Coach-Antwort',
      coach_critique: 'Coach-Feedback',
      resource_rerank: 'Ressourcenreihenfolge',
      plan_summary: 'Planzusammenfassung',
      resource_embedding: 'Ressourcensuche',
    },
  },
  'ja-JP': {
    connectionChecked: '接続を確認済み',
    connectionNeedsAttention: '接続の確認が必要',
    taskNeedsAttention: 'タスク設定の確認が必要',
    modelNeedsAttention: 'モデルの確認が必要',
    modelTestNeedsAttention: 'モデルのテストに失敗',
    modelListNeedsAttention: 'モデル一覧を取得できません',
    ready: '準備完了',
    modelListReady: 'モデルの準備完了',
    modelListUpdating: 'モデルを更新中',
    modelListIdle: 'モデル未確認',
    modelTestPassed: 'モデルのテストに合格',
    unnamedConnection: '名称未設定の接続',
    connectionMode: '接続方法',
    savedConnections: '保存済みの接続',
    changeHistory: '変更履歴',
    latestChange: '最近の切替',
    unknown: '不明',
    directConnection: '直接接続',
    gatewayConnection: 'ゲートウェイ経由',
    openAiConnection: 'OpenAI 互換接続',
    anthropicConnection: 'Anthropic 互換接続',
    geminiConnection: 'Gemini 接続',
    connectionType: 'モデル接続',
    capabilities: '利用できる機能',
    noCapabilities: '利用できる機能はありません',
    taskUses: '使用',
    taskNeeds: '必要',
    taskFallback: '代替',
    otherTask: 'その他のタスク',
    otherCapability: 'その他の機能',
    task: 'タスク',
    tasks: 'タスク',
    model: 'モデル',
    models: 'モデル',
    protocolLabels: {
      openai_responses: 'OpenAI 応答API',
      openai_chat_completions: 'OpenAI チャットAPI',
      openai_chat_completions_compatible: 'OpenAI 互換チャットAPI',
      anthropic_messages: 'Anthropic メッセージAPI',
      gemini_generate_content: 'Gemini コンテンツ生成API',
    },
    capabilityLabels: {
      chat: '会話',
      responses: '応答API',
      streaming: 'ストリーミング',
      tools: 'ツール',
      jsonSchema: 'JSON 形式',
      vision: '画像',
      embeddings: '意味検索',
      structuredOutput: '構造化出力',
    },
    taskLabels: {
      coach_reply: 'コーチの回答',
      coach_critique: 'コーチのフィードバック',
      resource_rerank: '資料の並び替え',
      plan_summary: '計画の要約',
      resource_embedding: '資料の検索',
    },
  },
  'ko-KR': {
    connectionChecked: '연결 확인됨',
    connectionNeedsAttention: '연결을 확인해야 합니다',
    taskNeedsAttention: '작업 설정을 확인해야 합니다',
    modelNeedsAttention: '모델을 확인해야 합니다',
    modelTestNeedsAttention: '모델 테스트에 실패했습니다',
    modelListNeedsAttention: '모델 목록을 사용할 수 없습니다',
    ready: '준비됨',
    modelListReady: '모델 준비됨',
    modelListUpdating: '모델 업데이트 중',
    modelListIdle: '모델 미확인',
    modelTestPassed: '모델 테스트 통과',
    unnamedConnection: '이름 없는 연결',
    connectionMode: '연결 방식',
    savedConnections: '저장된 연결',
    changeHistory: '변경 기록',
    latestChange: '최근 전환',
    unknown: '알 수 없음',
    directConnection: '직접 연결',
    gatewayConnection: '게이트웨이 경유',
    openAiConnection: 'OpenAI 호환 연결',
    anthropicConnection: 'Anthropic 호환 연결',
    geminiConnection: 'Gemini 연결',
    connectionType: '모델 연결',
    capabilities: '사용 가능한 기능',
    noCapabilities: '사용 가능한 기능이 없습니다',
    taskUses: '사용',
    taskNeeds: '필요',
    taskFallback: '대체',
    otherTask: '기타 작업',
    otherCapability: '기타 기능',
    task: '작업',
    tasks: '작업',
    model: '모델',
    models: '모델',
    protocolLabels: {
      openai_responses: 'OpenAI 응답 API',
      openai_chat_completions: 'OpenAI 채팅 API',
      openai_chat_completions_compatible: 'OpenAI 호환 채팅 API',
      anthropic_messages: 'Anthropic 메시지 API',
      gemini_generate_content: 'Gemini 콘텐츠 생성 API',
    },
    capabilityLabels: {
      chat: '대화',
      responses: '응답 API',
      streaming: '실시간 응답',
      tools: '도구',
      jsonSchema: 'JSON 형식',
      vision: '이미지',
      embeddings: '의미 검색',
      structuredOutput: '구조화된 응답',
    },
    taskLabels: {
      coach_reply: '코치 답변',
      coach_critique: '코치 피드백',
      resource_rerank: '자료 정렬',
      plan_summary: '계획 요약',
      resource_embedding: '자료 검색',
    },
  },
  'pt-BR': {
    connectionChecked: 'Conexão verificada',
    connectionNeedsAttention: 'A conexão precisa de atenção',
    taskNeedsAttention: 'A configuração de uma tarefa precisa de atenção',
    modelNeedsAttention: 'Um modelo precisa de atenção',
    modelTestNeedsAttention: 'O teste do modelo falhou',
    modelListNeedsAttention: 'A lista de modelos não está disponível',
    ready: 'Pronto',
    modelListReady: 'Modelos prontos',
    modelListUpdating: 'Atualizando modelos',
    modelListIdle: 'Modelos ainda não verificados',
    modelTestPassed: 'Teste do modelo aprovado',
    unnamedConnection: 'Conexão sem nome',
    connectionMode: 'Modo de conexão',
    savedConnections: 'Conexões salvas',
    changeHistory: 'Alterações',
    latestChange: 'Última troca',
    unknown: 'desconhecido',
    directConnection: 'Conexão direta',
    gatewayConnection: 'Por gateway',
    openAiConnection: 'Conexão compatível com OpenAI',
    anthropicConnection: 'Conexão compatível com Anthropic',
    geminiConnection: 'Conexão com Gemini',
    connectionType: 'Conexão do modelo',
    capabilities: 'Recursos disponíveis',
    noCapabilities: 'Nenhum recurso disponível',
    taskUses: 'usa',
    taskNeeds: 'precisa',
    taskFallback: 'alternativa',
    otherTask: 'outra tarefa',
    otherCapability: 'outro recurso',
    task: 'tarefa',
    tasks: 'tarefas',
    model: 'modelo',
    models: 'modelos',
    protocolLabels: {
      openai_responses: 'Respostas OpenAI',
      openai_chat_completions: 'Chat Completions OpenAI',
      openai_chat_completions_compatible: 'Chat compatível com OpenAI',
      anthropic_messages: 'Mensagens Anthropic',
      gemini_generate_content: 'Geração de conteúdo Gemini',
    },
    capabilityLabels: {
      chat: 'chat',
      responses: 'respostas',
      streaming: 'resposta ao vivo',
      tools: 'ferramentas',
      jsonSchema: 'formato JSON',
      vision: 'imagens',
      embeddings: 'busca semântica',
      structuredOutput: 'resposta estruturada',
    },
    taskLabels: {
      coach_reply: 'resposta do coach',
      coach_critique: 'feedback do coach',
      resource_rerank: 'ordem dos recursos',
      plan_summary: 'resumo do plano',
      resource_embedding: 'busca de recursos',
    },
  },
};

function providerSummaryCopy(language: ProviderSurfaceLanguage): ProviderSummaryCopy {
  return providerSummaryCopyByLanguage[language] ?? providerSummaryCopyByLanguage['en-US'];
}

const capabilityFlagOrder: ProviderCapabilityLabel[] = [
  'chat',
  'responses',
  'streaming',
  'tools',
  'jsonSchema',
  'vision',
  'embeddings',
  'structuredOutput',
];

const capabilityKeyByName: Record<string, ProviderCapabilityLabel> = {
  chat: 'chat',
  responses: 'responses',
  streaming: 'streaming',
  tools: 'tools',
  jsonSchema: 'jsonSchema',
  json_schema: 'jsonSchema',
  'json schema': 'jsonSchema',
  vision: 'vision',
  embeddings: 'embeddings',
  structuredOutput: 'structuredOutput',
  structured_output: 'structuredOutput',
  'structured output': 'structuredOutput',
};

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : undefined;
}

function asText(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}

function asTextArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((item) => asText(item)).filter((item): item is string => Boolean(item));
}

function joinSummaryParts(parts: Array<string | undefined | null>): string {
  return parts.filter((part): part is string => Boolean(part && part.trim())).join(' | ');
}

function activeCapabilityLabels(
  flags: ProviderCapabilityFlagsLike | undefined,
  language: ProviderSurfaceLanguage,
): string[] {
  const copy = providerSummaryCopy(language);
  const labels: string[] = [];
  for (const key of capabilityFlagOrder) {
    if (flags?.[key] === true) {
      labels.push(copy.capabilityLabels[key]);
    }
  }
  return labels;
}

function localizeCapabilityName(value: string, language: ProviderSurfaceLanguage): string {
  if (language === 'en-US') {
    return value;
  }
  const key = capabilityKeyByName[value];
  return key ? providerSummaryCopy(language).capabilityLabels[key] : providerSummaryCopy(language).otherCapability;
}

function formatCapabilitySummary(
  flags: ProviderCapabilityFlagsLike | undefined,
  language: ProviderSurfaceLanguage,
): string {
  const copy = providerSummaryCopy(language);
  const labels = activeCapabilityLabels(flags, language);
  return labels.length > 0 ? copy.capabilities + ': ' + labels.join(' | ') : copy.noCapabilities;
}

function localizeTaskBindingLabel(label: string, language: ProviderSurfaceLanguage): string {
  if (language === 'en-US') {
    return label;
  }
  const translated = providerSummaryCopy(language).taskLabels[label];
  if (translated) {
    return translated;
  }
  return label.includes('_') ? providerSummaryCopy(language).otherTask : label;
}

function formatTaskBindingSummary(
  binding: ProviderTaskBindingMatrixLike | undefined,
  language: ProviderSurfaceLanguage,
): string {
  const copy = providerSummaryCopy(language);
  const parts: string[] = [];
  const alias = asText(binding?.alias);
  if (alias) {
    parts.push(copy.taskUses + ' ' + alias);
  }
  const requiredCapabilities = asTextArray(binding?.requiredCapabilities);
  if (requiredCapabilities.length > 0) {
    parts.push(
      copy.taskNeeds +
        ' ' +
        requiredCapabilities.map((capability) => localizeCapabilityName(capability, language)).join('+'),
    );
  }
  const fallbackAliases = asTextArray(binding?.fallbackAliases);
  if (fallbackAliases.length > 0) {
    parts.push(copy.taskFallback + ' ' + fallbackAliases.join('+'));
  }
  return parts.join(' | ');
}

function pickLatestProfileHistoryEntry(
  history: Array<Record<string, unknown>>,
): Record<string, unknown> | undefined {
  if (history.length === 0) {
    return undefined;
  }

  return [...history].sort(compareProfileHistoryEntries).at(-1);
}

function compareProfileHistoryEntries(
  left: Record<string, unknown>,
  right: Record<string, unknown>,
): number {
  const leftTimestamp = asText(left.timestamp ?? left.updatedAt ?? left.createdAt) ?? '';
  const rightTimestamp = asText(right.timestamp ?? right.updatedAt ?? right.createdAt) ?? '';
  if (leftTimestamp !== rightTimestamp) {
    return leftTimestamp.localeCompare(rightTimestamp);
  }
  const leftId = asText(left.entryId ?? left.entry_id) ?? '';
  const rightId = asText(right.entryId ?? right.entry_id) ?? '';
  return leftId.localeCompare(rightId);
}

function formatProfileSwitch(
  entry: Record<string, unknown> | undefined,
  language: ProviderSurfaceLanguage,
): string | undefined {
  if (!entry) {
    return undefined;
  }
  const fromProfile =
    asText(entry.fromProfileLabel) ??
    asText(entry.fromProfileId) ??
    asText(entry.from_profile_label) ??
    asText(entry.from_profile_id);
  const toProfile =
    asText(entry.toProfileLabel) ??
    asText(entry.toProfileId) ??
    asText(entry.to_profile_label) ??
    asText(entry.to_profile_id);
  if (!fromProfile && !toProfile) {
    return undefined;
  }
  const unknown = providerSummaryCopy(language).unknown;
  return (fromProfile ?? unknown) + ' -> ' + (toProfile ?? unknown);
}

function formatProviderStatusCount(
  kind: 'task' | 'model',
  count: number,
  blockedCount: number | undefined,
  language: ProviderSurfaceLanguage,
): string {
  const copy = providerSummaryCopy(language);
  const blocked = blockedCount && blockedCount > 0 ? blockedCount : 0;
  if (language === 'en-US') {
    const label = kind === 'task' ? copy.tasks : copy.models;
    const suffix = count === 1 ? '' : 's';
    const blockedSuffix = blocked > 0 ? ' (' + blocked + ' blocked)' : '';
    return String(count) + ' ' + label + suffix + blockedSuffix;
  }

  const label =
    kind === 'task'
      ? count === 1
        ? copy.task
        : copy.tasks
      : count === 1
        ? copy.model
        : copy.models;
  switch (language) {
    case 'zh-CN':
      return String(count) + ' 项' + label + (blocked > 0 ? '（' + blocked + ' 项需要处理）' : '');
    case 'ja-JP':
      return String(count) + '件の' + label + (blocked > 0 ? '（' + blocked + '件を確認）' : '');
    case 'ko-KR':
      return label + ' ' + count + '개' + (blocked > 0 ? ' (' + blocked + '개 확인 필요)' : '');
    case 'es-ES':
      return String(count) + ' ' + label + (blocked > 0 ? ' (' + blocked + ' con problemas)' : '');
    case 'fr-FR':
      return String(count) + ' ' + label + (blocked > 0 ? ' (' + blocked + ' à vérifier)' : '');
    case 'de-DE':
      return String(count) + ' ' + label + (blocked > 0 ? ' (' + blocked + ' mit Hinweis)' : '');
    case 'pt-BR':
      return String(count) + ' ' + label + (blocked > 0 ? ' (' + blocked + ' com problema)' : '');
  }
}

function providerProtocolSurfaceLabel(
  protocol: ProviderProtocol | undefined,
  language: ProviderSurfaceLanguage,
): string {
  if (!protocol) {
    return language === 'en-US' ? 'Protocol unverified' : providerSummaryCopy(language).connectionType;
  }
  return language === 'en-US'
    ? providerProtocolCompletionLabel(protocol)
    : providerSummaryCopy(language).protocolLabels[protocol];
}

function providerProtocolFamilySummary(
  family: string,
  language: ProviderSurfaceLanguage,
): string {
  if (language === 'en-US') {
    return family + ' family';
  }
  const copy = providerSummaryCopy(language);
  switch (family.trim().toLowerCase()) {
    case 'openai':
      return copy.openAiConnection;
    case 'anthropic':
      return copy.anthropicConnection;
    case 'gemini':
      return copy.geminiConnection;
    default:
      return copy.connectionType;
  }
}

function providerTransportSummary(
  transport: string | undefined,
  language: ProviderSurfaceLanguage,
): string | undefined {
  if (!transport) {
    return undefined;
  }
  if (language === 'en-US') {
    return transport;
  }
  const normalized = transport.trim().toLowerCase();
  if (normalized === 'direct') {
    return providerSummaryCopy(language).directConnection;
  }
  if (normalized.includes('proxy') || normalized.includes('gateway')) {
    return providerSummaryCopy(language).gatewayConnection;
  }
  return undefined;
}

function providerProfileModeSummary(
  mode: string | undefined,
  language: ProviderSurfaceLanguage,
): string | undefined {
  if (!mode) {
    return undefined;
  }
  if (language === 'en-US') {
    return mode;
  }
  return providerTransportSummary(mode, language);
}

export function describeProviderDiagnosticVerdict(
  input: {
    protocolDiagnostic?: Record<string, unknown>;
    taskBindingDiagnostics?: Array<Record<string, unknown>>;
    modelDiagnostics?: Array<Record<string, unknown>>;
    modelTest?: Record<string, unknown>;
    modelListStatus?: string;
  },
  language: ProviderSurfaceLanguage,
): ProviderStatusVerdict {
  const copy = providerSummaryCopy(language);
  const protocolSupported = input.protocolDiagnostic?.supported !== false;
  const taskBindingDiagnostics = Array.isArray(input.taskBindingDiagnostics)
    ? input.taskBindingDiagnostics
    : [];
  const modelDiagnostics = Array.isArray(input.modelDiagnostics) ? input.modelDiagnostics : [];
  const blockedTaskBindings = taskBindingDiagnostics.filter((item) => item.supported === false).length;
  const blockedModels = modelDiagnostics.filter((item) => item.supported === false).length;
  const modelListStatus = asText(input.modelListStatus) ?? 'idle';
  const detailParts = [
    protocolSupported ? copy.connectionChecked : copy.connectionNeedsAttention,
    formatProviderStatusCount('task', taskBindingDiagnostics.length, blockedTaskBindings, language),
    formatProviderStatusCount('model', modelDiagnostics.length, blockedModels, language),
    modelListStatus === 'ready'
      ? copy.modelListReady
      : modelListStatus === 'loading'
        ? copy.modelListUpdating
        : modelListStatus === 'error'
          ? copy.modelListNeedsAttention
          : copy.modelListIdle,
  ];

  const modelTestDetail = asText(input.modelTest?.detail);
  if (language === 'en-US' && modelTestDetail) {
    detailParts.push(modelTestDetail);
  } else if (input.modelTest?.ok === true) {
    detailParts.push(copy.modelTestPassed);
  }

  if (!protocolSupported) {
    return { tone: 'fail', status: copy.connectionNeedsAttention, detail: joinSummaryParts(detailParts) };
  }
  if (blockedTaskBindings > 0) {
    return { tone: 'fail', status: copy.taskNeedsAttention, detail: joinSummaryParts(detailParts) };
  }
  if (blockedModels > 0) {
    return { tone: 'fail', status: copy.modelNeedsAttention, detail: joinSummaryParts(detailParts) };
  }
  if (input.modelTest && input.modelTest.ok === false) {
    return { tone: 'fail', status: copy.modelTestNeedsAttention, detail: joinSummaryParts(detailParts) };
  }
  if (modelListStatus === 'error') {
    return { tone: 'warn', status: copy.modelListNeedsAttention, detail: joinSummaryParts(detailParts) };
  }

  return { tone: 'pass', status: copy.ready, detail: joinSummaryParts(detailParts) };
}

export function describeProviderProtocolSummary(
  input: ProviderProtocolSummaryInput,
  language: ProviderSurfaceLanguage,
): ProviderStatusVerdict {
  const protocol = normalizeProviderProtocol(asText(input.protocolDiagnostic?.protocol) ?? input.protocol);
  const protocolName = providerProtocolSurfaceLabel(protocol, language);
  const protocolFamily = asText(input.protocolDiagnostic?.protocolFamily) ?? providerProtocolFamily(protocol) ?? '';
  const transport = asText(input.protocolDiagnostic?.transport);
  const endpointHint = asText(input.protocolDiagnostic?.endpointHint) ?? providerProtocolEndpointHint(protocol);
  const notes = asTextArray(input.protocolDiagnostic?.notes);

  return {
    tone: !protocol || input.protocolDiagnostic?.supported === false ? 'fail' : 'pass',
    status: protocolName,
    detail:
      language === 'en-US'
        ? joinSummaryParts([protocolFamily + ' family', transport, endpointHint, ...notes])
        : joinSummaryParts([
            providerProtocolFamilySummary(protocolFamily, language),
            providerTransportSummary(transport, language),
          ]),
  };
}

export function describeProviderProfileSummary(
  input: ProviderProfileSummaryInput,
  language: ProviderSurfaceLanguage,
): ProviderStatusVerdict {
  const copy = providerSummaryCopy(language);
  const profileId = asText(input.profileId);
  const suppliedProfileLabel = asText(input.profileLabel);
  const profileLabel = suppliedProfileLabel ?? profileId ?? copy.unnamedConnection;
  const profileMode = asText(input.profileMode);
  const profileCount = typeof input.profileCount === 'number' && Number.isFinite(input.profileCount)
    ? Math.max(0, Math.trunc(input.profileCount))
    : 0;
  const history = Array.isArray(input.profileHistory)
    ? input.profileHistory.filter((item): item is Record<string, unknown> => Boolean(item))
    : [];
  const latestSwitch = formatProfileSwitch(pickLatestProfileHistoryEntry(history), language);
  const localizedProfileMode = providerProfileModeSummary(profileMode, language);

  return {
    tone: profileId || suppliedProfileLabel ? 'pass' : 'warn',
    status: profileLabel,
    detail:
      language === 'en-US'
        ? joinSummaryParts([
            'Profile ID: ' + (profileId ?? copy.unknown),
            'Mode: ' + (profileMode ?? copy.unknown),
            'Profiles: ' + profileCount,
            'History: ' + history.length,
            latestSwitch ? 'Latest switch: ' + latestSwitch : undefined,
          ])
        : joinSummaryParts([
            localizedProfileMode ? copy.connectionMode + ': ' + localizedProfileMode : undefined,
            copy.savedConnections + ': ' + profileCount,
            copy.changeHistory + ': ' + history.length,
            latestSwitch ? copy.latestChange + ': ' + latestSwitch : undefined,
          ]),
  };
}

export function describeProviderConnectionSummary(
  input: ProviderConnectionSummaryInput,
  notConfiguredLabel: string,
): string {
  return joinSummaryParts([
    asText(input.providerName) ?? notConfiguredLabel,
    input.configured === false ? notConfiguredLabel : undefined,
    input.profileSummary?.status ? 'Profile: ' + input.profileSummary.status : undefined,
    input.protocolSummary?.status ? 'Protocol: ' + input.protocolSummary.status : undefined,
    input.modelTestSummary,
    input.diagnosticVerdict?.status ? 'Verdict: ' + input.diagnosticVerdict.status : undefined,
    input.apiKeyConfigured === false
      ? input.apiKeyMissingLabel ?? 'Missing'
      : input.apiKeySavedLabel ?? 'Saved',
  ]);
}

export function describeProviderSetupSummary(
  input: ProviderSetupSummaryInput,
  notConfiguredLabel: string,
): string {
  return joinSummaryParts([
    asText(input.providerName) ?? notConfiguredLabel,
    input.draftName ? 'Draft: ' + input.draftName : undefined,
    input.selectedProtocolLabel ? 'Protocol: ' + input.selectedProtocolLabel : undefined,
    input.credentialModeLabel ? 'Mode: ' + input.credentialModeLabel : undefined,
    input.model ? 'Model: ' + input.model : undefined,
    input.providerSaved ? 'Saved' : notConfiguredLabel,
    input.apiKeyConfigured ? 'API key ready' : input.apiKeyMissingLabel ?? 'Missing',
  ]);
}

export function describeProviderCapabilityCapsule(
  input: ProviderCapabilityCapsuleInput,
  notConfiguredLabel: string,
): string {
  return joinSummaryParts([
    asText(input.providerName) ?? notConfiguredLabel,
    input.profileSummary?.status,
    input.protocolSummary?.status,
    input.diagnosticsVerdict?.status,
    typeof input.profileCount === 'number' ? 'Profiles: ' + input.profileCount : undefined,
    typeof input.templateCount === 'number' ? 'Templates: ' + input.templateCount : undefined,
    typeof input.taskBindingCount === 'number' ? 'Task bindings: ' + input.taskBindingCount : undefined,
    input.lastTestSummary,
    input.capabilityState,
  ]);
}

export function describeProviderCapabilityMatrixGroups(
  input: ProviderCapabilityMatrixInput,
  language: ProviderSurfaceLanguage,
): ProviderCapabilityMatrixGroups {
  const aliases = Object.entries(input.modelAliases ?? {}).map(([label, detail]) => ({ label, detail }));
  const taskBindings = Object.entries(input.taskBindings ?? {}).map(([label, binding]) => ({
    label: localizeTaskBindingLabel(label, language),
    detail: formatTaskBindingSummary(binding, language),
  }));
  const modelCapabilities = Object.entries(input.modelCapabilities ?? {}).map(([label, detail]) => ({
    label,
    detail: formatCapabilitySummary(detail, language),
  }));

  return {
    aliases,
    taskBindings,
    modelCapabilities,
    capabilityFlags: activeCapabilityLabels(input.capabilityFlags, language),
  };
}

export function describeProviderCapabilityMatrix(
  input: ProviderCapabilityMatrixInput,
  language: ProviderSurfaceLanguage,
): ProviderCapabilityMatrixSummary {
  const groups = describeProviderCapabilityMatrixGroups(input, language);
  const copy = providerSummaryCopy(language);

  return {
    aliasSummary: joinSummaryParts(groups.aliases.map((entry) => entry.label + '->' + entry.detail)),
    taskBindingSummary: joinSummaryParts(
      groups.taskBindings.map((entry) => entry.label + '->' + entry.detail),
    ),
    modelCapabilitySummary: joinSummaryParts(
      groups.modelCapabilities.map((entry) => entry.label + '[' + entry.detail + ']'),
    ),
    capabilitySummary:
      groups.capabilityFlags.length > 0
        ? copy.capabilities + ': ' + groups.capabilityFlags.join(' | ')
        : copy.noCapabilities,
  };
}
