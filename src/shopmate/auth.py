"""Direct-user authentication and host-bound merchant delegation."""

from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt
from fastapi import HTTPException

MERCHANT_SCOPES = frozenset(
    {"merchant:read", "merchant:price:prepare", "merchant:price:read", "merchant:price:cancel"}
)


@dataclass(frozen=True)
class RequestIdentity:
    subject: str
    token: str = field(repr=False)


@dataclass(frozen=True)
class BoundContext:
    identity: RequestIdentity
    session_id: str
    turn_id: str | None = None


_context: ContextVar[BoundContext] = ContextVar("shopmate_request_context")


def current_context() -> BoundContext:
    return _context.get()


@contextmanager
def bind_context(identity: RequestIdentity, session_id: str, turn_id: str | None = None):
    handle = _context.set(BoundContext(identity, session_id, turn_id))
    try:
        yield _context.get()
    finally:
        _context.reset(handle)


class AuthClient:
    def __init__(self, settings: Any, http_client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.http = http_client or httpx.AsyncClient(timeout=10, follow_redirects=False)
        self._owns_http = http_client is None
        self._keys: dict[str, Any] = {}
        self._keys_until = 0.0

    async def _request(self, method: str, url: str, **kwargs) -> dict:
        try:
            response = await self.http.request(method, url, **kwargs)
        except httpx.HTTPError:
            raise HTTPException(503, "Identity service unavailable") from None
        if response.status_code in (401, 403):
            raise HTTPException(response.status_code, "Authentication denied")
        if response.status_code != 200:
            raise HTTPException(503, "Identity service unavailable")
        try:
            result = response.json()
            if not isinstance(result, dict):
                raise TypeError()
            return result
        except (ValueError, TypeError):
            raise HTTPException(503, "Invalid identity response") from None

    async def _refresh_keys(self):
        data = await self._request("GET", self.settings.jwks_url)
        try:
            keys = data["keys"]
            if not isinstance(keys, list) or not keys:
                raise ValueError()
            parsed = {}
            for key in keys:
                kid = key["kid"]
                if not isinstance(kid, str) or not kid or kid in parsed or key.get("kty") != "RSA":
                    raise ValueError()
                if key.get("alg", "RS256") != "RS256" or key.get("use", "sig") != "sig":
                    raise ValueError()
                parsed[kid] = jwt.PyJWK.from_dict(key, algorithm="RS256").key
            self._keys = parsed
            self._keys_until = time.monotonic() + 30
        except (KeyError, TypeError, ValueError, jwt.PyJWTError):
            raise HTTPException(503, "Invalid identity key set") from None

    async def verify(self, token: str) -> RequestIdentity:
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if header.get("alg") != "RS256" or not isinstance(kid, str) or not kid:
                raise ValueError()
        except (jwt.PyJWTError, ValueError):
            raise HTTPException(401, "Invalid direct user token") from None
        if time.monotonic() >= self._keys_until or kid not in self._keys:
            await self._refresh_keys()
        if kid not in self._keys:
            raise HTTPException(401, "Invalid direct user token")
        try:
            claims = jwt.decode(
                token,
                self._keys[kid],
                algorithms=["RS256"],
                issuer=self.settings.issuer,
                audience=self.settings.user_audience,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
            audience = claims["aud"]
            if audience not in (self.settings.user_audience, [self.settings.user_audience]):
                raise ValueError()
            subject = claims["sub"]
            permissions = claims.get("permissions")
            if (
                not isinstance(subject, str)
                or not subject
                or len(subject) > 128
                or claims.get("token_type") != "direct_user"
                or claims.get("principal_state") != "ACTIVE"
                or any(key in claims for key in ("act", "sandbox", "evaluation_handle"))
                or not isinstance(permissions, list)
                or not all(isinstance(p, str) for p in permissions)
            ):
                raise ValueError()
        except (jwt.PyJWTError, ValueError, TypeError):
            raise HTTPException(401, "Invalid direct user token") from None
        if "merchant:session:create" not in permissions:
            raise HTTPException(403, "Merchant permission required")
        return RequestIdentity(subject, token)

    async def login(self, login_identifier: str, password: str) -> dict:
        result = await self._request(
            "POST",
            self.settings.auth_url.rstrip("/") + "/auth/login",
            json={"loginIdentifier": login_identifier, "password": password},
        )
        token = result.get("accessToken")
        if not isinstance(token, str):
            raise HTTPException(503, "Invalid identity response")
        identity = await self.verify(token)
        return {
            "accessToken": token,
            "tokenType": "Bearer",
            "expiresIn": result.get("expiresIn"),
            "subject": identity.subject,
        }

    async def exchange(self, identity: RequestIdentity, session_id: str, scope: str) -> str:
        if scope not in MERCHANT_SCOPES:
            raise ValueError("Unsupported merchant scope")
        result = await self._request(
            "POST",
            self.settings.auth_url.rstrip("/") + "/auth/token/exchange",
            auth=httpx.BasicAuth("merchant-agent", self.settings.merchant_service_secret),
            headers={"X-User-Authorization": "Bearer " + identity.token},
            json={"sessionId": session_id, "userSubject": identity.subject, "scope": scope},
        )
        token = result.get("accessToken")
        if not isinstance(token, str) or not token:
            raise HTTPException(503, "Invalid identity response")
        return token

    async def close(self):
        if self._owns_http:
            await self.http.aclose()
