"""실제 사진 대신 생성한 단색 픽셀로 업로드 소유권과 상한을 검사한다."""

import importlib
from dataclasses import replace
from hashlib import sha256
from io import BytesIO

from PIL import Image
import pytest

from src.core.companion.extension_protocol import ExtensionContext
from tests.companion_helpers import sample_id


SCOPE = ExtensionContext(1, sample_id(1), sample_id(2), sample_id(3))


def api():
    module = "src.core.companion.input_uploads"
    assert importlib.util.find_spec(module) is not None, "제한된 입력 업로드 저장소가 필요하다"
    return importlib.import_module(module)


def picture(size=(16, 12), format="PNG"):
    output = BytesIO()
    Image.new("RGB", size, (20, 40, 80)).save(output, format)
    return output.getvalue()


def reserve(store, data, number=10, purpose="image"):
    return store.reserve(SCOPE, sample_id(number), purpose, len(data), sha256(data).hexdigest())


def ready(store, data, number=10, purpose="image"):
    key = reserve(store, data, number, purpose)
    store.begin(SCOPE, key, len(data))
    store.append(SCOPE, key, data)
    store.finish(SCOPE, key)
    return key


def descriptor(key, data, mime="image/png"):
    return dict(upload_id=key, byte_length=len(data), sha256=sha256(data).hexdigest(), mime=mime)


def test_reservation_is_idempotent_but_conflicting_body_is_not():
    mod = api()
    store = mod.UploadStore(SCOPE)
    data = picture()
    assert reserve(store, data) == reserve(store, data)
    with pytest.raises(mod.InputError, match="request_conflict"):
        reserve(store, b"different")
    assert store.reserved_bytes == len(data)


def test_only_complete_validated_images_can_be_claimed_once():
    mod = api()
    store = mod.UploadStore(SCOPE)
    data = picture()
    key = reserve(store, data)
    with pytest.raises(mod.InputError, match="upload_not_ready"):
        store.claim(SCOPE, [descriptor(key, data)], "image")
    store.begin(SCOPE, key, len(data))
    for offset in range(0, len(data), 7):
        store.append(SCOPE, key, data[offset:offset + 7])
    store.finish(SCOPE, key)
    result = store.claim(SCOPE, [descriptor(key, data)], "image")
    assert [(item.width, item.height, item.mime, item.body) for item in result] == [(16, 12, "image/png", data)]
    assert store.reserved_bytes == 0
    store.close()
    assert result[0].body == data
    with pytest.raises(mod.InputError):
        store.claim(SCOPE, [descriptor(key, data)], "image")


def test_claim_is_atomic_and_checks_ordered_descriptors():
    mod = api()
    store = mod.UploadStore(SCOPE)
    first, second = picture(), picture((12, 16))
    a, b = ready(store, first), ready(store, second, 11)
    bad = descriptor(b, second) | {"mime": "image/jpeg"}
    with pytest.raises(mod.InputError, match="upload_mismatch"):
        store.claim(SCOPE, [descriptor(a, first), bad], "image")
    result = store.claim(SCOPE, [descriptor(b, second), descriptor(a, first)], "image")
    assert [item.body for item in result] == [second, first]


@pytest.mark.parametrize("change", [dict(registration_generation=2), dict(server_epoch=sample_id(4)),
                                   dict(connection_generation=sample_id(4)), dict(conversation_id=sample_id(4))])
def test_scope_checked_at_every_boundary(change):
    mod = api()
    store = mod.UploadStore(SCOPE)
    data = picture()
    key = reserve(store, data)
    other = replace(SCOPE, **change)
    for operation in (lambda: store.begin(other, key, len(data)), lambda: store.append(other, key, data),
                      lambda: store.finish(other, key), lambda: store.claim(other, [descriptor(key, data)], "image"),
                      lambda: store.cancel(other, key)):
        with pytest.raises(mod.InputError, match="stale_extension"):
            operation()
    assert store.reserved_bytes == len(data)


def test_single_receiver_and_bounded_slot_counts():
    mod = api()
    store = mod.UploadStore(SCOPE)
    data = picture()
    keys = [reserve(store, data, number) for number in range(10, 14)]
    with pytest.raises(mod.InputError, match="input_limit"):
        reserve(store, data, 15)
    pcm = reserve(store, b"\0\0", 20, "pcm")
    with pytest.raises(mod.InputError, match="input_limit"):
        reserve(store, b"\0\0", 21, "pcm")
    store.begin(SCOPE, keys[0], len(data))
    with pytest.raises(mod.InputError, match="upload_busy"):
        store.begin(SCOPE, pcm, 2)
    store.cancel(SCOPE, keys[0])
    store.begin(SCOPE, pcm, 2)


@pytest.mark.parametrize("purpose,length", [("image", 0), ("image", 4194305), ("pcm", 960001), ("pcm", 3)])
def test_rejects_bad_declared_lengths_before_reserving(purpose, length):
    mod = api()
    store = mod.UploadStore(SCOPE)
    with pytest.raises(mod.InputError):
        store.reserve(SCOPE, sample_id(10), purpose, length, "0" * 64)
    assert store.reserved_bytes == 0


@pytest.mark.parametrize("mode", ["short", "long", "hash", "garbage", "oversized_pixels", "animated"])
def test_failed_input_is_disposed(mode):
    mod = api()
    store = mod.UploadStore(SCOPE)
    data = picture((2049, 1)) if mode == "oversized_pixels" else picture()
    if mode == "animated":
        output = BytesIO()
        first = Image.new("RGB", (2, 2), "blue")
        first.save(output, "PNG", save_all=True, append_images=[Image.new("RGB", (2, 2), "red")])
        data = output.getvalue()
    if mode == "garbage":
        data = b"not an image"
    key = reserve(store, data)
    store.begin(SCOPE, key, len(data))
    payload = data[:-1] if mode == "short" else data + b"x" if mode == "long" else bytes(len(data)) if mode == "hash" else data
    with pytest.raises(mod.InputError):
        store.append(SCOPE, key, payload)
        store.finish(SCOPE, key)
    assert store.reserved_bytes == 0


def test_expiry_and_reset_reject_late_completion():
    mod = api()
    now = [0.0]
    store = mod.UploadStore(SCOPE, clock=lambda: now[0])
    data = picture()
    key = reserve(store, data)
    store.begin(SCOPE, key, len(data))
    now[0] = 120.0
    with pytest.raises(mod.InputError, match="upload_not_found"):
        store.append(SCOPE, key, data)
    assert store.reserved_bytes == 0
    key = reserve(store, data, 11)
    store.reset(replace(SCOPE, conversation_id=sample_id(4)))
    with pytest.raises(mod.InputError):
        store.finish(SCOPE, key)
    assert store.reserved_bytes == 0


def test_pcm_is_memory_only_and_even_length():
    store = api().UploadStore(SCOPE)
    data = b"\0\0" * 1600
    key = ready(store, data, purpose="pcm")
    item, = store.claim(SCOPE, [descriptor(key, data, "audio/pcm")], "pcm")
    assert item.body == data and item.mime == "audio/pcm"
