"""Qt 주소 수집과 서버 루프 광고 사이의 세대·종료 경계를 검증한다."""

import threading
from dataclasses import replace

from src.core.companion.controller import CompanionController
from src.core.companion.gateway import GatewayState
from src.core.companion.network import Endpoint
from src.core.companion.storage import RegistrationStore
from src.core.companion.tls_storage import TlsIdentityStore
from tests.companion_helpers import sample_id
from tests.test_companion_bridge_transcript import bridge  # noqa: F401
from tests.test_companion_dialog import qt_app, spin  # noqa: F401


class AdvertisementDouble:
    def __init__(self, **kwargs):
        self.calls = []
        self.closed = False
        self.threads = []

    def update(self, endpoints):
        self.calls.append(tuple(endpoints))
        self.threads.append(threading.get_ident())

    async def close(self):
        self.closed = True


def test_registered_server_refreshes_on_qt_and_ignores_stale_generation(bridge, qt_app, tmp_path):
    store = RegistrationStore(tmp_path / "registration.json")
    with TlsIdentityStore(store) as tls:
        tls.load_or_create()
    record = store.load_or_create()
    store.save(replace(record, device_id=sample_id(42), registration_generation=1, token_hash="1" * 64))
    addresses = ["192.0.2.41"]
    qt_thread = threading.get_ident()
    instances = []

    def endpoints(port):
        assert threading.get_ident() == qt_thread
        return tuple(Endpoint(address, port) for address in addresses)

    def factory(**kwargs):
        advertisement = AdvertisementDouble(**kwargs)
        instances.append(advertisement)
        return advertisement

    controller = CompanionController(bridge, store_factory=lambda: store, endpoint_provider=endpoints, discovery_factory=factory)
    try:
        controller.start(port=0, host="127.0.0.1", test_port=True)
        spin(qt_app, lambda: instances and any(instances[0].calls))
        advertisement = instances[0]
        port = controller.state.port
        assert controller._discovery_timer.interval() == 15_000
        assert controller._discovery_timer.isActive()
        assert advertisement.calls[-1] == (Endpoint("192.0.2.41", port),)
        assert all(value != qt_thread for value in advertisement.threads)
        addresses[:] = ["192.0.2.42"]
        controller._refresh_discovery()
        spin(qt_app, lambda: advertisement.calls[-1] == (Endpoint("192.0.2.42", port),))
        done = threading.Event()
        def old_update():
            controller._apply_discovery("old-generation", (Endpoint("192.0.2.99", port),))
            done.set()
        controller._loop.call_soon_threadsafe(old_update)
        spin(qt_app, done.is_set)
        assert advertisement.calls[-1] == (Endpoint("192.0.2.42", port),)
        controller.revoke()
        spin(qt_app, lambda: not controller.state.registered and advertisement.calls[-1] == ())
        assert not controller._discovery_timer.isActive()
    finally:
        controller.stop()
        spin(qt_app, lambda: not controller.has_thread)
    assert advertisement.closed
    assert not controller._discovery_timer.isActive()

    controller.start(port=0, host="127.0.0.1", test_port=True)
    try:
        spin(qt_app, lambda: controller.state.running)
        assert len(instances) == 2
        assert instances[0] is not instances[1]
        assert not any(instances[1].calls)
    finally:
        controller.stop()
        spin(qt_app, lambda: not controller.has_thread)


def test_unregistered_and_early_stop_never_advertise(bridge, qt_app, tmp_path):
    instances = []
    def factory(**kwargs):
        instances.append(AdvertisementDouble(**kwargs))
        return instances[-1]
    controller = CompanionController(bridge, store_factory=lambda: RegistrationStore(tmp_path / "registration.json"),
        endpoint_provider=lambda _: (_ for _ in ()).throw(AssertionError("미등록 주소 수집 금지")), discovery_factory=factory)
    try:
        controller.start(port=0, host="127.0.0.1", test_port=True)
        spin(qt_app, lambda: controller.state.running)
        assert not any(instances[0].calls)
        assert not controller._discovery_timer.isActive()
    finally:
        controller.stop()
        spin(qt_app, lambda: not controller.has_thread)
    controller.start(port=0, host="127.0.0.1", test_port=True)
    controller.stop()
    spin(qt_app, lambda: not controller.has_thread)
    assert all(not any(instance.calls) and instance.closed for instance in instances)
