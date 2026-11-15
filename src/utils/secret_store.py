"""Encrypt small secrets (the saved UTAR password) with the OS.

Windows: DPAPI (CryptProtectData) through ctypes. The ciphertext can only be
decrypted by the same Windows user on the same computer, and no key is kept in
the program or the database. No extra dependency is needed.

Other platforms: not supported. `available()` is False and callers must not
store the secret (the app then remembers only the student ID).
"""

import base64
import sys

PREFIX = "dpapi:"
_ENTROPY = b"utar-course-bidding/credentials/v1"


def available() -> bool:
    return sys.platform == "win32"


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32
    _CRYPTPROTECT_UI_FORBIDDEN = 0x01

    def _blob(data: bytes):
        buffer = ctypes.create_string_buffer(data, len(data))
        return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer

    def _call(function, data: bytes) -> bytes:
        source, _keep = _blob(data)
        entropy, _keep_entropy = _blob(_ENTROPY)
        result = _Blob()
        if not function(ctypes.byref(source), None, ctypes.byref(entropy), None, None,
                        _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(result)):
            raise OSError(ctypes.get_last_error() or "DPAPI call failed")
        try:
            return ctypes.string_at(result.pbData, result.cbData)
        finally:
            _kernel32.LocalFree(result.pbData)

    def _protect(data: bytes) -> bytes:
        return _call(_crypt32.CryptProtectData, data)

    def _unprotect(data: bytes) -> bytes:
        # CryptUnprotectData's second argument is an out-pointer for the description.
        return _call(_crypt32.CryptUnprotectData, data)


def protect(text: str) -> str:
    """Encrypt text; returns an ASCII string that is safe to store."""
    if not available():
        raise RuntimeError("Secure password storage is only available on Windows")
    return PREFIX + base64.b64encode(_protect(text.encode("utf-8"))).decode("ascii")


def unprotect(stored: str) -> str:
    """Decrypt a value from protect(). Raises ValueError if it cannot be read."""
    if not stored:
        return ""
    if not stored.startswith(PREFIX) or not available():
        raise ValueError("Stored secret is not in a supported format")
    try:
        return _unprotect(base64.b64decode(stored[len(PREFIX):])).decode("utf-8")
    except Exception as error:  # noqa: BLE001 - another user/PC, or corrupted
        raise ValueError(f"Stored secret could not be decrypted: {error}") from error
