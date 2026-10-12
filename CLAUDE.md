# CLAUDE.md

Edico — AI-assisted LaTeX editor for scientific papers. FastAPI + LangGraph backend (`src/`), TanStack Start + React 19 frontend (`frontend/`), PostgreSQL via Prisma schema + SQLAlchemy runtime.

## Commands

Backend (repo root, Python 3.11+; `.venv` is the local virtualenv):

```bash
pip install -r requirements-dev.txt        # runtime + ruff/pytest (runtime-only: requirements.txt)
python -m uvicorn src.main:app --host 127.0.0.1 --port 8000 --reload
pytest tests/ -q                           # full suite (~770 tests, no DB/LLM needed; never reads .env)
pytest tests/test_services/test_cors_config.py -q   # single file
ruff check src tests && ruff format --check src tests
make check                                 # lint + format-check + tests
```

Frontend (`cd frontend`, Node 22, npm — `package-lock.json` is the only lockfile):

```bash
npm install
npm run dev        # Vite dev server, proxies /api/v1 → http://127.0.0.1:8000 (override: VITE_DEV_API_PROXY)
npm test           # vitest run
npm run build
npm run lint       # eslint (prettier enforced as a lint rule)
npm run format     # prettier --write .
npm run typecheck  # tsc --noEmit — must stay at 0 errors (CI enforces it)
```

Database (repo root): `npm install && npm run db:generate && npm run db:migrate`. Diagrams: `python scripts/build_diagrams.py [name]` regenerates every SVG in `docs/assets/` (always the light newsprint palette); the README masthead comes from `python scripts/build_banner.py` (needs `pip install fonttools uharfbuzz`; downloads Fraunces into `.cache/fonts/`).

## Architecture map

- `src/main.py` — FastAPI app, routers mounted under `/api/v1`; `/health` (liveness) and `/ready` (DB + TeX, `src/api/health_routes.py`) at the root. CORS in `src/cors_config.py`; settings in `src/config.py` (pydantic-settings, reads `.env`; `validate_production_settings` refuses a weak `AUTH_SECRET_KEY` in production). Middleware: `src/security_headers.py`, `src/request_context.py` (X-Request-ID); logging in `src/logging_config.py` (JSON lines outside development).
- `src/api/` — routes (chat/compile/citations in `routes.py`, plus auth, papers, admin, billing, defense, share, templates).
- `src/services/` — business logic: `chat_stream.py` (SSE editor path; shared SSE helpers in `sse.py`), `intent_router.py`, `llm_json.py` (the one place LLM replies are parsed as JSON, json-repair fallback), `guardrails/` (L1 prompt, L2 output checks), `logic_audit/`, `defense_*`, `latex_compile.py` (TeX Live + SyncTeX, sandboxed subprocess env), `citations/` (arXiv/CrossRef/S2/OpenAlex + L4 relevance; `title_match.py` uses rapidfuzz), `parser/latex.py` (bibtexparser v2 + cite-key matcher), `quota_policy.py` (every LLM path is metered), `peer_review/`, `preflight/` (deterministic submission-readiness checks, no LLM — `POST /api/v1/preflight/run`, `src/api/preflight_routes.py`), `document_import/` (DOCX/PDF → LaTeX), `ai_disclosure.py`, `template_builtins.py` (Springer/Elsevier seeds).
- `src/agents/graph.py` — LangGraph graph for the sync `POST /chat` path. Prompts live in `src/prompts/prompts.default.yaml`.
- `src/db/` — SQLAlchemy models mirroring `prisma/schema.prisma` (Prisma owns migrations).
- `frontend/src/routes/` — file-based routes; `frontend/src/routeTree.gen.ts` is generated, never edit it. Editor lives in `frontend/src/features/editor/` (`EditorWorkspace.tsx` + `state/` hooks). API clients in `frontend/src/lib/api/`.
- Docs: `ARCHITECTURE.md` (Vietnamese, diagrams in `docs/assets/`), `EVALUATION.md`, `docs/`.

Core invariant: AI output never applies itself — every edit goes through the Integrity Monitor and a diff the user Accepts/Rejects.

## Conventions

- Python: ruff (line length 120, rules in `ruff.toml`), formatted with `ruff format`; CI fails on lint or format drift.
- Frontend: Prettier (`frontend/.prettierrc`, width 100) + ESLint; CI runs `npm run lint -- --max-warnings 0`.
- Effects that must call a fresh callback without re-running use `useLatestRef` (`frontend/src/lib/use-latest-ref.ts`); don't silence `exhaustive-deps`.
- `.tsx` component files export only components (Fast Refresh); contexts/hooks live in sibling `.ts` files (e.g. `locale-context.ts`).
- `frontend/vite.config.ts` uses `@lovable.dev/vite-tanstack-config`, which already registers TanStack Start, React, Tailwind and path aliases — do not add those plugins again.
- UI copy is bilingual (EN/VI) via `frontend/src/lib/*-i18n.ts`; update both locales.
- Docs are Vietnamese with English technical terms. Commits follow Conventional Commits (`feat:`, `fix:`, `refactor:`, `docs:`, `chore:`).
- Never commit `.env` (copy from `.env.example`).

## Known state

- Vite builds without type-checking, so run `npm run typecheck` yourself; CI fails on any type error.
- pdf.js is v6: `AnnotationLayer` takes `linkService` in its constructor (render() ignores it) and `page.render()` needs `canvas`; free a document with `pdf.loadingTask.destroy()`. pdf.js 6 has no eval/`new Function` path (the `isEvalSupported` option is gone); PDF links are limited to http(s)/mailto (`frontend/src/lib/pdf-safe-url.ts`).
- One vitest test is timing-sensitive and can fail once under heavy CPU load; re-run before investigating.
- DB URLs are rewritten to `postgresql+psycopg2://` (`sqlalchemy_database_url`): SQLAlchemy 2.1 defaults bare `postgresql://` to psycopg 3, which isn't installed.
- `tests/conftest.py` disables `.env` loading for the whole suite — tests must never reach the real database or LLM keys.
- TeX runs with an allowlisted env, `shell_escape=f`, `openin_any=p`/`openout_any=p` (TeX Live; MiKTeX ignores the kpathsea vars). `main_file` must match `[A-Za-z0-9._/-]+` and end in `.tex`/`.latex`. Rerun detection reads the TeX `.log` (batchmode keeps warnings out of stdout).
- Live share sync (`WS /ws/share/{token}`) is owner-only: the client sends subprotocols `["edico-share", "bearer.<jwt>"]`; anonymous viewers get the `GET /share/{token}` snapshot.
- Billing: the payment-less QR checkout only runs when `BILLING_DEMO_CHECKOUT` is on (off by default in production); `/billing/upgrade` is god-admin only.
- Prisma migrations were verified locally against Postgres 16 (`migrate deploy` + `migrate diff --exit-code` with a shadow DB); CI repeats that check.

## Tooling

- **CI/CD** (`.github/workflows/`, no deployment): `ci.yml` (ruff, pytest on Python 3.11 + 3.12 with coverage, frontend lint/format/typecheck/test/build, Prisma migrations on Postgres 16), `security.yml` (CodeQL, pip-audit, npm audit, gitleaks, dependency review, license gate — no GPL/AGPL in shipped deps), `docker.yml` (build + smoke-test both images, nothing pushed), `latex.yml` (full suite on TeX Live), `release.yml` (tag `vX.Y.Z` → GitHub Release). Dependabot in `.github/dependabot.yml`.
- **Local gate**: `pre-commit install` once (hooks: ruff, Prettier + ESLint on staged frontend files, gitleaks on staged changes — needs the `gitleaks` binary, hygiene checks); `make ci` runs the backend + frontend checks CI runs. Tool versions are pinned in `requirements-dev.txt`. `.gitleaks.toml` keeps the default ruleset and allowlists one literal: the shared fake JWT key the test suite monkeypatches (`generic-api-key` flags it on entropy, so any PR adding another test that uses it would fail the scan).
- **Third-party licenses**: `THIRD_PARTY_NOTICES.md` + full texts in `LICENSES/` (verbatim, excluded from pre-commit); after dependency changes regenerate its tables with `python scripts/generate_third_party_notices.py` (pip-licenses + license-checker-rseidelsohn JSON; steps in the script docstring).
- **CodeGraph**: index lives in `.codegraph/` (local, git-ignored). After cloning run `codegraph init`; after large changes `codegraph sync`. Prefer `codegraph explore "<symbols or question>"` over grep for understanding code.
- **Skills** (installed with `npx autoskills -a claude-code`, pinned in `skills-lock.json`): backend/data skills in `.claude/skills/` (FastAPI, Pydantic, SQLAlchemy, Prisma, Python testing, Bash, frontend-design, accessibility, SEO) and frontend-scoped skills in `frontend/.claude/skills/` (React, composition patterns, TanStack Start, Vite, Vitest, Tailwind, shadcn, TypeScript). Re-run autoskills in the same folder to update; `.agents/` copies are git-ignored.
