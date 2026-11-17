# patch-validator

**Automated security patch validation and regression testing in CI/CD**

پروژهٔ اول درس امنیت داده و شبکه — دانشگاه صنعتی شریف

---

## مسئله

اعمال یک وصلهٔ امنیتی به‌معنای رفع قطعی آسیب‌پذیری نیست. گاهی وصله فقط ورودی خطاساز
*شناخته‌شده* را مسدود می‌کند و مسیر دیگری به همان نقص باز می‌ماند؛ گاهی آسیب‌پذیری را
برطرف می‌کند ولی رفتار درست برنامه را خراب می‌کند. این ابزار در پایپ‌لاین CI/CD دو پرسش
را با **اجرای واقعی برنامه** — نه تحلیل ایستا — پاسخ می‌دهد:

1. آیا خطای امنیتی که روی نسخهٔ پایه بازتولید می‌شود، پس از وصله همچنان رخ می‌دهد؟
2. آیا وصله رفتار مورد انتظار برنامه را روی ورودی‌های معتبر حفظ کرده است؟

و مهم‌تر: خطاهای مشاهده‌شده را به **تغییرات واقعی کد در diff** پیوند می‌دهد و شواهد
قابل بازتولید تولید می‌کند. «مشاهده نشدن خطا در آزمون‌ها» اثبات نبود آسیب‌پذیری نیست و
ابزار هیچ‌جا چنین ادعایی نمی‌کند.

## نمونهٔ خروجی

```
$ patch-validator validate --config configs/recparse.yaml --patched-revision incomplete-patch

========================================================================
  VULN_REMAINS_OR_NEW_ISSUE  (exit code 10)
========================================================================
  security axis       VULNERABLE
  functional axis     PASS
  analysis complete   COMPLETE

  3 fixed · 3 confirmed security finding(s) · 0 functional regression(s) · 0 gap(s)

  - INCOMPLETE_FIX: STACK_BUFFER_OVERFLOW still reproduces on the patched build
```

این وصله ورودی خطاساز اصلی را مسدود کرده (`FIXED`) ولی مسیر دیگری به همان تابع آسیب‌پذیر
باز مانده است (`INCOMPLETE_FIX`). ابزار هر دو را جداگانه گزارش می‌کند و برای هرکدام
می‌گوید آیا به تغییرات وصله مربوط است یا نه.

## معماری در یک نگاه

```
┌─────────────────── یک Docker container به ازای هر CI Job ───────────────────┐
│                                                                             │
│  patch-validator                                                            │
│      ├── git worktree → base    ─┐                                          │
│      ├── git worktree → patched ─┴→ Build Manager → ۴ باینری                │
│      │                              (base|patched) × (release|sanitized)    │
│      │                                                                      │
│      └── برای هر test case × ۴ باینری:                                       │
│              Sandbox سبک (bubblewrap) ← تنها جایی که کد هدف اجرا می‌شود      │
│                                                                             │
│  artifacts/<run-id>/  logs · crashes · bundles · minimized · report.json    │
└─────────────────────────────────────────────────────────────────────────────┘
```

«یک container به ازای هر CI job، یک sandbox سبک به ازای هر اجرای تست.» ابزار هیچ‌گاه
container نمی‌سازد و به Docker daemon یا socket دسترسی ندارد.

جزئیات کامل: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) ·
تصمیم‌های طراحی: [`docs/DESIGN_DECISIONS.md`](docs/DESIGN_DECISIONS.md)

## پیش‌نیازها

| ابزار | کاربرد |
|-------|--------|
| Python ≥ 3.11 | خود ابزار |
| `gcc` یا `clang` | ساخت برنامه‌های هدف |
| `cmake`, `make` | سیستم ساخت هدف‌ها |
| `bubblewrap` | ایزوله‌سازی هر اجرای تست |
| `util-linux` (`prlimit`) | محدودیت تعداد پراسس داخل sandbox |
| `binutils` (`readelf`) | تحلیل سخت‌سازی باینری |
| `git` | خواندن revisionها و diff |

```bash
sudo apt install -y bubblewrap util-linux binutils build-essential cmake git python3-venv
```

## نصب و اجرای سریع

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

patch-validator doctor                     # بررسی اینکه محیط آماده است
bash targets/recparse/bootstrap.sh         # ساخت مخزن هدف اسباب‌بازی

patch-validator validate --config configs/recparse.yaml
echo "exit code: $?"
```

راهنمای کامل نصب، از جمله اجرای داخل Docker: [`docs/INSTALLATION.md`](docs/INSTALLATION.md)

## اهداف تحویل‌شده

| هدف | نوع | آسیب‌پذیری | پیکربندی |
|------|-----|------------|-----------|
| [`recparse`](targets/recparse/) | اسباب‌بازی (ساختهٔ ما) | stack buffer overflow در تابع کپی مشترک | [`configs/recparse.yaml`](configs/recparse.yaml) |
| [`cjson`](targets/cjson/) | **پروژهٔ واقعی** ([cJSON](https://github.com/DaveGamble/cJSON)) | heap buffer over-read در `parse_object()`، commit رفع `3ef4e4e` | [`configs/cjson.yaml`](configs/cjson.yaml) |

هدف اسباب‌بازی چهار نسخه دارد تا هر چهار سناریوی ارزیابی به‌صورت قطعی پوشش داده شوند:

```bash
patch-validator validate --config configs/recparse.yaml --patched-revision correct-patch       # 0
patch-validator validate --config configs/recparse.yaml --patched-revision incomplete-patch    # 10
patch-validator validate --config configs/recparse.yaml --patched-revision regression-patch    # 20
```

هدف واقعی به دریافت منبع از شبکه نیاز دارد:

```bash
bash targets/cjson/bootstrap.sh
patch-validator validate --config configs/cjson.yaml     # 0
```

## افزودن برنامهٔ هدف جدید

**بدون تغییر هیچ خطی از کد ابزار.** یک فایل YAML کافی است:

```yaml
schema_version: 1
target:
  name: myprogram
  repo_path: targets/myprogram/repo
  base_revision: v1.0
  patched_revision: fix-cve-2026-1234
builds:
  - mode: release
    cflags: "-O2 -g"
    commands: [["cmake", "-S", "{source}", "-B", "{build_dir}"], ["cmake", "--build", "{build_dir}"]]
    binary_path: "{build_dir}/myprogram"
  - mode: sanitized
    cflags: "-O1 -g -fsanitize=address,undefined"
    ldflags: "-fsanitize=address,undefined"
    commands: [...]
    binary_path: "{build_dir}/myprogram"
input:
  method: file          # stdin | file | argv
  argv: ["{input_file}"]
tests:
  - id: valid_basic
    category: valid
    input: {path: targets/myprogram/tests/basic.bin}
    oracle:
      source: specification
      input_validity: valid
      exit_code: 0
      stdout: {match: exact, value: "expected output\n"}
```

راهنمای کامل گزینه‌ها: [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md)

## دستورات

| دستور | کار |
|-------|-----|
| `validate` | اجرای کامل: ساخت، اجرا، تحلیل، همبستگی، کوچک‌سازی، گزارش، کد خروج |
| `check-config` | اعتبارسنجی فایل پیکربندی و resolve کردن revisionها |
| `build` | فقط ساخت هر چهار باینری |
| `test` | ساخت و اجرای ماتریس، بدون تحلیل |
| `hardening` | مقایسهٔ محافظت‌های باینری میان دو نسخه |
| `regression --suite <s>` | بازاجرای تست‌های رگرسیون تولیدشده در یک اجرای قبلی |
| `report --run <dir>` | نمایش دوبارهٔ گزارش یک اجرای قبلی |
| `reproduce <bundle>` | بازپخش یک بستهٔ بازتولید |
| `doctor` | بررسی اینکه محیط اجرا آماده است |

`--patched-revision` روی همهٔ دستورها کار می‌کند و باعث می‌شود یک پیکربندی بتواند
**وصله‌ای را که هرگز ندیده** اعتبارسنجی کند: همان پایه، همان آزمون‌ها، همان Oracleها.

## کدهای خروج

| کد | نام | معنا |
|----|-----|------|
| `0` | `PASS` | خطای پایه بازتولید شد، روی نسخهٔ وصله‌شده مشاهده نشد، هیچ یافتهٔ امنیتی تأییدشدهٔ دیگری نیست، همهٔ آزمون‌های عملکردی موفق، و همهٔ بررسی‌های الزامی کامل |
| `10` | `VULN_REMAINS / NEW_ISSUE` | خطای قبلی همچنان رخ می‌دهد، یا خطای حافظه‌ای دیگری با شواهد معتبر تأیید شده |
| `20` | `FUNC_REGRESSION` | ورودی‌ای که روی پایه درست بود، روی نسخهٔ وصله‌شده مشخصات را نقض می‌کند |
| `30` | `BUILD_OR_CONFIG_ERROR` | ساخت ناموفق، پیکربندی نامعتبر، یا محیط اجرا غیرقابل‌استفاده |
| `40` | `INCONCLUSIVE` | بررسی الزامی ناقص، یا شواهد برای داوری کافی نیست |

**اولویت در همزمانی چند وضعیت: `30 > 10 > 20 > 40 > 0`**

دقت کنید `PASS` مشروط به **بازتولید شدن خطا روی نسخهٔ پایه** است. اگر هیچ خطایی روی پایه
دیده نشود، نتیجه `40` است نه `0` — چون چیزی وجود ندارد که نشان دهد وصله آن را رفع کرده.

## مشاهدهٔ گزارش

هر اجرا یک پوشه تولید می‌کند:

```
runs/<run-id>/
  report.json          گزارش ساختاریافته، اعتبارسنجی‌شده با JSON Schema
  report.md            خلاصهٔ خوانا برای توسعه‌دهنده
  patch.diff           diff واقعی میان دو revision
  builds/              لاگ و فراداده هر چهار build
  exec/<test>/<ver>.<mode>/   stdout، stderr و فراداده هر اجرا
  bundles/<finding>/   بستهٔ بازتولید + REPRODUCE.md + لاگ ≥۳ بازپخش
  minimized/<finding>/ ورودی کوچک‌شده و ردّ تلاش‌های ddmin
  regression/          تست‌های رگرسیون تولیدشده
  hardening/           وضعیت NX/PIE/RELRO/Canary در دو نسخه
```

هر یافته در `report.json` فیلد `evidence_refs` دارد که به مسیرهای همین پوشه اشاره می‌کند.
هیچ ادعایی بدون شاهد روی دیسک وجود ندارد.

```bash
patch-validator report --run runs/<run-id> --format summary
patch-validator report --run runs/<run-id> --format markdown
```

## بازتولید یک یافته

```bash
patch-validator reproduce runs/<run-id>/bundles/<finding>/
```

هر بسته شامل ورودی اصلی و کوچک‌شده، commit hash، مسیر و SHA256 باینری، نسخه و پرچم‌های
کامپایلر، دستورهای ساخت، متغیرهای محیطی، محدودیت منابع، پیکربندی sandbox، گزارش خطا و
نتیجهٔ جداگانهٔ هر بازپخش است. یافته‌ای که در هر سه بازپخش یکسان نباشد صریحاً
**`flaky`** علامت می‌خورد و از آن تست رگرسیون ساخته نمی‌شود.

## اجرای تست‌ها

```bash
pytest -q                    # ۱۶۳ تست
pytest -q -m "not slow"      # بدون اجراهای سرتاسری
pytest -q -m sandbox         # فقط تأیید ایزوله‌سازی
```

جزئیات: [`docs/TESTING.md`](docs/TESTING.md)

## محدودیت‌ها

ابزار عمداً در مواردی سکوت یا اعلام عدم قطعیت می‌کند. چند نمونه:

- اثبات **نبود** آسیب‌پذیری ممکن نیست؛ نتیجه فقط دربارهٔ ورودی‌های آزمون‌شده است.
- وجود `PIE` اثبات فعال بودن ASLR در زمان اجرا نیست.
- وجود شواهد canary به‌معنای محافظت همهٔ توابع نیست.
- بدون نمادگذاری (symbolization)، همبستگی با diff از `WEAK` فراتر نمی‌رود.
- `prlimit` محدودیت دقیق RAM را تضمین نمی‌کند.

فهرست کامل و صریح: [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md)

## مستندات

| فایل | محتوا |
|------|-------|
| [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) | ماتریس ردیابی ۸۰ الزام با شواهد |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | معماری، ماژول‌ها، جدول‌های تصمیم |
| [`docs/DESIGN_DECISIONS.md`](docs/DESIGN_DECISIONS.md) | ۱۳ ADR با دلیل و پیامد |
| [`docs/INSTALLATION.md`](docs/INSTALLATION.md) | نصب، Docker، رفع اشکال محیط |
| [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) | مرجع کامل فایل پیکربندی |
| [`docs/SECURITY_ANALYSIS.md`](docs/SECURITY_ANALYSIS.md) | تشخیص و طبقه‌بندی خطا |
| [`docs/PATCH_CORRELATION.md`](docs/PATCH_CORRELATION.md) | پیوند دادن خطا به diff |
| [`docs/REGRESSION_TESTING.md`](docs/REGRESSION_TESTING.md) | کوچک‌سازی، بازتولید، تولید تست |
| [`docs/TESTING.md`](docs/TESTING.md) | مجموعه آزمون خود ابزار |
| [`docs/CI_CD.md`](docs/CI_CD.md) | پایپ‌لاین و تفسیر کدهای خروج |
| [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md) | محدودیت‌های صریح |
| [`docs/DEFENSE_GUIDE.md`](docs/DEFENSE_GUIDE.md) | تقسیم کار و راهنمای دفاع فردی |
