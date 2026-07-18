from __future__ import annotations

import json

import requests

from tests.structured_response_fixtures import valid_envelope_json


class DummyHTTPResponse:
    def __init__(self, body=None, *, status_code: int = 200, text: str = ""):
        self._body = body if body is not None else {}
        self.status_code = status_code
        self.text = text or json.dumps(self._body, ensure_ascii=False)

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"synthetic HTTP {self.status_code}",
                response=self,
            )


def structured_settings(**overrides) -> dict:
    values = {
        "ui_language": "ko",
        "prompt_language": "ko",
        "tts_language": "ko",
        "structured_response_mode": "auto",
        "enable_response_analysis": False,
        "enable_schedule_recognition": False,
        "enable_conversation_promises": False,
        "enable_ene_goals": False,
        "enable_ene_thoughts": False,
        "enable_proactive_conversation": False,
        "enable_synthetic_gestures": False,
    }
    values.update(overrides)
    return values


def native_final_reply(reply: str = "검증된 합성 표시 답변") -> str:
    return valid_envelope_json(reply=reply)


def legacy_final_reply(reply: str = "검증된 합성 표시 답변") -> str:
    return (
        "[analysis]\nuser_intent=synthetic\n[/analysis]\n"
        f"{reply} [normal]"
    )


def install_client_request_sequence(monkeypatch, client, method_name, outcomes):
    records = []
    queue = list(outcomes)

    def fake_request(*_args, request_descriptor=None, **_kwargs):
        records.append(request_descriptor)
        outcome = queue.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(client, method_name, fake_request)
    return records


def explicit_unsupported_error() -> requests.HTTPError:
    response = DummyHTTPResponse(
        status_code=400,
        text=json.dumps(
            {"error": {"message": "Unknown parameter: response_format"}}
        ),
    )
    return requests.HTTPError("synthetic unsupported", response=response)
