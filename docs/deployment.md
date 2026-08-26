# اجرا، Build و Deployment

## اجرای Development

پیش‌نیاز: Windows، Python 3.10+ و WebView2 Runtime.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

یا در ویندوز:

```text
run.cmd
```

`run.cmd` venv محلی را می‌سازد، Dependencyهای لازم را نصب می‌کند و برنامه را
در User mode اجرا می‌کند.

## Build EXE

```powershell
. .\scripts\sync_portable.ps1 -BuildExe
```

نسخه قابل استفاده برای انتقال باید در پوشه `MyBarid-AI-Portable` قرار گیرد و
همراه فایل‌های داده همان پوشه منتقل شود.

پس از هر Build، فایل اجرایی ریشه پروژه و نسخه Portable هم‌زمان به‌روزرسانی
می‌شوند. تنظیمات کاربر از Portable به ریشه پروژه نیز Mirror می‌شوند؛
`app.db`، `criteria_config.json` و `api-key.bin` محلی هستند و نباید Commit شوند.

## کامپیوتر مقصد

1. کل پوشه `MyBarid-AI-Portable` را کپی کنید.
2. `MyBarid-AI.exe` را اجرا کنید.
3. WebView2 Runtime باید نصب باشد.
4. در صورت خطای کلید، API key را دوباره در تنظیمات AI وارد کنید.
5. Notes و Tasks را از داخل برنامه بارگذاری کنید.

## خارج از Scope فعلی

- Installer رسمی MSI/Setup تولید نمی‌شود.
- Deployment Server یا Multi-user وجود ندارد.
- دیتابیس مرکزی و Migration نسخه‌دار SQLite وجود ندارد.
