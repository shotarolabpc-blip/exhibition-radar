"""収集元パーサーの共通インターフェース。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from collector.date_range import DateRange
from collector.fetcher import Fetcher

# 収集元の優先度（同一イベントで値が食い違う場合、高い方を採用）：主催者公式HP ＞ 展示会場HP ＞ J-messe
SOURCE_PRIORITY = {"organizer": 4, "known_url": 4, "venue": 3, "jmesse": 2, "import": 1}


@dataclass
class CandidatePage:
    """Gemini に渡す候補ページ（構造が不明確なサイト向け）。"""

    url: str
    title: str
    text: str
    source_id: str
    source_name: str
    source_type: str
    venue_hint: str = ""
    skip_keyword_filter: bool = False
    content_hash: str = ""
    priority: int = 0  # 大きいほど先に Gemini へ送る


@dataclass
class RawEvent:
    """構造化サイトから直接抽出したイベント（Geminiは概要・カテゴリ付与のみに使う）。"""

    name: str
    start_date: str
    end_date: str
    venue: str
    url: str
    description: str
    source_id: str
    source_name: str
    source_type: str
    date_status: str = "fixed"
    parent_event_name: str = ""
    sub_event_name: str = ""
    categories: list[str] = field(default_factory=list)
    summary: str = ""
    confidence: int = 0
    reason: str = ""
    keywords: list[str] = field(default_factory=list)


@dataclass
class SourceResult:
    pages: list[CandidatePage] = field(default_factory=list)
    events: list[RawEvent] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class SourceParser(Protocol):
    def __init__(self, source: dict[str, Any], fetcher: Fetcher, context: dict[str, Any]) -> None: ...

    def collect(self, period: DateRange) -> SourceResult:
        """候補ページ（URL、タイトル、本文抜粋、取得元）または構造化済みイベントを返す。"""
        ...


class DisabledSource:
    """構造変更などで現在は対応していない収集元。sources.yaml で enabled: false にしておく。"""

    reason = "未対応"

    def __init__(self, source: dict[str, Any], fetcher: Fetcher, context: dict[str, Any]) -> None:
        self.source = source

    def collect(self, period: DateRange) -> SourceResult:
        return SourceResult(errors=[f"{self.source.get('id')}: {self.reason}"])
