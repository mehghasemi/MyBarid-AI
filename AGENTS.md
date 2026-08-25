# MyBarid-AI — راهنمای سریع عامل توسعه

این فایل نقطه شروع هر برنامه‌نویس یا مدل زبانی برای کار روی پروژه است.

## قبل از هر تغییر

1. `git status --short` و `git branch --show-current` را بررسی کن.
2. مستندات مرتبط را بخوان؛ کل Repository را بی‌دلیل دوباره بررسی نکن.
3. تغییرات کاربر را حفظ کن و فقط Scope درخواست را تغییر بده.
4. تغییرات GitHub فقط روی Branch `GapCode` انجام شود.

## نقشه سریع پروژه

- `main.py`: اجرای Desktop/WebView2
- `bridge.py`: قرارداد Python ↔ JavaScript و API عمومی UI
- `pipeline.py`: Orchestration بارگذاری و تحلیل
- `data/`: Excel، Mapping، Validation و ساخت CaseBundle
- `analysis/`: Rule Engine، Scoring، N/A، Reports تحلیلی
- `ai/`: Provider، Prompt، Schema و Cache تحلیل AI
- `config/`: معیارها، Profileها و راهنمای معیارها
- `database/`: SQLite تنظیمات و Cache امن کلید
- `ui/`: HTML/CSS/JavaScript
- `reports/`: Excel/CSV export
- `tests/`: تست‌های Regression و واحد

## انتخاب مستندات بر اساس کار

- معماری و وابستگی‌ها: `docs/architecture.md`
- API و خروجی‌های UI: `docs/api-contract.md`
- Excel، Case، Score و Cache: `docs/data-model.md`
- تصمیم‌های قبلی: `docs/decisions.md`
- روش توسعه، تست و Build: `docs/development.md`
- فهرست مستندات و قانون به‌روزرسانی: `docs/README.md`

## قواعد کم‌مصرف

- فقط فایل‌های مرتبط با درخواست و مستندات همان بخش را بخوان.
- از `rg` برای پیدا کردن Symbol و قرارداد استفاده کن.
- تغییرات را کوچک و مستقل نگه دار.
- Bug حل‌شده باید تست Regression داشته باشد.
- فقط در صورت تغییر API، مدل داده، معماری، امنیت یا فرآیند Release مستندات را
  به‌روزرسانی کن.
- متن کامل مستندات را در هر پاسخ یا هر درخواست دوباره کپی نکن؛ به مسیر فایل
  ارجاع بده.

## اعتبارسنجی استاندارد

```powershell
.venv\Scripts\python.exe -m pytest -q
node --check ui\app.js
.venv\Scripts\python.exe -m compileall -q ai analysis bridge.py
git diff --check
```

پس از تغییرات قابل انتشار، `VERSION` و `CHANGELOG.json` را به‌روزرسانی کن.
