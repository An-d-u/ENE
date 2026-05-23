"""
자리 비움 감지 응답을 위한 프롬프트 생성 도우미.
"""


def _idle_text(language: str, idle_minutes: int) -> str:
    if language == "en":
        return f"{idle_minutes} minutes"
    if language == "ja":
        return f"{idle_minutes}分"
    return f"{idle_minutes}분"


def _diff_note(language: str, diff_percent: float | None) -> str:
    if diff_percent is None:
        return {
            "ko": "비교 실패로 보수적으로",
            "en": "conservatively because comparison failed,",
            "ja": "比較に失敗したため保守的に",
        }.get(language, "비교 실패로 보수적으로")
    if language == "en":
        return f"with a {diff_percent:.2f}% difference,"
    if language == "ja":
        return f"差分 {diff_percent:.2f}% のため"
    return f"차이율 {diff_percent:.2f}%로"


def build_away_nudge_prompt(
    *,
    language: str,
    idle_minutes: int,
    use_stable_screen: bool,
    diff_percent: float | None,
) -> str:
    """유휴 감지 결과를 ENE 응답용 프롬프트로 변환한다."""
    normalized_language = str(language or "ko").strip().lower()
    idle = _idle_text(normalized_language, int(idle_minutes or 0))

    if use_stable_screen:
        if normalized_language == "en":
            return (
                f"Status notice: Master appears to be away. "
                f"They have not sent you a new message for the last {idle}, and "
                f"the 30-second screen comparison barely changed (difference {diff_percent:.2f}%). "
                f"Look at the latest full-screen image just attached and say one short, natural line, "
                f"like a quiet aside or a note left for Master."
            )
        if normalized_language == "ja":
            return (
                f"状態通知: マスターはいま席を外しているようです。"
                f"直近{idle}、あなたへ新しいメッセージを送っておらず、"
                f"30秒間隔の画面比較でもほとんど変化がありませんでした(差分 {diff_percent:.2f}%)。"
                f"添付された最新の全画面画像を見て、独り言のような自然な一言か、"
                f"席を外したマスターへ残す短い言葉を返してください。"
            )
        return (
            f"상태 알림: 마스터가 현재 자리 비움 상태야. "
            f"참고로 최근 {idle} 동안 너에게 새 메시지를 보내지 않았고, "
            f"30초 간격 화면 비교에서 변화가 거의 없었어(차이율 {diff_percent:.2f}%). "
            f"방금 첨부한 최신 전체 화면 1장을 보고, 혼잣말처럼 자연스럽게 한 마디 하거나 "
            f"자리 비운 마스터에게 남길 말을 짧게 해줘."
        )

    diff = _diff_note(normalized_language, diff_percent)
    if normalized_language == "en":
        return (
            f"Status notice: Master has not talked to you for the last {idle}. "
            f"{diff} the screen appears to have changed. "
            f"Look at the latest full-screen image just attached and reply with one short line "
            f"that gently shows you would like Master to talk to you a little."
        )
    if normalized_language == "ja":
        return (
            f"状態通知: マスターは直近{idle}、あなたに話しかけていません。"
            f"{diff}、画面には変化がある状態だと判断しました。"
            f"添付された最新の全画面画像を見て、マスターに少し話しかけてほしい気持ちが"
            f"伝わる短い一言を返してください。"
        )
    return (
        f"상태 알림: 마스터가 최근 {idle} 동안 너에게 말을 걸지 않았어. "
        f"{diff} 화면 변화가 있는 상태로 판단했어. "
        f"방금 첨부한 최신 전체 화면 1장을 보고, 마스터가 너에게 말을 조금 걸어줬으면 좋겠다는 "
        f"티가 나는 짧은 한마디를 해줘."
    )
