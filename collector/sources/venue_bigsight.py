"""東京ビッグサイト イベント情報（/visitor/event/search.php?page=N）。

1件ごとに article.lyt-event-01 があり、見出し（名称＋公式URL）・説明・dl（開催期間・URL・利用施設）を持つ。
"""

from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from collector.date_range import DateRange
from collector.fetcher import Fetcher
from collector.normalizer import clean_text, parse_dates
from collector.sources.base import RawEvent, SourceResult


def _dl_values(article: Tag) -> dict[str, Tag]:
    values: dict[str, Tag] = {}
    for dt in article.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if dd is not None:
            values[clean_text(dt.get_text())] = dd
    return values


def parse_list(html: str, source: dict[str, Any], base_url: str) -> list[RawEvent]:
    soup = BeautifulSoup(html, "lxml")
    events: list[RawEvent] = []
    for article in soup.select("article.lyt-event-01"):
        for svg in article.find_all("svg"):  # リンクアイコンの「新規タブで開きます」を除く
            svg.decompose()
        heading = article.find(["h3", "h2"])
        if heading is None:
            continue
        name = clean_text(heading.get_text(" "))
        link = heading.find("a", href=True)
        desc_el = article.find("p")
        dl = _dl_values(article)
        url_dd = dl.get("URL")
        url_a = url_dd.find("a", href=True) if url_dd else None
        url = (url_a or link)["href"] if (url_a or link) else ""
        parsed = parse_dates(dl["開催期間"].get_text(" ")) if "開催期間" in dl else None
        if not name or parsed is None or parsed.start is None:
            continue
        hall = clean_text(dl["利用施設"].get_text(" ")) if "利用施設" in dl else ""
        events.append(
            RawEvent(
                name=name,
                start_date=parsed.start.isoformat(),
                end_date=(parsed.end or parsed.start).isoformat(),
                date_status=parsed.status,
                venue=source.get("venue", "東京ビッグサイト"),
                url=urljoin(base_url, url) if url else "",
                description=clean_text(desc_el.get_text(" ")) if desc_el else "",
                source_id=source["id"],
                source_name=f"展示会場HP：{source['name']}",
                source_type="venue",
                reason=f"会場公式のイベント一覧に掲載（{hall}）" if hall else "会場公式のイベント一覧に掲載",
                confidence=90,
            )
        )
    return events


class Parser:
    def __init__(self, source: dict[str, Any], fetcher: Fetcher, context: dict[str, Any]) -> None:
        self.source = source
        self.fetcher = fetcher
        self.max_pages = int(context.get("max_pages_per_source", 100))

    def collect(self, period: DateRange) -> SourceResult:
        result = SourceResult()
        list_url = self.source.get("list_url") or urljoin(self.source["url"], "search.php")
        for page in range(1, self.max_pages + 1):
            res = self.fetcher.get(list_url, params={"page": page})
            if not res.ok:
                result.errors.append(f"{self.source['id']}: {res.error} ({list_url}?page={page})")
                break
            events = parse_list(res.text, self.source, res.final_url or list_url)
            if not events:
                break
            result.events.extend(e for e in events if period.overlaps(_d(e.start_date), _d(e.end_date)))
            if all(e.start_date > period.end.isoformat() for e in events):
                break
        return result


def _d(iso: str) -> date | None:
    return date.fromisoformat(iso) if iso else None
