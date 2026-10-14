from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from src.config import get_settings
from src.models.schemas import (
    CompileEnginesInfo,
    CompileRequest,
    CompileResponse,
    CompileStatusResponse,
)
from src.services.parser.latex import extract_cite_keys

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_LATEX_STUB_DIRS = (_PROJECT_ROOT / "frontend" / "public" / "latex-stubs",)
_STUB_FILES = ("IEEEtran.cls", "IEEEtran.bst", "tikz-cd.sty")
_LATEX_SUPPORT_SUFFIXES = {".cls", ".bst", ".sty", ".bib"}
_TEX_SUFFIXES = {".tex", ".latex"}
_COMPILER_NAMES = ("pdflatex", "xelatex", "lualatex", "latex")
LatexCompiler = Literal["auto", "pdflatex", "xelatex", "lualatex", "latex"]

# Custom Overleaf/journal classes → IEEE conference fallback when .cls is missing.
_DOCUMENTCLASS_FALLBACKS: dict[str, str] = {
    "RevDigMatEduInt": r"\documentclass[conference]{IEEEtran}",
    "revdigmateduint": r"\documentclass[conference]{IEEEtran}",
}
_WINDOWS_MIKTEX_BIN = (
    Path(r"C:\Program Files\MiKTeX\miktex\bin\x64"),
    Path(r"C:\Program Files (x86)\MiKTeX\miktex\bin"),
    Path.home() / "AppData" / "Local" / "Programs" / "MiKTeX" / "miktex" / "bin" / "x64",
)
_LOG_LIMIT = 200_000
_WORKSPACE_TTL_SEC = 2 * 60 * 60
_WORKSPACE_MAX = 24
_PDF_CACHE_TTL_SEC = 30 * 60
_PDF_CACHE_MAX = 32
_LATEX_INTERACTION = "batchmode"
_COMPILE_ARTIFACT_SUFFIXES = {
    ".log",
    ".aux",
    ".out",
    ".toc",
    ".lof",
    ".lot",
    ".pdf",
    ".synctex.gz",
    ".fls",
    ".fdb_latexmk",
    ".bbl",
    ".blg",
    ".bcf",
    ".run.xml",
    ".idx",
    ".ilg",
    ".ind",
    ".nav",
    ".snm",
    ".vrb",
}


class AssetResyncRequiredError(Exception):
    """Raised when hash-only assets are missing or stale in the compile workspace."""

    def __init__(self, names: list[str]):
        self.names = names
        super().__init__(f"ASSET_RESYNC_REQUIRED:{','.join(names)}")


class CompileBudgetExceededError(Exception):
    """Raised when a compile exceeds the configured wall-clock budget."""


class UnsafeMainFileError(ValueError):
    """Raised when main_file would resolve outside the compile workspace."""


@dataclass
class _CachedWorkspace:
    path: Path
    last_used: float


_workspaces: dict[str, _CachedWorkspace] = {}
_workspace_lock = threading.Lock()
_pdf_cache: dict[str, tuple[CompileResponse, float]] = {}
_pdf_cache_lock = threading.Lock()


def _find_executable(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for bin_dir in _WINDOWS_MIKTEX_BIN:
        candidate = bin_dir / f"{name}.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def find_pdflatex() -> str | None:
    return _find_executable("pdflatex")


def find_bibtex() -> str | None:
    return _find_executable("bibtex")


def find_biber() -> str | None:
    return _find_executable("biber")


def find_latexmk() -> str | None:
    return _find_executable("latexmk")


def find_tex_engine(compiler: str) -> str | None:
    if compiler not in _COMPILER_NAMES:
        return None
    return _find_executable(compiler)


def _engines_info() -> CompileEnginesInfo:
    return CompileEnginesInfo(
        pdflatex=find_pdflatex(),
        xelatex=find_tex_engine("xelatex"),
        lualatex=find_tex_engine("lualatex"),
        latex=find_tex_engine("latex"),
        latexmk=find_latexmk(),
        biber=find_biber(),
        bibtex=find_bibtex(),
    )


def compile_status() -> CompileStatusResponse:
    engines = _engines_info()
    primary = engines.pdflatex or engines.xelatex or engines.lualatex
    return CompileStatusResponse(
        available=primary is not None,
        engine=primary,
        engines=engines,
    )


def detect_compiler(latex: str, requested: LatexCompiler) -> str:
    if requested != "auto":
        return requested
    lowered = latex.lower()
    if any(token in lowered for token in ("\\usepackage{fontspec}", "\\setmainfont", "\\setmainlanguage")):
        if find_tex_engine("xelatex"):
            return "xelatex"
        if find_tex_engine("lualatex"):
            return "lualatex"
    if "\\usepackage{polyglossia}" in lowered and find_tex_engine("xelatex"):
        return "xelatex"
    if "\\usepackage{unicode-math}" in lowered and find_tex_engine("lualatex"):
        return "lualatex"
    return "pdflatex"


def uses_biblatex(latex: str) -> bool:
    lowered = latex.lower()
    return "biblatex" in lowered or "\\addbibresource" in lowered


def _decode_asset_payload(content_base64: str) -> bytes:
    payload = content_base64.strip()
    if "," in payload and payload.startswith("data:"):
        payload = payload.split(",", 1)[1]
    return base64.b64decode(payload)


def _safe_asset_path(name: str) -> Path | None:
    normalized = name.replace("\\", "/").lstrip("/")
    # ":" covers Windows drive letters (C:/x) and NTFS alternate streams (a.png:x), which
    # pathlib would resolve outside the workspace.
    if not normalized or ".." in normalized.split("/") or ":" in normalized:
        return None
    return Path(normalized)


def _extract_document_class(latex: str) -> str | None:
    match = re.search(r"\\documentclass\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}", latex)
    if not match:
        return None
    cls_name = match.group(1).strip()
    return Path(cls_name.replace("\\", "/")).name or None


def _is_usable_cls_file(cls_path: Path) -> bool:
    if not cls_path.is_file():
        return False
    try:
        if cls_path.stat().st_size < 32:
            return False
        content = cls_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return "\\ProvidesClass" in content or "\\LoadClass" in content or len(content) > 200


def _copy_support_files_to_root(work_dir: Path) -> None:
    for path in work_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _LATEX_SUPPORT_SUFFIXES:
            continue
        root_copy = work_dir / path.name
        if root_copy.resolve() != path.resolve() and not root_copy.exists():
            shutil.copy2(path, root_copy)


def _resolve_document_class(latex: str, work_dir: Path) -> tuple[str, list[str]]:
    warnings: list[str] = []
    cls_name = _extract_document_class(latex)
    if not cls_name:
        return latex, warnings

    if _is_usable_cls_file(work_dir / f"{cls_name}.cls"):
        return latex, warnings

    fallback = _DOCUMENTCLASS_FALLBACKS.get(cls_name) or _DOCUMENTCLASS_FALLBACKS.get(cls_name.lower())
    if fallback:
        substituted = re.sub(
            r"\\documentclass\s*(?:\[[^\]]*\])?\s*\{[^}]+\}",
            lambda _match: fallback,
            latex,
            count=1,
        )
        warnings.append(f"Missing {cls_name}.cls - auto-switched to IEEEtran conference layout for preview.")
        _copy_latex_stubs(work_dir, substituted)
        return substituted, warnings

    return latex, warnings


def _copy_latex_stubs(work_dir: Path, latex: str) -> None:
    needs_ieee = "IEEEtran" in latex
    needs_tikz_cd = "tikz-cd" in latex
    for root in _LATEX_STUB_DIRS:
        if not root.is_dir():
            continue
        for stub in _STUB_FILES:
            if stub.startswith("IEEEtran") and not needs_ieee:
                continue
            if stub == "tikz-cd.sty" and not needs_tikz_cd:
                continue
            src = root / stub
            dest = work_dir / stub
            if src.is_file() and not dest.exists():
                shutil.copy2(src, dest)


# Only these variables reach TeX subprocesses: user LaTeX runs there, so app secrets
# (AUTH_SECRET_KEY, *_API_KEY, DATABASE_URL, SMTP_*, ADMIN_*, ...) must never be inherited.
_TEX_ENV_ALLOWED_NAMES = frozenset(
    {
        "PATH",
        "HOME",
        "USERPROFILE",
        "TMP",
        "TEMP",
        "TMPDIR",
        "LANG",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "APPDATA",
        "LOCALAPPDATA",
        "PROGRAMDATA",
    }
)
_TEX_ENV_ALLOWED_PREFIXES = ("LC_", "FONTCONFIG_", "TEX", "MIKTEX", "BIB", "BST", "SOURCE_DATE_EPOCH")
# kpathsea reads these from the environment before texmf.cnf (TeX Live); MiKTeX ignores them.
_TEX_KPATHSEA_HARDENING = {
    "shell_escape": "f",  # no \write18 at all, not even the restricted list
    "openin_any": "p",  # no absolute paths, `..` or dotfiles for \input/\openin
    "openout_any": "p",  # same for \openout
}


def _is_allowed_tex_env_name(name: str) -> bool:
    upper = name.upper()
    return upper in _TEX_ENV_ALLOWED_NAMES or upper.startswith(_TEX_ENV_ALLOWED_PREFIXES)


def _tex_subprocess_env(*, allow_package_install: bool = True) -> dict[str, str]:
    """Minimal, hardened environment for TeX/BibTeX/latexmk/synctex subprocesses."""
    env = {name: value for name, value in os.environ.items() if _is_allowed_tex_env_name(name)}
    env.update(_TEX_KPATHSEA_HARDENING)
    if not _is_miktex():
        return env
    env["MIKTEX_DISABLE_DIAGNOSTICS"] = "1"
    if allow_package_install:
        env["MIKTEX_ENABLE_INSTALLER"] = "1"
        env["MIKTEX_ALLOW_UNATTENDED"] = "1"
    else:
        env["MIKTEX_ENABLE_INSTALLER"] = "0"
    return env


def _is_miktex() -> bool:
    return os.name == "nt"


def _pass_timeout_sec() -> int:
    return get_settings().compile_pass_timeout_sec


def _latexmk_timeout_sec() -> int:
    return get_settings().compile_latexmk_timeout_sec


def _build_tex_cmd(engine: str, main_file: str, *, synctex: bool) -> list[str]:
    cmd = [engine, f"-interaction={_LATEX_INTERACTION}"]
    if synctex:
        cmd.append("-synctex=1")
    if _is_miktex():
        cmd.append("--enable-installer")
        cmd.append("--disable-write18")
    else:
        cmd.append("-no-shell-escape")
    cmd.append(main_file)
    return cmd


_compile_budget_local = threading.local()


def _set_compile_budget(deadline: float | None) -> None:
    _compile_budget_local.deadline = deadline


def _assert_compile_budget() -> None:
    deadline = getattr(_compile_budget_local, "deadline", None)
    if deadline is not None and time.monotonic() > deadline:
        raise CompileBudgetExceededError("LaTeX compilation exceeded time budget.")


def _clear_compile_budget() -> None:
    _compile_budget_local.deadline = None


def _file_content_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assets_fingerprint(assets: list) -> str:
    digest = hashlib.sha256()
    for asset in sorted(assets, key=lambda item: item.name.lower()):
        digest.update(asset.name.encode("utf-8"))
        digest.update(b"\0")
        if asset.content_base64 and asset.content_base64.strip():
            digest.update(asset.content_base64.encode("utf-8"))
        elif asset.content_hash:
            digest.update(asset.content_hash.strip().lower().encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _workspace_cache_key(cache_id: str | None, assets_key: str, owner_key: str) -> str:
    """Workspace identity: the CALLER plus what they asked to compile.

    ``owner_key`` is derived server-side (``_compile_client_key`` in ``src/api/routes.py``: the
    authenticated user when the bearer token verifies, else the client IP) and is not optional,
    because both things it guards against were real:

    - ``cache_id`` is client-supplied and ``POST /compile`` has no auth dependency at all, so
      keying on it alone handed two unrelated callers the same directory. The frontend passes the
      SHARE TOKEN as ``cache_id`` on the anonymous share-viewer page
      (``frontend/src/routes/share.$token.tsx``), and ``/compile`` never consults the share
      service, so a forwarded or revoked link kept working as a key into that project's workspace.
    - ``_assets_fingerprint([])`` is ``sha256(b"")``, a constant, so every request with no
      ``cache_id`` and no assets -- the ordinary not-yet-saved-project path -- collapsed onto one
      global directory. That one needed no attacker at all.

    The owner goes in both branches rather than replacing the cache id, so a user recompiling
    their own project still reuses their own incremental workspace. Isolation must not cost that.
    """
    owner = _hash_owner_key(owner_key)
    project = (cache_id or "").strip()
    if project:
        return f"owner:{owner}|proj:{project}"
    return f"owner:{owner}|ephemeral:{assets_key}"


def _hash_owner_key(owner_key: str) -> str:
    """Short digest of the caller identity — it can be an IP, which has no business sitting in a
    dict key that gets logged or surfaced in a diagnostic."""
    return hashlib.sha256((owner_key or "anonymous").encode("utf-8")).hexdigest()[:32]


def _workspace_content_digest(
    work_dir: Path,
    *,
    latex: str,
    compiler: str,
    mode: str,
    main_file: str,
) -> str:
    digest = hashlib.sha256()
    digest.update(compiler.encode("utf-8"))
    digest.update(mode.encode("utf-8"))
    digest.update(main_file.encode("utf-8"))
    digest.update(latex.encode("utf-8"))
    for path in sorted(work_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(work_dir).as_posix()
        if any(rel.endswith(suffix) for suffix in _COMPILE_ARTIFACT_SUFFIXES):
            continue
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        if path.stat().st_size > 65_536:
            digest.update(_file_content_hash(path).encode("utf-8"))
        else:
            digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _prune_pdf_cache(now: float | None = None) -> None:
    now = now or time.monotonic()
    with _pdf_cache_lock:
        expired = [key for key, (_, ts) in _pdf_cache.items() if now - ts > _PDF_CACHE_TTL_SEC]
        for key in expired:
            _pdf_cache.pop(key, None)
        overflow = len(_pdf_cache) - _PDF_CACHE_MAX
        if overflow <= 0:
            return
        for key in sorted(_pdf_cache, key=lambda item: _pdf_cache[item][1])[:overflow]:
            _pdf_cache.pop(key, None)


def _get_cached_pdf(cache_key: str) -> CompileResponse | None:
    now = time.monotonic()
    _prune_pdf_cache(now)
    with _pdf_cache_lock:
        cached = _pdf_cache.get(cache_key)
        if not cached:
            return None
        response, ts = cached
        if now - ts > _PDF_CACHE_TTL_SEC:
            _pdf_cache.pop(cache_key, None)
            return None
        return response.model_copy(deep=True)


def _store_cached_pdf(cache_key: str, response: CompileResponse) -> None:
    if not response.success or not response.pdf_base64:
        return
    now = time.monotonic()
    _prune_pdf_cache(now)
    with _pdf_cache_lock:
        _pdf_cache[cache_key] = (response.model_copy(deep=True), now)


def _prune_workspaces(now: float | None = None) -> None:
    now = now or time.monotonic()
    expired = [key for key, workspace in _workspaces.items() if now - workspace.last_used > _WORKSPACE_TTL_SEC]
    for key in expired:
        workspace = _workspaces.pop(key)
        shutil.rmtree(workspace.path, ignore_errors=True)

    overflow = len(_workspaces) - _WORKSPACE_MAX
    if overflow <= 0:
        return
    for key in sorted(_workspaces, key=lambda item: _workspaces[item].last_used)[:overflow]:
        workspace = _workspaces.pop(key)
        shutil.rmtree(workspace.path, ignore_errors=True)


def _get_cached_compile_workspace(cache_id: str | None, *, owner_key: str) -> Path | None:
    """Look up a workspace the SAME caller stored earlier.

    Goes through ``_workspace_cache_key`` rather than rebuilding the key string here: when the
    owner component was added, a hand-built ``f"proj:{project}"`` silently stopped matching
    anything and broke SyncTeX's cached-workspace path with no test failure to show it.
    """
    project = (cache_id or "").strip()
    if not project:
        return None
    key = _workspace_cache_key(project, "", owner_key)
    with _workspace_lock:
        _prune_workspaces()
        cached = _workspaces.get(key)
        if cached and cached.path.is_dir():
            cached.last_used = time.monotonic()
            return cached.path
    return None


def _read_workspace_latex(work_dir: Path, jobname: str) -> str:
    safe_job = Path(jobname).stem or "main"
    candidates = [
        work_dir / f"{safe_job}.tex",
        work_dir / "main.tex",
    ]
    for path in candidates:
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")
    for path in sorted(work_dir.glob("*.tex")):
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")
    return ""


def _acquire_workspace(
    cache_id: str | None,
    assets: list,
    *,
    assets_key: str,
    owner_key: str,
) -> tuple[Path, bool]:
    workspace_key = _workspace_cache_key(cache_id, assets_key, owner_key)
    resync: list[str] = []

    with _workspace_lock:
        _prune_workspaces()
        cached = _workspaces.get(workspace_key)
        if cached and cached.path.is_dir():
            cached.last_used = time.monotonic()
            work_dir = cached.path
            fresh = False
        else:
            work_dir = Path(tempfile.mkdtemp(prefix="edico-latex-"))
            _workspaces[workspace_key] = _CachedWorkspace(path=work_dir, last_used=time.monotonic())
            fresh = True

    for asset in assets:
        rel = _safe_asset_path(asset.name)
        if rel is None:
            continue
        dest = work_dir / rel
        payload = (asset.content_base64 or "").strip()
        if payload:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(_decode_asset_payload(payload))
            continue

        expected = (asset.content_hash or "").strip().lower()
        if not expected:
            resync.append(asset.name)
            continue
        if not dest.is_file():
            resync.append(asset.name)
            continue
        if _file_content_hash(dest) != expected:
            resync.append(asset.name)

    if resync:
        raise AssetResyncRequiredError(resync)

    _mirror_figure_assets_to_root(work_dir)
    return work_dir, fresh


def _needs_full_toolchain(latex: str) -> bool:
    if uses_biblatex(latex):
        return True
    if _extract_bib_files(latex):
        return True
    if _extract_cite_keys(latex):
        return True
    if re.search(r"\\printbibliography\b", latex):
        return True
    return False


def _max_direct_passes(latex: str, *, fast: bool = False) -> int:
    if _needs_full_toolchain(latex):
        return 0
    if fast:
        return 1
    if re.search(
        r"\\(?:label|ref|eqref|pageref|autoref|cref|Cref|tableofcontents|listoffigures|listoftables)\b",
        latex,
    ):
        return 2
    return 1


def _extract_cite_keys(latex: str) -> set[str]:
    # Same matcher as the citation tools: \cite, natbib \citep[..][..]{..}, biblatex \parencite, …
    return set(extract_cite_keys(latex))


def _strip_latex_comments(latex: str) -> str:
    lines: list[str] = []
    for line in latex.splitlines():
        out: list[str] = []
        i = 0
        while i < len(line):
            if line[i] == "%" and (i == 0 or line[i - 1] != "\\"):
                break
            out.append(line[i])
            i += 1
        lines.append("".join(out))
    return "\n".join(lines)


def _normalize_bib_base(name: str) -> str | None:
    cleaned = name.strip().replace("\\", "/")
    if not cleaned or ".." in cleaned or cleaned.startswith("/"):
        return None
    base = Path(cleaned).name
    if not base or base.lower() == "ieeeabrv":
        return None
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", base):
        return None
    return base


def _extract_bib_files(latex: str) -> list[str]:
    cleaned = _strip_latex_comments(latex)
    names: list[str] = []
    for match in re.finditer(r"\\bibliography\{([^}]+)\}", cleaned):
        for part in match.group(1).split(","):
            base = _normalize_bib_base(part)
            if base and base not in names:
                names.append(base)
    return names


def _ensure_bibliography(work_dir: Path, latex: str) -> None:
    if uses_biblatex(latex):
        return
    cite_keys = _extract_cite_keys(latex)
    for bib_name in _extract_bib_files(latex):
        bib_path = work_dir / f"{bib_name}.bib"
        if bib_path.is_file():
            continue
        bib_path.parent.mkdir(parents=True, exist_ok=True)
        entries = "\n\n".join(
            f"@misc{{{key},\n  title = {{Reference placeholder for {key}}},\n  year = {{2024}}\n}}"
            for key in sorted(cite_keys)
        )
        bib_path.write_text(entries + "\n", encoding="utf-8")


_DROPPABLE_PACKAGES = {
    "flushend",
    "balance",
    "fixltx2e",
    "stfloats",
    "endfloat",
    "nidanfloat",
}


def _resolve_algorithm_package_conflict(latex: str) -> tuple[str, list[str]]:
    """algorithm2e and algorithms/algorithm packages cannot be loaded together."""
    warnings: list[str] = []
    has_algo2e = bool(re.search(r"\\usepackage(?:\[[^\]]*\])?\{algorithm2e\}", latex))
    has_algorithms = bool(re.search(r"\\usepackage(?:\[[^\]]*\])?\{[^}]*\balgorithms?\b", latex))
    if has_algo2e and has_algorithms:
        latex = re.sub(r"\\usepackage(?:\[[^\]]*\])?\{algorithm2e\}\s*\n?", "", latex)
        warnings.append("Removed `algorithm2e` (conflicts with `algorithm` / `algorithms`).")
    return latex, warnings


def _repair_latex_syntax(latex: str) -> tuple[str, list[str]]:
    """Fix common LaTeX corruptions from AI edits or manual mistakes."""
    warnings: list[str] = []

    if re.search(r"\\textbfface\b", latex, re.I):
        latex = re.sub(r"\\textbfface\b", r"\\textbf", latex, flags=re.I)
        warnings.append("Fixed typo `\\textbfface` → `\\textbf`.")

    if re.search(r"\\textbf\s*\{Introduction\}\s*In\s", latex, re.I) and not re.search(
        r"\\section\*?\{Introduction\}", latex, re.I
    ):
        latex = re.sub(
            r"\{?\s*\\textbf\s*\{Introduction\}\s*(?=In\s)",
            r"\\section{Introduction}\n",
            latex,
            count=1,
            flags=re.I,
        )
        warnings.append("Restored `\\section{Introduction}` from corrupted heading.")

    latex, n = re.subn(
        r"(\\(?:sub)*section\*?(?:\[[^\]]*\])?\{(?:[^{}]|\{[^{}]*\})*\})\s*\\+(?=\s*(?:\n|\\[a-zA-Z]|$))",
        r"\1",
        latex,
    )
    if n:
        warnings.append(f"Removed stray `\\\\` after {n} section heading(s).")

    latex, algo_warnings = _resolve_algorithm_package_conflict(latex)
    warnings.extend(algo_warnings)
    return latex, warnings


def _strip_droppable_packages(latex: str, extra: set[str] | None = None) -> str:
    droppable = _DROPPABLE_PACKAGES | (extra or set())

    def _replace(m: re.Match) -> str:
        names_str = m.group(1)
        names = [n.strip() for n in names_str.split(",")]
        kept = [n for n in names if n not in droppable]
        if not kept:
            return ""
        if len(kept) == len(names):
            return m.group(0)
        return r"\usepackage{" + ",".join(kept) + "}"

    return re.sub(
        r"\\usepackage(?:\[[^\]]*\])?\{([^}]+)\}",
        _replace,
        latex,
    )


_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".pdf", ".eps")


def _figure_available(fig_path: str, work_dir: Path) -> bool:
    """True when a figure file exists for an \\includegraphics path (with or without extension)."""
    normalized = fig_path.replace("\\", "/").strip()
    if not normalized:
        return False

    rel = Path(normalized)
    candidates: list[Path] = [work_dir / rel]
    if not rel.suffix:
        for ext in _IMAGE_EXTENSIONS:
            candidates.append(work_dir / f"{normalized}{ext}")

    name = rel.name
    stem = Path(name).stem if "." in name else name
    for ext in ("", *_IMAGE_EXTENSIONS):
        candidates.append(work_dir / f"{name}{ext}")
        candidates.append(work_dir / f"{stem}{ext}")

    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if candidate.is_file() and candidate.stat().st_size > 0:
            return True

    stem_guess = rel.stem if rel.suffix else normalized.split("/")[-1]
    for ext in _IMAGE_EXTENSIONS:
        if any(work_dir.rglob(f"*{stem_guess}{ext}")):
            return True
    return False


def _mirror_figure_assets_to_root(work_dir: Path) -> None:
    """Copy figures to compile root so basename-only \\includegraphics{} resolves."""
    for path in work_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _IMAGE_EXTENSIONS:
            continue
        root_copy = work_dir / path.name
        if root_copy.resolve() != path.resolve() and not root_copy.exists():
            shutil.copy2(path, root_copy)


def _prepare_latex_source(latex: str, work_dir: Path, asset_names: set[str]) -> tuple[str, list[str]]:
    warnings: list[str] = []
    prepared, repair_notes = _repair_latex_syntax(latex)
    if repair_notes:
        logger.info("LaTeX auto-repair applied: %s", "; ".join(repair_notes))
    prepared = prepared.replace(
        "[font=Medium, justification=raggedright]{caption}",
        "[font=small, justification=raggedright]{caption}",
    )
    prepared = _strip_droppable_packages(prepared)

    figure_paths = re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", prepared)
    missing_figures = [path for path in figure_paths if not _figure_available(path, work_dir)]
    if missing_figures and "\\usepackage{graphicx}" in prepared:
        prepared = prepared.replace(
            "\\usepackage{graphicx}",
            "\\usepackage[demo]{graphicx}",
            1,
        )

    return prepared, warnings


def _extract_missing_sty(log: str) -> str | None:
    m = re.search(r"File `([^']+\.sty)' not found", log)
    return m.group(1).replace(".sty", "") if m else None


def _extract_latex_error(log: str) -> str:
    missing_cls = re.search(r"File `([^']+\.cls)' not found", log)
    if missing_cls:
        cls_file = missing_cls.group(1)
        return (
            f"Missing LaTeX class file `{cls_file}`. Upload {cls_file} as a project asset, or change \\documentclass."
        )

    lines = log.splitlines()
    errors: list[str] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("! "):
            errors.append(stripped)
            if index + 1 < len(lines):
                next_line = lines[index + 1].strip()
                if next_line and not next_line.startswith("!"):
                    errors.append(next_line)
    if errors:
        return "\n".join(errors[-6:])
    for line in reversed(lines):
        if "Fatal error" in line or "Emergency stop" in line:
            return line.strip()
    return "PDF generation failed. Review the LaTeX log for errors."


def _main_file_path(work_dir: Path, main_file: str) -> Path:
    """Defence in depth on top of CompileRequest validation: never write outside work_dir."""
    root = work_dir.resolve()
    candidate = (root / main_file.replace("\\", "/")).resolve()
    if candidate == root or not candidate.is_relative_to(root):
        raise UnsafeMainFileError("main_file must stay inside the compile workspace")
    return candidate


def _jobname(main_file: str) -> str:
    return Path(main_file).stem or "main"


def _run_subprocess(
    cmd: list[str],
    work_dir: Path,
    timeout: int = 600,
    *,
    allow_package_install: bool = True,
) -> tuple[int, str]:
    _assert_compile_budget()
    result = subprocess.run(
        cmd,
        cwd=work_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        env=_tex_subprocess_env(allow_package_install=allow_package_install),
    )
    log = (result.stdout or "") + (result.stderr or "")
    return result.returncode, log


def _latexmk_compiler_flag(compiler: str) -> list[str]:
    if compiler == "pdflatex":
        return ["-pdf"]
    if compiler == "xelatex":
        return ["-xelatex"]
    if compiler == "lualatex":
        return ["-lualatex"]
    if compiler == "latex":
        return ["-pdfdvi"]
    return ["-pdf"]


def _run_latexmk(
    compiler: str,
    work_dir: Path,
    main_file: str,
    *,
    allow_package_install: bool = True,
    synctex: bool = True,
) -> tuple[int, str]:
    latexmk = find_latexmk()
    if not latexmk:
        return -1, ""
    cmd = [
        latexmk,
        *_latexmk_compiler_flag(compiler),
        f"-interaction={_LATEX_INTERACTION}",
    ]
    if synctex:
        cmd.append("-synctex=1")
    cmd.extend(["-halt-on-error", main_file])
    return _run_subprocess(
        cmd,
        work_dir,
        timeout=_latexmk_timeout_sec(),
        allow_package_install=allow_package_install,
    )


def _run_tex_pass(
    compiler: str,
    engine: str,
    work_dir: Path,
    main_file: str,
    *,
    allow_package_install: bool = True,
    synctex: bool = True,
) -> tuple[int, str]:
    cmd = _build_tex_cmd(engine, main_file, synctex=synctex)
    return _run_subprocess(
        cmd,
        work_dir,
        timeout=_pass_timeout_sec(),
        allow_package_install=allow_package_install,
    )


def _run_bibtex(
    work_dir: Path,
    jobname: str,
    bibtex: str | None = None,
    *,
    allow_package_install: bool = True,
) -> tuple[int, str]:
    engine = bibtex or find_bibtex() or "bibtex"
    return _run_subprocess(
        [engine, jobname],
        work_dir,
        timeout=120,
        allow_package_install=allow_package_install,
    )


def _run_biber(
    work_dir: Path,
    jobname: str,
    *,
    allow_package_install: bool = True,
) -> tuple[int, str]:
    biber = find_biber()
    if not biber:
        return -1, "biber not found"
    return _run_subprocess(
        [biber, jobname],
        work_dir,
        timeout=180,
        allow_package_install=allow_package_install,
    )


def _needs_rerun(log_text: str) -> bool:
    markers = (
        "Rerun to get",
        "rerun LaTeX",
        "Label(s) may have changed",
        "There were undefined references",
        "Citation(s) may have changed",
    )
    return any(m in log_text for m in markers)


def _pass_needs_rerun(stdout_log: str, work_dir: Path, jobname: str) -> bool:
    """Rerun check for the pass that just ran.

    In batchmode TeX prints its warnings ("There were undefined references", "Rerun to get ...")
    only to <jobname>.log, not stdout. The .log is rewritten by every pass, so it reflects this one.
    """
    try:
        tex_log = (work_dir / f"{jobname}.log").read_text(encoding="utf-8", errors="replace")
    except OSError:
        tex_log = ""
    return _needs_rerun(stdout_log) or _needs_rerun(tex_log)


def _direct_compile(
    compiler: str,
    work_dir: Path,
    main_file: str,
    passes: int,
    *,
    allow_package_install: bool = True,
    synctex: bool = True,
) -> list[str]:
    logs: list[str] = []
    engine = find_tex_engine(compiler)
    if not engine or passes <= 0:
        return logs

    jobname = _jobname(main_file)
    pdf_path = work_dir / f"{jobname}.pdf"

    for _ in range(passes):
        code, log = _run_tex_pass(
            compiler,
            engine,
            work_dir,
            main_file,
            allow_package_install=allow_package_install,
            synctex=synctex,
        )
        logs.append(log)
        if code != 0 and not pdf_path.is_file():
            break
        if not _pass_needs_rerun(log, work_dir, jobname):
            break

    return logs


def _manual_compile(
    compiler: str,
    work_dir: Path,
    main_file: str,
    main_latex: str,
    *,
    allow_package_install: bool = True,
    synctex: bool = True,
    fast: bool = False,
) -> list[str]:
    logs: list[str] = []
    engine = find_tex_engine(compiler)
    if not engine:
        logs.append(f"Engine `{compiler}` not found.")
        return logs

    jobname = _jobname(main_file)
    needs_bibtex = bool(_extract_bib_files(main_latex)) and not uses_biblatex(main_latex)
    needs_biber = uses_biblatex(main_latex)
    post_bib_passes = 1 if fast else 2

    def tex_passes() -> None:
        code, log = _run_tex_pass(
            compiler,
            engine,
            work_dir,
            main_file,
            allow_package_install=allow_package_install,
            synctex=synctex,
        )
        logs.append(log)
        if code != 0 and not (work_dir / f"{jobname}.pdf").exists():
            return
        if not fast and _pass_needs_rerun(log, work_dir, jobname):
            code, log = _run_tex_pass(
                compiler,
                engine,
                work_dir,
                main_file,
                allow_package_install=allow_package_install,
                synctex=synctex,
            )
            logs.append(log)

    tex_passes()

    if needs_biber:
        biber = find_biber()
        if biber:
            code, log = _run_biber(work_dir, jobname, allow_package_install=allow_package_install)
            logs.append(log)
            for _ in range(post_bib_passes):
                code, log = _run_tex_pass(
                    compiler,
                    engine,
                    work_dir,
                    main_file,
                    allow_package_install=allow_package_install,
                    synctex=synctex,
                )
                logs.append(log)
        else:
            logs.append("biblatex detected but biber is not installed.")

    if needs_bibtex:
        bibtex = find_bibtex()
        if bibtex:
            code, log = _run_bibtex(
                work_dir,
                jobname,
                bibtex,
                allow_package_install=allow_package_install,
            )
            logs.append(log)
            for _ in range(post_bib_passes):
                code, log = _run_tex_pass(
                    compiler,
                    engine,
                    work_dir,
                    main_file,
                    allow_package_install=allow_package_install,
                    synctex=synctex,
                )
                logs.append(log)

    return logs


def _read_synctex_gz(work_dir: Path, jobname: str) -> str:
    synctex_path = work_dir / f"{jobname}.synctex.gz"
    if not synctex_path.is_file():
        return ""
    return base64.b64encode(synctex_path.read_bytes()).decode("ascii")


def _force_apply_known_fallbacks(latex: str) -> tuple[str, list[str]]:
    applied: list[str] = []
    for cls_name, fallback_decl in _DOCUMENTCLASS_FALLBACKS.items():
        pattern = re.compile(
            r"\\documentclass\s*(?:\[[^\]]*\])?\s*\{" + re.escape(cls_name) + r"\}",
            re.IGNORECASE,
        )
        if pattern.search(latex):
            latex = pattern.sub(lambda _m: fallback_decl, latex, count=1)
            applied.append(f"Missing {cls_name}.cls - auto-switched to IEEEtran conference layout for preview.")
    return latex, applied


def _collect_all_tex_sources(main_latex: str, work_dir: Path, main_file: str) -> str:
    """Merge main + \\input/\\include .tex files for citation/bib detection."""
    combined = [main_latex]
    root = work_dir.resolve()
    for match in re.finditer(r"\\(?:input|include)\{([^}]+)\}", main_latex):
        rel = match.group(1).strip()
        if not rel.endswith((".tex", ".latex")):
            rel = f"{rel}.tex"
        candidate = (work_dir / rel.replace("\\", "/")).resolve()
        # `work_dir / "/abs/path"` is the absolute path itself — only read files in the workspace.
        if candidate.is_relative_to(root) and candidate.is_file():
            combined.append(candidate.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(combined)


def _run_compile_attempts(
    compiler: str,
    work_dir: Path,
    main_file: str,
    all_tex: str,
    *,
    allow_package_install: bool,
    fast: bool = False,
    synctex: bool = True,
) -> list[str]:
    logs: list[str] = []
    jobname = _jobname(main_file)
    pdf_path = work_dir / f"{jobname}.pdf"

    direct_passes = _max_direct_passes(all_tex, fast=fast)
    if direct_passes > 0:
        logs.extend(
            _direct_compile(
                compiler,
                work_dir,
                main_file,
                direct_passes,
                allow_package_install=allow_package_install,
                synctex=synctex,
            )
        )
        if pdf_path.is_file():
            return logs

    if _needs_full_toolchain(all_tex):
        logs.extend(
            _manual_compile(
                compiler,
                work_dir,
                main_file,
                all_tex,
                allow_package_install=allow_package_install,
                synctex=synctex,
                fast=fast,
            )
        )
        return logs

    latexmk_code, latexmk_log = _run_latexmk(
        compiler,
        work_dir,
        main_file,
        allow_package_install=allow_package_install,
        synctex=synctex,
    )
    if latexmk_code >= 0 and latexmk_log:
        logs.append(latexmk_log)

    if not pdf_path.is_file():
        logs.extend(
            _manual_compile(
                compiler,
                work_dir,
                main_file,
                all_tex,
                allow_package_install=allow_package_install,
                synctex=synctex,
                fast=fast,
            )
        )

    return logs


def compile_latex(request: CompileRequest, *, owner_key: str = "") -> CompileResponse:
    """``owner_key`` scopes the compile workspace to the caller — see ``_workspace_cache_key``.

    It defaults to empty only so existing unit tests can call this without inventing an identity;
    every production caller passes one (``src/api/routes.py`` hands over the same key it already
    computes for rate limiting). Two callers who both omit it still share, which is why the
    default must never be used by a route.
    """
    settings = get_settings()
    _set_compile_budget(time.monotonic() + settings.compile_total_budget_sec)
    try:
        return _compile_latex_impl(request, owner_key=owner_key)
    finally:
        _clear_compile_budget()


def _compile_latex_impl(request: CompileRequest, *, owner_key: str = "") -> CompileResponse:
    main_file = request.main_file.strip() or "main.tex"
    compiler = detect_compiler(request.latex, request.compiler)
    engine_path = find_tex_engine(compiler)
    compile_mode = request.mode or "full"
    fast = compile_mode == "fast"
    synctex = compile_mode == "full"

    if not engine_path:
        return CompileResponse(
            success=False,
            error=(
                f"`{compiler}` not found. Install MiKTeX (winget install MiKTeX.MiKTeX) "
                "or TeX Live with xelatex/lualatex support, then restart the backend."
            ),
            engine="none",
            compiler=compiler,
        )

    logs: list[str] = []
    warnings: list[str] = []
    jobname = _jobname(main_file)

    assets_key = _assets_fingerprint(request.assets)
    work_dir, fresh_workspace = _acquire_workspace(
        request.cache_id,
        request.assets,
        assets_key=assets_key,
        owner_key=owner_key,
    )
    allow_package_install = fresh_workspace
    asset_names = {Path(a.name).name for a in request.assets}

    patched_latex, fallback_warnings = _force_apply_known_fallbacks(request.latex)
    if fallback_warnings:
        warnings.extend(fallback_warnings)
        for cls_name in _DOCUMENTCLASS_FALLBACKS:
            bogus = work_dir / f"{cls_name}.cls"
            if bogus.is_file() and not _is_usable_cls_file(bogus):
                bogus.unlink(missing_ok=True)

    _copy_support_files_to_root(work_dir)

    prepared, prep_warnings = _prepare_latex_source(patched_latex, work_dir, asset_names)
    warnings.extend(prep_warnings)
    prepared, class_warnings = _resolve_document_class(prepared, work_dir)
    warnings.extend(class_warnings)

    main_path = _main_file_path(work_dir, main_file)
    main_path.parent.mkdir(parents=True, exist_ok=True)
    main_path.write_text(prepared, encoding="utf-8")

    _copy_latex_stubs(work_dir, prepared)
    all_tex = _collect_all_tex_sources(prepared, work_dir, main_file)
    _ensure_bibliography(work_dir, all_tex)

    pdf_cache_key = _workspace_content_digest(
        work_dir,
        latex=prepared,
        compiler=compiler,
        mode=compile_mode,
        main_file=main_file,
    )
    cached_pdf = _get_cached_pdf(pdf_cache_key)
    if cached_pdf is not None:
        if warnings and not cached_pdf.warning:
            cached_pdf.warning = "\n".join(warnings)
        return cached_pdf

    logs.extend(
        _run_compile_attempts(
            compiler,
            work_dir,
            main_file,
            all_tex,
            allow_package_install=allow_package_install,
            fast=fast,
            synctex=synctex,
        )
    )

    pdf_path = work_dir / f"{jobname}.pdf"
    if not pdf_path.is_file() and not fresh_workspace:
        logs.extend(
            _run_compile_attempts(
                compiler,
                work_dir,
                main_file,
                all_tex,
                allow_package_install=True,
                fast=fast,
                synctex=synctex,
            )
        )

    if not pdf_path.is_file():
        merged = "\n".join(logs)
        missing_sty = _extract_missing_sty(merged)
        if missing_sty and missing_sty not in _DROPPABLE_PACKAGES:
            warnings.append(f"Package `{missing_sty}` not available — removed for preview.")
            retry_tex = _strip_droppable_packages(prepared, extra={missing_sty})
            main_path.write_text(retry_tex, encoding="utf-8")
            all_tex = _collect_all_tex_sources(retry_tex, work_dir, main_file)
            logs.clear()
            logs.extend(
                _run_compile_attempts(
                    compiler,
                    work_dir,
                    main_file,
                    all_tex,
                    allow_package_install=True,
                    fast=fast,
                    synctex=synctex,
                )
            )

    if not pdf_path.is_file():
        merged_log = "\n".join(logs)
        return CompileResponse(
            success=False,
            log=merged_log[-_LOG_LIMIT:],
            error=_extract_latex_error(merged_log),
            engine=compiler,
            compiler=compiler,
        )

    synctex_b64 = _read_synctex_gz(work_dir, jobname) if synctex else ""
    if fast:
        (work_dir / f"{jobname}.synctex.gz").unlink(missing_ok=True)
    merged_log = "\n".join(logs)
    response = CompileResponse(
        success=True,
        pdf_base64=base64.b64encode(pdf_path.read_bytes()).decode("ascii"),
        log=merged_log[-_LOG_LIMIT:],
        engine=compiler,
        compiler=compiler,
        warning="\n".join(warnings),
        synctex_base64=synctex_b64,
        main_file=main_file,
    )
    _store_cached_pdf(pdf_cache_key, response)
    return response


def find_synctex() -> str | None:
    return _find_executable("synctex")


def _parse_synctex_cli_output(stdout: str) -> dict[str, str | int] | None:
    input_file = ""
    line_no = 0
    column_no = -1
    in_block = False
    for raw in stdout.splitlines():
        line = raw.strip()
        if line == "SyncTeX result begin":
            in_block = True
            continue
        if line == "SyncTeX result end":
            break
        if not in_block:
            continue
        if line.startswith("Input:"):
            input_file = line.split(":", 1)[1].strip()
        elif line.startswith("Line:"):
            try:
                line_no = int(line.split(":", 1)[1].strip())
            except ValueError:
                line_no = 0
        elif line.startswith("Column:"):
            try:
                column_no = int(line.split(":", 1)[1].strip())
            except ValueError:
                column_no = -1
    if not input_file or line_no < 0:
        return None
    return {
        "file": Path(input_file.replace("\\", "/")).name,
        "line": max(1, line_no),
        "column": column_no,
    }


def _normalize_match_text(text: str) -> str:
    cleaned = re.sub(r"\\[a-zA-Z*]+\{([^}]*)\}", r"\1", text)
    cleaned = re.sub(r"\\[a-zA-Z*]+", " ", cleaned)
    cleaned = re.sub(r"[{}]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned.lower()).strip()


def _resolve_line_by_context(
    latex: str,
    context: str,
    synctex_line: int,
    word: str = "",
) -> int | None:
    ctx = _normalize_match_text(context)
    if len(ctx) < 8:
        return None

    needle = word.strip().lower()
    words = ctx.split()
    lines = latex.splitlines()

    for length in range(len(words), 1, -1):
        for start in range(0, len(words) - length + 1):
            phrase = " ".join(words[start : start + length])
            if len(phrase) < 8:
                continue
            if needle and needle not in phrase:
                continue

            hits = [index + 1 for index, line in enumerate(lines) if phrase in _normalize_match_text(line)]
            if len(hits) == 1:
                return hits[0]
            if len(hits) > 1:
                return min(hits, key=lambda candidate: abs(candidate - synctex_line))

    return None


def _lines_containing_word(latex: str, word: str) -> list[int]:
    needle = word.strip().lower()
    if not needle:
        return []
    hits: list[int] = []
    for index, line in enumerate(latex.splitlines(), start=1):
        if needle in line.lower():
            hits.append(index)
    return hits


def _resolve_synctex_line(
    latex: str,
    synctex_line: int,
    word: str = "",
    context: str = "",
) -> int:
    """Map raw SyncTeX line to the source line that contains the clicked word."""
    ctx_line = _resolve_line_by_context(latex, context, synctex_line, word)
    if ctx_line:
        return ctx_line

    needle = word.strip().lower()
    if not needle or not latex.strip():
        return synctex_line

    lines = latex.splitlines()
    matches = [index + 1 for index, line in enumerate(lines) if needle in line.lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return min(matches, key=lambda candidate: abs(candidate - synctex_line))

    for delta in range(1, 31):
        for candidate in (synctex_line - delta, synctex_line + delta):
            if 1 <= candidate <= len(lines) and needle in lines[candidate - 1].lower():
                return candidate

    return synctex_line


resolve_synctex_line = _resolve_synctex_line


def resolve_synctex_line_from_request(
    cache_id: str | None,
    jobname: str,
    latex: str,
    synctex_line: int,
    word: str = "",
    context: str = "",
    owner_key: str = "",
) -> int:
    source_latex = latex.strip()
    if not source_latex and (cache_id or "").strip():
        work_dir = _get_cached_compile_workspace(cache_id, owner_key=owner_key)
        if work_dir is not None:
            source_latex = _read_workspace_latex(work_dir, Path(jobname).stem or "main")
    return resolve_synctex_line(source_latex, synctex_line, word, context)


def _synctex_inverse_probe(
    synctex: str,
    work_dir: Path,
    pdf_name: str,
    page: int,
    x: float,
    y: float,
) -> dict[str, str | int] | None:
    spec = f"{page}:{x:.2f}:{y:.2f}:{pdf_name}"
    result = subprocess.run(
        [synctex, "edit", "-o", spec, "-d", str(work_dir)],
        cwd=work_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
        env=_tex_subprocess_env(),
    )
    if result.returncode != 0 and "SyncTeX result begin" not in (result.stdout or ""):
        return None
    return _parse_synctex_cli_output(result.stdout or "")


def _synctex_inverse_with_workdir(
    synctex: str,
    work_dir: Path,
    pdf_name: str,
    page: int,
    x: float,
    y: float,
) -> dict[str, str | int | float] | None:
    hit = _synctex_inverse_probe(synctex, work_dir, pdf_name, page, x, y)
    if not hit:
        return None
    return {
        "file": hit["file"],
        "line": hit["line"],
        "column": hit.get("column", -1),
        "page": page,
        "x": x,
        "y": y,
    }


def _best_candidate_yscan(
    synctex: str,
    work_dir: Path,
    pdf_name: str,
    page: int,
    x: float,
    y: float,
    candidates: list[int],
) -> int:
    best_line = candidates[0]
    best_score = 10_000
    for dy in range(-40, 41, 8):
        probe = _synctex_inverse_probe(synctex, work_dir, pdf_name, page, x, y + dy)
        if not probe:
            continue
        probe_line = int(probe.get("line", 0))
        for candidate in candidates:
            score = abs(dy) + abs(probe_line - candidate)
            if score < best_score:
                best_score = score
                best_line = candidate
                if score == 0:
                    return best_line
    return best_line


def parse_synctex_inverse_disambiguated(
    synctex_gz_b64: str,
    pdf_b64: str,
    page: int,
    x: float,
    y: float,
    jobname: str = "main",
    word: str = "",
    latex: str = "",
    context: str = "",
    cache_id: str | None = None,
    owner_key: str = "",
) -> dict[str, str | int | float] | None:
    """Inverse SyncTeX with y-scan when the same word appears on multiple lines."""
    synctex = find_synctex()
    if not synctex:
        return None

    safe_job = Path(jobname).stem or "main"
    pdf_name = f"{safe_job}.pdf"
    synctex_name = f"{safe_job}.synctex.gz"

    work_dir = _get_cached_compile_workspace(cache_id, owner_key=owner_key)
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if work_dir is not None:
        if not (work_dir / pdf_name).is_file() or not (work_dir / synctex_name).is_file():
            work_dir = None

    if work_dir is None:
        if not synctex_gz_b64 or not pdf_b64:
            return None
        try:
            pdf_bytes = base64.b64decode(pdf_b64)
            synctex_bytes = base64.b64decode(synctex_gz_b64)
        except (OSError, ValueError):
            return None
        temp_dir = tempfile.TemporaryDirectory(prefix="edico-synctex-")
        work_dir = Path(temp_dir.name)
        (work_dir / pdf_name).write_bytes(pdf_bytes)
        (work_dir / synctex_name).write_bytes(synctex_bytes)

    assert work_dir is not None
    source_latex = latex.strip() or _read_workspace_latex(work_dir, safe_job)

    try:
        base = _synctex_inverse_with_workdir(synctex, work_dir, pdf_name, page, x, y)
        if not base:
            return None

        ctx_line = (
            _resolve_line_by_context(source_latex, context, int(base.get("line", 0)), word)
            if context.strip() and word.strip() and source_latex.strip()
            else None
        )
        if ctx_line:
            return {
                "file": str(base.get("file", "main.tex")),
                "line": ctx_line,
                "column": int(base.get("column", -1)),
                "page": page,
                "x": x,
                "y": y,
            }

        candidates = _lines_containing_word(source_latex, word) if word.strip() and source_latex.strip() else []
        if len(candidates) > 1:
            raw_line = int(base.get("line", 0))
            if raw_line in candidates:
                return {
                    "file": str(base.get("file", "main.tex")),
                    "line": raw_line,
                    "column": int(base.get("column", -1)),
                    "page": page,
                    "x": x,
                    "y": y,
                }

        if len(candidates) <= 1:
            return base

        best_line = _best_candidate_yscan(synctex, work_dir, pdf_name, page, x, y, candidates)
        return {
            "file": str(base.get("file", "main.tex")),
            "line": best_line,
            "column": int(base.get("column", -1)),
            "page": page,
            "x": x,
            "y": y,
        }
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()
