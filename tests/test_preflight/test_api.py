"""POST /api/v1/preflight/run — request validation, the main_file/files boundary check, and
report shape.

``get_current_user`` requires a live DB connection before it even looks at the Authorization
header (``src/api/deps.py``'s ``_require_db``), and ``tests/conftest.py`` strips
``DATABASE_URL``/``DIRECT_DATABASE_URL`` before importing the app, so there is no way to
authenticate for real through the plain ``client`` fixture: every call would 503 before FastAPI
even validates the request body, regardless of payload. This handler has nothing left to check
once the caller is known (no session store, no ownership lookup — the whole body is one call to
``run_preflight``), so these tests override the dependency with a stand-in, un-persisted user
instead of spinning up a throwaway database. They prove the *contract* this endpoint owns —
status codes, payload validation, response shape — not the auth gate.
"""

from __future__ import annotations

import uuid

import pytest

from src.api.deps import get_current_user
from src.db.models import User
from src.main import app

_FAKE_USER = User(id=uuid.uuid4(), email="preflight-test@example.com", full_name="Preflight Tester")


@pytest.fixture(autouse=True)
def _authenticated():
    """Stand in for ``get_current_user`` so requests reach the handler instead of 503ing on the DB."""
    app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_run_returns_a_report(client):
    res = await client.post(
        "/api/v1/preflight/run",
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
async def test_unsafe_main_file_is_rejected(client):
    res = await client.post("/api/v1/preflight/run", json={"main_file": "../../etc/passwd", "files": []})
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_too_many_files_is_rejected(client):
    files = [{"path": f"f{i}.tex", "content": ""} for i in range(65)]
    res = await client.post("/api/v1/preflight/run", json={"files": files})
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_empty_payload_reports_nothing_rather_than_erroring(client):
    res = await client.post("/api/v1/preflight/run", json={"files": []})
    assert res.status_code == 200
    assert res.json()["findings"] == []


@pytest.mark.asyncio
async def test_main_file_absent_from_nonempty_files_is_rejected(client):
    """``files`` is non-empty but none of its paths match ``main_file`` — a wrong ``main_file``,
    not "no content".

    Different from the ``files == []`` case above (still 200, still an empty report): here the
    payload carries real, analysable LaTeX, and ``build_source`` would silently discard every byte
    of it, because it resolves content only from ``main_file``. Answering that with a calm, clean
    empty report would hide a client bug behind a good-looking response, so the handler rejects it
    at the boundary instead of asking the runner to paper over it.
    """
    res = await client.post(
        "/api/v1/preflight/run",
        json={
            "main_file": "main.tex",
            "files": [{"path": "other.tex", "content": "See \\ref{ghost}.\n"}],
        },
    )
    assert res.status_code == 422
