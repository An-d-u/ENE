"""화면과 모델 호출 없이 대화창에 남길 짧은 안부."""
from random import choice


def away_greeting(language: str) -> str:
    greetings = {
        "ko": ("다시 이야기하고 싶을 때 불러 줘. 여기 있을게.", "오늘도 잘 지내고 있길 바라. 편할 때 들러 줘."),
        "ja": ("また話したくなったら声をかけてね。ここにいるよ。", "今日も元気に過ごせているといいな。"),
        "en": ("I'll be here whenever you feel like talking.", "Hope your day is going well. Drop by whenever you like."),
    }
    return choice(greetings.get(language, greetings["ko"]))
