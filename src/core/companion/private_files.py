"""접근 제한이 확인된 전용 디렉터리 안에서만 키 파일을 다룬다."""

from contextlib import contextmanager
import os
from pathlib import Path
import re
import stat
from uuid import uuid4

from src.core.app_paths import _replace_file_atomic_durable


class PrivateFileError(OSError):
    def __init__(self, code="tls_storage_unavailable"):
        self.code = code
        super().__init__(code)


def _no_link(path, *, directory):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise PrivateFileError("tls_storage_unsafe")
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(info.st_mode) or (not directory and info.st_nlink != 1):
        raise PrivateFileError("tls_storage_unsafe")
    return info


def _verify_permissions(path, *, directory):
    info = _no_link(path, directory=directory)
    try:
        if os.name == "nt":
            from .windows_private_files import verify_private

            verify_private(path, directory=directory)
        elif info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != (
            0o700 if directory else 0o600
        ):
            raise PermissionError()
    except OSError:
        raise PrivateFileError("tls_storage_unsafe") from None


class PrivateDirectory:
    def __init__(self, path):
        self.path = Path(path).absolute()
        try:
            for parent in reversed(self.path.parents):
                _no_link(parent, directory=True)
            if not self.path.exists():
                if os.name == "nt":
                    from .windows_private_files import create_directory

                    create_directory(self.path)
                else:
                    self.path.mkdir(mode=0o700)
            self.verify()
        except PrivateFileError:
            raise
        except OSError:
            raise PrivateFileError() from None

    def verify(self):
        _verify_permissions(self.path, directory=True)

    @contextmanager
    def lease(self):
        """잠금 파일을 교체·삭제하지 않아 프로세스 간 동일 잠금을 유지한다."""
        path = self._target("identity.lock")
        try:
            self._new_file("identity.lock", b"\0")
        except FileExistsError:
            pass
        _verify_permissions(path, directory=False)
        descriptor = os.open(
            path, os.O_RDWR | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        )
        locked = False
        try:
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except OSError:
                raise PrivateFileError("tls_storage_in_use") from None
            yield self
        finally:
            try:
                if locked:
                    if os.name == "nt":
                        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def _target(self, name):
        if (
            not isinstance(name, str)
            or len(name) > 100
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+)?", name)
        ):
            raise PrivateFileError("tls_storage_unsafe")
        if re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]", name.split(".")[0], re.I):
            raise PrivateFileError("tls_storage_unsafe")
        self.verify()
        return self.path / name

    def read(self, name, *, max_bytes=16384):
        path = self._target(name)
        try:
            _verify_permissions(path, directory=False)
            with path.open("rb") as stream:
                raw = stream.read(max_bytes + 1)
            if len(raw) > max_bytes:
                raise PrivateFileError("tls_storage_invalid")
            return raw
        except FileNotFoundError:
            return None
        except PrivateFileError:
            raise
        except OSError:
            raise PrivateFileError() from None

    def _new_file(self, name, payload):
        path = self._target(name)
        descriptor = os.open(
            path,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            if os.name == "nt":
                from .windows_private_files import protect_new_file

                protect_new_file(path)
            _verify_permissions(path, directory=False)
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = None
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            return path
        except BaseException:
            if descriptor is not None:
                os.close(descriptor)
            path.unlink(missing_ok=True)
            raise

    def atomic_write(self, name, payload, *, replace_file=_replace_file_atomic_durable):
        target = self._target(name)
        before = self.read(name)
        temporary = None
        try:
            temporary = self._new_file(f"tls-write-{uuid4().hex}.tmp", payload)
            replace_file(temporary, target)
            temporary = None
            if self.read(name) != payload:
                raise PrivateFileError("tls_storage_uncertain")
        except Exception:
            try:
                unchanged = self.read(name) == before
            except OSError:
                unchanged = False
            raise PrivateFileError(
                "tls_write_failed" if unchanged else "tls_storage_uncertain"
            ) from None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @contextmanager
    def temporary_file(self, payload):
        path = self._new_file(f"tls-load-{uuid4().hex}.pem", payload)
        try:
            yield path
        finally:
            path.unlink(missing_ok=True)

    def cleanup_temporary(self):
        """호출자는 이 신원 디렉터리의 단독 사용을 먼저 확보해야 한다."""
        self.verify()
        for path in self.path.iterdir():
            if re.fullmatch(
                r"tls-(?:load-[0-9a-f]{32}\.pem|write-[0-9a-f]{32}\.tmp)", path.name
            ):
                _verify_permissions(path, directory=False)
                path.unlink()
