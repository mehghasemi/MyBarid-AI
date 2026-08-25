# Workflowهای واقعی

## بارگذاری داده

```text
انتخاب Notes/Tasks
 -> bridge.upload
 -> load_excel
 -> detect_mapping
 -> normalize_notes / normalize_tasks
 -> build_cases
 -> نمایش خلاصه و هشدارهای سلامت داده
```

خطای فایل، Sheet خالی یا ستون ضروریِ ناشناخته باید قبل از تحلیل با پیام قابل
نمایش متوقف شود.

## تحلیل کلی

```text
انتخاب General
 -> start_analysis(mode="general")
 -> کپی Dataset جاری
 -> انتخاب Case یا Task بر اساس unit
 -> analyze_cases در حالت Case
 -> Rule + Score
 -> Dashboard / Ranking / Suspicious / Export
```

در این مسیر دو دوره ساخته نمی‌شود.

## مقایسه دو دوره

```text
انتخاب دو بازه
 -> Filter Notes/Tasks هر بازه
 -> ساخت CaseBundle مستقل برای هر دوره
 -> تحلیل AI هر دوره در صورت فعال‌بودن
 -> Scoring
 -> compare_periods
 -> Comparison / Ranking / Reports
```

هر اجرای جدید باید نتیجه و Status اجرای قبلی را جایگزین کند.

## بررسی AI یک Case

```text
کلیک بررسی Case
 -> start_case_ai_analysis
 -> Worker
 -> Provider.complete
 -> extract_json
 -> validate_case_analysis
 -> ذخیره Cache معتبر
 -> score_case
 -> get_case_detail
 -> نمایش Evidence و N/A
```

پاسخ معتبرِ همه معیارها با `score=null` و `na_reason` موفق است؛ Provider error،
JSON نامعتبر یا پاسخ فاقد هر معیار معتبر خطا است.

## Export/Import تنظیمات

Export شامل Criteria، Ratio، Expert Groups و تنظیمات Provider است و Secret را
حذف می‌کند. Import در حالت `merge` گروه‌ها را ادغام و در حالت `replace` جایگزین
می‌کند. کلید API باید در مقصد جداگانه ثبت شود.
## پیشنهاد بهبود پس از تحلیل AI

در همان پاسخ تحلیل، AI می‌تواند برای پنج معیار منتخب پیشنهاد
`add_pattern`، `activate_criterion` یا `new_rule` تولید کند. پیشنهادها
اعتبارسنجی و ذخیره می‌شوند و در پنجره Case با برچسب «فقط پیشنهاد» نمایش داده
می‌شوند؛ هیچ Rule یا امتیازی خودکار تغییر نمی‌کند.
