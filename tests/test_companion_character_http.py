"""실제 루프백 TLS에서 공개 모델 목록과 현재 연결에 한정된 바이트를 검증한다."""

import asyncio
import hashlib

from aiohttp import web
import pytest

from src.core.companion.protocol import decode_message, encode_message
from tests.test_companion_character_state import state_with_bundle, CATALOG
from tests.test_companion_gateway import harness, synchronize


async def character_connection(client, base, token, capabilities=("character_v1",)):
    ws = await client.ws_connect(
        base + "/ws", headers={"Authorization": f"Bearer {token}"}
    )
    await ws.send_json(
        {"type": "hello", "protocol_version": 1, "capabilities": list(capabilities)}
    )
    await ws.receive_json(timeout=3)
    extension = await ws.receive_json(timeout=2) if capabilities else None
    await synchronize(ws)
    headers = {"Authorization": f"Bearer {token}"}
    if extension:
        headers["X-ENE-Connection"] = extension["connection_generation"]
    return ws, headers, extension


def install_capture(port, state):
    original = port.call

    async def call(operation, context, **kwargs):
        if operation == "character_capture":
            return state.capture()
        return await original(operation, context, **kwargs)

    port.call = call


def test_manifest_and_assets_need_live_negotiated_connection(tmp_path):
    state, bundle = state_with_bundle(tmp_path)
    state.accept_catalog(
        state.generation, bundle.model_version, CATALOG, ["normal"], ["nod"]
    )

    async def scenario():
        async with harness(tmp_path, capabilities=("character_v1",)) as (
            gateway,
            client,
            base,
            token,
            port,
            _,
        ):
            install_capture(port, state)
            path = base + "/character/manifest"
            async with client.get(path) as response:
                assert response.status == 401
            ws, headers, _ = await character_connection(client, base, token)
            async with client.get(path, headers=headers) as response:
                assert response.status == 200
                assert response.headers["Cache-Control"] == "no-store"
                snapshot = await response.json()
                assert snapshot["model_version"] == bundle.model_version
            for asset in bundle.assets:
                async with client.get(
                    base + "/character/assets/" + asset.id, headers=headers
                ) as response:
                    assert response.status == 200
                    assert response.headers["Content-Type"] == asset.mime
                    assert int(response.headers["Content-Length"]) == asset.size
                    assert (
                        hashlib.sha256(await response.read()).hexdigest()
                        == asset.sha256
                    )
            state.unavailable("unsupported")
            async with client.get(
                base + "/character/assets/" + bundle.entry_asset_id, headers=headers
            ) as response:
                assert response.status == 404
            assert gateway._active.resources.active_count == 0
            await ws.close()
            async with client.get(path, headers=headers) as response:
                assert response.status == 404

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "suffix,extra,expected",
    [
        ("?next=1", {}, 400),
        ("", {"Origin": "null"}, 400),
        ("", {"Range": "bytes=0-"}, 400),
        ("", {"Authorization": "Bearer invalid"}, 401),
    ],
)
def test_character_http_rejects_browser_range_query_and_bad_auth(
    tmp_path, suffix, extra, expected
):
    state, _ = state_with_bundle(tmp_path)

    async def scenario():
        async with harness(tmp_path, capabilities=("character_v1",)) as (
            _,
            client,
            base,
            token,
            port,
            _,
        ):
            install_capture(port, state)
            ws, headers, _ = await character_connection(client, base, token)
            async with client.get(
                base + "/character/manifest" + suffix, headers=headers | extra
            ) as response:
                assert response.status == expected
            await ws.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["model", "socket"])
def test_model_change_or_disconnect_cancels_stalled_asset(
    tmp_path, monkeypatch, change
):
    state, bundle = state_with_bundle(tmp_path)
    state.accept_catalog(
        state.generation, bundle.model_version, CATALOG, ["normal"], ["nod"]
    )

    async def scenario():
        entered, cancelled = asyncio.Event(), asyncio.Event()

        async def stalled_write(self, data):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        monkeypatch.setattr(web.StreamResponse, "write", stalled_write)
        async with harness(tmp_path, capabilities=("character_v1",)) as (
            gateway,
            client,
            base,
            token,
            port,
            _,
        ):
            install_capture(port, state)
            ws, headers, extension = await character_connection(client, base, token)
            resources = gateway._active.resources
            response = await client.get(
                base + "/character/assets/" + bundle.entry_asset_id, headers=headers
            )
            try:
                await asyncio.wait_for(entered.wait(), 1)
                if change == "model":
                    state.unavailable("loading")
                    gateway.publish(
                        decode_message(
                            encode_message(
                                {
                                    **extension,
                                    "type": "character_changed",
                                    "state_revision": state.state_revision,
                                    "model_version": None,
                                    "reason": "loading",
                                }
                            )
                        )
                    )
                else:
                    await ws.close()
                await asyncio.wait_for(cancelled.wait(), 1)
                await asyncio.sleep(0.02)
                assert resources.active_count == 0
            finally:
                response.close()
                await ws.close()

    asyncio.run(scenario())


def test_audio_only_client_cannot_read_character_even_with_current_token(tmp_path):
    from tests.test_companion_media_http import media_connection

    async def scenario():
        async with harness(tmp_path, capabilities=("character_v1", "audio_pcm_v1")) as (
            _,
            client,
            base,
            token,
            _,
            _,
        ):
            ws, _, _, headers = await media_connection(client, base, token)
            async with client.get(
                base + "/character/manifest", headers=headers
            ) as response:
                assert response.status == 404
            await ws.close()

    asyncio.run(scenario())
