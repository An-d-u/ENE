"""Windows 전용 키 폴더의 현재 사용자/SYSTEM DACL만 생성·검증한다."""

from contextlib import contextmanager
import ctypes as C
from ctypes import wintypes as W


_advapi = C.WinDLL("advapi32", use_last_error=True)
_kernel = C.WinDLL("kernel32", use_last_error=True)
P = C.c_void_p
PP = C.POINTER(P)


def _function(library, name, result, *arguments):
    function = getattr(library, name)
    function.restype, function.argtypes = result, list(arguments)
    return function


_free = _function(_kernel, "LocalFree", P, P)
_close = _function(_kernel, "CloseHandle", W.BOOL, W.HANDLE)
_process = _function(_kernel, "GetCurrentProcess", W.HANDLE)
_open_token = _function(
    _advapi, "OpenProcessToken", W.BOOL, W.HANDLE, W.DWORD, C.POINTER(W.HANDLE)
)
_token_info = _function(
    _advapi,
    "GetTokenInformation",
    W.BOOL,
    W.HANDLE,
    C.c_int,
    P,
    W.DWORD,
    C.POINTER(W.DWORD),
)
_sid_text = _function(_advapi, "ConvertSidToStringSidW", W.BOOL, P, C.POINTER(W.LPWSTR))
_parse_sd = _function(
    _advapi,
    "ConvertStringSecurityDescriptorToSecurityDescriptorW",
    W.BOOL,
    W.LPCWSTR,
    W.DWORD,
    PP,
    C.POINTER(W.DWORD),
)
_get_owner = _function(
    _advapi, "GetSecurityDescriptorOwner", W.BOOL, P, PP, C.POINTER(W.BOOL)
)
_get_dacl = _function(
    _advapi,
    "GetSecurityDescriptorDacl",
    W.BOOL,
    P,
    C.POINTER(W.BOOL),
    PP,
    C.POINTER(W.BOOL),
)
_set_info = _function(
    _advapi, "SetNamedSecurityInfoW", W.DWORD, W.LPWSTR, C.c_int, W.DWORD, P, P, P, P
)
_get_info = _function(
    _advapi,
    "GetNamedSecurityInfoW",
    W.DWORD,
    W.LPCWSTR,
    C.c_int,
    W.DWORD,
    PP,
    PP,
    PP,
    PP,
    PP,
)
_get_control = _function(
    _advapi,
    "GetSecurityDescriptorControl",
    W.BOOL,
    P,
    C.POINTER(W.WORD),
    C.POINTER(W.DWORD),
)
_acl_info = _function(_advapi, "GetAclInformation", W.BOOL, P, P, W.DWORD, C.c_int)
_get_ace = _function(_advapi, "GetAce", W.BOOL, P, W.DWORD, PP)


class _SecurityAttributes(C.Structure):
    _fields_ = [("length", W.DWORD), ("descriptor", P), ("inherit", W.BOOL)]


class _AclSize(C.Structure):
    _fields_ = [("count", W.DWORD), ("used", W.DWORD), ("free", W.DWORD)]


_mkdir = _function(
    _kernel, "CreateDirectoryW", W.BOOL, W.LPCWSTR, C.POINTER(_SecurityAttributes)
)


def _require(success):
    if not success:
        raise OSError("private_security_unavailable")


def _sid_string(sid):
    text = W.LPWSTR()
    _require(_sid_text(sid, C.byref(text)))
    try:
        return text.value
    finally:
        _free(C.cast(text, P))


def _current_sid():
    token = W.HANDLE()
    _require(_open_token(_process(), 0x8, C.byref(token)))
    try:
        size = W.DWORD()
        _token_info(token, 1, None, 0, C.byref(size))
        if not 0 < size.value <= 65536:
            raise OSError("private_security_unavailable")
        buffer = C.create_string_buffer(size.value)
        _require(_token_info(token, 1, buffer, size, C.byref(size)))
        return _sid_string(P.from_buffer(buffer))
    finally:
        _close(token)


@contextmanager
def _descriptor(directory):
    sid = _current_sid()
    flags = "OICI" if directory else ""
    descriptor = P()
    text = f"O:{sid}D:P(A;{flags};FA;;;{sid})(A;{flags};FA;;;SY)"
    _require(_parse_sd(text, 1, C.byref(descriptor), None))
    try:
        yield descriptor
    finally:
        _free(descriptor)


def create_directory(path):
    with _descriptor(True) as descriptor:
        attributes = _SecurityAttributes(
            C.sizeof(_SecurityAttributes), descriptor, False
        )
        if not _mkdir(str(path), C.byref(attributes)) and C.get_last_error() != 183:
            raise OSError("private_security_unavailable")


def protect_new_file(path):
    """보호 폴더 안에서 방금 만든 빈 파일에만 적용한다."""
    with _descriptor(False) as descriptor:
        owner, dacl = P(), P()
        defaulted, present = W.BOOL(), W.BOOL()
        _require(_get_owner(descriptor, C.byref(owner), C.byref(defaulted)))
        _require(
            _get_dacl(descriptor, C.byref(present), C.byref(dacl), C.byref(defaulted))
        )
        _require(_set_info(str(path), 1, 0x80000005, owner, None, dacl, None) == 0)


def verify_private(path, *, directory):
    owner, dacl, descriptor = P(), P(), P()
    _require(
        _get_info(
            str(path),
            1,
            0x5,
            C.byref(owner),
            None,
            C.byref(dacl),
            None,
            C.byref(descriptor),
        )
        == 0
    )
    try:
        sid = _current_sid()
        control, revision, size = W.WORD(), W.DWORD(), _AclSize()
        _require(_get_control(descriptor, C.byref(control), C.byref(revision)))
        if not dacl.value or not control.value & 0x1000 or _sid_string(owner) != sid:
            raise PermissionError("private_security_invalid")
        _require(_acl_info(dacl, C.byref(size), C.sizeof(size), 2))
        if size.count != 2:
            raise PermissionError("private_security_invalid")
        allowed = set()
        for index in range(size.count):
            ace = P()
            _require(_get_ace(dacl, index, C.byref(ace)))
            header = C.string_at(ace, 8)
            mask = int.from_bytes(header[4:8], "little")
            if (
                header[0] != 0
                or header[1] != (3 if directory else 0)
                or mask != 0x1F01FF
            ):
                raise PermissionError("private_security_invalid")
            allowed.add(_sid_string(P(ace.value + 8)))
        if allowed != {sid, "S-1-5-18"}:
            raise PermissionError("private_security_invalid")
    finally:
        _free(descriptor)
