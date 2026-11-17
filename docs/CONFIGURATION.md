# CONFIGURATION

مرجع کامل فایل پیکربندی هدف. **افزودن یک برنامهٔ هدف جدید فقط به یک فایل YAML نیاز دارد
و هیچ تغییری در کد ابزار لازم نیست** (`R-SCOPE-08`).

پیکربندی پیش از هر کاری با JSON Schema اعتبارسنجی می‌شود، بنابراین یک غلط تایپی به کد
خروج ۳۰ با پیام دقیق تبدیل می‌شود، نه به شکست مرموز در میانهٔ build.

```bash
patch-validator check-config --config configs/myprogram.yaml
```

## ساختار کلی

```yaml
schema_version: 1          # الزامی، فعلاً فقط 1
base_dir: ".."             # ریشهٔ مسیرهای نسبی؛ پیش‌فرض: پوشهٔ همین فایل

target:    {...}           # الزامی
builds:    [...]           # الزامی، حداقل یکی، و حتماً یک mode: release
input:     {...}           # الزامی
tests:     [...]           # الزامی، حداقل یکی

limits:         {...}      # اختیاری
sandbox:        {...}      # اختیاری
minimization:   {...}      # اختیاری
reproduction:   {...}      # اختیاری
```

## `target`

```yaml
target:
  name: myprogram                       # الزامی
  description: >-                       # اختیاری، در گزارش می‌آید
    توضیح کوتاه برنامه و نقصی که بررسی می‌شود
  language: c                           # c | c++ (پیش‌فرض c)
  repo_path: targets/myprogram/repo     # الزامی، باید مخزن git باشد
  source_subdir: "."                    # زیرپوشه‌ای که build از آن شروع می‌شود
  base_revision: v1.0                   # الزامی: شاخه، تگ یا هش
  patched_revision: fix-cve-2026-1234   # الزامی
```

هر دو revision بلافاصله به هش کامل commit تبدیل می‌شوند و همان هش در گزارش می‌آید، پس
گزارش به شاخه‌ای که ممکن است بعداً جابه‌جا شود وابسته نیست.

اگر هر دو به یک commit برسند، ابزار رد می‌کند: وصله‌ای برای اعتبارسنجی وجود ندارد.

هر دو را می‌توان از خط فرمان بازنویسی کرد:

```bash
patch-validator validate --config configs/myprogram.yaml --patched-revision some-other-branch
```

## `builds`

حداقل یک build با `mode: release` الزامی است (محور عملکرد روی آن داوری می‌شود). نبودِ
`sanitized` هشدار تولید می‌کند، چون خطاهایی که release build را از پا درنمی‌آورند دیده
نخواهند شد.

```yaml
builds:
  - mode: release                       # release | sanitized
    compiler: gcc
    cflags: "-O2 -g -fno-omit-frame-pointer"
    ldflags: ""
    commands:
      - ["cmake", "-S", "{source}", "-B", "{build_dir}",
         "-DCMAKE_C_COMPILER={compiler}",
         "-DCMAKE_C_FLAGS={cflags}"]
      - ["cmake", "--build", "{build_dir}", "--parallel", "{jobs}"]
    binary_path: "{build_dir}/myprogram"
    env: {}                             # متغیرهای محیطی زمان ساخت

  - mode: sanitized
    compiler: gcc
    cflags: "-O1 -g -fno-omit-frame-pointer -fno-common -fsanitize=address,undefined"
    ldflags: "-fsanitize=address,undefined"
    commands: [...]
    binary_path: "{build_dir}/myprogram"
```

### قالب‌های مجاز در `commands` و `binary_path`

| قالب | مقدار |
|------|-------|
| `{source}` | ریشهٔ worktree این نسخه، به‌علاوهٔ `source_subdir` |
| `{build_dir}` | پوشهٔ ساخت اختصاصی این (نسخه، mode) |
| `{compiler}` | مقدار `compiler` |
| `{cflags}` | مقدار `cflags` |
| `{ldflags}` | مقدار `ldflags` |
| `{jobs}` | تعداد CPUهای در دسترس |
| `{base_dir}` | ریشهٔ مسیرهای نسبی؛ برای ارجاع به فایل‌هایی که خود پیکربندی می‌آورد (مثل harness) |

قالب ناشناخته پیش از اجرای هر دستوری خطا می‌دهد و فهرست قالب‌های معتبر را چاپ می‌کند.

### نکتهٔ مهم دربارهٔ پرچم‌ها

`{cflags}` و `{ldflags}` **فهرست پرچم** هستند. اگر یک آرگومان **دقیقاً** برابر یکی از
این دو قالب باشد، به چند آرگومان بسط می‌یابد:

```yaml
- ["gcc", "{cflags}", "-o", "{build_dir}/app", "{source}/a.c"]
#   →  gcc -O2 -g -fsanitize=address -o /build/app /src/a.c
```

اگر قالب داخل یک آرگومان بزرگ‌تر باشد، یک آرگومان می‌ماند:

```yaml
- ["cmake", "-DCMAKE_C_FLAGS={cflags}"]
#   →  cmake -DCMAKE_C_FLAGS=-O2 -g -fsanitize=address
```

هیچ قالب دیگری تقسیم نمی‌شود؛ مسیری که فاصله دارد همیشه یک آرگومان می‌ماند.

**هیچ shellی درگیر نیست.** دستورها فهرست argv هستند. اگر دستور را به‌صورت رشته بنویسید،
**پیش از** جایگذاری با قواعد POSIX تقسیم می‌شود.

### کتابخانه‌ها و harness

اگر هدف یک کتابخانه است (برنامهٔ اجرایی ندارد)، یک harness کوچک بنویسید و آن را خارج از
مخزن هدف نگه دارید تا تنها متغیر میان دو build، خود کد هدف باشد:

```yaml
commands:
  - ["{compiler}", "{cflags}", "-I{source}",
     "-o", "{build_dir}/cli",
     "{base_dir}/targets/mylib/harness/cli.c",
     "{source}/mylib.c",
     "{ldflags}"]
```

نمونهٔ کامل: [`configs/cjson.yaml`](../configs/cjson.yaml)

## `input`

```yaml
input:
  method: file              # stdin | file | argv
  argv: ["{input_file}"]    # آرگومان‌هایی که بعد از مسیر باینری می‌آیند
  filename: input.bin       # نام فایل ورودی داخل sandbox (فقط برای method: file)
```

| روش | ورودی چطور می‌رسد | قالب لازم |
|-----|---------------------|------------|
| `stdin` | به‌صورت بایت روی ورودی استاندارد | — |
| `file` | در پوشهٔ کاری sandbox نوشته می‌شود | `{input_file}` باید در `argv` باشد |
| `argv` | به‌عنوان یک آرگومان متنی | `{input_arg}` باید در `argv` باشد |

قالب‌های در دسترس: `{input_file}`، `{input_arg}`، `{binary}`، `{workdir}`.

روش `argv` نمی‌تواند ورودی حاوی بایت `NUL` را حمل کند و ابزار این را صریحاً خطا می‌دهد.

## `tests`

```yaml
tests:
  - id: valid_basic                     # یکتا، الگوی [A-Za-z0-9_.-]+
    category: valid                     # valid | boundary | invalid | security
    note: توضیح اختیاری که در گزارش می‌آید
    timeout_s: 30                       # بازنویسی timeout برای همین تست
    input:                              # دقیقاً یکی از path/text/base64
      path: targets/myprogram/tests/basic.bin
    oracle: {...}                       # اختیاری ولی قویاً توصیه‌شده
```

`category` فقط فراداده است و هیچ تصمیمی را تعیین نمی‌کند؛ تصمیم‌ها فقط از شواهد اجرا
می‌آیند. به همین دلیل یک وصلهٔ ناشناخته هم درست ارزیابی می‌شود.

سه شکل ورودی:

```yaml
input: {path: targets/x/tests/a.bin}    # فایل
input: {text: "hello world"}            # متن درون‌خطی
input: {base64: "SGVsbG8="}             # باینری درون‌خطی
```

## `oracle`

رفتاری که یک پیاده‌سازی **درست** باید داشته باشد. باید از مشخصات یا مستندات هدف استخراج
شود، **نه از خروجی نسخهٔ وصله‌شده**.

```yaml
oracle:
  source: specification       # specification | upstream_docs |
                              # reference_test_suite | instructor_approved
  input_validity: valid       # valid | boundary | invalid
  instructor_approved: pending # yes | no | pending
  exit_code: 0                # عدد یا null (یعنی بی‌اهمیت)
  stdout:
    match: exact              # exact | contains | regex | absent | ignore
    value: "expected output\n"
  stderr:
    match: absent
  semantics: توضیح انسانی از قرارداد رفتاری
```

| `match` | معنا |
|---------|------|
| `exact` | خروجی دقیقاً برابر `value` |
| `contains` | `value` زیررشتهٔ خروجی است |
| `regex` | الگو با flagهای MULTILINE و DOTALL جست‌وجو می‌شود |
| `absent` | خروجی باید خالی باشد |
| `ignore` | بررسی نشود (پیش‌فرض) |

خاتمه با سیگنال، انتظار `exit_code` را نقض می‌کند ولی در گزارش جداگانه از «کد خروج
اشتباه» نمایش داده می‌شود.

تست بدون `oracle` در محور عملکرد شرکت نمی‌کند و با `MISSING_ORACLE` در محور
کامل‌بودن تحلیل ثبت می‌شود؛ ولی همچنان اجرا می‌شود و در محور امنیت شرکت دارد.

## `limits`

```yaml
limits:
  timeout_s: 10             # پیش‌فرض 10
  memory_mb: 1024           # پیش‌فرض 1024
  cpu_s: 10                 # پیش‌فرض 10
  max_processes: 64         # پیش‌فرض 64
  max_output_bytes: 1048576 # پیش‌فرض 1 MiB
  max_file_size_mb: 64      # پیش‌فرض 64
```

عبور از timeout یا محدودیت منابع **هرگز** به‌عنوان آسیب‌پذیری طبقه‌بندی نمی‌شود؛ در محور
کامل‌بودن تحلیل ثبت می‌گردد.

برای buildهای sanitized، `memory_mb` از طریق `hard_rss_limit_mb` خود ASan اعمال می‌شود
و نه `RLIMIT_AS` — دلیلش در [`LIMITATIONS.md §5.2`](LIMITATIONS.md) آمده.

## `sandbox`

```yaml
sandbox:
  backend: bubblewrap       # bubblewrap | subprocess
  network: false            # پیش‌فرض false
  unsafe_ack: false         # برای backend: subprocess الزاماً true
  extra_ro_binds: []        # مسیرهای میزبان که فقط-خواندنی در دسترس باشند
```

`backend: subprocess` **هیچ ایزوله‌سازی‌ای ندارد** و فقط برای دیباگ محلی است. بدون
`unsafe_ack: true` پیکربندی رد می‌شود، و در صورت استفاده، بررسی الزامی
`executions_isolated` رد می‌شود و اجرا هرگز `COMPLETE` گزارش نمی‌گردد.

## `minimization` و `reproduction`

```yaml
minimization:
  enabled: true
  max_iterations: 2000      # سقف تعداد اجرای واقعی
  budget_seconds: 120       # سقف زمان

reproduction:
  replays: 3                # حداقل 3؛ کمتر از آن schema رد می‌کند
```

## خطاهای رایج پیکربندی

| پیام | علت |
|------|------|
| `schema violation at 'builds/0/mode'` | مقدار خارج از `release`/`sanitized` |
| `unknown placeholder {foo}` | قالب تعریف‌نشده در دستور ساخت |
| `input.method 'file' requires {input_file} in input.argv` | قالب ورودی جا افتاده |
| `a 'release' build is required` | هیچ build با mode release نیست |
| `not a git repository` | `repo_path` مخزن git نیست |
| `duplicate test id` | دو تست با `id` یکسان |
| `sandbox.backend 'subprocess' provides no isolation` | `unsafe_ack: true` جا افتاده |
