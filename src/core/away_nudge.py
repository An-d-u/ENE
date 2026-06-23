"""
자리 비움 감지 응답을 위한 프롬프트 생성 도우미.
"""
from ..ai.persona_names import korean_subject_particle


def _idle_text(language: str, idle_minutes: int) -> str:
    if language == "en":
        return f"{idle_minutes} minutes"
    if language == "ja":
        return f"{idle_minutes}分"
    return f"{idle_minutes}분"


def _input_grace_text(language: str, input_grace_minutes: int) -> str:
    if language == "en":
        return f"{input_grace_minutes} minutes"
    if language == "ja":
        return f"{input_grace_minutes}分"
    return f"{input_grace_minutes}분"


def _input_note(language: str, user_input_detected: bool | None, input_grace_minutes: int) -> str:
    input_grace = _input_grace_text(language, input_grace_minutes)
    if user_input_detected is None:
        return {
            "ko": "마우스/키보드 입력 상태를 확인하지 못해 보수적으로",
            "en": "conservatively because keyboard and mouse input status could not be checked,",
            "ja": "マウス/キーボード入力の状態を確認できなかったため保守的に",
        }.get(language, "마우스/키보드 입력 상태를 확인하지 못해 보수적으로")
    if language == "en":
        return f"keyboard or mouse input happened within the last {input_grace}"
    if language == "ja":
        return f"直近{input_grace}以内にマウスまたはキーボード入力がありました"
    return f"최근 {input_grace} 안에 마우스나 키보드 입력은 있었어"


def _default_user_name(language: str) -> str:
    return {
        "ko": "마스터",
        "en": "Master",
        "ja": "マスター",
    }.get(language, "마스터")


def build_away_nudge_prompt(
    *,
    language: str,
    idle_minutes: int,
    input_grace_minutes: int | None = None,
    use_stable_screen: bool | None = None,
    diff_percent: float | None = None,
    user_input_detected: bool | None = None,
    user_name: str | None = None,
) -> str:
    """유휴 감지 결과를 ENE 응답용 프롬프트로 변환한다."""
    normalized_language = str(language or "ko").strip().lower()
    idle = _idle_text(normalized_language, int(idle_minutes or 0))
    input_grace_minutes = max(1, int(input_grace_minutes or idle_minutes or 1))
    input_grace = _input_grace_text(normalized_language, input_grace_minutes)
    prompt_user_name = str(user_name or "").strip() or _default_user_name(normalized_language)
    if user_input_detected is None and use_stable_screen is not None:
        user_input_detected = not bool(use_stable_screen)

    if user_input_detected is False:
        if normalized_language == "en":
            return (
                f"Status notice: {prompt_user_name} appears to be away. "
                f"They have not sent you a new message for the last {idle}, and "
                f"there has been no keyboard or mouse input for the last {input_grace}. "
                f"Look at the latest full-screen image just attached and say one short, natural line, "
                f"like a quiet aside or a note left for {prompt_user_name}."
            )
        if normalized_language == "ja":
            return (
                f"状態通知: {prompt_user_name}はいま席を外しているようです。"
                f"直近{idle}、あなたへ新しいメッセージを送っておらず、"
                f"直近{input_grace}のマウス/キーボード入力もありませんでした。"
                f"添付された最新の全画面画像を見て、独り言のような自然な一言か、"
                f"席を外した{prompt_user_name}へ残す短い言葉を返してください。"
            )
        return (
            f"상태 알림: {prompt_user_name}{korean_subject_particle(prompt_user_name)} 현재 자리 비움 상태야. "
            f"참고로 최근 {idle} 동안 너에게 새 메시지를 보내지 않았고, "
            f"최근 {input_grace} 동안 마우스/키보드 입력도 없었어. "
            f"방금 첨부한 최신 전체 화면 1장을 보고, 혼잣말처럼 자연스럽게 한 마디 하거나 "
            f"자리 비운 {prompt_user_name}에게 남길 말을 짧게 해줘."
        )

    input_note = _input_note(normalized_language, user_input_detected, input_grace_minutes)
    if normalized_language == "en":
        return (
            f"Status notice: {prompt_user_name} has not talked to you for the last {idle}. "
            f"{input_note}, so they may still be using the computer. "
            f"Look at the latest full-screen image just attached and reply with one short line "
            f"that gently shows you would like {prompt_user_name} to talk to you a little."
        )
    if normalized_language == "ja":
        return (
            f"状態通知: {prompt_user_name}は直近{idle}、あなたに話しかけていません。"
            f"{input_note}。まだPCを使っている可能性があります。"
            f"添付された最新の全画面画像を見て、{prompt_user_name}に少し話しかけてほしい気持ちが"
            f"伝わる短い一言を返してください。"
        )
    return (
        f"상태 알림: {prompt_user_name}{korean_subject_particle(prompt_user_name)} 최근 {idle} 동안 너에게 말을 걸지 않았어. "
        f"{input_note}. 아직 컴퓨터를 쓰고 있을 가능성이 있어. "
        f"방금 첨부한 최신 전체 화면 1장을 보고, {prompt_user_name}{korean_subject_particle(prompt_user_name)} 너에게 말을 조금 걸어줬으면 좋겠다는 "
        f"티가 나는 짧은 한마디를 해줘."
    )
