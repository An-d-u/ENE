"""시험 소유 임시 폴더 안에서만 OS 접근 제한과 원자 보관을 검증한다."""

import json
import os
import stat
import subprocess

import pytest


def test_new_directory_and_written_file_have_private_os_permissions(tmp_path):
    from src.core.companion.private_files import PrivateDirectory

    folder = PrivateDirectory(tmp_path / "tls")
    folder.atomic_write("identity.json", b"synthetic-key-material")
    assert folder.read("identity.json") == b"synthetic-key-material"
    folder.verify()
    if os.name == "nt":
        environment = {
            **os.environ,
            "ENE_TLS_TEST_PATH": str(folder.path / "identity.json"),
        }
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "$a=Get-Acl -LiteralPath $env:ENE_TLS_TEST_PATH; "
                "[pscustomobject]@{Protected=$a.AreAccessRulesProtected; "
                "Count=@($a.Access).Count; Inherited=@($a.Access | Where-Object IsInherited).Count} | ConvertTo-Json -Compress",
            ],
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        assert json.loads(result.stdout) == {
            "Protected": True,
            "Count": 2,
            "Inherited": 0,
        }
    else:
        assert stat.S_IMODE(folder.path.stat().st_mode) == 0o700
        assert stat.S_IMODE((folder.path / "identity.json").stat().st_mode) == 0o600


def test_existing_unrestricted_directory_is_rejected_without_modifying_it(tmp_path):
    from src.core.companion.private_files import PrivateDirectory, PrivateFileError

    path = tmp_path / "unrestricted"
    path.mkdir(mode=0o755)
    if os.name != "nt":
        path.chmod(0o755)
    (path / "keep.txt").write_text("가상 보존 자료", encoding="utf-8")
    with pytest.raises(PrivateFileError, match="tls_storage_unsafe"):
        PrivateDirectory(path)
    assert (path / "keep.txt").read_text(encoding="utf-8") == "가상 보존 자료"


@pytest.mark.parametrize("name", ["../outside", ".", "..", "a/b", "a\\b", "C:outside"])
def test_file_names_cannot_escape_protected_directory(tmp_path, name):
    from src.core.companion.private_files import PrivateDirectory, PrivateFileError

    folder = PrivateDirectory(tmp_path / "tls")
    with pytest.raises(PrivateFileError):
        folder.atomic_write(name, b"synthetic")
    assert list(folder.path.iterdir()) == []


def test_temporary_key_file_is_removed_on_success_and_failure(tmp_path):
    from src.core.companion.private_files import PrivateDirectory

    folder = PrivateDirectory(tmp_path / "tls")
    with folder.temporary_file(b"synthetic") as path:
        assert path.parent == folder.path
        assert path.read_bytes() == b"synthetic"
    assert not path.exists()
    with pytest.raises(RuntimeError):
        with folder.temporary_file(b"synthetic") as failed:
            raise RuntimeError("가상 로더 실패")
    assert not failed.exists()


def test_atomic_failure_preserves_old_bytes_and_removes_staging_file(tmp_path):
    from src.core.companion.private_files import PrivateDirectory, PrivateFileError

    folder = PrivateDirectory(tmp_path / "tls")
    folder.atomic_write("identity.json", b"before")

    def fail_replace(_source, _target):
        raise OSError("가상 저장 실패")

    with pytest.raises(PrivateFileError, match="tls_write_failed"):
        folder.atomic_write("identity.json", b"after", replace_file=fail_replace)
    assert folder.read("identity.json") == b"before"
    assert [item.name for item in folder.path.iterdir()] == ["identity.json"]


def test_after_replace_failure_is_reported_as_uncertain(tmp_path):
    from src.core.companion.private_files import PrivateDirectory, PrivateFileError

    folder = PrivateDirectory(tmp_path / "tls")
    folder.atomic_write("identity.json", b"before")

    def fail_after_replace(source, target):
        os.replace(source, target)
        raise OSError("가상 내구 확인 실패")

    with pytest.raises(PrivateFileError, match="tls_storage_uncertain"):
        folder.atomic_write("identity.json", b"after", replace_file=fail_after_replace)


def test_hard_link_file_is_not_accepted(tmp_path):
    from src.core.companion.private_files import PrivateDirectory, PrivateFileError

    folder = PrivateDirectory(tmp_path / "tls")
    folder.atomic_write("identity.json", b"synthetic")
    linked = tmp_path / "linked.json"
    os.link(folder.path / "identity.json", linked)
    with pytest.raises(PrivateFileError, match="tls_storage_unsafe"):
        folder.read("identity.json")


def test_oversize_read_is_rejected(tmp_path):
    from src.core.companion.private_files import PrivateDirectory, PrivateFileError

    folder = PrivateDirectory(tmp_path / "tls")
    folder.atomic_write("identity.json", b"x" * 33)
    with pytest.raises(PrivateFileError, match="tls_storage_invalid"):
        folder.read("identity.json", max_bytes=32)


def test_cleanup_only_removes_recognized_owned_temporary_files(tmp_path):
    from src.core.companion.private_files import PrivateDirectory

    folder = PrivateDirectory(tmp_path / "tls")
    stale = "tls-load-" + "0" * 32 + ".pem"
    folder.atomic_write(stale, b"synthetic")
    folder.atomic_write("keep.pem", b"preserve")
    folder.cleanup_temporary()
    assert not (folder.path / stale).exists()
    assert folder.read("keep.pem") == b"preserve"


def test_directory_symlink_is_rejected_without_touching_target(tmp_path):
    from src.core.companion.private_files import PrivateDirectory, PrivateFileError

    target = PrivateDirectory(tmp_path / "tls")
    target.atomic_write("keep.json", b"preserve")
    link = tmp_path / "link"
    try:
        link.symlink_to(target.path, target_is_directory=True)
    except OSError:
        pytest.skip("현재 시험 계정에 심볼릭 링크 생성 권한 없음")
    try:
        with pytest.raises(PrivateFileError, match="tls_storage_unsafe"):
            PrivateDirectory(link)
        assert target.read("keep.json") == b"preserve"
    finally:
        link.unlink()


def test_two_owners_cannot_use_the_identity_directory_concurrently(tmp_path):
    from src.core.companion.private_files import PrivateDirectory, PrivateFileError

    first = PrivateDirectory(tmp_path / "tls")
    second = PrivateDirectory(first.path)
    with first.lease():
        with pytest.raises(PrivateFileError, match="tls_storage_in_use"):
            with second.lease():
                pytest.fail("동시에 두 보관 소유자가 들어오면 안 됨")
    with second.lease():
        second.atomic_write("identity.json", b"after-release")
