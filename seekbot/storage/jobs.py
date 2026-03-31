from collections import OrderedDict
import csv
import os
import re
import time

from seekbot.domain import ApplicationRecord


CSV_FIELDS = [
    "timestamp",
    "status",
    "reason",
    "url",
    "title",
    "company",
    "location",
    "hr_name",
    "hr_email",
    "hr_phone",
    "external_url",
    "search_url",
    "keyword",
    "role_key",
    "selected_resume_role",
    "resume_path",
    "quick_apply",
    "compatibility_score",
    "compatibility_threshold",
    "matched_keywords",
    "missing_keywords",
    "dry_run",
    "external",
    "job_index",
]

TERMINAL_SKIP_STATUSES = {
        "applied",
        "already_applied",
        "skipped_non_quick",
        "skipped_external",
        "skipped_compatibility",
}

RETRYABLE_FAILURE_STATUSES = {
    "failed_apply",
}


class CsvJobStore:
    def __init__(self, path: str):
        self.path = path
        self.rows: OrderedDict[str, dict] = OrderedDict()
        self._load_existing()

    def _normalize_row(self, row: dict) -> dict:
        normalized = {field: row.get(field, "") for field in CSV_FIELDS}
        url = str(normalized.get("url", "")).strip()
        match = re.search(r"/job/(\d+)", url)
        if match:
            normalized["job_index"] = match.group(1)
        return normalized

    def _row_key(self, row: dict) -> str:
        url = str(row.get("url", "")).strip()
        match = re.search(r"/job/(\d+)", url)
        if match:
            return match.group(1)
        job_id = str(row.get("job_index", "")).strip()
        return job_id or url

    def _lookup_key(self, url_or_job_id: str) -> str:
        value = str(url_or_job_id or "").strip()
        if not value:
            return ""
        if value.isdigit():
            return value
        match = re.search(r"/job/(\d+)", value)
        return match.group(1) if match else value

    def _load_existing(self) -> None:
        if not os.path.exists(self.path):
            return
        total_rows = 0
        with open(self.path, newline="") as handle:
            reader = csv.DictReader(handle)
            for raw_row in reader:
                total_rows += 1
                row = self._normalize_row(raw_row)
                key = self._row_key(row)
                if not key:
                    continue
                if key in self.rows:
                    self.rows.pop(key)
                self.rows[key] = row
        if total_rows != len(self.rows):
            self._write_all()

    def _write_all(self) -> None:
        with open(self.path, "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for row in self.rows.values():
                writer.writerow(self._normalize_row(row))

    def append(self, record: ApplicationRecord) -> None:
        row = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": record.status,
            "reason": record.reason,
            "url": record.url,
            "title": record.title,
            "company": record.company,
            "location": record.location,
            "hr_name": record.contact.name,
            "hr_email": record.contact.email,
            "hr_phone": record.contact.phone,
            "external_url": record.external_url,
            "search_url": record.search_url,
            "keyword": record.keyword,
            "role_key": record.role_key,
            "selected_resume_role": record.selected_resume_role,
            "resume_path": record.resume_path,
            "quick_apply": record.quick_apply,
            "compatibility_score": record.compatibility.score if record.compatibility else None,
            "compatibility_threshold": record.compatibility_threshold,
            "matched_keywords": ", ".join(record.compatibility.matched_keywords if record.compatibility else []),
            "missing_keywords": ", ".join(record.compatibility.missing_keywords if record.compatibility else []),
            "dry_run": record.dry_run,
            "external": record.external,
            "job_index": record.job_index,
        }
        key = self._row_key(row)
        if key:
            if key in self.rows:
                self.rows.pop(key)
            self.rows[key] = row
            self._write_all()

    def get(self, url: str) -> dict | None:
        return self.rows.get(self._lookup_key(url))

    def should_skip(self, url: str) -> bool:
        row = self.get(url)
        return bool(row and row.get("status") in TERMINAL_SKIP_STATUSES)

    def status_summary(self) -> dict[str, int]:
        summary = {"total": len(self.rows), "terminal": 0, "retryable_failed": 0}
        for row in self.rows.values():
            status = str(row.get("status", "")).strip()
            if status in TERMINAL_SKIP_STATUSES:
                summary["terminal"] += 1
            if status in RETRYABLE_FAILURE_STATUSES:
                summary["retryable_failed"] += 1
        return summary
