# معماری همگام‌سازی CRM در MyBarid-AI

این سند وضعیت واقعی همگام‌سازی Microsoft Dynamics 365 On-Premises در پروژه را
ثبت می‌کند تا توسعه‌دهنده یا مدل زبانی دیگر بتواند بدون حدس‌زدن آن را ادامه دهد.

## وضعیت فعلی

```text
CRM View
  -> دریافت صفحه‌ای با @odata.nextLink
  -> تبدیل Note/Task به مدل داخلی
  -> Merge بر اساس شناسه پایدار
  -> ذخیره Snapshot در SQLite
  -> بارگذاری Snapshot در شروع برنامه بدون اتصال CRM
```

منبع داده در این فاز فقط خواندنی است و هیچ Create، Update یا Delete روی CRM
انجام نمی‌شود.

## محل ذخیره‌سازی

در حالت Portable، Snapshot در `MyBarid-AI-Portable/app.db` و تنظیمات در همان
پوشه کنار EXE ذخیره می‌شوند. Snapshotهای CRM در جدول `crm_snapshots` قرار دارند
و شامل View، زمان دریافت، metadata و payload کامل Note/Task هستند.

## مدل دریافت افزایشی فعلی

همگام‌سازی از Watermark مبتنی بر `modifiedon` استفاده می‌کند:

| موجودیت | Watermark |
|---|---|
| Case/Incident | `max_case_modified_on` |
| Note/Annotation | `max_note_modified_on` |
| Task | `max_task_modified_on` |

Watermarkها در metadata Snapshot با کلید `watermarks` ذخیره می‌شوند. در اجرای
بعدی شرط `modifiedon > watermark` به FetchXML اضافه می‌شود و فقط رکوردهای جدید
یا تغییرکرده دریافت می‌شوند. Merge بر اساس `note_id` و `task_id` انجام می‌شود.

Snapshotهای قدیمی که Watermark نداشتند، در اولین اجرای نسخه ۱.۹.۸۶ از زمان
آخرین Snapshot به‌عنوان نقطه شروع استفاده می‌کنند تا کل داده دوباره دریافت نشود.

## حذف رکوردها

فیلتر `modifiedon` حذف‌شدن رکورد را اعلام نمی‌کند. دریافت کامل برای بررسی حذف‌ها
فقط در اولین دریافت، تغییر View، درخواست دستی کاربر یا پس از گذشت هفت روز از
آخرین Full Reconciliation انجام می‌شود. در دریافت افزایشی Snapshot قبلی حفظ
می‌شود تا بررسی کامل بعدی.

## Note و Taskهای وابسته به Case

برای Viewهای Incident، Note و Task به‌صورت دو درخواست گروهی دریافت می‌شوند و
برای هر Case درخواست جداگانه ارسال نمی‌شود. Watermark فعالیت‌ها از Watermark
Case مستقل است تا Note جدید روی Case قدیمی از دست نرود.

## Delta Link رسمی

Dynamics 365 On-Premises قابلیت Change Tracking دارد و مسیر رسمی آن
`RetrieveEntityChanges` از Organization Service است. Delta Tracking در Web API
برای Queryهای دارای فیلتر، orderby، expand یا top محدودیت دارد؛ بنابراین فعال‌کردن
ظاهری `Prefer: odata.track-changes` روی Viewهای FetchXML فعلی امن نیست.

Watermark فعلی یک جایگزین کنترل‌شده و سازگار با View است، نه Delta Link رسمی.
برای Delta رسمی باید Adapter مستقل مبتنی بر Organization Service SDK و
`RetrieveEntityChanges` ساخته و روی همین سازمان CRM آزمایش شود.

## چرخه شروع برنامه

در شروع برنامه CRM خوانده نمی‌شود؛ Snapshot محلی بازیابی و زمان آخرین دریافت
به شمسی نمایش داده می‌شود. Sync فقط با تأیید کاربر یا دکمه دریافت اجرا می‌شود.
لغو Sync نباید Snapshot قبلی را حذف کند.

## قواعد توسعه آینده

- دریافت کامل را برای هر ورود به برنامه اجرا نکنید.
- Watermark هر موجودیت را جدا نگه دارید.
- `@odata.nextLink` فقط Cursor همان اجرای Sync است و Watermark دائمی نیست.
- با تغییر View یا FetchXML، Sync کامل اجرا شود.
- رمز عبور و اطلاعات احراز هویت در log، Snapshot یا Git ثبت نشود.
