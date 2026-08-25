# معماری سیستم

## نمای کلی

MyBarid-AI یک Desktop App ویندوزی است. رابط کاربر در WebView2 اجرا می‌شود و
از طریق Bridge با منطق Python ارتباط می‌گیرد.

```text
Excel Notes + Tasks
        |
        v
data.loader -> data.mapper -> data.validator -> data.cleaner
        |
        v
      Dataset / CaseBundle
        |
        v
pipeline.py
  |-- period/general selection
  |-- AI analysis (optional, case mode)
  |-- Rule Engine + Scoring
  |-- comparison / ranking / suspicious / data health
        |
        v
bridge.Api  <---->  ui/app.js + ui/index.html + ui/styles.css
        |
        v
reports/* and local database/*
```

## لایه‌ها

### Entry point

- `main.py`: ساخت پنجره WebView2، تعیین نسخه، آماده‌سازی storage و راه‌اندازی
  `bridge.Api`.
- `MyBarid-AI.spec`: تنظیمات PyInstaller.

### Bridge/API

- `bridge.py`: تنها مرز عمومی Python و JavaScript.
- مسئول نگهداری Dataset جاری، تنظیمات، وضعیت اجرای تحلیل، اجرای Workerهای
  طولانی و تبدیل مدل‌های Python به Dictionary قابل مصرف UI است.
- UI نباید مستقیماً به SQLite، فایل Excel یا ماژول‌های تحلیل دسترسی داشته باشد.

### Data

- `data/loader.py`: خواندن Workbook.
- `data/mapper.py`: تشخیص نام ستون‌ها و نگاشت به فیلدهای استاندارد.
- `data/validator.py`: تبدیل و اعتبارسنجی رکوردهای Notes/Tasks.
- `data/cleaner.py`: ساخت `CaseBundle` و اتصال Task به Case.

### Analysis

- `analysis/rules.py`: محاسبات Rule-Based.
- `analysis/scoring.py`: ترکیب معیارها، وزن‌دهی، N/A، Coverage و Confidence.
- `analysis/comparison.py`: مقایسه دوره‌ها.
- `analysis/experts.py`: تجمیع و رتبه‌بندی کارشناسان.
- `analysis/suspicious.py`: موارد نیازمند بررسی.
- `analysis/data_quality.py`: سلامت داده.
- `analysis/timeline.py`: Timeline قابل ارسال به UI و AI.

### AI

- `ai/providers.py`: Providerهای Gemini و OpenAI-compatible.
- `ai/prompts.py`: Promptهای استاندارد.
- `ai/schemas.py`: استخراج و اعتبارسنجی JSON پاسخ.
- `ai/analyzer.py`: Cache، Retry، اجرای تحلیل کیس و نگاشت پاسخ به امتیاز.

AI اختیاری است. نبود شواهد معتبر باید به N/A منجر شود، نه امتیاز صفر و نه
فرض نقص.

### Configuration

- `config/v2_criteria.json`: تنظیمات پیش‌فرض معیارها و Profileها.
- `config/criteria_config.py`: مدل و منطق انتخاب Profile.
- `config/criteria_guides.json`: راهنمای قابل نمایش معیارها.
- در نسخه قابل‌انتقال، تنظیمات کاربر کنار EXE در
  `MyBarid-AI-Portable` ذخیره می‌شود و بر فایل پیش‌فرض غلبه دارد.
- مسیر قدیمی `%LOCALAPPDATA%\CRMQualityReviewer` فقط منبع Migration اولیه است.

### Persistence

- `database/db.py`: SQLite تنظیمات و Cache AI.
- کلید API در Windows با DPAPI در `api-key.bin` ذخیره می‌شود و در Export
  تنظیمات قرار نمی‌گیرد.

## قوانین وابستگی

1. `ui` فقط از `bridge.Api` استفاده می‌کند.
2. `pipeline` orchestration می‌کند، اما نباید منطق UI داشته باشد.
3. `analysis` نباید به WebView یا Bridge وابسته شود.
4. `ai` نباید مستقیماً UI را تغییر دهد.
5. `database` نباید مدل‌های UI یا HTML را بشناسد.
6. تبدیل Python object به JSON فقط در Bridge یا Export انجام شود.

## مسیرهای مستقل تحلیل

- `comparison`: دو بازه زمانی واقعی، سپس مقایسه.
- `general`: کل Dataset فعلی به‌صورت یک جمعیت واحد؛ دوره صوری ساخته نمی‌شود.
- `case AI`: تحلیل مستقل یک Case و به‌روزرسانی همان Breakdown در نتیجه جاری.
- `task`: امتیازدهی Task-based؛ تحلیل AI کیس در این Mode اجرا نمی‌شود.
