# رابط کاربری

UI در `ui/index.html` تعریف و در `ui/app.js` کنترل می‌شود. Navigation از
`data-page` استفاده می‌کند و API Python از `window.pywebview.api` در دسترس است.

## بخش‌ها

### تحلیل

- `dashboard`: KPIها و خلاصه نتیجه.
- `general`: تحلیل کل Dataset بدون دو دوره صوری.
- `comparison`: مقایسه دوره اول و دوم.
- `ranking`: رتبه‌بندی کارشناسان و جزئیات.
- `cases`: جدول Caseها، فیلترها، جست‌وجو و پنجره جزئیات.
- `suspicious`: موارد نیازمند بررسی با Filter کارشناس، دلیل و نوع مورد.
- `data-quality`: Checkهای سلامت داده.
- `mgmt-report`: جمع‌بندی مدیریتی.
- `export`: خروجی Excel و CSV.

### تنظیمات و ورود داده

- `upload`: انتخاب Notes و Tasks و نمایش Validation.
- `periods`: انتخاب بازه‌ها، Mode، گروه کارشناس و اجرای تحلیل.
- `expert-groups`: ساخت و مدیریت گروه‌ها.
- `criteria`: وزن، فعال‌بودن، Profile و راهنمای معیارها.
- `ai-settings`: Provider، مدل، کلید، Preset و تست اتصال.

## رفتارهای مهم

- عملیات طولانی تحلیل از طریق Status Poll می‌شود تا UI قفل نشود.
- پنجره Case شامل Timeline، Breakdown، Evidence و دکمه بررسی تکی AI است.
- خطای AI در `case-ai-error` نمایش داده می‌شود و نباید با N/A معیار اشتباه شود.
- فیلترهای جدول باید به API واقعی متصل باشند؛ تغییر ظاهری کنترل به‌تنهایی کافی
  نیست.
- Changelog با کلیک روی نسخه جاری از `CHANGELOG.json` خوانده می‌شود.
