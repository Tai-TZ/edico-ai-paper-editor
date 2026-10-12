import asyncio
from contextlib import asynccontextmanager

import inngest.fast_api
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.admin_routes import router as admin_router
from src.api.ai_disclosure_routes import router as ai_disclosure_router
from src.api.auth_routes import router as auth_router
from src.api.billing_routes import router as billing_router
from src.api.defense_routes import router as defense_router
from src.api.health_routes import router as health_router
from src.api.import_routes import router as import_router
from src.api.paper_routes import router as papers_router
from src.api.preflight_routes import router as preflight_router
from src.api.profile_routes import router as profile_router
from src.api.review_routes import router as review_router
from src.api.routes import router
from src.api.share_routes import router as share_router
from src.api.template_routes import router as template_router
from src.config import get_settings, validate_production_settings
from src.cors_config import build_cors_middleware_kwargs
from src.db.engine import db_is_ready, get_db, init_db, is_db_enabled
from src.inngest.client import inngest_client
from src.inngest.functions import INNGEST_FUNCTIONS
from src.logging_config import configure_logging
from src.security_headers import SecurityHeadersMiddleware
from src.services.auth_service import ensure_god_admin
from src.services.sessions import refresh_session_store
from src.services.template_store import ensure_template_seed


def _provision_god_admin() -> None:
    try:
        with get_db() as db:
            user = ensure_god_admin(db)
            if user:
                print(f"God admin ready: {user.email}")
    except Exception as exc:
        print(f"God admin provisioning skipped: {exc}")


def _refresh_provider_keys() -> None:
    try:
        from src.services.provider_key_store import refresh_provider_key_cache

        with get_db() as db:
            refresh_provider_key_cache(db)
    except Exception as exc:
        print(f"Provider key cache refresh skipped: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    print(f"Starting {settings.app_name} in {settings.app_env} mode")
    validate_production_settings(settings)
    if is_db_enabled():
        try:
            await asyncio.wait_for(asyncio.to_thread(init_db), timeout=20.0)
            if db_is_ready():
                await asyncio.to_thread(_provision_god_admin)
                await asyncio.to_thread(_refresh_provider_keys)
            refresh_session_store()
            print("Database connected")
        except TimeoutError:
            print("Database init timed out after 20s, using in-memory store")
        except Exception as exc:
            print(f"Database init failed, using in-memory store: {exc}")
    else:
        print("DATABASE_URL not set — using in-memory session store")
    try:
        await asyncio.to_thread(ensure_template_seed)
    except Exception as exc:
        print(f"Template gallery seed skipped: {exc}")
    if settings.inngest_serve_enabled():
        print("Inngest sync endpoint: /api/inngest")
    yield
    print("Shutting down...")


app = FastAPI(
    title="Edico API",
    description="AI-assisted LaTeX editing for scientific papers — Dico agents built with LangGraph",
    version="1.0.0",
    lifespan=lifespan,
)

configure_logging(app)

settings = get_settings()
app.add_middleware(CORSMiddleware, **build_cors_middleware_kwargs(settings))
# Added last = outermost, so CORS preflights and error responses get the headers too.
app.add_middleware(SecurityHeadersMiddleware, hsts=settings.app_env == "production")

app.include_router(router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(papers_router, prefix="/api/v1")
app.include_router(ai_disclosure_router, prefix="/api/v1")
app.include_router(profile_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(share_router, prefix="/api/v1")
app.include_router(defense_router, prefix="/api/v1")
app.include_router(review_router, prefix="/api/v1")
app.include_router(template_router, prefix="/api/v1")
app.include_router(billing_router, prefix="/api/v1")
app.include_router(import_router, prefix="/api/v1")
app.include_router(preflight_router, prefix="/api/v1")

if settings.inngest_serve_enabled():
    inngest.fast_api.serve(app, inngest_client, INNGEST_FUNCTIONS)

app.include_router(health_router)


@app.get("/health")
async def health():
    db_status = "connected" if db_is_ready() else "disconnected"
    if not is_db_enabled():
        db_status = "not_configured"
    return {"status": "ok", "env": settings.app_env, "database": db_status}
