"""既知イベントURL巡回（config/known_urls.yaml）。

既存リストの公式ページを巡回し、次回開催の情報や日程変更を拾う。
- 1回の実行で巡回するのは max_urls_per_run 件まで。前回確認が古い順に回す（ローテーション）
- 本文のハッシュを data/page_state.json と比べ、前回 Gemini に送った時から変化したページだけを候補にする
- 現在掲載中でないイベント（過去回）のURLは「次回開催の発見」を優先して高い優先度にする
"""

from __future__ import annotations

import hashlib
from typing import Any

from collector.date_range import DateRange
from collector.fetcher import Fetcher, html_to_text
from collector.normalizer import url_key
from collector.sources.base import CandidatePage, SourceResult


def text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


class Parser:
    def __init__(self, source: dict[str, Any], fetcher: Fetcher, context: dict[str, Any]) -> None:
        self.source = source
        self.fetcher = fetcher
        self.max_chars = int(context.get("max_input_chars", 12000))
        self.urls: list[dict[str, str]] = context.get("known_urls", [])
        self.page_state: dict[str, dict[str, str]] = context.get("page_state", {})
        self.live_url_keys: set[str] = context.get("live_url_keys", set())
        self.max_urls = int(source.get("max_urls_per_run", 200))

    def ordered_urls(self) -> list[dict[str, str]]:
        def key(item: dict[str, str]) -> tuple[str, str]:
            return (self.page_state.get(item["url"], {}).get("checked", ""), item["url"])

        return sorted(self.urls, key=key)[: self.max_urls]

    def collect(self, period: DateRange) -> SourceResult:
        result = SourceResult()
        for item in self.ordered_urls():
            url = item["url"]
            res = self.fetcher.get(url)
            state = self.page_state.setdefault(url, {})
            state["checked"] = period.start.isoformat()
            if not res.ok:
                state["error"] = res.error
                continue  # 個別URLの失敗は収集元エラーにしない（過年度ページの404が多いため）
            state.pop("error", None)
            if "pdf" in res.content_type.lower():
                title, text = item.get("name", url), res.text[: self.max_chars]
            else:
                title, text = html_to_text(res.text, self.max_chars)
            digest = text_hash(text)
            if not text.strip() or state.get("hash") == digest:
                continue
            result.pages.append(
                CandidatePage(
                    url=res.final_url or url,
                    title=title or item.get("name", ""),
                    text=text,
                    source_id=self.source["id"],
                    source_name=f"主催者HP（既知URL）：{item.get('name') or title}",
                    source_type="known_url",
                    content_hash=digest,
                    priority=1 if url_key(url) in self.live_url_keys else 2,
                )
            )
        return result
