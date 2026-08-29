"""Read-only Dynamics 365 On-Premises Web API client.

The Windows session credential is delegated to PowerShell/WinHTTP through
Invoke-WebRequest -UseDefaultCredentials. No CRM write operation is exposed.
"""
from __future__ import annotations

import json
import hashlib
import os
import subprocess
from datetime import datetime
from xml.etree import ElementTree
from urllib.parse import quote

from data.cleaner import build_cases
from data.validator import NoteRecord, ValidationSummary, parse_datetime
from pipeline import Dataset


class CRMClientError(RuntimeError):
    pass


DEFAULT_BASE_URL = "https://crm.baridsoft.ir"
DEFAULT_ORGANIZATION = "Main"
DEFAULT_API_VERSION = "v9.1"
DEFAULT_VIEW_NAME = "TESTNOTE"


def _iso(value):
    return value.isoformat() if isinstance(value, datetime) else None


def dataset_to_payload(dataset: Dataset) -> dict:
    return {
        "notes": [
            {**n.__dict__, "case_created_on": _iso(n.case_created_on),
             "note_date": _iso(n.note_date)}
            for n in dataset.notes
        ],
        "tasks": [],
    }


def dataset_from_payload(payload: dict) -> Dataset:
    notes = [
        NoteRecord(
            **{**row, "case_created_on": parse_datetime(row.get("case_created_on")),
               "note_date": parse_datetime(row.get("note_date"))}
        )
        for row in payload.get("notes", [])
    ]
    cases, unmatched = build_cases(notes, [])
    summary = ValidationSummary(
        file_name="CRM Snapshot", sheet_name="CRM", total_rows=len(notes),
        usable_rows=len(notes), rows_without_date=sum(1 for n in notes if not n.note_date),
        unique_cases=len(cases), incomplete_rows=sum(1 for n in notes if not n.description),
        usable_columns=0, total_columns=0, mapping={}, missing_required_labels=[],
        ambiguous={}, unmatched_headers=[],
        warnings=["این داده از Snapshot محلی CRM بازیابی شده است."],
    )
    return Dataset(
        notes=notes, tasks=[], cases=cases, unmatched_tasks=unmatched,
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
        "$utf8 = New-Object System.Text.UTF8Encoding($false); "
        "$OutputEncoding = $utf8; "
        "[Console]::OutputEncoding = $utf8; "
        "$u=$env:MYBARID_CRM_URL; "
        "if ($env:MYBARID_CRM_USER -and $env:MYBARID_CRM_PASS) { "
        "$sec=ConvertTo-SecureString $env:MYBARID_CRM_PASS -AsPlainText -Force; "
        "$cred=New-Object System.Management.Automation.PSCredential("
        "$env:MYBARID_CRM_USER,$sec); "
        "$r=Invoke-WebRequest -Uri $u -Credential $cred "
        "-Headers @{Accept='application/json';'OData-Version'='4.0';"
        "Prefer='odata.include-annotations=\"*\"'} -TimeoutSec 120 "
        "} else { "
        "$r=Invoke-WebRequest -Uri $u -UseDefaultCredentials "
        "-Headers @{Accept='application/json';'OData-Version'='4.0';"
        "Prefer='odata.include-annotations=\"*\"'} -TimeoutSec 120 "
        "}; "
        "$bytes = $r.RawContentStream.ToArray(); "
        "$content = [System.Text.Encoding]::UTF8.GetString($bytes); "
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
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=150,
            env=env, check=False, startupinfo=startupinfo,
            creationflags=creationflags,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CRMClientError(f"ارتباط با CRM برقرار نشد: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise CRMClientError(f"خطا در دریافت اطلاعات CRM: {detail[:700]}")
    raw_response = completed.stdout
    if not isinstance(raw_response, str) or not raw_response.strip():
        detail = (completed.stderr or "").strip()
        suffix = f" جزئیات: {detail[:500]}" if detail else ""
        raise CRMClientError(
            "CRM پاسخ JSON برنگرداند؛ احتمالاً پاسخ خالی، خطای احراز هویت "
            f"یا خطای سرویس است.{suffix}"
        )
    try:
        # Some Dynamics installations return literal control characters inside
        # multiline annotation text.  The response is still structurally JSON;
        # accepting those characters here preserves the Note content.
        payload = json.loads(raw_response, strict=False)
    except json.JSONDecodeError as exc:
        raise CRMClientError("پاسخ CRM قابل خواندن نیست یا احراز هویت Windows موفق نبود.") from exc
    if not isinstance(payload, dict):
        raise CRMClientError("ساختار پاسخ CRM معتبر نیست.")
    return payload


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
        if view.get("returnedtypecode") != "annotation":
            raise CRMClientError("View انتخاب‌شده روی موجودیت Note/annotation نیست.")
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
                if row.get("returnedtypecode") == "annotation" and row.get("name"):
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

    def fetch_view_dataset(self, since: datetime | None = None) -> tuple[Dataset, dict]:
        view = self._get_user_view()
        fetchxml = view.get("fetchxml")
        if not fetchxml:
            raise CRMClientError("View فاقد FetchXML قابل اجرا است.")
        query_fetchxml = _add_modified_since_filter(fetchxml, since) if since else fetchxml
        url = f"{self.api_root}/annotations?fetchXml={quote(query_fetchxml, safe='')}"
        payload = _powershell_get_json(url, self.username, self.password)
        rows = list(payload.get("value") or [])
        # Dataverse may paginate FetchXML results. The first response can
        # contain only a small page even when the selected View has many more
        # records. Follow the server-provided continuation link.
        next_link = payload.get("@odata.nextLink") or payload.get("odata.nextLink")
        page_count = 1
        while next_link and page_count < 1000:
            page_payload = _powershell_get_json(next_link, self.username, self.password)
            rows.extend(page_payload.get("value") or [])
            next_link = page_payload.get("@odata.nextLink") or page_payload.get("odata.nextLink")
            page_count += 1
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
            ))
        cases, unmatched = build_cases(notes, [])
        now = datetime.now().isoformat()
        summary = ValidationSummary(
            file_name=f"CRM View: {self.view_name}",
            sheet_name=self.view_name,
            total_rows=len(rows), usable_rows=len(notes),
            rows_without_date=sum(1 for n in notes if not n.note_date),
            unique_cases=len(cases), incomplete_rows=sum(1 for n in notes if not n.description),
            usable_columns=0, total_columns=0, mapping={}, missing_required_labels=[],
            ambiguous={}, unmatched_headers=[],
            warnings=["داده‌های Task در View TESTNOTE وجود ندارد و در این مرحله خالی است."],
        )
        dataset = Dataset(
            notes=notes, tasks=[], cases=cases, unmatched_tasks=unmatched,
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
        }
