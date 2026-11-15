# ARCHITECTURE

> Requirements covered: `R-ARCH-01..03`, `R-SBX-02..03`, `R-SCOPE-08`, `R-DYN-08`.

## 1. Design goals

1. **Evidence first.** هیچ وضعیتی بدون شواهد اجرای واقعی تولید نمی‌شود. هر یافته یک یا چند
   `evidence_ref` به فایل لاگ/خروجی روی دیسک دارد.
2. **Target agnostic.** هیچ نام فایل، نام تابع، یا شناسهٔ وصلهٔ مربوط به یک هدف خاص در کد ابزار
   وجود ندارد. افزودن هدف جدید = افزودن یک YAML.
3. **Separation of axes.** امنیت، عملکرد، و کامل‌بودن تحلیل سه محور مستقل‌اند که تا آخرین لحظه
   با هم ترکیب نمی‌شوند؛ خروجی JSON هر سه را جداگانه نگه می‌دارد.
4. **Deterministic matrix.** هر test case روی ماتریس کامل `{base, patched} × {release, sanitized}`
   با تنظیمات یکسان اجرا می‌شود و نتایج هرگز میان build modeها مخلوط نمی‌شوند.
5. **Isolation by default.** هر اجرای باینری هدف داخل یک sandbox سبک انجام می‌شود. نبودِ
   sandbox یک خطای پیکربندی (exit 30) است، نه دلیلی برای اجرای بدون ایزوله‌سازی.

## 2. Execution topology

```
┌──────────────────────────────────────── CI Job (1 Docker container) ───────────────────────────────┐
│                                                                                                    │
│   patch-validator (Python 3.11+)                                                                   │
│        │                                                                                           │
│        ├── git worktree ──► /work/base      ──► BuildManager ──► base.release   base.sanitized     │
│        ├── git worktree ──► /work/patched   ──► BuildManager ──► patched.release patched.sanitized │
│        │                                                                                           │
│        └── for each test case × 4 binaries:                                                        │
│                 SandboxManager.spawn()                                                             │
│                      └── bubblewrap: new mount/pid/net/ipc/uts/user ns                             │
│                           + rlimits + timeout + process-group cleanup                              │
│                           └── execve(target_binary)   ← the only place target code runs            │
│                                                                                                    │
│   artifacts/<run-id>/   logs · crashes · bundles · minimized · report.json · report.md             │
└────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

قاعدهٔ اصلاحیهٔ معماری: **یک Docker container به ازای هر CI job، یک sandbox سبک به ازای هر اجرای
تست**. ابزار هیچ‌گاه Docker container نمی‌سازد و به Docker socket/daemon دسترسی ندارد
(`R-SBX-03`).

## 3. Module map

| # | Module | Package | Public interface | Responsibility |
|---|--------|---------|------------------|----------------|
| 1 | Configuration Manager | `patch_validator.config` | `load_config(path) -> ValidationConfig` | خواندن YAML، اعتبارسنجی schema، نرمال‌سازی مسیرها، مقادیر پیش‌فرض |
| 2 | VCS Gateway | `patch_validator.vcs` | `GitRepo.resolve/worktree/diff` | resolve کردن revision، ساخت worktree، تولید diff خام |
| 3 | Build Manager | `patch_validator.build` | `BuildManager.build(rev, mode) -> BuildRecord` | ساخت دو نسخه × دو حالت، ثبت کامل فراداده و SHA256 |
| 4 | Sandbox Manager | `patch_validator.sandbox` | `SandboxManager.run(spec) -> SandboxResult` | ایزوله‌سازی، محدودیت منابع، timeout، cleanup، probe قابلیت‌ها |
| 5 | Execution Engine | `patch_validator.execution` | `ExecutionEngine.run_case(...) -> ExecutionResult` | آماده‌سازی ورودی (stdin/file/argv)، اجرا، ثبت خروجی خام |
| 6 | Crash Analyzer | `patch_validator.analysis.crash` | `CrashAnalyzer.analyze(result) -> CrashInfo` | parse سیگنال/ASan/UBSan، stack trace، crash signature |
| 7 | Oracle | `patch_validator.analysis.oracle` | `OracleEvaluator.evaluate(case, result) -> OracleVerdict` | مقایسهٔ رفتار با مشخصات مستقل (نه با نسخهٔ وصله‌شده) |
| 8 | Differential Tester | `patch_validator.analysis.differential` | `DifferentialTester.compare(...) -> list[Finding]` | مقایسهٔ متناظر base/patched در هر build mode |
| 9 | Patch Analyzer | `patch_validator.analysis.patch` | `PatchAnalyzer.correlate(finding) -> Correlation` | parse diff، نگاشت خط→تابع، تطبیق stack trace، سطح اطمینان |
| 10 | Testcase Minimizer | `patch_validator.minimize` | `Minimizer.minimize(input, predicate) -> MinimizationResult` | ddmin بایت‌محور با predicate مبتنی بر crash signature |
| 11 | Reproducer Manager | `patch_validator.reproducer` | `ReproducerManager.create/replay` | ساخت bundle کامل، بازپخش ≥۳ بار، تشخیص flakiness |
| 12 | Regression Generator | `patch_validator.regression` | `RegressionGenerator.generate(finding)` | تولید تست رگرسیون اجراشدنی از ورودی کوچک‌شده |
| 13 | Hardening Analyzer | `patch_validator.analysis.hardening` | `HardeningAnalyzer.analyze(path) -> HardeningReport` | NX/PIE/RELRO/Canary از شواهد واقعی ELF |
| 14 | Classification Engine | `patch_validator.classify` | `classify(run) -> Classification` | ترکیب سه محور، تعیین وضعیت نهایی و exit code |
| 15 | Report Generator | `patch_validator.report` | `write_json/write_markdown` | گزارش JSON نسخه‌دار + خلاصهٔ خوانا از یک مدل داده |
| 16 | Pipeline | `patch_validator.pipeline` | `Pipeline.run(stages)` | ارکستراسیون مراحل و مدیریت artifact |
| 17 | CLI | `patch_validator.cli` | `main(argv) -> int` | زیردستورها و exit code واقعی پروسه |

وابستگی‌ها یک‌طرفه‌اند: `cli → pipeline → {config, build, execution, analysis, …} → {sandbox, vcs, util}`.
هیچ ماژول تحلیلی به `cli` یا `pipeline` وابسته نیست، بنابراین همه مستقل قابل تست‌اند.

## 4. Core data model

```
ValidationConfig
 ├─ TargetSpec        name, language, source_path, base_revision, patched_revision
 ├─ BuildSpec[]       mode(release|sanitized), compiler, cflags, ldflags, commands, binary_path
 ├─ InputSpec         method(stdin|file|argv), argv_template, file_arg_template
 ├─ TestCase[]        id, category, role, input(inline|file), oracle(OracleSpec|None), timeout_override
 ├─ OracleSpec        expected_exit, expected_stdout(exact|regex|contains), expected_stderr, semantics, source
 ├─ Limits            timeout_s, memory_mb, cpu_s, max_processes, max_output_bytes
 └─ SandboxSpec       backend, network, allow_paths[], tmpfs[]

RunRecord
 ├─ run_id, started_at, tool_version, schema_version, environment
 ├─ BuildRecord[]     (version, mode) → compiler meta, flags, sha256, status, log_ref
 ├─ ExecutionResult[] (test_id, version, mode) → exit, signal, stdout/stderr refs, duration, hashes
 ├─ CrashInfo[]       error_type, detection_mechanism, location, frames, signature, confidence
 ├─ Finding[]         security / functional findings with evidence_refs
 ├─ Correlation[]     finding ↔ diff hunk, status, confidence
 ├─ Reproduction[]    bundle_ref, replays[], stability
 ├─ Minimization[]    original/minimized size, reduction, verification
 ├─ HardeningReport   per-protection base/patched/change_status
 └─ Classification    security_status, functional_status, completeness_status, final, exit_code
```

## 5. Decision tables

### 5.1 Per-test security axis (within one build mode)

| base outcome | patched outcome | signature equal | → finding |
|---|---|---|---|
| security event | clean | — | `FIXED` |
| security event | security event | yes | `INCOMPLETE_FIX` |
| security event | security event | no | `INCOMPLETE_FIX` (confidence ≤ MEDIUM, signature shift recorded) |
| clean | security event | — | `NEW_ISSUE` (confidence از همبستگی با diff) |
| clean | clean | — | — |
| timeout / resource limit | * | — | خارج از محور امنیت؛ ثبت در محور کامل‌بودن (`R-DYN-07`) |

«security event» = crash با سیگنال حافظه‌ای، یا گزارش ASan/UBSan. صرف exit code غیرصفر
security event نیست (`R-DYN-14`).

### 5.2 Per-test functional axis (release build is authoritative)

| base vs oracle | patched vs oracle | → finding |
|---|---|---|
| MATCH | MATCH | — |
| MATCH | MISMATCH | `FUNCTIONAL_REGRESSION` |
| MISMATCH | MATCH | `FUNCTIONAL_FIX` (اطلاعاتی) |
| MISMATCH | MISMATCH | `PRE_EXISTING_DEFECT` (اطلاعاتی) |
| MISMATCH | MISMATCH ولی رفتار متفاوت از base | `INCONCLUSIVE` note — اعلام قطعی regression ممنوع (`R-CORE-13`) |
| oracle تعریف‌نشده | — | محور کامل‌بودن: `missing_oracle` |

### 5.3 Final classification and exit code

```
precedence = [30, 10, 20, 40, 0]          # SPEC §3.5 — see docs/REQUIREMENTS.md C-01

30 BUILD_OR_CONFIG_ERROR  ← هر خطای build/config/sandbox-unavailable
10 VULN_REMAINS|NEW_ISSUE ← ≥1 یافتهٔ امنیتی با شواهد کافی روی نسخهٔ وصله‌شده
20 FUNC_REGRESSION        ← ≥1 FUNCTIONAL_REGRESSION اثبات‌شده (base مطابق oracle بوده)
40 INCONCLUSIVE           ← بررسی الزامی ناقص، شواهد ناکافی، یافتهٔ ناپایدار،
                            یا خطای پایه بازتولید نشده
 0 PASS                   ← خطای پایه بازتولید شد ∧ روی patched مشاهده نشد ∧
                            هیچ یافتهٔ امنیتی تأییدشدهٔ دیگری نیست ∧ همهٔ آزمون‌های
                            عملکردی موفق ∧ همهٔ بررسی‌های الزامی کامل
```

**Mandatory checks** (نقض هرکدام ⇒ `completeness = INCOMPLETE` ⇒ حداقل exit 40):

1. همهٔ buildهای پیکربندی‌شده موفق بوده‌اند.
2. هر test case روی هر ۴ ترکیب اجرا شده یا دلیل عدم اجرا ثبت شده است.
3. هر یافتهٔ امنیتی ≥۳ بار بازپخش شده و پایدار است.
4. تحلیل hardening روی هر دو release build اجرا شده است.
5. برای هر یافتهٔ امنیتی تلاش همبستگی با diff انجام شده است.
6. هر test case با `oracle` تعریف‌شده ارزیابی شده است.
7. خطای پایه (حداقل یک security event روی base) بازتولید شده است.

## 6. Sandbox contract

```python
class SandboxBackend(Protocol):
    name: str
    def probe(self) -> ProbeReport: ...
    def run(self, spec: SandboxSpec) -> SandboxResult: ...
```

`BubblewrapSandboxBackend` پیاده‌سازی اصلی است:

- `--unshare-user --unshare-pid --unshare-net --unshare-ipc --unshare-uts`
- `--ro-bind` فقط برای مسیرهای لازم (باینری، کتابخانه‌ها، symbolizer)، `--bind` فقط برای
  پوشهٔ کاری تست، `--tmpfs /tmp`, `--proc /proc`, `--dev /dev`
- `--die-with-parent --new-session`
- محدودیت منابع با `resource.setrlimit` در `preexec_fn`: `RLIMIT_AS`, `RLIMIT_CPU`,
  `RLIMIT_NPROC`, `RLIMIT_FSIZE`, `RLIMIT_CORE=0`
- timeout با `subprocess` + کشتن کل process group

`SandboxManager.probe()` پیش از اجرای تست‌ها اجرا می‌شود و در صورت نبود قابلیت،
`SandboxUnavailable` با علت دقیق و راهکار حداقلی تولید می‌کند (`R-SBX-06/07`).

## 7. Artifact layout

```
artifacts/<run-id>/
  config.resolved.yaml
  builds/<version>.<mode>/{build.log, meta.json}
  exec/<test-id>/<version>.<mode>/{stdout.bin, stderr.bin, meta.json}
  crashes/<finding-id>/{crash.txt, input.bin, signature.txt}
  bundles/<finding-id>/{manifest.json, input.bin, minimized.bin, replays/*.json, REPRODUCE.md}
  minimized/<finding-id>/{minimized.bin, trace.json}
  regression/<finding-id>/test_<id>.yaml
  hardening/{base.json, patched.json, diff.json}
  report.json
  report.md
```

همهٔ `evidence_ref`ها مسیرهای نسبی داخل همین پوشه‌اند تا بسته قابل انتقال باشد.
