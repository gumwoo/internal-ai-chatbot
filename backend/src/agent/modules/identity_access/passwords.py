"""비밀번호 해시(표준 라이브러리 scrypt). 형식: scrypt$n$r$p$salt_b64$hash_b64."""

import base64
import hashlib
import hmac
import secrets
from functools import cache

_N, _R, _P, _LEN = 2**14, 8, 1, 32


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_LEN)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str | None) -> bool:
    """해시가 맞으면 True. 해시가 없거나(웹 로그인 없음·계정 없음) 형식이 틀리면 False.

    계정이 없을 때도 같은 비용의 계산을 해, 응답 시간으로 계정 존재를 짐작하지 못하게 한다.
    """
    if stored is None:
        _matches(password, _dummy_hash())
        return False
    return _matches(password, stored)


def _matches(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, expected = stored.split("$")
        if scheme != "scrypt":
            return False
        expected_raw = base64.b64decode(expected)
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=base64.b64decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected_raw),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected_raw)


@cache
def _dummy_hash() -> str:
    return hash_password(secrets.token_hex(8))


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


# 첫 "계정 없음" 로그인만 느려지지 않게 import 때 미리 만든다.
_dummy_hash()
