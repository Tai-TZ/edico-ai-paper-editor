from __future__ import annotations

import asyncio
import contextlib
import subprocess
import uuid
import zlib
from functools import partial

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from src.agents.graph import agent
from src.api.agent_deps import assert_paper_session_access, get_agent_user_id
from src.config import get_settings, is_llm_provider_enabled
from src.db.engine import db_is_ready, is_db_enabled
from src.models.citation_schemas import CitationRelevanceRequest, CitationRelevanceResponse
from src.models.schemas import (
    ChatRequest,
    ChatResponse,
    CitationVerifyRequest,
    CitationVerifyResponse,
    CompileRequest,
    CompileResponse,
    CompileStatusResponse,
    IntegrityFlagSchema,
    ProviderInfo,
    ProvidersResponse,
    RevisionAction,
    RevisionRecordResponse,
    RevisionsListResponse,
    SessionCreate,
    SessionResponse,
    SessionUpdate,
    StyleEditRequest,
    StyleEditResponse,
    SyncTeXLookupRequest,
    SyncTeXLookupResponse,
)
from src.services.auth_service import decode_access_token
from src.services.chat_stream import AGENT_NAME, flush_sse_stream, stream_chat
from src.services.citations.relevance import run_citation_relevance
from src.services.citations.verifier import verify_citations
from src.services.compile_policy import CompileRateLimitedError, check_compile_rate_limit
from src.services.latex_compile import (
    AssetResyncRequiredError,
    CompileBudgetExceededError,
    UnsafeMainFileError,
    compile_latex,
    compile_status,
    parse_synctex_inverse_disambiguated,
    resolve_synctex_line_from_request,
)
from src.services.llm import list_providers
from src.services.llm_errors import friendly_llm_error
from src.services.parser.latex import extract_bib_content, extract_cite_keys, parse_bib_entries
from src.services.quota_policy import QuotaExceededError, enforce_llm_quota_for_paper
from src.services.sessions import session_store

router = APIRouter()


def _session_to_response(session) -> SessionResponse:
    return SessionResponse(
        id=session.id,
        name=session.name,
        latex_content=session.latex_content,
        metadata=session.metadata,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _build_chat_response(result: dict) -> ChatResponse:
    flags = [IntegrityFlagSchema(**f) for f in result.get("integrity_flags", [])]
    metadata = result.get("metadata") or {}
    return ChatResponse(
        response=result.get("response", ""),
        analysis=result.get("analysis", ""),
        task=result.get("task", "chat"),
        suggestion=result.get("suggestion", ""),
        original_text=result.get("original_text", ""),
        diff=result.get("diff", ""),
        apply_mode=result.get("apply_mode"),
        revision_id=metadata.get("revision_id", result.get("revision_id", "")),
        integrity_flags=flags,
        edits=result.get("edits", []),
        citation_results=result.get("citation_results", []),
        structure_suggestions=result.get("structure_suggestions", []),
        logic_audit_report=result.get("logic_audit_report", {}),
    )


def _revision_to_response(record) -> RevisionRecordResponse:
    return RevisionRecordResponse(
        id=record.id,
        section=record.section,
        original=record.original,
        suggestion=record.suggestion,
        action=record.action,
        created_at=record.created_at,
    )


def _agent_input(**kwargs) -> dict:
    settings = get_settings()
    payload = dict(kwargs)
    if not payload.get("llm_provider"):
        payload["llm_provider"] = settings.llm_provider
    return payload


async def _enforce_llm_quota(session_id: str | None, user_id: uuid.UUID | None) -> None:
    """Sync LLM entry points (/chat, /edit/style): quota + rate limit once per request, 429 when over."""
    try:
        await asyncio.to_thread(enforce_llm_quota_for_paper, session_id, user_id)
    except QuotaExceededError as e:
        raise HTTPException(status_code=429, detail=str(e)) from e


@router.get("/status")
async def agent_status():
    settings = get_settings()
    if db_is_ready():
        storage = "postgresql" if get_settings().sqlalchemy_database_url().startswith("postgresql") else "database"
    elif is_db_enabled():
        storage = "database (connection failed — check DATABASE_URL)"
    else:
        storage = "in-memory (set DATABASE_URL to enable persistence)"
    return {
        "status": "ready",
        "agent": f"{AGENT_NAME} v1.0",
        "default_provider": settings.llm_provider,
        "storage": storage,
    }


@router.get("/providers", response_model=ProvidersResponse)
async def get_providers():
    settings = get_settings()
    providers = [ProviderInfo(**p) for p in list_providers()]
    if not providers:
        raise HTTPException(
            status_code=503,
            detail="No LLM API keys configured. Set GOOGLE_API_KEY, OPENROUTER_API_KEY, or ZAI_API_KEY in .env",
        )
    configured_ids = {p.id for p in providers}
    default_provider = settings.llm_provider
    if default_provider not in configured_ids or not is_llm_provider_enabled(default_provider):
        default_provider = providers[0].id
    return ProvidersResponse(
        default_provider=default_provider,
        providers=providers,
    )


@router.post("/sessions", response_model=SessionResponse)
async def create_session(
    body: SessionCreate,
    user_id: uuid.UUID | None = Depends(get_agent_user_id),
):
    assert_paper_session_access(body.id, user_id)
    session = session_store.create(
        session_id=body.id,
        name=body.name,
        latex_content=body.latex_content,
        metadata=body.metadata,
    )
    return _session_to_response(session)


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    user_id: uuid.UUID | None = Depends(get_agent_user_id),
):
    assert_paper_session_access(session_id, user_id)
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return _session_to_response(session)


@router.patch("/sessions/{session_id}", response_model=SessionResponse)
async def update_session(
    session_id: str,
    body: SessionUpdate,
    user_id: uuid.UUID | None = Depends(get_agent_user_id),
):
    assert_paper_session_access(session_id, user_id)
    session = session_store.get(session_id)
    if not session:
        session = session_store.get_or_create(
            session_id,
            name=body.name or "Untitled",
            latex_content=body.latex_content or "",
            metadata=body.metadata,
        )
    else:
        updated = session_store.update(
            session_id,
            name=body.name,
            latex_content=body.latex_content,
            metadata=body.metadata,
        )
        session = updated or session
    return _session_to_response(session)


@router.get("/sessions/{session_id}/revisions", response_model=RevisionsListResponse)
async def list_session_revisions(
    session_id: str,
    user_id: uuid.UUID | None = Depends(get_agent_user_id),
):
    assert_paper_session_access(session_id, user_id)
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return RevisionsListResponse(
        revisions=[_revision_to_response(r) for r in session.revision_history],
    )


@router.get("/sessions/{session_id}/citations", response_model=CitationVerifyResponse)
async def get_session_citations(
    session_id: str,
    user_id: uuid.UUID | None = Depends(get_agent_user_id),
):
    assert_paper_session_access(session_id, user_id)
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    results = session.citation_registry or []
    verified = sum(1 for r in results if r.get("status") == "verified")
    summary = f"Verified {verified}/{len(results)} citations." if results else "No citation verification on file."
    return CitationVerifyResponse(results=results, summary=summary)


@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    http_request: Request,
    user_id: uuid.UUID | None = Depends(get_agent_user_id),
):
    assert_paper_session_access(request.session_id or "", user_id)
    cancel = asyncio.Event()

    async def watch_disconnect() -> None:
        while not cancel.is_set():
            if await http_request.is_disconnected():
                cancel.set()
                return
            await asyncio.sleep(0.2)

    async def stream_with_disconnect():
        watcher = asyncio.create_task(watch_disconnect())
        agen = stream_chat(request, cancel_event=cancel, user_id=user_id)
        try:
            async for chunk in flush_sse_stream(agen):
                if cancel.is_set():
                    break
                yield chunk
        finally:
            cancel.set()
            watcher.cancel()
            with contextlib.suppress(Exception):
                await agen.aclose()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher

    try:
        return StreamingResponse(
            stream_with_disconnect(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "Content-Encoding": "identity",
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    user_id: uuid.UUID | None = Depends(get_agent_user_id),
):
    assert_paper_session_access(request.session_id or "", user_id)
    await _enforce_llm_quota(request.session_id, user_id)
    try:
        if request.session_id and request.latex_content:
            session_store.get_or_create(
                request.session_id,
                latex_content=request.latex_content,
            )
            session_store.update(request.session_id, latex_content=request.latex_content)

        result = await agent.ainvoke(
            _agent_input(
                query=request.message,
                session_id=request.session_id or "",
                latex=request.latex_content,
                selection=request.selection,
                task=request.task,
                llm_provider=request.llm_provider,
                llm_model=request.llm_model,
            )
        )
        result["task"] = result.get("task") or request.task or "chat"
        return _build_chat_response(result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/edit/style", response_model=StyleEditResponse)
async def edit_style(
    request: StyleEditRequest,
    user_id: uuid.UUID | None = Depends(get_agent_user_id),
):
    assert_paper_session_access(request.session_id, user_id)
    await _enforce_llm_quota(request.session_id, user_id)
    try:
        session = session_store.get_or_create(request.session_id)
        session_store.update(request.session_id, latex_content=session.latex_content)

        result = await agent.ainvoke(
            _agent_input(
                task="style",
                session_id=request.session_id,
                latex=session.latex_content,
                selection=request.text,
                section=request.section,
                query=f"Improve style: {request.section or 'selection'}",
                llm_provider=request.llm_provider,
                llm_model=request.llm_model,
            )
        )
        flags = [IntegrityFlagSchema(**f) for f in result.get("integrity_flags", [])]
        revision_id = (result.get("metadata") or {}).get("revision_id", "")
        return StyleEditResponse(
            original_text=result.get("original_text", request.text),
            suggestion=result.get("suggestion", ""),
            diff=result.get("diff", ""),
            integrity_flags=flags,
            revision_id=revision_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/citations/verify", response_model=CitationVerifyResponse)
async def verify_session_citations(
    request: CitationVerifyRequest,
    user_id: uuid.UUID | None = Depends(get_agent_user_id),
):
    assert_paper_session_access(request.session_id, user_id)
    session = session_store.get_or_create(request.session_id)
    latex = session.latex_content
    bib = extract_bib_content(latex, request.bib_content)
    cite_keys = extract_cite_keys(latex)
    bib_entries = parse_bib_entries(bib)

    entries = []
    for key in cite_keys:
        entries.append(bib_entries.get(key, {"key": key, "title": "", "doi": "", "eprint": "", "raw": ""}))

    if not entries:
        return CitationVerifyResponse(
            results=[],
            summary="No citations found in manuscript.",
        )

    settings = get_settings()
    results = await verify_citations(
        entries,
        semantic_scholar_api_key=settings.semantic_scholar_api_key,
        openalex_mailto=settings.openalex_mailto,
    )
    session_store.set_citation_registry(request.session_id, results)
    verified = sum(1 for r in results if r.get("status") == "verified")
    return CitationVerifyResponse(
        results=results,
        summary=f"Verified {verified}/{len(results)} citations.",
    )


@router.post("/citations/relevance", response_model=CitationRelevanceResponse)
async def check_citations_relevance(
    request: CitationRelevanceRequest,
    user_id: uuid.UUID | None = Depends(get_agent_user_id),
):
    """Citation Layer 4 — LLM judges whether each cited source supports its claim (read-only)."""
    assert_paper_session_access(request.session_id, user_id)
    try:
        return await run_citation_relevance(request, user_id=user_id)
    except QuotaExceededError as e:
        raise HTTPException(status_code=429, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=friendly_llm_error(e)) from e


@router.get("/compile/status", response_model=CompileStatusResponse)
async def get_compile_status():
    return compile_status()


# Upper bound for the compile request body, both as sent and after gzip decompression.
COMPILE_MAX_BODY_BYTES = 64 * 1024 * 1024


def _payload_too_large() -> HTTPException:
    limit_mb = COMPILE_MAX_BODY_BYTES // (1024 * 1024)
    return HTTPException(status_code=413, detail=f"Compile request is too large (limit {limit_mb} MB).")


async def _read_compile_body(request: Request) -> bytes:
    """Read the body without ever buffering more than COMPILE_MAX_BODY_BYTES."""
    limit = COMPILE_MAX_BODY_BYTES
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            declared_len = int(declared)
        except ValueError as e:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header.") from e
        if declared_len > limit:
            raise _payload_too_large()
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise _payload_too_large()
    return bytes(body)


def _gunzip_bounded(raw: bytes) -> bytes:
    """Decompress gzip, refusing output above COMPILE_MAX_BODY_BYTES (no zip bombs)."""
    limit = COMPILE_MAX_BODY_BYTES
    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        out = decompressor.decompress(raw, limit + 1)
    except zlib.error as e:
        raise HTTPException(status_code=400, detail="Invalid gzip request body.") from e
    if len(out) > limit or decompressor.unconsumed_tail:
        raise _payload_too_large()
    if not decompressor.eof:
        raise HTTPException(status_code=400, detail="Truncated gzip request body.")
    return out


@router.post("/compile", response_model=CompileResponse)
async def compile_manuscript(request: Request):
    try:
        client_key = _compile_client_key(request)
        check_compile_rate_limit(client_key)
        raw = await _read_compile_body(request)
        if request.headers.get("content-encoding", "").lower() == "gzip":
            raw = _gunzip_bounded(raw)
        body = CompileRequest.model_validate_json(raw)
        result = await asyncio.to_thread(partial(compile_latex, body, owner_key=client_key))
        return result
    except HTTPException:
        raise
    except CompileRateLimitedError as e:
        raise HTTPException(status_code=429, detail=str(e)) from e
    except ValidationError as e:
        raise HTTPException(
            status_code=422,
            detail=e.errors(include_url=False, include_context=False, include_input=False),
        ) from e
    except UnsafeMainFileError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except AssetResyncRequiredError as e:
        raise HTTPException(
            status_code=409,
            detail={"code": "ASSET_RESYNC_REQUIRED", "assets": e.names},
        ) from e
    except CompileBudgetExceededError as e:
        raise HTTPException(status_code=504, detail=str(e)) from e
    except subprocess.TimeoutExpired as e:
        raise HTTPException(status_code=504, detail="LaTeX compilation timed out.") from e
    except Exception as e:
        import traceback

        tb = traceback.format_exc()
        print(f"[COMPILE_ERROR] {tb}", flush=True)
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}") from e


def _client_ip(request: Request) -> str | None:
    """Rightmost X-Forwarded-For hop (appended by Cloud Run's proxy); the leftmost is client-controlled."""
    forwarded = request.headers.get("x-forwarded-for", "")
    hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
    if hops:
        return hops[-1]
    if request.client and request.client.host:
        return request.client.host
    return None


def _compile_client_key(request: Request) -> str:
    """Rate-limit key: the authenticated user when the bearer token verifies, else the client IP.

    Unverified token strings are never used as keys (anyone could rotate them to dodge the limit).
    """
    auth = request.headers.get("authorization", "").strip()
    if auth.lower().startswith("bearer "):
        payload = decode_access_token(auth.split(" ", 1)[1].strip())
        sub = payload.get("sub") if payload else None
        if sub:
            return f"user:{sub}"
    ip = _client_ip(request)
    return f"ip:{ip}" if ip else "ip:unknown"


@router.post("/compile/synctex", response_model=SyncTeXLookupResponse)
async def synctex_lookup(body: SyncTeXLookupRequest, request: Request):
    # Same server-derived identity the compile route uses: a cached workspace belongs to the
    # caller that created it, so SyncTeX must look it up under that caller, not by cache_id alone.
    client_key = _compile_client_key(request)
    hit = await asyncio.to_thread(
        partial(
            parse_synctex_inverse_disambiguated,
            body.synctex_base64,
            body.pdf_base64,
            body.page,
            body.x,
            body.y,
            body.jobname,
            body.word,
            body.latex,
            body.context,
            body.cache_id,
            owner_key=client_key,
        )
    )
    if not hit:
        return SyncTeXLookupResponse(found=False, page=body.page)
    raw_line = int(hit.get("line", 0))
    resolved_line = resolve_synctex_line_from_request(
        body.cache_id,
        body.jobname,
        body.latex,
        raw_line,
        body.word,
        body.context,
    )
    return SyncTeXLookupResponse(
        found=True,
        file=str(hit.get("file", "")),
        line=resolved_line,
        synctex_line=raw_line,
        column=int(hit.get("column", -1)),
        page=body.page,
    )


@router.post("/revisions/{session_id}/{revision_id}")
async def revision_action(
    session_id: str,
    revision_id: str,
    body: RevisionAction,
    user_id: uuid.UUID | None = Depends(get_agent_user_id),
):
    assert_paper_session_access(session_id, user_id)
    record = session_store.set_revision_action(session_id, revision_id, body.action)
    if not record:
        raise HTTPException(status_code=404, detail="Revision not found")
    return {"status": "ok", "revision_id": revision_id, "action": body.action}
