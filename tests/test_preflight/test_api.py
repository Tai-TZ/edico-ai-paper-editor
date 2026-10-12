"""POST /api/v1/preflight/run — request validation, the main_file/files boundary check, and
report shape.

``get_current_user`` requires a live DB connection before it even looks at the Authorization
header (``src/api/deps.py``'s ``_require_db``), and ``tests/conftest.py`` strips
``DATABASE_URL``/``DIRECT_DATABASE_URL`` before importing the app. Rather than overriding the
dependency (no precedent anywhere in this repo — ``grep -rn dependency_overrides tests/`` has no
other hits), these tests follow the repo's actual pattern for an endpoint gated only by
``Depends(get_current_user)`` (see ``tests/test_api/test_profile.py``, which tests the
identically-shaped ``GET /users/me/profile``): a throwaway sqlite database brought up via
``monkeypatch`` + ``init_db()``, and a real bearer token obtained through
``register_user_via_verification`` so requests exercise the real dependency end to end.
"""

from __future__ import annotations

import os

import pytest

from src.config import get_settings
from src.db.engine import init_db, reset_db_state
from tests.test_api.auth_helpers import register_user_via_verification


@pytest.fixture
def preflight_db(monkeypatch):
    db_path = os.path.join(os.path.dirname(__file__), "_test_preflight.db")
    if os.path.exists(db_path):
        os.remove(db_path)
    url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DIRECT_DATABASE_URL", url)
    monkeypatch.setenv("AUTH_SECRET_KEY", "test-secret-key-for-jwt-signing-32chars")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("SMTP_FROM", "")
    monkeypatch.setenv("SMTP_USER", "")
    monkeypatch.setenv("SMTP_PASSWORD", "")
    get_settings.cache_clear()
    reset_db_state()
    init_db()
    yield
    reset_db_state()
    get_settings.cache_clear()
    # Known trap (tests/test_api/test_ai_disclosure_api.py, tests/test_db/conftest.py): init_db()
    # plus a real login can leave the module-global session store bound to a DatabaseSessionStore
    # pointing at the sqlite file we are about to delete, which poisons later tests. This endpoint
    # never touches the session store itself, but clear the global anyway so teardown order can't
    # matter.
    import src.services.sessions as sessions_mod

    sessions_mod._store = None
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except OSError:
            pass


async def _auth_headers(client) -> dict[str, str]:
    body = await register_user_via_verification(
        client,
        name="Preflight Tester",
        email="preflight-test@example.com",
        password="SecurePass1",
    )
    return {"Authorization": f"Bearer {body['access_token']}"}


@pytest.mark.asyncio
async def test_run_returns_a_report(client, preflight_db):
    headers = await _auth_headers(client)
    res = await client.post(
        "/api/v1/preflight/run",
        headers=headers,
        json={
            "main_file": "main.tex",
            "files": [{"path": "main.tex", "content": "See \\ref{ghost}.\n"}],
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["integrity_mode"] == "comment_only"
    assert body["findings"][0]["rule"] == "crossref.undefined_ref"


@pytest.mark.asyncio
async def test_unsafe_main_file_is_rejected(client, preflight_db):
    headers = await _auth_headers(client)
    res = await client.post(
        "/api/v1/preflight/run",
        headers=headers,
        json={"main_file": "../../etc/passwd", "files": []},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_too_many_files_is_rejected(client, preflight_db):
    headers = await _auth_headers(client)
    files = [{"path": f"f{i}.tex", "content": ""} for i in range(65)]
    res = await client.post("/api/v1/preflight/run", headers=headers, json={"files": files})
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_empty_payload_reports_nothing_rather_than_erroring(client, preflight_db):
    headers = await _auth_headers(client)
    res = await client.post("/api/v1/preflight/run", headers=headers, json={"files": []})
    assert res.status_code == 200
    assert res.json()["findings"] == []


@pytest.mark.asyncio
async def test_main_file_absent_from_nonempty_files_is_rejected(client, preflight_db):
    """``files`` is non-empty but none of its paths match ``main_file`` — a wrong ``main_file``,
    not "no content".

    Different from the ``files == []`` case above (still 200, still an empty report): here the
    payload carries real, analysable LaTeX, and ``build_source`` would silently discard every byte
    of it, because it resolves content only from ``main_file``. Answering that with a calm, clean
    empty report would hide a client bug behind a good-looking response, so the handler rejects it
    at the boundary instead of asking the runner to paper over it.
    """
    headers = await _auth_headers(client)
    res = await client.post(
        "/api/v1/preflight/run",
        headers=headers,
        json={
            "main_file": "main.tex",
            "files": [{"path": "other.tex", "content": "See \\ref{ghost}.\n"}],
        },
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_run_requires_authentication(client, preflight_db):
    res = await client.post(
        "/api/v1/preflight/run",
        json={
            "main_file": "main.tex",
            "files": [{"path": "main.tex", "content": "See \\ref{ghost}.\n"}],
        },
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_run_rejects_malformed_token(client, preflight_db):
    """``decode_access_token`` swallows every ``jwt.PyJWTError`` and returns ``None``, so expired,
    malformed, and wrong-signature tokens are indistinguishable at the call site and all produce
    the same response — this one malformed-token case covers that whole class.
    """
    res = await client.post(
        "/api/v1/preflight/run",
        headers={"Authorization": "Bearer not-a-real-token"},
        json={
            "main_file": "main.tex",
            "files": [{"path": "main.tex", "content": "See \\ref{ghost}.\n"}],
        },
    )
    assert res.status_code == 401
