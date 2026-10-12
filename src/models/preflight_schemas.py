"""Request/response models for Submission Preflight (POST /api/v1/preflight/run).

Pydantic lives here, not under ``src/services/preflight/``, matching every other
``response_model`` in this repo (``schemas.py``, ``citation_schemas.py``,
``ai_disclosure_schemas.py``, ``peer_review_schemas.py`` all live under ``src/models/``). The
services layer stays pure dataclasses and plain functions — see
``src/services/preflight/catalogue.py``'s ``Finding`` and ``src/services/preflight/source.py``;
only ``runner.py`` builds the models defined here.

Models are copied from the design spec, section 4.2 (``PreflightProfile``, ``PreflightFinding``,
``PreflightReport``) and section 4.3 (``PreflightFile``, ``PreflightRequest``).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from src.models.schemas import validate_main_file_path

PreflightSeverity = Literal["critical", "warning", "info"]
PreflightGroup = Literal["crossref", "bib", "statement", "format", "anon", "length"]
RequiredStatement = Literal["data_availability", "ethics", "coi", "funding", "author_contributions"]


class PreflightProfile(BaseModel):
    double_blind: bool = False
    word_limit: int | None = Field(default=None, ge=1, le=100_000)
    required_statements: list[RequiredStatement] = Field(
        default_factory=lambda: ["data_availability", "ethics", "coi", "funding"]
    )


class PreflightFinding(BaseModel):
    id: str  # "crossref.undefined_ref:0" — stable within one report
    rule: str  # "crossref.undefined_ref"
    group: PreflightGroup
    severity: PreflightSeverity
    file: str = ""  # path of the file containing the fault (multi-file)
    line: int | None = None  # 1-based WITHIN that file
    symbol: str = ""  # violating token ("fig:pipeline") — frontend interpolates this into copy
    count: int = 1  # occurrence count, for rules like large_negative_vspace
    excerpt: str = ""  # short context for display


class PreflightReport(BaseModel):
    integrity_mode: str = "comment_only"
    findings: list[PreflightFinding] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)  # severity -> count
    # group did not run -- either not declared (anon when not double-blind, length when no
    # word_limit) or, on the no-content path, every group at once, for a different reason
    # (nothing to analyse, not "undeclared"); `no_content` below is what tells the two apart.
    skipped: list[str] = Field(default_factory=list)
    suppressed: list[str] = Field(default_factory=list)  # rule disabled due to the 3.5 conflict
    # \input targets absent from the request payload (surfaced so the panel can explain why a
    # rule group's findings may be incomplete — see source.py's build_source).
    unresolved_includes: list[str] = Field(default_factory=list)
    # True when there was nothing to analyse at all (no files, or every resolved file is blank/
    # comment-only once masked) -- see runner.py's "no-content path". Deliberately a separate
    # field from `skipped`: `skipped` already means "not declared" (anon/length), and overloading
    # it to also mean "nothing to analyse" would leave the panel unable to tell the two apart.
    no_content: bool = False


class PreflightFile(BaseModel):
    path: str = Field(..., min_length=1, max_length=512)
    content: str = Field(default="", max_length=500_000)


class PreflightRequest(BaseModel):
    main_file: str = Field(default="main.tex", max_length=512)  # validated below
    files: list[PreflightFile] = Field(default_factory=list, max_length=64)
    bib_content: str = Field(default="", max_length=500_000)
    profile: PreflightProfile = Field(default_factory=PreflightProfile)

    @field_validator("main_file", mode="before")
    @classmethod
    def _safe_main_file(cls, value: object) -> str:
        return validate_main_file_path(value)
