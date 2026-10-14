import type { PreflightRuleId, PreflightSeverity } from "@/lib/api/preflight-api";
import type { UiLanguage } from "@/lib/locale-store";
import type { PreflightSuppressionReason } from "@/lib/preflight-panel";

export type PreflightRuleCopy = { title: string; hint: string };

// Mirrors `PreflightGroup` / `RequiredStatement` in src/models/preflight_schemas.py — small, fixed
// literal unions, kept local (not imported from preflight-api.ts, which only mirrors rule ids) so
// group/statement labels have somewhere typed to live.
export type PreflightGroupId = "crossref" | "bib" | "statement" | "format" | "anon" | "length";
export type RequiredStatementId =
  "data_availability" | "ethics" | "coi" | "funding" | "author_contributions";

export type PreflightCopy = {
  tab: string;
  run: string;
  running: string;
  // Shown only before the first run of a session — must never be confused with `clean` (an
  // actual clean result). Nothing has been checked yet, so nothing can be said to be fine.
  beforeRun: string;
  // A clean report: no findings. Spec requirement, not a nicety — must read as a mechanical
  // check, never as a guarantee the venue will accept the paper.
  clean: string;
  // The word count is an estimate; every venue counts differently. Must never imply the number
  // shown is what the venue will actually measure.
  approximate: string;
  goToLine: string;
  severity: Record<PreflightSeverity, string>;
  // A group skipped because it was never declared for this run (anon without double-blind,
  // length without a word limit) — must never read as "this group passed". Generic fallback;
  // `skippedReason` below gives the specific "why" for the two groups that can actually skip.
  skippedGroup: string;
  // Short section heading above the skipped-group list (rendered as an uppercase micro-heading,
  // so it must stay short — the sentence-length copy belongs in `skippedGroup`/`skippedReason`,
  // not here, or it would read as a sentence shouting in small caps).
  skippedGroupHeading: string;
  // Short section heading above the suppressed-rule list — see `skippedGroupHeading`'s note on
  // why this must stay short rather than being a full sentence.
  suppressedRuleHeading: string;
  // Why a specific suppressed rule was turned off, one full sentence per
  // `PreflightSuppressionReason` (mirrors runner.py's suppression sets exactly — see
  // `preflightSuppressionReason` and `preflightCrossFileCauses` in preflight-panel.ts). Each
  // reason gets its own sentence so a reader is never left to guess between candidate causes at
  // once — including the two cross-file causes, which suppress the identical rule ids but are NOT
  // the same event: `unresolved_includes` is a file that is missing, `unexamined_files` is a file
  // that is right there and was never read.
  suppressedReason: Record<PreflightSuppressionReason, string>;
  // report.no_content: the draft is still empty or a bare template, so every group was skipped
  // for that reason rather than because it was not declared. Distinct message on purpose — see
  // the module docstring in src/services/preflight/runner.py's "no-content path".
  noContent: string;
  // design §7 / spec's "Để sau" risk: a fresh-from-template draft is almost entirely placeholder
  // text, so a plain run would bury the author under findings about a document they have not
  // written yet. Shown instead of (not in place of the ability to run) the findings list.
  placeholderTemplate: string;
  profile: {
    title: string;
    doubleBlindLabel: string;
    doubleBlindHint: string;
    wordLimitLabel: string;
    wordLimitHint: string;
    statementsLabel: string;
    statementsHint: string;
  };
  requiredStatementLabel: Record<RequiredStatementId, string>;
  groupLabel: Record<PreflightGroupId, string>;
  // Only "anon" and "length" are ever conditionally skipped (spec §3.5/§3.6); every other group
  // always runs, so this record deliberately has no entries for them.
  skippedReason: Record<"anon" | "length", string>;
  rules: Record<PreflightRuleId, PreflightRuleCopy>;
};

const COPY: Record<UiLanguage, PreflightCopy> = {
  en: {
    tab: "Preflight",
    run: "Run preflight check",
    running: "Running preflight check…",
    beforeRun: "Nothing checked yet — declare your submission profile above, then run the check.",
    clean:
      "No issues found. This is a mechanical check, not a guarantee of acceptance — always read your venue's call for papers too.",
    approximate:
      "This word count is only an estimate — every venue counts words differently, so it may not match the number your venue's own system reports.",
    goToLine: "Go to line",
    severity: {
      critical: "Critical",
      warning: "Warning",
      info: "Info",
    },
    skippedGroup: "Not checked — this group wasn't enabled for this submission.",
    skippedGroupHeading: "Not checked",
    suppressedRuleHeading: "Suppressed rules",
    suppressedReason: {
      unresolved_includes:
        "Turned off for this report — it depends on a \\input file that could not be found, so the result would not be reliable. Add the file to the project, or delete the \\input line asking for it, then run the check again.",
      unexamined_files:
        "Turned off for this report — your project has a .tex file that the main file never pulls in with \\input or \\include, so nothing read its labels or citations and the result would not be reliable. Either \\input it from the main file, or delete it if it is left over, then run the check again.",
      double_blind_conflict:
        "Turned off for this report — your venue wants this statement in the camera-ready version, not in a blinded submission, so requiring it here would be contradictory advice.",
    },
    noContent:
      "Nothing to check yet. The draft is still empty or just the template — every check was skipped for that reason, not because it was turned off.",
    placeholderTemplate:
      "This draft still reads like an unfinished template — mostly placeholder text and TODOs, not written content yet. You can still run the check, but most findings would just point back at things you haven't written. Consider filling in the draft first.",
    profile: {
      title: "Submission profile",
      doubleBlindLabel: "Double-blind submission",
      doubleBlindHint:
        "Turn this on if your venue requires an anonymous submission — it enables checks for author names, emails, affiliations, and other identity leaks.",
      wordLimitLabel: "Word limit (optional)",
      wordLimitHint:
        "Enter your venue's word limit to flag an estimated overrun. Leave blank to skip the length check.",
      statementsLabel: "Required statements",
      statementsHint:
        "Choose which statements your venue requires, so only those are flagged when missing.",
    },
    requiredStatementLabel: {
      data_availability: "Data availability",
      ethics: "Ethics / IRB approval",
      coi: "Conflict of interest",
      funding: "Funding",
      author_contributions: "Author contributions",
    },
    groupLabel: {
      crossref: "Cross-references",
      bib: "Bibliography",
      statement: "Required statements",
      format: "Formatting",
      anon: "Anonymity",
      length: "Length",
    },
    skippedReason: {
      anon: "Not checked — declare this as a double-blind submission above to enable identity-leak checks.",
      length: "Not checked — enter a word limit above to enable the length check.",
    },
    rules: {
      "crossref.undefined_ref": {
        title: "Undefined reference",
        hint: 'A \\ref, \\eqref, or similar points to a label that is never defined anywhere in the source. Readers (and LaTeX) will see "??" where this should resolve.',
      },
      "crossref.float_without_label": {
        title: "Figure or table missing a label",
        hint: "This figure or table environment has no \\label, so it cannot be cross-referenced from the text with \\ref.",
      },
      "crossref.unused_label": {
        title: "Label never referenced",
        hint: "This label is defined but no \\ref in the document points to it — likely harmless, but worth a check.",
      },
      "crossref.duplicate_label": {
        title: "Duplicate label",
        hint: "The same label is defined more than once. Every \\ref to it will resolve to whichever definition LaTeX saw last, silently pointing at the wrong figure, table, or equation.",
      },
      "bib.cite_key_missing": {
        title: "Citation key not in the bibliography",
        hint: 'A \\cite points to a key that does not exist in your .bib file. This reference will render as "?" and the paper may be flagged for a broken citation.',
      },
      "bib.duplicate_entry": {
        title: "Duplicate bibliography entry",
        hint: "This citation key is defined more than once in the bibliography. BibTeX will silently keep only one version, which may not be the one you meant to cite.",
      },
      "bib.missing_required_field": {
        title: "Bibliography entry missing a required field",
        hint: "This entry's type requires a field (such as journal, year, or booktitle) that is not set. Many venues reject references with incomplete metadata.",
      },
      "bib.missing_doi": {
        title: "Reference has no DOI",
        hint: "This entry has no doi field. Many venues now expect one where it exists — add it if the source has one.",
      },
      "bib.uncited_entry": {
        title: "Bibliography entry never cited",
        hint: "This entry is in your bibliography but no \\cite in the manuscript uses it. Remove it or cite it.",
      },
      "statement.data_availability_missing": {
        title: "Data availability statement missing",
        hint: "No data availability statement was found. Most venues now require one explaining where the underlying data can be accessed.",
      },
      "statement.ethics_missing": {
        title: "Ethics statement missing",
        hint: "No ethics declaration was found (e.g. IRB approval, informed consent, animal welfare). Check your venue's requirements before submitting.",
      },
      "statement.coi_missing": {
        title: "Conflict-of-interest statement missing",
        hint: "No conflict-of-interest (competing interests) statement was found. Most venues require one even when there is nothing to disclose.",
      },
      "statement.funding_missing": {
        title: "Funding statement missing",
        hint: "No funding or financial support statement was found. Add one if this work received any funding.",
      },
      "statement.author_contributions_missing": {
        title: "Author contributions statement missing",
        hint: "No author contributions statement was found. Many journals require one describing each author's role (e.g. the CRediT taxonomy).",
      },
      "format.compressed_leading": {
        title: "Line spacing compressed below normal",
        hint: "The source overrides line spacing to something tighter than the template default — a common way to sneak extra content past a page limit. Reviewers and editors check for this, and some venues treat it as a formatting violation.",
      },
      "format.margin_override": {
        title: "Page margins overridden",
        hint: "The source changes the page margins away from the template's defaults — often used to fit more text per page. Check this is allowed by your venue.",
      },
      "format.large_negative_vspace": {
        title: "Large negative vertical space",
        hint: "A large negative \\vspace pulls content upward, shrinking a gap the template normally leaves — another common way to squeeze in extra content.",
      },
      "format.font_size_override": {
        title: "Font size overridden",
        hint: "The source sets a font size smaller than the template's default — another way text can be squeezed past a page or word limit.",
      },
      "anon.author_populated": {
        title: "Author names are visible",
        hint: "The \\author command still contains names. A double-blind submission must not reveal author identity.",
      },
      "anon.affiliation_populated": {
        title: "Author affiliation is visible",
        hint: "An institutional affiliation is still present in the source. This can identify the authors even when names are removed.",
      },
      "anon.email_present": {
        title: "Email address found",
        hint: "An email address appears in the source. Emails almost always identify an author or their institution — remove it for double-blind review.",
      },
      "anon.orcid_present": {
        title: "ORCID identifier found",
        hint: "An ORCID iD is present. It links directly to a named researcher profile and should be removed for double-blind review.",
      },
      "anon.thanks_present": {
        title: "Author footnote (\\thanks) found",
        hint: "A \\thanks footnote is present — these commonly carry funding or contact details tied to a specific author and can break anonymity.",
      },
      "anon.acknowledgements_present": {
        title: "Acknowledgements section found",
        hint: "An acknowledgements section is present. It often names people, labs, or grants that can identify the authors — save it for the camera-ready version.",
      },
      "anon.funding_identifiers": {
        title: "Funding or grant identifier found",
        hint: "A grant number or funder name appears in the text. These can be looked up and traced back to the authors' lab.",
      },
      "anon.self_reference": {
        title: "Possible self-identifying reference",
        hint: 'A phrase like "our previous work" next to a citation can point reviewers straight to the authors — consider rephrasing in the third person for review.',
      },
      "anon.repository_link": {
        title: "Non-anonymous repository link",
        hint: "A code or data link points to a repository under a named account or organisation. Use an anonymized mirror (e.g. anonymous.4open.science) for review.",
      },
      "length.over_limit": {
        title: "Over the word limit",
        hint: "The estimated word count exceeds the limit you set for this submission.",
      },
      "length.near_limit": {
        title: "Close to the word limit",
        hint: "The estimated word count is close to the limit you set — leave some room in case the final count runs a little higher.",
      },
    },
  },
  vi: {
    tab: "Trước khi nộp",
    run: "Chạy kiểm tra trước khi nộp",
    running: "Đang kiểm tra…",
    beforeRun: "Chưa kiểm tra gì — hãy khai báo hồ sơ nộp bài ở trên rồi chạy kiểm tra.",
    clean:
      "Không phát hiện vấn đề nào. Đây là kiểm tra tự động, không phải lời cam kết bài sẽ được chấp nhận — hãy luôn đọc kỹ thông báo mời bài (call for papers) của tạp chí/hội nghị.",
    approximate:
      "Số từ này chỉ là ước tính — mỗi tạp chí/hội nghị tính số từ theo cách khác nhau, nên có thể không khớp với số liệu mà hệ thống của họ đưa ra.",
    goToLine: "Tới dòng",
    severity: {
      critical: "Nghiêm trọng",
      warning: "Cảnh báo",
      info: "Gợi ý",
    },
    skippedGroup: "Chưa kiểm tra — nhóm này chưa được bật cho lần nộp này.",
    skippedGroupHeading: "Chưa kiểm tra",
    suppressedRuleHeading: "Quy tắc đã tắt",
    suppressedReason: {
      unresolved_includes:
        "Đã tắt cho báo cáo này — mục này phụ thuộc vào một tệp \\input chưa tìm thấy, nên kết quả sẽ không đáng tin cậy. Hãy thêm tệp đó vào dự án, hoặc xoá dòng \\input đang gọi nó, rồi kiểm tra lại.",
      unexamined_files:
        "Đã tắt cho báo cáo này — trong dự án có tệp .tex mà tệp chính không nạp qua \\input hay \\include, nên chưa có gì đọc các nhãn và trích dẫn trong đó, kết quả sẽ không đáng tin cậy. Hãy \\input tệp đó từ tệp chính, hoặc xoá nó nếu là tệp còn sót lại, rồi kiểm tra lại.",
      double_blind_conflict:
        "Đã tắt cho báo cáo này — tạp chí/hội nghị muốn tuyên bố này xuất hiện ở bản camera-ready, không phải ở bài nộp phản biện kín, nên yêu cầu tuyên bố này ở đây sẽ là lời khuyên mâu thuẫn.",
    },
    noContent:
      "Chưa có gì để kiểm tra. Bản thảo vẫn còn trống hoặc mới chỉ là mẫu — mọi mục kiểm tra bị bỏ qua vì lý do này, không phải vì bị tắt.",
    placeholderTemplate:
      "Bản thảo này vẫn giống một mẫu chưa hoàn thiện — phần lớn là chỗ trống và ghi chú TODO, chưa có nội dung thật. Bạn vẫn có thể chạy kiểm tra, nhưng hầu hết kết quả sẽ chỉ nhắc lại những phần bạn chưa viết. Nên hoàn thiện bản thảo trước.",
    profile: {
      title: "Hồ sơ nộp bài",
      doubleBlindLabel: "Nộp bài phản biện kín (double-blind)",
      doubleBlindHint:
        "Bật nếu tạp chí/hội nghị yêu cầu nộp bài ẩn danh — sẽ kích hoạt các kiểm tra về tên tác giả, email, đơn vị công tác và các dấu hiệu để lộ danh tính khác.",
      wordLimitLabel: "Giới hạn số từ (không bắt buộc)",
      wordLimitHint:
        "Nhập giới hạn số từ của tạp chí/hội nghị để cảnh báo khi vượt quá ước tính. Để trống nếu muốn bỏ qua kiểm tra độ dài.",
      statementsLabel: "Các tuyên bố bắt buộc",
      statementsHint:
        "Chọn những tuyên bố mà tạp chí/hội nghị của bạn yêu cầu, để chỉ những mục đó được cảnh báo khi thiếu.",
    },
    requiredStatementLabel: {
      data_availability: "Khả năng truy cập dữ liệu",
      ethics: "Đạo đức nghiên cứu / phê duyệt IRB",
      coi: "Xung đột lợi ích",
      funding: "Nguồn tài trợ",
      author_contributions: "Vai trò các tác giả",
    },
    groupLabel: {
      crossref: "Tham chiếu chéo",
      bib: "Tài liệu tham khảo",
      statement: "Tuyên bố bắt buộc",
      format: "Định dạng",
      anon: "Ẩn danh",
      length: "Độ dài",
    },
    skippedReason: {
      anon: "Chưa kiểm tra — hãy khai báo đây là bài nộp phản biện kín ở trên để bật kiểm tra lộ danh tính.",
      length: "Chưa kiểm tra — hãy nhập giới hạn số từ ở trên để bật kiểm tra độ dài.",
    },
    rules: {
      "crossref.undefined_ref": {
        title: "Tham chiếu không xác định",
        hint: 'Một lệnh \\ref, \\eqref... trỏ tới một label không được định nghĩa ở bất kỳ đâu trong mã nguồn. Người đọc (và LaTeX) sẽ thấy dấu "??" ở vị trí này.',
      },
      "crossref.float_without_label": {
        title: "Hình hoặc bảng chưa có label",
        hint: "Môi trường hình/bảng này chưa có \\label, nên không thể được trích dẫn chéo bằng \\ref từ phần văn bản.",
      },
      "crossref.unused_label": {
        title: "Label không được tham chiếu",
        hint: "Label này đã được định nghĩa nhưng không có \\ref nào trong bài trỏ tới — thường không nghiêm trọng, nhưng nên kiểm tra lại.",
      },
      "crossref.duplicate_label": {
        title: "Label bị trùng",
        hint: "Label này được định nghĩa nhiều hơn một lần. Mọi \\ref tới nó sẽ trỏ về lần định nghĩa cuối cùng mà LaTeX đọc được, có thể âm thầm chỉ sai hình, bảng hoặc công thức.",
      },
      "bib.cite_key_missing": {
        title: "Khóa trích dẫn không có trong thư mục tài liệu",
        hint: 'Một lệnh \\cite trỏ tới khóa không tồn tại trong file .bib. Trích dẫn này sẽ hiện dấu "?" và bài báo có thể bị đánh dấu vì trích dẫn lỗi.',
      },
      "bib.duplicate_entry": {
        title: "Mục tài liệu tham khảo bị trùng",
        hint: "Khóa trích dẫn này được khai báo nhiều hơn một lần trong thư mục tài liệu. BibTeX sẽ âm thầm chỉ giữ lại một bản, có thể không phải bản bạn muốn dùng.",
      },
      "bib.missing_required_field": {
        title: "Mục tài liệu thiếu trường bắt buộc",
        hint: "Loại mục này cần một trường bắt buộc (như journal, year hoặc booktitle) nhưng chưa được khai báo. Nhiều tạp chí từ chối tài liệu tham khảo thiếu thông tin.",
      },
      "bib.missing_doi": {
        title: "Tài liệu tham khảo chưa có DOI",
        hint: "Mục này chưa có trường doi. Nhiều tạp chí hiện yêu cầu DOI nếu nguồn có — hãy bổ sung nếu có.",
      },
      "bib.uncited_entry": {
        title: "Tài liệu tham khảo không được trích dẫn",
        hint: "Mục này có trong thư mục tài liệu nhưng không có \\cite nào trong bản thảo sử dụng nó. Hãy xóa hoặc trích dẫn nó.",
      },
      "statement.data_availability_missing": {
        title: "Thiếu tuyên bố về khả năng truy cập dữ liệu",
        hint: "Không tìm thấy tuyên bố về khả năng truy cập dữ liệu. Hầu hết tạp chí hiện yêu cầu một đoạn giải thích nơi có thể truy cập dữ liệu gốc.",
      },
      "statement.ethics_missing": {
        title: "Thiếu tuyên bố đạo đức nghiên cứu",
        hint: "Không tìm thấy tuyên bố về đạo đức nghiên cứu (như phê duyệt IRB, sự đồng thuận tham gia, phúc lợi động vật). Hãy kiểm tra yêu cầu của tạp chí trước khi nộp bài.",
      },
      "statement.coi_missing": {
        title: "Thiếu tuyên bố xung đột lợi ích",
        hint: "Không tìm thấy tuyên bố về xung đột lợi ích (competing interests). Hầu hết tạp chí yêu cầu mục này dù không có gì cần công bố.",
      },
      "statement.funding_missing": {
        title: "Thiếu tuyên bố về nguồn tài trợ",
        hint: "Không tìm thấy tuyên bố về nguồn tài trợ. Hãy bổ sung nếu nghiên cứu này có nhận tài trợ.",
      },
      "statement.author_contributions_missing": {
        title: "Thiếu tuyên bố về vai trò các tác giả",
        hint: "Không tìm thấy tuyên bố mô tả vai trò/đóng góp của từng tác giả. Nhiều tạp chí yêu cầu mục này (ví dụ theo chuẩn CRediT).",
      },
      "format.compressed_leading": {
        title: "Giãn dòng bị thu hẹp bất thường",
        hint: "Mã nguồn ghi đè khoảng giãn dòng xuống thấp hơn mức mặc định của mẫu — một cách thường dùng để nhồi thêm nội dung vượt giới hạn số trang. Phản biện và biên tập viên thường kiểm tra việc này, và một số tạp chí coi đây là vi phạm định dạng.",
      },
      "format.margin_override": {
        title: "Lề trang bị thay đổi",
        hint: "Mã nguồn thay đổi lề trang khác với mặc định của mẫu — thường nhằm nhồi thêm nội dung trên mỗi trang. Hãy kiểm tra lại xem tạp chí có cho phép việc này.",
      },
      "format.large_negative_vspace": {
        title: "Khoảng cách dọc âm quá lớn",
        hint: "Một lệnh \\vspace âm lớn kéo nội dung lên trên, thu hẹp khoảng trống mà mẫu quy định — một cách khác thường dùng để nhồi thêm nội dung.",
      },
      "format.font_size_override": {
        title: "Cỡ chữ bị thay đổi",
        hint: "Mã nguồn đặt cỡ chữ nhỏ hơn mặc định của mẫu — một cách khác để nhồi thêm nội dung vượt giới hạn trang hoặc số từ.",
      },
      "anon.author_populated": {
        title: "Tên tác giả vẫn hiển thị",
        hint: "Lệnh \\author vẫn chứa tên tác giả. Bài nộp phản biện kín (double-blind) không được để lộ danh tính tác giả.",
      },
      "anon.affiliation_populated": {
        title: "Cơ quan/đơn vị công tác vẫn hiển thị",
        hint: "Thông tin cơ quan/đơn vị công tác vẫn còn trong mã nguồn. Điều này có thể để lộ danh tính tác giả dù đã xóa tên.",
      },
      "anon.email_present": {
        title: "Phát hiện địa chỉ email",
        hint: "Có địa chỉ email trong mã nguồn. Email hầu như luôn để lộ danh tính tác giả hoặc đơn vị công tác — hãy xóa để đảm bảo phản biện kín.",
      },
      "anon.orcid_present": {
        title: "Phát hiện mã ORCID",
        hint: "Có mã định danh ORCID trong bài. Mã này liên kết trực tiếp tới hồ sơ cá nhân của nhà nghiên cứu nên cần được xóa khi phản biện kín.",
      },
      "anon.thanks_present": {
        title: "Phát hiện chú thích tác giả (\\thanks)",
        hint: "Có chú thích \\thanks trong bài — loại chú thích này thường chứa thông tin tài trợ hoặc liên hệ gắn với một tác giả cụ thể, có thể làm lộ danh tính.",
      },
      "anon.acknowledgements_present": {
        title: "Phát hiện mục lời cảm ơn",
        hint: "Có mục lời cảm ơn trong bài. Mục này thường nêu tên người, phòng thí nghiệm hoặc đề tài tài trợ có thể để lộ danh tính tác giả — hãy để lại cho bản camera-ready.",
      },
      "anon.funding_identifiers": {
        title: "Phát hiện mã số tài trợ/đề tài",
        hint: "Có mã số đề tài hoặc tên đơn vị tài trợ xuất hiện trong văn bản. Những thông tin này có thể bị tra cứu và lần ra phòng thí nghiệm của tác giả.",
      },
      "anon.self_reference": {
        title: "Câu văn có thể tự để lộ danh tính",
        hint: 'Cụm từ như "công trình trước đây của chúng tôi" đi kèm một trích dẫn có thể giúp phản biện suy ra ngay tác giả — nên viết lại ở ngôi thứ ba khi nộp phản biện kín.',
      },
      "anon.repository_link": {
        title: "Liên kết mã nguồn/dữ liệu chưa được ẩn danh",
        hint: "Liên kết tới mã nguồn hoặc dữ liệu trỏ tới một tài khoản hoặc tổ chức có tên thật. Hãy dùng bản sao ẩn danh (ví dụ anonymous.4open.science) khi nộp phản biện kín.",
      },
      "length.over_limit": {
        title: "Vượt quá giới hạn số từ",
        hint: "Số từ ước tính đã vượt quá giới hạn bạn đặt cho bài nộp này.",
      },
      "length.near_limit": {
        title: "Gần đạt giới hạn số từ",
        hint: "Số từ ước tính đang gần chạm giới hạn bạn đặt — nên để dư một chút phòng khi số từ cuối cùng cao hơn.",
      },
    },
  },
};

export function preflightCopy(locale: UiLanguage): PreflightCopy {
  return COPY[locale];
}
