# Submission Preflight — Design

**Ngày:** 11/10/2026
**Trạng thái:** đề xuất, chờ review
**Tham chiếu:** [ARCHITECTURE.md](../../../ARCHITECTURE.md) · [ROADMAP.md](../../../ROADMAP.md)

---

## 1. Vấn đề

Nguyên nhân desk-reject phổ biến nhất không phải chất lượng khoa học mà là lỗi kỹ thuật cơ học
trước khi reviewer kịp đọc nội dung:

| Nguyên nhân | Hệ quả |
|---|---|
| Rò danh tính trong bài double-blind | Desk-reject thẳng (ICLR 2026 nêu rõ: main text hoặc supplementary) |
| Thiếu data availability / ethics approval / reporting checklist | ~20% desk reject ở journal diện rộng |
| Bóp `\linespread` < 1, sửa lề, nén vertical spacing | Auto desk-reject vì vi phạm format |
| Dùng style file của kỳ trước | Desk-reject |

Tất cả đều **phát hiện được bằng static analysis** — không cần LLM, không cần phán đoán khoa học.
Edico hiện không kiểm bất kỳ mục nào trong số đó.

Những gì đã có và **không** trùng với preflight:

- `citations/verifier.py` — xác thực bib entry **đã có** với arXiv/CrossRef/S2/OpenAlex
  (`verified`/`possible_mismatch`/`not_found`/`unverified`). Không bắt cite key thiếu trong `.bib`,
  entry không ai cite, hay entry trùng.
- `frontend/src/lib/paper-score.ts` — chấm điểm IMRaD + word count + phát hiện template placeholder.
  Là *điểm chất lượng*, không phải *checklist nộp bài*.
- `latex_compile.py:935` — chuỗi `"There were undefined references"` chỉ dùng để trigger rerun;
  không có dữ liệu structured nào về `\ref` nào bị thiếu.

## 2. Phạm vi

**Mục tiêu:** một panel trong editor liệt kê những lỗi cơ học sẽ khiến bài bị trả về, mỗi lỗi
chỉ được đúng chỗ trong source.

**Không làm (có chủ đích):**

- **Không có preset theo venue.** Profile cứng theo hội nghị sai hạn mỗi năm, và sai theo hướng
  tệ nhất — khiến tác giả tin là đã đạt. Luật generic luôn chạy; luật phụ thuộc venue
  (double-blind, giới hạn độ dài) chỉ bật khi tác giả **tự khai**.
- **Không gọi mạng.** "Thiếu DOI" nghĩa là *entry không có field `doi`*, không phải *DOI không
  resolve*. Giữ deterministic, nhanh, và không chạm `quota_policy` (không phải LLM path).
- **Không hứa số trang.** Page count cần compile thật; v1 chỉ đếm word.
- **Không gate gì.** `integrity_mode: "comment_only"` như `logic_audit`. Preflight không chặn
  export, không sửa document. Invariant #1 Human Supremacy giữ nguyên.
- **Không OCR, không đọc PDF metadata.** Chỉ phân tích LaTeX source + `.bib`.

## 3. Catalogue luật

Severity theo đúng vocabulary của `logic_audit/schemas.py`: `critical` / `warning` / `info`.

`critical` chỉ dành cho thứ **chắc chắn** sai và **chắc chắn** gây hậu quả. Mọi luật heuristic
nằm ở `warning` hoặc `info`. False positive ở `critical` phá niềm tin vào cả panel.

### 3.1 Cross-reference (`crossref.*`) — luôn chạy

| Rule id | Severity | Phát hiện | Ghi chú false-positive |
|---|---|---|---|
| `crossref.undefined_ref` | critical | `\ref`/`\eqref`/`\autoref`/`\cref` trỏ tới label không tồn tại | Phải bỏ qua phần trong comment `%` và trong `verbatim`/`lstlisting` |
| `crossref.float_without_label` | warning | `figure`/`table`/`algorithm` không có `\label` | Float trang trí không cần ref là hợp lệ → warning, không critical |
| `crossref.unused_label` | info | `\label` không ai `\ref` | Rất thường vô hại |
| `crossref.duplicate_label` | critical | Hai `\label` cùng tên | LaTeX tự warn nhưng chôn trong log |

### 3.2 BibTeX hygiene (`bib.*`) — luôn chạy

| Rule id | Severity | Phát hiện | Ghi chú |
|---|---|---|---|
| `bib.cite_key_missing` | critical | `\cite{k}` mà `k` không có trong bib | Dùng `extract_cite_keys` + `parse_bib_entries` có sẵn |
| `bib.duplicate_entry` | warning | Hai entry cùng DOI, hoặc title chuẩn hoá giống nhau | Title match dùng `citations/title_match.py` (rapidfuzz) đã có |
| `bib.missing_required_field` | warning | `@article` thiếu `journal`/`year`, `@inproceedings` thiếu `booktitle`/`year`, v.v. | Bảng field bắt buộc theo entry type |
| `bib.missing_doi` | info | Entry không có `doi` lẫn `eprint` | Nhiều entry hợp lệ vốn không có DOI → info |
| `bib.uncited_entry` | info | Entry trong bib không ai cite | Vô hại nhưng làm reference list phình |

### 3.3 Required statements (`statement.*`) — luôn chạy, mỗi mục bật/tắt được

| Rule id | Severity | Mục |
|---|---|---|
| `statement.data_availability_missing` | warning | Data availability |
| `statement.ethics_missing` | warning | Ethics approval / IRB |
| `statement.coi_missing` | warning | Conflict of interest / competing interests |
| `statement.funding_missing` | warning | Funding |
| `statement.author_contributions_missing` | info | Author contributions |

Phát hiện bằng heading regex (`\section{Data Availability}`) **hoặc** cụm từ trong body
("data supporting the findings", "available upon request", …), cả EN và VI. Mặc định bật
`data_availability`, `ethics`, `coi`, `funding`; `author_contributions` tắt vì nhiều venue
không yêu cầu.

### 3.4 Formatting manipulation (`format.*`) — luôn chạy

| Rule id | Severity | Phát hiện |
|---|---|---|
| `format.compressed_leading` | critical | `\linespread{x}`/`\baselinestretch{x}`/`\setstretch{x}` với x < 1 |
| `format.margin_override` | warning | `\geometry{…}` hoặc `\usepackage[margin=…]{geometry}` khi document class là class của venue |
| `format.large_negative_vspace` | warning | `\vspace{-…}` ≥ 1em, báo kèm số lần xuất hiện |
| `format.font_size_override` | warning | `\fontsize` trong body |

`format.margin_override` là luật dễ false-positive nhất: với `article` thường thì đổi lề là
hoàn toàn bình thường. Chỉ báo khi documentclass **không** phải `article`/`report`/`book`
(tức là đang dùng class do venue cấp, nơi lề đã bị quy định).

### 3.5 Anonymity (`anon.*`) — chỉ khi khai `double_blind: true`

| Rule id | Severity | Phát hiện |
|---|---|---|
| `anon.author_populated` | critical | `\author{…}` có nội dung không phải placeholder (`Anonymous`, `Anonymous Authors`, rỗng) |
| `anon.affiliation_populated` | critical | `\institute`/`\affiliation`/`\affil` có nội dung |
| `anon.email_present` | critical | Regex email trong preamble hoặc body |
| `anon.orcid_present` | warning | `\orcid{…}` hoặc URL orcid.org |
| `anon.thanks_present` | warning | `\thanks{…}` |
| `anon.acknowledgements_present` | warning | Section acknowledgement/acknowledgment/lời cảm ơn |
| `anon.funding_identifiers` | warning | Số hiệu grant (regex kiểu `NSF-1234567`, `No. 12345`) |
| `anon.self_reference` | info | Cụm "our previous work", "in our earlier paper", "nghiên cứu trước của chúng tôi" |
| `anon.repository_link` | info | URL github.com/gitlab.com có tên user |

Nghịch lý đáng chú ý: `anon.acknowledgements_present` và `statement.funding_missing` xung đột
nhau khi bật double-blind — venue muốn có funding statement ở bản camera-ready nhưng không ở
bản nộp. Xử lý: khi `double_blind: true` thì **tắt** `statement.funding_missing` và
`statement.author_contributions_missing`, và nêu lý do trong report (`suppressed` field) để
tác giả không tưởng là bỏ sót.

### 3.6 Length (`length.*`) — chỉ khi khai `word_limit`

| Rule id | Severity | Phát hiện |
|---|---|---|
| `length.over_limit` | warning | Word count body > limit |
| `length.near_limit` | info | Trong khoảng 95–100% limit |

`length.over_limit` là **warning**, không phải critical (sửa ở final whole-branch review,
Ruling 29): bảng này bản đầu ghi critical nhưng mâu thuẫn với chính đoạn prose ngay dưới — con số
là *xấp xỉ* — và §3 đã ra nguyên tắc quyết định: luật heuristic không được ở `critical`. Đo thực
tế: 320 từ prose thật + một `eqnarray` + ba bảng kết quả đếm ra 428 so với limit 400, tức critical
trên bài đang dưới limit 20%. Một hàng critical mà ngay bên dưới hiển thị "con số này chỉ là ước
tính" là copy tự mâu thuẫn.

Word count **bỏ**: comment, preamble, `\bibliography`, math inline/display (đủ cả bộ environment
display math — `equation`, `eqnarray`, `align`, `alignat`, `flalign`, `gather`, `multline`,
`IEEEeqnarray`, kèm dạng có dấu sao, cùng `subequations`/`displaymath`/`math`). **Tính**: caption
(phần lớn venue tính caption vào tổng), và cả nội dung `tabular` — đây là văn bản mà venue có thể
đếm, nên không strip. Vì mỗi venue đếm một kiểu, UI phải nói rõ con số này là xấp xỉ, chỉ dùng để
cảnh báo sớm — không phải con số venue sẽ đo.

## 4. Backend

### 4.1 Module

```
src/models/preflight_schemas.py  — pydantic request/response (convention: mọi response_model
                                   của repo nằm ở src/models/, không ở src/services/)
src/services/preflight/
    catalogue.py     — PREFLIGHT_RULE_IDS: nguồn sự thật duy nhất cho rule id
    rules/
        crossref.py      — 3.1
        bibliography.py  — 3.2
        statements.py    — 3.3
        formatting.py    — 3.4
        anonymity.py     — 3.5
        length.py        — 3.6
    source.py        — chuẩn hoá source: tách comment, mask verbatim, resolve \input/\include,
                       map offset → (file, line)
    runner.py        — chạy các nhóm luật, gom findings, áp quy tắc suppress của 3.5
```

Mỗi rule module là **hàm thuần** `(doc: PreflightSource, profile: PreflightProfile) -> list[PreflightFinding]`.
Không I/O, không state, không LLM → test bằng pytest trực tiếp, không cần fixture DB.

`source.py` là nơi duy nhất biết cách bóc comment và mask `verbatim`/`lstlisting`. Mọi luật
đọc source đã chuẩn hoá, nên không luật nào tự regex trên raw text và tự sinh một lớp
false-positive riêng. Nó cũng giữ bảng offset → `line` để finding chỉ được đúng dòng.

Tái dùng, không viết lại: `parse_latex_sections`, `extract_cite_keys`, `extract_bib_content`,
`parse_bib_entries` (`services/parser/latex.py`); `normalize_title` (`citations/title_match.py`);
`LatexNodes2Text` (pylatexenc) cho word count.

### 4.2 Schema

```python
PreflightSeverity = Literal["critical", "warning", "info"]
PreflightGroup = Literal["crossref", "bib", "statement", "format", "anon", "length"]
RequiredStatement = Literal[
    "data_availability", "ethics", "coi", "funding", "author_contributions"
]


class PreflightProfile(BaseModel):
    double_blind: bool = False
    word_limit: int | None = Field(default=None, ge=1, le=100_000)
    required_statements: list[RequiredStatement] = Field(
        default_factory=lambda: ["data_availability", "ethics", "coi", "funding"]
    )


class PreflightFinding(BaseModel):
    id: str                      # "crossref.undefined_ref:0" — stable trong một report
    rule: str                    # "crossref.undefined_ref"
    group: PreflightGroup
    severity: PreflightSeverity
    file: str = ""               # path của file chứa lỗi (multi-file)
    line: int | None = None      # 1-based TRONG FILE đó
    symbol: str = ""             # token vi phạm ("fig:pipeline") — frontend nội suy vào copy
    count: int = 1               # số lần, cho luật kiểu large_negative_vspace
    excerpt: str = ""            # ngữ cảnh ngắn để hiển thị


class PreflightReport(BaseModel):
    integrity_mode: str = "comment_only"
    findings: list[PreflightFinding] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)      # severity → số lượng
    skipped: list[str] = Field(default_factory=list)          # group không chạy vì chưa khai
    suppressed: list[str] = Field(default_factory=list)       # rule bị tắt do xung đột 3.5
    unresolved_includes: list[str] = Field(default_factory=list)  # \input không có trong payload
```

`file` + `line` thay vì chỉ `line`: bắt buộc, xem 4.3. `line` là 1-based và tính theo cùng
phép tách `\r?\n` mà frontend dùng (`latex-outline.ts:8` `lineAtOffset` trả `split(/\r?\n/).length`,
không bao giờ trả 0) — lệch quy ước này thì mọi cú jump lệch một dòng.

Backend **không** trả prose cho người đọc. Nó trả `rule` + `symbol` + `count`; copy EN/VI nằm ở
`frontend/src/lib/preflight-i18n.ts` theo convention "UI copy is bilingual via
`frontend/src/lib/*-i18n.ts`" trong CLAUDE.md. Khác với `ai_disclosure` — nơi prose EN/VI sinh ở
server vì output là **nội dung chèn vào bài**, không phải copy UI.

Pydantic model đặt ở `src/models/preflight_schemas.py`, không ở `src/services/preflight/`: mọi
`response_model` hiện có của repo (`schemas.py`, `citation_schemas.py`, `ai_disclosure_schemas.py`,
`peer_review_schemas.py`) đều nằm dưới `src/models/`. Tầng `services/preflight/rules/*` trả
dataclass thuần, runner mới dựng Pydantic — giữ `services/parser/latex.py` style: pure, no Pydantic.

### 4.3 API — vì sao nhận payload nhiều file

Dự định ban đầu là đọc `session.latex_content` như `/citations/verify`. **Không dùng được**, hai lý do
đều xác nhận bằng đọc code:

1. `latex_content` chỉ là **file main**. Frontend gửi `sentMainLatex` (`useEditorChat.ts:964-977`),
   và `PaperSession` (`sessions.py:25-28`) chỉ có một field `latex_content: str`. Với project
   multi-file — tính năng đầu bảng của Edico — mọi `\label` trong `sections/*.tex` sẽ vô hình,
   nên `crossref.undefined_ref` bắn critical cho gần như mọi cross-reference.
2. **Bib không nằm trong session.** `PaperSession` không có field bib, bảng `papers` không có cột
   bib. `.bib` nằm ở `metadata["assets"]` dưới dạng base64 data URL
   (`template_store.py:271-276`), còn `metadata["files"]` chỉ chứa `.tex`/`.latex` plaintext.
   Và `extract_bib_content(latex, "")` fallback về thân `\begin{thebibliography}` — là `\bibitem`,
   không phải BibTeX, nên `parse_bib_entries` trả `{}`.

Nên request mang nội dung, giống cách `/compile` nhận `assets`:

```python
class PreflightFile(BaseModel):
    path: str = Field(..., min_length=1, max_length=512)
    content: str = Field(default="", max_length=500_000)


class PreflightRequest(BaseModel):
    main_file: str = Field(default="main.tex", max_length=512)   # validate_main_file_path
    files: list[PreflightFile] = Field(default_factory=list, max_length=64)
    bib_content: str = Field(default="", max_length=500_000)
    profile: PreflightProfile = Field(default_factory=PreflightProfile)
```

```
POST /api/v1/preflight/run     router = APIRouter(prefix="/preflight", tags=["preflight"])
```

Auth: `user: User = Depends(get_current_user)` — **chỉ authentication**, không có resource nào
để authorize vì nội dung nằm trong body. Cố ý tránh `assert_paper_session_access`: nó no-op khi
`db_is_ready()` False (`agent_deps.py:31-32`), bỏ qua ownership khi `session_id` falsy
(`:35-36`), và là hàm sync blocking gọi trong handler async. Hệ quả phải chấp nhận:
`get_current_user` cần DB nên preflight 503 khi DB sập — nhất quán với phần còn lại của repo.

Không chạm session store, không ghi gì, không `enforce_llm_quota_for_paper` (nó tiêu cả budget
rate-limit mỗi phút — `quota_policy.py:119` — nên gọi nó sẽ khiến một check tĩnh miễn phí đốt
quota LLM của người dùng). Thuần hàm: `def run_preflight(req) -> PreflightReport`, `def` sync.

`\input`/`\include` được resolve trong `source.py` theo `files` của payload. File được `\input`
mà không có trong payload đi vào `unresolved_includes`, và khi danh sách đó không rỗng thì
`crossref.undefined_ref` + `bib.uncited_entry` bị **suppress** — thà im lặng còn hơn bắn critical
dựa trên dữ liệu thiếu.

### 4.4 Cite key: vì sao không dùng trực tiếp `extract_cite_keys`

`CITE_RE` (`parser/latex.py:15`) có hai tính chất khiến dùng thẳng sẽ sinh false positive:

- Nó **không bỏ comment**. Không chỗ nào trong `parser/latex.py` strip comment hay mask
  `verbatim`/`lstlisting`. Một `\cite` bị comment-out sẽ bị tính là "đã cite".
- Literal `cite` trong `[A-Za-z]*cite[A-Za-z]*` là chữ thường, nên natbib dạng hoa
  `\Citep{…}`, `\Citet{…}`, `\Cite{…}` **không match**. Entry chỉ được cite bằng `\Citep` sẽ bị
  báo `bib.uncited_entry` oan.

Cách xử lý: preflight gọi `extract_cite_keys(masked_source)` — tái dùng regex nhưng truyền source
đã mask, nên vấn đề comment biến mất — **cộng** một regex riêng cho biến thể viết hoa. Cố ý
**không** sửa `CITE_RE`: làm nó case-insensitive sẽ đổi hành vi của citation verification đang
chạy, tức là chạm flow cũ. Ghi vào §8 để xử lý riêng.

## 5. Frontend

| File | Thay đổi |
|---|---|
| `features/editor/types.ts:36` | `ToolsTab` thêm `\| "preflight"` |
| `features/editor/components/ToolsPanel.tsx` | thêm entry vào tab list (154-163, **phải có `as const` từng phần tử**) + nhánh render **trước** fallback dòng 340 |
| `features/editor/components/PreflightPanel.tsx` | **mới** — form khai profile + findings nhóm theo severity |
| `features/editor/state/useEditorPreflight.ts` | **mới** — state + gọi API |
| `lib/api/preflight-api.ts` | **mới** — client (convention `-api.ts`) |
| `lib/preflight-i18n.ts` | **mới** — copy EN/VI keyed theo rule id |
| `lib/editor-i18n.ts` | thêm `tools.preflight`: type key (73-124) + EN (384-437) + VI (723-775) |
| `features/editor/components/MobileToolsSheet.tsx` | **ba** chỗ cho mỗi prop mới: destructure, type literal, forward list |

Bốn cái bẫy recon tìm ra, phải xử lý tường minh:

- **Fallback render Versions.** `ToolsPanel.tsx:340` là `) : (` trần, không có nhánh
  `tab === "versions"`. Thêm `"preflight"` vào union mà quên nhánh thì panel render lịch sử
  revision và TypeScript **không** báo lỗi. Nhánh preflight phải đặt trước fallback.
- **Tab bị giật.** Hai `useEffect` ở `:99-103` và `:105-109` gọi `setTab("logic")` /
  `setTab("structure")` mỗi lần prop đó đổi identity. User đang đọc Preflight mà một logic audit
  xong sẽ bị kéo đi. Không sửa hai effect đó (chạm flow cũ) — nhưng cũng **không** thêm effect
  auto-switch thứ ba cho preflight.
- **`as const` kép.** Tab list dùng `id: "info" as const` trên từng phần tử *và* `] as const` ở
  cuối (156-162). Bỏ `as const` ở entry mới làm `item.id` rộng thành `string` và vỡ `npm run typecheck`.
- **MobileToolsSheet không spread.** Nó liệt kê ~30 prop ba lần. Quên block forward thì prop
  compile sạch nhưng im lặng không bao giờ tới panel trên mobile.

Jump: `jumpToOutlineLine(line)` (`useLatexWorkspace.ts:299`) nhận line 1-based, nhưng nó tính
theo `mainLatexSource` còn editor render file đang active — nên phải `switchActiveFile(finding.file)`
trước, đúng như `jumpToLogicIssue` làm (`useEditorTools.ts:343`). `scrollToLineInternal` chỉ chặn
`line < 1` (`latex-code-editor.tsx:260`), **không** clamp quá EOF, nên line từ backend phải được
validate lại với số dòng thật của file trước khi tin.

Không copy predicate `canJumpToPreflightFinding`: Logic Audit cần `canJumpToIssue` vì nó resolve
bằng tìm text có thể thất bại; preflight có line thật nên chỉ cần kiểm `1 <= line <= lineCount`.

Profile tự khai persist bằng localStorage theo paper (**không** thêm cột DB ở v1).

## 6. Testing

| Tầng | Test |
|---|---|
| Mỗi rule module | `tests/test_preflight/test_<group>.py` — bảng input LaTeX nhỏ → findings mong đợi. Mỗi rule có **cả** case dương và case âm (đặc biệt: comment `%` và `verbatim` phải **không** sinh finding) |
| `source.py` | offset → (file, line) đúng; comment/verbatim bị mask; `\%` escaped không bị coi là comment; `\input` resolve; `\input` thiếu → `unresolved_includes` |
| `runner.py` | thứ tự findings, `counts`, `skipped`, `suppressed` khi `double_blind`, suppress khi có `unresolved_includes` |
| API | `tests/test_preflight/test_api.py` — payload quá cỡ, `main_file` không hợp lệ, profile mặc định |
| Frontend | `lib/preflight-i18n.test.ts` — copy đủ cho mọi rule id ở cả hai locale |

`tests/test_preflight/` cần `__init__.py` (mọi thư mục test hiện có đều có) và **không** cần
`conftest.py` — fixture `client` ở `tests/conftest.py:19-24` được kế thừa toàn bộ cây.
pytest-asyncio chạy **STRICT mode không có file config nào** (repo không có `pytest.ini`,
`pyproject.toml`, `setup.cfg`, `tox.ini`), nên mọi async test phải có `@pytest.mark.asyncio`
tường minh — thiếu nó là test bị **skip im lặng**. Test rule thuần là `def` thường, không marker.

Một cảnh báo về test auth: `tests/conftest.py` xoá `DATABASE_URL` trước khi import app, nên trong
suite mặc định `db_is_ready()` là False và không có gì được authenticate. Một test "chứng minh"
preflight chặn người lạ sẽ **không chứng minh được gì** ở đó; nếu cần thì phải đặt dưới
`tests/test_db/`.

### 6.1 Parity EN/VI: để TypeScript lo, không phải test đọc file

Spec bản đầu định cho pytest đọc `preflight-i18n.ts` dưới dạng text. Recon cho thấy có cách
mạnh hơn, và cho thấy tiền đề ban đầu sai: `template-formats-i18n.test.ts` **không** có
assertion "đủ hai locale" (nó hardcode từng literal mong đợi), và **không test vitest nào trong
repo đọc file từ disk** (`environment: "node"`, `include: ["src/**/*.test.ts"]`).

Cơ chế thay thế:

1. `src/services/preflight/catalogue.py` khai `PREFLIGHT_RULE_IDS: tuple[str, ...]` — nguồn sự
   thật phía backend.
2. `lib/api/preflight-api.ts` khai `export type PreflightRuleId = "crossref.undefined_ref" | …`
   — union TS mirror danh sách đó.
3. `lib/preflight-i18n.ts` key copy bằng `Record<PreflightRuleId, PreflightRuleCopy>` cho **cả**
   `en` và `vi`, theo shape `Record<UiLanguage, …>` của `peer-review-i18n.ts`. Thiếu một rule ở
   một locale thành **lỗi `npm run typecheck`** — CI đã gate ở 0 error.
4. `tests/test_preflight/test_catalogue_parity.py` đọc `preflight-api.ts` dưới dạng text và
   khẳng định union TS khớp đúng `PREFLIGHT_RULE_IDS`. Đây là chỗ duy nhất cần đọc file, và nó
   bắt đúng một thứ: backend thêm rule mà frontend chưa biết.

Khác biệt đáng giá: parity hai locale do compiler bảo đảm (không thể quên), còn drift
backend↔frontend do một test bắt. Bản spec đầu để cả hai phụ thuộc vào một test đọc text.

## 7. Rủi ro & tương thích

Flow cũ bị chạm tới đâu:

| Vùng | Chạm | Rủi ro |
|---|---|---|
| Pipeline AI (chat/stream/guardrail L1–L4) | không | không |
| `quota_policy` | không — preflight không phải LLM path | không |
| Compile / SyncTeX | không | không |
| Session store | không — nội dung đến từ request body | không |
| `parser/latex.py` (kể cả `CITE_RE`) | không — chỉ gọi, không sửa | không |
| DB schema | không có migration | không |
| `ToolsTab` | thêm một giá trị union | thấp, nhưng xem bẫy fallback ở §5 |
| `editor-i18n.ts` | thêm key | thấp — thiếu locale là lỗi compile |
| `main.py` | một import + một `include_router` | thấp — import block alphabetical (ruff "I"), thứ tự mount thì không |

Rủi ro thật nằm ở chất lượng luật, không ở tích hợp:

- **False positive ở `critical`** phá niềm tin vào toàn bộ panel. Giảm thiểu: `critical` chỉ cho
  luật tất định; mọi heuristic xuống `warning`/`info`; mỗi rule có test case âm.
- **Cảm giác an toàn sai** — panel sạch không có nghĩa là bài sẽ được nhận. Panel phải nói rõ:
  đây là kiểm cơ học, không thay CFP của venue.
- **`source.py` sai** sẽ làm sai *mọi* luật cùng lúc. Vì vậy nó là module được test dày nhất.
- **Document mới từ template** có đầy `% TODO` placeholder và chưa có bib, nên preflight sẽ bắn
  một tràng finding vào bài vừa tạo. Panel cần trạng thái "bản thảo còn là khung" trước khi liệt
  kê — tín hiệu đã có sẵn ở `paper-score.ts` (`assessManuscriptMaturity`, `isPlaceholderTemplate`).

## 8. Để sau

Không thuộc v1, ghi lại để không mất:

- DOI resolve thật qua DataCite/CrossRef (cần network + cache; gắn với workstream Citation reformat)
- Page count thật từ compile output
- Reporting checklist theo chuẩn (CONSORT, PRISMA, ARRIVE)
- Quét PDF metadata tìm rò danh tính sau compile
- Preflight trong Export dialog, không chỉ panel Tools
- Đồng bộ profile qua DB thay cho localStorage
- `CITE_RE` không match natbib viết hoa (`\Citep`, `\Citet`, `\Cite`) — sửa riêng, có test
  cho citation verification, vì nó đổi hành vi flow đang chạy (xem §4.4)
- `parse_latex_sections` để section cuối ăn luôn `\end{document}` và khối bibliography
  (`parser/latex.py:77-82`); `SECTION_RE` dùng `[^}]*` nên title có brace bị cắt
  (`\section{The \textbf{Big} Idea}` → `The \textbf{Big`)
- `STANDARD_SECTIONS` khai hai lần trùng nội dung (`parser/latex.py:22` và `:175`), bản đầu là
  dead binding và không có consumer nào

---

*Spec sống — cập nhật khi implement lệch khỏi thiết kế.*
