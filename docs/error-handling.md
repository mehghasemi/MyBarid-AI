# مدیریت خطا و Logging

## لایه‌ها

- `data.loader`: `ExcelLoadError` برای فایل ناموجود، Workbook خالی یا فرمت
  ناسازگار.
- `bridge.Api`: خطاهای قابل انتظار را به `ok:false` و پیام فارسی تبدیل می‌کند.
- `pipeline`: خطای یک Case در AI نباید کل تحلیل Dataset را متوقف کند؛ در
  `ai_errors` ثبت می‌شود.
- `ai.providers`: خطای HTTP، شبکه، JSON و ساختار پاسخ به `AIProviderError`
  تبدیل می‌شود.
- UI: نتیجه را در `err-box` یا Toast نمایش می‌دهد.
- `main.py`: خطای راه‌اندازی WebView2 را در Console و MessageBox نشان می‌دهد.

## Logging فعلی

سیستم Logging مرکزی فایل‌محور ندارد. بخشی از Exceptionها با
`traceback.print_exc()` در Console چاپ می‌شوند و کاربر پیام خلاصه دریافت می‌کند.
برای پشتیبانی Production، اضافه‌کردن Logger چرخشی با حذف داده حساس یک Technical
Debt است.

## اصول امنیتی

- API key در Documentation، Export و Log ثبت نمی‌شود.
- پاسخ خام Provider نباید همراه داده مشتری در Log دائمی ذخیره شود.
- متن خطا باید برای کاربر قابل فهم و برای Developer دارای Context کافی باشد.

## خطاهای شناخته‌شده

- نبود WebView2 یا نسخه قدیمی می‌تواند Startup را متوقف کند.
- تغییر نام ستون Excel ممکن است Mapping را ناقص کند.
- Provider نامعتبر یا مدل حذف‌شده خطای سرویس می‌دهد.
- N/A معتبر خطا نیست و باید با `na_reason` نمایش داده شود.
