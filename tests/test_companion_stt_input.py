"""가상 PCM만 사용해 모바일 STT의 스냅샷·취소 경계를 검증한다."""
import asyncio
from hashlib import sha256
import threading
from types import SimpleNamespace

from src.core.companion.extension_protocol import ExtensionContext
from src.core.companion.input_uploads import UploadStore
from src.core.companion.protocol import decode_message, encode_message
from src.core.companion.stt_input import SttInput
from src.core.stt_service import SharedSttService, SttSettings
from tests.companion_helpers import sample_id


def run_case(operation):
    async def run():
        context = ExtensionContext(1, sample_id(1), sample_id(2), sample_id(3))
        emitted = []
        settings = [SttSettings(language="ko")]
        async def call(name, _):
            assert name == "stt_settings"
            return settings[0], 100, 1000, "ready"
        session = SimpleNamespace(extension_context=context, context=object(), synced=True,
            uploads=UploadStore(context), adapter=SimpleNamespace(call=call),
            queue=lambda value, **_: emitted.append(decode_message(encode_message(value)).to_dict()))
        def message(kind, **fields):
            return decode_message(encode_message(dict(type=kind, protocol_version=1,
                registration_generation=1, server_epoch=context.server_epoch, connection_generation=context.connection_generation,
                conversation_id=context.conversation_id, command_id=sample_id(5), **fields)))
        def upload():
            body = b"\0\0" * 1600
            digest = sha256(body).hexdigest()
            key = session.uploads.reserve(context, sample_id(6), "pcm", len(body), digest)
            session.uploads.begin(context, key, len(body)); session.uploads.append(context, key, body); session.uploads.finish(context, key)
            return dict(upload_id=key, sha256=digest, byte_length=len(body))
        await operation(session, emitted, settings, message, upload)
    asyncio.run(run())


def test_begin_captures_settings_and_result_never_creates_chat():
    async def operation(session, emitted, settings, message, upload):
        seen = []
        service = SharedSttService(SimpleNamespace(configure=lambda **value: seen.append(value), transcribe_pcm16=lambda _: "합성 인식 결과"))
        boundary = SttInput(session, service)
        await boundary.receive(message("stt_begin"))
        settings[0] = SttSettings(language="ja")
        await boundary.receive(message("stt_transcribe", **upload()))
        await boundary.task
        assert seen[0]["language"] == "ko"
        assert [item["type"] for item in emitted] == ["stt_ready", "stt_result"]
        assert emitted[-1]["text"] == "합성 인식 결과"
        assert session.uploads.reserved_bytes == 0
    run_case(operation)


def test_cancel_discards_late_result_but_keeps_engine_busy_until_real_exit():
    async def operation(session, emitted, settings, message, upload):
        started, finish = threading.Event(), threading.Event()
        def recognize(_):
            started.set()
            assert finish.wait(3)
            return "늦은 합성 결과"
        service = SharedSttService(SimpleNamespace(configure=lambda **_: None, transcribe_pcm16=recognize))
        boundary = SttInput(session, service)
        await boundary.receive(message("stt_begin"))
        await boundary.receive(message("stt_transcribe", **upload()))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            boundary.cancel()
            await asyncio.sleep(.01)
            assert service.busy
            assert not any(item["type"] == "stt_result" for item in emitted)
        finally:
            finish.set()
        for _ in range(100):
            if not service.busy:
                break
            await asyncio.sleep(.01)
        assert not service.busy
        assert not any(item["type"] == "stt_result" for item in emitted)
    run_case(operation)


def test_recording_scope_change_blocks_result():
    async def operation(session, emitted, settings, message, upload):
        service = SharedSttService(SimpleNamespace(configure=lambda **_: None, transcribe_pcm16=lambda _: "가상 결과"))
        boundary = SttInput(session, service)
        await boundary.receive(message("stt_begin"))
        await boundary.receive(message("stt_transcribe", **upload()))
        session.extension_context = ExtensionContext(2, sample_id(1), sample_id(2), sample_id(3))
        await boundary.task
        assert len(emitted) == 1
    run_case(operation)
