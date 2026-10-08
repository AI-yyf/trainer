"""One recovery instruction for an explicitly exhausted provider account."""

from __future__ import annotations

_COPY: dict[str, tuple[str, str]] = {
    "zh-CN": (
        "模型服务商的账户额度已用完，这一轮暂时无法继续。",
        "请补充服务商账户额度，或在设置中换一个可用连接，再重发这一轮。",
    ),
    "en-US": (
        "The provider account has no quota left, so this turn cannot continue.",
        "Restore the provider account's quota or choose another connection in Settings, then resend this turn.",
    ),
    "es-ES": (
        "La cuenta del proveedor no tiene cuota disponible; este turno no puede continuar.",
        "Añade cuota a la cuenta del proveedor o elige otra conexión en Ajustes y vuelve a enviar este turno.",
    ),
    "fr-FR": (
        "Le quota du compte du fournisseur est épuisé ; cet échange ne peut pas continuer.",
        "Rétablissez le quota du fournisseur ou choisissez une autre connexion dans les paramètres, puis renvoyez ce message.",
    ),
    "de-DE": (
        "Das Kontingent des Anbieterkontos ist aufgebraucht; diese Anfrage kann nicht fortgesetzt werden.",
        "Füllen Sie das Kontingent auf oder wählen Sie in den Einstellungen eine andere Verbindung und senden Sie die Anfrage erneut.",
    ),
    "ja-JP": (
        "モデル提供元のアカウントの利用枠がなくなったため、このやり取りを続けられません。",
        "提供元の利用枠を補充するか、設定で別の接続を選んでから、このメッセージを再送してください。",
    ),
    "ko-KR": (
        "모델 제공업체 계정의 사용 한도가 소진되어 이 대화를 계속할 수 없습니다.",
        "제공업체의 사용 한도를 충전하거나 설정에서 다른 연결을 선택한 후 이 메시지를 다시 보내세요.",
    ),
    "pt-BR": (
        "A conta do provedor está sem cota; esta conversa não pode continuar agora.",
        "Reponha a cota do provedor ou escolha outra conexão nas configurações e envie esta mensagem novamente.",
    ),
}


def provider_quota_copy(language: str | None) -> tuple[str, str]:
    return _COPY.get(language or "en-US", _COPY["en-US"])


def provider_quota_reply(language: str | None) -> str:
    summary, next_step = provider_quota_copy(language)
    return f"{summary}\n\n{next_step}"
