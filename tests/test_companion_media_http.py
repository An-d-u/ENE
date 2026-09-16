"""합성 PCM과 실제 루프백 TLS로 연결별 음성 접근 권한을 확인한다."""

import asyncio

from aiohttp import web
import pytest

from src.core.companion.audio_buffer import WavSource
from tests.companion_helpers import sample_id
from tests.test_companion_audio_buffer import wav
from tests.test_companion_gateway import harness, synchronize


async def media_connection(client, base, token, capabilities=("audio_pcm_v1",)):
    ws = await client.ws_connect(
        base + "/ws", headers={"Authorization": f"Bearer {token}"}
    )
    await ws.send_json(
        {"type": "hello", "protocol_version": 1, "capabilities": list(capabilities)}
    )
    ready = await ws.receive_json(timeout=3)
    extension = await ws.receive_json(timeout=2)
    assert ready["capabilities"] == extension["capabilities"] == list(capabilities)
    await synchronize(ws)
    return (
        ws,
        ready,
        extension,
        {
            "Authorization": f"Bearer {token}",
            "X-ENE-Connection": extension["connection_generation"],
        },
    )


def add_audio(gateway, number=900):
    source = WavSource(wav())
    gateway._active.resources.add_audio(sample_id(number), source)
    return source


def test_token_without_current_wss_cannot_read_audio(tmp_path):
    async def scenario():
        async with harness(tmp_path, capabilities=("audio_pcm_v1",)) as (
            _,
            client,
            base,
            token,
            _,
            _,
        ):
            path = base + "/audio/" + sample_id(900)
            async with client.get(path) as response:
                assert response.status == 401
            async with client.get(
                path,
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-ENE-Connection": sample_id(1),
                },
            ) as response:
                assert response.status == 404

    asyncio.run(scenario())


def test_audio_is_single_use_framed_and_never_cached(tmp_path):
    async def scenario():
        async with harness(tmp_path, capabilities=("audio_pcm_v1",)) as (
            gateway,
            client,
            base,
            token,
            _,
            _,
        ):
            ws, _, _, headers = await media_connection(client, base, token)
            add_audio(gateway)
            path = base + "/audio/" + sample_id(900)
            async with client.get(path, headers=headers) as response:
                assert response.status == 200
                assert response.headers["Cache-Control"] == "no-store"
                assert response.headers["X-ENE-Audio-Format"] == "pcm_s16le"
                assert response.headers["X-ENE-Sample-Rate"] == "24000"
                assert response.headers["X-ENE-Channels"] == "1"
                assert response.headers.get("Content-Encoding") is None
                assert await response.read() == b"\x00\x00" * 100
            async with client.get(path, headers=headers) as response:
                assert response.status == 404
            assert gateway._active.resources.active_count == 0
            await ws.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "suffix,extra,status",
    [
        ("", {"Range": "bytes=0-"}, 400),
        ("", {"Origin": "null"}, 400),
        ("?part=1", {}, 400),
        ("", {"X-ENE-Connection": sample_id(99)}, 404),
        ("", {"Authorization": "Bearer invalid"}, 401),
    ],
)
def test_policy_and_stale_credentials_fail_before_consumption(
    tmp_path, suffix, extra, status
):
    async def scenario():
        async with harness(tmp_path, capabilities=("audio_pcm_v1",)) as (
            gateway,
            client,
            base,
            token,
            _,
            _,
        ):
            ws, _, _, headers = await media_connection(client, base, token)
            add_audio(gateway)
            path = base + "/audio/" + sample_id(900)
            async with client.get(path + suffix, headers=headers | extra) as response:
                assert response.status == status
            async with client.get(path, headers=headers) as response:
                assert response.status == 200
            await ws.close()

    asyncio.run(scenario())


def test_cancelled_audio_is_gone_and_new_connection_cannot_reuse_it(tmp_path):
    async def scenario():
        async with harness(tmp_path, capabilities=("audio_pcm_v1",)) as (
            gateway,
            client,
            base,
            token,
            _,
            _,
        ):
            ws, _, _, headers = await media_connection(client, base, token)
            add_audio(gateway)
            old = gateway._active.resources
            old.cancel_audio()
            path = base + "/audio/" + sample_id(900)
            async with client.get(path, headers=headers) as response:
                assert response.status == 410
            await ws.close()
            next_ws, _, _, new_headers = await media_connection(client, base, token)
            assert old.closed and old.active_count == 0
            for credential in (headers, new_headers):
                async with client.get(path, headers=credential) as response:
                    assert response.status == 404
            await next_ws.close()

    asyncio.run(scenario())


def test_authenticated_media_rate_is_separate_from_preauth_and_chat(tmp_path):
    async def scenario():
        async with harness(tmp_path, capabilities=("audio_pcm_v1",)) as (
            _,
            client,
            base,
            token,
            _,
            _,
        ):
            ws, _, _, headers = await media_connection(client, base, token)
            codes = []
            for _ in range(18):
                async with client.get(
                    base + "/audio/" + sample_id(900), headers=headers
                ) as response:
                    codes.append(response.status)
            assert codes[:16] == [404] * 16 and 429 in codes[16:]
            await ws.send_json(
                {"type": "ping", "protocol_version": 1, "nonce": sample_id(700)}
            )
            assert (await ws.receive_json(timeout=1))["type"] == "pong"
            await ws.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("shutdown", ["socket", "revoke", "replace", "tls_expiry"])
def test_wss_close_cancels_stalled_write_and_releases_source(
    tmp_path, monkeypatch, shutdown
):
    async def scenario():
        entered, cancelled = asyncio.Event(), asyncio.Event()

        async def stalled_write(self, data):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        monkeypatch.setattr(web.StreamResponse, "write", stalled_write)
        async with harness(tmp_path, capabilities=("audio_pcm_v1",)) as (
            gateway,
            client,
            base,
            token,
            _,
            _,
        ):
            ws, _, _, headers = await media_connection(client, base, token)
            source = add_audio(gateway)
            resources = gateway._active.resources
            response = await client.get(
                base + "/audio/" + sample_id(900), headers=headers
            )
            try:
                await asyncio.wait_for(entered.wait(), 1)
                async with client.get(
                    base + "/audio/" + sample_id(900), headers=headers
                ) as duplicate:
                    assert duplicate.status == 404
                if shutdown == "socket":
                    await ws.close()
                elif shutdown == "revoke":
                    await gateway.revoke()
                elif shutdown == "replace":
                    next_ws, _, _, _ = await media_connection(client, base, token)
                    await next_ws.close()
                else:
                    gateway._tls_clock = lambda: gateway._tls_identity.leaf_not_after
                    await gateway.check_tls()
                await asyncio.wait_for(cancelled.wait(), 1)
                assert source.closed
                await asyncio.wait_for(resources.wait_closed(), 1)
                assert resources.active_count == 0
            finally:
                response.close()

    asyncio.run(scenario())
