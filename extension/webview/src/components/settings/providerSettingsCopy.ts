/**
 * Provider settings copy helpers (extracted from CoachSettingsView.tsx,
 * batch 7). Pure locale tables — no component state.
 */

import type { ComposerLanguage } from "../../../../../shared/src/types";

function providerConnectionNameLabel(language: ComposerLanguage): string {
  switch (language) {
    case "zh-CN":
      return "\u8fde\u63a5\u540d\u79f0\uff08\u53ef\u9009\uff09";
    case "es-ES":
      return "Nombre de conexion (opcional)";
    case "fr-FR":
      return "Nom de connexion (facultatif)";
    case "de-DE":
      return "Verbindungsname (optional)";
    case "ja-JP":
      return "\u63a5\u7d9a\u540d\uff08\u4efb\u610f\uff09";
    case "ko-KR":
      return "\uc5f0\uacb0 \uc774\ub984(\uc120\ud0dd)";
    case "pt-BR":
      return "Nome da conexao (opcional)";
    default:
      return "Connection name (optional)";
  }
}

function providerModelCardCopy(language: ComposerLanguage): {
  live: string;
  manual: string;
  remove: string;
  liveFetch: string;
  cached: string;
  autoOn: string;
  cacheOnly: string;
} {
  const copy: Record<ComposerLanguage, ReturnType<typeof providerModelCardCopy>> = {
    "zh-CN": { live: "实时", manual: "手动添加", remove: "移除模型", liveFetch: "实时拉取", cached: "使用缓存", autoOn: "已开启", cacheOnly: "仅缓存" },
    "en-US": { live: "Live", manual: "Manual", remove: "Remove model", liveFetch: "Live fetch", cached: "Cached", autoOn: "On", cacheOnly: "Cache only" },
    "es-ES": { live: "En directo", manual: "Manual", remove: "Quitar modelo", liveFetch: "Consulta en directo", cached: "En caché", autoOn: "Activado", cacheOnly: "Solo caché" },
    "fr-FR": { live: "En direct", manual: "Manuel", remove: "Retirer le modèle", liveFetch: "Récupération en direct", cached: "En cache", autoOn: "Activé", cacheOnly: "Cache uniquement" },
    "de-DE": { live: "Live", manual: "Manuell", remove: "Modell entfernen", liveFetch: "Live abrufen", cached: "Zwischengespeichert", autoOn: "Aktiv", cacheOnly: "Nur Cache" },
    "ja-JP": { live: "取得済み", manual: "手動追加", remove: "モデルを削除", liveFetch: "最新の一覧を取得", cached: "キャッシュ", autoOn: "有効", cacheOnly: "キャッシュのみ" },
    "ko-KR": { live: "실시간", manual: "직접 추가", remove: "모델 제거", liveFetch: "실시간으로 가져오기", cached: "캐시됨", autoOn: "켜짐", cacheOnly: "캐시만 사용" },
    "pt-BR": { live: "Ao vivo", manual: "Manual", remove: "Remover modelo", liveFetch: "Buscar ao vivo", cached: "Em cache", autoOn: "Ativado", cacheOnly: "Somente cache" },
  };

  return copy[language] ?? copy["en-US"];
}

function providerFailureCopy(
  category: string | undefined,
  language: ComposerLanguage,
): { statusLabel: string; headline: string } {
  const localized = (
    values: Record<ComposerLanguage, { statusLabel: string; headline: string }>,
  ): { statusLabel: string; headline: string } => values[language] ?? values["en-US"];

  switch (category) {
    case "test_failed":
      return localized({
        "zh-CN": { statusLabel: "\u6d4b\u8bd5\u5931\u8d25", headline: "\u8fde\u63a5\u6d4b\u8bd5\u5931\u8d25" },
        "en-US": { statusLabel: "Test failed", headline: "Connection test failed" },
        "es-ES": { statusLabel: "Prueba fallida", headline: "Falló la prueba de conexión" },
        "fr-FR": { statusLabel: "Test échoué", headline: "Le test de connexion a échoué" },
        "de-DE": { statusLabel: "Test fehlgeschlagen", headline: "Verbindungstest fehlgeschlagen" },
        "ja-JP": { statusLabel: "\u30c6\u30b9\u30c8\u5931\u6557", headline: "\u63a5\u7d9a\u30c6\u30b9\u30c8\u306b\u5931\u6557\u3057\u307e\u3057\u305f" },
        "ko-KR": { statusLabel: "\ud14c\uc2a4\ud2b8 \uc2e4\ud328", headline: "\uc5f0\uacb0 \ud14c\uc2a4\ud2b8\uac00 \uc2e4\ud328\ud588\uc2b5\ub2c8\ub2e4" },
        "pt-BR": { statusLabel: "Teste falhou", headline: "O teste de conexão falhou" },
      });
    case "invalid_key_or_permission":
    case "invalid_api_key":
    case "authentication_failed":
      return localized({
        "zh-CN": { statusLabel: "密钥被拒", headline: "API key 被拒绝" },
        "en-US": { statusLabel: "Key rejected", headline: "API key rejected" },
        "es-ES": { statusLabel: "Clave rechazada", headline: "La clave API fue rechazada" },
        "fr-FR": { statusLabel: "Clé refusée", headline: "La clé API a été refusée" },
        "de-DE": { statusLabel: "Schlüssel abgelehnt", headline: "API-Schlüssel wurde abgelehnt" },
        "ja-JP": { statusLabel: "キー拒否", headline: "API キーが拒否されました" },
        "ko-KR": { statusLabel: "키 거부", headline: "API 키가 거부되었습니다" },
        "pt-BR": { statusLabel: "Chave rejeitada", headline: "A chave de API foi rejeitada" },
      });
    case "model_unsupported":
    case "model_not_supported":
      return localized({
        "zh-CN": { statusLabel: "模型被拒", headline: "模型名不被接受" },
        "en-US": { statusLabel: "Model rejected", headline: "Model name rejected" },
        "es-ES": { statusLabel: "Modelo rechazado", headline: "El nombre del modelo fue rechazado" },
        "fr-FR": { statusLabel: "Modèle refusé", headline: "Le nom du modèle a été refusé" },
        "de-DE": { statusLabel: "Modell abgelehnt", headline: "Modellname wurde abgelehnt" },
        "ja-JP": { statusLabel: "モデル拒否", headline: "モデル名が受け付けられませんでした" },
        "ko-KR": { statusLabel: "모델 거부", headline: "모델 이름이 거부되었습니다" },
        "pt-BR": { statusLabel: "Modelo rejeitado", headline: "O nome do modelo foi rejeitado" },
      });
    case "model_not_found":
      return localized({
        "zh-CN": { statusLabel: "模型未就位", headline: "目标模型当前不可用" },
        "en-US": { statusLabel: "Model unavailable", headline: "Model is unavailable right now" },
        "es-ES": { statusLabel: "Modelo no disponible", headline: "El modelo no está disponible ahora mismo" },
        "fr-FR": { statusLabel: "Modèle indisponible", headline: "Le modèle est indisponible pour le moment" },
        "de-DE": { statusLabel: "Modell nicht verfügbar", headline: "Das Modell ist derzeit nicht verfügbar" },
        "ja-JP": { statusLabel: "モデル利用不可", headline: "このモデルは現在利用できません" },
        "ko-KR": { statusLabel: "모델 사용 불가", headline: "지금은 이 모델을 사용할 수 없습니다" },
        "pt-BR": { statusLabel: "Modelo indisponível", headline: "O modelo não está disponível agora" },
      });
    case "malformed_response":
      return localized({
        "zh-CN": { statusLabel: "暂时无法使用", headline: "请重试，仍失败可换一个模型" },
        "en-US": { statusLabel: "Reply unavailable", headline: "Try again, or choose another model" },
        "es-ES": { statusLabel: "Respuesta no disponible", headline: "Inténtalo de nuevo o elige otro modelo" },
        "fr-FR": { statusLabel: "Réponse indisponible", headline: "Réessayez ou choisissez un autre modèle" },
        "de-DE": { statusLabel: "Antwort nicht verfügbar", headline: "Erneut versuchen oder anderes Modell wählen" },
        "ja-JP": { statusLabel: "回答を利用できません", headline: "もう一度試すか、別のモデルを選んでください" },
        "ko-KR": { statusLabel: "응답을 사용할 수 없음", headline: "다시 시도하거나 다른 모델을 선택하세요" },
        "pt-BR": { statusLabel: "Resposta indisponível", headline: "Tente novamente ou escolha outro modelo" },
      });
    case "sidecar_unavailable":
      return localized({
        "zh-CN": { statusLabel: "正在准备", headline: "Trainer 正在启动，请稍后重试" },
        "en-US": { statusLabel: "Getting ready", headline: "Trainer is starting. Try again shortly" },
        "es-ES": { statusLabel: "Preparando", headline: "Trainer se está iniciando. Inténtalo de nuevo en un momento" },
        "fr-FR": { statusLabel: "Préparation", headline: "Trainer démarre. Réessayez dans un instant" },
        "de-DE": { statusLabel: "Wird vorbereitet", headline: "Trainer startet. Bitte gleich noch einmal versuchen" },
        "ja-JP": { statusLabel: "準備中", headline: "Trainer を起動しています。少し待って再試行してください" },
        "ko-KR": { statusLabel: "준비 중", headline: "Trainer를 시작하고 있습니다. 잠시 후 다시 시도하세요" },
        "pt-BR": { statusLabel: "Preparando", headline: "O Trainer está iniciando. Tente novamente em instantes" },
      });
    case "workspace_trust":
      return localized({
        "zh-CN": { statusLabel: "需要确认", headline: "请在 VS Code 中信任此文件夹后重试" },
        "en-US": { statusLabel: "Action needed", headline: "Trust this folder in VS Code, then try again" },
        "es-ES": { statusLabel: "Se requiere acción", headline: "Confía en esta carpeta en VS Code y vuelve a intentarlo" },
        "fr-FR": { statusLabel: "Action requise", headline: "Faites confiance à ce dossier dans VS Code, puis réessayez" },
        "de-DE": { statusLabel: "Aktion nötig", headline: "Vertrauen Sie diesem Ordner in VS Code und versuchen Sie es erneut" },
        "ja-JP": { statusLabel: "確認が必要", headline: "VS Code でこのフォルダーを信頼してから、もう一度試してください" },
        "ko-KR": { statusLabel: "확인이 필요함", headline: "VS Code에서 이 폴더를 신뢰한 뒤 다시 시도하세요" },
        "pt-BR": { statusLabel: "Ação necessária", headline: "Confie nesta pasta no VS Code e tente novamente" },
      });
    case "network":
    case "network_error":
      return localized({
        "zh-CN": { statusLabel: "无法连接", headline: "请检查网络后重试" },
        "en-US": { statusLabel: "Can't connect", headline: "Check your connection, then try again" },
        "es-ES": { statusLabel: "No se puede conectar", headline: "Revisa tu conexión y vuelve a intentarlo" },
        "fr-FR": { statusLabel: "Connexion impossible", headline: "Vérifiez votre connexion, puis réessayez" },
        "de-DE": { statusLabel: "Keine Verbindung", headline: "Verbindung prüfen und erneut versuchen" },
        "ja-JP": { statusLabel: "接続できません", headline: "接続を確認してから、もう一度試してください" },
        "ko-KR": { statusLabel: "연결할 수 없음", headline: "연결을 확인한 뒤 다시 시도하세요" },
        "pt-BR": { statusLabel: "Não foi possível conectar", headline: "Verifique a conexão e tente novamente" },
      });
    case "timeout":
      return localized({
        "zh-CN": { statusLabel: "等待超时", headline: "请稍后重试" },
        "en-US": { statusLabel: "Took too long", headline: "Try again in a moment" },
        "es-ES": { statusLabel: "Tardó demasiado", headline: "Vuelve a intentarlo en un momento" },
        "fr-FR": { statusLabel: "Trop long", headline: "Réessayez dans un instant" },
        "de-DE": { statusLabel: "Dauert zu lange", headline: "Bitte gleich noch einmal versuchen" },
        "ja-JP": { statusLabel: "時間がかかりすぎています", headline: "少し待って再試行してください" },
        "ko-KR": { statusLabel: "시간이 너무 오래 걸림", headline: "잠시 후 다시 시도하세요" },
        "pt-BR": { statusLabel: "Demorou demais", headline: "Tente novamente em instantes" },
      });
    case "rate_limit":
      return localized({
        "zh-CN": { statusLabel: "请稍后再试", headline: "现在请求太多，请稍后重试" },
        "en-US": { statusLabel: "Please wait", headline: "It is busy right now. Try again shortly" },
        "es-ES": { statusLabel: "Espera un momento", headline: "Hay mucha actividad. Inténtalo de nuevo en breve" },
        "fr-FR": { statusLabel: "Patientez un instant", headline: "Il y a beaucoup d’activité. Réessayez bientôt" },
        "de-DE": { statusLabel: "Bitte kurz warten", headline: "Gerade ist viel los. Bitte gleich erneut versuchen" },
        "ja-JP": { statusLabel: "しばらくお待ちください", headline: "ただいま混み合っています。少し待って再試行してください" },
        "ko-KR": { statusLabel: "잠시 기다려 주세요", headline: "현재 사용량이 많습니다. 잠시 후 다시 시도하세요" },
        "pt-BR": { statusLabel: "Aguarde um momento", headline: "Há muito movimento agora. Tente novamente em instantes" },
      });
    case "language_probe_inconclusive":
      return localized({
        "zh-CN": { statusLabel: "\u4ecd\u5f85\u9a8c\u8bc1", headline: "zh-CN \u5b8c\u6574\u6027\u4ecd\u5f85\u9a8c\u8bc1" },
        "en-US": { statusLabel: "Not fully verified", headline: "zh-CN integrity still needs verification" },
        "es-ES": { statusLabel: "Aun sin verificar", headline: "La integridad zh-CN a\u00fan necesita verificaci\u00f3n" },
        "fr-FR": { statusLabel: "Encore \u00e0 v\u00e9rifier", headline: "L'int\u00e9grit\u00e9 zh-CN doit encore \u00eatre v\u00e9rifi\u00e9e" },
        "de-DE": { statusLabel: "Noch unbest\u00e4tigt", headline: "Die zh-CN-Integrit\u00e4t muss noch gepr\u00fcft werden" },
        "ja-JP": { statusLabel: "\u672a\u691c\u8a3c", headline: "zh-CN \u306e\u5b8c\u6574\u6027\u306f\u307e\u3060\u691c\u8a3c\u4e2d\u3067\u3059" },
        "ko-KR": { statusLabel: "\ubbf8\uac80\uc99d", headline: "zh-CN \ubb34\uacb0\uc131\uc740 \uc544\uc9c1 \uac80\uc99d\uc774 \ud544\uc694\ud569\ub2c8\ub2e4" },
        "pt-BR": { statusLabel: "Ainda n\u00e3o verificado", headline: "A integridade zh-CN ainda precisa de verifica\u00e7\u00e3o" },
      });
    case "language_corruption":
      return localized({
        "zh-CN": { statusLabel: "中文未正常送达", headline: "中文内容没有正常送到模型" },
        "en-US": { statusLabel: "Input corrupted", headline: "Chinese input is being corrupted" },
        "es-ES": { statusLabel: "Entrada dañada", headline: "La entrada en chino se está corrompiendo" },
        "fr-FR": { statusLabel: "Entrée altérée", headline: "La saisie chinoise est altérée" },
        "de-DE": { statusLabel: "Eingabe beschädigt", headline: "Chinesische Eingaben werden beschädigt" },
        "ja-JP": { statusLabel: "入力破損", headline: "中国語入力が壊れています" },
        "ko-KR": { statusLabel: "입력 손상", headline: "중국어 입력이 손상되고 있습니다" },
        "pt-BR": { statusLabel: "Entrada corrompida", headline: "A entrada em chinês está sendo corrompida" },
      });
    case "reasoning_budget_exhausted":
      return localized({
        "zh-CN": { statusLabel: "思考耗尽预算", headline: "模型隐藏推理消耗了输出预算，可重试或换非思考模型" },
        "en-US": { statusLabel: "Reasoning consumed budget", headline: "Hidden reasoning consumed the output budget; retry or pick a non-reasoning model" },
        "es-ES": { statusLabel: "Razoning consumió presupuesto", headline: "El razonamiento oculto consumió el presupuesto; reintenta o elige otro modelo" },
        "fr-FR": { statusLabel: "Raisonnement épuisé", headline: "Le raisonnement caché a consommé le budget; réessayez ou changez de modèle" },
        "de-DE": { statusLabel: "Denkenbudget aufgebraucht", headline: "Verdecktes Reasoning hat das Budget verbraucht; wiederholen oder anderes Modell wählen" },
        "ja-JP": { statusLabel: "思考が予算を消費", headline: "隠れた推論が出力予算を消費しました。再試行または別のモデルを選択してください" },
        "ko-KR": { statusLabel: "추론이 예산 소진", headline: "숨은 추론이 출력 예산을 소비했습니다. 재시도하거나 다른 모델을 선택하세요" },
        "pt-BR": { statusLabel: "Raciocínio esgotou orçamento", headline: "O raciocínio oculto consumiu o orçamento; tente novamente ou escolha outro modelo" },
      });
    case "reasoning_leak":
    case "empty_response":
      return localized({
        "zh-CN": { statusLabel: "空回复", headline: "模型没有给出可用回复" },
        "en-US": { statusLabel: "Empty reply", headline: "Provider returned no usable reply" },
        "es-ES": { statusLabel: "Respuesta vacía", headline: "El proveedor no devolvió una respuesta usable" },
        "fr-FR": { statusLabel: "Réponse vide", headline: "Le fournisseur n'a renvoyé aucune réponse exploitable" },
        "de-DE": { statusLabel: "Leere Antwort", headline: "Der Anbieter lieferte keine brauchbare Antwort" },
        "ja-JP": { statusLabel: "空応答", headline: "利用可能な応答が返ってきませんでした" },
        "ko-KR": { statusLabel: "빈 응답", headline: "사용 가능한 응답이 돌아오지 않았습니다" },
        "pt-BR": { statusLabel: "Resposta vazia", headline: "O provedor não devolveu resposta utilizável" },
      });
    case "truncated_or_empty":
      return localized({
        "zh-CN": { statusLabel: "回复不可用", headline: "模型回复不可用" },
        "en-US": { statusLabel: "Reply unusable", headline: "Provider reply was unusable" },
        "es-ES": { statusLabel: "Respuesta inutilizable", headline: "La respuesta del proveedor no se pudo usar" },
        "fr-FR": { statusLabel: "Réponse inutilisable", headline: "La réponse du fournisseur était inutilisable" },
        "de-DE": { statusLabel: "Antwort unbrauchbar", headline: "Die Antwort des Anbieters war unbrauchbar" },
        "ja-JP": { statusLabel: "応答不可", headline: "プロバイダーの応答は利用できませんでした" },
        "ko-KR": { statusLabel: "응답 사용 불가", headline: "제공자 응답을 사용할 수 없었습니다" },
        "pt-BR": { statusLabel: "Resposta inutilizável", headline: "A resposta do provedor não pôde ser usada" },
      });
    case "context_length_exceeded":
      return localized({
        "zh-CN": { statusLabel: "内容太长", headline: "请缩短输入内容后重试" },
        "en-US": { statusLabel: "Too much content", headline: "Shorten your message, then try again" },
        "es-ES": { statusLabel: "Demasiado contenido", headline: "Acorta el mensaje y vuelve a intentarlo" },
        "fr-FR": { statusLabel: "Trop de contenu", headline: "Raccourcissez votre message, puis réessayez" },
        "de-DE": { statusLabel: "Zu viel Inhalt", headline: "Kürzen Sie Ihre Nachricht und versuchen Sie es erneut" },
        "ja-JP": { statusLabel: "内容が長すぎます", headline: "メッセージを短くして、もう一度試してください" },
        "ko-KR": { statusLabel: "내용이 너무 깁니다", headline: "메시지를 줄인 뒤 다시 시도하세요" },
        "pt-BR": { statusLabel: "Conteúdo demais", headline: "Encurte a mensagem e tente novamente" },
      });
    default:
      return localized({
        "zh-CN": { statusLabel: "需要处理", headline: "连接需要检查" },
        "en-US": { statusLabel: "Needs attention", headline: "Connection needs attention" },
        "es-ES": { statusLabel: "Necesita atención", headline: "La conexión necesita revisión" },
        "fr-FR": { statusLabel: "À vérifier", headline: "La connexion doit être vérifiée" },
        "de-DE": { statusLabel: "Benötigt Prüfung", headline: "Verbindung muss geprüft werden" },
        "ja-JP": { statusLabel: "確認が必要", headline: "接続の確認が必要です" },
        "ko-KR": { statusLabel: "확인 필요", headline: "연결을 확인해야 합니다" },
        "pt-BR": { statusLabel: "Precisa de atenção", headline: "A conexão precisa de revisão" },
      });
  }

  const zh = language === "zh-CN";
  switch (category) {
    case "invalid_key_or_permission":
    case "invalid_api_key":
    case "authentication_failed":
      return {
        statusLabel: zh ? "密钥被拒" : "Key rejected",
        headline: zh ? "API key 被拒绝" : "API key rejected",
      };
    case "model_unsupported":
    case "model_not_supported":
      return {
        statusLabel: zh ? "模型被拒" : "Model rejected",
        headline: zh ? "模型名称不可用" : "Model name rejected",
      };
    case "model_not_found":
      return {
        statusLabel: zh ? "模型未就位" : "Model unavailable",
        headline: zh ? "目标模型当前不可用" : "Model is unavailable right now",
      };
    case "malformed_response":
      return {
        statusLabel: zh ? "响应不兼容" : "Payload unsupported",
        headline: zh ? "接口响应不兼容" : "Endpoint payload unsupported",
      };
    case "sidecar_unavailable":
      return {
        statusLabel: zh ? "后端未就绪" : "Backend offline",
        headline: zh ? "Trainer 后端未就绪" : "Trainer backend not ready",
      };
    case "workspace_trust":
      return {
        statusLabel: zh ? "等待授信" : "Trust required",
        headline: zh ? "工作区尚未授信" : "Workspace trust required",
      };
    case "network":
    case "network_error":
      return {
        statusLabel: zh ? "无法连通" : "Unreachable",
        headline: zh ? "无法连接 provider" : "Provider unreachable",
      };
    case "timeout":
      return {
        statusLabel: zh ? "请求超时" : "Timed out",
        headline: zh ? "provider 响应超时" : "Provider timed out",
      };
    case "rate_limit":
      return {
        statusLabel: zh ? "限流中" : "Rate limited",
        headline: zh ? "provider 正在限流" : "Provider is rate limiting",
      };
    case "empty_response":
      return {
        statusLabel: zh ? "空回复" : "Empty reply",
        headline: zh ? "模型没有给出可用回复" : "Provider returned no usable reply",
      };
    case "truncated_or_empty":
      return {
        statusLabel: zh ? "回复不可用" : "Reply unusable",
        headline: zh ? "模型回复不完整" : "Provider reply was unusable",
      };
    case "context_length_exceeded":
      return {
        statusLabel: zh ? "上下文超限" : "Context limited",
        headline: zh ? "上下文长度超限" : "Context window exceeded",
      };
    default:
      return {
        statusLabel: zh ? "需检查" : "Needs attention",
        headline: zh ? "连接需要检查" : "Connection needs attention",
      };
  }
}

function sidecarRestartCopy(
  language: ComposerLanguage,
): { label: string; detail: string } {
  const copy: Record<ComposerLanguage, { label: string; detail: string }> = {
    "zh-CN": {
      label: "重新启动 Trainer",
      detail: "重新启动本地后端，再继续检查连接。",
    },
    "en-US": {
      label: "Restart Trainer",
      detail: "Restart the local backend, then check the connection again.",
    },
    "es-ES": {
      label: "Reiniciar Trainer",
      detail: "Reinicia el backend local y vuelve a comprobar la conexión.",
    },
    "fr-FR": {
      label: "Redémarrer Trainer",
      detail: "Redémarrez le backend local, puis vérifiez à nouveau la connexion.",
    },
    "de-DE": {
      label: "Trainer neu starten",
      detail: "Starten Sie das lokale Backend neu und prüfen Sie die Verbindung erneut.",
    },
    "ja-JP": {
      label: "Trainer を再起動",
      detail: "ローカルバックエンドを再起動してから、接続をもう一度確認します。",
    },
    "ko-KR": {
      label: "Trainer 다시 시작",
      detail: "로컬 백엔드를 다시 시작한 다음 연결을 다시 확인합니다.",
    },
    "pt-BR": {
      label: "Reiniciar o Trainer",
      detail: "Reinicie o backend local e verifique a conexão novamente.",
    },
  };
  return copy[language] ?? copy["en-US"];
}

export {
  providerConnectionNameLabel,
  providerFailureCopy,
  providerModelCardCopy,
  sidecarRestartCopy,
};
