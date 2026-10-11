"""다운로드 정책과 분리된 고정 입력 업로드 경계. 본문을 로그나 파일에 남기지 않는다."""

import asyncio

from aiohttp import web

from .connection_resources import MediaError
from .adapter import AdapterError
from .image_thumbnail import thumbnail
from .input_uploads import InputError
from .media_http import media_response, validate_policy
from .protocol import ProtocolError, uuid_value


def validate_upload_policy(request):
    if (request.method != "PUT" or "?" in request.raw_path or "%" in request.raw_path
            or any(name in request.headers for name in ("Origin", "Range", "If-Range", "Transfer-Encoding", "Content-Encoding"))
            or len(request.headers.getall("Content-Length", [])) != 1
            or request.headers.getall("Content-Type", []) != ["application/octet-stream"]
            or request.content_length is None or not 0 < request.content_length <= 4194304):
        raise InputError("invalid_request")


class InputHttp:
    def __init__(self, authorize, validate_connection, *, idle_timeout=10, total_timeout=60):
        self._authorize, self._validate_connection = authorize, validate_connection
        self._idle_timeout, self._total_timeout = idle_timeout, total_timeout

    async def upload(self, request):
        session = context = key = None
        task = None
        started = False
        try:
            session = self._authorize(request)
            if not session.input_rate.take():
                raise InputError("rate_limited", 429)
            validate_upload_policy(request)
            try:
                key = uuid_value(request.match_info["upload_id"])
            except ProtocolError:
                raise InputError("invalid_request") from None
            context = session.extension_context
            purpose = session.uploads.purpose(context, key)
            if ("chat_images_v1" if purpose == "image" else "stt_input_v1") not in session.capabilities:
                raise InputError("not_found", 404)
            task = session.resources.acquire("upload")
            session.uploads.begin(context, key, request.content_length)
            started = True

            def current():
                self._validate_connection()
                if self._authorize(request) is not session or session.extension_context != context or not session.synced:
                    raise InputError("stale_extension", 409)

            async with asyncio.timeout(self._total_timeout):
                current()
                while True:
                    chunk = await asyncio.wait_for(request.content.read(65536), self._idle_timeout)
                    current()
                    if not chunk:
                        break
                    session.uploads.append(context, key, chunk)
                # 디코드·해시 검증은 heartbeat/UI 스레드 밖에서 한다.
                await asyncio.to_thread(session.uploads.finish, context, key)
                current()
            started = False
            return web.json_response({"status": "ready"}, headers={"Cache-Control": "no-store"})
        except (InputError, MediaError) as error:
            return media_response(error.code, error.status)
        except TimeoutError:
            return media_response("upload_timeout", 408)
        except (ConnectionError, web.HTTPException):
            return media_response("upload_failed", 400)
        finally:
            if task is not None:
                session.resources.release(task)
            if started:
                try:
                    session.uploads.cancel(context, key)
                except InputError:
                    pass

    async def image(self, request):
        session = task = None
        try:
            session = self._authorize(request)
            if not session.thumbnail_rate.take():
                raise InputError("rate_limited", 429)
            validate_policy(request)
            if "chat_images_v1" not in session.capabilities or not session.synced:
                raise InputError("not_found", 404)
            try:
                ids = tuple(uuid_value(request.match_info[key]) for key in ("message_id", "image_id"))
            except ProtocolError:
                raise InputError("invalid_request") from None
            context = session.extension_context
            task = session.resources.acquire("thumbnail")

            def current():
                self._validate_connection()
                if self._authorize(request) is not session or session.extension_context != context:
                    raise InputError("stale_extension", 409)

            async with asyncio.timeout(15):
                current()
                revision, data = await session.adapter.call("image_capture", session.context, pending=ids)
                current()
                body, mime = await asyncio.to_thread(thumbnail, data)
                current()
                fresh_revision, _ = await session.adapter.call("image_capture", session.context, pending=ids)
                current()
                if revision != fresh_revision:
                    raise InputError("image_unavailable", 404)
                return web.Response(body=body, headers={"Cache-Control": "no-store", "Content-Type": mime,
                    "X-Content-Type-Options": "nosniff", "X-ENE-Attachment-Revision": str(revision)})
        except (InputError, MediaError) as error:
            return media_response(error.code, error.status)
        except AdapterError:
            return media_response("image_unavailable", 404)
        except TimeoutError:
            return media_response("image_timeout", 408)
        finally:
            if task is not None:
                session.resources.release(task)
