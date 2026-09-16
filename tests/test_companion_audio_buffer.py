"""직접 만든 PCM/WAV만 사용해 정렬·크기·단일 바이트 소유권을 확인한다."""

import io
import struct
import wave

import pytest

from src.core.companion.audio_buffer import (
    AudioBufferError,
    PcmFormat,
    PcmStream,
    WavSource,
)


def wav(pcm=b"\x00\x00" * 100, rate=24000, channels=1, width=2):
    out = io.BytesIO()
    with wave.open(out, "wb") as writer:
        writer.setparams((channels, width, rate, 0, "NONE", ""))
        writer.writeframes(pcm)
    return out.getvalue()


@pytest.mark.parametrize("rate", [8000, 48000])
@pytest.mark.parametrize("channels", [1, 2])
def test_complete_wav_retains_original_and_reads_aligned_views(rate, channels):
    raw = wav(b"\x12\x34" * channels * rate * 10, rate, channels)
    source = WavSource(raw)
    assert source.raw is raw
    assert source.format == PcmFormat(rate, channels)
    assert source.total_frames == rate * 10
    total = 0
    while chunk := source.peek(32768):
        assert isinstance(chunk, memoryview) and chunk.obj is raw
        assert len(chunk) <= 32768 and len(chunk) % (channels * 2) == 0
        source.consume(len(chunk))
        total += len(chunk)
    assert total == source.total_frames * channels * 2


def test_unknown_chunk_with_odd_padding_is_skipped():
    raw = wav()
    body = raw[8:12] + b"JUNK" + struct.pack("<I", 3) + b"abc\x00" + raw[12:]
    source = WavSource(b"RIFF" + struct.pack("<I", len(body)) + body)
    assert bytes(source.peek()) == b"\x00\x00" * 100


@pytest.mark.parametrize(
    "raw",
    [b"bad", wav()[:-1], wav() + b"x", wav(width=1), wav(rate=7999), wav(channels=3)],
)
def test_invalid_or_unsupported_wav_is_not_exposed(raw):
    with pytest.raises(AudioBufferError):
        WavSource(raw)


def test_non_pcm_and_truncated_frame_are_rejected():
    raw = bytearray(wav())
    raw[20:22] = struct.pack("<H", 3)
    with pytest.raises(AudioBufferError):
        WavSource(bytes(raw))
    raw = wav(b"\x00\x00\x00", channels=2)
    with pytest.raises(AudioBufferError):
        WavSource(raw)


@pytest.mark.parametrize(
    "offset,fmt,value", [(34, "<H", 15), (32, "<H", 1), (28, "<I", 1)]
)
def test_inconsistent_pcm_format_fields_are_rejected(offset, fmt, value):
    raw = bytearray(wav())
    struct.pack_into(fmt, raw, offset, value)
    with pytest.raises(AudioBufferError):
        WavSource(bytes(raw))


def test_source_duration_and_original_bytes_are_bounded():
    with pytest.raises(AudioBufferError):
        WavSource(wav(b"\x00\x00" * (8000 * 180 + 1), rate=8000))
    with pytest.raises(AudioBufferError):
        WavSource(b"\x00" * (36 * 1024 * 1024 + 1))


def test_prefix_and_pending_http_bytes_share_one_limit():
    stream = PcmStream(PcmFormat(8000, 1))
    first, second = b"\x01\x00" * 16000, b"\x02\x00" * 16000
    assert stream.offer(first) == "accepted"
    assert stream.peek().obj is first
    stream.consume(len(first))
    assert stream.buffered_bytes == len(first)
    assert stream.offer(second) == "accepted"
    assert stream.buffered_bytes == stream.format.buffer_limit == 64000
    assert stream.offer(b"\x00\x00") == "full"
    prefix = stream.take_for_pc()
    assert prefix == (first, second) and prefix[0] is first
    assert stream.buffered_bytes == 0
    assert stream.offer(b"\x00\x00") == "closed"


def test_commit_releases_only_consumed_prefix_and_does_not_copy():
    stream = PcmStream(PcmFormat(24000, 2))
    data = b"\x01\x00\x02\x00" * 100
    stream.offer(data)
    stream.consume(40)
    stream.commit()
    assert stream.buffered_bytes == len(data)
    assert stream.peek().obj is data
    assert len(stream.peek()) == len(data) - 40
    stream.consume(len(data) - 40)
    assert stream.buffered_bytes == 0
    assert stream.take_for_pc() == ()


def test_queue_is_bounded_even_for_tiny_chunks_and_closes_cleanly():
    stream = PcmStream(PcmFormat(48000, 1))
    for _ in range(256):
        assert stream.offer(b"\x00\x00") == "accepted"
    assert stream.offer(b"\x00\x00") == "full"
    assert stream.offer(b"\x00") == "invalid"
    assert stream.offer(b"\x00" * 32770) == "invalid"
    stream.finish()
    assert stream.offer(b"\x00\x00") == "closed"
    stream.close()
    assert stream.peek() is None and stream.buffered_bytes == 0


def test_invalid_consume_never_skips_bytes():
    stream = PcmStream(PcmFormat(8000, 2))
    stream.offer(b"\x00" * 8)
    for count in (1, -4, 12):
        with pytest.raises(AudioBufferError):
            stream.consume(count)
    assert len(stream.peek()) == 8


def test_stream_total_duration_remains_bounded_after_drain():
    stream = PcmStream(PcmFormat(8000, 1))
    stream.commit()
    for _ in range(90):
        assert stream.offer(b"\x00" * 32000) == "accepted"
        stream.consume(32000)
    assert stream.offer(b"\x00\x00") == "invalid"
