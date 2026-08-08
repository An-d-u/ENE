import asyncio
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.ai.response_protocol import (
    MAX_SAFE_TOKEN_COUNT,
    OneShotGenerationResult,
    OneShotTokenUsage,
    ResponseStatus,
)
from src.core.bridge_workers import (
    LifeRecordGenerationRequest,
    LifeRecordWorker,
    LifeRecordWorkerResult,
)


SEOUL = ZoneInfo("Asia/Seoul")
START = datetime(2099, 8, 6, 23, 0, tzinfo=SEOUL)
END = datetime(2099, 8, 7, 10, 0, tzinfo=SEOUL)


def _valid_output(*, activity: str = "가상 정원에서 조용히 시간을 보냈다.") -> str:
    return json.dumps(
        {
            "entries": [
                {
                    "started_at": START.isoformat(),
                    "ended_at": END.isoformat(),
                    "place": "가상 정원",
                    "activity": activity,
                }
            ],
            "ending_state": {
                "place": "가상 정원",
                "summary": "정원의 의자에 앉아 있었다.",
            },
        },
        ensure_ascii=False,
    )


def _invalid_output(code: str = "gap") -> str:
    if code == "invalid_json":
        return "not-json"
    payload = json.loads(_valid_output())
    payload["entries"][0]["started_at"] = datetime(
        2099, 8, 7, 0, 0, tzinfo=SEOUL
    ).isoformat()
    return json.dumps(payload, ensure_ascii=False)


def _one_shot(
    text: str,
    *,
    status: ResponseStatus = ResponseStatus.COMPLETE,
    usage: tuple[int | None, int | None, int | None] = (1, 2, 3),
    finish_reason: str = "stop",
) -> OneShotGenerationResult:
    return OneShotGenerationResult(
        text=text,
        status=status,
        finish_reason=finish_reason,
        token_usage=OneShotTokenUsage(*usage),
    )


class _Client:
    def __init__(self, *responses: object):
        self.responses = list(responses)
        self.prompts: list[str] = []
        self.history = ["synthetic-existing-history"]

    async def generate_life_record_once(self, prompt: str):
        self.prompts.append(prompt)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def _request(*, prompt: str = "SYNTHETIC-LIFE-PROMPT") -> LifeRecordGenerationRequest:
    return LifeRecordGenerationRequest(
        operation_id=17,
        prompt=prompt,
        inactive_started_at=START,
        returned_at=END,
        timezone="Asia/Seoul",
        language="ko",
    )


def _run(worker: LifeRecordWorker):
    successes: list[tuple[int, LifeRecordWorkerResult]] = []
    failures: list[tuple[int, LifeRecordWorkerResult]] = []
    worker.result_ready.connect(lambda operation_id, result: successes.append((operation_id, result)))
    worker.error_occurred.connect(lambda operation_id, result: failures.append((operation_id, result)))
    worker.run()
    return successes, failures


def test_life_record_worker_accepts_first_complete_valid_output_once():
    client = _Client(_one_shot(_valid_output(), usage=(2, 3, 5)))

    successes, failures = _run(LifeRecordWorker(client, _request()))

    assert failures == []
    assert len(successes) == 1
    operation_id, result = successes[0]
    assert operation_id == 17
    assert result.output is not None
    assert result.output.entries[0].started_at == START
    assert result.status is ResponseStatus.COMPLETE
    assert result.error_code is None
    assert result.attempt_count == 1
    assert result.token_usage == OneShotTokenUsage(2, 3, 5)
    assert client.prompts == ["SYNTHETIC-LIFE-PROMPT"]


def test_life_record_worker_retries_one_complete_validation_failure_with_safe_code():
    client = _Client(
        _one_shot(_invalid_output(), usage=(2, 3, 5)),
        _one_shot(_valid_output(), usage=(7, 11, 18)),
    )

    successes, failures = _run(LifeRecordWorker(client, _request()))

    assert failures == []
    result = successes[0][1]
    assert result.output is not None
    assert result.attempt_count == 2
    assert result.token_usage == OneShotTokenUsage(9, 14, 23)
    assert client.prompts[0] == "SYNTHETIC-LIFE-PROMPT"
    assert client.prompts[1].startswith("SYNTHETIC-LIFE-PROMPT\n\n")
    assert "out_of_range" in client.prompts[1]
    assert _invalid_output() not in client.prompts[1]


def test_life_record_worker_stops_after_second_validation_failure():
    client = _Client(
        _one_shot(_invalid_output("invalid_json"), usage=(2, 3, 5)),
        _one_shot(_invalid_output(), usage=(7, 11, 18)),
    )

    successes, failures = _run(LifeRecordWorker(client, _request()))

    assert successes == []
    result = failures[0][1]
    assert result.output is None
    assert result.status is ResponseStatus.COMPLETE
    assert result.error_code == "out_of_range"
    assert result.attempt_count == 2
    assert result.token_usage == OneShotTokenUsage(9, 14, 23)
    assert len(client.prompts) == 2


@pytest.mark.parametrize(
    ("status", "finish_reason", "expected_code"),
    [
        (ResponseStatus.REFUSAL, "content_filter", "provider_refusal"),
        (ResponseStatus.INCOMPLETE, "other", "provider_incomplete"),
        (ResponseStatus.INCOMPLETE, "max_tokens", "provider_incomplete"),
        (ResponseStatus.EMPTY, "stop", "provider_empty"),
    ],
)
def test_life_record_worker_does_not_retry_non_complete_status(
    status, finish_reason, expected_code
):
    client = _Client(
        _one_shot(
            _invalid_output(),
            status=status,
            finish_reason=finish_reason,
            usage=(2, 3, 5),
        )
    )

    successes, failures = _run(LifeRecordWorker(client, _request()))

    assert successes == []
    result = failures[0][1]
    assert result.status is status
    assert result.error_code == expected_code
    assert result.attempt_count == 1
    assert len(client.prompts) == 1


def test_life_record_worker_does_not_retry_provider_error_and_hides_exception():
    try:
        raise RuntimeError("SYNTHETIC-NESTED-PRIVATE")
    except RuntimeError as cause:
        error = RuntimeError("SYNTHETIC-PROVIDER-PRIVATE")
        error.__cause__ = cause
    client = _Client(error)

    successes, failures = _run(LifeRecordWorker(client, _request()))

    assert successes == []
    result = failures[0][1]
    assert result.status is None
    assert result.error_code == "generation_failed"
    assert result.attempt_count == 1
    assert result.token_usage == OneShotTokenUsage(None, None, None)
    assert len(client.prompts) == 1
    assert "SYNTHETIC-PROVIDER-PRIVATE" not in repr(result)
    assert "SYNTHETIC-NESTED-PRIVATE" not in repr(result)


@pytest.mark.parametrize(
    "provider_failure",
    [
        asyncio.CancelledError("SYNTHETIC-CANCELLED-PRIVATE"),
        BaseException("SYNTHETIC-BASE-PRIVATE"),
    ],
)
def test_life_record_worker_contains_provider_base_exception_without_raw_details(
    provider_failure, capsys
):
    client = _Client(provider_failure)

    successes, failures = _run(LifeRecordWorker(client, _request()))
    captured = capsys.readouterr()

    assert successes == []
    assert len(failures) == 1
    result = failures[0][1]
    assert result.error_code == "generation_failed"
    assert result.attempt_count == 1
    assert "SYNTHETIC" not in captured.out
    assert "SYNTHETIC" not in captured.err


def test_life_record_worker_usage_keeps_missing_field_none_across_attempts():
    client = _Client(
        _one_shot(_invalid_output(), usage=(2, None, 5)),
        _one_shot(_valid_output(), usage=(7, 11, 18)),
    )

    successes, _failures = _run(LifeRecordWorker(client, _request()))

    assert successes[0][1].token_usage == OneShotTokenUsage(9, None, 23)


def test_life_record_worker_usage_overflow_remains_none():
    client = _Client(
        _one_shot(_invalid_output(), usage=(MAX_SAFE_TOKEN_COUNT, 1, 1)),
        _one_shot(_valid_output(), usage=(1, 1, 1)),
    )

    successes, _failures = _run(LifeRecordWorker(client, _request()))

    assert successes[0][1].token_usage == OneShotTokenUsage(None, 2, 2)


def test_life_record_worker_interruption_after_await_prevents_retry_and_signals():
    interrupted = False

    class InterruptingClient(_Client):
        async def generate_life_record_once(self, prompt: str):
            nonlocal interrupted
            result = await super().generate_life_record_once(prompt)
            interrupted = True
            return result

    class InterruptibleWorker(LifeRecordWorker):
        def isInterruptionRequested(self):
            return interrupted

    client = InterruptingClient(_one_shot(_invalid_output()))
    worker = InterruptibleWorker(client, _request())

    successes, failures = _run(worker)

    assert successes == []
    assert failures == []
    assert len(client.prompts) == 1


def test_life_record_worker_provider_cancellation_is_silent_when_interrupted():
    interrupted = False

    class CancellingClient(_Client):
        async def generate_life_record_once(self, prompt: str):
            nonlocal interrupted
            self.prompts.append(prompt)
            interrupted = True
            raise asyncio.CancelledError("SYNTHETIC-CANCELLED-PRIVATE")

    class InterruptibleWorker(LifeRecordWorker):
        def isInterruptionRequested(self):
            return interrupted

    client = CancellingClient()

    successes, failures = _run(InterruptibleWorker(client, _request()))

    assert successes == []
    assert failures == []
    assert len(client.prompts) == 1


@pytest.mark.parametrize("provider_succeeds", [True, False])
def test_life_record_worker_interruption_during_completion_log_prevents_signal(
    provider_succeeds, monkeypatch
):
    interrupted = False

    class InterruptibleWorker(LifeRecordWorker):
        def isInterruptionRequested(self):
            return interrupted

    response = (
        _one_shot(_valid_output())
        if provider_succeeds
        else RuntimeError("SYNTHETIC-PROVIDER-PRIVATE")
    )
    client = _Client(response)
    worker = InterruptibleWorker(client, _request())
    original_print = print

    def interrupting_print(*args, **kwargs):
        nonlocal interrupted
        original_print(*args, **kwargs)
        if args and str(args[0]).startswith("[Life Record Worker]"):
            interrupted = True

    monkeypatch.setattr("builtins.print", interrupting_print)

    successes, failures = _run(worker)

    assert successes == []
    assert failures == []


def test_life_record_worker_does_not_mutate_provider_history():
    client = _Client(_one_shot(_valid_output()))
    before = list(client.history)

    _run(LifeRecordWorker(client, _request()))

    assert client.history == before


def test_life_record_worker_request_and_results_hide_sensitive_content(capsys):
    prompt = "SYNTHETIC-PRIVATE-PROMPT"
    activity = "SYNTHETIC-PRIVATE-ACTIVITY"
    request = _request(prompt=prompt)
    client = _Client(_one_shot(_valid_output(activity=activity)))

    successes, _failures = _run(LifeRecordWorker(client, request))
    captured = capsys.readouterr().out

    assert prompt not in repr(request)
    assert prompt not in repr(successes[0][1])
    assert activity not in repr(successes[0][1])
    assert prompt not in captured
    assert activity not in captured


@pytest.mark.parametrize(
    "changes",
    [
        {"operation_id": True},
        {"operation_id": -1},
        {"prompt": ""},
        {"inactive_started_at": START.replace(microsecond=1)},
        {"returned_at": END.replace(microsecond=1)},
        {"timezone": "Invalid/Zone"},
        {"language": "fr"},
    ],
)
def test_life_record_generation_request_rejects_invalid_contract(changes):
    values = {
        "operation_id": 17,
        "prompt": "SYNTHETIC-LIFE-PROMPT",
        "inactive_started_at": START,
        "returned_at": END,
        "timezone": "Asia/Seoul",
        "language": "ko",
    }
    values.update(changes)

    with pytest.raises(ValueError):
        LifeRecordGenerationRequest(**values)
