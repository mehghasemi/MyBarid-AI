"""Normalized records supplied by the CRM data source."""
from dataclasses import dataclass
from datetime import datetime


@dataclass
class NoteRecord:
    note_id: str | None
    description: str
    case_number: str | None
    case_title: str | None
    customer: str | None
    owner: str | None
    service: str | None
    case_status: str | None
    case_status_reason: str | None
    case_created_on: datetime | None
    case_created_by: str | None
    note_date: datetime | None
    note_author: str | None
    assign_to: str | None
    incident_type: str | None
    case_description: str | None
    scenario: str | None

    @property
    def case_key(self) -> str | None:
        return self.case_number or (f"title::{self.case_title}" if self.case_title else None)

    @property
    def is_customer_authored(self) -> bool:
        author = (self.note_author or "").strip().casefold()
        return author in {"portal portal", "customer portal"}


@dataclass
class TaskRecord:
    task_id: str | None
    subject: str | None
    description: str | None
    case_number: str | None
    regarding: str | None
    created_by: str | None
    created_on: datetime | None
    actual_start: datetime | None
    due_date: datetime | None
    status_reason: str | None
    follow_up_needed: str | None
    next_follow_up: datetime | None
    work_type: str | None
    assign_to: str | None

    @property
    def case_key_hint(self) -> str | None:
        return self.case_number or (f"title::{self.regarding}" if self.regarding else None)
