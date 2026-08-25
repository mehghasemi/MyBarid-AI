# راهنمای توسعه و نگهداری

## شروع کار

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## چرخه تغییر

1. قبل از تغییر، `git status` و Branch را بررسی کن.
2. فایل مستندات مرتبط را پیدا کن.
3. کوچک‌ترین تغییر مستقل را اعمال کن.
4. تست همان لایه و سپس تست کامل را اجرا کن.
5. اگر قرارداد، مدل داده یا معماری تغییر کرد، Docs و Changelog را به‌روز کن.
6. نسخه را در `VERSION` افزایش بده.
7. روی Branch `GapCode` Commit و Push کن.

## تست و اعتبارسنجی

```powershell
.venv\Scripts\python.exe -m pytest -q
node --check ui\app.js
.venv\Scripts\python.exe -m compileall -q ai analysis bridge.py
git diff --check
```

برای Build:

```powershell
.venv\Scripts\pyinstaller.exe --noconfirm --clean MyBarid-AI.spec
Copy-Item .\dist\MyBarid-AI.exe .\MyBarid-AI.exe -Force
```

## قواعد تغییر بخش‌ها

### معیار جدید

- Criterion را در تنظیمات پیش‌فرض اضافه کن.
- اگر Rule-Based است، تابع را در `analysis/rules.py` اضافه کن.
- Guide معیار را در `config/criteria_guides.json` تکمیل کن.
- برای Profileهای مرتبط، `criteria_ids` را بررسی کن.
- تست Score و N/A اضافه کن.

### تغییر API

- امضای متد و شکل خروجی را در `docs/api-contract.md` تغییر بده.
- UI مصرف‌کننده را هم‌زمان به‌روزرسانی کن.
- خطای قابل انتظار را با `ok:false` برگردان.

### تغییر داده

- Mapper و Validator را تغییر بده، نه Ruleها را برای جبران نام استاندارد.
- رفتار رکورد ناقص و unmatched را مستند کن.
- تست ورودی واقعی/نمونه اضافه کن.

### تغییر AI

- Prompt نمونه JSON باید آکولادهای Escape شده داشته باشد.
- پاسخ Provider با `extract_json` و `validate_case_analysis` اعتبارسنجی شود.
- پاسخ N/A معتبر با خطای Provider یکی نیست.
- کلید API، داده واقعی مشتری و پاسخ خام حساس نباید Log یا Commit شوند.

## بازگشت نسخه

برای بازگشت امن، از Commit مشخص یک Branch تست بساز یا با `git revert` تغییر را
برگردان. حذف تاریخچه یا `reset --hard` فقط با درخواست صریح انجام شود.

## کار با پروژه بزرگ

- هر قابلیت بزرگ را به ماژول مستقل با قرارداد مشخص تقسیم کن.
- از وابستگی UI به منطق تحلیل جلوگیری کن.
- تغییرات ساختاری را با ADR ثبت کن.
- تست‌های Regression را برای Bugهای حل‌شده نگه دار.
- فایل‌های نمونه و داده واقعی را وارد Git نکن.
