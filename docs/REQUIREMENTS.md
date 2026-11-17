# REQUIREMENTS — Automated Security Patch Validation and Regression Testing in CI/CD

استخراج الزامات از دو سند مرجع. این فایل مرجع ردیابی (traceability) پروژه است و با پیشرفت کار
ستون‌های «Status» و «Evidence» به‌روزرسانی می‌شوند.

## Source documents

| Tag | File | Description |
|-----|------|-------------|
| `SPEC` | [`docs/project-spec.pdf`](project-spec.pdf) | سند رسمی درس (مدرس: سولماز سلیمی) — **مرجع اصلی / قانون صفر** |
| `PROMPT` | [`docs/prompt.pdf`](prompt.pdf) | سند راهنمای پیاده‌سازی (۲۶ مرحله) |

**Conflict rule.** هر جا `PROMPT` با `SPEC` اختلاف داشت، `SPEC` اولویت دارد. اختلاف‌های
شناسایی‌شده در بخش [Conflicts and assumptions](#conflicts-and-assumptions) ثبت شده‌اند.

## Legend

- **Priority** — `M` = mandatory (صریح در SPEC)، `S` = should (صریح در PROMPT، ضمنی در SPEC)، `C` = could (پیشنهادی).
- **Status** — `TODO` / `WIP` / `DONE` / `PARTIAL` / `WONTFIX (documented)`.
- **Evidence** — مسیر فایل، تست، یا artifact واقعی که تحقق الزام را اثبات می‌کند. هیچ الزامی
  بدون شواهد `DONE` علامت نخورده است.

## وضعیت فعلی

| | |
|---|---|
| الزامات استخراج‌شده | **۱۰۱** |
| `DONE` با شواهد | **۱۰۱** |
| تست‌های خودکار | **۱۶۳** (همه سبز) |
| اهداف تحویل‌شده | ۲ (`recparse` اسباب‌بازی + `cjson` واقعی) |
| کدهای خروج تأییدشده با `$?` | ۰، ۱۰، ۲۰، ۳۰، ۴۰ |

ارجاع‌های `runs/*` به artifactهای تولیدشده در اجرای واقعی اشاره دارند؛ با اجرای
`patch-validator validate --config configs/<target>.yaml` دوباره تولید می‌شوند.

---

## 1. Scope and target constraints

| ID | Requirement | Source | Pri | Module | Implementation approach | Verification method | Status | Evidence |
|----|-------------|--------|-----|--------|------------------------|---------------------|--------|----------|
| R-SCOPE-01 | Target = برنامهٔ C/C++ کامپایل‌شدنی به ELF روی Linux x86_64 | SPEC §2 p1 | M | BuildManager | کامپایل با gcc/clang به ELF؛ بررسی ELF magic پس از build | `file`/`readelf` روی باینری تولیدشده در تست یکپارچه | DONE | `build/manager.py` ELF magic check · `runs/*/builds/*/meta.json` |
| R-SCOPE-02 | ورودی برنامهٔ هدف از `stdin` / file / `argv` دریافت شود | SPEC §2 p1 | M | ExecutionEngine | `input_method` در config با سه حالت `stdin\|file\|argv` | تست واحد برای هر سه حالت | DONE | `execution/engine.py::_build_invocation` · `test_config_and_minimize.py` |
| R-SCOPE-03 | کد منبع هر دو نسخه (base و patched) در دسترس و قابل ساخت باشد | SPEC §2 p1 | M | BuildManager | checkout دو revision از مخزن git هدف با `git worktree` | اجرای `build` روی هر دو نسخه | DONE | `vcs/git.py::add_worktree` · هر دو هدف ساخته می‌شوند |
| R-SCOPE-04 | هدف نباید اسکریپت/زبان مفسری باشد (اما خودِ ابزار می‌تواند Python باشد) | SPEC §2 p1 | M | — | محدودیت مستندشده؛ ابزار Python 3، هدف‌ها C | بازبینی مستندات | DONE | ابزار Python، هر دو هدف C · `ADR-001` |
| R-SCOPE-05 | ابزار باید روی **دو برنامهٔ مستقل** C/C++ آزمایش و تحویل شود | SPEC §4 p4 | M | configs/ | دو config مجزا: toy + real-world | اجرای کامل CLI روی هر دو | DONE | `configs/recparse.yaml` + `configs/cjson.yaml`، هر دو exit 0 |
| R-SCOPE-06 | **حداقل یکی** از دو هدف باید پروژه/کتابخانهٔ واقعی و غیر اسباب‌بازی باشد | SPEC §4 p4 | M | configs/ | انتخاب پروژهٔ open-source با CVE و commit رفع واقعی | config + گزارش اجرای واقعی | DONE | cJSON، commit رفع واقعی `3ef4e4e` · `runs/cjson/report.json` |
| R-SCOPE-07 | الزام به اجرای پویا؛ اتکا به SAST یا بازبینی متنی کافی نیست | SPEC §2 p1 | M | ExecutionEngine | همهٔ احکام از اجرای واقعی باینری استخراج می‌شوند | عدم وجود مسیر تصمیم‌گیری بدون اجرا | DONE | هیچ مسیر تصمیمی بدون اجرا؛ همهٔ یافته‌ها از `ExecutionResult` |
| R-SCOPE-08 | قابلیت تعمیم: افزودن هدف جدید فقط با تغییر فایل پیکربندی، بدون تغییر کد | SPEC §2 p1، PROMPT §18 | M | ConfigManager | هیچ نام تابع/فایلِ هدف در کد ابزار hardcode نشود | افزودن هدف سوم صرفاً با YAML در تست | DONE | هدف دوم فقط با YAML + harness افزوده شد، بدون تغییر کد ابزار |
| R-SCOPE-09 | ابزار نباید بر اساس نام فایل یا شناسهٔ از پیش شناخته‌شدهٔ وصله تصمیم بگیرد (آزمون روز دفاع / unseen patches) | SPEC §4 p4 | M | ClassificationEngine | تصمیم فقط از شواهد اجرا؛ ممنوعیت allow-list نام وصله | تست با وصلهٔ ناشناخته (`unseen`) | DONE | `--patched-revision` · `test_end_to_end.py::TestUnseenPatch` |

## 2. Patch validation and diff correlation (هستهٔ اصلی — ۲۵ نمره)

| ID | Requirement | Source | Pri | Module | Implementation approach | Verification method | Status | Evidence |
|----|-------------|--------|-----|--------|------------------------|---------------------|--------|----------|
| R-CORE-01 | دریافت نسخهٔ قبل از وصله، نسخهٔ بعد از وصله و Git Diff میان آن‌ها | SPEC §3.1 p2 | M | PatchAnalyzer | `git diff base..patched` با `--unified` و parse واقعی | تست واحد روی diff نمونه | DONE | `vcs/git.py::diff` · `analysis/diffparse.py` · `runs/*/patch.diff` |
| R-CORE-02 | استخراج فایل‌های تغییرکرده و بازه‌های خطوط تغییرکرده (hunks) | SPEC §3.1، PROMPT §9 | M | PatchAnalyzer | parser کامل unified diff (hunk header + line mapping) | تست واحد با diff چندفایلی | DONE | `diffparse.parse_patch` · `test_patch_analysis.py::TestDiffParsing` |
| R-CORE-03 | شناسایی توابع تغییرکرده تا حد امکان (بدون وابستگی به نام تابع خاص) | SPEC §3.1، PROMPT §9 | M | PatchAnalyzer | heuristic استخراج محدودهٔ تابع از منبع C + نگاشت خط→تابع | تست واحد روی فایل C نمونه | DONE | `analysis/cfunctions.py` · `test_patch_analysis.py::TestFunctionMapping` |
| R-CORE-04 | تطبیق Stack Trace (فایل/تابع/خط) با hunkهای وصله | SPEC §3.1 p2 | M | PatchAnalyzer | امتیازدهی تطبیق: فایل+تابع+فاصلهٔ خطی | تست واحد با stack trace مصنوعی و واقعی | DONE | `patch.PatchAnalyzer._match_frame` · `test_end_to_end.py` |
| R-CORE-05 | در نظر گرفتن ارتباط **غیرمستقیم** از طریق caller/callee یا مسیر اجرا | SPEC §3.1 p2، PROMPT §9 | M | PatchAnalyzer | پیمایش frameهای stack trace فراتر از فریم صفر + تطبیق مسیر | تست با خطایی که فریم بالایی آن در hunk است | DONE | همهٔ فریم‌ها بررسی می‌شوند؛ `indirect=True` روی cJSON واقعی |
| R-CORE-06 | صرف همجواری ظاهری خطا و diff برای اثبات ارتباط کافی نیست | SPEC §3.1 p2 | M | PatchAnalyzer | سطوح confidence؛ همجواری تنها ⇒ `WEAK`، نه `CONFIRMED` | تست واحد روی حالت همجواری بدون شواهد | DONE | فایل مشترک تنها ⇒ `WEAK`، منتسب نمی‌شود · `Correlation.attributed` |
| R-CORE-07 | در صورت ناکافی بودن شواهد، ارتباط `UNKNOWN` گزارش شود | SPEC §3.1، PROMPT §9 | M | PatchAnalyzer | مقدار پیش‌فرض `UNKNOWN` و نه `CORRELATED` | تست واحد بدون stack trace | DONE | `UNKNOWN` پیش‌فرض · یافتهٔ fortify در release |
| R-CORE-08 | تولید Patch Correlation Report با فیلدهای: Finding ID, Affected File, Affected Function, Relevant Diff Hunk, Stack Trace Evidence, Base Behavior, Patched Behavior, Correlation Evidence, Confidence, Correlation Status | PROMPT §9 | S | PatchAnalyzer / Report | dataclass اختصاصی + سریال‌سازی JSON | اعتبارسنجی schema گزارش | DONE | `Correlation.to_dict` با ۱۳ فیلد · `report.json → patch_correlations` |
| R-CORE-09 | هر ورودی خطاساز با تنظیمات متناظر روی **هر دو نسخه** اجرا شود | SPEC §3.1 p2 | M | DifferentialTester | ماتریس اجرا: {base,patched} × {release,sanitized} | ثبت ۴ اجرا به ازای هر تست در گزارش | DONE | `pipeline._execute_matrix` · ۷۲ و ۹۶ اجرا در دو هدف |
| R-CORE-10 | تفکیک وضعیت یافته‌ها به FIXED / INCOMPLETE_FIX / NEW_ISSUE / FUNCTIONAL_REGRESSION / INCONCLUSIVE | SPEC §3.1 p2، PROMPT §15 | M | ClassificationEngine | جدول تصمیم مبتنی بر (base_outcome, patched_outcome, oracle) | تست واحد برای تمام ترکیب‌ها | DONE | `analysis/findings.py::FindingKind` · `classify/engine.py` |
| R-CORE-11 | «تازه مشاهده شدن یک خطا» به‌تنهایی اثبات نمی‌کند وصله علت آن بوده است | SPEC §3.1 p2 | M | ClassificationEngine | `NEW_ISSUE` فقط با correlation؛ در غیر این صورت confidence پایین + ثبت ابهام | تست واحد سناریوی خطای جدید بدون ارتباط | DONE | یادداشت صریح روی هر `NEW_ISSUE` · `test_differential_*` |
| R-CORE-12 | تشخیص Functional Regression نیازمند اثبات: base مطابق Oracle بوده و patched آن را نقض کرده | SPEC §3.1 p2، PROMPT §10 | M | DifferentialTester | شرط دوطرفه: `base==oracle and patched!=oracle` | تست واحد با base ناسازگار با oracle | DONE | شرط دوطرفه در `_functional_axis` · `test_...::TestFunctionalAxis` |
| R-CORE-13 | اگر base هم با Oracle سازگار نبود، صرف اختلاف دو نسخه ⇒ اعلام قطعی regression ممنوع | PROMPT §10 | M | DifferentialTester | خروجی `INCONCLUSIVE` + یادداشت صریح | تست واحد | DONE | `INCONCLUSIVE` وقتی base هم Oracle را نقض کرده |

## 3. Dynamic testing and crash classification (۲۵ نمره)

| ID | Requirement | Source | Pri | Module | Implementation approach | Verification method | Status | Evidence |
|----|-------------|--------|-----|--------|------------------------|---------------------|--------|----------|
| R-DYN-01 | اجرای واقعی ELF با پشتیبانی stdin / file / argv | SPEC §3.2، PROMPT §7 | M | ExecutionEngine | `subprocess` داخل sandbox با آماده‌سازی ورودی | تست واحد سه‌حالته | DONE | `execution/engine.py` · سه روش ورودی |
| R-DYN-02 | مجموعه آزمون شامل ورودی‌های معتبر، مرزی و نامعتبر | SPEC §3.2 p2 | M | configs/, targets/ | تعریف test case در YAML با برچسب `category` | پوشش هر سه دسته در هر دو هدف | DONE | ۱۸ و ۲۴ test case در دو هدف، هر چهار دسته |
| R-DYN-03 | اجرای یکسان مجموعه آزمون روی هر دو نسخه و هر دو build | SPEC §3.2 p2 | M | DifferentialTester | حلقهٔ ماتریسی با تنظیمات یکسان | گزارش JSON شامل ۴ اجرا در هر تست | DONE | ماتریس `{base,patched} × {release,sanitized}` |
| R-DYN-04 | ثبت Error Type (stack/heap overflow, UAF, double free, null deref, int overflow, div-by-zero, segfault, abort, UB) | SPEC §3.2، PROMPT §8 | M | CrashAnalyzer | parser خروجی ASan/UBSan + نگاشت سیگنال | تست واحد با نمونه‌های واقعی خروجی sanitizer | DONE | `analysis/crash.py` نگاشت ASan/UBSan/glibc · `test_crash_analysis.py` |
| R-DYN-05 | ثبت Detection Mechanism (OS signal / ASan / UBSan / stack protector / runtime diagnostic) | SPEC §3.2 p2 | M | CrashAnalyzer | فیلد مستقل `detection_mechanism` | تست واحد | DONE | `detection_mechanism` با ۱۰ مقدار |
| R-DYN-06 | ثبت Termination: exit code، signal، stdout، stderr | SPEC §3.2 p2 | M | ExecutionEngine | ثبت خام هر چهار مورد در `ExecutionResult` | تست واحد | DONE | `ExecutionResult.to_dict` · `runs/*/exec/*/meta.json` |
| R-DYN-07 | عبور از timeout یا محدودیت منابع گزارش شود ولی **خودکار** به‌عنوان آسیب‌پذیری طبقه‌بندی نشود | SPEC §3.2 p2، PROMPT §7 | M | CrashAnalyzer | وضعیت مجزای `TIMEOUT` / `RESOURCE_LIMIT`، خارج از دستهٔ security | تست واحد با برنامهٔ کند | DONE | `outcome` جدا برای timeout/resource · `test_crash_analysis.py::TestBoundaries` |
| R-DYN-08 | تفکیک کامل Release Build و Sanitized Build؛ نتایج مخلوط نشوند | SPEC §3.2 p2، PROMPT §6 | M | BuildManager / Report | `build_mode` در کلید همهٔ نتایج؛ مقایسه فقط میان buildهای متناظر | بازبینی schema + تست واحد | DONE | `CasePair.__post_init__` استثنا می‌دهد · `test_...::TestPairIntegrity` |
| R-DYN-09 | گزارش اینکه هر حالت چه چیزی را آشکار کرد (release vs sanitized) | SPEC §3.2 p2 | M | Report | بخش `build_mode_comparison` در گزارش | گزارش نمونهٔ تولیدشده | DONE | `build_mode_comparison` در گزارش · `boundary_text32` |
| R-DYN-10 | ثبت اطلاعات اجرا: exit code، signal، stdout، stderr، زمان اجرا، timeout، resource limit، build mode، input hash، binary hash، test id | PROMPT §7 | S | ExecutionEngine | dataclass `ExecutionResult` با همهٔ فیلدها | اعتبارسنجی schema | DONE | `ExecutionResult` با ۲۲ فیلد · schema گزارش |
| R-DYN-11 | استخراج Stack Trace و محل خطا (فایل/تابع/خط) در صورت وجود | SPEC §3.2، PROMPT §8 | M | CrashAnalyzer | parse فریم‌های ASan + symbolization با build دیباگ‌دار | تست واحد با خروجی واقعی | DONE | `analysis/frames.py` · فریم‌های نمادین در `runs/*/exec/*/stderr.bin` |
| R-DYN-12 | تولید Crash Signature پایدار برای هر خطا | PROMPT §8، §11 | M | CrashAnalyzer | هش از (error_type, detection, N فریم نرمال‌شدهٔ بالایی) | تست پایداری در ۳ اجرای متوالی | DONE | `crash_signature` + `location_signature` · ۳/۳ بازپخش یکسان |
| R-DYN-13 | Error Classification با Root Cause Analysis یکسان نیست؛ ادعای علت ریشه‌ای نشود | SPEC §3.2، PROMPT §8 | M | CrashAnalyzer | فقط دسته‌بندی + شواهد؛ بدون ادعای علت | بازبینی خروجی و مستندات | DONE | هیچ ادعای علت ریشه‌ای · `docs/SECURITY_ANALYSIS.md` |
| R-DYN-14 | وجود crash یا exit code غیرصفر ⇒ اثبات آسیب‌پذیری قابل بهره‌برداری نیست | SPEC §3.2 p2، PROMPT اصول | M | ClassificationEngine | تفکیک `crash` از `security_finding`؛ هیچ ادعای exploitability | بازبینی مستندات + تست | DONE | کد خروج غیرصفر ⇒ `clean` · `test_...::test_nonzero_exit_alone_is_not_a_crash` |

## 4. Reproducibility, minimization, regression tests (۱۵ نمره)

| ID | Requirement | Source | Pri | Module | Implementation approach | Verification method | Status | Evidence |
|----|-------------|--------|-----|--------|------------------------|---------------------|--------|----------|
| R-REPRO-01 | بستهٔ بازتولید شامل ورودی خطاساز، commit hash، هش باینری، تنظیمات ساخت، متغیرهای محیطی، دستور اجرا | SPEC §3.3 p3، PROMPT §12 | M | ReproducerManager | پوشهٔ bundle + `manifest.json` | بازتولید از روی bundle در تست | DONE | `reproducer/bundle.py::_manifest` · `runs/*/bundles/*/manifest.json` |
| R-REPRO-02 | هر خطا حداقل **سه بار** بازپخش و نتیجهٔ هر اجرا جداگانه ثبت شود | SPEC §3.3، PROMPT §12 | M | ReproducerManager | `replay_count: 3` پیش‌فرض، ثبت آرایهٔ نتایج | گزارش JSON با ۳ رکورد | DONE | `reproduction.replays: 3` (حداقل در schema) · آرایهٔ `replays` |
| R-REPRO-03 | موارد ناپایدار (flaky) صریحاً مشخص شوند | SPEC §3.3 p3 | M | ReproducerManager | `stability: stable\|flaky` بر اساس یکسانی crash signature | تست واحد با نتایج ناهمسان | DONE | `stability: stable|flaky|not_reproduced` |
| R-REPRO-04 | دستور CLI مستقل برای بازپخش یک bundle | PROMPT §12 | S | CLI | `patch-validator reproduce <bundle>` | اجرای واقعی روی bundle تولیدشده | DONE | `patch-validator reproduce` با تأیید SHA256 باینری |
| R-REPRO-05 | کوچک‌سازی خودکار ورودی با Delta Debugging (ddmin) | SPEC §3.3 p3، PROMPT §11 | M | TestcaseMinimizer | پیاده‌سازی ddmin روی سطح بایت | تست واحد + کاهش واقعی اندازه | DONE | `minimize/ddmin.py` · ۱۰۲۴→۳ بایت در تست |
| R-REPRO-06 | ورودی کوچک‌شده باید **همان نوع خطا در همان محل** را بازتولید کند | SPEC §3.3 p3 | M | TestcaseMinimizer | predicate = تطابق crash signature، نه صرفاً exit code | تست واحد با دو خطای متفاوت | DONE | predicate بر اساس `crash_signature` · `pipeline._predicate` |
| R-REPRO-07 | «هر کد خروج غیرصفر» معیار حفظ خطا نیست | SPEC §3.3 p3، PROMPT §11 | M | TestcaseMinimizer | predicate صریحاً signature-based | تست واحد: exit!=0 با signature متفاوت ⇒ رد | DONE | کد خروج در predicate نقشی ندارد · `test_...::TestMinimizer` |
| R-REPRO-08 | ذخیرهٔ هر دو ورودی اولیه و کوچک‌شده + درصد کاهش | SPEC §3.3، PROMPT §11 | M | TestcaseMinimizer | فیلدهای `original_size`, `minimized_size`, `reduction_percent` | گزارش JSON | DONE | `original_size`/`minimized_size`/`reduction_percent` · ۶۴.۹٪ واقعی |
| R-REPRO-09 | محدودیت تعداد تلاش و زمان برای جلوگیری از اجرای بی‌نهایت | PROMPT §11 | M | TestcaseMinimizer | `max_iterations`, `budget_seconds` در config | تست واحد با بودجهٔ کوچک | DONE | `max_iterations` + `budget_seconds` · `stop_reason` در گزارش |
| R-REG-01 | تولید خودکار Regression Test از ورودی کوچک‌شده | SPEC §3.3 p3، PROMPT §13 | M | RegressionGenerator | تولید فایل تست + ثبت در مجموعهٔ آزمون پروژه | فایل تست تولیدشده در مخزن | DONE | `regression/generator.py` · `runs/*/regression/*/testcase.yaml` |
| R-REG-02 | تست تولیدشده باید بروز خطا روی base و نبود آن روی patched را بررسی کند | SPEC §3.3 p3 | M | RegressionGenerator | دو assert مجزا در تست تولیدی | اجرای تست تولیدشده | DONE | `expectations.base.must_fault` و `patched.must_fault` |
| R-REG-03 | تست تولیدشده رفتار مورد انتظار patched را بر اساس Oracle بررسی کند و صرفاً به exit code تکیه نکند | PROMPT §13 | M | RegressionGenerator | تطبیق stdout/exit/semantic از Oracle | بازبینی تست تولیدی | DONE | Oracle از test case اصلی در `expectations.patched.oracle` |
| R-REG-04 | اجرای مجدد تست‌های تولیدشده در CI تضمین شود | SPEC §3.3، PROMPT §13 | M | CI | مرحلهٔ `regression` در workflow | لاگ CI | DONE | مرحلهٔ ۱۰ پایپ‌لاین · `.github/workflows/validate.yml` |

## 5. Independent functional oracle

| ID | Requirement | Source | Pri | Module | Implementation approach | Verification method | Status | Evidence |
|----|-------------|--------|-----|--------|------------------------|---------------------|--------|----------|
| R-ORC-01 | معیار صحت عملکرد باید **پیش از ارزیابی** و مستقل از خروجی نسخهٔ وصله‌شده تعریف شود | SPEC §2 p2، PROMPT §10 | M | Oracle | `SPECIFICATION.md` + جدول oracle در YAML، commit شده پیش از اجرا | تاریخ commit مشخصات < تاریخ اجرا | DONE | `SPECIFICATION.md` پیش از وصله‌ها commit شد — تاریخچهٔ git شاهد است |
| R-ORC-02 | Oracle نباید از خروجی Correct Patch استخراج شود | PROMPT §4.5 | M | Oracle | مستند تصمیم + عدم وجود مسیر تولید خودکار oracle از باینری | بازبینی کد و مستندات | DONE | هیچ مسیر تولید خودکار Oracle · `ADR-006`؛ برای cJSON استخراج از RFC 8259 |
| R-ORC-03 | Oracle شامل: ورودی، اعتبار ورودی، stdout مورد انتظار، stderr (در صورت اهمیت)، exit code، رفتار معنایی، منبع oracle | SPEC §2، PROMPT §10 | M | Oracle | schema کامل test case | اعتبارسنجی schema | DONE | `OracleSpec` با ۷ فیلد · schema پیکربندی |
| R-ORC-04 | خروجی نسخهٔ وصله‌شده یا مدل زبانی به‌تنهایی مرجع صحت نیست | SPEC §2 p2 | M | — | مستندشده در DESIGN_DECISIONS | بازبینی مستندات | DONE | `docs/DESIGN_DECISIONS.md` ADR-006 |
| R-ORC-05 | وضعیت تأیید مدرس برای oracleها جداگانه نگهداری شود | PROMPT §10 | S | Oracle | فیلد `instructor_approved: true\|false\|pending` | بازبینی config | DONE | `instructor_approved: yes|no|pending` در هر Oracle |

## 6. Binary hardening (۵ نمره)

| ID | Requirement | Source | Pri | Module | Implementation approach | Verification method | Status | Evidence |
|----|-------------|--------|-----|--------|------------------------|---------------------|--------|----------|
| R-HARD-01 | بررسی NX، PIE، RELRO، Stack Canary روی Release Build هر دو نسخه | SPEC §3.4 p3 | M | HardeningAnalyzer | parse خروجی `readelf`/`objdump` | تست واحد روی باینری واقعی | DONE | `analysis/hardening.py` با `readelf` · `runs/*/hardening/` |
| R-HARD-02 | تفکیک سه سطح RELRO: None / Partial / Full | SPEC §3.4، PROMPT §14 | M | HardeningAnalyzer | بررسی `GNU_RELRO` + `BIND_NOW`/`DT_FLAGS` | تست واحد با دو باینری متفاوت | DONE | `none`/`partial`/`full` · تأیید با باینری lazy-binding |
| R-HARD-03 | هشدار در صورت غیرفعال‌شدن ناخواستهٔ یک محافظ در نسخهٔ جدید | SPEC §3.4 p3 | M | HardeningAnalyzer | مقایسهٔ base/patched + `change_status` | تست با build عمداً بدون canary | DONE | `change_status` + هشدار · تأیید با باینری عمداً بدون محافظ |
| R-HARD-04 | وجود PIE اثبات فعال‌بودن ASLR در محیط اجرا نیست | SPEC §3.4 p3 | M | HardeningAnalyzer / docs | یادداشت محدودیت در گزارش | بازبینی گزارش | DONE | `LIMITATIONS` در خروجی JSON و گزارش خوانا |
| R-HARD-05 | وجود شواهد canary به‌معنای محافظت همهٔ توابع نیست | SPEC §3.4 p3 | M | HardeningAnalyzer / docs | یادداشت محدودیت در گزارش | بازبینی گزارش | DONE | همان |
| R-HARD-06 | استفاده از شواهد واقعی ELF (نه حدس از flagهای ساخت) | SPEC §3.4، PROMPT §14 | M | HardeningAnalyzer | خواندن مستقیم ELF با readelf | بازبینی کد | DONE | فقط `readelf`؛ هیچ استنتاجی از پرچم‌های ساخت |

## 7. CI/CD, exit codes, reporting (۱۰ نمره)

| ID | Requirement | Source | Pri | Module | Implementation approach | Verification method | Status | Evidence |
|----|-------------|--------|-----|--------|------------------------|---------------------|--------|----------|
| R-CICD-01 | ابزار از خط فرمان قابل اجرا باشد | SPEC §3.5 p3 | M | CLI | `argparse` با زیردستورها | اجرای واقعی | DONE | `cli.py` با ۸ زیردستور |
| R-CICD-02 | تولید خروجی JSON ساختاریافته | SPEC §3.5 p3 | M | Report | schema نسخه‌دار + اعتبارسنجی jsonschema | validate در تست | DONE | `report/schema.json` · اعتبارسنجی پیش از نوشتن |
| R-CICD-03 | تولید گزارش خلاصهٔ خوانا برای توسعه‌دهنده | SPEC §3.5 p3 | M | Report | Markdown/متن رنگی | گزارش نمونه | DONE | `report.md` · `report/writer.py::render_markdown` |
| R-CICD-04 | دو گزارش نباید با یکدیگر تناقض داشته باشند | PROMPT §16 | M | Report | تولید هر دو از یک مدل دادهٔ واحد | تست مقایسهٔ فیلدهای کلیدی | DONE | هر دو از یک `RunRecord` · `test_end_to_end.py::test_the_markdown_summary_agrees` |
| R-CICD-05 | هر یافته باید Evidence Reference داشته باشد | PROMPT §16 | M | Report | `evidence_refs[]` به مسیر لاگ/artifact | اعتبارسنجی schema | DONE | `evidence_refs` · `test_every_finding_references_evidence_that_exists` |
| R-EXIT-01 | `0 = PASS` — خطای پایه بازتولید نشده، خطای تأییدشدهٔ دیگری نیست، همهٔ آزمون‌های عملکردی موفق و بررسی‌های الزامی کامل | SPEC §3.5 p3 | M | ClassificationEngine | شرط چهارگانه در جدول تصمیم | تست واحد | DONE | شرط چهارگانه + بازتولید پایه · `test_...::test_clean_run_passes` |
| R-EXIT-02 | `10 = VULN_REMAINS / NEW_ISSUE` | SPEC §3.5 p3 | M | ClassificationEngine | — | تست واحد | DONE | `incomplete-patch` → ۱۰ از طریق CLI واقعی |
| R-EXIT-03 | `20 = FUNC_REGRESSION` | SPEC §3.5 p3 | M | ClassificationEngine | — | تست واحد | DONE | `regression-patch` → ۲۰ از طریق CLI واقعی |
| R-EXIT-04 | `30 = BUILD_OR_CONFIG_ERROR` و نباید با یافتن خطای امنیتی یکسان حساب شود | SPEC §3.5 p3 | M | ClassificationEngine | مسیر خطای جدا برای build/config | تست واحد با config خراب | DONE | config ناقص/revision ناشناخته → ۳۰ · مسیر `BuildError` جدا |
| R-EXIT-05 | `40 = INCONCLUSIVE` — بررسی الزامی انجام نشده یا شواهد کافی نیست | SPEC §3.5 p3 | M | ClassificationEngine | پرچم `mandatory_checks_complete` | تست واحد | DONE | تست‌های فقط-معتبر → ۴۰ |
| R-EXIT-06 | اولویت در همزمانی چند وضعیت: **30 > 10 > 20 > 40 > 0** | SPEC §3.5 p3 | M | ClassificationEngine | لیست اولویت ثابت و مستند | تست واحد با چند وضعیت همزمان | DONE | `EXIT_PRECEDENCE = (30,10,20,40,0)` · ۱۴ حالت در تست |
| R-EXIT-07 | تمام یافته‌ها و وضعیت‌های مستقل امنیت/عملکرد/کامل‌بودن تحلیل در JSON باقی بمانند | SPEC §3.5 p3، PROMPT §15 | M | Report | سه فیلد مستقل + `final_classification` | بازبینی schema | DONE | سه فیلد مستقل در `classification` |
| R-EXIT-08 | exit code واقعی پروسه باید مطابق مشخصات باشد (چاپ در JSON کافی نیست) | PROMPT §17 | M | CLI | `sys.exit(code)` | تست با `$?` در shell | DONE | `sys.exit` واقعی؛ هر پنج کد با `$?` تأیید شد |
| R-CICD-06 | Pipeline شامل checkout, env setup, deps, config validation, build, release test, sanitized test, crash analysis, patch correlation, regression, hardening, report, artifact upload, final exit code | PROMPT §19 | S | CI | GitHub Actions workflow | اجرای workflow | DONE | ۱۴ مرحله در `.github/workflows/validate.yml` |
| R-CICD-07 | در صورت شکست، گزارش‌ها همچنان ذخیره و قابل دریافت باشند اما CI نباید failure را به success تبدیل کند | PROMPT §19 | M | CI | `if: always()` برای upload، بدون `\|\| true` روی گام تصمیم | بازبینی workflow | DONE | `if: always()` روی آپلود، بدون `|| true` در مرحلهٔ تصمیم |
| R-CICD-08 | Workflow امکان اجرای دستی و اجرای خودکار روی تغییرات مرتبط داشته باشد | PROMPT §19 | S | CI | `workflow_dispatch` + `push`/`pull_request` | بازبینی workflow | DONE | `workflow_dispatch` با ورودی revision + `push`/`pull_request` |

## 8. Architecture, sandboxing, execution environment

| ID | Requirement | Source | Pri | Module | Implementation approach | Verification method | Status | Evidence |
|----|-------------|--------|-----|--------|------------------------|---------------------|--------|----------|
| R-ARCH-01 | معماری ماژولار با Interface مشخص برای هر ماژول | PROMPT §3 | M | all | Protocolهای typing + DI در نقاط توسعه‌پذیر | بازبینی کد | DONE | `SandboxBackend` Protocol · ۱۷ ماژول با رابط مشخص |
| R-ARCH-02 | معماری مستقل از ساختار و نام توابع برنامه‌های هدف | PROMPT §3، SPEC §2 | M | all | هیچ ارجاع hardcode به هدف‌ها | grep در CI | DONE | افزودن cJSON بدون تغییر کد ابزار |
| R-ARCH-03 | ماژول‌های الزامی: Config, Build, Execution, Crash, Patch, Differential, Reproducer, Minimizer, RegressionGen, Hardening, Report, CI, Sandbox | PROMPT §3، Amendment §2 | S | all | یک پکیج به ازای هر ماژول | ساختار پوشه‌ها | DONE | ساختار `src/patch_validator/` |
| R-SBX-01 | تمام آزمایش‌های برنامهٔ آسیب‌پذیر در محیط ایزوله و مجاز اجرا شوند | SPEC §5 p4 | M | SandboxManager | bubblewrap با namespace ایزوله | تست واحد sandbox | DONE | bubblewrap · `test_sandbox.py::TestIsolation` (۷ تست) |
| R-SBX-02 | معماری: یک Docker Container به ازای هر CI Job + یک Sandbox سبک به ازای هر اجرای تست | PROMPT Amendment §1 | M | SandboxManager / CI | ابزار داخل container؛ هر اجرا داخل bwrap | بازبینی workflow + کد | DONE | `Dockerfile` + `SandboxManager` · تأیید اجرا داخل container |
| R-SBX-03 | ابزار نباید به Docker Daemon یا Docker Socket وابسته باشد | PROMPT Amendment §1 | M | SandboxManager | هیچ فراخوانی Docker API در کد ابزار | grep در CI | DONE | هیچ ارجاعی به Docker API/socket در `src/` |
| R-SBX-04 | Sandbox باید filesystem, process, network isolation + CPU/mem limit + timeout + cleanup + جمع‌آوری stdout/stderr + تشخیص exit/signal را مدیریت کند | PROMPT Amendment §2 | M | SandboxManager | bwrap flags + `prlimit`/`setrlimit` + `subprocess` | تست واحد برای هر قابلیت | DONE | `test_sandbox.py::TestIsolation` + `TestLimits` + `TestLifecycle` |
| R-SBX-05 | محدودیت `prlimit` دقیق RAM را تضمین نمی‌کند؛ این محدودیت مستند شود | PROMPT Amendment §2 | M | docs/LIMITATIONS | یادداشت صریح | بازبینی مستندات | DONE | `docs/LIMITATIONS.md §5.1` |
| R-SBX-06 | پیش از اجرای تست‌ها، قابلیت استفاده از Sandbox داخل Docker بررسی شود (userns, mount/pid ns, seccomp, cgroups v2, permissions) | PROMPT Amendment §3 | M | SandboxManager / `doctor` | دستور `doctor` با probeهای واقعی | اجرای `doctor` | DONE | `BubblewrapSandboxBackend.probe` با ۵ بررسی · `patch-validator doctor` |
| R-SBX-07 | اگر sandbox قابل اجرا نبود: علت تشخیص داده شود، راهکار با حداقل دسترسی پیشنهاد شود، privileged mode پیش‌فرض نشود، و هیچ تست آسیب‌پذیری بدون ایزوله‌سازی اجرا نشود | PROMPT Amendment §3 | M | SandboxManager | خطای `SandboxUnavailable` ⇒ exit 30 | تست با sandbox غیرفعال | DONE | `SandboxUnavailable` → ۳۰ · `test_...::test_an_unavailable_sandbox_still_produces_a_readable_report` |
| R-SBX-08 | ثبت Docker Image Digest، Sandbox Backend، Sandbox Config، Resource Limits، Env، Binary Hash، Execution Command برای هر تست | PROMPT Amendment §5 | S | Report | فیلدهای `environment` در هر نتیجه | بازبینی JSON | DONE | `util/environment.py` · بخش `environment` در هر manifest |
| R-SBX-09 | تست‌های تأیید sandbox: اجرا داخل Docker، جلوگیری از دسترسی خارج، نبود شبکه، timeout، محدودیت منابع، پاک‌سازی process، اجرای متوالی مستقل، حفظ شواهد پس از حذف sandbox | PROMPT Amendment §6 | M | tests/ | مجموعه تست اختصاصی | اجرای pytest | DONE | `tests/test_sandbox.py` — ۱۹ تست، یکی به ازای هر بند فهرست تأیید |
| R-BUILD-01 | دو build مستقل (Release و Sanitized) برای هر نسخه | SPEC §3.2، PROMPT §6 | M | BuildManager | دو مجموعه flag از config | وجود ۴ باینری | DONE | چهار باینری در هر اجرا · `runs/*/builds/` |
| R-BUILD-02 | ثبت compiler, version, flags, linker flags, build command, source commit, timestamp, result, binary path, SHA256 | PROMPT §6 | M | BuildManager | `BuildRecord` dataclass | بازبینی JSON | DONE | `BuildRecord` با ۱۸ فیلد |
| R-BUILD-03 | خطای ساخت ⇒ exit 30 و نه یافتهٔ امنیتی | SPEC §3.5، PROMPT §6 | M | BuildManager | استثنای `BuildError` | تست با منبع خراب | DONE | `BuildError` → ۳۰، هرگز یافته |
| R-BUILD-04 | buildهای حساس به اطلاعات دیباگ (`-g`) برای symbolization | PROMPT §6 | S | BuildManager | `-g` در هر دو حالت | بررسی stack trace نمادین | DONE | `-g` در هر دو mode · فریم‌های نمادین در شواهد |

## 9. Documentation and delivery (۵ نمره)

| ID | Requirement | Source | Pri | Module | Implementation approach | Verification method | Status | Evidence |
|----|-------------|--------|-----|--------|------------------------|---------------------|--------|----------|
| R-DOC-01 | فایل‌های الزامی: README، INSTALLATION، ARCHITECTURE، CONFIGURATION، TESTING، SECURITY_ANALYSIS، PATCH_CORRELATION، REGRESSION_TESTING، CI_CD، LIMITATIONS، DEFENSE_GUIDE | PROMPT §23 | S | docs/ | نوشتن همه | وجود فایل‌ها | DONE | همهٔ ۱۱ فایل در `docs/` + `README.md` |
| R-DOC-02 | README شامل معرفی، هدف، معماری، پیش‌نیاز، نصب، اجرای سریع، افزودن هدف، اجرای تست، مشاهدهٔ گزارش، کدهای خروج، محدودیت‌ها، بازتولید | PROMPT §23 | S | README.md | — | بازبینی | DONE | `README.md` — همهٔ ۱۲ بخش خواسته‌شده |
| R-DOC-03 | مستندسازی محدودیت‌های ابزار به‌صورت صریح | SPEC §3.4، PROMPT §23 | M | docs/LIMITATIONS.md | — | بازبینی | DONE | `docs/LIMITATIONS.md` — ۹ بخش |
| R-DOC-04 | راهنمای دفاع فردی: معماری، توابع مهم، تصمیم‌های طراحی، محدودیت‌ها، نمونه یافتهٔ واقعی، تفسیر شواهد، تغییر کوچک محتمل و روش آزمایش آن | PROMPT §24 | S | docs/DEFENSE_GUIDE.md | چهار بخش برای چهار عضو | بازبینی | DONE | `docs/DEFENSE_GUIDE.md` — چهار عضو با یافتهٔ واقعی |
| R-DOC-05 | پیشنهاد تقسیم کار چهار نفره + تمرین تغییر محدود برای هر عضو | PROMPT §24، SPEC §5 | S | docs/DEFENSE_GUIDE.md | — | بازبینی | DONE | `docs/DEFENSE_GUIDE.md` — تمرین تغییر محدود + روش آزمایش |
| R-DEL-01 | تحویل شامل کد، پیکربندی هدف‌ها، نسخهٔ دقیق هدف‌ها، اسکریپت ساخت، آزمون‌ها، oracleها، بسته‌های بازتولید، ورودی‌های کوچک‌شده، تست‌های رگرسیون تولیدشده، گزارش JSON و خوانا، workflow، Dockerfile، راهنما | SPEC §5، PROMPT §26 | M | repo | — | ساختار نهایی مخزن | DONE | ساختار مخزن · `runs/` به‌عنوان artifact |
| R-DEL-02 | امکان اجرای مستقل (standalone) پروژه | SPEC §6 جدول | M | repo | `pip install -e .` + Dockerfile | اجرای از صفر در محیط تمیز | DONE | `pip install -e .` + `Dockerfile` · `doctor` تأیید محیط |
| R-QA-01 | کد: ماژولار، خوانا، دارای type hint، مدیریت خطا، logging استاندارد، بدون مسیر hardcode | PROMPT §3 | S | all | mypy-friendly + `logging` | بازبینی کد | DONE | type hint در همهٔ ماژول‌ها · `logging` · بدون مسیر hardcode |
| R-QA-02 | ممنوعیت hardcode نتیجهٔ آزمون‌ها یا تصمیم بر اساس نام وصله | SPEC §4، PROMPT §2 | M | all | بازبینی + تست unseen patch | تست روز دفاع شبیه‌سازی‌شده | DONE | `test_no_decision_depends_on_the_patch_identity` |

---

## Conflicts and assumptions

### C-01 — اولویت کدهای خروج
- `SPEC §3.5 p3`: «در صورت همزمانی چند وضعیت، اولویت کد خروج به ترتیب ۳۰، ۱۰، ۲۰، ۴۰ و ۰ است.»
- `PROMPT §15`: «ترتیب اولویت: `0 < 30 < 10 < 20 < 40`».

این دو در مورد جایگاه `40` و `30` ناسازگارند. طبق قانون صفر، **`SPEC` اعمال می‌شود**:
`30 > 10 > 20 > 40 > 0`. این ترتیب در یک ثابت واحد (`EXIT_PRECEDENCE`) متمرکز شده و در
`docs/DESIGN_DECISIONS.md` مستند است.

### C-02 — مراحل غایب در شماره‌گذاری PROMPT
سند PROMPT از مرحلهٔ ۱۹ مستقیماً به ۲۳ و از ۲۴ به ۲۶ می‌پرد (مراحل ۲۰–۲۲ و ۲۵ در سند
وجود ندارند). فرض می‌شود این مراحل حذف شده‌اند و الزام اضافه‌ای ایجاد نمی‌کنند؛ پوشش کامل
بر اساس `SPEC` سنجیده می‌شود.

### C-03 — Toy project در SPEC الزامی نیست
`SPEC §4` دو برنامهٔ مستقل می‌خواهد که **حداقل یکی** واقعی باشد؛ `PROMPT §4` ساخت کامل یک
toy project را الزامی می‌کند. هر دو برآورده می‌شوند: هدف اول toy (ساختهٔ خودمان، برای پوشش
کامل و قطعی چهار سناریو) و هدف دوم پروژهٔ واقعی open-source با CVE و commit رفع واقعی.

### C-04 — ابزار کامپایلر
`clang` در محیط توسعه موجود نیست؛ `gcc 13.3` با `-fsanitize=address,undefined` استفاده می‌شود.
انتخاب کامپایلر از config خوانده می‌شود و hardcode نیست، بنابراین در محیطی با clang بدون تغییر
کد قابل استفاده است.

### C-05 — دامنهٔ symbolization
برای stack trace نمادین، `-g` و `ASAN_SYMBOLIZER_PATH` لازم است. در نبود `llvm-symbolizer`،
ASan از `addr2line` استفاده می‌کند؛ در صورت نبود هر دو، فریم‌ها بدون نام فایل/خط ثبت می‌شوند و
`confidence` همبستگی کاهش می‌یابد. این محدودیت در `docs/LIMITATIONS.md` ثبت است.
