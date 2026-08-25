# Project documentation

این پوشه مرجع فنی پروژه است. هر تغییر معماری، قرارداد API، مدل داده یا تصمیم
مهم باید در همین پوشه ثبت و همراه همان Commit کد نسخه‌بندی شود.

## اسناد

- [نمای کلی سیستم](system-overview.md)
- [معماری سیستم](architecture.md)
- [ساختار Repository](repository-structure.md)
- [قرارداد Bridge/API](api-contract.md)
- [مدل داده و جریان پردازش](data-model.md)
- [رابط کاربری](ui.md)
- [Workflowهای واقعی](workflows.md)
- [مدیریت خطا و Logging](error-handling.md)
- [Configuration و Dependencyها](configuration.md)
- [اجرا، Build و Deployment](deployment.md)
- [سناریوهای واقعی](scenarios.md)
- [تصمیم‌های معماری](decisions.md)
- [راهنمای توسعه و نگهداری](development.md)

## قانون به‌روزرسانی

هر Pull/Commit که یکی از موارد زیر را تغییر می‌دهد، باید سند مربوطه را نیز
به‌روزرسانی کند:

1. امضای متدهای عمومی `bridge.Api`
2. شکل داده خروجی که UI مصرف می‌کند
3. ساختار فایل Excel یا نگاشت ستون‌ها
4. Rule، Scoring، معیارهای AI یا سیاست N/A
5. محل نگهداری تنظیمات، Cache یا کلیدها
6. روش Build، Release یا اجرای برنامه

برای هر تصمیم برگشت‌ناپذیر یا دارای اثر گسترده، یک رکورد جدید در
`decisions.md` اضافه شود؛ متن تصمیم‌های قبلی حذف یا بازنویسی نشود.
