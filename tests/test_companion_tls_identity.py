"""TLS 시험의 키·인증서는 매번 새로 만들며 실제 등록을 읽지 않는다."""

import base64
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.x509.oid import ExtendedKeyUsageOID
import pytest

from tests.companion_helpers import sample_id


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
CASES = json.loads(
    (Path(__file__).parents[1] / "contracts/companion/v1/tls_cases.json").read_text(
        encoding="utf-8"
    )
)


def test_each_installation_has_a_unique_ca_and_valid_leaf():
    from src.core.companion.tls_identity import TlsIdentity, TrustAnchor

    first = TlsIdentity.create(sample_id(1), NOW)
    other = TlsIdentity.create(sample_id(2), NOW)
    anchor = TrustAnchor.parse(first.ca_certificate, sample_id(1), NOW)
    assert first.ca_sha256 != other.ca_sha256
    assert anchor.hostname == f"ene-{sample_id(1)}.invalid"
    assert len(anchor.der) <= 768
    assert anchor.certificate.extensions.get_extension_for_class(
        x509.BasicConstraints
    ).value == x509.BasicConstraints(True, 0)
    assert anchor.certificate.public_key().curve.name == "secp256r1"
    leaf = first.leaf
    leaf.verify_directly_issued_by(anchor.certificate)
    assert leaf.extensions.get_extension_for_class(
        x509.SubjectAlternativeName
    ).value.get_values_for_type(x509.DNSName) == [anchor.hostname]
    assert (
        ExtendedKeyUsageOID.SERVER_AUTH
        in leaf.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    )
    assert (
        leaf.extensions.get_extension_for_class(x509.BasicConstraints).value.ca is False
    )
    assert first.leaf_not_after == NOW + timedelta(days=90)
    assert first.leaf_not_after < first.ca_not_after


def test_identity_round_trip_preserves_keys_without_printing_them():
    from src.core.companion.tls_identity import TlsIdentity

    identity = TlsIdentity.create(sample_id(1), NOW)
    restored = TlsIdentity.from_record(identity.to_record(), NOW)
    assert restored.ca_certificate == identity.ca_certificate
    assert restored.leaf_key_pem == identity.leaf_key_pem
    assert restored.leaf_certificate == identity.leaf_certificate
    assert "PRIVATE" not in repr(restored)
    assert identity.ca_certificate not in repr(restored)


@pytest.mark.parametrize("case", CASES["anchor_cases"], ids=lambda case: case["id"])
def test_anchor_rejects_bad_or_unbound_input(case):
    from src.core.companion.tls_identity import TlsError, TlsIdentity, TrustAnchor

    identity = TlsIdentity.create(sample_id(1), NOW)
    value, server_id = identity.ca_certificate, sample_id(1)
    variant = case["mutation"]
    if variant == "wrong-id":
        server_id = sample_id(2)
    elif variant == "extra-der":
        value = base64.b64encode(base64.b64decode(value) + b"extra").decode()
    elif variant == "noncanonical":
        value += "\n"
    elif variant == "oversize":
        value = base64.b64encode(b"x" * 769).decode()
    elif variant == "leaf-as-ca":
        value = identity.leaf_certificate
    elif variant == "garbage":
        value = "not-a-certificate"
    elif variant == "missing":
        value = None
    elif variant != "none":
        pytest.fail("정의되지 않은 공통 계약 변형")
    if case["accepted"]:
        assert TrustAnchor.parse(value, server_id, NOW).sha256 == identity.ca_sha256
        return
    with pytest.raises(TlsError):
        TrustAnchor.parse(value, server_id, NOW)


@pytest.mark.parametrize(
    "moment", [NOW - timedelta(minutes=6), NOW + timedelta(days=3650)]
)
def test_anchor_checks_its_own_validity_on_every_use(moment):
    from src.core.companion.tls_identity import TlsError, TlsIdentity, TrustAnchor

    identity = TlsIdentity.create(sample_id(1), NOW)
    with pytest.raises(TlsError):
        TrustAnchor.parse(identity.ca_certificate, sample_id(1), moment)


def test_leaf_renewal_preserves_ca_and_replaces_server_key():
    from src.core.companion.tls_identity import TlsIdentity

    identity = TlsIdentity.create(sample_id(1), NOW)
    later = NOW + timedelta(days=61)
    assert not identity.renewal_due(NOW)
    assert identity.renewal_due(later)
    renewed = identity.renew(later)
    assert renewed.ca_certificate == identity.ca_certificate
    assert renewed.leaf_key_pem != identity.leaf_key_pem
    assert renewed.leaf_not_after == later + timedelta(days=90)
    assert not renewed.renewal_due(later)


def test_near_ca_expiry_requires_local_repair_instead_of_renewal_loop():
    from src.core.companion.tls_identity import TlsError, TlsIdentity

    identity = TlsIdentity.create(sample_id(1), NOW)
    near = identity.ca_not_after - timedelta(days=30)
    assert identity.ca_repair_due(near)
    assert not identity.renewal_due(near)
    with pytest.raises(TlsError, match="tls_repair_required"):
        identity.renew(near)


@pytest.mark.parametrize(
    "variant",
    ["ca-key", "leaf-key", "leaf-cert", "server-id", "version", "extra-field"],
)
def test_storage_record_rejects_mixed_identity_parts(variant):
    from src.core.companion.tls_identity import TlsError, TlsIdentity

    first = TlsIdentity.create(sample_id(1), NOW)
    other = TlsIdentity.create(sample_id(2), NOW)
    payload = first.to_record()
    if variant in {"ca-key", "leaf-key", "leaf-cert"}:
        key = {
            "ca-key": "ca_key_pem",
            "leaf-key": "leaf_key_pem",
            "leaf-cert": "leaf_certificate",
        }[variant]
        payload[key] = other.to_record()[key]
    elif variant == "server-id":
        payload["server_id"] = sample_id(2)
    elif variant == "version":
        payload["version"] = True
    else:
        payload["extra"] = 1
    with pytest.raises(TlsError):
        TlsIdentity.from_record(payload, NOW)


def test_expired_leaf_can_be_loaded_for_renewal_but_not_for_connection():
    from src.core.companion.tls_identity import TlsError, TlsIdentity

    original = TlsIdentity.create(sample_id(1), NOW)
    later = NOW + timedelta(days=91)
    loaded = TlsIdentity.from_record(original.to_record(), later)
    with pytest.raises(TlsError, match="tls_expired"):
        loaded.validate_connection(later)
    loaded.renew(later).validate_connection(later)
    assert b"CERTIFICATE" in loaded.leaf.public_bytes(serialization.Encoding.PEM)
