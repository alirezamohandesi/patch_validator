# INSTALLATION

## پیش‌نیازهای سیستم

```bash
sudo apt install -y \
    python3 python3-venv \
    build-essential cmake git \
    bubblewrap util-linux binutils
```

| بسته | چرا لازم است | در نبودش چه می‌شود |
|------|---------------|---------------------|
| `bubblewrap` | ایزوله‌سازی هر اجرای تست | ابزار با کد ۳۰ خارج می‌شود و هیچ باینری آسیب‌پذیری اجرا نمی‌کند |
| `util-linux` (`prlimit`) | محدودیت تعداد پراسس داخل sandbox | محدودیت اعمال نمی‌شود؛ در لاگ debug هشدار می‌آید |
| `binutils` (`readelf`) | شواهد ELF برای تحلیل سخت‌سازی | وضعیت محافظ‌ها `unknown` می‌شود و بررسی الزامی رد می‌شود |
| `build-essential`, `cmake` | ساخت برنامه‌های هدف | خطای ساخت، کد ۳۰ |
| `git` | خواندن revisionها و diff | ابزار اصلاً شروع نمی‌شود |

## نصب

```bash
git clone <repository-url> patch-validator
cd patch-validator

python3 -m venv .venv
source .venv/bin/activate
pip install -e .            # یا: pip install -e ".[dev]" برای اجرای تست‌ها
```

روی اوبونتو ۲۳ به بعد، نصب در محیط سیستمی با `pip` مسدود است (PEP 668). استفاده از
virtual environment تنها راه درست است؛ `--break-system-packages` را به کار نبرید.

## بررسی محیط

```bash
patch-validator doctor
```

خروجی سالم:

```
sandbox
  executable             /usr/bin/bwrap
  user_namespaces        ok
  cgroups_v2             available
  seccomp                disabled
  namespace_smoke_test   ok
  available              True

this environment can run the validator
```

`doctor` با کد ۰ یا ۳۰ خارج می‌شود، پس در اسکریپت CI قابل استفاده است.

## آماده‌سازی اهداف

```bash
bash targets/recparse/bootstrap.sh     # آفلاین، هش‌های قطعی
bash targets/cjson/bootstrap.sh        # نیازمند شبکه (clone از GitHub)
```

`recparse` یک مخزن git واقعی با چهار شاخه می‌سازد. چون نام و تاریخ مؤلف ثابت‌اند،
هش‌های commit روی هر ماشین یکسان درمی‌آیند.

## اولین اجرا

```bash
patch-validator validate --config configs/recparse.yaml
echo "exit: $?"          # انتظار: 0
```

## اجرا داخل Docker

```bash
docker build -t patch-validator .

cid=$(docker run -d \
    --security-opt seccomp=unconfined \
    --security-opt apparmor=unconfined \
    --security-opt systempaths=unconfined \
    --cap-add=SYS_ADMIN \
    patch-validator validate --config /opt/src/configs/recparse.yaml)

docker wait "$cid"                      # کد خروج ابزار
docker cp "$cid:/project/runs" ./runs   # artifactها
docker rm "$cid"
```

کانتینر باید با کاربر root اجرا شود؛ `--user` قابلیتی را که sandbox لازم دارد از بین
می‌برد. به همین دلیل artifactها با `docker cp` بیرون کشیده می‌شوند و نه با bind mount.

### چرا این پرچم‌ها

| پرچم | محدودیتی که حل می‌کند |
|------|------------------------|
| `seccomp=unconfined` | پروفایل پیش‌فرض Docker برخی پرچم‌های `clone(2)` مورد نیاز bubblewrap را مسدود می‌کند |
| `systempaths=unconfined` | Docker مسیرهایی زیر `/proc` را ماسک می‌کند و کرنل اجازهٔ mount کردن procfs تازه را نمی‌دهد |
| `apparmor=unconfined` + `--cap-add=SYS_ADMIN` | روی اوبونتو ۲۴.۰۴ به بعد، `kernel.apparmor_restrict_unprivileged_userns=1` user namespace بدون امتیاز را فقط برای باینری‌های دارای پروفایل AppArmor مجاز می‌کند؛ نسخهٔ bubblewrap داخل کانتینر چنین پروفایلی ندارد |

اگر روی میزبان `kernel.apparmor_restrict_unprivileged_userns=0` تنظیم شود،
`--cap-add=SYS_ADMIN` دیگر لازم نیست. `--privileged` هم کار می‌کند ولی هرگز لازم نیست و
دسترسی بسیار گسترده‌تری می‌دهد.

## رفع اشکال

| نشانه | علت | راه‌حل |
|--------|------|--------|
| `bwrap: Creating new namespace failed: Resource temporarily unavailable` | `RLIMIT_NPROC` از بیرون اعمال شده | این باگ رفع شده؛ اگر دیدید یعنی نسخهٔ قدیمی اجرا می‌شود |
| `bwrap: Can't mount proc on /newroot/proc` | مسیرهای ماسک‌شدهٔ `/proc` در Docker | `--security-opt systempaths=unconfined` |
| `bwrap: loopback: Failed RTM_NEWADDR` | محدودیت AppArmor روی user namespace | `--security-opt apparmor=unconfined --cap-add=SYS_ADMIN` |
| `bwrap: setting up uid map: Permission denied` | user namespace بدون امتیاز غیرفعال است | `sysctl kernel.unprivileged_userns_clone=1` |
| `build produced no binary at ...` | قالب `binary_path` با خروجی واقعی build نمی‌خواند | `cat runs/<id>/builds/<ver>.<mode>/build.log` |
| `error: externally-managed-environment` | نصب در محیط سیستمی | از venv استفاده کنید |
| خطای `ModuleNotFoundError: patch_validator` | محیط فعال نیست | `source .venv/bin/activate` |

لاگ کامل هر اجرا در `runs/<run-id>/` است؛ `-v` یا `-vv` جزئیات بیشتری چاپ می‌کند.
