from __future__ import annotations

import csv


def export_csv(path: str, headers: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # BOM برای نمایش صحیح فارسی در Excel
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
