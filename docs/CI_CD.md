# CI/CD

اجرای ابزار در پایپ‌لاین و تفسیر نتیجهٔ آن.

## معماری اجرا

```
┌──────────────── یک Docker container به ازای هر CI Job ────────────────┐
│                                                                        │
│   patch-validator                                                      │
│        │                                                               │
│        └── به ازای هر اجرای تست: یک sandbox سبک (bubblewrap)          │
│                                                                        │
│   هیچ دسترسی‌ای به Docker daemon یا socket وجود ندارد                  │
└────────────────────────────────────────────────────────────────────────┘
```

ابزار هرگز container نمی‌سازد. ساخت container به ازای هر تست ده‌ها برابر کندتر است و
نیازمند دسترسی به daemon است — یک سطح دسترسی خطرناک داخل CI.

## چهارده مرحلهٔ پایپ‌لاین

`.github/workflows/validate.yml`:

| # | مرحله | دستور |
|---|-------|-------|
| ۱ | Checkout | `actions/checkout@v4` |
| ۲ | Environment setup | `actions/setup-python@v5` |
| ۳ | Dependency installation | `apt-get install` + `pip install -e .` |
| ۴ | Configuration validation | `patch-validator check-config` |
| ۵ | Build | `patch-validator build` |
| ۶ | Release testing | `patch-validator test` (ماتریس کامل) |
| ۷ | Sanitized testing | همان دستور، هر دو mode |
| ۸ | Crash analysis | داخل `validate` |
| ۹ | Patch correlation | داخل `validate` |
| ۱۰ | Regression testing | داخل `validate` |
| ۱۱ | Hardening analysis | `patch-validator hardening` |
| ۱۲ | Report generation | داخل `validate` |
| ۱۳ | Artifact upload | `actions/upload-artifact@v4` با `if: always()` |
| ۱۴ | Final exit code evaluation | مرحلهٔ صریح assert |

پیش از همهٔ این‌ها `patch-validator doctor` اجرا می‌شود؛ اگر محیط sandbox را پشتیبانی
نکند، job همان‌جا و با پیام دقیق شکست می‌خورد.

## سه job

### `tests` — آزمون خود ابزار

۱۶۳ تست. اگر این job شکست بخورد، هیچ ادعایی از ابزار قابل اتکا نیست، پس بقیه به آن
وابسته‌اند.

### `scenarios` — تأیید رفتار ابزار

ماتریسی روی سه وصلهٔ هدف اسباب‌بازی. هر سناریو کد خروج مستندی دارد و job شکست می‌خورد
اگر ابزار **عدد دیگری** بدهد:

```yaml
matrix:
  include:
    - {revision: correct-patch,    expected_exit: 0}
    - {revision: incomplete-patch, expected_exit: 10}
    - {revision: regression-patch, expected_exit: 20}
```

این هم pass دروغین را می‌گیرد و هم failure دروغین را.

### `gate` — ابزار در نقش دروازه

همان‌طور که یک پروژهٔ واقعی استفاده می‌کند: هر کد خروج غیرصفر، پایپ‌لاین را می‌شکند.

## مدیریت کد خروج

**کد خروج هرگز دور ریخته یا پنهان نمی‌شود.**

```yaml
- name: Validate the patch
  id: validate
  continue-on-error: true           # تا artifactها آپلود شوند
  run: |
    set +e
    patch-validator validate --config ... --run-dir "runs/${{ matrix.revision }}"
    echo "exit_code=$?" >> "$GITHUB_OUTPUT"

- name: Upload the run directory
  if: always()                      # حتی وقتی شکست خورده
  uses: actions/upload-artifact@v4

- name: Check the exit code
  run: |
    actual="${{ steps.validate.outputs.exit_code }}"
    if [ "$actual" != "${{ matrix.expected_exit }}" ]; then
      echo "::error::patch-validator returned $actual, expected ${{ matrix.expected_exit }}"
      exit 1
    fi
```

نکات طراحی:

- `continue-on-error` فقط روی مرحلهٔ اجرا است، نه روی مرحلهٔ تصمیم.
- `if: always()` روی آپلود، تضمین می‌کند گزارش اجرای شکست‌خورده قابل دریافت است.
- **هیچ `|| true` در مرحلهٔ تصمیم نیست.** شکست، شکست می‌ماند.

## تفسیر کدهای خروج در پایپ‌لاین

| کد | معنا | اقدام پیشنهادی |
|----|------|------------------|
| `0` | وصله قبول | ادغام مجاز |
| `10` | آسیب‌پذیری باقی مانده یا خطای جدید | **مسدود کردن ادغام.** بخش `security` گزارش و همبستگی هر یافته را ببینید |
| `20` | پسرفت عملکردی | **مسدود کردن ادغام.** هر یافته ورودی و هر دو رفتار را نشان می‌دهد |
| `30` | خطای ساخت یا پیکربندی | مشکل زیرساخت است، نه وصله. `build.log` و خروجی `doctor` را ببینید |
| `40` | غیرقطعی | **موفقیت تلقی نکنید.** بخش `mandatory_checks` می‌گوید چه چیزی کامل نشده |

اولویت در همزمانی: `30 > 10 > 20 > 40 > 0`.

کد ۴۰ معمولاً یعنی یکی از این‌ها:

- خطای پایه بازتولید نشد (چیزی برای اثبات رفع وجود ندارد)
- یافته‌ای ناپایدار بود
- ماتریس کامل اجرا نشد
- اجرا بدون ایزوله‌سازی انجام شد

## Artifactها

هر job کل پوشهٔ اجرا را آپلود می‌کند:

```
runs/<revision>/
  report.json  report.md  patch.diff
  builds/  exec/  bundles/  minimized/  regression/  hardening/
```

خلاصهٔ markdown به `$GITHUB_STEP_SUMMARY` هم نوشته می‌شود، پس نتیجه بدون دانلود artifact
در صفحهٔ job دیده می‌شود.

## اجرای دستی

```yaml
on:
  workflow_dispatch:
    inputs:
      patched_revision:
        description: Revision of the target to validate against the base
        default: correct-patch
```

همین مسیر، سناریوی **وصلهٔ دیده‌نشده** را پوشش می‌دهد: یک revision دلخواه بدهید و ابزار
آن را با همان پایه، همان آزمون‌ها و همان Oracleها ارزیابی می‌کند.

## بازتولید محلی یک اجرای CI

```bash
# artifact را دانلود و باز کنید، سپس:
patch-validator report --run runs/incomplete-patch --format summary
patch-validator reproduce runs/incomplete-patch/bundles/<finding>/
```

بسته شامل hash commit، SHA256 باینری، پرچم‌های ساخت و دستورهای بازسازی است، پس اجرای
CI روی ماشین محلی قابل بازسازی است.

## متغیرهای محیطی

| متغیر | کاربرد |
|-------|---------|
| `PATCH_VALIDATOR_IMAGE_DIGEST` | در هر بستهٔ بازتولید ثبت می‌شود تا یافته به ایمیج دقیقی که تولیدش کرده گره بخورد |

## اجرا با Docker در CI

اگر به‌جای نصب مستقیم روی runner از ایمیج استفاده می‌کنید:

```bash
cid=$(docker run -d \
    --security-opt seccomp=unconfined \
    --security-opt apparmor=unconfined \
    --security-opt systempaths=unconfined \
    --cap-add=SYS_ADMIN \
    -e PATCH_VALIDATOR_IMAGE_DIGEST="$IMAGE_DIGEST" \
    patch-validator validate --config /opt/src/configs/recparse.yaml)

docker wait "$cid"
docker cp "$cid:/project/runs" ./runs
docker rm "$cid"
```

دلیل هر پرچم در [`INSTALLATION.md`](INSTALLATION.md) و
[`LIMITATIONS.md §5.4`](LIMITATIONS.md) آمده. `--privileged` لازم نیست.
