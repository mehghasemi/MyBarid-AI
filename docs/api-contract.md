# قرارداد Bridge/API

این سند قرارداد بین `ui/app.js` و `bridge.Api` است. نام متدها و فیلدها باید با
کد واقعی `bridge.py` هماهنگ بماند.

## قواعد عمومی

تمام متدهای عمومی JSON-compatible برمی‌گردانند:

```json
{"ok": true}
```

یا:

```json
{"ok": false, "error": "پیام قابل نمایش برای کاربر"}
```

خطاهای قابل انتظار باید به‌صورت `ok:false` برگردند؛ Exception خام نباید به UI
نشت کند. متدهای طولانی باید Worker باشند و UI با `get_status` یا Status مخصوص
آن‌ها Poll کند.

## چرخه Dataset

| متد | ورودی اصلی | خروجی |
|---|---|---|
| `pick_file()` | — | مسیر انتخاب‌شده یا `null` |
| `upload(notes_path, tasks_path)` | دو مسیر Excel | خلاصه بارگذاری و سلامت داده |
| `clear_dataset()` | — | وضعیت پاک‌شدن Dataset |
| `get_data_quality()` | — | Checkها و شاخص سلامت |

## تنظیمات

| متد | هدف |
|---|---|
| `get_criteria()` | معیارها، دسته‌ها، Profileها و راهنماها |
| `update_criterion(id, weight, active)` | تغییر فعال‌بودن/وزن معیار |
| `update_ratio(objective, ai)` | نسبت Objective/AI |
| `update_evaluation_profile(...)` | اتصال Service به معیارها |
| `reset_criteria()` | بازگردانی تنظیمات معیار |
| `get_ai_settings()` | تنظیمات AI بدون API key |
| `save_ai_settings(payload)` | ذخیره Provider، مدل و تنظیمات |
| `test_ai_connection()` | تست Provider با درخواست نمونه |

## تحلیل

`start_analysis(p1_start, p1_end, p2_start, p2_end, expert_group, mode,
force_ai)` یک اجرای مستقل شروع می‌کند.

- `mode="comparison"`: هر دو دوره لازم است.
- `mode="general"`: کل Dataset فعلی؛ دوره‌ها نادیده گرفته می‌شوند.
- `force_ai=true`: Cache معتبر قبلی هم استفاده نمی‌شود.
- هر اجرای جدید باید `generation` جدید داشته باشد و نتیجه قبلی را جایگزین کند.

| متد | خروجی/رفتار |
|---|---|
| `get_status()` | وضعیت Worker و درصد پیشرفت |
| `get_dashboard()` | KPI و خلاصه Mode جاری |
| `get_comparison()` | مقایسه دو دوره |
| `get_ranking()` | رتبه‌بندی کارشناسان |
| `get_cases_table(...)` | جدول صفحه‌بندی‌شده موارد |
| `get_suspicious(...)` | موارد نیازمند بررسی با Filter |
| `get_case_detail(case_key, period)` | Timeline و Breakdown یک مورد |
| `get_management_report()` | گزارش مدیریتی |

## تحلیل AI یک کیس

1. `start_case_ai_analysis(case_key, force=false)`
2. Poll با `get_case_ai_status(case_key)`
3. پس از موفقیت، `get_case_detail(case_key, "all")`

Status:

```json
{"running": false, "done": true, "error": null}
```

در صورت پاسخ معتبر N/A، `done=true` است و معیارها دلیل N/A خودشان را دارند.
فقط پاسخ بدون هیچ معیار معتبر یا خطای Provider باید `error` تولید کند.

## قرارداد Breakdown

فیلدهای اصلی:

```json
{
  "objective_score": 0,
  "ai_score": 0,
  "final_score": 0,
  "ai_used": true,
  "coverage": 0.0,
  "confidence": "low|medium|high",
  "na_criteria": 0,
  "criteria": [
    {
      "id": "criterion_id",
      "type": "RULE|AI|HYBRID",
      "score": 0,
      "evidence": "fact-based evidence",
      "na_reason": "reason when score is null",
      "source_events": []
    }
  ]
}
```

`score=null` یک وضعیت معتبر است و نباید در UI به‌عنوان خطای سرویس تفسیر شود.
## پیشنهادهای بهبود معیار

پس از تحلیل موفق، `get_case_detail` فیلد `improvement_suggestions` را نیز
برمی‌گرداند. هر پیشنهاد فقط وضعیت `proposed` دارد و اعمال خودکار ندارد:

```json
{
  "type": "add_pattern|activate_criterion|new_rule",
  "criterion_id": "notes_result_recorded",
  "title": "عنوان کوتاه",
  "problem": "شرح مشکل",
  "suggestion": "تغییر پیشنهادی",
  "evidence": "شاهد Case",
  "confidence": "low|medium|high",
  "status": "proposed"
}
```

معیارهای مجاز:
`notes_result_recorded`, `task_presence_when_needed`, `final_status_clear`,
`solution_appropriateness`, `problem_understanding`.
