import json
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from shopmate.auth import AuthClient, RequestIdentity
from shopmate.settings import Settings


@pytest.fixture
def signer():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def token(signer, **overrides):
    claims = {
        "sub": "operator",
        "iss": "https://identity.citybuddy.test",
        "aud": "citybuddy-web",
        "iat": int(time.time()),
        "exp": int(time.time()) + 600,
        "token_type": "direct_user",
        "principal_state": "ACTIVE",
        "permissions": ["merchant:session:create"],
    }
    claims.update(overrides)
    return jwt.encode(claims, signer, algorithm="RS256", headers={"kid": "current"})


def client(signer, handler=None):
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(signer.public_key())) | {"kid": "current"}

    def respond(request):
        if request.url.path == "/auth/jwks":
            return httpx.Response(200, json={"keys": [jwk]})
        return handler(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    return AuthClient(Settings(merchant_service_secret="test-service-secret"), http)


async def test_direct_login_verifies_signature_and_keeps_original_dto(signer):
    value = token(signer)

    def handler(request):
        assert json.loads(request.content) == {
            "loginIdentifier": "user",
            "password": "test-password",
        }
        return httpx.Response(
            200, json={"accessToken": value, "tokenType": "Bearer", "expiresIn": 600}
        )

    auth = client(signer, handler)
    result = await auth.login("user", "test-password")
    assert result == {
        "accessToken": value,
        "tokenType": "Bearer",
        "expiresIn": 600,
        "subject": "operator",
    }
    assert "test-password" not in repr(await auth.verify(value))


@pytest.mark.parametrize(
    "claims,status",
    [
        ({"token_type": "agent_obo", "act": {"azp": "merchant-agent"}}, 401),
        ({"sandbox": "test"}, 401),
        ({"aud": ["citybuddy-web", "other"]}, 401),
        ({"exp": 1}, 401),
        ({"permissions": []}, 403),
    ],
)
async def test_untrusted_direct_token_claims_rejected(signer, claims, status):
    with pytest.raises(HTTPException) as failure:
        await client(signer).verify(token(signer, **claims))
    assert failure.value.status_code == status


async def test_exchange_uses_server_identity_exact_scope_and_no_apply(signer):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.headers["authorization"].startswith("Basic ")
        assert request.headers["x-user-authorization"] == "Bearer direct-test-token"
        assert json.loads(request.content) == {
            "userSubject": "operator",
            "sessionId": "SessionA",
            "scope": "merchant:read",
        }
        return httpx.Response(200, json={"accessToken": "obo-test-token"})

    auth = client(signer, handler)
    identity = RequestIdentity("operator", "direct-test-token")
    assert await auth.exchange(identity, "SessionA", "merchant:read") == "obo-test-token"
    with pytest.raises(ValueError):
        await auth.exchange(identity, "SessionA", "merchant:price:apply")
    assert len(requests) == 1


async def test_jwks_outage_is_unavailable_not_auth_denial(signer):
    auth = AuthClient(
        Settings(), httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(503)))
    )
    with pytest.raises(HTTPException) as failure:
        await auth.verify(token(signer))
    assert failure.value.status_code == 503
