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
| `length.over_limit` | critical | Word count body > limit |
| `length.near_limit` | info | Trong khoảng 95–100% limit |

Word count **bỏ**: comment, preamble, `\bibliography`, math inline/display. **Tính**: caption
(phần lớn venue tính caption vào tổng). Vì mỗi venue đếm một kiểu, UI phải nói rõ con số này
là xấp xỉ, chỉ dùng để cảnh báo sớm — không phải con số venue sẽ đo.

## 4. Backend

### 4.1 Module

```
src/services/preflight/
    schemas.py       — pydantic: PreflightProfile, PreflightFinding, PreflightReport
    rules/
        crossref.py      — 3.1
        bibliography.py  — 3.2
        statements.py    — 3.3
        formatting.py    — 3.4
        anonymity.py     — 3.5
        length.py        — 3.6
    source.py        — chuẩn hoá source: tách comment, mask verbatim, map offset → line
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
    symbol: str = ""             # token vi phạm ("fig:pipeline") — để frontend nội suy vào copy
    count: int = 1               # số lần, cho luật kiểu large_negative_vspace
    line: int | None = None      # 1-based trong main document
    excerpt: str = ""            # ngữ cảnh ngắn để hiển thị


class PreflightReport(BaseModel):
    integrity_mode: str = "comment_only"
    findings: list[PreflightFinding] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)      # severity → số lượng
    skipped: list[str] = Field(default_factory=list)          # group không chạy vì chưa khai
    suppressed: list[str] = Field(default_factory=list)       # rule bị tắt do xung đột 3.5
```

Backend **không** trả prose cho người đọc. Nó trả `rule` + `symbol` + `count`; copy EN/VI nằm ở
`frontend/src/lib/preflight-i18n.ts` theo đúng convention "UI copy is bilingual via
`frontend/src/lib/*-i18n.ts`" trong CLAUDE.md. Khác với `ai_disclosure` — nơi prose EN/VI sinh ở
server vì output là **nội dung chèn vào bài**, không phải copy UI.

### 4.3 API

```
POST /api/v1/preflight
```

Theo đúng hình dạng `/citations/verify` (`routes.py:360`): nhận `session_id`, đọc
`session.latex_content` từ session store, access control bằng `assert_paper_session_access`.
Không nhận latex trong body — tránh payload lớn và không mở thêm bề mặt dữ liệu.

```python
class PreflightRequest(BaseModel):
    session_id: str
    bib_content: str = Field(default="", max_length=500_000)
    profile: PreflightProfile = Field(default_factory=PreflightProfile)
```

Route mới `src/api/preflight_routes.py`, dependency `get_agent_user_id` như `/citations/verify`.
Đồng bộ (không SSE): toàn bộ là regex trên document trong RAM, không có gì để stream.

## 5. Frontend

| File | Thay đổi |
|---|---|
| `features/editor/types.ts:36` | `ToolsTab` thêm `"preflight"` |
| `features/editor/components/ToolsPanel.tsx:159` | thêm `{ id: "preflight", label: t.tools.preflight }` vào tab list + một nhánh render ở `:263` |
| `features/editor/components/PreflightPanel.tsx` | **mới** — form khai profile + danh sách findings nhóm theo severity |
| `features/editor/state/useEditorPreflight.ts` | **mới** — state + gọi API, theo pattern `useEditorTools` |
| `lib/api/preflight.ts` | **mới** — client |
| `lib/preflight-i18n.ts` | **mới** — copy EN/VI cho từng rule id |
| `lib/editor-i18n.ts` | thêm `tools.preflight` label (cả `en` và `vi`) |
| `features/editor/components/MobileToolsSheet.tsx` | tab mới xuất hiện trên mobile |

Không có exhaustive switch nào trên `ToolsTab` nên thêm tab thứ 7 là thuần cộng thêm —
đã kiểm: chỉ `ToolsPanel.tsx` liệt kê tab, các chỗ khác chỉ `setToolsTab("…")`.

Click một finding → nhảy tới `line` trong editor, dùng lại đường jump-to-line mà
`jumpToLogicIssue`/`jumpToStructureSection` đang dùng.

Profile tự khai được persist theo paper (localStorage như các tuỳ chọn editor khác, **không**
thêm cột DB ở v1 — nếu sau này cần đồng bộ nhiều máy thì mới migrate).

## 6. Testing

Bộ luật deterministic nên test được gần như toàn phần, và đó là lý do chọn backend.

| Tầng | Test |
|---|---|
| Mỗi rule module | `tests/test_preflight/test_<group>.py` — bảng input LaTeX nhỏ → findings mong đợi. Mỗi rule có **cả** case dương và case âm (đặc biệt: comment `%` và `verbatim` phải **không** sinh finding) |
| `source.py` | offset → line đúng; comment/verbatim bị mask; `\%` escaped không bị coi là comment |
| `runner.py` | thứ tự findings, `counts`, `skipped` khi chưa khai profile, `suppressed` khi `double_blind` tắt funding |
| API | `tests/test_api/test_preflight.py` — auth bắt buộc, session không thuộc user → 403/404, payload quá cỡ, profile mặc định |
| Frontend | `preflight-i18n.test.ts` — **mọi** rule id trong catalogue có copy ở cả `en` và `vi` (bắt chước `template-formats-i18n.test.ts` đã có) |

Test i18n là mấu chốt: rule id sinh ở backend mà copy ở frontend, nên thiếu một bản dịch sẽ
hiện ra như một dòng rỗng trong panel — im lặng, không ai phát hiện. Test phải so **toàn bộ**
danh sách rule id với bảng copy, chứ không kiểm vài key mẫu.

Cơ chế cụ thể, không cần generator hay build step:

1. `src/services/preflight/catalogue.py` khai `PREFLIGHT_RULE_IDS: tuple[str, ...]` — một nguồn
   sự thật duy nhất cho mọi rule id.
2. `tests/test_preflight/test_runner.py` khẳng định mọi finding mà runner sinh ra đều có `rule`
   nằm trong `PREFLIGHT_RULE_IDS` (bắt rule mới quên đăng ký).
3. `tests/test_preflight/test_rule_catalogue_i18n.py` đọc `frontend/src/lib/preflight-i18n.ts`
   dưới dạng text và khẳng định mỗi id trong `PREFLIGHT_RULE_IDS` xuất hiện dưới **cả** `en` và
   `vi` (bắt thiếu bản dịch).

Test cross-language ở bước 3 hơi khác thường, nhưng nó đổi một build step lấy một lần đọc file
trong repo, và nó bắt đúng cái lỗi thật sự xảy ra. Nếu về sau rule id nhiều lên tới mức khó
quản thì mới cân nhắc sinh file TS từ catalogue.

## 7. Rủi ro & tương thích

Flow cũ bị chạm tới đâu:

| Vùng | Chạm | Rủi ro |
|---|---|---|
| Pipeline AI (chat/stream/guardrail L1–L4) | không | không |
| `quota_policy` | không — preflight không phải LLM path | không |
| Compile / SyncTeX | không | không |
| Session store | chỉ **đọc** `latex_content` | không |
| DB schema | không có migration | không |
| `ToolsTab` | thêm một giá trị union | thấp — không có switch exhaustive |
| `editor-i18n.ts` | thêm key | thấp |

Rủi ro thật nằm ở chất lượng luật, không ở tích hợp:

- **False positive ở `critical`** phá niềm tin vào toàn bộ panel. Giảm thiểu: `critical` chỉ cho
  luật tất định; mọi heuristic xuống `warning`/`info`; mỗi rule có test case âm.
- **Cảm giác an toàn sai** — panel sạch không có nghĩa là bài sẽ được nhận. Panel phải nói rõ:
  đây là kiểm cơ học, không thay CFP của venue.
- **`source.py` sai** sẽ làm sai *mọi* luật cùng lúc. Vì vậy nó là module được test dày nhất.

## 8. Để sau

Không thuộc v1, ghi lại để không mất:

- DOI resolve thật qua DataCite/CrossRef (cần network + cache; gắn với workstream Citation reformat)
- Page count thật từ compile output
- Reporting checklist theo chuẩn (CONSORT, PRISMA, ARRIVE)
- Quét PDF metadata tìm rò danh tính sau compile
- Preflight trong Export dialog, không chỉ panel Tools
- Đồng bộ profile qua DB thay cho localStorage

---

*Spec sống — cập nhật khi implement lệch khỏi thiết kế.*
