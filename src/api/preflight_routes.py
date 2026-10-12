"""HTTP endpoint for Submission Preflight — a deterministic, read-only static-analysis report.

Thin by design: authenticate, hand the body straight to the pure runner, return its report. No
session store, no DB read beyond authentication, no quota call — see the design spec, section 4.3
(``docs/superpowers/specs/2026-10-11-submission-preflight-design.md``).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from src.api.deps import get_current_user
from src.db.models import User
from src.models.preflight_schemas import PreflightReport, PreflightRequest
from src.services.preflight.runner import run_preflight

router = APIRouter(prefix="/preflight", tags=["preflight"])


@router.post("/run", response_model=PreflightReport)
def preflight_run(
    request: PreflightRequest,
    user: User = Depends(get_current_user),
) -> PreflightReport:
    """Run every applicable preflight rule group over the submitted LaTeX source.

    A non-empty ``files`` list whose paths do not include ``main_file`` is rejected here rather
    than left to the runner: ``build_source`` resolves content only from ``main_file``, so a wrong
    one silently discards every byte the client sent, and the runner would answer with a clean,
    empty report over a request that actually carried analysable content. That is a client bug
    (a wrong ``main_file``), not "nothing to analyse" (which is exactly what an empty ``files``
    list still is, and keeps returning 200 with an empty report). Keeping this check here, instead
    of as a validator on ``PreflightRequest``, leaves the runner's "never raises, always returns a
    report" contract intact for every other caller, and leaves ``PreflightRequest`` usable as a
    plain data object in the runner's own unit tests, several of which construct it directly with
    a ``main_file`` that does not match its ``files``.
    """
    if request.files and request.main_file not in {f.path for f in request.files}:
        raise HTTPException(
            status_code=422,
            detail=f"main_file '{request.main_file}' is not among the submitted files.",
        )
    return run_preflight(request)
