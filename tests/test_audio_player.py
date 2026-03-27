from src.core.audio_player import AudioPlayer


def test_serialize_device_id_handles_bytes_and_empty_values():
    assert AudioPlayer.serialize_device_id(b"\x01\x02\xfe") == "0102fe"
    assert AudioPlayer.serialize_device_id(bytearray(b"\x0a\x0b")) == "0a0b"
    assert AudioPlayer.serialize_device_id("") == ""
    assert AudioPlayer.serialize_device_id(None) == ""


def test_normalize_volume_clamps_to_valid_range():
    assert AudioPlayer.normalize_volume(-1.0) == 0.0
    assert AudioPlayer.normalize_volume(0.55) == 0.55
    assert AudioPlayer.normalize_volume(3.0) == 1.0


def test_resolve_output_device_matches_serialized_id():
    class FakeDevice:
        def __init__(self, raw_id, name):
            self._raw_id = raw_id
            self._name = name

        def id(self):
            return self._raw_id

        def description(self):
            return self._name

    first = FakeDevice(b"\xaa\xbb", "첫 번째")
    second = FakeDevice(b"\xcc\xdd", "두 번째")

    assert AudioPlayer.resolve_output_device("ccdd", [first, second]) is second
    assert AudioPlayer.resolve_output_device("ffff", [first, second]) is None
    assert AudioPlayer.resolve_output_device("", [first, second]) is None
