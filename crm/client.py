"""Read-only Microsoft Dynamics 365 on-premise Web API client.

The client deliberately keeps transport/authentication separate from the analysis
pipeline. Windows authentication uses the current Windows identity through
PowerShell; explicit credentials are supported for environments where the CRM
requires a different Windows account.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass
from urllib.parse import quote


@dataclass
class CRMSettings:
    base_url: str = "https://crm.baridsoft.ir"
    organization_path: str = ""
    api_version: str = "v9.1"
    auth_mode: str = "windows"
    username: str = ""
    password: str = ""
    timeout_seconds: int = 45

    @property
    def api_root(self) -> str:
        base = self.base_url.rstrip("/")
        org = self.organization_path.strip("/")
        suffix = f"/api/data/{self.api_version}/"
        return f"{base}/{org}{suffix}" if org else f"{base}{suffix}"


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class CRMClientError(RuntimeError):
    pass


class CRMClient:
    def __init__(self, settings: CRMSettings):
        self.settings = settings

    def _request(self, url: str) -> dict:
        auth_mode = self.settings.auth_mode.lower().strip()
        credential = "$null"
        if auth_mode == "credentials":
            if not self.settings.username or not self.settings.password:
                raise CRMClientError("نام کاربری و رمز عبور CRM وارد نشده است.")
            credential = (
                f"New-Object System.Management.Automation.PSCredential("
                f"{_ps_quote(self.settings.username)}, "
                f"(ConvertTo-SecureString {_ps_quote(self.settings.password)} -AsPlainText -Force))"
            )
        script = f"""
$ErrorActionPreference = 'Stop'
$u = {_ps_quote(url)}
$headers = @{{ Accept = 'application/json;odata.metadata=minimal' }}
try {{
  if ({' $true ' if auth_mode == 'credentials' else ' $false '}) {{
    $cred = {credential}
    $r = Invoke-RestMethod -Uri $u -Method Get -Headers $headers -Credential $cred -TimeoutSec {int(self.settings.timeout_seconds)}
  }} else {{
    $r = Invoke-RestMethod -Uri $u -Method Get -Headers $headers -UseDefaultCredentials -TimeoutSec {int(self.settings.timeout_seconds)}
  }}
  $r | ConvertTo-Json -Depth 30 -Compress
}} catch {{
  [Console]::Error.WriteLine($_.Exception.Message)
  exit 1
}}
"""
        proc = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True, text=True, timeout=max(10, int(self.settings.timeout_seconds) + 10), encoding="utf-8", errors="replace",
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "پاسخ خالی").strip()
            raise CRMClientError(f"دریافت از CRM ناموفق بود: {detail}")
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise CRMClientError("CRM پاسخ JSON معتبر برنگرداند.") from exc

    def test_connection(self) -> dict:
        return self._request(self.settings.api_root + "WhoAmI")

    def get_views(self) -> list[dict]:
        select = "name,returnedtypecode,savedqueryid,fetchxml,isdefault"
        query = f"savedqueries?$select={select}&$orderby=name"
        result = self._request(self.settings.api_root + query)
        rows = result.get("value", []) if isinstance(result, dict) else []
        return [{
            "id": x.get("savedqueryid"), "name": x.get("name") or "بدون نام",
            "entity": x.get("returnedtypecode"), "fetchxml": x.get("fetchxml"),
            "is_default": bool(x.get("isdefault")), "scope": "سازمانی",
        } for x in rows]

    def fetch_entity_records(self, entity: str, select: list[str], filter_expression: str | None = None) -> list[dict]:
        query = f"{entity}?$select=" + ",".join(select)
        if filter_expression:
            query += "&$filter=" + quote(filter_expression, safe="()_,$=")
        result = self._request(self.settings.api_root + query)
        return result.get("value", []) if isinstance(result, dict) else []

    def fetch_related_activities(self, case_ids: list[str]) -> tuple[list[dict], list[dict]]:
        ids = [x.strip("{}") for x in case_ids if x]
        if not ids:
            return [], []
        notes: list[dict] = []
        tasks: list[dict] = []
        # Dynamics On-Premise may return HTTP 500 for very long OR filters.
        # Keep each request bounded so one large View does not fail as a whole.
        for start in range(0, len(ids), 50):
            chunk = ids[start:start + 50]
            clauses = " or ".join(f"_objectid_value eq {x}" for x in chunk)
            notes.extend(self.fetch_entity_records(
                "annotations",
                ["annotationid", "subject", "notetext", "createdon", "_objectid_value", "_modifiedby_value"],
                clauses,
            ))
            clauses = " or ".join(f"_regardingobjectid_value eq {x}" for x in chunk)
            tasks.extend(self.fetch_entity_records(
                "tasks",
                ["activityid", "subject", "description", "createdon", "actualstart", "scheduledend", "statuscode", "_regardingobjectid_value", "_ownerid_value"],
                clauses,
            ))
        return notes, tasks
    def fetch_view(self, view: dict) -> list[dict]:
        fetchxml = view.get("fetchxml")
        if not fetchxml:
            raise CRMClientError("View انتخاب‌شده FetchXML ندارد.")
        match = re.search(r"<entity\\s+name=['\"]([^'\"]+)", fetchxml, re.I)
        if not match:
            raise CRMClientError("نام موجودیت View از FetchXML قابل تشخیص نیست.")
        entity = match.group(1)
        url = self.settings.api_root + entity + "?fetchXml=" + quote(fetchxml, safe="")
        result = self._request(url)
        return result.get("value", []) if isinstance(result, dict) else []


def settings_from_dict(payload: dict | None) -> CRMSettings:
    payload = payload or {}
    base = asdict(CRMSettings())
    for key in base:
        if key in payload and payload[key] is not None:
            base[key] = payload[key]
    base["timeout_seconds"] = int(base["timeout_seconds"])
    return CRMSettings(**base)
