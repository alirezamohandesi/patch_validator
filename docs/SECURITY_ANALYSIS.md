# SECURITY ANALYSIS

چگونه یک اجرا به یک مشاهدهٔ طبقه‌بندی‌شده تبدیل می‌شود، و مرزهایی که عمداً رعایت می‌شوند.

## اصل حاکم

> **مشاهدهٔ خطا اثبات آسیب‌پذیری نیست، و نبود خطا اثبات امنیت نیست.**

ابزار سه چیز متفاوت را از هم جدا نگه می‌دارد:

| | |
|---|---|
| **چه چیزی مشاهده شد** | نوع خطا، مکانیزم تشخیص، نحوهٔ خاتمه، محل |
| **چه چیزی مشاهده نشد** | صریحاً گزارش می‌شود، ولی هرگز به «امن است» ترجمه نمی‌شود |
| **چه چیزی نامشخص ماند** | محور کامل‌بودن تحلیل |

## ترتیب تشخیص

`CrashAnalyzer.analyze` تشخیص‌دهنده‌ها را به ترتیب زیر اجرا می‌کند. **ترتیب معنادار است.**

```
1. launch_failure      برنامه اصلاً اجرا نشد → یافته نیست
2. timeout             خاتمه نیافت → محور کامل‌بودن، نه امنیت
3. resource signal     SIGXCPU / SIGXFSZ → محدودیت منابع، نه امنیت
4. AddressSanitizer    گزارش ASan
5. LeakSanitizer       نشت حافظه
6. UBSan               رفتار تعریف‌نشده
7. glibc diagnostics   stack protector / FORTIFY / بررسی‌های malloc
8. سیگنال خام          SIGSEGV / SIGBUS / SIGFPE / SIGILL / SIGABRT
9. clean               هیچ شاهدی از خطا
```

**چرا timeout پیش از ASan؟** اجرایی که وسط چاپ گزارش ASan کشته شده، گزارش ناقص روی
stderr دارد. اگر اول دنبال الگوی ASan می‌گشتیم، یک timeout به «خطای حافظه‌ای تأییدشده»
تبدیل می‌شد. این در تست
`test_a_timeout_wins_over_a_partial_sanitizer_report` تثبیت شده است.

## انواع خطا

| دسته | نمونه‌ها |
|------|----------|
| سرریز بافر | `STACK_BUFFER_OVERFLOW`, `HEAP_BUFFER_OVERFLOW`, `GLOBAL_BUFFER_OVERFLOW`, `BUFFER_OVERFLOW` |
| چرخهٔ عمر حافظه | `USE_AFTER_FREE`, `USE_AFTER_RETURN`, `USE_AFTER_SCOPE`, `DOUBLE_FREE`, `INVALID_FREE`, `ALLOC_DEALLOC_MISMATCH` |
| فساد heap | `HEAP_CORRUPTION` |
| اشاره‌گر | `NULL_POINTER_DEREFERENCE`, `SEGMENTATION_FAULT`, `BUS_ERROR` |
| محاسباتی | `INTEGER_OVERFLOW`, `DIVISION_BY_ZERO`, `ARITHMETIC_FAULT`, `INVALID_SHIFT` |
| رفتار تعریف‌نشده | `UNDEFINED_BEHAVIOR`, `ARRAY_OUT_OF_BOUNDS`, `MISALIGNED_ACCESS` |
| منابع | `STACK_EXHAUSTION`, `MEMORY_LEAK`, `ALLOCATION_SIZE_TOO_BIG` |
| خاتمه | `ABORT`, `ILLEGAL_INSTRUCTION`, `TRAP`, `BAD_SYSCALL` |

دسته‌ای که در نگاشت نباشد با نام خام sanitizer گزارش می‌شود
(`ASAN_<CATEGORY>`) و یادداشت «unmapped category» می‌گیرد — به‌جای اینکه به یک دستهٔ
نزدیک و نادرست نسبت داده شود.

## مکانیزم‌های تشخیص

| مکانیزم | چه چیزی را نشان می‌دهد | محدودیت |
|---------|------------------------|---------|
| `address_sanitizer` | نوع دقیق خطا + محل + stack trace | فقط در build سانیتایزشده |
| `undefined_behavior_sanitizer` | نوع UB + فایل:خط | همان |
| `leak_sanitizer` | نشت حافظه | نقص منابع است، نه نقض ایمنی حافظه |
| `stack_protector` | canary پشته دستکاری شده | محل شروع نوشتن را نمی‌گوید |
| `fortify_source` | یک کران نقض شده | **stack trace ندارد** |
| `glibc_malloc_check` | ساختار heap خراب شده | محل خرابی اولیه را نمی‌گوید |
| `os_signal` | خطای سخت‌افزاری/سیستمی | دستهٔ دقیق خطا را نمی‌گوید |

سه مورد آخر عمداً `confidence` پایین‌تر یا یادداشت صریح می‌گیرند.

## نحوهٔ خاتمه

برای هر اجرا ثبت می‌شود: `exit_code`، `signal`، `signal_name`، `signal_inferred`،
`timed_out`، و هر دو جریان خروجی.

`bubblewrap` مرگ با سیگنال را به کد خروج `128+N` تبدیل می‌کند. ابزار آن را رمزگشایی
می‌کند و **با پرچم `signal_inferred: true`** علامت می‌زند، `confidence` را به `medium`
کاهش می‌دهد، و در یادداشت‌ها می‌نویسد که تنها شاهد تأییدکننده، خروجی ثبت‌شده است.

نمونهٔ واقعی:

```
exit=134  signal=SIGABRT  inferred=True
stderr: '*** buffer overflow detected ***: terminated'
→ BUFFER_OVERFLOW via fortify_source, confidence high
```

کد خروج به‌تنهایی مبهم بود؛ پیام glibc آن را تأیید کرد.

## امضای خطا

برای هر خطا **دو** امضا ساخته می‌شود:

| امضا | ساختار | کاربرد |
|------|---------|--------|
| `crash_signature` | `sha256(نوع خطا | مکانیزم | ۳ فریم هدف با فایل:خط)` | کوچک‌سازی ورودی: «آیا هنوز همان باگ در همان جاست؟» |
| `location_signature` | همان، **بدون شمارهٔ خط** | مقایسهٔ base با patched |

**چرا دو تا؟** وصله شماره‌خط‌ها را جابه‌جا می‌کند. اگر فقط امضای دقیق داشتیم، هر خطای
واقعاً یکسان پس از وصله «جابه‌جاشده» گزارش می‌شد. تست
`test_line_change_alters_the_precise_signature_only` این را تثبیت می‌کند.

فیلد `signature_quality`:

- `symbolized` — فریم‌ها فایل و خط دارند
- `unsymbolized` — فقط `module+offset`؛ همبستگی از `WEAK` فراتر نمی‌رود
- `none` — هیچ فریمی نبود؛ امضا فقط از نوع و مکانیزم ساخته شده

## فریم‌های هدف در برابر فریم‌های ابزار

بالاترین فریم‌های یک گزارش ASan معمولاً interceptorهای سانیتایزر و توابع libc هستند:

```
#0 memcpy       .../sanitizer_common_interceptors_memintrinsics.inc:115   ← ابزار
#1 memcpy       /usr/include/.../string_fortified.h:29                    ← ابزار
#2 copy_payload src/record.c:21                                           ← هدف
#3 handle_text  src/record.c:30                                           ← هدف
#4 parse_stream src/record.c:102                                          ← هدف
```

همهٔ فریم‌ها به‌عنوان شاهد نگه داشته می‌شوند، ولی `target_frames` فقط فریم‌های هدف را
دارد و مسیرشان **نسبت به ریشهٔ مخزن** نرمال‌سازی شده است. این دو کار لازم‌اند چون:

1. همبستگی باید از اولین فریم کد هدف شروع شود، نه از `memcpy`.
2. base و patched در دو worktree متفاوت build می‌شوند؛ بدون نرمال‌سازی، کد یکسان مسیر
   متفاوت تولید می‌کند و هیچ مقایسه‌ای ممکن نیست.

## تفکیک release و sanitized

نتایج دو build **هرگز** مخلوط نمی‌شوند. این در `CasePair.__post_init__` با یک استثنا
تضمین شده، نه با قرارداد:

```python
if self.base_result.build_mode != self.patched_result.build_mode:
    raise ValueError("refusing to compare different build modes")
```

گزارش بخش جداگانه‌ای دارد که نشان می‌دهد build سانیتایزشده چه چیزی را آشکار کرد که
release نکرد. نمونهٔ واقعی از `recparse`:

| ورودی | release | sanitized |
|-------|---------|-----------|
| `boundary_text32` | `exit 0` — هیچ نشانه‌ای | `STACK_BUFFER_OVERFLOW` در `copy_payload` |

این سرریز یک‌بایتی در build بهینه‌شده در padding می‌نشیند و هیچ اثری ندارد.

## جدول تصمیم محور امنیت

برای هر (تست، build mode):

| base | patched | امضای مکان یکسان | یافته |
|------|---------|-------------------|-------|
| خطا | سالم | — | `FIXED` |
| خطا | خطا | بله | `INCOMPLETE_FIX` (confidence بالا) |
| خطا | خطا | خیر | `INCOMPLETE_FIX` (confidence متوسط، `signature_changed`) |
| سالم | خطا | — | `NEW_ISSUE` |
| سالم | سالم | — | — |
| timeout / محدودیت منابع | هر چیزی | — | محور کامل‌بودن تحلیل |

`FIXED` همیشه با این یادداشت می‌آید: نبود خطا برای **این ورودی** اثبات نمی‌کند که کل
دستهٔ نقص از بین رفته است.

`NEW_ISSUE` همیشه با این یادداشت می‌آید: تازه مشاهده شدن یک خطا به‌تنهایی اثبات نمی‌کند
وصله علت آن بوده؛ برای آن باید به همبستگی نگاه کرد.

## آنچه هرگز ادعا نمی‌شود

- **قابلیت بهره‌برداری.** هیچ خروجی‌ای نمی‌گوید یک یافته قابل بهره‌برداری است.
- **علت ریشه‌ای.** محل گزارش‌شده محل بروز خطاست، نه لزوماً محل ورود دادهٔ مخرب.
- **کامل بودن.** نتیجه فقط دربارهٔ ورودی‌های آزمون‌شده است.
- **امنیت.** `PASS` یعنی «در این محدوده چیزی دیده نشد»، نه «امن است».
