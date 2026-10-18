"""POST /api/v1/compile — request validation, body limits and rate-limit keys (TeX is mocked)."""

from __future__ import annotations

import gzip
import json
import uuid

import pytest
from starlette.requests import Request

from src.api import routes
from src.config import get_settings
from src.models.schemas import CompileResponse
from src.services.auth_service import create_access_token
from src.services.compile_policy import reset_compile_rate_limit_state

MINIMAL_LATEX = r"\documentclass{article}\begin{document}Hi\end{document}"


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    reset_compile_rate_limit_state()
    yield
    reset_compile_rate_limit_state()


class _CompileCalls(list):
    """The recorded requests, plus the owner_key each call carried.

    A plain list cannot hold the extra attribute, and keeping the two in step matters: a route
    that forgets to pass owner_key puts every caller back into one shared workspace.
    """

    owner_keys: list


@pytest.fixture
def fake_compile(monkeypatch):
    calls = _CompileCalls()
    calls_owner: list = []

    def _fake(request, *, owner_key=""):
        # owner_key scopes the compile workspace to the caller (see _workspace_cache_key). It is
        # recorded alongside the request so a test can assert the route actually supplies one —
        # a route that forgot to would silently put every caller back in a shared workspace.
        calls.append(request)
        calls_owner.append(owner_key)
        return CompileResponse(success=True, pdf_base64="JVBERg==", main_file=request.main_file)

    monkeypatch.setattr(routes, "compile_latex", _fake)
    calls.owner_keys = calls_owner
    return calls


def _payload(**overrides) -> bytes:
    body = {"latex": MINIMAL_LATEX, "compiler": "pdflatex", **overrides}
    return json.dumps(body).encode("utf-8")


# ─── B2: main_file validation ────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("main_file", ["../x.tex", "/etc/x.tex", "C:\\x.tex", "a/../../b.tex"])
async def test_compile_rejects_unsafe_main_file(client, fake_compile, main_file):
    res = await client.post("/api/v1/compile", content=_payload(main_file=main_file))
    assert res.status_code == 422, res.text
    assert fake_compile == []


@pytest.mark.asyncio
@pytest.mark.parametrize("main_file", ["main.tex", "chapters/intro.tex"])
async def test_compile_accepts_safe_main_file(client, fake_compile, main_file):
    res = await client.post("/api/v1/compile", content=_payload(main_file=main_file))
    assert res.status_code == 200, res.text
    assert fake_compile[0].main_file == main_file


# ─── B3: body size limits ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_compile_rejects_declared_oversized_body(client, fake_compile, monkeypatch):
    monkeypatch.setattr(routes, "COMPILE_MAX_BODY_BYTES", 1024)
    res = await client.post("/api/v1/compile", content=_payload(latex=MINIMAL_LATEX + "%" * 4096))
    assert res.status_code == 413
    assert fake_compile == []


@pytest.mark.asyncio
async def test_compile_rejects_streamed_oversized_body_without_content_length(client, fake_compile, monkeypatch):
    monkeypatch.setattr(routes, "COMPILE_MAX_BODY_BYTES", 1024)

    async def chunks():
        for _ in range(8):
            yield b" " * 512

    res = await client.post("/api/v1/compile", content=chunks())
    assert res.status_code == 413
    assert fake_compile == []


@pytest.mark.asyncio
async def test_compile_accepts_gzip_body(client, fake_compile):
    res = await client.post(
        "/api/v1/compile",
        content=gzip.compress(_payload()),
        headers={"Content-Encoding": "gzip", "Content-Type": "application/json"},
    )
    assert res.status_code == 200, res.text
    assert fake_compile[0].latex == MINIMAL_LATEX


@pytest.mark.asyncio
async def test_compile_rejects_gzip_bomb(client, fake_compile, monkeypatch):
    monkeypatch.setattr(routes, "COMPILE_MAX_BODY_BYTES", 4096)
    bomb = gzip.compress(_payload(latex=MINIMAL_LATEX + "%" * 1_000_000))
    assert len(bomb) < 4096  # small on the wire, huge once inflated

    def _unbounded(*_args, **_kwargs):
        raise AssertionError("gzip.decompress must not be used")

    monkeypatch.setattr(gzip, "decompress", _unbounded)
    res = await client.post("/api/v1/compile", content=bomb, headers={"Content-Encoding": "gzip"})
    assert res.status_code == 413
    assert fake_compile == []


@pytest.mark.asyncio
async def test_compile_rejects_invalid_gzip(client, fake_compile):
    res = await client.post("/api/v1/compile", content=b"not gzip at all", headers={"Content-Encoding": "gzip"})
    assert res.status_code == 400
    assert fake_compile == []


# ─── B3: rate-limit key ──────────────────────────────────────────────────────


def _request(headers: dict[str, str] | None = None, client_host: str | None = "10.0.0.9") -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/compile",
        "headers": [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in (headers or {}).items()],
        "client": (client_host, 1234) if client_host else None,
    }
    return Request(scope)


@pytest.fixture
def jwt_secret(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET_KEY", "test-secret-key-for-jwt-signing-32chars")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_client_key_uses_verified_user_id(jwt_secret):
    user_id = str(uuid.uuid4())
    token = create_access_token(user_id=user_id, email="u@test.local")
    key = routes._compile_client_key(_request({"Authorization": f"Bearer {token}", "X-Forwarded-For": "1.2.3.4"}))
    assert key == f"user:{user_id}"


def test_client_key_ignores_invalid_tokens():
    first = routes._compile_client_key(_request({"Authorization": "Bearer garbage-1"}))
    second = routes._compile_client_key(_request({"Authorization": "Bearer garbage-2"}))
    assert first == second == "ip:10.0.0.9"


def test_client_key_uses_rightmost_forwarded_hop():
    request = _request({"X-Forwarded-For": "6.6.6.6, 203.0.113.7"})
    assert routes._compile_client_key(request) == "ip:203.0.113.7"
    spoofed = _request({"X-Forwarded-For": "1.1.1.1, 9.9.9.9 , 203.0.113.7"})
    assert routes._compile_client_key(spoofed) == "ip:203.0.113.7"


def test_client_key_falls_back_to_peer_address():
    assert routes._compile_client_key(_request()) == "ip:10.0.0.9"
    assert routes._compile_client_key(_request({"X-Forwarded-For": " , "})) == "ip:10.0.0.9"
    assert routes._compile_client_key(_request(client_host=None)) == "ip:unknown"


@pytest.mark.asyncio
async def test_rotating_bogus_tokens_cannot_bypass_rate_limit(client, fake_compile, monkeypatch):
    monkeypatch.setenv("COMPILE_RATE_LIMIT_PER_MIN", "2")
    get_settings.cache_clear()
    try:
        statuses = []
        for i in range(3):
            res = await client.post(
                "/api/v1/compile",
                content=_payload(),
                headers={"Authorization": f"Bearer bogus-{i}", "X-Forwarded-For": f"10.{i}.0.1, 198.51.100.4"},
            )
            statuses.append(res.status_code)
        assert statuses == [200, 200, 429]
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_compile_route_passes_a_non_empty_owner_key(client, fake_compile):
    """The route must hand compile_latex a caller identity.

    compile_latex's owner_key defaults to "" so unit tests can call it without inventing an
    identity — which means a route that forgot to pass one would silently put every caller back
    into a single shared workspace, exactly the defect this parameter exists to close.
    """
    res = await client.post("/api/v1/compile", content=_payload(), headers={"Content-Type": "application/json"})
    assert res.status_code == 200, res.text
    assert fake_compile.owner_keys, "compile_latex was never called"
    assert all(key for key in fake_compile.owner_keys), fake_compile.owner_keys
