# Configuration و Dependencyها

## فایل‌های Configuration

- `config/v2_criteria.json`: معیارها، Categoryها، Profileها و Ratio پیش‌فرض.
- `config/criteria_guides.json`: هدف، محاسبه، تفسیر و محدودیت معیارها.
- `VERSION`: نسخه نرم‌افزار.
- `CHANGELOG.json`: Release Notes.
- `requirements.txt`: Dependencyهای Runtime و تست.

## تنظیمات قابل‌انتقال

نسخه قابل‌انتقال تنظیمات را کنار EXE در `MyBarid-AI-Portable` نگه می‌دارد:

```text
app.db                 settings، expert_groups و ai_cache
criteria_config.json   تنظیمات معیار کاربر
api-key.bin            Secret رمزنگاری‌شده محلی
webview2/              profile WebView2
```

مسیر قدیمی `%LOCALAPPDATA%\CRMQualityReviewer` فقط برای Migration اولیه
استفاده می‌شود. Secret رمزنگاری‌شده با Windows DPAPI ممکن است روی کامپیوتر
دیگر باز نشود.

## Environment Variable

`MYBARID_PORTABLE_DIR` برای تست یا اجرای کنترل‌شده مسیر داده قابل‌انتقال را
Override می‌کند. در حالت EXE، مسیر پیش‌فرض پوشه EXE است؛ در حالت Source،
پوشه `MyBarid-AI-Portable` کنار Repository است.

## Dependencyها

| Package | کاربرد |
|---|---|
| `openpyxl` | خواندن و تولید Excel |
| `pywebview` | پنجره Desktop و WebView2 Bridge |
| `pytest` | تست‌های توسعه؛ Runtime اجباری نیست |
| `PyInstaller` | ساخت EXE؛ ابزار Build |

Providerهای AI با `urllib` استاندارد Python پیاده‌سازی شده‌اند و Dependency
شبکه‌ای اضافه ندارند.
