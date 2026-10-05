"""events.json / events.csv / events_detail.csv / runs.json の出力（C-09）とアーカイブ。

CSV共通仕様（3.3.3）：UTF-8 BOM付き、CRLF、全フィールドをダブルクォート。
列構成は docs/assets/csv.js と一致させること。
"""

from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from collector.models import STATUS_LABELS, Event
from collector.normalizer import format_date_slash

EXCEL_COLUMNS = ["No", "イベント名", "開始日", "終了日", "会場", "SA部アサイン", "コムシスアサイン", "対応カテゴリ", "概要", "URL"]
DETAIL_COLUMNS = EXCEL_COLUMNS + [
    "総合展名",
    "構成展名",
    "都道府県",
    "地方区分",
    "ステータス",
    "信頼度",
    "収集元",
    "検出キーワード",
    "判定理由",
    "初回検出日",
    "最終更新日",
    "イベントID",
]


def sort_key(e: Event) -> tuple[int, str, str]:
    """開始日昇順。日程未定は末尾。"""
    return (0 if e.start_date else 1, e.start_date or "9999", e.event_name)


def excel_row(e: Event) -> list[str]:
    return [
        "",  # No：本番Excel側で採番
        e.event_name,
        format_date_slash(e.start_date),
        format_date_slash(e.end_date),
        e.venue,
        "",  # SA部アサイン：ツールでは扱わない
        "",  # コムシスアサイン：ツールでは扱わない
        "・".join(e.categories),
        e.summary,
        e.url,
    ]


def detail_row(e: Event) -> list[str]:
    return excel_row(e) + [
        e.parent_event_name,
        e.sub_event_name,
        e.prefecture,
        e.region,
        STATUS_LABELS.get(e.status, e.status),
        str(e.confidence),
        e.source,
        "・".join(e.keywords),
        e.reason,
        format_date_slash(e.first_seen),
        format_date_slash(e.last_updated),
        e.id,
    ]


def publishable(events: list[Event]) -> list[Event]:
    """Web・CSVに出す対象（excluded以外）を開始日順で返す。"""
    return sorted((e for e in events if e.status != "excluded"), key=sort_key)


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
        writer.writerow(header)
        writer.writerows(rows)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_events(path: Path) -> list[Event]:
    return [Event.from_dict(d) for d in read_json(path, [])]


def write_events(events: list[Event], data_dir: Path) -> None:
    """events.json（excludedも保持＝再検出防止）と CSV 2種を出力する。"""
    write_json(data_dir / "events.json", [e.to_dict() for e in sorted(events, key=sort_key)])
    pub = publishable(events)
    write_csv(data_dir / "events.csv", EXCEL_COLUMNS, [excel_row(e) for e in pub])
    write_csv(data_dir / "events_detail.csv", DETAIL_COLUMNS, [detail_row(e) for e in pub])


def append_run(data_dir: Path, run: dict[str, Any], keep: int) -> None:
    path = data_dir / "runs.json"
    runs = read_json(path, [])
    runs.insert(0, run)
    write_json(path, runs[:keep])


def archive_events(events: list[Event], today: date, after_days: int, archive_dir: Path) -> list[Event]:
    """終了日（無ければ開始日）が today - after_days より前のイベントを archive/{年}.json へ移す。"""
    limit = (today - timedelta(days=after_days)).isoformat()
    remaining: list[Event] = []
    archived: dict[str, list[Event]] = {}
    for e in events:
        last = e.end_date or e.start_date
        if last and last < limit:
            archived.setdefault(last[:4], []).append(e)
        else:
            remaining.append(e)
    for year, items in archived.items():
        path = archive_dir / f"{year}.json"
        existing = {d["id"]: d for d in read_json(path, [])}
        for e in items:
            existing[e.id] = e.to_dict()
        write_json(path, sorted(existing.values(), key=lambda d: (d.get("start_date") or "", d["id"])))
    return remaining
