"""Read-only Dynamics 365 On-Premises Web API client.

The Windows session credential is delegated to PowerShell/WinHTTP through
Invoke-WebRequest -UseDefaultCredentials. No CRM write operation is exposed.
"""
from __future__ import annotations

import json
import hashlib
import os
import subprocess
import time
from datetime import datetime
from xml.etree import ElementTree
from urllib.parse import quote

from data.cleaner import build_cases
from data.validator import NoteRecord, TaskRecord, ValidationSummary, parse_datetime
from pipeline import Dataset


class CRMClientError(RuntimeError):
    pass


DEFAULT_BASE_URL = "https://crm.baridsoft.ir"
# The on-premises Dynamics endpoint can take longer than the default PowerShell
# request timeout, especially when the selected View contains many records.
# Keep the process timeout a little higher so a request timeout is reported by
# the PowerShell layer instead of being mistaken for an empty JSON response.
CRM_REQUEST_TIMEOUT_SECONDS = 180
CRM_PROCESS_TIMEOUT_SECONDS = CRM_REQUEST_TIMEOUT_SECONDS + 30
DEFAULT_ORGANIZATION = "Main"
DEFAULT_API_VERSION = "v9.1"
DEFAULT_VIEW_NAME = "داشبورد مدیریت مورد های ثبت شده هلپدسک چهار ماه اخیر"


def _iso(value):
    return value.isoformat() if isinstance(value, datetime) else None


def dataset_to_payload(dataset: Dataset) -> dict:
    return {
        "notes": [
            {**n.__dict__, "case_created_on": _iso(n.case_created_on),
             "note_date": _iso(n.note_date)}
            for n in dataset.notes
        ],
        "tasks": [
            {**t.__dict__, "created_on": _iso(t.created_on),
             "actual_start": _iso(t.actual_start), "due_date": _iso(t.due_date),
             "next_follow_up": _iso(t.next_follow_up)}
            for t in dataset.tasks
        ],
    }


def dataset_from_payload(payload: dict) -> Dataset:
    notes = [
        NoteRecord(
            **{**row, "case_created_on": parse_datetime(row.get("case_created_on")),
               "note_date": parse_datetime(row.get("note_date"))}
        )
        for row in payload.get("notes", [])
    ]
    tasks = [
        TaskRecord(
            **{**row, "created_on": parse_datetime(row.get("created_on")),
               "actual_start": parse_datetime(row.get("actual_start")),
               "due_date": parse_datetime(row.get("due_date")),
               "next_follow_up": parse_datetime(row.get("next_follow_up"))}
        )
        for row in payload.get("tasks", [])
    ]
    cases, unmatched = build_cases(notes, tasks)
    summary = ValidationSummary(
        file_name="CRM Snapshot", sheet_name="CRM", total_rows=len(notes),
        usable_rows=len(notes), rows_without_date=sum(1 for n in notes if not n.note_date),
        unique_cases=len(cases), incomplete_rows=sum(1 for n in notes if not n.description),
        usable_columns=0, total_columns=0, mapping={}, missing_required_labels=[],
        ambiguous={}, unmatched_headers=[],
        warnings=["این داده از Snapshot محلی CRM بازیابی شده است."],
    )
    return Dataset(
        notes=notes, tasks=tasks, cases=cases, unmatched_tasks=unmatched,
        notes_summary=summary, tasks_summary=summary,
    )


def _value(row: dict, *names: str):
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


def _display(row: dict, *names: str):
    for name in names:
        candidates = (name, f"{name}name", f"{name}_name")
        value = _value(
            row,
            *[
                candidate
                for base in candidates
                for candidate in (
                    f"{base}@OData.Community.Display.V1.FormattedValue",
                    f"{base}@odata.displayname",
                    base,
                )
            ],
        )
        if value not in (None, ""):
            text = str(value)
            # Do not expose a raw Dataverse GUID/option number when no label
            # was returned by the selected View.
            if not (_looks_like_guid(text) or text.isdecimal()):
                return value
        # Dynamics can vary the casing of annotation names after the
        # PowerShell JSON round-trip.  Find the formatted value by its
        # semantic suffix before falling back to a raw GUID/option value.
        for base in candidates:
            wanted = base.casefold()
            for key, candidate in row.items():
                key_text = str(key).casefold()
                key_field = key_text.split("@", 1)[0].split(".")[-1]
                wanted_field = wanted.split(".")[-1]
                if (key_text.find("@") > 0
                        and key_field == wanted_field
                        and "formattedvalue" in key_text
                        and candidate not in (None, "")):
                    return candidate
    return None


def _looks_like_guid(value: str) -> bool:
    parts = value.split("-")
    return len(parts) == 5 and all(parts) and all(
        all(ch in "0123456789abcdefABCDEF" for ch in part) for part in parts
    )


def _guid(value) -> str | None:
    text = str(value or "").strip().strip("{}")
    return text if _looks_like_guid(text) else None


def _row_guid(row: dict, *names: str) -> str | None:
    direct = _guid(_value(row, *names))
    if direct:
        return direct
    # FetchXML aliases vary between Dynamics deployments. When an explicit
    # field name is absent, inspect lookup-like keys for a GUID value.
    for key, value in row.items():
        key_text = str(key).casefold()
        if any(token in key_text for token in (
            "objectid", "incidentid", "regardingobjectid",
        )):
            found = _guid(value)
            if found:
                return found
    return None


def _paged_values(url: str, username: str = "", password: str = "") -> list[dict]:
    payload = _powershell_get_json(url, username, password)
    rows = list(payload.get("value") or [])
    next_link = payload.get("@odata.nextLink") or payload.get("odata.nextLink")
    page_count = 1
    while next_link and page_count < 1000:
        page_payload = _powershell_get_json(next_link, username, password)
        rows.extend(page_payload.get("value") or [])
        next_link = page_payload.get("@odata.nextLink") or page_payload.get("odata.nextLink")
        page_count += 1
    return rows


def _add_modified_since_filter(fetchxml: str, since: datetime) -> str:
    """Add an annotation modifiedon watermark without replacing View filters."""
    root = ElementTree.fromstring(fetchxml)
    entity = root.find("./entity")
    if entity is None:
        raise CRMClientError("ساختار FetchXML View قابل تشخیص نیست.")
    target = entity.find("./filter")
    if target is None:
        target = ElementTree.SubElement(entity, "filter", {"type": "and"})
    ElementTree.SubElement(target, "condition", {
        "attribute": "modifiedon",
        "operator": "gt",
        "value": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    return ElementTree.tostring(root, encoding="unicode", short_empty_elements=True)


def _powershell_get_json(url: str, username: str = "", password: str = "") -> dict:
    # Keep the URL outside the command text to avoid command injection.
    command = (
        "$ErrorActionPreference = 'Stop'; "
        "$utf8 = New-Object System.Text.UTF8Encoding($false); "
        "$OutputEncoding = $utf8; "
        "[Console]::OutputEncoding = $utf8; "
        "$u=$env:MYBARID_CRM_URL; "
        "if ($env:MYBARID_CRM_USER -and $env:MYBARID_CRM_PASS) { "
        "$sec=ConvertTo-SecureString $env:MYBARID_CRM_PASS -AsPlainText -Force; "
        "$cred=New-Object System.Management.Automation.PSCredential("
        "$env:MYBARID_CRM_USER,$sec); "
        "$r=Invoke-WebRequest -UseBasicParsing -Uri $u -Credential $cred "
        "-Headers @{Accept='application/json';'OData-Version'='4.0';"
        "Prefer='odata.include-annotations=\"*\"'} "
        f"-TimeoutSec {CRM_REQUEST_TIMEOUT_SECONDS} "
        "} else { "
        "$r=Invoke-WebRequest -UseBasicParsing -Uri $u -UseDefaultCredentials "
        "-Headers @{Accept='application/json';'OData-Version'='4.0';"
        "Prefer='odata.include-annotations=\"*\"'} "
        f"-TimeoutSec {CRM_REQUEST_TIMEOUT_SECONDS} "
        "}; "
        "if ($null -eq $r -or $null -eq $r.RawContentStream) { "
        "throw 'CRM پاسخ خالی برگرداند.' "
        "}; "
        "$bytes = $r.RawContentStream.ToArray(); "
        "$content = [System.Text.Encoding]::UTF8.GetString($bytes); "
        "if ([string]::IsNullOrWhiteSpace($content)) { throw 'CRM پاسخ خالی برگرداند.' }; "
        "$parsed = $content | ConvertFrom-Json; "
        "$parsed | ConvertTo-Json -Compress -Depth 100"
    )
    env = os.environ.copy()
    env["MYBARID_CRM_URL"] = url
    env["MYBARID_CRM_USER"] = username or ""
    env["MYBARID_CRM_PASS"] = password or ""
    try:
        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=CRM_PROCESS_TIMEOUT_SECONDS,
            env=env, check=False, startupinfo=startupinfo,
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired as exc:
        raise CRMClientError(
            f"مهلت ارتباط با CRM پس از {CRM_PROCESS_TIMEOUT_SECONDS} ثانیه تمام شد؛ "
            "سرور، View یا شبکه پاسخ نداد."
        ) from exc
    except OSError as exc:
        raise CRMClientError(f"اجرای ابزار ارتباط با CRM ممکن نشد: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        detail = detail[:700] or "جزئیات خطا از PowerShell دریافت نشد."
        lowered = detail.casefold()
        if "timed out" in lowered or "timeout" in lowered or "مهلت" in detail:
            raise CRMClientError(
                f"مهلت دریافت پاسخ از CRM پس از {CRM_REQUEST_TIMEOUT_SECONDS} ثانیه تمام شد. "
                "اتصال شبکه، احراز هویت و سنگین‌بودن View را بررسی کنید."
                f" جزئیات فنی: {detail}"
            )
        raise CRMClientError(f"خطا در دریافت اطلاعات CRM: {detail}")
    raw_response = completed.stdout
    if not isinstance(raw_response, str) or not raw_response.strip():
        detail = (completed.stderr or "").strip()
        suffix = f" جزئیات: {detail[:500]}" if detail else ""
        raise CRMClientError(
            "CRM پاسخ خالی برگرداند؛ احتمالاً خطای احراز هویت یا خطای سرویس رخ داده است."
            f"{suffix}"
        )
    try:
        # Some Dynamics installations return literal control characters inside
        # multiline annotation text.  The response is still structurally JSON;
        # accepting those characters here preserves the Note content.
        payload = json.loads(raw_response, strict=False)
    except json.JSONDecodeError as exc:
        preview = raw_response.strip().replace("\r", " ").replace("\n", " ")[:180]
        raise CRMClientError(
            "CRM پاسخ JSON معتبر برنگرداند؛ احتمالاً صفحه خطا، پاسخ احراز هویت یا خطای سرویس دریافت شده است."
            f" پیش‌نمایش پاسخ: {preview}"
        ) from exc
    if not isinstance(payload, dict):
        raise CRMClientError("ساختار پاسخ CRM معتبر نیست.")
    return payload


def _build_related_activity_fetchxml(case_fetchxml: str, activity_entity: str) -> str:
    """Build one batched activity query from the selected Case View."""
    root = ElementTree.fromstring(case_fetchxml)
    case_entity = root.find("./entity")
    if case_entity is None or case_entity.get("name") != "incident":
        raise CRMClientError("FetchXML View موردها ساختار قابل استفاده‌ای ندارد.")
    new_root = ElementTree.Element(
        "fetch", {k: v for k, v in root.attrib.items() if k not in {"page", "paging-cookie"}}
    )
    new_root.set("distinct", "true")
    activity = ElementTree.SubElement(new_root, "entity", {"name": activity_entity})
    if activity_entity == "annotation":
        attributes = ("annotationid", "notetext", "createdon", "modifiedon", "modifiedby", "objectid")
        to_attribute = "objectid"
    else:
        attributes = ("activityid", "subject", "description", "createdon", "actualstart", "scheduledend", "statuscode", "ownerid", "regardingobjectid")
        to_attribute = "regardingobjectid"
    for name in attributes:
        ElementTree.SubElement(activity, "attribute", {"name": name})
    link = ElementTree.fromstring(ElementTree.tostring(case_entity, encoding="unicode"))
    link.tag = "link-entity"
    link.attrib = {"name": "incident", "from": "incidentid", "to": to_attribute, "alias": "ac"}
    activity.append(link)
    return ElementTree.tostring(new_root, encoding="unicode", short_empty_elements=True)


class DynamicsCRMClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        organization: str = DEFAULT_ORGANIZATION,
        api_version: str = DEFAULT_API_VERSION,
        view_name: str = DEFAULT_VIEW_NAME,
        username: str = "",
        password: str = "",
    ):
        self.base_url = base_url.rstrip("/")
        self.organization = organization.strip("/")
        self.api_version = api_version.strip("/")
        self.view_name = view_name
        self.username = username
        self.password = password

    @property
    def api_root(self) -> str:
        return f"{self.base_url}/{self.organization}/api/data/{self.api_version}"

    def _get_user_view(self) -> dict:
        query = (
            f"{self.api_root}/userqueries?"
            "$select=name,userqueryid,returnedtypecode,fetchxml"
            f"&$filter=name%20eq%20'{quote(self.view_name)}'"
        )
        payload = _powershell_get_json(query, self.username, self.password)
        values = payload.get("value") or []
        if not values:
            raise CRMClientError(
                f"View شخصی «{self.view_name}» پیدا نشد یا برای کاربر Windows فعلی Share نشده است."
            )
        view = values[0]
        returned_type = str(view.get("returnedtypecode") or "").casefold()
        if returned_type not in {"annotation", "incident"}:
            raise CRMClientError("View انتخاب‌شده از نوع مورد (Case) یا Note نیست.")
        return view

    def list_note_views(self) -> list[dict]:
        """Return readable personal/system Note views for the current Windows user."""
        views: list[dict] = []
        for entity, id_key, scope in (
            ("userqueries", "userqueryid", "شخصی"),
            ("savedqueries", "savedqueryid", "سازمانی"),
        ):
            select = f"$select=name,{id_key},returnedtypecode"
            payload = _powershell_get_json(f"{self.api_root}/{entity}?{select}",
                                           self.username, self.password)
            for row in payload.get("value") or []:
                if row.get("returnedtypecode") in {"annotation", "incident"} and row.get("name"):
                    views.append({
                        "id": row.get(id_key), "name": row["name"],
                        "scope": scope, "kind": entity,
                    })
        unique = {f"{item['kind']}:{item['id']}": item for item in views}
        return sorted(unique.values(), key=lambda item: item["name"].casefold())

    def test_connection(self) -> dict:
        payload = _powershell_get_json(f"{self.api_root}/WhoAmI",
                                       self.username, self.password)
        return {"ok": True, "api_root": self.api_root, "user": payload}

    def fetch_view_dataset(
        self,
        since: datetime | None = None,
        include_related_activities: bool = False,
        progress_callback=None,
    ) -> tuple[Dataset, dict]:
        def progress(stage, completed=0, total=0, detail=""):
            if progress_callback:
                progress_callback(stage, completed, total, detail)

        view_started = time.perf_counter()
        progress("در حال یافتن View انتخاب‌شده از CRM...", 0, 0, "درخواست شناسایی View ارسال شد")
        view = self._get_user_view()
        progress("View شناسایی شد", 0, 0, f"زمان پاسخ: {time.perf_counter() - view_started:.1f} ثانیه؛ نوع: {view.get('returnedtypecode')}")
        fetchxml = view.get("fetchxml")
        if not fetchxml:
            raise CRMClientError("View فاقد FetchXML قابل اجرا است.")
        returned_type = str(view.get("returnedtypecode") or "").casefold()
        entity_set = {"annotation": "annotations", "incident": "incidents"}.get(returned_type)
        if not entity_set:
            raise CRMClientError("Unsupported CRM View entity type.")
        query_fetchxml = _add_modified_since_filter(fetchxml, since) if since else fetchxml
        url = f"{self.api_root}/{entity_set}?fetchXml={quote(query_fetchxml, safe='')}"
        page_started = time.perf_counter()
        progress("در حال دریافت صفحه اول View...", 0, 0, "درخواست FetchXML ارسال شد")
        payload = _powershell_get_json(url, self.username, self.password)
        rows = list(payload.get("value") or [])
        progress("صفحه اول View دریافت شد", 0, 0, f"زمان پاسخ: {time.perf_counter() - page_started:.1f} ثانیه؛ {len(rows):,} رکورد")
        # Dataverse may paginate FetchXML results. The first response can
        # contain only a small page even when the selected View has many more
        # records. Follow the server-provided continuation link.
        next_link = payload.get("@odata.nextLink") or payload.get("odata.nextLink")
        page_count = 1
        while next_link and page_count < 1000:
            progress("در حال دریافت صفحات بعدی View...", page_count, 0, f"صفحه {page_count}")
            page_payload = _powershell_get_json(next_link, self.username, self.password)
            rows.extend(page_payload.get("value") or [])
            next_link = page_payload.get("@odata.nextLink") or page_payload.get("odata.nextLink")
            page_count += 1
        progress("دریافت View انجام شد", page_count, page_count, f"{len(rows):,} رکورد")

        # A Case View can contain thousands of cases. Fetch related activities
        # in two batched requests instead of two requests per case.
        case_context: dict[str, dict] = {}
        case_ids: set[str] = set()
        for row in rows:
            case_id = _row_guid(row, "_objectid_value", "ac.incidentid", "incidentid", "objectid")
            if case_id:
                case_ids.add(case_id)
                case_context.setdefault(case_id, row)

        if returned_type == "incident":
            progress("در حال دریافت Noteهای مرتبط با موردها...", 0, 2, "یک درخواست گروهی")
            note_fetchxml = _build_related_activity_fetchxml(query_fetchxml, "annotation")
            note_url = f"{self.api_root}/annotations?fetchXml={quote(note_fetchxml, safe='')}"
            expanded_notes = _paged_values(note_url, self.username, self.password)
            progress("دریافت Noteهای مرتبط انجام شد", 1, 2, f"{len(expanded_notes):,} Note")
            progress("در حال دریافت Taskهای مرتبط با موردها...", 1, 2, "یک درخواست گروهی")
            task_fetchxml = _build_related_activity_fetchxml(query_fetchxml, "task")
            task_url = f"{self.api_root}/tasks?fetchXml={quote(task_fetchxml, safe='')}"
            expanded_tasks = _paged_values(task_url, self.username, self.password)
            progress("دریافت Taskهای مرتبط انجام شد", 2, 2, f"{len(expanded_tasks):,} Task")
        else:
            expanded_notes = list(rows)
            note_ids = {
                str(_value(row, "annotationid") or "").casefold()
                for row in expanded_notes
                if _value(row, "annotationid")
            }
            expanded_tasks: list[dict] = []
            related_case_ids = sorted(case_ids) if include_related_activities else []
            for index, case_id in enumerate(related_case_ids, start=1):
                progress("در حال دریافت Note و Taskهای وابسته...", index - 1,
                         len(related_case_ids), f"مورد {index - 1} از {len(related_case_ids)}")
                note_url = (
                    f"{self.api_root}/annotations?"
                    f"$filter=_objectid_value%20eq%20{case_id}"
                    f"&$select=annotationid,notetext,createdon,modifiedon,modifiedby,"
                    f"_objectid_value"
                )
                for note_row in _paged_values(note_url, self.username, self.password):
                    note_id = str(_value(note_row, "annotationid") or "").casefold()
                    if note_id and note_id not in note_ids:
                        expanded_notes.append({**case_context[case_id], **note_row, "_objectid_value": case_id})
                        note_ids.add(note_id)
                task_url = (
                    f"{self.api_root}/tasks?"
                    f"$filter=_regardingobjectid_value%20eq%20{case_id}"
                    f"&$select=activityid,subject,description,createdon,actualstart,"
                    f"scheduledend,statuscode,ownerid,_regardingobjectid_value"
                )
                for task_row in _paged_values(task_url, self.username, self.password):
                    expanded_tasks.append({**case_context[case_id], **task_row, "_regardingobjectid_value": case_id})
                progress("در حال دریافت Note و Taskهای وابسته...", index,
                         len(related_case_ids), f"مورد {index} از {len(related_case_ids)}")

        rows = expanded_notes
        notes: list[NoteRecord] = []
        for row in rows:
            case_number = _value(row, "ac.ticketnumber", "ticketnumber")
            case_title = _value(row, "ac.title", "title")
            notes.append(NoteRecord(
                note_id=_value(row, "annotationid"),
                description=str(_value(row, "notetext") or ""),
                case_number=case_number,
                case_title=case_title,
                customer=_display(row, "ac.customerid"),
                owner=_display(row, "ac.ownerid", "ac.brd_assignto"),
                service=_display(row, "ac.brd_caseservice", "ac.brd_service"),
                case_status=_display(row, "ac.statecode"),
                case_status_reason=_display(row, "ac.statuscode"),
                case_created_on=parse_datetime(_value(row, "ac.createdon")),
                case_created_by=_display(row, "ac.createdby"),
                note_date=parse_datetime(_value(row, "modifiedon", "createdon")),
                note_author=_display(row, "modifiedby", "createdby"),
                assign_to=_display(row, "ac.brd_assignto"),
                incident_type=_display(row, "ac.brd_incidenttype"),
                case_description=_value(row, "ac.description"),
                scenario=_value(row, "ac.brd_scenario"),
                case_id=_row_guid(
                    row, "_objectid_value", "ac.incidentid", "incidentid", "objectid"
                ),
            ))
        tasks = [
            TaskRecord(
                task_id=_value(row, "activityid", "taskid"),
                subject=_value(row, "subject"),
                description=_value(row, "description"),
                case_number=_value(row, "ac.ticketnumber", "ticketnumber"),
                regarding=_value(row, "ac.title", "title", "_regardingobjectid_value"),
                created_by=_display(row, "ownerid", "createdby"),
                created_on=parse_datetime(_value(row, "createdon")),
                actual_start=parse_datetime(_value(row, "actualstart")),
                due_date=parse_datetime(_value(row, "scheduledend")),
                status_reason=_display(row, "statuscode"),
                follow_up_needed=None,
                next_follow_up=None,
                work_type=None,
                assign_to=_display(row, "ownerid"),
                case_id=_row_guid(
                    row, "_regardingobjectid_value", "regardingobjectid"
                ),
            )
            for row in expanded_tasks
        ]
        cases, unmatched = build_cases(notes, tasks)
        now = datetime.now().isoformat()
        summary = ValidationSummary(
            file_name=f"CRM View: {self.view_name}",
            sheet_name=self.view_name,
            total_rows=len(rows) + len(tasks), usable_rows=len(notes) + len(tasks),
            rows_without_date=sum(1 for n in notes if not n.note_date),
            unique_cases=len(cases), incomplete_rows=sum(1 for n in notes if not n.description),
            usable_columns=0, total_columns=0, mapping={}, missing_required_labels=[],
            ambiguous={}, unmatched_headers=[],
            warnings=[
                "Note و Taskهای وابسته نیز دریافت شدند."
                if include_related_activities or returned_type == "incident"
                else "فقط رکوردهای View دریافت شدند؛ دریافت Note و Taskهای وابسته فعال نشده است."
            ],
        )
        dataset = Dataset(
            notes=notes, tasks=tasks, cases=cases, unmatched_tasks=unmatched,
            notes_summary=summary, tasks_summary=summary,
        )
        modified_dates = [n.note_date for n in notes if n.note_date]
        return dataset, {
            "view_name": self.view_name, "view_id": view.get("userqueryid"),
            "fetched_at": now, "row_count": len(rows), "api_root": self.api_root,
            "sync_mode": "incremental" if since else "full",
            "since": _iso(since),
            "max_modified_on": _iso(max(modified_dates)) if modified_dates else _iso(since),
            "fetchxml_hash": hashlib.sha256(fetchxml.encode("utf-8")).hexdigest(),
            "related_activities": bool(include_related_activities or returned_type == "incident"),
        }
