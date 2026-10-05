"""Eventデータモデル（events.json の1要素）。"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import asdict, dataclass, field, fields
from datetime import date
from typing import Any

DATE_STATUSES = ("fixed", "tentative", "unknown")
STATUSES = ("new", "updated", "unchanged", "needs_review", "excluded")

STATUS_LABELS = {
    "new": "新規",
    "updated": "更新",
    "unchanged": "変更なし",
    "needs_review": "要確認",
    "excluded": "除外",
}

SOURCE_TYPES = ("organizer", "venue", "jmesse", "known_url", "import")

# 差分判定の対象項目（6.4：日付/会場/URL/概要）
TRACKED_FIELDS = ("start_date", "end_date", "date_status", "venue", "url", "summary")


@dataclass
class Event:
    id: str
    event_name: str
    parent_event_name: str
    sub_event_name: str = ""
    start_date: str = ""
    end_date: str = ""
    date_status: str = "unknown"
    venue: str = ""
    prefecture: str = ""
    region: str = ""
    categories: list[str] = field(default_factory=list)
    summary: str = ""
    url: str = ""
    source: str = ""
    source_type: str = ""
    keywords: list[str] = field(default_factory=list)
    confidence: int = 0
    reason: str = ""
    status: str = "new"
    first_seen: str = ""
    last_updated: str = ""
    last_checked: str = ""
    year: str = ""
    history: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Event:
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})

    def add_history(self, day: str, change: str) -> None:
        self.history.append({"date": day, "change": change})


def _id_key(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    return re.sub(r"[\s\-‐―－–—・/／|｜:：()（）\[\]【】「」『』'\"]+", "", text)


def make_event_id(parent: str, sub: str, year: str, venue: str = "") -> str:
    """parent_event_name + sub_event_name + 開催年 の正規化文字列のハッシュ（先頭8桁）。

    日付を含めないため、日程未定→確定でも同一IDを維持する（6.3）。
    開催年が不明な場合は "unknown" を使う（そのイベントは needs_review 扱い）。
    同名・同年で別会場の回（例：東京展と大阪展）と衝突した場合のみ venue を加えて区別する。
    """
    key = f"{_id_key(parent)}|{_id_key(sub)}|{year or 'unknown'}"
    if venue:
        key += f"|{_id_key(venue)}"
    return "evt_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]


def is_same_edition(a: Event, b: Event, max_gap_days: int = 31) -> bool:
    """同一IDの2件が同じ開催回か。会場が異なる、または開始日が大きく離れていれば別の回。"""
    if a.venue and b.venue and _id_key(a.venue) != _id_key(b.venue):
        return False
    if a.start_date and b.start_date:
        gap = abs((date.fromisoformat(a.start_date) - date.fromisoformat(b.start_date)).days)
        return gap <= max_gap_days
    return True


def edition_id(event: Event) -> str:
    """衝突回避用の会場付きID。"""
    return make_event_id(event.parent_event_name, event.sub_event_name, event.year, event.venue or event.start_date)


def compose_event_name(parent: str, sub: str) -> str:
    """`総合展名 - 構成展名`。構成展が無い/総合展名と同じなら総合展名のみ。"""
    parent = parent.strip()
    sub = sub.strip()
    if not sub or _id_key(sub) == _id_key(parent):
        return parent
    if not parent:
        return sub
    return f"{parent} - {sub}"
