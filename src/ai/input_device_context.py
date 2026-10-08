"""현재 최종 요청에만 포함할 입력 기기 문맥."""

_CONTEXT = {
    "ko": (
        "이번 응답을 요청한 입력 기기: {device}. 현재 요청에만 유효합니다. "
        "사용자의 위치·이동 상태·화면 접근·도구 권한을 추정하지 마세요. "
        "기기만을 이유로 답변 길이나 말투를 일괄 변경하거나 기기를 불필요하게 언급하지 마세요. "
        "사용자 프로필이나 장기적인 사실로 취급하지 마세요."
    ),
    "en": (
        "Input device for this response request: {device}. Valid only for this request. "
        "Do not infer the user's location, movement, screen access, or tool permissions. "
        "Do not automatically change response length or tone, or mention the device unnecessarily. "
        "Do not treat this as a user profile attribute or lasting fact."
    ),
    "ja": (
        "今回の応答を要求した入力デバイス: {device}。このリクエストだけに有効です。"
        "ユーザーの居場所・移動状態・画面へのアクセス・ツールの権限を推測しないでください。"
        "デバイスだけを理由に回答の長さや口調を一律に変えたり、不必要に言及したりしないでください。"
        "ユーザープロフィールや長期的な事実として扱わないでください。"
    ),
}
_MOBILE = {"ko": "모바일 앱", "en": "mobile app", "ja": "モバイルアプリ"}


def append_input_device_context(
    message: str, request_device: str | None, language: str
) -> str:
    """사용자 원문을 변경하지 않고 최종 전송용 새 문자열만 만든다."""
    if type(request_device) is not str or request_device not in ("pc", "mobile"):
        return message
    language = language if language in _CONTEXT else "ko"
    device = "PC" if request_device == "pc" else _MOBILE[language]
    return (
        message
        + "\n\n[Input device context]\n"
        + _CONTEXT[language].format(device=device)
    )
