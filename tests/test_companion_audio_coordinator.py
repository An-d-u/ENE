"""가상 출력과 합성 음성으로 발화별 단일 출력·한 번의 완료를 검증한다."""

from dataclasses import replace

import pytest

from src.core.companion.audio_buffer import PcmFormat, WavSource
from src.core.companion.audio_coordinator import AudioCoordinator, AudioRef
from src.core.companion.extension_protocol import ExtensionContext
from src.core.companion.protocol import decode_message, encode_message
from tests.companion_helpers import sample_id
from tests.test_companion_audio_buffer import wav


class Transport:
    def __init__(self):
        self.events = []
        self.source = None
        self.succeed = True

    def offer(self, message, source):
        self.events.append(message.to_dict())
        self.source = source
        return self.succeed

    def send(self, message):
        self.events.append(message.to_dict())
        return self.succeed

    def notify(self, ref):
        pass

    def cancel(self, ref):
        pass


class Sink:
    def __init__(self):
        self.waves, self.formats, self.chunks, self.ends = [], [], [], 0

    def play(self, data):
        self.waves.append(data)

    def start(self, format):
        self.formats.append(format)

    def write(self, data):
        self.chunks.append(data)

    def finish(self):
        self.ends += 1


@pytest.fixture
def setup():
    ref = AudioRef(
        1,
        sample_id(1),
        sample_id(2),
        sample_id(3),
        sample_id(4),
        sample_id(5),
        sample_id(6),
    )
    transport, sink, completed = Transport(), Sink(), []
    now = [0]
    coordinator = AudioCoordinator(
        transport,
        sink,
        lambda ref, reason: completed.append((ref, reason)),
        now_ms=lambda: now[0],
    )
    context = ExtensionContext(1, sample_id(1), sample_id(2), sample_id(3))
    coordinator.availability(context, True)
    return coordinator, ref, transport, sink, completed, now


def command(ref, kind, **fields):
    return decode_message(
        encode_message(
            {**ref.to_fields(), "type": kind, "protocol_version": 1, **fields}
        )
    )


def prepare(coordinator, ref):
    return coordinator.receive(command(ref, "audio_prepared", buffered_frames=4800))


def test_complete_ten_second_wave_is_not_pushed_into_four_second_queue(setup):
    coordinator, ref, transport, sink, completed, _ = setup
    raw = wav(b"\x00\x00" * 24000 * 10)
    assert coordinator.begin_wave(ref, WavSource(raw))
    assert prepare(coordinator, ref) is None
    assert transport.source.raw is raw
    assert sink.waves == [] and sink.formats == []
    assert coordinator.target == "phone"
    assert (
        coordinator.receive(command(ref, "audio_finished", played_frames=240000))
        is None
    )
    assert completed == [(ref, "finished")]


def test_wav_rejection_reuses_original_bytes_without_generating_again(setup):
    coordinator, ref, _, sink, completed, _ = setup
    raw = wav()
    assert coordinator.begin_wave(ref, WavSource(raw))
    coordinator.receive(command(ref, "audio_rejected", reason="focus_denied"))
    assert sink.waves == [raw] and sink.waves[0] is raw
    assert completed == [(ref, "pc_fallback")]
    coordinator.receive(command(ref, "audio_rejected", reason="focus_denied"))
    assert len(sink.waves) == len(completed) == 1


def test_first_pcm_starts_prepare_timeout_not_format_notification(setup):
    coordinator, ref, transport, sink, completed, now = setup
    assert coordinator.begin_stream(ref, PcmFormat(24000, 1))
    now[0] = 7000
    coordinator.tick()
    assert transport.events == []
    coordinator.offer_pcm(ref, b"\x00\x00" * 4800)
    assert transport.events[0]["type"] == "audio_offer"
    now[0] = 8999
    coordinator.tick()
    assert completed == []
    now[0] = 9000
    coordinator.tick()
    assert len(sink.formats) == 1 and len(sink.chunks) == 1
    assert completed == [(ref, "pc_fallback")]


def test_prefix_overflow_before_commit_falls_back_once_with_current_chunk(setup):
    coordinator, ref, _, sink, completed, _ = setup
    coordinator.begin_stream(ref, PcmFormat(8000, 1))
    chunks = [bytes([number, 0]) * 16000 for number in (1, 2, 3)]
    for chunk in chunks:
        coordinator.offer_pcm(ref, chunk)
    assert sink.chunks == chunks and len(sink.formats) == 1
    assert completed == [(ref, "pc_fallback")]


def test_overflow_after_start_permission_never_replays_on_pc(setup):
    coordinator, ref, transport, sink, completed, _ = setup
    coordinator.begin_stream(ref, PcmFormat(8000, 1))
    coordinator.offer_pcm(ref, b"\x00" * 32000)
    coordinator.receive(command(ref, "audio_prepared", buffered_frames=1600))
    coordinator.offer_pcm(ref, b"\x00" * 32000)
    coordinator.offer_pcm(ref, b"\x00\x00")
    assert sink.chunks == sink.waves == []
    assert completed == [(ref, "buffer_full")]
    assert transport.events[-1]["type"] == "audio_cancel"


def test_start_send_failure_is_committed_before_send_and_only_cancels(setup):
    coordinator, ref, transport, sink, completed, _ = setup
    coordinator.begin_wave(ref, WavSource(wav()))
    observed = []

    def send(message):
        if message.type == "audio_start":
            observed.append(coordinator.target)
            return False
        return True

    transport.send = send
    prepare(coordinator, ref)
    assert observed == ["phone"]
    assert sink.waves == [] and completed == [(ref, "delivery_failed")]


def test_source_finish_does_not_release_gate_before_phone_drains(setup):
    coordinator, ref, _, _, completed, _ = setup
    coordinator.begin_stream(ref, PcmFormat(24000, 1))
    coordinator.offer_pcm(ref, b"\x00\x00" * 4800)
    prepare(coordinator, ref)
    coordinator.source_end(ref)
    assert completed == []
    ack = coordinator.receive(
        command(ref, "audio_progress", played_frames=4800, mouth_open=0.5)
    )
    assert ack.type == "audio_progress_ack" and ack.fields["played_frames"] == 4800
    coordinator.receive(command(ref, "audio_finished", played_frames=4800))
    coordinator.source_end(ref)
    coordinator.cancel(ref, "interrupted")
    assert completed == [(ref, "finished")]


def test_old_ref_or_connection_does_not_complete_current_audio(setup):
    coordinator, ref, _, _, completed, _ = setup
    coordinator.begin_wave(ref, WavSource(wav()))
    prepare(coordinator, ref)
    coordinator.receive(
        command(
            replace(ref, utterance_id=sample_id(99)),
            "audio_finished",
            played_frames=100,
        )
    )
    coordinator.receive(
        command(
            replace(ref, connection_generation=sample_id(99)),
            "audio_finished",
            played_frames=100,
        )
    )
    assert completed == []


@pytest.mark.parametrize("visible,available", [(False, True), (True, False)])
def test_unpublished_or_unavailable_utterance_stays_with_existing_pc_path(
    setup, visible, available
):
    coordinator, ref, transport, sink, completed, _ = setup
    coordinator.availability(
        ExtensionContext(
            1, ref.server_epoch, ref.connection_generation, ref.conversation_id
        ),
        available,
    )
    assert not coordinator.begin_wave(ref, WavSource(wav()), visible=visible)
    assert transport.events == [] and sink.waves == [] and completed == []


def test_disconnect_while_offered_preserves_prefix_for_pc(setup):
    coordinator, ref, transport, sink, completed, _ = setup
    coordinator.begin_stream(ref, PcmFormat(24000, 1))
    data = b"\x01\x00" * 4800
    coordinator.offer_pcm(ref, data)
    transport.source.cancel_transfer()
    coordinator.disconnected()
    assert sink.chunks == [data]
    assert completed == [(ref, "pc_fallback")]
    assert transport.source.buffered_bytes == 0


def test_connection_resources_preserve_uncommitted_prefix_for_owner(setup):
    from src.core.companion.connection_resources import ConnectionResources

    coordinator, ref, transport, sink, _, _ = setup
    coordinator.begin_stream(ref, PcmFormat(24000, 1))
    data = b"\x01\x00" * 4800
    coordinator.offer_pcm(ref, data)
    resources = ConnectionResources()
    resources.add_audio(ref.utterance_id, transport.source)
    resources.cancel()
    coordinator.disconnected()
    assert sink.chunks == [data]
