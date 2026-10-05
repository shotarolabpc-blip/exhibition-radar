"""汎用会場カレンダー。ページ本文をそのまま Gemini に渡して全項目を抽出させる（構造が不明確なサイト向け）。

sources.yaml の設定：
  url: 一覧ページ
  extra_urls: [追加で読むページ（翌月分など）]
  venue: 会場名（Geminiへのヒント兼、会場が書かれていない場合の既定値）
会場カレンダーはIT以外のイベントが混在するため、キーワード一次判定は行わない（skip_keyword_filter）。
"""

from __future__ import annotations

from typing import Any

from collector.date_range import DateRange
from collector.fetcher import Fetcher, html_to_text
from collector.sources.base import CandidatePage, SourceResult


class Parser:
    source_type = "venue"
    label = "展示会場HP"
    skip_keyword_filter = True

    def __init__(self, source: dict[str, Any], fetcher: Fetcher, context: dict[str, Any]) -> None:
        self.source = source
        self.fetcher = fetcher
        self.max_chars = int(context.get("max_input_chars", 12000))

    def collect(self, period: DateRange) -> SourceResult:
        result = SourceResult()
        for url in [self.source["url"], *(self.source.get("extra_urls") or [])]:
            res = self.fetcher.get(url)
            if not res.ok:
                result.errors.append(f"{self.source['id']}: {res.error} ({url})")
                continue
            if "pdf" in res.content_type.lower():
                title, text = url, res.text[: self.max_chars]
            else:
                title, text = html_to_text(res.text, self.max_chars)
            if not text.strip():
                result.errors.append(f"{self.source['id']}: 本文が空（JavaScript描画の可能性）({url})")
                continue
            result.pages.append(
                CandidatePage(
                    url=res.final_url or url,
                    title=title,
                    text=text,
                    source_id=self.source["id"],
                    source_name=f"{self.label}：{self.source['name']}",
                    source_type=self.source_type,
                    venue_hint=self.source.get("venue", ""),
                    skip_keyword_filter=self.skip_keyword_filter,
                )
            )
        return result
