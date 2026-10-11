"""가상 PCM과 엔진으로 STT 동시성·설정 격리를 검증한다."""
import threading
from types import SimpleNamespace

import pytest

from src.core.stt_service import SharedSttService, SttBusy, SttSettings


def test_worker_owns_inference_until_lazy_segments_finish():
    entered, finish = threading.Event(), threading.Event()

    class Engine:
        def configure(self, **_kwargs):
            pass

        def transcribe_pcm16(self, _data):
            entered.set()
            assert finish.wait(3)
            return "가상의 인식 결과"

    service = SharedSttService(Engine())
    results = []
    worker = threading.Thread(target=lambda: results.append(service.transcribe_pcm16(b"\0\0")))
    worker.start()
    try:
        assert entered.wait(2)
        assert service.busy
        with pytest.raises(SttBusy):
            service.transcribe_pcm16(b"\0\0")
        service.configure("base", "cpu", "int8", "en")
        assert service.busy
    finally:
        finish.set()
        worker.join(3)
    assert results == ["가상의 인식 결과"]
    assert not service.busy


def test_mobile_snapshot_does_not_change_pc_configuration():
    seen = []
    engine = SimpleNamespace(configure=lambda **values: seen.append(values), transcribe_pcm16=lambda _: "")
    service = SharedSttService(engine)
    service.configure("small", "cpu", "int8", "ko")
    service.transcribe_pcm16(b"\0\0", SttSettings("tiny", "cpu", "int8", "ja"))
    service.transcribe_pcm16(b"\0\0")
    assert [item["language"] for item in seen] == ["ja", "ko"]


def test_shorter_pc_limit_and_invalid_settings_are_bounded():
    from src.core.stt_service import recording_limits

    assert recording_limits({"stt_max_record_sec": 2, "stt_min_record_sec": .5}) == (500, 2000)
    assert recording_limits({"stt_max_record_sec": 500}) == (250, 30000)
    assert recording_limits({"stt_min_record_sec": 3, "stt_max_record_sec": 1}) == (1000, 1000)
