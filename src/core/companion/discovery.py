"""등록된 TLS 서버를 익명 실행 단위 이름으로만 광고한다."""

import asyncio
import ipaddress
import re
from uuid import uuid4

from .network import select_endpoints


SERVICE_TYPE = "_ene-companion._tcp.local."


def build_service_info(endpoints, instance):
    from zeroconf import ServiceInfo

    if not re.fullmatch(r"ene-[0-9a-f]{32}", instance):
        raise ValueError("discovery_invalid_instance")
    if not endpoints or len({item.port for item in endpoints}) != 1:
        raise ValueError("discovery_invalid_endpoints")
    selected = select_endpoints((item.host for item in endpoints), endpoints[0].port)
    if not selected:
        raise ValueError("discovery_no_address")
    return ServiceInfo(
        SERVICE_TYPE, instance + "." + SERVICE_TYPE,
        addresses=[ipaddress.IPv4Address(item.host).packed for item in selected],
        port=selected[0].port, server=instance + ".local.",
        properties={b"v": b"1", b"transport": b"tls_v1"},
    )


def _create_zeroconf(**kwargs):
    from zeroconf.asyncio import AsyncZeroconf

    return AsyncZeroconf(**kwargs)


class CompanionAdvertisement:
    def __init__(self, *, factory=_create_zeroconf, report=lambda code: None):
        self._factory, self._report = factory, report
        self._instance = "ene-" + uuid4().hex
        self._zeroconf = self._info = self._task = None
        self._desired = None
        self._applied = ()
        self._closed = self._blocked = False

    def update(self, endpoints):
        """서버 루프에서만 호출하며 입력은 최신 한 개만 보관한다."""
        if self._closed or self._blocked:
            return
        self._desired = tuple(endpoints)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._drain())

    async def wait_idle(self):
        if self._task is not None:
            await self._task

    async def _drain(self):
        while self._desired is not None and not self._closed:
            endpoints, self._desired = self._desired, None
            if endpoints == self._applied:
                continue
            try:
                if not endpoints:
                    await self._dispose_bounded()
                    continue
                from zeroconf import IPVersion

                info = build_service_info(endpoints, self._instance)
                interfaces = info.parsed_addresses()
                if self._zeroconf is None:
                    self._zeroconf = self._factory(interfaces=interfaces, ip_version=IPVersion.V4Only)
                    # register 도중 취소되어도 해제할 수 있도록 먼저 보관한다.
                    self._info = info
                    await (await self._zeroconf.async_register_service(info))
                else:
                    await self._zeroconf.async_update_interfaces(interfaces)
                    self._info = info
                    await (await self._zeroconf.async_update_service(info))
                self._applied = endpoints
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self._report("discovery_unavailable" if isinstance(error, ImportError) else "discovery_publish_failed")
                await self._dispose_bounded()
                return

    async def _dispose(self):
        if self._zeroconf is None:
            self._applied = ()
            return
        zeroconf, info = self._zeroconf, self._info
        try:
            if info is not None:
                await (await zeroconf.async_unregister_service(info))
        finally:
            await zeroconf.async_close()
            self._zeroconf = self._info = None
            self._applied = ()

    async def _dispose_bounded(self):
        try:
            await asyncio.wait_for(self._dispose(), 2)
        except asyncio.TimeoutError:
            self._blocked = True
            self._report("discovery_shutdown_timeout")
        except Exception:
            if self._zeroconf is not None:
                self._blocked = True
            self._report("discovery_publish_failed")

    async def close(self):
        if self._closed:
            return
        self._closed = True
        self._desired = None

        async def finish():
            try:
                if self._task is not None:
                    self._task.cancel()
                    try:
                        await self._task
                    except asyncio.CancelledError:
                        pass
            finally:
                await self._dispose()
        try:
            await asyncio.wait_for(finish(), 2)
        except asyncio.TimeoutError:
            self._report("discovery_shutdown_timeout")
        except Exception:
            self._report("discovery_publish_failed")
