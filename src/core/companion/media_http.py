"""고정 음성 경로만 제공한다. 인증 후 정책 검사와 자원 예약을 마친 뒤 전송한다."""

import asyncio

from aiohttp import web

from .connection_resources import MediaError
from .protocol import ProtocolError, uuid_value


def media_response(code, status):
    return web.json_response(
        {"code": code}, status=status, headers={"Cache-Control": "no-store"}
    )


def validate_policy(request):
    if (
        request.method != "GET"
        or "?" in request.raw_path
        or "%" in request.raw_path
        or any(
            name in request.headers
            for name in ("Origin", "Range", "If-Range", "Transfer-Encoding")
        )
        or request.content_length not in (None, 0)
    ):
        raise MediaError("invalid_request", 400)


class MediaHttp:
    def __init__(self, authorize, validate_connection):
        self._authorize = authorize
        self._validate_connection = validate_connection

    async def audio(self, request):
        try:
            session = self._authorize(request)
            resources = session.resources
            if not resources.rate.take():
                raise MediaError("rate_limited", 429)
            validate_policy(request)
            if "audio_pcm_v1" not in session.capabilities:
                raise MediaError("not_found", 404)
            try:
                utterance_id = uuid_value(request.match_info["utterance_id"])
            except ProtocolError:
                raise MediaError("invalid_request", 400) from None
            task, source = resources.acquire_audio(utterance_id)
        except MediaError as error:
            return media_response(error.code, error.status)
        response = web.StreamResponse(
            headers={
                "Cache-Control": "no-store",
                "Content-Type": "application/octet-stream",
                "X-ENE-Audio-Format": "pcm_s16le",
                "X-ENE-Sample-Rate": str(source.format.sample_rate),
                "X-ENE-Channels": str(source.format.channels),
            }
        )
        complete = False
        try:
            async with asyncio.timeout(185):
                self._validate_connection()
                await response.prepare(request)
                while True:
                    self._validate_connection()
                    if resources.closed or resources.audio_cancelled or source.closed:
                        raise MediaError("audio_cancelled", 410)
                    resources.audio_ready.clear()
                    chunk = source.peek()
                    if chunk is not None:
                        # consume 전까지 원본 구간을 보관하므로 write 중인 바이트도 상한에 포함된다.
                        await asyncio.wait_for(response.write(chunk), 5)
                        self._validate_connection()
                        source.consume(len(chunk))
                    elif source.source_ended:
                        await response.write_eof()
                        complete = True
                        break
                    else:
                        await asyncio.wait_for(resources.audio_ready.wait(), 5)
            return response
        finally:
            resources.release(task)
            if not complete:
                source.cancel_transfer()
                resources.audio_cancelled = True
                # 정상 EOF로 오인하지 않도록 중단된 본문은 transport까지 닫는다.
                if request.transport is not None:
                    request.transport.close()
