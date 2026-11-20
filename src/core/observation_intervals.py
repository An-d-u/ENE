"""PC 창과 휴대폰 카메라의 자동 관찰에 함께 적용하는 시간 설정."""

DEFAULT_SAMPLE_SECONDS = 30
DEFAULT_REQUEST_SECONDS = 300
MAX_INTERVAL_SECONDS = 86400
SAMPLE_SECONDS_KEY = "observation_sample_seconds"
REQUEST_SECONDS_KEY = "observation_request_seconds"
DEFAULT_VISUAL_CONTEXT_TURNS = 5


def visual_context_turns(settings):
    value = settings.get("visual_context_turns", DEFAULT_VISUAL_CONTEXT_TURNS)
    return value if type(value) is int and 0 <= value <= 20 else DEFAULT_VISUAL_CONTEXT_TURNS


def valid_interval_seconds(value: object) -> bool:
    return type(value) is int and 1 <= value <= MAX_INTERVAL_SECONDS


def normalize_observation_intervals(settings) -> tuple[int, int]:
    """누락되거나 범위를 벗어난 항목만 해당 기본값으로 복원한다."""
    sample = settings.get(SAMPLE_SECONDS_KEY)
    request = settings.get(REQUEST_SECONDS_KEY)
    return (
        sample if valid_interval_seconds(sample) else DEFAULT_SAMPLE_SECONDS,
        request if valid_interval_seconds(request) else DEFAULT_REQUEST_SECONDS,
    )
