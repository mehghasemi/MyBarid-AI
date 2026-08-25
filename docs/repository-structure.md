# ساختار Repository

| مسیر | نقش |
|---|---|
| `main.py` | Entry point و WebView2 |
| `bridge.py` | API عمومی Python ↔ UI و Workerهای تحلیل |
| `pipeline.py` | Load، Filter، تحلیل کلی/مقایسه و تجمیع |
| `data/` | Loader، Mapper، Validator و Case Builder |
| `analysis/` | Rule، Scoring، Comparison، Ranking و Data Health |
| `ai/` | Provider، Prompt، Schema، Retry و Cache |
| `config/` | JSON معیارها و مدل CriteriaConfig |
| `database/` | SQLite و رمزنگاری کلید API |
| `reports/` | Excel، CSV و گزارش کارشناس |
| `ui/` | HTML، CSS، JavaScript و فونت/Chart vendor |
| `tests/` | Unit و Regression tests |
| `docs/` | Living Documentation |
| `AGENTS.md` | راهنمای سریع و کم‌مصرف برای عامل توسعه |
| `VERSION` | نسخه جاری |
| `CHANGELOG.json` | تاریخچه نگارش‌ها |
| `MyBarid-AI.spec` | Build PyInstaller |
| `run.cmd` | اجرای Development با venv محلی |

## نقطه‌های حساس

- تغییر `bridge.py` روی قرارداد UI اثر مستقیم دارد.
- تغییر `config/v2_criteria.json` می‌تواند امتیازهای همه Caseها را تغییر دهد.
- تغییر `analysis/scoring.py` روی Dashboard، Ranking و Export اثر دارد.
- تغییر `data/mapper.py` می‌تواند کل داده ورودی را جابه‌جا کند.
- تغییر Signature یا Schema در `ai/analyzer.py` روی Cache اثر دارد.
