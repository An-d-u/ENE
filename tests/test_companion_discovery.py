"""실제 LAN 송신 없이 최소 광고 정보와 비동기 정리를 검증한다."""

import asyncio

import pytest

from src.core.companion.network import Endpoint


def test_announcement_exposes_only_ephemeral_service_metadata():
    from src.core.companion.discovery import build_service_info

    instance = "ene-" + "1" * 32
    info = build_service_info((Endpoint("192.0.2.41", 8765),), instance)
    assert info.type == "_ene-companion._tcp.local."
    assert info.name == instance + "._ene-companion._tcp.local."
    assert info.server == instance + ".local."
    assert info.port == 8765
    assert info.properties == {b"v": b"1", b"transport": b"tls_v1"}
    assert info.parsed_addresses() == ["192.0.2.41"]


@pytest.mark.parametrize("endpoints", [(), (Endpoint("host.local", 8765),), (Endpoint("192.0.2.1", 0),), (Endpoint("192.0.2.1", 8765), Endpoint("192.0.2.2", 9876))])
def test_invalid_announcement_is_rejected(endpoints):
    from src.core.companion.discovery import build_service_info

    with pytest.raises(ValueError):
        build_service_info(endpoints, "ene-" + "1" * 32)


def test_announcement_deduplicates_and_caps_addresses():
    from src.core.companion.discovery import build_service_info

    info = build_service_info(tuple(Endpoint(f"192.0.2.{i}", 8765) for i in range(1, 20)), "ene-" + "1" * 32)
    assert len(info.addresses) == 8
    with pytest.raises(ValueError):
        build_service_info((Endpoint("192.0.2.1", 8765),), "personal-host")


class FakeZeroconf:
    def __init__(self, **kwargs):
        self.options = kwargs
        self.calls = []
        self.register_gate = None
        self.fail = False

    async def _announce(self, operation, info):
        self.calls.append((operation, info))
        if self.register_gate is not None and operation == "register":
            await self.register_gate.wait()
        if self.fail and operation == "register":
            raise OSError("synthetic")

        async def sent():
            self.calls.append((operation + "_sent", info))
        return asyncio.create_task(sent())

    async def async_register_service(self, info):
        return await self._announce("register", info)

    async def async_update_service(self, info):
        return await self._announce("update", info)

    async def async_unregister_service(self, info):
        return await self._announce("unregister", info)

    async def async_update_interfaces(self, interfaces):
        self.calls.append(("interfaces", interfaces))

    async def async_close(self):
        self.calls.append(("close", None))


def test_advertisement_updates_serially_and_closes_once():
    from src.core.companion.discovery import CompanionAdvertisement

    async def run():
        instances = []
        advertisement = CompanionAdvertisement(factory=lambda **kw: instances.append(FakeZeroconf(**kw)) or instances[-1])
        a, b = (Endpoint("192.0.2.41", 8765),), (Endpoint("192.0.2.42", 8765),)
        advertisement.update(())
        await advertisement.wait_idle()
        assert not instances
        advertisement.update(a)
        await advertisement.wait_idle()
        first = instances[0].calls[0][1]
        advertisement.update(a)
        await advertisement.wait_idle()
        assert [c[0] for c in instances[0].calls] == ["register", "register_sent"]
        advertisement.update(b)
        await advertisement.wait_idle()
        assert instances[0].calls[-1][0] == "update_sent"
        assert instances[0].calls[-1][1].name == first.name
        await advertisement.close()
        await advertisement.close()
        assert [c[0] for c in instances[0].calls][-3:] == ["unregister", "unregister_sent", "close"]
        advertisement.update(a)
        await advertisement.wait_idle()
        assert len(instances) == 1
    asyncio.run(run())


def test_delayed_register_is_cancelled_on_stop_and_pending_updates_coalesce():
    from src.core.companion.discovery import CompanionAdvertisement

    async def run():
        fake = FakeZeroconf()
        fake.register_gate = asyncio.Event()
        advertisement = CompanionAdvertisement(factory=lambda **kw: fake)
        advertisement.update((Endpoint("192.0.2.41", 8765),))
        await asyncio.sleep(0)
        for i in range(1, 100):
            advertisement.update((Endpoint(f"192.0.2.{i}", 8765),))
        await advertisement.close()
        assert [c[0] for c in fake.calls] == ["register", "unregister", "unregister_sent", "close"]
    asyncio.run(run())


def test_publish_failure_and_missing_dependency_are_nonfatal_and_retryable():
    from src.core.companion.discovery import CompanionAdvertisement

    async def run():
        notices, instances = [], []
        def factory(**kw):
            if not instances:
                instances.append(None)
                raise ImportError("synthetic")
            fake = FakeZeroconf(**kw)
            fake.fail = len(instances) == 1
            instances.append(fake)
            return fake
        advertisement = CompanionAdvertisement(factory=factory, report=notices.append)
        for _ in range(3):
            advertisement.update((Endpoint("192.0.2.41", 8765),))
            await advertisement.wait_idle()
        assert notices == ["discovery_unavailable", "discovery_publish_failed"]
        assert instances[-1].calls[-1][0] == "register_sent"
        advertisement.update(())
        await advertisement.wait_idle()
        assert instances[-1].calls[-1][0] == "close"
        await advertisement.close()
    asyncio.run(run())
