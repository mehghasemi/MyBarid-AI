# الگوی اتصال خواندنی به Microsoft Dynamics 365 On-Premise

این سند یک الگوی قابل‌استفاده مجدد برای اتصال برنامه‌های دسکتاپ یا داخلی شرکت به
Microsoft Dynamics 365 On-Premise است. هدف، خواندن اطلاعات از View انتخاب‌شده،
ذخیره Snapshot محلی و انجام همگام‌سازی افزایشی است؛ در این الگو هیچ عملیات
نوشتن، ویرایش یا حذف روی CRM انجام نمی‌شود.

> این سند برای انتقال به برنامه‌ها یا مدل‌های زبانی دیگر نوشته شده است. مقادیر
> سازمان، View، موجودیت و فیلدها باید برای هر پروژه بررسی و جایگزین شوند.

## 1. مشخصات نمونه این پروژه

```text
CRM Base URL:       https://crm.baridsoft.ir
Organization:       Main
API Version:        v9.1
API Root:           https://crm.baridsoft.ir/Main/api/data/v9.1/
Entity:             annotation (Note)
View:               TESTNOTE
Access mode:        Read-only
Network assumption: داخل شبکه شرکت
```

آدرس واقعی API از ترکیب زیر ساخته می‌شود:

```text
{base_url}/{organization}/api/data/{api_version}/
```

برای نمونه:

```text
https://crm.baridsoft.ir/Main/api/data/v9.1/
```

## 2. پیش‌نیازهای سمت CRM

کاربر CRM باید:

1. از داخل شبکه سازمان به CRM دسترسی داشته باشد.
2. مجوز خواندن موجودیت‌های زیر را داشته باشد:
   - `UserQuery` برای Viewهای شخصی
   - `SavedQuery` برای Viewهای سازمانی
   - `Annotation` برای Noteها
   - موجودیت مرتبط Case/Incident و فیلدهای مورد نیاز View
3. بتواند View موردنظر را در CRM ببیند یا View برای او Share شده باشد.
4. در صورت نیاز، مجوز خواندن فیلدهای Lookup و Option Set را نیز داشته باشد.

در این پروژه View `TESTNOTE` باید روی موجودیت `annotation` باشد. اگر View روی
موجودیت دیگری باشد، برنامه باید خطای واضح بدهد و از اجرای Query نادرست جلوگیری
کند.

## 3. تشخیص نوع ورود و احراز هویت

### روش پیش‌فرض پیشنهادی: Windows Integrated Authentication

برای Dynamics 365 On-Premise داخل شبکه، ابتدا از حساب Windows جاری استفاده شود:

```powershell
Invoke-WebRequest `
  -Uri "https://crm.example.local/Org/api/data/v9.1/WhoAmI" `
  -UseDefaultCredentials `
  -Headers @{
    Accept = "application/json"
    "OData-Version" = "4.0"
    Prefer = 'odata.include-annotations="*"'
  }
```

این روش برای محیط‌های Windows Authentication مناسب است و رمز عبور کاربر را
در برنامه ذخیره نمی‌کند.

### روش جایگزین: نام کاربری و رمز عبور

فقط اگر سازمان به‌صورت مشخص احراز هویت جداگانه می‌خواهد، فرم ورود برنامه
می‌تواند نام کاربری و رمز عبور را بگیرد. رمز عبور نباید در URL، لاگ، Command
Line یا متن خطا ثبت شود.

```powershell
$secure = ConvertTo-SecureString $password -AsPlainText -Force
$credential = New-Object System.Management.Automation.PSCredential(
  $username, $secure
)

Invoke-WebRequest `
  -Uri $url `
  -Credential $credential `
  -Headers @{
    Accept = "application/json"
    "OData-Version" = "4.0"
    Prefer = 'odata.include-annotations="*"'
  }
```

### تشخیص عملی نوع ورود

برنامه باید این مراحل را انجام دهد:

1. ابتدا `WhoAmI` را با `-UseDefaultCredentials` اجرا کند.
2. اگر پاسخ موفق بود، نوع ورود را `Windows Integrated` اعلام کند.
3. اگر پاسخ `401` یا `403` بود، علت را واضح نمایش دهد.
4. فقط در صورت فعال بودن گزینه ورود دستی، Credential واردشده را امتحان کند.
5. تفاوت «عدم دسترسی» با «آدرس اشتباه» و «View پیدا نشد» در پیام خطا حفظ شود.

## 4. آزمون اتصال

اولین درخواست باید سبک و بدون دریافت Dataset باشد:

```http
GET {api_root}/WhoAmI
Accept: application/json
OData-Version: 4.0
Prefer: odata.include-annotations="*"
```

پاسخ موفق معمولاً شامل شناسه کاربر، واحد کسب‌وکار و سازمان است. پس از موفقیت،
برنامه باید فقط وضعیت اتصال و کاربر را نمایش دهد؛ واکشی اطلاعات نباید خودکار
در همین مرحله انجام شود.

## 5. دریافت فهرست Viewها

برای Viewهای شخصی:

```http
GET {api_root}/userqueries?$select=name,userqueryid,returnedtypecode,fetchxml
```

برای Viewهای سازمانی:

```http
GET {api_root}/savedqueries?$select=name,savedqueryid,returnedtypecode,fetchxml
```

فقط Viewهایی که شرایط زیر را دارند در فهرست نمایش داده شوند:

```text
name خالی نباشد
returnedtypecode == "annotation"
کاربر مجوز خواندن View را داشته باشد
```

برای جلوگیری از Query دستی و خطای تایپی، نام View باید از فهرست خوانده‌شده از
CRM در یک ComboBox نمایش داده شود. مقدار انتخاب‌شده و شناسه View در تنظیمات
محلی ذخیره شود.

## 6. دریافت FetchXML View

پس از انتخاب View، از `userqueries` یا `savedqueries`، مقدار `fetchxml` خوانده
شود. برنامه نباید FetchXML را به‌صورت حدسی از روی نام View بسازد.

نمونه Query:

```http
GET {api_root}/userqueries?
  $select=name,userqueryid,returnedtypecode,fetchxml&
  $filter=name eq 'TESTNOTE'
```

قبل از اجرا:

1. XML با Parser معتبر خوانده شود.
2. وجود `entity` بررسی شود.
3. موجودیت با موجودیت مورد انتظار تطبیق داده شود.
4. در صورت نبود FetchXML، اجرای واکشی متوقف شود.
5. فیلترهای اصلی View حفظ شوند.

## 7. اجرای View و دریافت رکوردها

برای موجودیت Note:

```http
GET {api_root}/annotations?fetchXml={url_encoded_fetchxml}
```

Headerهای پیشنهادی:

```text
Accept: application/json
OData-Version: 4.0
Prefer: odata.include-annotations="*"
```

`fetchXml` باید URL-Encode شود. زمان Timeout باید محدود باشد؛ در این پروژه
Timeout درخواست ۱۲۰ ثانیه و Timeout کل PowerShell حدود ۱۵۰ ثانیه در نظر گرفته
شده است.

## 8. صفحه‌بندی پاسخ

پاسخ ممکن است تمام رکوردها را در یک درخواست برنگرداند. همیشه این موارد بررسی
شوند:

```json
{
  "value": [],
  "@odata.nextLink": "https://..."
}
```

تا زمانی که `@odata.nextLink` وجود دارد، درخواست بعدی اجرا شود. برای جلوگیری از
حلقه بی‌نهایت، سقف تعداد صفحات تعیین شود؛ در این پروژه سقف ۱۰۰۰ صفحه است.

تعداد نهایی Dataset باید برابر مجموع رکوردهای همه صفحات باشد، نه تعداد رکوردهای
صفحه اول.

## 9. نگاشت فیلدها

نگاشت باید در یک Adapter مستقل انجام شود و UI مستقیماً به نام فیلدهای خام CRM
وابسته نباشد.

نمونه نگاشت مورد استفاده در این پروژه:

| مفهوم داخلی | فیلدهای ممکن CRM |
|---|---|
| شناسه Note | `annotationid` |
| متن Note | `notetext` |
| شماره Case | `ac.ticketnumber` یا `ticketnumber` |
| عنوان Case | `ac.title` یا `title` |
| مشتری | `ac.customerid` |
| مالک/کارشناس | `ac.ownerid` یا `ac.brd_assignto` |
| سرویس | `ac.brd_caseservice` یا `ac.brd_service` |
| وضعیت | `ac.statecode` |
| دلیل وضعیت | `ac.statuscode` |
| تاریخ ایجاد Case | `ac.createdon` |
| ایجادکننده Case | `ac.createdby` |
| تاریخ Note | `modifiedon` یا `createdon` |
| نویسنده Note | `modifiedby` یا `createdby` |
| نوع مورد | `ac.brd_incidenttype` |
| شرح Case | `ac.description` |
| سناریو | `ac.brd_scenario` |

### Lookup و Option Set

برای نمایش عنوان به‌جای GUID یا کد عددی، باید از Annotationهای OData استفاده شود:

```text
{field}@OData.Community.Display.V1.FormattedValue
```

قاعده نمایش:

1. ابتدا مقدار FormattedValue استفاده شود.
2. اگر مقدار نمایشی نبود، مقدار خام فقط در صورت خوانا بودن استفاده شود.
3. GUID خام یا کد عددی بدون برچسب به کاربر نمایش داده نشود.
4. در نبود برچسب، مقدار «نامشخص» یا «—» نمایش داده شود، نه `????`.

## 10. تبدیل به Dataset داخلی

رکوردهای CRM پس از نگاشت به مدل‌های داخلی تبدیل شوند:

```text
CRM rows
  -> NoteRecord / TaskRecord
  -> اعتبارسنجی
  -> CaseBundle
  -> Dataset
```

اتصال Note به Case باید با شناسه یا شماره Case انجام شود. اگر اتصال قطعی نبود:

- رکورد حذف نشود.
- در `unmatched_tasks` یا گزارش سلامت داده ثبت شود.
- در UI قابل مشاهده باشد.
- در Ruleها به‌عنوان نقص قطعی فرض نشود.

## 11. Snapshot محلی

پس از واکشی موفق، Dataset باید در بانک محلی ذخیره شود. هدف Snapshot این است
که کاربر هنگام ورود دوباره به برنامه بدون اتصال مجدد به CRM بتواند:

- موارد را ببیند.
- گرید جزئیات را باز کند.
- نتایج تحلیل قبلی را مشاهده کند.
- زمان آخرین واکشی را ببیند.

ساختار پیشنهادی:

```text
crm_snapshots
  source
  view_name
  fetched_at
  metadata
  payload
```

در این پروژه بانک `app.db` از SQLite استفاده می‌کند و `payload` شامل Noteها و
در آینده Taskها است.

## 12. به‌روزرسانی افزایشی

برنامه نباید هر بار کل View را بدون دلیل دوباره دریافت کند. فرآیند پیشنهادی:

1. آخرین Snapshot و زمان `fetched_at` خوانده شود.
2. View انتخاب‌شده و Hash مربوط به FetchXML با Snapshot قبلی مقایسه شود.
3. اگر View تغییر کرده، یا همگام‌سازی کامل درخواست شده، Full Sync انجام شود.
4. در غیر این صورت، زمان آخرین واکشی به‌عنوان Watermark استفاده شود.
5. شرط زیر به FetchXML اضافه شود:

```xml
<condition attribute="modifiedon"
           operator="gt"
           value="2026-08-29T10:30:00Z" />
```

6. رکوردهای جدید و تغییرکرده دریافت شوند.
7. رکوردهای جدید با Snapshot قبلی Merge شوند.
8. رکورد بر اساس شناسه پایدار مانند `annotationid` جایگزین شود.
9. Snapshot جدید با زمان دقیق ذخیره شود.

### نکته مهم درباره حذف رکوردها

فیلتر `modifiedon > watermark` رکوردهای حذف‌شده را پیدا نمی‌کند. اگر حذف‌ها مهم
هستند، باید یکی از این روش‌ها استفاده شود:

- Full Sync دوره‌ای، مثلاً هر ۱۰ بار همگام‌سازی.
- Change Tracking در صورت فعال بودن روی سازمان.
- ستون وضعیت حذف/غیرفعال در View.
- فرآیند جداگانه برای دریافت حذف‌ها.

در این پروژه برای جلوگیری از قدیمی‌شدن دائمی Snapshot، Full Sync دوره‌ای در
نظر گرفته شده است.

## 13. تشخیص تغییر Dataset

برای تشخیص اینکه نتیجه تحلیل مربوط به داده فعلی است یا Snapshot قدیمی، یک
Dataset ID پایدار ساخته شود:

```text
1. payload را Deep Copy کن.
2. Notes و Tasks را بر اساس شناسه مرتب کن.
3. JSON را با sort_keys=True و UTF-8 تولید کن.
4. SHA-256 بگیر.
```

ترتیب برگشت رکوردها نباید باعث تغییر Dataset ID شود.

نتیجه تحلیل باید همراه این اطلاعات ذخیره شود:

```text
result
dataset_id
dataset_id_version
view_name
saved_at
```

اگر `dataset_id` نتیجه با Snapshot فعلی متفاوت بود:

- نتیجه قبلی حذف یا مخفی نشود.
- نتیجه برای مشاهده قابل دسترس بماند.
- وضعیت `stale=true` نمایش داده شود.
- اجرای تحلیل جدید فقط با درخواست صریح کاربر انجام شود.

## 14. جداسازی واکشی، تحلیل و نمایش

این سه عملیات باید مستقل باشند:

```text
CRM Fetch/Sync
      |
      v
Local Snapshot
      |
      +--> Details Grid (بدون نیاز به تحلیل)
      |
      +--> Analysis (اختیاری و با انتخاب کاربر)
                    |
                    v
             Local Analysis Result
```

گرید جزئیات باید از Snapshot محلی خوانده شود و نباید به وجود نتیجه تحلیل وابسته
باشد. ستون‌های امتیاز و AI در نبود تحلیل خالی یا `N/A` باشند، اما شماره، عنوان،
کارشناس، سرویس، Note و Task همچنان نمایش داده شوند.

## 15. رفتار شروع برنامه

در شروع برنامه:

1. به CRM وصل نشو.
2. View را واکشی نکن.
3. Excel را خودکار نخوان.
4. آخرین Snapshot محلی را بازیابی کن.
5. زمان آخرین واکشی را به تاریخ و ساعت شمسی نمایش بده.
6. اگر کاربر خواست، دکمه «دریافت داده از CRM» را اجرا کن.
7. پس از واکشی موفق، Dataset و Snapshot را به‌روزرسانی کن.

برای استفاده سریع، برنامه می‌تواند پیام زیر را نشان دهد:

```text
آخرین داده محلی در تاریخ و ساعت ... دریافت شده است.
آیا می‌خواهید داده‌های جدید و تغییرکرده از CRM دریافت شود؟
```

دکمه «انصراف» باید فقط عملیات واکشی جاری را متوقف کند و Snapshot قبلی را
حذف نکند.

## 16. مدیریت خطا

| وضعیت | پیام مناسب |
|---|---|
| آدرس اشتباه | آدرس API معتبر نیست یا سرویس قابل دسترسی نیست |
| `401` | احراز هویت انجام نشد؛ حساب Windows یا Credential را بررسی کنید |
| `403` | کاربر به View یا موجودیت موردنظر مجوز خواندن ندارد |
| View پیدا نشد | View برای کاربر جاری Share نشده یا نام آن اشتباه است |
| View روی موجودیت اشتباه | View انتخاب‌شده روی Note/annotation نیست |
| پاسخ خالی | CRM پاسخ JSON خالی برگرداند؛ اتصال و احراز هویت بررسی شود |
| JSON نامعتبر | پاسخ CRM قابل خواندن نیست؛ احتمالاً خطای Proxy یا Login است |
| Timeout | دریافت طولانی شد؛ شبکه، فیلتر View و تعداد رکوردها بررسی شود |
| `nextLink` تکراری | همگام‌سازی متوقف و خطای صفحه‌بندی ثبت شود |
| فیلد بدون Label | مقدار نمایشی موجود نیست؛ از نمایش GUID یا کد خام خودداری شود |

جزئیات فنی برای توسعه‌دهنده در لاگ ثبت شود، اما رمز عبور، API Key و Token هرگز
در لاگ، UI یا Git ثبت نشوند.

## 17. امنیت

- اتصال CRM در این الگو Read-only است.
- هیچ Endpoint نوشتنی در Client expose نشود.
- از ساختن Command با الحاق مستقیم ورودی کاربر خودداری شود.
- URL و Credential از طریق Environment یا Argument امن به PowerShell منتقل شود.
- پسورد در متن Command، لاگ و Exception نیاید.
- برای نگهداری Secret از Windows DPAPI یا Credential Manager استفاده شود.
- فایل‌های حاوی Secret در Git Commit نشوند.
- `app.db` و Snapshot ممکن است حاوی اطلاعات حساس مشتریان باشند؛ دسترسی فایل
  محدود و Backupها رمزگذاری شوند.

## 18. ساختار پیشنهادی برای برنامه‌های دیگر

```text
crm/
  client.py          # اتصال، احراز هویت و درخواست HTTP/PowerShell
  views.py           # فهرست Viewها و دریافت FetchXML
  mapper.py          # نگاشت فیلدها و Labelها
  sync.py            # Full/Incremental Sync و Merge
  models.py          # مدل‌های داخلی Note/Task/Case
storage/
  snapshots.py       # ذخیره و بازیابی Snapshot
analysis/
  engine.py          # تحلیل مستقل از CRM
ui/
  connection-form    # تنظیمات و آزمون اتصال
  details-grid       # نمایش Snapshot محلی
```

قرارداد پیشنهادی Client:

```python
class ReadOnlyDynamicsClient:
    def test_connection(self) -> dict: ...
    def list_views(self) -> list[dict]: ...
    def get_view_fetchxml(self, view_id: str) -> str: ...
    def fetch_view(self, view_id: str, since=None) -> tuple[list[dict], dict]: ...
```

قرارداد پیشنهادی Sync:

```python
class SnapshotSync:
    def full_sync(self, view_id: str) -> SyncResult: ...
    def incremental_sync(self, view_id: str) -> SyncResult: ...
    def get_latest_snapshot(self, view_id: str) -> Snapshot | None: ...
```

## 19. چک‌لیست پیاده‌سازی در App دیگر

- [ ] Base URL، Organization و API Version از تنظیمات گرفته می‌شوند.
- [ ] `WhoAmI` قبل از واکشی Dataset تست می‌شود.
- [ ] Windows Authentication اولویت دارد.
- [ ] فهرست Viewها از CRM خوانده می‌شود.
- [ ] View فقط در صورت `returnedtypecode == annotation` قابل انتخاب است.
- [ ] FetchXML از خود View خوانده می‌شود.
- [ ] FetchXML URL-Encode می‌شود.
- [ ] `@odata.nextLink` تا پایان دنبال می‌شود.
- [ ] فیلدهای Lookup و Option Set با FormattedValue نمایش داده می‌شوند.
- [ ] Snapshot محلی پس از واکشی موفق ذخیره می‌شود.
- [ ] شروع برنامه به CRM متصل نمی‌شود.
- [ ] گرید جزئیات قبل از تحلیل نیز داده دارد.
- [ ] Full و Incremental Sync از هم جدا هستند.
- [ ] حذف‌ها با Full Sync دوره‌ای پوشش داده می‌شوند.
- [ ] Dataset ID پایدار برای اعتبار نتیجه تحلیل ساخته می‌شود.
- [ ] نتیجه قدیمی مخفی نمی‌شود و فقط Stale علامت می‌خورد.
- [ ] لغو واکشی Snapshot قبلی را حذف نمی‌کند.
- [ ] هیچ رمز، Token یا API Key در Git ثبت نمی‌شود.

## 20. متن آماده برای دادن به مدل یا برنامه‌نویس دیگر

```text
برای این برنامه یک اتصال Read-only به Microsoft Dynamics 365 On-Premise طراحی کن.
ابتدا با Windows Integrated Authentication و WhoAmI اتصال را تست کن و فقط در
صورت نیاز Credential دستی را فعال کن. فهرست Viewهای شخصی و سازمانی را از
userqueries و savedqueries بخوان و فقط Viewهای موجودیت annotation را نمایش بده.
FetchXML را از View انتخاب‌شده دریافت کن و آن را بدون حذف فیلترهای اصلی اجرا کن.
پاسخ‌های OData را با دنبال‌کردن @odata.nextLink صفحه‌بندی کن. فیلدهای Lookup و
Option Set را با OData FormattedValue به برچسب قابل‌خواندن تبدیل کن.

نتیجه واکشی را به‌صورت Snapshot در بانک محلی ذخیره کن. برنامه هنگام شروع نباید
خودکار به CRM وصل شود؛ آخرین Snapshot باید بدون شبکه قابل مشاهده باشد. گرید
جزئیات باید قبل از اجرای تحلیل هم داده داشته باشد. برای به‌روزرسانی، در حالت
عادی از modifiedon و watermark استفاده کن و Full Sync دوره‌ای برای پوشش حذف‌ها
انجام بده. برای Snapshot یک SHA-256 پایدار بساز و نتیجه تحلیل را با dataset_id
ذخیره کن. اگر Snapshot تغییر کرد، نتیجه قبلی را حذف نکن؛ آن را stale علامت بزن
و تحلیل مجدد را فقط با تأیید صریح کاربر انجام بده. هیچ عملیات Create، Update یا
Delete روی CRM پیاده‌سازی نکن و Secretها را در لاگ یا Git ذخیره نکن.
```

## 21. وضعیت فعلی این پروژه

در پیاده‌سازی فعلی MyBarid-AI:

- اتصال به `https://crm.baridsoft.ir/Main/api/data/v9.1/` انجام می‌شود.
- احراز هویت پیش‌فرض با حساب Windows جاری است.
- Viewهای Note قابل فهرست‌شدن هستند.
- View `TESTNOTE` با FetchXML خوانده می‌شود.
- صفحه‌بندی OData پشتیبانی می‌شود.
- Snapshot محلی در `app.db` ذخیره می‌شود.
- Dataset و نتیجه تحلیل هنگام شروع قابل بازیابی هستند.
- دریافت Task از CRM هنوز در این مرحله انجام نمی‌شود و `tasks` خالی است؛ برای
  دریافت Task باید View/Query و نگاشت موجودیت Task جداگانه طراحی و پیاده‌سازی شود.
- عملیات CRM در این فاز فقط خواندنی است.

