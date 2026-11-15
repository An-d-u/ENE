"""합성 JPEG로 모바일 카메라 업로드의 세대, 렌즈 전환, 수명 경계를 검증한다."""

import asyncio
from hashlib import sha256
from io import BytesIO

from PIL import Image
import pytest

from src.core.companion.extension_protocol import ExtensionContext
from src.core.companion.input_uploads import InputError, UploadStore
from tests.companion_helpers import sample_id
from tests.test_companion_gateway import harness
from tests.test_companion_media_http import media_connection
from src.core.companion.protocol import decode_message, encode_message


SCOPE = ExtensionContext(1, sample_id(500), sample_id(501), sample_id(502))


def picture(fmt="JPEG", size=(16, 12)):
    output = BytesIO()
    Image.new("RGB", size, (40, 60, 80)).save(output, format=fmt)
    return output.getvalue()


def reserve(store, generation, data):
    return store.reserve(SCOPE, sample_id(503), "camera", len(data), sha256(data).hexdigest(),
                         generation=generation)


def upload(store, generation, data):
    key = reserve(store, generation, data)
    store.begin(SCOPE, key, len(data))
    store.append(SCOPE, key, data)
    store.finish(SCOPE, key)
    return dict(upload_id=key, byte_length=len(data), sha256=sha256(data).hexdigest(), mime="image/jpeg")


def test_camera_needs_current_opt_in_and_cannot_be_claimed_as_photo():
    store = UploadStore(SCOPE)
    data = picture()
    with pytest.raises(InputError):
        reserve(store, 1, data)
    store.configure_camera(SCOPE, 1, question=True, observe=False)
    store.camera_availability(SCOPE, 1, available=True, observe_allowed=False)
    frame = upload(store, 1, data)
    assert store.camera_current(SCOPE, 1, "question")
    assert not store.camera_current(SCOPE, 1, "observe")
    with pytest.raises(InputError):
        store.claim(SCOPE, [frame], "image")
    assert store.claim(SCOPE, [frame], "camera", generation=1)[0].body == data
    with pytest.raises(InputError):
        store.claim(SCOPE, [frame], "camera", generation=1)


def test_switch_turnoff_disconnect_and_reset_invalidate_frames():
    store = UploadStore(SCOPE)
    data = picture()
    store.configure_camera(SCOPE, 1, question=True, observe=True)
    store.camera_availability(SCOPE, 1, available=True, observe_allowed=True)
    key = reserve(store, 1, data)
    store.begin(SCOPE, key, len(data))
    store.configure_camera(SCOPE, 2, question=True, observe=True)
    store.camera_availability(SCOPE, 2, available=True, observe_allowed=True)
    assert not store.camera_current(SCOPE, 1, "question")
    with pytest.raises(InputError):
        store.append(SCOPE, key, data)
    frame = upload(store, 2, data)
    with pytest.raises(InputError):
        store.configure_camera(SCOPE, 1, question=True, observe=True)
    assert not store.camera_current(SCOPE, 1, "observe")
    store.configure_camera(SCOPE, 3, question=False, observe=False)
    assert store.reserved_bytes == 0
    with pytest.raises(InputError):
        store.claim(SCOPE, [frame], "camera", generation=3)
    with pytest.raises(InputError):
        reserve(store, 3, data)
    store.reset(SCOPE)
    store.configure_camera(SCOPE, 1, question=False, observe=True)
    store.camera_availability(SCOPE, 1, available=True, observe_allowed=True)
    assert store.camera_current(SCOPE, 1, "observe")
    store.close()
    assert not store.camera_current(SCOPE, 1, "observe")


@pytest.mark.parametrize("fmt,size", [("PNG", (8, 12)), ("JPEG", (1281, 10)), ("JPEG", (721, 721))])
def test_camera_rejects_other_formats_and_oversize_frames(fmt, size):
    store = UploadStore(SCOPE)
    store.configure_camera(SCOPE, 1, question=True, observe=False)
    store.camera_availability(SCOPE, 1, available=True, observe_allowed=False)
    with pytest.raises(InputError):
        upload(store, 1, picture(fmt, size))
    assert store.reserved_bytes == 0


def test_delayed_frame_cannot_be_observed_after_pc_takes_and_returns_ownership():
    store = UploadStore(SCOPE)
    data = picture()
    store.configure_camera(SCOPE, 2, question=True, observe=True)
    with pytest.raises(InputError):
        reserve(store, 2, data)
    store.camera_availability(SCOPE, 2, available=True, observe_allowed=True)
    old = upload(store, 2, data)
    store.camera_availability(SCOPE, 2, available=True, observe_allowed=False)
    store.camera_availability(SCOPE, 2, available=True, observe_allowed=True)
    with pytest.raises(InputError):
        store.claim(SCOPE, [old], "camera", generation=2, mode="observe")
    assert store.claim(SCOPE, [old], "camera", generation=2, mode="question")[0].body == data
    store.configure_camera(SCOPE, 3, question=False, observe=True)
    store.camera_availability(SCOPE, 3, available=True, observe_allowed=False)
    with pytest.raises(InputError):
        reserve(store, 3, data)
    store.camera_availability(SCOPE, 3, available=True, observe_allowed=True)
    reserve(store, 3, data)
    store.camera_availability(SCOPE, 3, available=False, observe_allowed=False)
    assert store.reserved_bytes == 0
    store.camera_availability(SCOPE, 3, available=True, observe_allowed=True)
    with pytest.raises(InputError):
        reserve(store, 3, data)
    store.configure_camera(SCOPE, 4, question=False, observe=True)
    store.camera_availability(SCOPE, 4, available=True, observe_allowed=True)
    assert reserve(store, 4, data)


def test_camera_transport_binds_slot_to_connection_and_releases_unused_input(tmp_path):
    async def scenario():
        async with harness(tmp_path, capabilities=("camera_v1",)) as (gateway, client, base, token, port, _):
            original = port.call
            observed = []
            started, resume = asyncio.Event(), asyncio.Event()

            async def call(operation, context, *, message=None, **options):
                if operation != "extension" or not message.type.startswith("camera_"):
                    return await original(operation, context, message=message, **options)
                fields = message.fields
                if message.type == "camera_share":
                    state = {key: fields[key] for key in ("registration_generation", "server_epoch",
                             "conversation_id", "connection_generation", "generation")}
                    return decode_message(encode_message(dict(type="camera_state", protocol_version=1, **state,
                        available=True, observe_allowed=fields["observe"], remote=False, model="local-demo")))
                store = options["input_store"]
                started.set()
                await asyncio.wait_for(resume.wait(), 3)
                # UI 판단이 지연된 사이 휴대폰에서 공유 종료를 누른 상황이다.
                observed.append(store.camera_current(store.context, fields["generation"], "observe"))
                return None

            port.call = call
            ws, ready, ext, headers = await media_connection(client, base, token, ("camera_v1",))
            envelope = {key: ext[key] for key in ("protocol_version", "registration_generation",
                                                  "server_epoch", "connection_generation")}
            envelope["conversation_id"] = ready["conversation_id"]
            share = dict(**envelope, type="camera_share", generation=2, question=True, observe=True, lens="front")
            await ws.send_json(share)
            assert (await ws.receive_json(timeout=3))["type"] == "camera_state"
            data = picture()
            digest = sha256(data).hexdigest()
            await ws.send_json(dict(**envelope, type="input_reserve", generation=2,
                purpose="camera", command_id=sample_id(510), byte_length=len(data), sha256=digest))
            slot = await ws.receive_json(timeout=3)
            key = slot["upload_id"]
            async with client.put(base + "/input/" + key, data=data, headers=headers) as response:
                assert response.status == 200 and response.headers["Cache-Control"] == "no-store"
            await ws.send_json(dict(**envelope, type="camera_observation", generation=2, frame=dict(
                upload_id=key, byte_length=len(data), sha256=digest, mime="image/jpeg")))
            await asyncio.wait_for(started.wait(), 3)
            await ws.send_json(share | dict(generation=3, question=False, observe=False))
            await ws.send_json(dict(type="ping", protocol_version=1, nonce=sample_id(512)))
            assert (await ws.receive_json(timeout=3))["type"] == "pong"
            resume.set()
            assert (await ws.receive_json(timeout=3))["generation"] == 3
            assert gateway._active.uploads.reserved_bytes == 0
            assert not gateway._active.uploads.camera_current(gateway._active.extension_context, 2, "observe")
            assert observed == [False]
            await ws.close()

    asyncio.run(scenario())
