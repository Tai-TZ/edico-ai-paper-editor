"""Tests for LaTeX compile service (Overleaf parity)."""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.models.schemas import CompileRequest
from src.services import latex_compile as lc


@pytest.fixture(autouse=True)
def _clear_compile_workspaces():
    yield
    with lc._workspace_lock:
        for workspace in lc._workspaces.values():
            shutil.rmtree(workspace.path, ignore_errors=True)
        lc._workspaces.clear()
    with lc._pdf_cache_lock:
        lc._pdf_cache.clear()


def _cached_workspace_for(cache_id: str, owner_key: str = "") -> lc._CachedWorkspace:
    """The workspace a ``compile_latex(...)`` call stored for ``cache_id``.

    Goes through ``_workspace_cache_key`` instead of spelling the key format out here. The two
    callers below are TeX-gated, so a hardcoded ``f"proj:{cache_id}"`` rots silently in every
    environment without pdflatex and surfaces only in the TeX Live workflow — which is exactly
    what happened when the owner component was added to the key.
    """
    return lc._workspaces[lc._workspace_cache_key(cache_id, "", owner_key)]


def test_detect_compiler_defaults_to_pdflatex():
    assert lc.detect_compiler(r"\documentclass{article}", "auto") == "pdflatex"


def test_detect_compiler_fontspec_prefers_xelatex(monkeypatch):
    monkeypatch.setattr(lc, "find_tex_engine", lambda name: "/usr/bin/xelatex" if name == "xelatex" else None)
    src = r"\documentclass{article}\usepackage{fontspec}"
    assert lc.detect_compiler(src, "auto") == "xelatex"


def test_uses_biblatex_detection():
    assert lc.uses_biblatex(r"\usepackage{biblatex}")
    assert not lc.uses_biblatex(r"\bibliography{refs}")


def test_extract_bib_files_ignores_commented_ieee_example():
    latex = r"""
\begin{document}
%\bibliography{IEEEabrv,../bib/paper}
\bibliography{references}
\end{document}
"""
    assert lc._extract_bib_files(latex) == ["references"]


def test_extract_bib_files_splits_comma_separated_names():
    latex = r"\bibliography{refs,extra}"
    assert lc._extract_bib_files(latex) == ["refs", "extra"]


def test_compile_status_shape():
    status = lc.compile_status()
    assert hasattr(status, "available")
    assert hasattr(status, "engines")


def test_safe_asset_path_rejects_traversal():
    assert lc._safe_asset_path("../etc/passwd") is None
    assert lc._safe_asset_path("figures/a.png") is not None


def test_figure_available_matches_extensionless_includegraphics(tmp_path):
    figures = tmp_path / "figures"
    figures.mkdir()
    (figures / "architecture.png").write_bytes(b"\x89PNG\r\n")

    assert lc._figure_available("figures/architecture", tmp_path) is True
    assert lc._figure_available("architecture", tmp_path) is True


def test_prepare_latex_source_keeps_graphicx_when_figure_exists(tmp_path):
    (tmp_path / "diagram.pdf").write_bytes(b"%PDF-1.4")
    latex = r"\usepackage{graphicx}\includegraphics{diagram}"
    prepared, _warnings = lc._prepare_latex_source(latex, tmp_path, set())
    assert "[demo]{graphicx}" not in prepared


def test_prepare_latex_source_uses_demo_when_figure_missing(tmp_path):
    latex = r"\usepackage{graphicx}\includegraphics{missing-figure}"
    prepared, _warnings = lc._prepare_latex_source(latex, tmp_path, set())
    assert "[demo]{graphicx}" in prepared


def test_repair_latex_syntax_fixes_textbfface_and_stray_backslash():
    broken = (
        r"\documentclass{article}"
        r"\usepackage{algorithm2e}"
        r"\usepackage{algorithm,algorithmic}"
        r"\textbfface{broken heading}"
        r"\subsubsection{Foo}\\"
        r"{\textbf{Introduction}In Thailand"
    )
    fixed, warnings = lc._repair_latex_syntax(broken)
    assert r"\textbf" in fixed
    assert "textbfface" not in fixed.lower()
    assert r"\subsubsection{Foo}" in fixed
    assert r"\subsubsection{Foo}\\" not in fixed
    assert r"\section{Introduction}" in fixed
    assert "algorithm2e" not in fixed
    assert warnings


def test_repair_latex_syntax_simplifies_section_textbf():
    src = r"\section{\textbf{Conclusion}}"
    fixed, warnings = lc._repair_latex_syntax(src)
    assert fixed == src
    assert not warnings


def test_force_apply_known_fallbacks():
    src = r"\documentclass{RevDigMatEduInt}"
    patched, warnings = lc._force_apply_known_fallbacks(src)
    assert "IEEEtran" in patched
    assert warnings


def test_compile_missing_engine(monkeypatch):
    monkeypatch.setattr(lc, "find_tex_engine", lambda _c: None)
    result = lc.compile_latex(CompileRequest(latex=r"\documentclass{article}\begin{document}hi\end{document}"))
    assert result.success is False
    assert "not found" in result.error.lower()


def test_synctex_inverse_when_available():
    if not lc.find_pdflatex() or not lc.find_synctex():
        return
    req = CompileRequest(
        latex="\\documentclass{article}\\begin{document}\nTarget line here\n\\end{document}",
        compiler="pdflatex",
    )
    result = lc.compile_latex(req)
    assert result.success and result.synctex_base64
    hit = lc.parse_synctex_inverse_disambiguated(result.synctex_base64, result.pdf_base64, 1, 200.0, 650.0, "main")
    assert hit is not None
    assert hit["line"] >= 1


def test_synctex_inverse_uses_cached_workspace():
    if not lc.find_pdflatex() or not lc.find_synctex():
        return
    cache_id = "test-synctex-cache"
    req = CompileRequest(
        latex="\\documentclass{article}\\begin{document}\nTarget line here\n\\end{document}",
        compiler="pdflatex",
        cache_id=cache_id,
    )
    result = lc.compile_latex(req)
    assert result.success and result.synctex_base64
    hit = lc.parse_synctex_inverse_disambiguated(
        "",
        "",
        1,
        200.0,
        650.0,
        "main",
        cache_id=cache_id,
    )
    assert hit is not None
    assert hit["line"] >= 1


def test_max_direct_passes_simple_article():
    latex = r"\documentclass{article}\begin{document}Hello\end{document}"
    assert lc._max_direct_passes(latex) == 1


def test_max_direct_passes_with_references():
    latex = r"\documentclass{article}\begin{document}\label{sec:a}See \ref{sec:a}\end{document}"
    assert lc._max_direct_passes(latex) == 2


def test_max_direct_passes_with_bibliography():
    latex = r"\documentclass{article}\begin{document}\cite{smith}\bibliography{refs}\end{document}"
    assert lc._max_direct_passes(latex) == 0


def test_assets_fingerprint_changes_with_asset_content():
    from src.models.schemas import CompileAssetFile

    a = [CompileAssetFile(name="a.tex", content_base64="ZGE=")]
    b = [CompileAssetFile(name="a.tex", content_base64="ZGI=")]
    assert lc._assets_fingerprint(a) != lc._assets_fingerprint(b)


def test_workspace_cache_key_scopes_by_project():
    assets_key = "abc123"
    owner = "user:alice"
    assert lc._workspace_cache_key("proj-1", assets_key, owner) != lc._workspace_cache_key("proj-2", assets_key, owner)
    assert lc._workspace_cache_key("proj-1", assets_key, owner) == lc._workspace_cache_key("proj-1", assets_key, owner)


# The property the test above never checked: scoping by project is not the same as isolating
# between callers. `cache_id` is client-supplied and /compile has no auth dependency at all, so
# before the owner component existed, two unrelated callers sending the same cache_id were handed
# the same directory on disk -- and the frontend passes the SHARE TOKEN as cache_id on the
# anonymous share-viewer page (frontend/src/routes/share.$token.tsx), making it reachable by
# anyone holding a link, including a revoked one.
def test_two_callers_sending_the_same_cache_id_do_not_share_a_workspace_key():
    assets_key = "abc123"
    alice = lc._workspace_cache_key("same-project-id", assets_key, "user:alice")
    bob = lc._workspace_cache_key("same-project-id", assets_key, "user:bob")
    assert alice != bob


# _assets_fingerprint([]) is sha256(b"") -- a fixed constant -- so every request with no cache_id
# and no assets (the normal not-yet-saved-project path) collapsed onto ONE global directory. This
# needed no attacker and no guessed value: it was the default.
def test_two_callers_with_no_cache_id_and_no_assets_do_not_share_a_workspace_key():
    empty = lc._assets_fingerprint([])
    alice = lc._workspace_cache_key(None, empty, "user:alice")
    bob = lc._workspace_cache_key(None, empty, "user:bob")
    assert alice != bob


def test_the_same_caller_still_reuses_its_own_workspace():
    # The whole point of the cache: one user recompiling the same project keeps the incremental
    # workspace. Isolation must not cost that.
    empty = lc._assets_fingerprint([])
    assert lc._workspace_cache_key("proj-1", empty, "user:alice") == lc._workspace_cache_key(
        "proj-1", empty, "user:alice"
    )
    assert lc._workspace_cache_key(None, empty, "user:alice") == lc._workspace_cache_key(None, empty, "user:alice")


def test_acquire_workspace_hands_different_directories_to_different_callers():
    alice_dir, _ = lc._acquire_workspace("shared-cache-id", [], assets_key="k", owner_key="user:alice")
    (alice_dir / "unpublished.tex").write_text("Alice's unpublished manuscript")
    bob_dir, _ = lc._acquire_workspace("shared-cache-id", [], assets_key="k", owner_key="user:bob")
    assert bob_dir != alice_dir
    assert not (bob_dir / "unpublished.tex").exists()


def test_compile_minimal_document_when_pdflatex_available():
    if not lc.find_pdflatex():
        return
    req = CompileRequest(
        latex=r"\documentclass{article}\begin{document}Hello Edico\end{document}",
        compiler="pdflatex",
    )
    result = lc.compile_latex(req)
    assert result.success is True
    assert result.pdf_base64
    assert result.compiler == "pdflatex"


def test_compile_reuses_workspace_with_hash_only_assets():
    if not lc.find_pdflatex():
        return
    from src.models.schemas import CompileAssetFile

    tex = r"\documentclass{article}\begin{document}Hello\end{document}"
    asset = CompileAssetFile(name="extra.tex", content_base64="ZGE=")
    first = lc.compile_latex(
        CompileRequest(latex=tex, compiler="pdflatex", cache_id="proj-delta", assets=[asset]),
    )
    assert first.success is True
    asset_hash = lc._file_content_hash(
        _cached_workspace_for("proj-delta").path / "extra.tex",
    )
    second = lc.compile_latex(
        CompileRequest(
            latex=r"\documentclass{article}\begin{document}Hello again\end{document}",
            compiler="pdflatex",
            cache_id="proj-delta",
            assets=[CompileAssetFile(name="extra.tex", content_hash=asset_hash)],
        ),
    )
    assert second.success is True


def test_compile_pdf_cache_returns_without_rerunning_tex():
    if not lc.find_pdflatex():
        return
    req = CompileRequest(
        latex=r"\documentclass{article}\begin{document}Cache me\end{document}",
        compiler="pdflatex",
        cache_id="proj-cache",
    )
    first = lc.compile_latex(req)
    assert first.success is True

    original_run = lc._run_compile_attempts

    def boom(*_args, **_kwargs):
        raise AssertionError("compile should have been served from cache")

    lc._run_compile_attempts = boom
    try:
        second = lc.compile_latex(req)
        assert second.success is True
        assert second.pdf_base64 == first.pdf_base64
    finally:
        lc._run_compile_attempts = original_run


def test_asset_resync_when_hash_only_missing():
    from src.models.schemas import CompileAssetFile

    with pytest.raises(lc.AssetResyncRequiredError):
        lc._acquire_workspace(
            "proj-missing",
            [CompileAssetFile(name="fig.png", content_hash="a" * 64)],
            assets_key="deadbeef",
            owner_key="user:alice",
        )


def test_build_tex_cmd_omits_enable_installer_on_posix(monkeypatch):
    monkeypatch.setattr(lc, "_is_miktex", lambda: False)
    cmd = lc._build_tex_cmd("/usr/bin/pdflatex", "main.tex", synctex=True)
    assert "--enable-installer" not in cmd
    assert cmd[-1] == "main.tex"


def test_build_tex_cmd_includes_enable_installer_on_miktex(monkeypatch):
    monkeypatch.setattr(lc, "_is_miktex", lambda: True)
    cmd = lc._build_tex_cmd("pdflatex", "main.tex", synctex=False)
    assert "--enable-installer" in cmd


def test_build_tex_cmd_disables_shell_escape_on_tex_live(monkeypatch):
    monkeypatch.setattr(lc, "_is_miktex", lambda: False)
    cmd = lc._build_tex_cmd("/usr/bin/pdflatex", "main.tex", synctex=False)
    assert "-no-shell-escape" in cmd
    assert "--disable-write18" not in cmd
    assert cmd.index("-no-shell-escape") < cmd.index("main.tex")


def test_build_tex_cmd_disables_write18_on_miktex(monkeypatch):
    monkeypatch.setattr(lc, "_is_miktex", lambda: True)
    cmd = lc._build_tex_cmd("pdflatex", "main.tex", synctex=True)
    assert "--disable-write18" in cmd
    assert "-no-shell-escape" not in cmd
    assert cmd.index("--disable-write18") < cmd.index("main.tex")


_APP_SECRETS = {
    "AUTH_SECRET_KEY": "jwt-secret-value",
    "OPENAI_API_KEY": "sk-openai-secret",
    "GOOGLE_API_KEY": "google-secret",
    "OPENROUTER_API_KEY": "or-secret",
    "DATABASE_URL": "postgresql://u:p@db/x",
    "DIRECT_DATABASE_URL": "postgresql://u:p@db/direct",
    "ADMIN_GOD_PASSWORD": "god-password",
    "SMTP_PASSWORD": "smtp-password",
    "GOOGLE_CLIENT_SECRET": "oauth-secret",
}


@pytest.mark.parametrize("miktex", [False, True])
def test_tex_env_excludes_app_secrets(monkeypatch, miktex):
    monkeypatch.setattr(lc, "_is_miktex", lambda: miktex)
    for name, value in _APP_SECRETS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("TEXMFHOME", "/srv/texmf")
    monkeypatch.setenv("LC_ALL", "C.UTF-8")
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "0")

    env = lc._tex_subprocess_env()

    upper_names = {name.upper() for name in env}
    for name in _APP_SECRETS:
        assert name not in upper_names
    assert not set(env.values()) & set(_APP_SECRETS.values())
    assert env["TEXMFHOME"] == "/srv/texmf"
    assert env["LC_ALL"] == "C.UTF-8"
    assert env["SOURCE_DATE_EPOCH"] == "0"
    assert "PATH" in upper_names


@pytest.mark.parametrize("miktex", [False, True])
def test_tex_env_sets_kpathsea_hardening(monkeypatch, miktex):
    monkeypatch.setattr(lc, "_is_miktex", lambda: miktex)
    monkeypatch.setenv("openin_any", "a")  # an inherited permissive value must not win

    env = lc._tex_subprocess_env()

    assert env["shell_escape"] == "f"
    assert env["openin_any"] == "p"
    assert env["openout_any"] == "p"


def test_tex_env_keeps_miktex_installer_flags(monkeypatch):
    monkeypatch.setattr(lc, "_is_miktex", lambda: True)
    allowed = lc._tex_subprocess_env(allow_package_install=True)
    assert allowed["MIKTEX_ENABLE_INSTALLER"] == "1"
    assert allowed["MIKTEX_ALLOW_UNATTENDED"] == "1"
    assert allowed["MIKTEX_DISABLE_DIAGNOSTICS"] == "1"
    blocked = lc._tex_subprocess_env(allow_package_install=False)
    assert blocked["MIKTEX_ENABLE_INSTALLER"] == "0"


def _pdflatex_is_tex_live() -> bool:
    if os.name == "nt":
        return False
    pdflatex = lc.find_pdflatex()
    if not pdflatex:
        return False
    try:
        version = subprocess.run([pdflatex, "--version"], capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    banner = (version.stdout or "") + (version.stderr or "")
    return "TeX Live" in banner and "MiKTeX" not in banner


@pytest.mark.skipif(not _pdflatex_is_tex_live(), reason="needs TeX Live pdflatex (kpathsea openin_any)")
def test_compile_cannot_input_absolute_path_outside_workspace(tmp_path):
    marker = f"EDICOLEAK{uuid.uuid4().hex}"
    secret = tmp_path / "secret.tex"
    # \typeout would copy the marker into the log if TeX ever read the file.
    secret.write_text(f"\\typeout{{{marker}}}\n{marker}\n", encoding="utf-8")
    latex = (
        f"\\documentclass{{article}}\n\\begin{{document}}\n\\input{{{secret.as_posix()}}}\nBody\n\\end{{document}}\n"
    )

    cache_id = f"leak-{uuid.uuid4().hex}"

    result = lc.compile_latex(CompileRequest(latex=latex, compiler="pdflatex", cache_id=cache_id))

    assert marker not in result.log
    assert marker not in result.error
    # batchmode keeps \typeout out of stdout, so also check TeX's own transcript in the workspace.
    tex_log = _cached_workspace_for(cache_id).path / "main.log"
    if tex_log.is_file():
        assert marker not in tex_log.read_text(encoding="utf-8", errors="replace")
    assert result.success is False or "openin_any" in result.log


def test_compile_budget_exceeded():
    import time

    lc._set_compile_budget(time.monotonic() - 1)
    with pytest.raises(lc.CompileBudgetExceededError):
        lc._assert_compile_budget()
    lc._clear_compile_budget()


@pytest.mark.parametrize("main_file", ["main.tex", "chapters/intro.tex", "paper-v2_final.latex", "a/b/c.TeX"])
def test_compile_request_accepts_safe_main_file(main_file):
    assert CompileRequest(latex="x", main_file=main_file).main_file == main_file


@pytest.mark.parametrize("main_file", ["", "   "])
def test_compile_request_blank_main_file_defaults(main_file):
    assert CompileRequest(latex="x", main_file=main_file).main_file == "main.tex"


@pytest.mark.parametrize(
    "main_file",
    [
        "../x.tex",
        "/etc/x.tex",
        r"C:\x.tex",
        "C:/x.tex",
        "a/../../b.tex",
        r"\\server\share\x.tex",
        r"chapters\..\..\x.tex",
        "main.sty",
        "main",
        "my paper.tex",
        "..",
    ],
)
def test_compile_request_rejects_unsafe_main_file(main_file):
    with pytest.raises(ValidationError):
        CompileRequest(latex="x", main_file=main_file)


def test_main_file_path_guard_rejects_escape(tmp_path):
    assert lc._main_file_path(tmp_path, "chapters/intro.tex") == (tmp_path / "chapters" / "intro.tex").resolve()
    for bad in ("../escape.tex", "a/../../escape.tex", "."):
        with pytest.raises(lc.UnsafeMainFileError):
            lc._main_file_path(tmp_path, bad)


def test_compile_impl_guards_unvalidated_main_file(monkeypatch, tmp_path):
    monkeypatch.setattr(lc, "find_tex_engine", lambda _compiler: "pdflatex")
    request = CompileRequest.model_construct(
        latex=r"\documentclass{article}\begin{document}x\end{document}",
        main_file="../../escape.tex",
        compiler="pdflatex",
        assets=[],
        cache_id=f"guard-{uuid.uuid4().hex}",
        mode="full",
    )
    with pytest.raises(lc.UnsafeMainFileError):
        lc.compile_latex(request)


def _fake_batchmode_passes(monkeypatch, tmp_path, tex_logs: list[str]) -> list[int]:
    """Fake TeX passes: stdout stays empty (batchmode); warnings only land in main.log."""
    calls: list[int] = []

    def fake_pass(_compiler, _engine, work_dir, main_file, **_kwargs):
        index = len(calls)
        calls.append(index)
        log = tex_logs[min(index, len(tex_logs) - 1)]
        (work_dir / f"{lc._jobname(main_file)}.log").write_text(log, encoding="utf-8")
        (work_dir / f"{lc._jobname(main_file)}.pdf").write_bytes(b"%PDF-1.5")
        return 0, ""

    monkeypatch.setattr(lc, "find_tex_engine", lambda _compiler: "pdflatex")
    monkeypatch.setattr(lc, "_run_tex_pass", fake_pass)
    return calls


_UNDEFINED_REFS_LOG = "LaTeX Warning: There were undefined references.\n"
_CLEAN_LOG = "Output written on main.pdf (1 page).\n"


def test_direct_compile_reruns_when_tex_log_reports_undefined_references(monkeypatch, tmp_path):
    calls = _fake_batchmode_passes(monkeypatch, tmp_path, [_UNDEFINED_REFS_LOG, _CLEAN_LOG])
    lc._direct_compile("pdflatex", tmp_path, "main.tex", passes=3)
    assert len(calls) == 2


def test_direct_compile_stops_after_clean_tex_log(monkeypatch, tmp_path):
    calls = _fake_batchmode_passes(monkeypatch, tmp_path, [_CLEAN_LOG])
    lc._direct_compile("pdflatex", tmp_path, "main.tex", passes=3)
    assert len(calls) == 1


def test_manual_compile_reruns_when_tex_log_reports_undefined_references(monkeypatch, tmp_path):
    calls = _fake_batchmode_passes(monkeypatch, tmp_path, [_UNDEFINED_REFS_LOG, _CLEAN_LOG])
    latex = "See [1] via cite{a}; thebibliography only, no bibtex run."
    lc._manual_compile("pdflatex", tmp_path, "main.tex", latex)
    assert len(calls) == 2


def test_pass_needs_rerun_reads_tex_log(tmp_path):
    assert lc._pass_needs_rerun("", tmp_path, "main") is False  # no .log yet
    (tmp_path / "main.log").write_text("Label(s) may have changed. Rerun to get cross-references right.")
    assert lc._pass_needs_rerun("", tmp_path, "main") is True
    assert lc._pass_needs_rerun("LaTeX Warning: There were undefined references.", tmp_path, "other") is True


def test_extract_cite_keys_covers_natbib_and_biblatex_forms():
    latex = r"\citep[see][p.~3]{a,b} \parencite{c} \textcite{d} \cite{e} \nocite{*} \citestyle{plain}"
    assert lc._extract_cite_keys(latex) == {"a", "b", "c", "d", "e"}


def test_ensure_bibliography_stubs_natbib_cite_keys(tmp_path):
    latex = r"\citep[p.~3]{smith2020} \bibliography{refs}"
    lc._ensure_bibliography(tmp_path, latex)
    assert "smith2020" in (tmp_path / "refs.bib").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["C:/Windows/win.ini", "c:evil.png", "fig.png:stream", "../up.png", ""])
def test_safe_asset_path_rejects_paths_outside_workspace(name):
    assert lc._safe_asset_path(name) is None


def test_safe_asset_path_keeps_nested_relative_names():
    assert lc._safe_asset_path("figures/plot 1.png") == Path("figures/plot 1.png")


def test_collect_all_tex_sources_ignores_inputs_outside_workspace(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "intro.tex").write_text("INSIDE", encoding="utf-8")
    outside = tmp_path / "secret.tex"
    outside.write_text("OUTSIDE", encoding="utf-8")
    latex = rf"\input{{intro}} \input{{{outside.as_posix()}}} \include{{../secret}}"
    merged = lc._collect_all_tex_sources(latex, work, "main.tex")
    assert "INSIDE" in merged
    assert "OUTSIDE" not in merged


# _get_cached_compile_workspace used to hand-build its own "proj:{id}" key instead of calling
# _workspace_cache_key. When the owner component was added to the latter, this lookup silently
# stopped matching any stored workspace — breaking SyncTeX's cached-workspace path without a
# single test failing, because test_synctex_inverse_uses_cached_workspace early-returns when
# pdflatex is absent (it is, in CI's unit job; only the TeX Live workflow would have caught it).
# These two tests need no TeX at all, so they fail everywhere the bug exists.
def test_cached_workspace_lookup_finds_what_acquire_workspace_stored():
    owner = "user:alice"
    acquired, _ = lc._acquire_workspace("proj-synctex", [], assets_key="k", owner_key=owner)
    found = lc._get_cached_compile_workspace("proj-synctex", owner_key=owner)
    assert found == acquired


def test_cached_workspace_lookup_is_scoped_to_the_owner():
    alice_dir, _ = lc._acquire_workspace("proj-synctex", [], assets_key="k", owner_key="user:alice")
    assert lc._get_cached_compile_workspace("proj-synctex", owner_key="user:bob") is None
    assert lc._get_cached_compile_workspace("proj-synctex", owner_key="user:alice") == alice_dir
