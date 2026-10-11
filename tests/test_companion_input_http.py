"""합성 사진을 실제 루프백 TLS로 업로드해 WSS 예약과 HTTP 권한 결합을 검사한다."""

import asyncio
from hashlib import sha256

import pytest

from tests.companion_helpers import sample_id
from tests.test_companion_gateway import harness
from tests.test_companion_media_http import media_connection
from tests.test_companion_input_uploads import picture, descriptor


async def reservation(ws, ready, extensions, data, command=10):
    fields = dict(registration_generation=ready["registration_generation"], server_epoch=ready["server_epoch"],
                  connection_generation=extensions["connection_generation"], conversation_id=ready["conversation_id"])
    await ws.send_json(dict(type="input_reserve", protocol_version=1, **fields, command_id=sample_id(command),
                           purpose="image", byte_length=len(data), sha256=sha256(data).hexdigest()))
    reply = await ws.receive_json(timeout=3)
    assert reply["type"] == "input_reserved"
    assert reply["command_id"] == sample_id(command)
    return reply["upload_id"]


def test_authenticated_reservation_upload_and_single_consumption(tmp_path):
    async def scenario():
        async with harness(tmp_path, capabilities=("chat_images_v1",)) as (gateway, client, base, token, *_):
            ws, ready, extensions, headers = await media_connection(client, base, token, ("chat_images_v1",))
            data = picture()
            key = await reservation(ws, ready, extensions, data)
            async with client.put(base + "/input/" + key, headers=headers, data=data) as response:
                assert response.status == 200
                assert response.headers["Cache-Control"] == "no-store"
                assert await response.json() == {"status": "ready"}
            session = gateway._active
            result = session.uploads.claim(session.extension_context, [descriptor(key, data)], "image")
            assert result[0].body == data
            async with client.put(base + "/input/" + key, headers=headers, data=data) as response:
                assert response.status == 404
            await ws.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("suffix,extra,status", [("", {"Origin": "null"}, 400), ("?token=unused", {}, 400),
    ("", {"Content-Encoding": "gzip"}, 400), ("", {"Content-Type": "image/png"}, 400),
    ("", {"X-ENE-Connection": sample_id(8)}, 404), ("", {"Authorization": "Bearer invalid"}, 401)])
def test_upload_policy_rejects_before_consuming_reservation(tmp_path, suffix, extra, status):
    async def scenario():
        async with harness(tmp_path, capabilities=("chat_images_v1",)) as (_, client, base, token, *_):
            ws, ready, extensions, headers = await media_connection(client, base, token, ("chat_images_v1",))
            data = picture()
            key = await reservation(ws, ready, extensions, data)
            async with client.put(base + "/input/" + key + suffix, headers=headers | extra, data=data) as response:
                assert response.status == status
            async with client.put(base + "/input/" + key, headers=headers, data=data) as response:
                assert response.status == 200
            await ws.close()
    asyncio.run(scenario())


def test_bad_hash_and_length_do_not_publish(tmp_path):
    async def scenario():
        async with harness(tmp_path, capabilities=("chat_images_v1",)) as (gateway, client, base, token, *_):
            ws, ready, extensions, headers = await media_connection(client, base, token, ("chat_images_v1",))
            data = picture()
            key = await reservation(ws, ready, extensions, data)
            async with client.put(base + "/input/" + key, headers=headers, data=b"x" * len(data)) as response:
                assert response.status == 400
            assert gateway._active.uploads.reserved_bytes == 0
            key = await reservation(ws, ready, extensions, data, 11)
            async with client.put(base + "/input/" + key, headers=headers, data=data[:-1]) as response:
                assert response.status == 400
            await ws.close()
    asyncio.run(scenario())


def test_socket_close_disposes_unaccepted_upload(tmp_path):
    async def scenario():
        async with harness(tmp_path, capabilities=("chat_images_v1",)) as (gateway, client, base, token, *_):
            ws, ready, extensions, headers = await media_connection(client, base, token, ("chat_images_v1",))
            data = picture()
            key = await reservation(ws, ready, extensions, data)
            session = gateway._active
            await ws.close()
            await asyncio.wait_for(session.finished.wait(), 3)
            assert session.uploads.reserved_bytes == 0
            async with client.put(base + "/input/" + key, headers=headers, data=data) as response:
                assert response.status == 404
    asyncio.run(scenario())


@pytest.mark.parametrize("syncing", [False, True])
def test_rejected_photo_command_releases_uploaded_slots(tmp_path, syncing):
    async def scenario():
        async with harness(tmp_path, capabilities=("chat_images_v1",)) as (gateway, client, base, token, *_):
            ws, ready, ext, headers = await media_connection(client, base, token, ("chat_images_v1",))
            data = picture()
            key = await reservation(ws, ready, ext, data)
            async with client.put(base + "/input/" + key, headers=headers, data=data) as response:
                assert response.status == 200
            session = gateway._active
            assert session.uploads.reserved_bytes == len(data)
            if syncing:
                session.synced = False
            # 가상 adapter의 send_images 미지원 예외와 재동기화 거절을 모두 검사한다.
            await ws.send_json(dict(type="chat_images_send", protocol_version=1,
                registration_generation=ready["registration_generation"], server_epoch=ready["server_epoch"],
                connection_generation=ext["connection_generation"], conversation_id=ready["conversation_id"],
                request_id=sample_id(85), text="가상 이미지", images=[descriptor(key, data)]))
            result = await ws.receive_json(timeout=3)
            assert result["type"] == "request_status"
            assert result["state"] in {"unknown", "rejected"}
            assert session.uploads.reserved_bytes == 0
            await ws.close()
    asyncio.run(scenario())
