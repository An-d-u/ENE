"""LAN 후보 선택과 메모리 QR 생성의 경계를 확인한다."""

import pytest


def test_candidates_filter_unreachable_local_addresses_and_preserve_order():
    from src.core.companion.network import select_endpoints

    candidates = [
        "0.0.0.0",
        "127.0.0.1",
        "224.0.0.1",
        "::1",
        "192.0.2.10",
        "192.0.2.10",
        "100.64.0.2",
        "198.51.100.10",
    ]
    endpoints = select_endpoints(candidates, 8765, preferred_host="100.64.0.2")
    assert [item.host for item in endpoints] == [
        "100.64.0.2",
        "192.0.2.10",
        "198.51.100.10",
    ]
    assert all(item.port == 8765 for item in endpoints)


def test_candidates_are_bounded_without_private_subnet_assumption():
    from src.core.companion.network import select_endpoints

    assert (
        len(select_endpoints([f"192.0.2.{index}" for index in range(1, 30)], 8765)) == 8
    )
    assert select_endpoints(["203.0.113.10"], 8765)


@pytest.mark.parametrize(
    "host,port",
    [
        ("http://pc", 8765),
        ("pc/path", 8765),
        ("user@pc", 8765),
        ("pc?x", 8765),
        ("pc", 0),
        ("pc", 65536),
        ("pc", True),
        ("", 8765),
        ("::1", 8765),
        ("pc\\path", 8765),
    ],
)
def test_invalid_manual_endpoints_are_rejected(host, port):
    from src.core.companion.network import NetworkError, normalize_endpoint

    with pytest.raises(NetworkError):
        normalize_endpoint(host, port)


def test_manual_endpoint_allows_hostname_and_configurable_port():
    from src.core.companion.network import normalize_endpoint

    endpoint = normalize_endpoint("  ene-pc.local  ", 9876)
    assert endpoint.host == "ene-pc.local" and endpoint.port == 9876


def test_qr_is_immutable_boolean_matrix_with_quiet_zone():
    from src.core.companion.network import qr_matrix

    matrix = qr_matrix('{"purpose":"가상 연결 시험"}')
    assert isinstance(matrix, tuple) and len(matrix) >= 29
    assert all(isinstance(row, tuple) and len(row) == len(matrix) for row in matrix)
    assert all(type(cell) is bool for row in matrix for cell in row)
    assert not any(cell for row in matrix[:4] for cell in row)


def test_oversize_qr_is_rejected_without_creating_an_image():
    from src.core.companion.network import NetworkError, qr_matrix

    with pytest.raises(NetworkError, match="qr_too_large"):
        qr_matrix("x" * 2049)


def test_discovery_reads_only_up_running_nonloopback_qt_interfaces(monkeypatch):
    from types import SimpleNamespace
    from PyQt6.QtNetwork import QHostAddress, QNetworkInterface
    from src.core.companion import network

    flags = QNetworkInterface.InterfaceFlag

    def interface(value, addresses):
        return SimpleNamespace(
            flags=lambda: value,
            addressEntries=lambda: [
                SimpleNamespace(ip=lambda address=address: QHostAddress(address))
                for address in addresses
            ],
        )

    interfaces = [
        interface(flags.IsUp | flags.IsRunning, ["192.0.2.10", "::1"]),
        interface(flags.IsUp, ["192.0.2.20"]),
        interface(flags.IsUp | flags.IsRunning | flags.IsLoopBack, ["127.0.0.1"]),
    ]
    monkeypatch.setattr(
        network,
        "QNetworkInterface",
        SimpleNamespace(InterfaceFlag=flags, allInterfaces=lambda: interfaces),
    )
    assert [endpoint.host for endpoint in network.discover_endpoints(8765)] == [
        "192.0.2.10"
    ]
