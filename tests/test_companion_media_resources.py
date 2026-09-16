"""반복 교체·포화·반쪽 전송을 합성 자원과 실제 루프백 TLS로 확인한다."""

import asyncio
import time

from aiohttp import web
import pytest

from src.core.companion.connection_resources import ConnectionResources, MediaError
from tests.test_companion_gateway import harness
from tests.test_companion_media_http import media_connection, add_audio
from tests.test_companion_character_runtime import run_character


def test_twenty_resource_generations_cancel_both_media_kinds_and_drain():
    async def scenario():
        for index in range(20):
            resources = ConnectionResources()
            resources.observe_character(1, "a" * 64)
            entered, drained = [], []

            async def hold(kind):
                task = resources.acquire(kind)
                entered.append(kind)
                try:
                    await asyncio.Event().wait()
                finally:
                    resources.release(task)
                    drained.append(kind)

            tasks = [asyncio.create_task(hold(kind)) for kind in ("audio", "asset", "asset", "manifest")]
            await asyncio.sleep(0)
            assert len(entered) == resources.active_count == 4
            for kind in ("audio", "asset", "manifest"):
                with pytest.raises(MediaError) as caught:
                    resources.acquire(kind)
                assert caught.value.status == 429
            if index % 2:
                assert resources.observe_character(2, "b" * 64)
                assert not resources.observe_character(1, "a" * 64)
                await asyncio.sleep(0)
                assert resources.active_count == 1
            resources.cancel()
            await asyncio.wait_for(resources.wait_closed(), 1)
            assert resources.closed and resources.active_count == 0
            assert len(drained) == 4 and all(task.done() for task in tasks)
            with pytest.raises(MediaError):
                resources.acquire("manifest")

    asyncio.run(scenario())


def test_twenty_live_tls_replacements_close_stalled_pcm_and_old_authority(tmp_path, monkeypatch):
    async def scenario():
        entered = asyncio.Event()

        async def stalled_write(_response, _data):
            entered.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(web.StreamResponse, "write", stalled_write)
        async with harness(tmp_path, capabilities=("audio_pcm_v1",)) as (gateway, client, base, token, _, _):
            # 반복 수명 시험은 1분 간격 접속을 가상 시간으로 진행한다. 실제 제한 정책은 유지한다.
            stamp = time.monotonic()
            gateway._limiter._clock = lambda: stamp
            ws, _, _, headers = await media_connection(client, base, token)
            for index in range(20):
                stamp += 61
                entered.clear()
                source = add_audio(gateway, 1000 + index)
                previous = gateway._active.resources
                path = base + "/audio/" + previous.audio_id
                response = await client.get(path, headers=headers)
                reader = None
                try:
                    await asyncio.wait_for(entered.wait(), 1)
                    # 정상 앱처럼 이전 WSS의 닫기 프레임도 읽어 고정 종료 타임아웃을 반복 소모하지 않는다.
                    reader = asyncio.create_task(ws.receive())
                    next_ws, _, _, next_headers = await media_connection(client, base, token)
                    await asyncio.wait_for(reader, 2)
                    await asyncio.wait_for(previous.wait_closed(), 1)
                    assert previous.closed and previous.active_count == 0 and source.closed
                    async with client.get(path, headers=headers) as stale:
                        assert stale.status == 404
                    await ws.close()
                    ws, headers = next_ws, next_headers
                finally:
                    response.close()
                    if reader is not None and not reader.done():
                        reader.cancel()
                        await asyncio.gather(reader, return_exceptions=True)
            await ws.close()

    asyncio.run(scenario())


def test_twenty_shared_renderer_lifetimes_leave_no_javascript_callbacks():
    run_character(r"""
for(let i=0;i<20;i++) {
    const character=context.createCharacter(host,canvas);
    await character.applySnapshot(snapshot);
    character.applyPreview({...snapshot,settings:{enable_head_pat:false},parameters:{ParamAccent:0.6}});
    character.applyPlayback({active:true,mouth_open:0.5});
    await tick();character.dispose();character.dispose();
    assert.equal(frames.size,0);assert.equal(timers.size,0);assert.equal(listeners.size,0);
    assert.equal(context.live2dModel,null);
}
assert.equal(calls.filter(x=>x==='destroyApp').length,20);
""")
