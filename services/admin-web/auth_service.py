from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from ldap3 import Connection, NONE, Server
from ldap3.core.exceptions import LDAPException

from config import (
    AUTH_MODE,
    AUTH_SESSION_SECRET,
    AUTH_SESSION_TTL_SECONDS,
    LDAP_ADMIN_USERS,
    LDAP_BASE_DN,
    LDAP_CONNECT_TIMEOUT_SECONDS,
    LDAP_URL,
    LDAP_USERS_RDN,
)

_USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class AuthenticationError(ValueError):
    pass


@dataclass(frozen=True)
class AuthUser:
    username: str
    role: str

    def as_dict(self) -> dict[str, str]:
        return {"username": self.username, "role": self.role}


def auth_enabled() -> bool:
    return AUTH_MODE == "ldap"


def local_admin() -> AuthUser:
    return AuthUser(username="local-admin", role="admin")


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _session_secret() -> bytes:
    if len(AUTH_SESSION_SECRET) < 32:
        raise AuthenticationError("AUTH_SESSION_SECRET is not configured")
    return AUTH_SESSION_SECRET.encode("utf-8")


def _normalize_username(username: str) -> str:
    normalized = username.strip()
    if not _USERNAME_RE.fullmatch(normalized):
        raise AuthenticationError("用户名格式不正确")
    return normalized


def _ldap_server() -> Server:
    parsed = urlparse(LDAP_URL)
    if parsed.scheme not in {"ldap", "ldaps"} or not parsed.hostname:
        raise AuthenticationError("LDAP_URL must use ldap:// or ldaps://")
    return Server(
        parsed.hostname,
        port=parsed.port or (636 if parsed.scheme == "ldaps" else 389),
        use_ssl=parsed.scheme == "ldaps",
        get_info=NONE,
        connect_timeout=LDAP_CONNECT_TIMEOUT_SECONDS,
    )


def _user_dn(username: str) -> str:
    if not LDAP_BASE_DN:
        raise AuthenticationError("LDAP_BASE_DN is not configured")
    return f"uid={username},{LDAP_USERS_RDN},{LDAP_BASE_DN}"


def authenticate_ldap(username: str, password: str) -> AuthUser:
    if not auth_enabled():
        return local_admin()
    normalized_username = _normalize_username(username)
    if not password:
        raise AuthenticationError("请输入密码")
    if normalized_username not in LDAP_ADMIN_USERS:
        raise AuthenticationError("该 LDAP 用户尚未获授 Knowledge Hub 管理权限")

    connection: Connection | None = None
    try:
        connection = Connection(
            _ldap_server(),
            user=_user_dn(normalized_username),
            password=password,
            receive_timeout=LDAP_CONNECT_TIMEOUT_SECONDS,
            raise_exceptions=False,
        )
        if not connection.bind():
            raise AuthenticationError("用户名或密码错误")
    except AuthenticationError:
        raise
    except LDAPException as exc:
        raise AuthenticationError("LDAP 连接或认证失败") from exc
    except Exception as exc:
        raise AuthenticationError("LDAP 服务暂时不可用") from exc
    finally:
        if connection and connection.bound:
            connection.unbind()
    return AuthUser(username=normalized_username, role="admin")


def issue_session(user: AuthUser) -> str:
    now = int(time.time())
    payload = {
        "username": user.username,
        "role": user.role,
        "issued_at": now,
        "expires_at": now + AUTH_SESSION_TTL_SECONDS,
    }
    encoded_payload = _base64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = hmac.new(
        _session_secret(), encoded_payload.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{encoded_payload}.{_base64url_encode(signature)}"


def parse_session(token: str | None) -> AuthUser | None:
    if not auth_enabled():
        return local_admin()
    if not token or "." not in token:
        return None
    encoded_payload, encoded_signature = token.rsplit(".", 1)
    try:
        expected_signature = hmac.new(
            _session_secret(), encoded_payload.encode("ascii"), hashlib.sha256
        ).digest()
        supplied_signature = _base64url_decode(encoded_signature)
        if not hmac.compare_digest(expected_signature, supplied_signature):
            return None
        payload = json.loads(_base64url_decode(encoded_payload))
        username = _normalize_username(str(payload["username"]))
        if (
            payload.get("role") != "admin"
            or username not in LDAP_ADMIN_USERS
            or int(payload["expires_at"]) < int(time.time())
        ):
            return None
    except (AuthenticationError, KeyError, ValueError, TypeError, json.JSONDecodeError):
        return None
    return AuthUser(username=username, role="admin")
