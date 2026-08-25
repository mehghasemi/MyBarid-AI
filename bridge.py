from __future__ import annotations

import json
import threading
import traceback
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from ai.providers import AISettings
from analysis.timeline import build_timeline
from config.criteria_config import Category, Criterion, CriteriaConfig, load_criteria_config, save_criteria_config
import webview
from data.loader import ExcelLoadError
from database import db
from pipeline import Dataset, run_full_analysis
import pipeline as pipeline_mod
from reports.csv_export import export_csv
from reports.employee_report_export import export_expert_report_excel as export_expert_report_excel_file
from reports.excel_export import export_excel

USER_CONFIG_PATH = db.app_data_dir() / "criteria_config.json"
VERSION_FILE = Path(__file__).resolve().parent / "VERSION"


def get_app_version() -> str:
    if VERSION_FILE.exists():
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    return "0.0.0"


def _iso(dt):
    return dt.isoformat() if isinstance(dt, datetime) else None


def _parse_period_bound(value: str, end: bool) -> datetime:
    """ورودی می‌تواند فقط تاریخ («YYYY-MM-DD») یا تاریخ+ساعت باشد. اگر فقط
    تاریخ داده شود (رفتار جدید UI که ساعت را حذف کرده)، برای شروع بازه
    ساعت ۰۰:۰۰:۰۰ و برای پایان بازه ساعت ۲۳:۵۹:۵۹ در نظر گرفته می‌شود تا کل
    همان روز پوشش داده شود."""
    dt = datetime.fromisoformat(value)
    if "T" not in value and " " not in value:  # فقط تاریخ، بدون بخش ساعت
        if end:
            dt = dt.replace(hour=23, minute=59, second=59)
    return dt


class Api:
    def __init__(self):
        self.window = None
        self.dataset: Dataset | None = None
        self.config: CriteriaConfig = self._load_config()
        self.ai_settings: AISettings = self._load_ai_settings()
        self.result: dict | None = None
        self.last_periods: tuple | None = None
        self.status = {"running": False, "done": False, "stage": "", "current": 0, "total": 0, "error": None}
        self._lock = threading.Lock()

    def set_window(self, window):
        self.window = window

    def get_version(self) -> str:
        return get_app_version()

    # ------------------------------------------------------------- config --

    def _load_config(self) -> CriteriaConfig:
        if USER_CONFIG_PATH.exists():
            try:
                return load_criteria_config(USER_CONFIG_PATH)
            except Exception:
                pass
        return load_criteria_config()

    def _load_ai_settings(self) -> AISettings:
        stored = db.get_setting("ai_settings", {}) or {}
        settings = AISettings(**{**asdict(AISettings()), **stored})
        settings.api_key = db.load_api_key()
        return settings

    # -------------------------------------------------------------- files --

    def pick_file(self) -> str | None:
        if not self.window:
            return None
        try:
            dialog_type = getattr(getattr(webview, "FileDialog", None), "OPEN", webview.OPEN_DIALOG)
            result = self.window.create_file_dialog(
                dialog_type, file_types=("Excel Files (*.xlsx)",),
                allow_multiple=False,
            )
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            return None
        return result[0] if result else None

    def pick_save_path(self, suggested_name: str) -> str | None:
        if not self.window:
            return None
        try:
            dialog_type = getattr(getattr(webview, "FileDialog", None), "SAVE", webview.SAVE_DIALOG)
            result = self.window.create_file_dialog(
                dialog_type, save_filename=suggested_name
            )
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            return None
        return result if isinstance(result, str) else (result[0] if result else None)

    def upload(self, notes_path: str, tasks_path: str) -> dict:
        try:
            self.dataset = pipeline_mod.load_dataset(notes_path, tasks_path)
        except ExcelLoadError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            return {"ok": False, "error": f"خطای غیرمنتظره در پردازش فایل: {exc}"}

        ns, ts = self.dataset.notes_summary, self.dataset.tasks_summary
        dates = [n.note_date for n in self.dataset.notes if n.note_date] + \
                [t.created_on for t in self.dataset.tasks if t.created_on]
        bounds = {"min": _iso(min(dates)), "max": _iso(max(dates))} if dates else {"min": None, "max": None}
        return {
            "ok": True,
            "notes_summary": _summary_to_dict(ns),
            "tasks_summary": _summary_to_dict(ts),
            "total_cases": len(self.dataset.cases),
            "unmatched_tasks": len(self.dataset.unmatched_tasks),
            "date_bounds": bounds,
        }

    def clear_dataset(self) -> dict:
        self.dataset = None
        self.result = None
        return {"ok": True}

    # -------------------------------------------------------- expert groups

    DEFAULT_GROUP_TEMPLATES = {
        "Help Desk": {
            "review_unit": "case",
            "names": ["مرندی", "حدادی", "جلالی", "فتحعلی", "مهدوی‌نیا", "امیر حسین فیض"],
        },
        "پشتیبانی فنی": {
            "review_unit": "task",
            "names": ["بندلو", "نورمحمدی", "کتاب‌الهی", "محمد حسن فتوحی", "قاسم آزادهو", "علی روایی", "حامد عابدی"],
        },
    }

    def get_detected_experts(self) -> dict:
        if not self.dataset:
            return {"ok": False, "experts": []}
        from analysis.experts import primary_expert
        case_experts = {primary_expert(c) for c in self.dataset.cases.values()}
        task_experts = {t.created_by for t in self.dataset.tasks if t.created_by}
        experts = sorted(case_experts | task_experts)
        return {"ok": True, "experts": experts}

    def get_expert_groups(self) -> dict:
        groups = db.get_setting("expert_groups", {}) or {}
        # سازگاری با قالب قدیمی (فقط لیست کارشناسان، بدون review_unit)
        normalized = {}
        for name, value in groups.items():
            if isinstance(value, list):
                normalized[name] = {"experts": value, "review_unit": "case"}
            else:
                normalized[name] = value
        return {"ok": True, "groups": normalized}

    def save_expert_group(self, name: str, experts: list[str], review_unit: str = "case") -> dict:
        name = (name or "").strip()
        if not name:
            return {"ok": False, "error": "نام گروه نمی‌تواند خالی باشد."}
        if not experts:
            return {"ok": False, "error": "حداقل یک کارشناس باید انتخاب شود."}
        if review_unit not in ("case", "task"):
            return {"ok": False, "error": "واحد بررسی نامعتبر است."}
        groups = db.get_setting("expert_groups", {}) or {}
        groups[name] = {"experts": experts, "review_unit": review_unit}
        db.set_setting("expert_groups", groups)
        return {"ok": True}

    def delete_expert_group(self, name: str) -> dict:
        groups = db.get_setting("expert_groups", {}) or {}
        groups.pop(name, None)
        db.set_setting("expert_groups", groups)
        return {"ok": True}

    @staticmethod
    def _normalize_name(text: str) -> str:
        return "".join((text or "").split()).replace("\u200c", "").casefold()

    def suggest_default_groups(self) -> dict:
        """پیشنهاد اعضای دو گروه پیش‌فرض (Help Desk / پشتیبانی فنی) بر اساس
        تطبیق تقریبی نام‌های داده‌شده با نام کامل کارشناسان شناسایی‌شده در
        داده واقعی. چیزی ذخیره نمی‌شود؛ فقط برای تأیید کاربر برگردانده می‌شود."""
        if not self.dataset:
            return {"ok": False, "error": "ابتدا فایل‌ها را بارگذاری کنید."}
        detected = self.get_detected_experts()["experts"]
        norm_map = {self._normalize_name(e): e for e in detected}

        result = {}
        for group_name, tmpl in self.DEFAULT_GROUP_TEMPLATES.items():
            entries = []
            for target in tmpl["names"]:
                target_norm = self._normalize_name(target)
                matches = [full for norm, full in norm_map.items() if target_norm in norm or norm in target_norm]
                matches = sorted(set(matches))
                entries.append({
                    "target": target,
                    "matches": matches,
                    "status": "matched" if len(matches) == 1 else ("ambiguous" if len(matches) > 1 else "not_found"),
                })
            result[group_name] = {"review_unit": tmpl["review_unit"], "entries": entries}
        return {"ok": True, "suggestions": result}

    def create_default_groups(self, selections: dict) -> dict:
        """selections: { group_name: {"review_unit": "...", "experts": [نام‌های نهایی تأییدشده]} }"""
        groups = db.get_setting("expert_groups", {}) or {}
        created = []
        for group_name, payload in selections.items():
            experts = payload.get("experts") or []
            if not experts:
                continue
            groups[group_name] = {"experts": experts, "review_unit": payload.get("review_unit", "case")}
            created.append(group_name)
        db.set_setting("expert_groups", groups)
        return {"ok": True, "created": created}

    # -------------------------------------------------- export/import settings

    SETTINGS_EXPORT_VERSION = 1

    def export_settings(self, path: str) -> dict:
        try:
            payload = {
                "export_version": self.SETTINGS_EXPORT_VERSION,
                "criteria_config": self.config.to_dict(),
                "expert_groups": db.get_setting("expert_groups", {}) or {},
                "ai_settings": {  # عمداً بدون api_key (ریسک امنیتی انتقال کلید محرمانه بین سیستم‌ها)
                    "provider": self.ai_settings.provider, "model": self.ai_settings.model,
                    "base_url": self.ai_settings.base_url, "temperature": self.ai_settings.temperature,
                    "max_tokens": self.ai_settings.max_tokens, "batch_size": self.ai_settings.batch_size,
                    "enabled": self.ai_settings.enabled,
                },
            }
            Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return {"ok": True, "path": path}
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            return {"ok": False, "error": f"خطا در ذخیره فایل تنظیمات: {exc}"}

    def import_settings(self, path: str, mode: str = "merge") -> dict:
        """mode: 'merge' (گروه‌های جدید اضافه/به‌روزرسانی می‌شوند، گروه‌های
        موجودِ نام‌نبرده‌شده در فایل دست‌نخورده می‌مانند) یا 'replace'
        (گروه‌های فعلی کامل با فایل جایگزین می‌شوند)."""
        try:
            raw = Path(path).read_text(encoding="utf-8")
            payload = json.loads(raw)
        except FileNotFoundError:
            return {"ok": False, "error": "فایل انتخاب‌شده پیدا نشد."}
        except json.JSONDecodeError:
            return {"ok": False, "error": "فایل انتخاب‌شده یک JSON معتبر نیست (احتمالاً خراب یا فایل اشتباه است)."}

        version = payload.get("export_version")
        if version != self.SETTINGS_EXPORT_VERSION:
            return {"ok": False, "error": f"نسخه فایل تنظیمات ({version}) با این برنامه (نسخه {self.SETTINGS_EXPORT_VERSION}) سازگار نیست."}

        if "criteria_config" not in payload or "expert_groups" not in payload:
            return {"ok": False, "error": "ساختار فایل تنظیمات ناقص است (فیلدهای موردنیاز پیدا نشد)."}

        try:
            categories = [
                Category(id=c["id"], name_fa=c["name_fa"], criteria=[Criterion(**cr) for cr in c["criteria"]])
                for c in payload["criteria_config"]["categories"]
            ]
            self.config = CriteriaConfig(
                objective_ai_ratio=payload["criteria_config"]["objective_ai_ratio"],
                categories=categories,
                data_health_checks=payload["criteria_config"].get("data_health_checks", []),
            )
            save_criteria_config(self.config, USER_CONFIG_PATH)
        except (KeyError, TypeError) as exc:
            return {"ok": False, "error": f"ساختار معیارها در فایل نامعتبر است: {exc}"}

        incoming_groups = payload.get("expert_groups", {})
        if mode == "replace":
            db.set_setting("expert_groups", incoming_groups)
        else:
            current = db.get_setting("expert_groups", {}) or {}
            current.update(incoming_groups)
            db.set_setting("expert_groups", current)

        ai_payload = payload.get("ai_settings")
        if ai_payload:
            self.ai_settings.provider = ai_payload.get("provider", self.ai_settings.provider)
            self.ai_settings.model = ai_payload.get("model", self.ai_settings.model)
            self.ai_settings.base_url = ai_payload.get("base_url", self.ai_settings.base_url)
            self.ai_settings.temperature = ai_payload.get("temperature", self.ai_settings.temperature)
            self.ai_settings.max_tokens = ai_payload.get("max_tokens", self.ai_settings.max_tokens)
            self.ai_settings.batch_size = ai_payload.get("batch_size", self.ai_settings.batch_size)
            self.ai_settings.enabled = ai_payload.get("enabled", self.ai_settings.enabled)
            db.set_setting("ai_settings", ai_payload)

        return {
            "ok": True,
            "imported_groups": list(incoming_groups.keys()),
            "note": "کلید API (در صورت وجود) به‌دلایل امنیتی منتقل نشد؛ در صورت نیاز آن را در تنظیمات AI دوباره وارد کنید.",
        }

    # ------------------------------------------------------------ criteria --

    def get_criteria(self) -> dict:
        return self.config.to_dict()

    def update_criterion(self, criterion_id: str, weight: float, active: bool) -> dict:
        c = self.config.find_criterion(criterion_id)
        if not c:
            return {"ok": False, "error": "معیار پیدا نشد."}
        c.weight = float(weight)
        c.active = bool(active)
        save_criteria_config(self.config, USER_CONFIG_PATH)
        return {"ok": True}

    def update_ratio(self, objective: float, ai: float) -> dict:
        total = objective + ai
        if total <= 0:
            return {"ok": False, "error": "مجموع نسبت‌ها باید بزرگ‌تر از صفر باشد."}
        self.config.objective_ai_ratio = {"objective": objective / total, "ai": ai / total}
        save_criteria_config(self.config, USER_CONFIG_PATH)
        return {"ok": True}

    def reset_criteria(self) -> dict:
        self.config = load_criteria_config()
        if USER_CONFIG_PATH.exists():
            USER_CONFIG_PATH.unlink()
        return {"ok": True}

    # ----------------------------------------------------------- AI settings

    def get_ai_settings(self) -> dict:
        s = self.ai_settings
        return {
            "provider": s.provider, "model": s.model, "base_url": s.base_url,
            "temperature": s.temperature, "max_tokens": s.max_tokens, "batch_size": s.batch_size,
            "enabled": s.enabled, "api_key_masked": db.mask_key(s.api_key), "has_key": bool(s.api_key),
        }

    def save_ai_settings(self, payload: dict) -> dict:
        s = self.ai_settings
        s.provider = payload.get("provider", s.provider)
        s.model = payload.get("model", s.model)
        s.base_url = payload.get("base_url", s.base_url)
        s.temperature = float(payload.get("temperature", s.temperature))
        s.max_tokens = int(payload.get("max_tokens", s.max_tokens))
        s.batch_size = int(payload.get("batch_size", s.batch_size))
        s.enabled = bool(payload.get("enabled", s.enabled))
        new_key = payload.get("api_key")
        if new_key:
            s.api_key = new_key
            db.save_api_key(new_key)
        db.set_setting("ai_settings", {
            "provider": s.provider, "model": s.model, "base_url": s.base_url,
            "temperature": s.temperature, "max_tokens": s.max_tokens,
            "batch_size": s.batch_size, "enabled": s.enabled,
        })
        return {"ok": True}

    def delete_ai_key(self) -> dict:
        db.delete_api_key()
        self.ai_settings.api_key = ""
        return {"ok": True}

    def test_ai_connection(self) -> dict:
        from ai.providers import AIProviderError, get_provider
        if not self.ai_settings.api_key:
            return {"ok": False, "message": "کلید API ثبت نشده است."}
        try:
            provider = get_provider(self.ai_settings)
            reply = provider.complete(
                "فقط یک شیء JSON به فرم {\"ok\": true} برگردان.", "تست اتصال", self.ai_settings
            )
            return {"ok": True, "message": f"اتصال موفق بود. پاسخ نمونه: {reply[:120]}"}
        except AIProviderError as exc:
            return {"ok": False, "message": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": f"خطای غیرمنتظره: {exc}"}

    # ------------------------------------------------------------ analysis --

    def start_analysis(self, p1_start: str, p1_end: str, p2_start: str, p2_end: str,
                        expert_group: str | None = None) -> dict:
        if not self.dataset:
            return {"ok": False, "error": "ابتدا فایل‌های Notes و Tasks را بارگذاری کنید."}
        if self.status["running"]:
            return {"ok": False, "error": "یک تحلیل در حال اجراست."}
        try:
            period1 = (_parse_period_bound(p1_start, end=False), _parse_period_bound(p1_end, end=True))
            period2 = (_parse_period_bound(p2_start, end=False), _parse_period_bound(p2_end, end=True))
        except ValueError:
            return {"ok": False, "error": "فرمت تاریخ نامعتبر است."}
        self.last_periods = (period1, period2)

        expert_filter = None
        unit = "case"
        if expert_group:
            groups = db.get_setting("expert_groups", {}) or {}
            group_data = groups.get(expert_group)
            if isinstance(group_data, list):
                group_data = {"experts": group_data, "review_unit": "case"}
            if not group_data or not group_data.get("experts"):
                return {"ok": False, "error": f"گروه «{expert_group}» یافت نشد یا خالی است."}
            expert_filter = set(group_data["experts"])
            unit = group_data.get("review_unit", "case")

        self.status = {"running": True, "done": False, "stage": "شروع", "current": 0, "total": 0, "error": None}
        thread = threading.Thread(target=self._run_worker, args=(period1, period2, expert_filter, unit), daemon=True)
        thread.start()
        return {"ok": True}

    def _run_worker(self, period1, period2, expert_filter=None, unit="case"):
        def progress_cb(label, current, total):
            self.status.update({"stage": label, "current": current, "total": total})

        try:
            result = run_full_analysis(
                self.dataset, self.config, period1, period2,
                self.ai_settings if self.ai_settings.enabled else AISettings(enabled=False),
                progress_cb, expert_filter, unit,
            )
            with self._lock:
                self.result = result
            self.status.update({"running": False, "done": True, "stage": "پایان یافت"})
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self.status.update({"running": False, "done": False, "error": str(exc)})

    def get_status(self) -> dict:
        return self.status

    # ------------------------------------------------------------ results --

    def get_dashboard(self) -> dict:
        if not self.result or not self.dataset:
            return {"ok": False}
        r = self.result
        p1, p2 = r["period1"], r["period2"]
        overall = r["comparison"]["overall"]
        analyzed_cases = len(set(p1.cases) | set(p2.cases))
        return {
            "ok": True,
            "unit": r.get("unit", "case"),
            "total_cases": analyzed_cases,
            "total_cases_all": len(self.dataset.cases),
            "total_experts": len({e for e in r["experts_p2"]} | {e for e in r["experts_p1"]}),
            "total_notes": sum(len(c.notes) for c in p1.cases.values()) + sum(len(c.notes) for c in p2.cases.values()),
            "total_tasks": sum(len(c.tasks) for c in p1.cases.values()) + sum(len(c.tasks) for c in p2.cases.values()),
            "data_quality": r["data_health_index"],
            "period1_score": overall.period1,
            "period2_score": overall.period2,
            "improvement_pct": overall.change_pct,
            "category_chart": [
                {"name": c.name_fa, "period1": c.period1, "period2": c.period2}
                for c in r["comparison"]["categories"]
            ],
            "suspicious_count": len(r["suspicious"]),
        }

    def get_comparison(self) -> dict:
        if not self.result:
            return {"ok": False}
        comp = self.result["comparison"]
        return {
            "ok": True,
            "overall": asdict(comp["overall"]),
            "categories": [asdict(c) for c in comp["categories"]],
            "criteria": [asdict(c) for c in comp["criteria"]],
            "narrative": comp["narrative"],
        }

    def get_ranking(self) -> dict:
        if not self.result:
            return {"ok": False}
        return {"ok": True, "rows": self.result["ranking"]}

    def get_expert_detail(self, expert: str) -> dict:
        if not self.result:
            return {"ok": False}
        r = self.result
        s1 = r["experts_p1"].get(expert)
        s2 = r["experts_p2"].get(expert)

        def ser(s):
            if not s:
                return None
            return {
                "case_count": s.case_count, "note_count": s.note_count, "task_count": s.task_count,
                "avg_objective": s.avg_objective, "avg_ai": s.avg_ai, "avg_final": s.avg_final,
                "weak_criteria": s.weak_criteria.most_common(5), "strong_criteria": s.strong_criteria.most_common(5),
            }

        cases_p2 = []
        for key, case in r["period2"].cases.items():
            from analysis.experts import primary_expert
            if primary_expert(case) == expert:
                b = r["period2"].scores.get(key)
                cases_p2.append({
                    "case_key": key, "case_number": case.case_number, "case_title": case.case_title,
                    "final_score": b.final_score if b else None,
                })
        cases_p2.sort(key=lambda c: (c["final_score"] is None, c["final_score"] or 0))

        from analysis.experts import build_employee_feedback
        feedback = build_employee_feedback(s2) if s2 else (build_employee_feedback(s1) if s1 else None)

        return {
            "ok": True, "period1": ser(s1), "period2": ser(s2), "cases": cases_p2[:200],
            "feedback": feedback,
        }

    def _build_full_expert_report(self, expert: str) -> dict:
        from analysis.experts import build_full_employee_report
        r = self.result
        s1 = r["experts_p1"].get(expert)
        s2 = r["experts_p2"].get(expert)
        s_current, s_previous = (s2, s1) if s2 else (s1, None)

        period_label = "—"
        if self.last_periods:
            p1, p2 = self.last_periods
            active = p2 if s2 else p1
            period_label = f"{active[0].date().isoformat()} تا {active[1].date().isoformat()}"

        return build_full_employee_report(
            expert, s_current, s_previous, r["experts_p2"], period_label, unit=r.get("unit", "case"),
        )

    def get_expert_report(self, expert: str) -> dict:
        if not self.result:
            return {"ok": False, "error": "ابتدا تحلیل را اجرا کنید."}
        report = self._build_full_expert_report(expert)
        return {"ok": True, "report": report}

    def export_expert_report_excel(self, expert: str, path: str) -> dict:
        if not self.result:
            return {"ok": False, "error": "ابتدا تحلیل را اجرا کنید."}
        try:
            report = self._build_full_expert_report(expert)
            export_expert_report_excel_file(path, report)
            return {"ok": True, "path": path}
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            return {"ok": False, "error": f"خطا در ساخت گزارش: {exc}"}

    def _resolve_period(self, period: str) -> tuple[dict, dict]:
        """cases, scores را برای period داده‌شده برمی‌گرداند. period می‌تواند
        'period1'، 'period2' یا 'all' (ترکیب هر دو دوره، دوره دوم در صورت
        تداخل کلید ارجحیت دارد چون جدیدتر است) باشد."""
        if period == "all":
            cases = {**self.result["period1"].cases, **self.result["period2"].cases}
            scores = {**self.result["period1"].scores, **self.result["period2"].scores}
            return cases, scores
        pr = self.result[period] if period in ("period1", "period2") else self.result["period2"]
        return pr.cases, pr.scores

    def get_case_detail(self, case_key: str, period: str = "period2") -> dict:
        if not self.result:
            return {"ok": False}
        cases, scores = self._resolve_period(period)
        case = cases.get(case_key) or (self.dataset.cases.get(case_key) if self.dataset else None)
        if not case:
            return {"ok": False, "error": "مورد پیدا نشد."}
        breakdown = scores.get(case_key)
        timeline = build_timeline(case)
        return {
            "ok": True,
            "case_number": case.case_number, "case_title": case.case_title,
            "customer": case.customer, "owner": case.owner, "service": case.service,
            "status": case.status, "status_reason": case.status_reason,
            "scenario": case.scenario, "case_description": case.case_description,
            "timeline": timeline,
            "breakdown": _breakdown_to_dict(breakdown) if breakdown else None,
        }

    def get_cases_table(self, period: str, page: int, page_size: int,
                         expert_filter: str | None = None, status_reason_filter: list[str] | None = None,
                         case_number_filter: str | None = None) -> dict:
        if not self.result:
            return {"ok": False}
        cases, scores = self._resolve_period(period)
        from analysis.experts import primary_expert
        rows = []
        experts_seen = set()
        status_reasons_seen = set()
        query = (case_number_filter or "").strip().casefold()
        for key, case in cases.items():
            expert = primary_expert(case)
            experts_seen.add(expert)
            if case.status_reason:
                status_reasons_seen.add(case.status_reason)
            if expert_filter and expert != expert_filter:
                continue
            if status_reason_filter and (case.status_reason or "") not in status_reason_filter:
                continue
            if query and query not in (case.case_number or "").casefold():
                continue
            b = scores.get(key)
            rows.append({
                "case_key": key, "case_number": case.case_number, "case_title": case.case_title,
                "expert": expert, "status_reason": case.status_reason,
                "notes": len(case.notes), "tasks": len(case.tasks),
                "objective_score": b.objective_score if b else None,
                "ai_score": b.ai_score if b else None,
                "final_score": b.final_score if b else None,
            })
        rows.sort(key=lambda r: (r["final_score"] is None, r["final_score"] or 0))
        total = len(rows)
        start = page * page_size
        return {
            "ok": True, "rows": rows[start:start + page_size], "total": total,
            "experts": sorted(experts_seen), "status_reasons": sorted(status_reasons_seen),
            "unit": self.result.get("unit", "case"),
        }

    def get_suspicious(self) -> dict:
        if not self.result:
            return {"ok": False}
        rows = [
            {"case_key": s.case_key, "case_number": s.case_number, "case_title": s.case_title, "reasons": s.reasons}
            for s in self.result["suspicious"]
        ]
        return {"ok": True, "rows": rows, "unit": self.result.get("unit", "case")}

    def get_data_quality(self) -> dict:
        if not self.result:
            return {"ok": False}
        checks = [
            {"id": h.id, "name_fa": h.name_fa, "healthy_score": h.healthy_score,
             "issue_count": h.issue_count, "detail_fa": h.detail_fa}
            for h in self.result["data_health_checks"]
        ]
        return {"ok": True, "checks": checks, "index": self.result["data_health_index"]}

    def get_management_report(self) -> dict:
        if not self.result:
            return {"ok": False}
        r = self.result
        comp = r["comparison"]
        ranking = r["ranking"]
        improved = [row for row in ranking if row["change"] is not None and row["change"] > 0]
        worsened = [row for row in ranking if row["change"] is not None and row["change"] < 0]
        improved.sort(key=lambda x: -x["change"])
        worsened.sort(key=lambda x: x["change"])
        top_weak = _top_weak_criteria(comp["criteria"])
        return {
            "ok": True,
            "overall_status": comp["narrative"],
            "top_strengths": [c.name_fa for c in comp["categories"] if c.period2 and c.period2 >= 75][:5],
            "top_weaknesses": top_weak,
            "most_improved": improved[:5],
            "most_declined": worsened[:5],
            "data_issues": [h.name_fa for h in r["data_health_checks"] if h.healthy_score < 80],
            "recommendations": _build_recommendations(comp, r["data_health_index"]),
        }

    # -------------------------------------------------------------- export --

    def export_excel_report(self, path: str) -> dict:
        if not self.result:
            return {"ok": False, "error": "ابتدا تحلیل را اجرا کنید."}
        try:
            data = self._build_export_tables()
            export_excel(path, data)
            return {"ok": True, "path": path}
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            return {"ok": False, "error": f"خطا در ساخت فایل خروجی: {exc}"}

    def export_csv_table(self, table: str, path: str) -> dict:
        if not self.result:
            return {"ok": False, "error": "ابتدا تحلیل را اجرا کنید."}
        data = self._build_export_tables()
        section = data.get(table)
        if not section:
            return {"ok": False, "error": "جدول موردنظر یافت نشد."}
        export_csv(path, section["headers"], section["rows"])
        return {"ok": True, "path": path}

    def _build_export_tables(self) -> dict:
        r = self.result
        comp = r["comparison"]

        summary_rows = [
            ["تعداد کل مورد", len(self.dataset.cases)],
            ["تعداد Note", len(self.dataset.notes)],
            ["تعداد Task", len(self.dataset.tasks)],
            ["شاخص سلامت داده CRM", r["data_health_index"]],
            ["امتیاز کلی دوره اول", comp["overall"].period1],
            ["امتیاز کلی دوره دوم", comp["overall"].period2],
            ["تغییر", comp["overall"].change],
        ]

        case_rows = []
        for period_key, pr in (("دوره اول", r["period1"]), ("دوره دوم", r["period2"])):
            from analysis.experts import primary_expert
            for key, case in pr.cases.items():
                b = pr.scores.get(key)
                case_rows.append([
                    period_key, case.case_number, case.case_title, primary_expert(case),
                    len(case.notes), len(case.tasks),
                    b.objective_score if b else None, b.ai_score if b else None, b.final_score if b else None,
                ])

        expert_rows = [
            [row["expert"], row["period1_score"], row["period2_score"], row["change"], row["status"],
             row["period1_cases"], row["period2_cases"]]
            for row in r["ranking"]
        ]

        criteria_rows = [
            [c.name_fa, c.period1, c.period2, c.change, c.change_pct] for c in comp["criteria"]
        ]

        comparison_rows = [
            [c.name_fa, c.period1, c.period2, c.change, c.change_pct] for c in comp["categories"]
        ]

        dq_rows = [
            [h.name_fa, h.healthy_score, h.issue_count, h.detail_fa] for h in r["data_health_checks"]
        ]

        ai_rows = []
        for period_key, pr in (("دوره اول", r["period1"]), ("دوره دوم", r["period2"])):
            for key, case in pr.cases.items():
                b = pr.scores.get(key)
                if not b or not b.ai_used:
                    continue
                for cs in b.criterion_scores:
                    if cs.evaluation_type in ("AI", "HYBRID") and cs.score is not None:
                        ai_rows.append([period_key, case.case_number, cs.name_fa, cs.score, cs.evidence])

        suspicious_rows = [
            [s.case_number, s.case_title, "؛ ".join(s.reasons)] for s in r["suspicious"]
        ]

        return {
            "summary": {"headers": ["شاخص", "مقدار"], "rows": summary_rows},
            "cases": {"headers": ["دوره", "شماره مورد", "عنوان", "کارشناس", "تعداد Note", "تعداد Task",
                                   "Objective", "AI", "Final"], "rows": case_rows},
            "experts": {"headers": ["کارشناس", "دوره اول", "دوره دوم", "تغییر", "وضعیت",
                                     "تعداد مورد دوره اول", "تعداد مورد دوره دوم"], "rows": expert_rows},
            "criteria": {"headers": ["معیار", "دوره اول", "دوره دوم", "تغییر", "درصد تغییر"], "rows": criteria_rows},
            "comparison": {"headers": ["دسته", "دوره اول", "دوره دوم", "تغییر", "درصد تغییر"], "rows": comparison_rows},
            "data_quality": {"headers": ["شاخص", "امتیاز سلامت", "تعداد مشکل", "توضیح"], "rows": dq_rows},
            "ai_analysis": {"headers": ["دوره", "شماره مورد", "معیار", "امتیاز", "شواهد"], "rows": ai_rows},
            "suspicious": {"headers": ["شماره مورد", "عنوان", "دلایل"], "rows": suspicious_rows},
        }


def _summary_to_dict(s) -> dict:
    return {
        "file_name": s.file_name, "sheet_name": s.sheet_name, "total_rows": s.total_rows,
        "usable_rows": s.usable_rows, "rows_without_date": s.rows_without_date,
        "unique_cases": s.unique_cases, "incomplete_rows": s.incomplete_rows,
        "usable_columns": s.usable_columns, "total_columns": s.total_columns,
        "missing_required_labels": s.missing_required_labels, "warnings": s.warnings,
        "unmatched_headers": s.unmatched_headers,
    }


def _breakdown_to_dict(b) -> dict:
    return {
        "objective_score": b.objective_score, "ai_score": b.ai_score, "final_score": b.final_score,
        "ai_used": b.ai_used, "category_scores": b.category_scores,
        "coverage": b.coverage, "confidence": b.confidence,
        "na_criteria": b.na_criteria, "criteria_version": b.criteria_version,
        "outcome_status": b.outcome_status, "lifecycle_status": b.lifecycle_status,
        "criteria": [
            {"id": c.criterion_id, "name_fa": c.name_fa, "category": c.category_name_fa,
             "type": c.evaluation_type, "score": c.score, "evidence": c.evidence,
             "coverage": c.coverage, "confidence": c.confidence,
             "na_reason": c.na_reason, "source_events": c.source_events,
             "criteria_version": c.criteria_version}
            for c in b.criterion_scores
        ],
    }


def _top_weak_criteria(criteria_comparisons, n=5):
    ranked = sorted(
        [c for c in criteria_comparisons if c.period2 is not None],
        key=lambda c: c.period2,
    )
    return [{"name": c.name_fa, "score": c.period2} for c in ranked[:n]]


def _build_recommendations(comp, data_health_index) -> list[str]:
    recs = []
    weak = _top_weak_criteria(comp["criteria"], n=3)
    for w in weak:
        recs.append(f"بهبود «{w['name']}» (امتیاز فعلی {w['score']}) از طریق آموزش یا Checklist ثبت.")
    if data_health_index < 80:
        recs.append("شاخص سلامت داده CRM پایین است؛ بازبینی الزام ثبت Description و اتصال صحیح Task به مورد توصیه می‌شود.")
    if not recs:
        recs.append("در حال حاضر ضعف قابل‌توجهی شناسایی نشد؛ روند فعلی حفظ شود.")
    return recs
