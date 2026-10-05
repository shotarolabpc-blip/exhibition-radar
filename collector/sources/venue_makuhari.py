"""幕張メッセ イベントカレンダー（/event/?month=YYYYMM&page=N）。

一覧の li.eventInr に カテゴリ・会期・名称・詳細ページURL がある。
公式URLは詳細ページにしか無いため、キーワード判定を通過したイベントのみ詳細ページを取得する（resolve_url）。
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from collector.date_range import DateRange
from collector.fetcher import Fetcher
from collector.normalizer import clean_text, normalize_url, parse_dates
from collector.sources.base import RawEvent, SourceResult

DEFAULT_CATEGORIES = ["展示会・見本市"]


def months_in(period: DateRange) -> list[str]:
    months: list[str] = []
    y, m = period.start.year, period.start.month
    while (y, m) <= (period.end.year, period.end.month):
        months.append(f"{y}{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return months


def parse_list(html: str, source: dict[str, Any], base_url: str, categories: list[str]) -> tuple[list[RawEvent], int]:
    """(イベント, 最大ページ番号) を返す。"""
    soup = BeautifulSoup(html, "lxml")
    events: list[RawEvent] = []
    for li in soup.select("li.eventInr"):
        a = li.find("a", href=True)
        cat = clean_text(li.select_one(".category").get_text(" ")) if li.select_one(".category") else ""
        title_el = li.select_one(".eventTit")
        date_el = li.select_one(".date")
        if a is None or title_el is None or date_el is None:
            continue
        if categories and cat not in categories:
            continue
        parsed = parse_dates(date_el.get_text(" "))
        if parsed.start is None:
            continue
        events.append(
            RawEvent(
                name=clean_text(title_el.get_text(" ")),
                start_date=parsed.start.isoformat(),
                end_date=(parsed.end or parsed.start).isoformat(),
                date_status=parsed.status,
                venue=source.get("venue", "幕張メッセ"),
                url="",
                description=urljoin(base_url, a["href"]),  # 詳細ページURL（resolve_urlで公式URLに置換）
                source_id=source["id"],
                source_name=f"展示会場HP：{source['name']}",
                source_type="venue",
                reason=f"会場公式のイベントカレンダーに掲載（{cat}）",
                confidence=90,
            )
        )
    pages = [int(p) for p in re.findall(r"pager\((\d+)\)", html)]
    return events, max(pages, default=1)


def parse_detail(html: str, page_url: str) -> tuple[str, str]:
    """詳細ページから (公式URL, 説明文) を返す。会場の広告リンク（utm_source=venue-site）や会場自身へのリンクは除く。"""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "header", "footer", "nav"]):
        tag.decompose()
    own_host = urlsplit(page_url).netloc
    official = ""
    for row_label in soup.find_all(["dt", "th"]):
        if re.search(r"URL|ホームページ|公式|ウェブサイト|Web", row_label.get_text(), re.IGNORECASE):
            cell = row_label.find_next_sibling(["dd", "td"])
            link = cell.find("a", href=True) if cell else None
            if link:
                official = link["href"]
                break
    if not official:
        for link in soup.find_all("a", href=True):
            href = link["href"]
            host = urlsplit(href).netloc
            if href.startswith("http") and host != own_host and "venue-site" not in href and "ccb.or.jp" not in host:
                official = href
                break
    desc = ""
    for p in soup.find_all("p"):
        text = clean_text(p.get_text(" "))
        if len(text) >= 30:
            desc = text
            break
    return normalize_url(official), desc[:400]


class Parser:
    def __init__(self, source: dict[str, Any], fetcher: Fetcher, context: dict[str, Any]) -> None:
        self.source = source
        self.fetcher = fetcher
        self.max_pages = int(context.get("max_pages_per_source", 100))
        self.categories = source.get("categories", DEFAULT_CATEGORIES)

    def collect(self, period: DateRange) -> SourceResult:
        result = SourceResult()
        seen: set[str] = set()
        fetched = 0
        for month in months_in(period):
            page, last = 1, 1
            while page <= last and fetched < self.max_pages:
                res = self.fetcher.get(self.source["url"], params={"month": month, "page": page})
                fetched += 1
                if not res.ok:
                    result.errors.append(f"{self.source['id']}: {res.error} (month={month}, page={page})")
                    break
                events, last = parse_list(res.text, self.source, res.final_url or self.source["url"], self.categories)
                for e in events:
                    key = e.description
                    if key in seen:
                        continue
                    seen.add(key)
                    if period.overlaps(date.fromisoformat(e.start_date), date.fromisoformat(e.end_date)):
                        result.events.append(e)
                page += 1
        return result

    def resolve_url(self, event: RawEvent) -> None:
        """詳細ページを取得して公式URLと説明文を埋める（キーワード判定通過後に main から呼ばれる）。"""
        detail_url = event.description
        if not detail_url.startswith("http"):
            return
        res = self.fetcher.get(detail_url)
        if res.ok:
            event.url, event.description = parse_detail(res.text, res.final_url or detail_url)
        if not event.url:
            event.url = detail_url
