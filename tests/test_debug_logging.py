"""합성 입력만으로 디버그 로그의 저장·격리 경계를 검증한다."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
import requests

from src.core import debug_logging
from src.ai.http_llm_common import _post_with_safe_errors, _raise_for_status_with_detail
from tests.test_life_record_settings_ui import prompt_paths


@pytest.fixture
def debug_log(tmp_path):
    debug_logging.configure_debug_logging({"debug_mode": True}, root=tmp_path)
    yield tmp_path / "log"
    debug_logging.configure_debug_logging({"debug_mode": False}, root=tmp_path)


def records(log_dir):
    return [json.loads(line) for path in log_dir.glob("*.jsonl")
            for line in path.read_text(encoding="utf-8").splitlines()]


def test_disabled_does_not_create_files_or_evaluate_payload(tmp_path):
    debug_logging.configure_debug_logging({"debug_mode": False}, root=tmp_path)
    with debug_logging.debug_request("llm", "demo", "demo-model", lambda: 1 / 0):
        pass
    assert not (tmp_path / "log").exists()


def test_log_directory_uses_executable_folder_for_packaged_app(tmp_path, monkeypatch):
    monkeypatch.setattr(debug_logging.sys, "frozen", True, raising=False)
    monkeypatch.setattr(debug_logging.sys, "executable", str(tmp_path / "ENE.exe"))
    monkeypatch.setattr(debug_logging.sys, "_MEIPASS", str(tmp_path / "unpacked"), raising=False)
    assert debug_logging.get_debug_log_dir() == tmp_path / "log"


def test_log_directory_uses_source_root_independent_of_working_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(debug_logging.sys, "frozen", False, raising=False)
    monkeypatch.setattr(debug_logging, "get_bundle_root", lambda: tmp_path / "source")
    assert debug_logging.get_debug_log_dir() == tmp_path / "source" / "log"


def test_duration_uses_monotonic_clock(debug_log, monkeypatch):
    ticks = iter([10.0, 13.25])
    monkeypatch.setattr(debug_logging, "time", SimpleNamespace(perf_counter=lambda: next(ticks)))
    with debug_logging.debug_request("llm", "demo", "demo-model", {}):
        pass
    assert records(debug_log)[-1]["elapsed_seconds"] == 3.25


def test_credentials_and_binary_are_omitted_but_prompt_is_preserved(debug_log):
    debug_logging.configure_debug_logging(
        {"debug_mode": True, "llm_api_keys": {"demo": "synthetic-credential"}}, root=debug_log.parent,
    )
    payload = {"messages": [{"content": "가상 전문\n두 번째 줄"}], "inline_data": b"binary",
               "api_key": "synthetic-credential", "image_url": "data:image/png;base64,ZmFrZQ=="}
    with pytest.raises(ValueError):
        with debug_logging.debug_request("llm", "demo", "demo-model", payload):
            raise ValueError("합성 실패 synthetic-credential")
    start, end = records(debug_log)
    assert start["request"]["messages"] == payload["messages"]
    combined = json.dumps([start, end], ensure_ascii=False)
    assert "synthetic-credential" not in combined
    assert "ZmFrZQ" not in combined
    assert "합성 실패" in end["error_message"]


def test_full_prompt_timing_and_concurrent_records(debug_log):
    prompt = "합성 문장\n" * 2000
    def run(index):
        with debug_logging.debug_request("llm", "demo", "demo-model", {"prompt": prompt, "index": index}):
            pass
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(run, range(12)))
    events = records(debug_log)
    assert len(events) == 24
    starts = [event for event in events if event["event"] == "request"]
    ends = [event for event in events if event["event"] == "result"]
    assert len({event["request_id"] for event in starts}) == 12
    assert all(event["request"]["prompt"] == prompt for event in starts)
    assert all(event["elapsed_seconds"] >= 0 and event["status"] == "success" for event in ends)
    assert not next(debug_log.glob("*.jsonl")).read_bytes().startswith(b"\xef\xbb\xbf")


def test_disable_stops_inflight_writes(debug_log):
    with debug_logging.debug_request("llm", "demo", "demo-model", {"prompt": "가상 입력"}):
        debug_logging.configure_debug_logging({"debug_mode": False}, root=debug_log.parent)
    assert len(records(debug_log)) == 1


def test_write_failure_does_not_break_generation(tmp_path, capsys):
    (tmp_path / "log").write_text("가상 장애물", encoding="utf-8")
    debug_logging.configure_debug_logging({"debug_mode": True}, root=tmp_path)
    try:
        with debug_logging.debug_request("llm", "demo", "demo-model", {"prompt": "비공개 합성 입력"}):
            result = 42
        assert result == 42
        assert "비공개 합성 입력" not in capsys.readouterr().out
    finally:
        debug_logging.configure_debug_logging({"debug_mode": False}, root=tmp_path)


def test_log_failure_with_closed_console_does_not_break_generation(tmp_path, monkeypatch):
    (tmp_path / "log").write_text("가상 장애물", encoding="utf-8")
    def closed_console(*args, **kwargs):
        raise OSError("가상 콘솔 종료")
    monkeypatch.setattr("builtins.print", closed_console)
    try:
        debug_logging.configure_debug_logging({"debug_mode": True}, root=tmp_path)
        with debug_logging.debug_request("llm", "demo", "demo-model", {}):
            pass
    finally:
        debug_logging.configure_debug_logging({"debug_mode": False}, root=tmp_path)


def test_http_logs_actual_payload_and_original_error(debug_log):
    response = requests.Response()
    response.status_code = 400
    response._content = '{"error":{"message":"합성 원본 오류"}}'.encode("utf-8")
    payload = {"model": "demo-model", "messages": [{"role": "system", "content": "가상 지침"}]}
    returned = _post_with_safe_errors("openai", "https://example.invalid", lambda *a, **k: response,
                                     json=payload, headers={"Authorization": "Bearer synthetic-key"})
    with pytest.raises(requests.HTTPError, match="category=http_error"):
        _raise_for_status_with_detail(returned, "openai")
    start, end = records(debug_log)
    assert start["request"] == payload
    assert start["model"] == "demo-model"
    assert end["status"] == "error"
    assert "합성 원본 오류" in end["error_body"]
    assert "synthetic-key" not in json.dumps([start, end])


def test_http_network_failure_is_logged_before_sanitizing(debug_log):
    def fail(*args, **kwargs):
        raise requests.Timeout("가상 네트워크 원본 오류")
    with pytest.raises(requests.Timeout, match="category=network_error"):
        _post_with_safe_errors("openai", "https://example.invalid", fail, json={"model": "demo"})
    end = records(debug_log)[-1]
    assert end["error_message"] == "가상 네트워크 원본 오류"
    assert "Timeout" in end["traceback"]


def test_http_debug_body_failure_does_not_replace_provider_error(debug_log):
    class Response:
        status_code = 500
        @property
        def text(self):
            raise OSError("가상 본문 읽기 오류")
    response = Response()
    assert _post_with_safe_errors("demo", "https://example.invalid", lambda *a, **k: response) is response


def test_google_http_model_is_recorded_without_forwarding_debug_argument(debug_log, monkeypatch, prompt_paths):
    from src.ai.http_llm_clients import GoogleCloudClient
    from src.ai.response_protocol import LLMRequestKind
    calls = []
    def post(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status_code=200, raise_for_status=lambda: None,
            json=lambda: {"candidates": [{"content": {"parts": [{"text": "가상 답변"}]}}]})
    monkeypatch.setattr("requests.post", post)
    client = GoogleCloudClient(api_key="synthetic-key", model_name="demo-google-model", endpoint="https://example.invalid")
    client._request_one_shot_raw("가상 입력", request_kind=LLMRequestKind.SUMMARY, include_sub_prompt=False)
    assert records(debug_log)[0]["model"] == "demo-google-model"
    assert "debug_model" not in calls[0]


def test_gemini_records_system_history_and_current_input(debug_log, gemini_harness, prompt_paths):
    client = gemini_harness.client([], repair_responses=["가상 생성 결과"], history=[
        {"role": "user", "parts": [{"text": "가상 이전 입력"}]},
        {"role": "model", "parts": [{"text": "가상 이전 답변"}]},
    ])
    from src.ai.response_protocol import LLMRequestKind
    client._generate_one_shot_text("가상 단발 입력", request_kind=LLMRequestKind.SUMMARY, include_sub_prompt=False)
    start = records(debug_log)[0]
    assert start["request"]["contents"] == "가상 단발 입력"
    assert start["request"]["config"]["system_instruction"]
    client.client.chat_responses.append(gemini_harness.response("가상 채팅 결과"))
    client._send_chat_message("가상 현재 입력")
    start = records(debug_log)[2]
    assert "가상 이전 입력" in json.dumps(start, ensure_ascii=False)
    assert start["request"]["contents"] == "가상 현재 입력"
    assert start["request"]["config"]["system_instruction"]


def test_tts_records_model_duration_and_raw_fish_error(debug_log, monkeypatch):
    from src.ai.tts_client import create_tts_client
    class Response:
        status = 422
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def text(self): return "가상 음성 오류 원문"
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        def post(self, *args, **kwargs): return Response()
    monkeypatch.setattr("src.ai.tts_client.aiohttp.ClientSession", Session)
    client = create_tts_client("fish_audio", {"model": "demo-tts"}, api_key="synthetic-key")
    with pytest.raises(RuntimeError, match="Fish Audio 오류"):
        asyncio.run(client.generate_speech("가상 음성 입력"))
    start, end = records(debug_log)
    assert start["model"] == "demo-tts"
    assert start["request"]["text"] == "가상 음성 입력"
    assert end["elapsed_seconds"] >= 0
    assert end["error_body"] == "가상 음성 오류 원문"
    assert end["status"] == "error"


@pytest.mark.parametrize("outcome", ["success", "error", "cancelled", "cancelled_other_task"])
def test_tts_stream_records_completion_error_and_cancellation(debug_log, monkeypatch, outcome):
    from src.ai.tts_client import create_tts_client
    class Content:
        async def iter_chunked(self, size):
            yield b"first"
            if outcome == "error":
                raise RuntimeError("가상 스트리밍 원본 오류")
            yield b"last"
    class Response:
        status = 200
        content = Content()
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        def post(self, *args, **kwargs): return Response()
    monkeypatch.setattr("src.ai.tts_client.aiohttp.ClientSession", Session)
    client = create_tts_client("gpt_sovits_http", {})
    monkeypatch.setattr(client, "_build_request_payload", lambda text: {"text": text})
    async def run():
        stream = client.stream_speech("가상 스트리밍 입력")
        assert await anext(stream) == b"first"
        if outcome == "cancelled_other_task":
            await asyncio.create_task(stream.aclose())
        elif outcome == "cancelled":
            await stream.aclose()
        elif outcome == "error":
            with pytest.raises(RuntimeError, match="가상 스트리밍 원본 오류"):
                await anext(stream)
        else:
            assert await anext(stream) == b"last"
            with pytest.raises(StopAsyncIteration):
                await anext(stream)
    asyncio.run(run())
    start, end = records(debug_log)
    assert start["request"]["streaming"] is True
    assert start["model"] is None
    assert end["status"] == ("cancelled" if outcome.startswith("cancelled") else outcome)
    if outcome == "error":
        assert end["error_message"] == "가상 스트리밍 원본 오류"


def test_async_gemini_preserves_original_error(debug_log, gemini_harness, prompt_paths):
    client = gemini_harness.client([])
    async def fail(**kwargs):
        raise RuntimeError("가상 비동기 원본 오류")
    client.client.aio = SimpleNamespace(models=SimpleNamespace(generate_content=fail))
    with pytest.raises(RuntimeError, match="life_record_generation_failed"):
        asyncio.run(client.generate_life_record_once("가상 생활 생성 입력"))
    start, end = records(debug_log)
    assert start["request"]["contents"] == "가상 생활 생성 입력"
    assert end["error_message"] == "가상 비동기 원본 오류"


def test_debug_settings_toggle_roundtrip(prompt_paths, monkeypatch):
    from tests.test_life_record_settings_ui import _dialog
    from src.core.settings import Settings
    assert Settings.DEFAULT_CONFIG["debug_mode"] is False
    dialog = _dialog(prompt_paths, monkeypatch)
    assert dialog.debug_mode_check.isChecked() is False
    dialog.debug_mode_check.setChecked(True)
    values = dialog._get_current_values()
    dialog.close()
    reopened = _dialog(prompt_paths, monkeypatch, values)
    assert reopened.debug_mode_check.isChecked() is True
    assert reopened.debug_mode_check.text() == "디버그 로그 저장"
    reopened.close()


def test_application_applies_logging_after_save_and_stops_after_disable(tmp_path, monkeypatch):
    from src.core.app import ENEApplication
    from src.core.settings import Settings
    monkeypatch.setattr(debug_logging, "get_debug_log_dir", lambda: tmp_path / "log")
    settings = Settings(config_path=str(tmp_path / "synthetic-config.json"),
                        secret_path=str(tmp_path / "synthetic-secrets.json"))
    debug_logging.configure_debug_logging(settings)
    app = ENEApplication.__new__(ENEApplication)
    app.settings = settings
    app.global_ptt = None
    def apply(values):
        settings.update(values)
        settings.save()
    app.overlay_window = SimpleNamespace(
        bridge=SimpleNamespace(enable_tts=False), apply_new_settings=apply,
        preview_settings=lambda _: None, restore_settings=lambda: None,
    )
    try:
        app._on_settings_preview({"debug_mode": True})
        assert not (tmp_path / "log").exists()
        assert app._on_settings_changed({"debug_mode": True})["status"] == "accepted"
        assert (tmp_path / "log").is_dir()
        assert json.loads(settings.config_path.read_text(encoding="utf-8"))["debug_mode"] is True
        with debug_logging.debug_request("llm", "demo", "demo-model", {}):
            pass
        assert len(records(tmp_path / "log")) == 2
        app._on_settings_changed({"debug_mode": False})
        with debug_logging.debug_request("llm", "demo", "demo-model", {}):
            pass
        assert len(records(tmp_path / "log")) == 2
    finally:
        debug_logging.configure_debug_logging({"debug_mode": False})
