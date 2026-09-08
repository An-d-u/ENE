"""Qt의 활성 IPv4 후보와 수동 주소를 정규화하고 QR 행렬만 생성한다."""

from dataclasses import dataclass
import ipaddress
import re

from PyQt6.QtCore import QCoreApplication, QThread
from PyQt6.QtNetwork import QNetworkInterface
import qrcode


class NetworkError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Endpoint:
    host: str
    port: int

    def to_dict(self):
        return {"host": self.host, "port": self.port}


def normalize_endpoint(host, port):
    if not isinstance(host, str) or type(port) is not int or not 1 <= port <= 65535:
        raise NetworkError("invalid_endpoint")
    host = host.strip()
    if not host or len(host) > 253 or any(char in host for char in "/\\@?#"):
        raise NetworkError("invalid_endpoint")
    if ":" in host:
        raise NetworkError("unsupported_address_family")
    try:
        address = ipaddress.ip_address(host)
        if not isinstance(address, ipaddress.IPv4Address):
            raise NetworkError("unsupported_address_family")
        host = str(address)
    except ValueError:
        if re.fullmatch(r"[0-9.]+", host) or not all(
            re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
            for label in host.rstrip(".").split(".")
        ):
            raise NetworkError("invalid_endpoint") from None
        host = host.lower()
    return Endpoint(host, port)


def select_endpoints(addresses, port, *, preferred_host=None):
    normalize_endpoint("validation.local", port)
    selected = []
    for raw in addresses:
        if not isinstance(raw, str):
            continue
        try:
            address = ipaddress.IPv4Address(raw)
        except ipaddress.AddressValueError:
            continue
        if (
            address.is_loopback
            or address.is_multicast
            or address.is_unspecified
            or str(address) == "255.255.255.255"
        ):
            continue
        host = str(address)
        if host not in selected:
            selected.append(host)
    if preferred_host in selected:
        selected.remove(preferred_host)
        selected.insert(0, preferred_host)
    return tuple(Endpoint(host, port) for host in selected[:8])


def discover_endpoints(port, *, preferred_host=None):
    app = QCoreApplication.instance()
    if app is not None and QThread.currentThread() != app.thread():
        raise NetworkError("wrong_thread")
    flags = QNetworkInterface.InterfaceFlag
    required = flags.IsUp | flags.IsRunning
    addresses = []
    for interface in QNetworkInterface.allInterfaces():
        status = interface.flags()
        if (status & required) != required or status & flags.IsLoopBack:
            continue
        addresses.extend(entry.ip().toString() for entry in interface.addressEntries())
    return select_endpoints(addresses, port, preferred_host=preferred_host)


def qr_matrix(payload):
    try:
        raw = payload.encode("utf-8")
    except (AttributeError, UnicodeError):
        raise NetworkError("invalid_qr") from None
    if len(raw) > 2048:
        raise NetworkError("qr_too_large")
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=1, border=4
    )
    qr.add_data(raw, optimize=0)
    qr.make(fit=True)
    return tuple(tuple(bool(cell) for cell in row) for row in qr.get_matrix())
