"""Qt는 수락 권한을 소유하고 별도 스레드는 서버 루프만 실행한다."""

import asyncio
from contextlib import ExitStack
from dataclasses import replace
import threading
from uuid import uuid4

from PyQt6.QtCore import QObject, QTimer, Qt, pyqtSignal, pyqtSlot

from .adapter import AdmissionContext, AdapterError, QtGatewayAdapter
from .gateway import CompanionGateway, GatewayState
from .network import discover_endpoints
from .pairing import PairingError, PairingService
from .storage import RegistrationStore, StorageError
from .private_files import PrivateFileError
from .tls_identity import TlsError, TrustAnchor, utc_now
from .tls_storage import TlsIdentityStore


class CompanionController(QObject):
    state_changed = pyqtSignal(object)
    operation_failed = pyqtSignal(str)
    stopped = pyqtSignal()
    _network_state = pyqtSignal(object)
    _thread_done = pyqtSignal()
    _action_done = pyqtSignal()

    def __init__(
        self,
        owner,
        parent=None,
        *,
        store_factory=RegistrationStore,
        endpoint_provider=discover_endpoints,
    ):
        super().__init__(parent)
        self.adapter = QtGatewayAdapter(owner, self)
        self.state = GatewayState(False, None, False, None, None)
        self._store_factory, self._endpoint_provider = store_factory, endpoint_provider
        self._thread = self._loop = None
        self._gateway = self._stop_event = None
        self._stop_requested = threading.Event()
        self._action_pending = False
        self._generation = None
        self._network_state.connect(
            self._receive_state, Qt.ConnectionType.QueuedConnection
        )
        self._thread_done.connect(
            self._finish_thread, Qt.ConnectionType.QueuedConnection
        )
        self._action_done.connect(
            self._finish_action, Qt.ConnectionType.QueuedConnection
        )

    @property
    def has_thread(self):
        return self._thread is not None

    @pyqtSlot(object)
    def _receive_state(self, state):
        if self._stop_requested.is_set() and state.running:
            state = replace(
                state, running=False, qr=None, pending=None, code="stopping"
            )
        self.state = state
        self.state_changed.emit(state)

    def start(self, port=8765, host="0.0.0.0", *, test_port=False):
        if type(port) is not int or not (
            1 <= port <= 65535 or (test_port and port == 0)
        ):
            raise ValueError("invalid_port")
        if self.has_thread:
            self.operation_failed.emit("gateway_busy")
            return
        self._stop_requested.clear()
        self._generation = str(uuid4())
        self.adapter.configure(self._generation, 0)
        self._loop = asyncio.new_event_loop()
        self.adapter.attach(self._loop, self._route_event)
        self._receive_state(
            GatewayState(False, None, self.state.registered, None, None, "starting")
        )
        self._thread = threading.Thread(
            target=self._thread_main,
            args=(host, port),
            name="ene-companion-server",
            daemon=True,
        )
        self._thread.start()

    def _route_event(self, event):
        """서버 루프에서만 호출하며 Qt 객체나 화면에 접근하지 않는다."""
        if self._gateway is not None:
            self._gateway.publish(event)

    def _thread_main(self, host, port):
        loop = self._loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._serve(host, port))
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
            loop.close()
            self._thread_done.emit()

    async def _serve(self, host, port):
        self._stop_event = asyncio.Event()
        failure = None
        registered = False
        resources = ExitStack()

        def gateway_state(state):
            nonlocal failure
            if not state.running and state.code:
                failure = state.code
                self._stop_event.set()
            self._network_state.emit(state)

        try:
            if self._stop_requested.is_set():
                return
            store = self._store_factory()
            tls_store = resources.enter_context(TlsIdentityStore(store))
            identity = tls_store.load_or_create()
            anchor = TrustAnchor.parse(
                identity.ca_certificate, identity.server_id, utc_now()
            )
            pairing = PairingService(store, trust_anchor=anchor)
            registered = pairing.registration.token_hash is not None
            context = AdmissionContext(
                self._generation, pairing.registration.registration_generation
            )
            await self.adapter.call("block", context)
            await self.adapter.call("register", context)
            if self._stop_requested.is_set():
                return
            self._gateway = CompanionGateway(
                pairing,
                self.adapter,
                self._generation,
                tls_store=tls_store,
                on_state=gateway_state,
            )
            await self._gateway.start(host, port)
            if not self._stop_requested.is_set():
                await self._stop_event.wait()
        except (StorageError, PrivateFileError, TlsError, PairingError) as error:
            failure = error.code
        except AdapterError:
            failure = None if self._stop_requested.is_set() else "adapter_unavailable"
        except OSError:
            failure = "listen_failed"
        except Exception:
            failure = "gateway_failed"
        finally:
            if self._gateway is not None:
                registered = self._gateway.pairing.registration.token_hash is not None
                await self._gateway.stop()
                self._gateway = None
            resources.close()
            self._stop_event = None
            self._network_state.emit(
                GatewayState(False, None, registered, None, None, failure)
            )

    def stop(self):
        # Qt에서 즉시 차단하므로 그 뒤 처리되는 서버 신호는 신규 작업을 수락할 수 없다.
        self._stop_requested.set()
        self.adapter.disable()
        if self._loop is not None and not self._loop.is_closed():
            self._receive_state(
                replace(
                    self.state, running=False, qr=None, pending=None, code="stopping"
                )
            )
            self._loop.call_soon_threadsafe(self._signal_stop)
            generation = self._generation
            QTimer.singleShot(8000, lambda: self._check_stop_timeout(generation))

    def _signal_stop(self):
        if self._stop_event is not None:
            self._stop_event.set()

    def _check_stop_timeout(self, generation):
        if (
            self.has_thread
            and self._generation == generation
            and self._stop_requested.is_set()
        ):
            # Python 스레드를 강제 종료하거나 끝났다고 거짓 보고하지 않는다.
            self._receive_state(
                replace(self.state, running=False, code="shutdown_timeout")
            )

    @pyqtSlot()
    def _finish_thread(self):
        if self._thread is not None and self._thread.is_alive():
            QTimer.singleShot(10, self._finish_thread)
            return
        self.adapter.disable()
        self.adapter.detach()
        self._thread = self._loop = None
        self._action_pending = False
        self.stopped.emit()

    @pyqtSlot()
    def _finish_action(self):
        self._action_pending = False

    def _schedule(self, operation, *args):
        if (
            not self.state.running
            or self._loop is None
            or self._stop_requested.is_set()
        ):
            self.operation_failed.emit("gateway_unavailable")
            return
        if self._action_pending:
            self.operation_failed.emit("gateway_busy")
            return
        self._action_pending = True
        future = asyncio.run_coroutine_threadsafe(
            self._run_action(operation, args), self._loop
        )
        future.add_done_callback(lambda completed: self._action_done.emit())

    async def _run_action(self, operation, args):
        try:
            gateway = self._gateway
            if gateway is None:
                raise PairingError("gateway_unavailable")
            if operation == "qr":
                await gateway.issue_qr(*args)
            elif operation == "approve":
                await gateway.approve(*args)
            elif operation == "reject":
                await gateway.reject(*args)
            elif operation == "revoke":
                await gateway.revoke()
        except (PairingError, StorageError, AdapterError) as error:
            self.operation_failed.emit(error.code)
        except Exception:
            self.operation_failed.emit("operation_failed")

    def request_qr(self):
        if not self.state.running:
            self.operation_failed.emit("gateway_unavailable")
            return
        endpoints = self._endpoint_provider(self.state.port)
        self._schedule("qr", endpoints)

    def approve(self, pairing_id, connection_id):
        self._schedule("approve", pairing_id, connection_id)

    def reject(self, pairing_id):
        self._schedule("reject", pairing_id)

    def revoke(self):
        self._schedule("revoke")

    def reset_tls(self):
        """확인창을 거친 PC 호출 전용이다. 네트워크 실행 중에는 초기화하지 않는다."""
        if self.has_thread:
            self.operation_failed.emit("tls_stop_first")
            return
        self.adapter.disable()
        self._stop_requested.clear()
        self._generation = str(uuid4())
        self._receive_state(
            GatewayState(
                False, None, self.state.registered, None, None, "tls_resetting"
            )
        )
        self._thread = threading.Thread(
            target=self._reset_tls_main, name="ene-companion-tls-reset", daemon=True
        )
        self._thread.start()

    def _reset_tls_main(self):
        code = "tls_reset_complete"
        try:
            with TlsIdentityStore(self._store_factory()) as store:
                store.reset()
        except (StorageError, PrivateFileError, TlsError) as error:
            code = error.code
        except Exception:
            code = "tls_reset_failed"
        finally:
            self._network_state.emit(GatewayState(False, None, False, None, None, code))
            self._thread_done.emit()
