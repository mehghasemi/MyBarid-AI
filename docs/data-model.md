# مدل داده و جریان پردازش

## ورودی Excel

دو Workbook اصلی وارد می‌شوند:

- Notes: رویدادها، متن اقدام، اطلاعات Case و کارشناس.
- Tasks: فعالیت‌ها، نتیجه، زمان‌ها، Case Number یا Regarding.

نام ستون‌ها مستقیماً در منطق تحلیل استفاده نمی‌شود؛ ابتدا توسط Mapper به فیلدهای
استاندارد تبدیل می‌شوند.

## مدل‌های استاندارد

### NoteRecord

شامل شناسه Note، متن، Case Number/Title، مشتری، کارشناس، Service، وضعیت Case،
تاریخ Case، تاریخ Note، نویسنده، Assign و نوع رویداد است.

### TaskRecord

شامل شناسه Task، Subject، Description، Case Number، Regarding، Created By،
Created On، Actual Start/End، Due Date، Status و Status Reason است.

### CaseBundle

واحد تحلیل Case:

```text
case_key
case_number / case_title
customer / owner / service
status / status_reason
scenario / case_description
notes[]
task_links[] -> TaskLink(task, confidence)
```

اتصال Task به Case در اولویت زیر انجام می‌شود:

1. Case Number دقیق
2. تطبیق Regarding با عنوان Case
3. نزدیک‌ترین زمان در صورت چند تطبیق
4. بدون تطبیق: unmatched

### CaseScoreBreakdown

نتیجه امتیازدهی شامل امتیاز Objective، AI، Final، Coverage، Confidence،
و فهرست `CriterionScore` است. هر معیار می‌تواند امتیاز عددی یا `N/A` داشته
باشد.

## Flow

```text
Excel
 -> LoadedSheet
 -> NoteRecord / TaskRecord
 -> CaseBundle
 -> Profile matching by Service + keywords
 -> active criteria
 -> Rule scores + AI scores
 -> N/A-aware weighted scoring
 -> reports / UI / export
```

## AI Cache

Cache در SQLite جدول `ai_cache` با Signature ذخیره می‌شود. Signature به Case،
رویدادها، معیارها و تنظیمات مؤثر Provider وابسته است؛ API key عمداً در Signature
قرار نمی‌گیرد.

Cache ناقص یا بدون معیار معتبر نباید موفق تلقی شود. پاسخ معتبر N/A می‌تواند
Cache شود، چون نشان‌دهنده تحلیل موفق با شواهد ناکافی است.

## محل نگهداری نصب قابل‌انتقال

در نگارش‌های قابل‌انتقال، داده‌های محلی کنار EXE و در پوشه
`MyBarid-AI-Portable` نگهداری می‌شوند:

```text
MyBarid-AI-Portable/
├── MyBarid-AI.exe
├── app.db
├── criteria_config.json
├── api-key.bin
└── webview2/
```

در اولین اجرای نسخه جدید، فایل‌های موجود در
`%LOCALAPPDATA%\CRMQualityReviewer` بدون حذف نسخه اصلی به این پوشه کپی
می‌شوند. `api-key.bin` با Windows DPAPI رمزنگاری شده است؛ بنابراین انتقال آن
به کاربر یا کامپیوتر دیگر ممکن است قابل‌بازگشایی نباشد و باید کلید API در مقصد
دوباره وارد شود.

## سیاست N/A

- نبود شواهد: `score=null` و `na_reason`.
- N/A از وزن مؤثر حذف می‌شود.
- N/A امتیاز منفی فرضی تولید نمی‌کند.
- نبود Task فقط در صورت Rule معتبرِ نیاز به Task نقص است؛ در غیر این صورت N/A.
